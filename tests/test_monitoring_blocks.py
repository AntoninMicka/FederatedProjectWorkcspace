# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

from tests import test_reporting as fixtures
from spikes.monitoring_blocks import MonitoringBlocks
from spikes.composable_monitoring import ComposableMonitoring
from spikes.monitoring import Monitoring
from spikes.monitoring_placement import local_node_id
from spikes.projects import Projects
from spikes.metadata import ValidationError
from spikes.message_pools import MessagePools, stamp
from spikes.reporting_schema import encoded


def block(kind, title, config):
    return dict(id=str(uuid4()), previous=[], privacy='project', value=dict(
        schema='fpw-reporting-block-v1', kind=kind, title=title, config=config))


def blocks(node):
    source = block('source', 'ČT24', dict(connector='rss-atom', locator='https://example.org/rss',
        poll_seconds=900, terms='Public test feed', retention='30 days'))
    pool = block('pool', 'Energetika', dict(retention_days=30))
    filter_ = block('filter', 'Všechny zprávy', dict(source_ids=[source['id']], pool_id=pool['id'],
        pipeline=dict(schema='fpw-monitoring-pipeline-v1', revision='1', steps=[dict(id='dedup', kind='dedup', field='content_sha256')])))
    processing = block('processing', 'Ranní zpráva', dict(pool_ids=[pool['id']], search_ids=[],
        instructions='Shrnout zprávy a uvést zdroje.', mode='deterministic', lookback_days=7,
        schedule=dict(kind='manual', time='07:00', timezone='Europe/Prague'), node_id=local_node_id(node)))
    task = block('task', 'Denní energetika', dict(source_ids=[source['id']], filter_ids=[filter_['id']],
        pool_ids=[pool['id']], processing_ids=[processing['id']], instructions='Denní zpráva.'))
    return [source, pool, filter_, processing, task]


def response(content='Energie dnes'):
    raw = ('<rss version="2.0"><channel><title>Test</title><item><guid>one</guid>'
           '<link>https://example.org/one</link><title>Zpráva</title><description>'+content+
           '</description></item></channel></rss>').encode()
    return dict(status=200, raw=raw, validators={'if-none-match':'"v1"'})


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.monitoring = Monitoring(self.f.node, Projects(self.f.node), clock=lambda: 1794160000)
        self.service = ComposableMonitoring(self.monitoring, fetcher=lambda *a, **kw: response())
        self.specs = blocks(self.f.node)
        self.service.blocks.save(self.f.project, self.f.git.head(), self.specs, str(uuid4()))

    def test_shared_blocks_usage_and_atomic_validation(self):
        catalog = self.service.blocks.read(self.f.project)
        self.assertEqual(len(catalog['blocks']), 5)
        source = next(b for b in catalog['blocks'] if b['id'] == self.specs[0]['id'])
        self.assertEqual(set(source['used_by']), {self.specs[2]['id'], self.specs[4]['id']})
        head = self.f.git.head(); invalid = deepcopy(self.specs)
        for b in invalid: b['id'] = str(uuid4())
        invalid[2]['value']['config']['source_ids'] = [str(uuid4())]
        with self.assertRaisesRegex(ValidationError, 'dependency'):
            self.service.blocks.save(self.f.project, head, invalid, str(uuid4()))
        self.assertEqual(head, self.f.git.head())

    def activate(self):
        self.service.configure(self.f.project, self.specs[0]['id'], True, confirm=True)

    def test_pool_capture_does_not_write_feed_to_git_and_restart_preserves_inputs(self):
        self.activate(); head = self.f.git.head(); self.service.tick(self.f.project)
        self.assertEqual(head, self.f.git.head())
        pool = self.service.pools.view(self.f.project, self.specs[1]['id'])
        self.assertEqual(len(pool), 1); self.assertEqual(len(pool[0]['revisions']), 1)
        self.assertEqual(pool[0]['revisions'][0]['item']['content'], 'Energie dnes')
        self.assertEqual(pool[0]['revisions'][0]['item']['discovered_at'], stamp(self.monitoring.clock()))
        restarted = ComposableMonitoring(self.monitoring, fetcher=lambda *a, **kw: self.fail('No second GET'))
        restarted.tick(self.f.project)
        run = restarted.process(self.f.project, self.specs[3]['id'], str(uuid4()))
        self.assertEqual(run['state'], 'review'); self.assertIn('Energie dnes', run['result']['markdown'])

    def test_two_nodes_and_two_filters_deduplicate_content_and_retain_corrections(self):
        self.activate(); self.service.tick(self.f.project)
        # A fresh observer uses the exact same source UUID and different local clock/node.
        b = self.service.blocks.read(self.f.project); by_id = {r['id']:r for r in b['blocks']}
        from spikes.source_connectors import RSSConnector, SourceContext
        source = by_id[self.specs[0]['id']]
        context = SourceContext(source['id'], source['value']['config']['locator'], stamp(self.monitoring.clock()+10), 'project', '30 days', channel=source['value']['title'])
        items = RSSConnector().normalize(dict(raw=response()['raw'], url=context.locator), context)['items']
        with patch('spikes.composable_monitoring.local_node_id', return_value=str(uuid4())):
            rows = self.service._selected(self.f.project, source, items, [by_id[self.specs[2]['id']]], by_id, context.discovered_at)
        self.service.pools.merge(self.f.project, rows); self.service.pools.merge(self.f.project, rows)
        view = self.service.pools.view(self.f.project, self.specs[1]['id'])
        self.assertEqual(len(view), 1); self.assertEqual(len(view[0]['revisions']), 1)
        self.assertEqual(len(view[0]['observations']), 2)
        items = RSSConnector().normalize(dict(raw=response('Opravená energie')['raw'], url=context.locator), context)['items']
        rows = self.service._selected(self.f.project, source, items, [by_id[self.specs[2]['id']]], by_id, context.discovered_at)
        self.service.pools.merge(self.f.project, rows)
        view = self.service.pools.view(self.f.project, self.specs[1]['id'])
        self.assertEqual(len(view[0]['revisions']), 2); self.assertTrue(view[0]['concurrent_versions'])

    def test_unknown_dispatch_is_not_automatically_retried(self):
        self.activate(); calls=[]
        def crash(url, **kwargs): calls.append(url); raise TimeoutError('interrupted')
        self.service.fetcher=crash
        self.service.tick(self.f.project); self.service.tick(self.f.project)
        self.assertEqual(len(calls), 1)
        job = next(j for j in self.service.catalog(self.f.project)['jobs'] if j['state']=='unknown')
        self.service.release_unknown(self.f.project, job['id'], confirm=True)
        self.monitoring.clock=lambda: 1794161000; self.service.clock=self.monitoring.clock; self.service.pools.clock=self.monitoring.clock
        self.service.fetcher=lambda *a, **kw:response(); self.service.tick(self.f.project)
        self.assertEqual(len(self.service.pools.view(self.f.project,self.specs[1]['id'])),1)

    def test_rejected_text_never_enters_pool_or_git(self):
        filter_=self.specs[2]; saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==filter_['id'])
        updated=deepcopy(filter_); updated['previous']=[saved['ref']]
        updated['value']['config']['pipeline']['steps']=[dict(id='terms',kind='keywords',fields=['content'],all=['missing'],any=[],none=[],case_sensitive=False)]
        self.service.blocks.save(self.f.project,self.f.git.head(),[updated],str(uuid4()))
        self.activate(); self.service.tick(self.f.project)
        self.assertEqual(self.service.pools.export(self.f.project),[])
        self.assertNotIn(b'Energie dnes', b''.join(self.f.git.snapshot(self.f.git.head()).values()))

    def test_search_is_never_periodic_and_unconfigured_search_fails_visibly(self):
        source=block('source','Hledání',dict(connector='web-search',locator='energetika',poll_seconds=None,terms='Test',retention='30 days'))
        self.service.blocks.save(self.f.project,self.f.git.head(),[source],str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'Only RSS'):
            self.service.configure(self.f.project,source['id'],True,confirm=True)

    def test_pool_merge_crash_rolls_back_then_replays_once(self):
        self.activate(); self.service.tick(self.f.project); rows=self.service.pools.export(self.f.project)
        other = self.f.base/'other.json'
        from spikes.project_creation import ProjectCreation
        ProjectCreation(other).create('Other',self.f.base/'other-project',str(uuid4()))
        pool=MessagePools(other,clock=self.monitoring.clock)
        def crash(stage):
            if stage=='pool-inserted': raise RuntimeError('crash')
        with self.assertRaisesRegex(RuntimeError,'crash'):pool.merge(self.f.project,rows,checkpoint=crash)
        self.assertEqual(pool.export(self.f.project),[])
        pool.merge(self.f.project,rows); pool.merge(self.f.project,rows)
        self.assertEqual(pool.export(self.f.project),rows)

    def test_proposal_validates_shared_refs_and_complete_task(self):
        self.service.validate_proposal(self.f.project,self.f.git.head(),[block('task','Reuse',deepcopy(self.specs[4]['value']['config']))])
        invalid=block('task','Bad',deepcopy(self.specs[4]['value']['config']));invalid['value']['config']['source_ids']=[str(uuid4())]
        with self.assertRaisesRegex(ValidationError,'dependency'):
            self.service.validate_proposal(self.f.project,self.f.git.head(),[invalid])

    def model(self, transport):
        from spikes.ollama_backend import OllamaBinding,OllamaBindings,OllamaAdapter
        root=self.f.node.parent/('.'+self.f.node.name+'.chat');root.mkdir(mode=0o700,exist_ok=True)
        binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='v1',adapter='ollama',
            boundary='same-node',endpoint='http://127.0.0.1:11434',model='synthetic',target_id='local-process'))
        OllamaBindings(root).save(binding)
        self.monitoring.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport,runtime_probe=lambda b:dict(status='unknown'))

    def test_llm_composition_uses_manifest_and_returns_editable_reuse_proposal_without_writes(self):
        proposal=dict(blocks=[block('task','LLM reuse',deepcopy(self.specs[4]['value']['config']))],explanation='Použít existující bloky.')
        calls=[]
        def transport(binding,request):
            calls.append(request);return dict(model=binding.model,response=encoded(proposal).decode(),done=True)
        self.model(transport);head=self.f.git.head();run_id=str(uuid4())
        result=self.service.compose(self.f.project,run_id,'Ranní přehled',confirm=True)
        self.assertEqual(result['state'],'review');self.assertEqual(result['result']['proposal'],proposal)
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual(self.service.compose(self.f.project,run_id,'Ranní přehled',confirm=True),result)
        self.assertEqual(len(calls),1)
        job=next(j for j in self.service.catalog(self.f.project)['jobs'] if j['id']==run_id)
        self.assertIn('manifest',job['intent'])
        self.service.blocks.save(self.f.project,head,result['result']['proposal']['blocks'],str(uuid4()))
        self.assertEqual(len(self.service.blocks.read(self.f.project)['blocks']),6)

    def test_llm_unknown_is_not_redispatched(self):
        calls=[]
        def transport(binding,request):calls.append(request);raise TimeoutError('lost response')
        self.model(transport);run_id=str(uuid4())
        with self.assertRaises(Exception):self.service.compose(self.f.project,run_id,'Report',confirm=True)
        result=self.service.compose(self.f.project,run_id,'Report',confirm=True)
        self.assertEqual(result['state'],'unknown');self.assertEqual(len(calls),1)

    def test_report_publication_is_reviewed_and_idempotent(self):
        self.activate();self.service.tick(self.f.project);run_id=str(uuid4())
        result=self.service.process(self.f.project,self.specs[3]['id'],run_id)
        head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'approval'):
            self.service.publish(self.f.project,run_id,'0'*64,confirm=True)
        self.assertEqual(head,self.f.git.head())
        published=self.service.publish(self.f.project,run_id,result['result']['approval_digest'],confirm=True)
        head=self.f.git.head()
        self.assertEqual(published,self.service.publish(self.f.project,run_id,result['result']['approval_digest'],confirm=True))
        self.assertEqual(head,self.f.git.head())

    def test_expired_membership_cannot_resurrect_and_unknown_intake_stays_blocked(self):
        self.activate();self.service.tick(self.f.project);rows=self.service.pools.export(self.f.project)
        self.service.pools.clock=lambda:1794160000+31*86400
        self.assertEqual(self.service.pools.export(self.f.project),[])
        self.service.pools.merge(self.f.project,rows)
        self.assertEqual(self.service.pools.export(self.f.project),[])
        with self.service.pools.db() as db:
            job_id=str(uuid4());intent=dict(kind='intake',source_id=self.specs[0]['id'],expires_at=1)
            db.execute('INSERT INTO block_jobs VALUES(?,?,?,?,NULL)',(job_id,self.f.project,'unknown',encoded(intent)))
        self.service.pools.export(self.f.project)
        with self.service.pools.db() as db:
            state,raw=db.execute('SELECT state,document FROM block_jobs WHERE id=?',(job_id,)).fetchone()
        self.assertEqual(state,'unknown');self.assertEqual(json.loads(raw)['source_id'],self.specs[0]['id'])

    def test_filter_change_requires_new_local_consent(self):
        self.activate();catalog=self.service.blocks.read(self.f.project)
        row=next(b for b in catalog['blocks'] if b['id']==self.specs[2]['id'])
        edited=deepcopy(self.specs[2]);edited['previous']=[row['ref']];edited['value']['title']='New filter revision'
        self.service.blocks.save(self.f.project,self.f.git.head(),[edited],str(uuid4()))
        self.service.fetcher=lambda *a,**kw:self.fail('Changed filter must not run without new consent')
        self.service.tick(self.f.project)
        self.assertEqual(self.service.pools.export(self.f.project),[])
        source=next(b for b in self.service.catalog(self.f.project)['blocks'] if b['id']==self.specs[0]['id'])
        self.assertIn('confirm',source['runtime']['error'])

    def test_multiple_sources_filters_pools_and_processing_share_blocks(self):
        catalog=self.service.blocks.read(self.f.project)
        source=deepcopy(self.specs[0]);source['id']=str(uuid4());source['value']['title']='Second channel';source['value']['config']['locator']='https://example.org/rss-two'
        pool=block('pool','Second pool',dict(retention_days=7))
        filter_=deepcopy(self.specs[2]);filter_['id']=str(uuid4());filter_['value']['config'].update(source_ids=[self.specs[0]['id'],source['id']],pool_id=pool['id'])
        processing=deepcopy(self.specs[3]);processing['id']=str(uuid4());processing['value']['config']['pool_ids'].append(pool['id'])
        self.service.blocks.save(self.f.project,self.f.git.head(),[source,pool,filter_,processing],str(uuid4()))
        catalog=self.service.blocks.read(self.f.project)
        first=next(b for b in catalog['blocks'] if b['id']==self.specs[0]['id'])
        self.assertIn(filter_['id'],first['used_by']);self.assertEqual(len(catalog['blocks']),9)

    def test_intake_process_crashes_have_no_automatic_second_get(self):
        script='''
import json,os,sys
from spikes.composable_monitoring import ComposableMonitoring
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from tests.test_monitoring_blocks import response
s=ComposableMonitoring(Monitoring(sys.argv[1],Projects(sys.argv[1]),clock=lambda:1794160000),fetcher=lambda *a,**k:response())
def stop(stage):
 if stage==sys.argv[3]:os._exit(73)
s.tick(sys.argv[2],checkpoint=stop)
'''
        for stage in ('intake-dispatching','intake-fetched','pool-inserted','intake-committed'):
            with self.subTest(stage=stage):
                # One source stream per trial; its own immutable definitions and local consent.
                source=deepcopy(self.specs[0]);source['id']=str(uuid4())
                filter_=deepcopy(self.specs[2]);filter_['id']=str(uuid4());filter_['value']['config']['source_ids']=[source['id']]
                self.service.blocks.save(self.f.project,self.f.git.head(),[source,filter_],str(uuid4()))
                self.service.configure(self.f.project,source['id'],True,confirm=True)
                result=subprocess.run([sys.executable,'-c',script,str(self.f.node),self.f.project,stage],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,73,result.stderr)
                restarted=ComposableMonitoring(self.monitoring,fetcher=lambda *a,**kw:self.fail('Crash cannot cause second GET'))
                restarted.tick(self.f.project)
                # Stop stream so it cannot affect the next independent trial.
                restarted.configure(self.f.project,source['id'],False,confirm=True)

    def test_local_only_catalog_cannot_be_sent_to_private_network_model(self):
        from spikes.ollama_backend import OllamaBinding,OllamaBindings
        self.model(lambda *a,**kw:self.fail('Privacy must block transport'))
        secret=block('pool','Private inventory',dict(retention_days=1));secret['privacy']='local-only'
        self.service.blocks.save(self.f.project,self.f.git.head(),[secret],str(uuid4()))
        root=self.f.node.parent/('.'+self.f.node.name+'.chat')
        binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='v1',adapter='ollama',
            boundary='private-network',endpoint='https://192.168.10.4:11443',model='synthetic',target_id=str(uuid4()),tls_cert_sha256='a'*64))
        OllamaBindings(root).save(binding)
        with self.assertRaisesRegex(ValidationError,'local-only'):
            self.service.compose(self.f.project,str(uuid4()),'Report',confirm=True)

    def test_complex_task_reuses_child_run_ids(self):
        self.activate();self.service.tick(self.f.project);run_id=str(uuid4())
        first=self.service.run_task(self.f.project,self.specs[4]['id'],run_id)
        self.assertEqual(first['state'],'completed')
        self.assertEqual(self.service.run_task(self.f.project,self.specs[4]['id'],run_id),first)
        self.assertEqual(first['children'][0]['state'],'review')

    def test_daily_processing_runs_once(self):
        catalog=self.service.blocks.read(self.f.project)
        saved=next(b for b in catalog['blocks'] if b['id']==self.specs[3]['id'])
        p=deepcopy(self.specs[3]);p['previous']=[saved['ref']];p['value']['config']['schedule'].update(kind='daily',time='00:00')
        self.service.blocks.save(self.f.project,self.f.git.head(),[p],str(uuid4()))
        self.service.configure(self.f.project,p['id'],True,confirm=True)
        self.service.tick(self.f.project);self.service.tick(self.f.project)
        jobs=[j for j in self.service.catalog(self.f.project)['jobs'] if j['intent']['kind']=='processing']
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['state'],'review')

    def test_shared_filter_edit_resolves_new_channel_in_tasks_without_rewriting_them(self):
        catalog=self.service.blocks.read(self.f.project);saved=next(b for b in catalog['blocks'] if b['id']==self.specs[2]['id'])
        second=deepcopy(self.specs[0]);second['id']=str(uuid4())
        edited=deepcopy(self.specs[2]);edited['previous']=[saved['ref']];edited['value']['config']['source_ids'].append(second['id'])
        self.service.blocks.save(self.f.project,self.f.git.head(),[second,edited],str(uuid4()))
        catalog=self.service.blocks.read(self.f.project)
        task=next(b for b in catalog['blocks'] if b['id']==self.specs[4]['id'])
        source=next(b for b in catalog['blocks'] if b['id']==second['id'])
        self.assertIn(second['id'],task['resolved_ids']);self.assertIn(task['id'],source['tasks'])

    def test_pausing_during_http_does_not_get_overwritten_by_inflight_result(self):
        self.activate()
        def fetch(*a,**kw):
            self.service.configure(self.f.project,self.specs[0]['id'],False,confirm=True)
            return response()
        self.service.fetcher=fetch;self.service.tick(self.f.project)
        source=next(b for b in self.service.catalog(self.f.project)['blocks'] if b['id']==self.specs[0]['id'])
        self.assertFalse(source['runtime']['enabled']);self.assertEqual(self.service.pools.export(self.f.project),[])

    def test_repeated_observation_does_not_extend_existing_selection_retention(self):
        self.activate();self.service.tick(self.f.project)
        original=[r for r in self.service.pools.export(self.f.project) if r['kind']=='membership']
        self.service.clock=lambda:1794161000;self.service.pools.clock=self.service.clock
        self.service.tick(self.f.project)
        current=[r for r in self.service.pools.export(self.f.project) if r['kind']=='membership']
        self.assertEqual(original,current)

    def test_web_search_runs_only_when_report_requests_it_using_existing_search_journal(self):
        from spikes.web_search import SearXNGBinding,SearXNGBindings,SearXNGAdapter
        root=self.f.node.parent/('.'+self.f.node.name+'.chat');root.mkdir(mode=0o700,exist_ok=True)
        binding=SearXNGBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='1',adapter='searxng',
            boundary='same-node',endpoint='http://127.0.0.1:8888',target_id='local-process',result_limit=3,timeout_seconds=15))
        SearXNGBindings(root).save(binding)
        search=block('source','Hledání',dict(connector='web-search',locator='energy news',poll_seconds=None,terms='Public search',retention='1 day'))
        saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==self.specs[3]['id'])
        p=deepcopy(self.specs[3]);p['previous']=[saved['ref']];p['value']['config']['search_ids']=[search['id']]
        self.service.blocks.save(self.f.project,self.f.git.head(),[search,p],str(uuid4()))
        calls=[]
        def transport(binding,query):
            calls.append(query);return dict(results=[dict(title='Web evidence',url='https://example.org/search-result',content='Search snippet')])
        with patch('spikes.web_search.SearXNGAdapter',side_effect=lambda runs:SearXNGAdapter(runs,transport=transport)):
            self.service.tick(self.f.project);self.assertEqual(calls,[])
            result=self.service.process(self.f.project,p['id'],str(uuid4()))
        self.assertEqual(calls,['energy news']);self.assertEqual(result['state'],'review')
        self.assertIn('Search snippet',result['result']['markdown'])

    def test_known_rss_unavailability_retries_after_interval_without_unknown_release(self):
        from spikes.rss_reader import RSSUnavailable
        self.activate();calls=[]
        def unavailable(*a,**kw):
            calls.append(1);error=RSSUnavailable('503');error.retry_after='60';raise error
        self.service.fetcher=unavailable;self.service.tick(self.f.project)
        job=next(j for j in self.service.catalog(self.f.project)['jobs'] if j['intent']['kind']=='intake')
        self.assertEqual(job['state'],'failed')
        self.service.clock=lambda:1794161000;self.service.pools.clock=self.service.clock
        self.service.fetcher=lambda *a,**kw:response();self.service.tick(self.f.project)
        self.assertEqual(len(self.service.pools.view(self.f.project,self.specs[1]['id'])),1)
