# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.monitoring import Monitoring
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.projects import Projects
from spikes.reporting import operation_uuid
from spikes.rss_monitoring import RSSMonitoring
from spikes.rss_reader import fetch_response,RSSUnavailable
from spikes.public_source import HTTPResult,PublicSourceUnknown
from tests import test_reporting as fixtures
from tests.test_monitoring_definitions import definition
from tests.test_rss_pilot import rss


class RSSConditionalTests(unittest.TestCase):
    def test_connector_exposes_304_as_not_modified_instead_of_empty_feed(self):
        from spikes.source_connectors import RSSConnector,SourceContext
        ctx=SourceContext('rss','https://example.test/feed','2026-11-06T17:00:00Z','public','test-only')
        with patch('spikes.source_connectors.fetch_response',return_value=dict(status=304,raw=None,validators={'if-none-match':'"one"'})):
            result=RSSConnector().read(dict(url=ctx.locator),ctx,continuation=dict(validators={'if-none-match':'"one"'}))
        self.assertTrue(result['not_modified']);self.assertEqual(result['items'],[])
        self.assertEqual(result['continuation']['validators']['if-none-match'],'"one"')

    def test_conditional_get_304_preserves_missing_validators(self):
        calls=[]
        def transport(url,headers):
            calls.append((url,dict(headers)))
            if url.endswith('robots.txt'):return HTTPResult(200,{'content-type':'text/plain'},b'User-agent: *\nAllow: /',url)
            return HTTPResult(304,{'etag':'"next"'},b'',url)
        result=fetch_response('https://example.test/feed',validators={'if-none-match':'"old"','if-modified-since':'Wed, 01 Apr 2026 00:00:00 GMT'},transport=transport)
        self.assertEqual(result['status'],304);self.assertIsNone(result['raw'])
        self.assertEqual(result['validators']['if-none-match'],'"next"')
        self.assertIn('if-modified-since',result['validators'])
        self.assertEqual(calls[0][1],{})
        self.assertEqual(calls[1][1]['if-none-match'],'"old"')

    def test_validator_header_injection_rejected_before_network(self):
        with self.assertRaisesRegex(ValidationError,'validator'):
            fetch_response('https://example.test/feed',validators={'if-none-match':'x\r\nAuthorization: secret'},transport=lambda *a:self.fail('network'))


class RSSMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.now=[time.time()];self.calls=[];self.body=rss();self.response=None
        self.definitions=MonitoringDefinitions(self.f.node);self.value=definition()
        self.watch=str(uuid4())
        self.saved=self.definitions.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=self.watch,
            previous=[],privacy='project',definition=self.value),str(uuid4()))
        def fetcher(url,*,validators):
            self.calls.append((url,deepcopy(validators)))
            if isinstance(self.response,Exception):raise self.response
            return self.response or dict(status=200,raw=self.body,validators={'if-none-match':'"one"'})
        self.fetcher=fetcher
        self.runtime=RSSMonitoring(self.f.node,clock=lambda:self.now[0],fetcher=fetcher)
        self.config=dict(project_id=self.f.project,watch_id=self.watch,input_id=self.value['inputs'][0]['id'],
            definition_ref=self.saved['definition_ref'],enabled=True,mode='queue-all')
        self.runtime.configure(self.config,confirm=True)

    def status(self):return self.runtime.status(self.f.project)
    def findings(self):return self.status()['findings']
    def advance(self):self.now[0]+=901

    def test_15_minute_collection_is_independent_of_daily_output_and_never_calls_llm(self):
        with patch('spikes.ollama_backend.OllamaAdapter.dispatch',side_effect=AssertionError('LLM called')):
            self.runtime.tick(self.f.project)
            self.runtime.tick(self.f.project)
        self.assertEqual(len(self.calls),1)
        records=self.findings();self.assertEqual(len(records),1)
        self.assertEqual(records[0]['provenance']['method'],'import')
        meta=json.loads(self.f.git.snapshot(self.f.git.head())[f"artifacts/{records[0]['revision_id']}/metadata.json"])
        self.assertEqual(meta['provenance'],'external')
        finding=records[0]['value'];self.assertEqual(finding['stage'],'pending')
        self.assertEqual(finding['selection']['decision'],'selected')
        self.assertIn('include-all',finding['selection']['filter_revision'])
        self.assertIsNotNone(finding['item']['imported_at'])
        self.assertEqual(finding['raw_ref']['sha256'],finding['item']['provenance']['raw_sha256'])
        self.assertFalse(any(r['type']=='ReportSnapshot' for r in self.f.service.read(self.f.project)['records']))
        self.assertEqual(self.status()['bindings'][0]['interval'],900)
        self.assertEqual(self.definitions.read(self.f.project)['definitions'][0]['runtime_state'],'collection-configured')
        self.assertEqual(self.value['schedule']['kind'],'daily')

    def test_restart_deduplicates_and_304_advances_only_poll_state(self):
        self.runtime.tick(self.f.project);head=self.f.git.head()
        restarted=RSSMonitoring(self.f.node,clock=lambda:self.now[0],fetcher=self.fetcher)
        self.advance();restarted.tick(self.f.project)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[1][1],{'if-none-match':'"one"'})
        self.assertEqual(len(self.findings()),1);self.assertEqual(self.f.git.head(),head)
        self.response=dict(status=304,raw=None,validators={'if-none-match':'"one"'})
        self.advance();restarted.tick(self.f.project)
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual({p['state'] for p in self.status()['polls']},{'completed'})
        self.assertEqual(self.findings()[0]['value']['stage'],'pending')

    def test_correction_preserves_history_aliases_and_processed_repeat_is_not_requeued(self):
        self.runtime.tick(self.f.project);first=self.findings()[0]
        pin=self.f.service.pin(self.f.project,first['revision_id'])
        operation=str(uuid4())
        receipt=self.runtime.transition(self.f.project,pin,'processed','Reviewed processing result',operation,confirm=True)
        self.assertEqual(self.runtime.transition(self.f.project,pin,'processed','Reviewed processing result',operation,confirm=True),receipt)
        with self.assertRaisesRegex(ValidationError,'another finding transition'):
            self.runtime.transition(self.f.project,pin,'discarded','Different request',operation,confirm=True)
        head=self.f.git.head();self.advance();self.runtime.tick(self.f.project)
        self.assertEqual(self.f.git.head(),head);self.assertEqual(self.findings()[0]['value']['stage'],'processed')
        self.body=rss(title='Correction',identifier='changed-id');self.advance();self.runtime.tick(self.f.project)
        current=self.findings()[0]
        self.assertEqual(current['entity_id'],first['entity_id']);self.assertEqual(current['value']['stage'],'pending')
        self.assertEqual(current['value']['item']['imported_at'],first['value']['item']['imported_at'])
        self.assertEqual(current['value']['item']['discovered_at'],first['value']['item']['discovered_at'])
        self.assertIn('id:one',current['value']['aliases']);self.assertIn('id:changed-id',current['value']['aliases'])
        self.assertEqual(self.f.record(pin),first)

    def test_capture_only_state_and_explicit_discard_reason_survive_restart(self):
        self.config['mode']='capture-only';self.runtime.configure(self.config,confirm=True)
        self.runtime.tick(self.f.project);finding=self.findings()[0]
        self.assertEqual(finding['value']['stage'],'captured')
        self.assertEqual(finding['value']['selection']['decision'],'not-evaluated')
        pin=self.f.service.pin(self.f.project,finding['revision_id'])
        self.runtime.transition(self.f.project,pin,'discarded','Outside selected topic',str(uuid4()),confirm=True)
        restarted=RSSMonitoring(self.f.node,clock=lambda:self.now[0],fetcher=self.fetcher)
        result=restarted.status(self.f.project)['findings'][0]
        self.assertEqual(result['value']['stage'],'discarded')
        self.assertEqual(result['value']['selection']['reason'],'Outside selected topic')

    def test_failed_feed_is_not_empty_success_and_cursor_is_not_advanced(self):
        self.runtime.tick(self.f.project);success=self.status()['bindings'][0]['last_success']
        self.response=OSError('offline');self.advance();self.runtime.tick(self.f.project)
        self.assertEqual(len(self.findings()),1)
        self.assertEqual(self.status()['bindings'][0]['last_success'],success)
        self.assertIn('offline',self.status()['bindings'][0]['last_error'])
        self.assertEqual(self.status()['polls'][-1]['state'],'failed')
        self.assertEqual(self.calls[-1][1],{'if-none-match':'"one"'})

    def test_unknown_dispatch_blocks_future_slots_until_explicit_reconciliation(self):
        self.response=PublicSourceUnknown('interrupted')
        self.runtime.tick(self.f.project);self.advance();self.runtime.tick(self.f.project)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.findings(),[])
        poll=self.status()['polls'][0]
        self.assertEqual(poll['state'],'unknown')
        with self.assertRaises(ValidationError):self.runtime.reconcile(self.f.project,poll['id'])
        self.runtime.reconcile(self.f.project,poll['id'],confirm=True)
        self.response=None;self.advance();self.runtime.tick(self.f.project)
        self.assertEqual(len(self.calls),2);self.assertEqual(len(self.findings()),1)

    def test_changed_or_paused_definition_stops_network_and_binding_can_be_disabled(self):
        changed=deepcopy(self.value);changed['active']=False
        self.definitions.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=self.watch,
            previous=[self.saved['definition_ref']],privacy='project',definition=changed),str(uuid4()))
        self.runtime.tick(self.f.project);self.assertEqual(self.calls,[])
        self.config['enabled']=False
        self.assertFalse(self.runtime.configure(self.config,confirm=True)['enabled'])

    def test_backend_tick_uses_same_rss_worker_without_starting_another_daemon(self):
        monitoring=Monitoring(self.f.node,Projects(self.f.node),clock=lambda:self.now[0])
        monitoring._rss_runtime=self.runtime;monitoring.tick(self.f.project)
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.findings()),1)

    def test_second_worker_cannot_recover_or_repeat_a_live_dispatch(self):
        second=RSSMonitoring(self.f.node,clock=lambda:self.now[0],fetcher=lambda *a,**kw:self.fail('duplicate worker GET'))
        def fetcher(url,**kwargs):
            second.tick(self.f.project)
            self.calls.append(url)
            return dict(status=200,raw=self.body,validators={})
        self.runtime.fetcher=fetcher;self.runtime.tick(self.f.project)
        self.assertEqual(len(self.calls),1)
        self.assertEqual([p['state'] for p in self.status()['polls']],['completed'])

    def test_distinct_native_items_with_same_content_are_not_merged(self):
        self.body=rss().replace(b'</channel>',b'<item><guid>two</guid><title>First</title><link>https://example.test/two</link><description>&lt;b&gt;inert&lt;/b&gt;</description></item></channel>')
        self.runtime.tick(self.f.project)
        findings=self.findings();self.assertEqual(len(findings),2)
        self.assertEqual(len({r['value']['item']['content_sha256'] for r in findings}),1)

    def test_origin_backoff_also_blocks_another_watch_on_the_same_origin(self):
        value=definition('Second watch');watch=str(uuid4())
        saved=self.definitions.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=watch,
            previous=[],privacy='project',definition=value),str(uuid4()))
        self.runtime.configure(dict(self.config,watch_id=watch,input_id=value['inputs'][0]['id'],definition_ref=saved['definition_ref']),confirm=True)
        self.response=RSSUnavailable('rate limit');self.response.retry_after='3600'
        self.runtime.tick(self.f.project)
        self.assertEqual(len(self.calls),1)
        self.assertTrue(all(b['next_due']>=self.now[0]+3600 for b in self.status()['bindings']))

    def test_stale_publication_preserves_foreign_edit_and_requires_reconciliation(self):
        def interrupt(stage):
            if stage=='rss-plan':raise OSError('interrupted')
        self.runtime.tick(self.f.project,checkpoint=interrupt)
        from spikes.artifacts import Artifacts
        Artifacts(self.f.node).save(dict(project_id=self.f.project,artifact_id=str(uuid4()),base_head=self.f.git.head(),
            title='Foreign work',body='Keep this edit',new=True),str(uuid4()))
        head=self.f.git.head();self.runtime.tick(self.f.project)
        self.assertEqual(self.f.git.head(),head);self.assertEqual(self.findings(),[])
        self.assertEqual(len(self.calls),1)
        poll=self.status()['polls'][0];self.assertEqual(poll['state'],'publishing')
        self.assertEqual(self.runtime.reconcile(self.f.project,poll['id'],confirm=True)['state'],'cancelled')
        self.assertEqual(self.f.git.head(),head)

    def test_process_crash_during_dispatch_recovers_unknown_without_another_get(self):
        script='''
import os,sys
from spikes.rss_monitoring import RSSMonitoring
def fetcher(*args,**kwargs):os._exit(73)
RSSMonitoring(sys.argv[1],clock=lambda:float(sys.argv[3]),fetcher=fetcher).tick(sys.argv[2])
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.f.node),self.f.project,str(self.now[0])],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,73,result.stderr)
        self.runtime.tick(self.f.project)
        self.assertEqual(self.calls,[]);self.assertEqual(self.status()['polls'][0]['state'],'unknown')

    def test_fetched_capture_recovery_uses_no_second_get_after_process_crash(self):
        # Actual process exits at each boundary; parent resumes the same journal.
        script='''
import os,sys
from spikes.rss_monitoring import RSSMonitoring
from tests.test_rss_pilot import rss
def fetcher(url,**kwargs):return dict(status=200,raw=rss(title=sys.argv[3],identifier=sys.argv[3]),validators={'if-none-match':'"crash"'})
def checkpoint(stage):
 if stage==sys.argv[3]:os._exit(73)
RSSMonitoring(sys.argv[1],clock=lambda:float(sys.argv[4]),fetcher=fetcher).tick(sys.argv[2],checkpoint=checkpoint)
'''
        for stage in ['rss-fetched','rss-plan','prepared','before-ref','ref-updated','rss-published','rss-completed']:
            with self.subTest(stage=stage):
                # New native source identity for each crash, while preserving old receipts.
                self.body=rss(title=stage,identifier=stage)
                # Separate input avoids a previous completed identical finding hiding the write path.
                self.now[0]+=901
                result=subprocess.run([sys.executable,'-c',script,str(self.f.node),self.f.project,stage,str(self.now[0])],
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,73,result.stderr)
                resumed=RSSMonitoring(self.f.node,clock=lambda:self.now[0],fetcher=lambda *a,**kw:self.fail('duplicate GET'))
                resumed.tick(self.f.project)
                self.assertNotIn('publishing',{p['state'] for p in resumed.status(self.f.project)['polls']})
                self.assertEqual(self.f.git.run('status','--porcelain').stdout,'')
