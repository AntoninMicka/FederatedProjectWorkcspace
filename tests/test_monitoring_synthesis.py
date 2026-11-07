# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.monitoring_synthesis import WatchSynthesis,windows
from spikes.reporting_scheduler import calendar_period
from spikes.reporting_schema import encoded
from spikes.rss_monitoring import RSSMonitoring
from spikes.source_import import Sources,request_from_bytes
from datetime import datetime
from tests import test_reporting as fixtures
from tests.test_monitoring_definitions import definition


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.model=MonitoringDefinitions(self.f.node);self.service=WatchSynthesis(self.f.node)
        self.month=calendar_period('2026-10-01T00:00:00+02:00','monthly','Europe/Prague','iso-calendar-v1')

    def save(self,value,identity=None,previous=None):
        return self.model.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=identity or str(uuid4()),
            previous=previous or [],privacy='project',definition=value),str(uuid4()))

    def weekly(self):
        value=definition('Weekly evidence','weekly');value['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        value['inputs'][0]['policy']=dict(window='ending-in-period',approval='captured',missing='allow-incomplete')
        return self.save(value),value

    def monthly(self,upstream,missing='wait'):
        value=definition('Monthly from stored reports','monthly',upstream=upstream['watch_id'])
        value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing=missing)
        return self.save(value),value

    def issue(self,watch,period,**kwargs):
        result=self.service.execute(self.f.project,watch['definition_ref'],period,**kwargs)
        self.assertEqual(result['state'],'review',result)
        preview=self.service.scheduler.preview(result['run']['run_id'])
        issued=self.service.publish(result['run']['run_id'],preview['approval_digest'],confirm=True)
        return issued['workspace_receipt']['snapshot'],result

    def test_monthly_uses_exact_issued_weeks_without_network_and_one_publication(self):
        week,cfg=self.weekly();month,_=self.monthly(week)
        refs=[]
        for period in windows(cfg['schedule'],self.month,'ending-in-period'):refs.append(self.issue(week,period)[0])
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('No fetch')):
            pin,result=self.issue(month,self.month)
        self.assertTrue(result['complete']);record=self.f.record(pin);self.assertTrue(record['value']['synthesis']['complete'])
        manifest=record['value']['synthesis']['manifest_ref'];plan=json.loads(self.f.git.snapshot(manifest['commit_id'])[manifest['path']])
        self.assertEqual({r['artifact_id'] for r in plan['inputs'][0]['refs']},{r['artifact_id'] for r in refs})
        before=self.f.git.head();again=self.service.execute(self.f.project,month['definition_ref'],self.month)
        self.assertEqual(again['run']['workspace_receipt']['snapshot'],pin);self.assertEqual(before,self.f.git.head())

    def test_missing_week_waits_or_explicitly_marks_incomplete_and_freezes(self):
        week,cfg=self.weekly();month,_=self.monthly(week)
        result=self.service.prepare(self.f.project,month['definition_ref'],self.month)
        self.assertEqual(result['state'],'waiting-inputs');self.assertIn('missing',result['missing'][0])
        incomplete,_=self.monthly(week,'allow-incomplete')
        first=self.service.prepare(self.f.project,incomplete['definition_ref'],self.month);self.assertFalse(first['complete'])
        self.issue(week,windows(cfg['schedule'],self.month,'ending-in-period')[0])
        result=self.service.execute(self.f.project,incomplete['definition_ref'],self.month)
        self.assertEqual(result['manifest_ref'],first['manifest_ref']);self.assertFalse(result['complete'])
        text=self.service.scheduler.preview(result['run']['run_id'])['request']['records'][0]['markdown']
        self.assertIn('NEÚPLNÁ',text);self.assertIn('missing',text)

    def test_freeze_survives_real_process_exit_and_different_intent_cannot_replace_it(self):
        week,_=self.weekly();month,_=self.monthly(week,'allow-incomplete')
        invalid=deepcopy(self.month);invalid['calendar_revision']='unknown';head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'canonical watch calendar'):
            self.service.prepare(self.f.project,month['definition_ref'],invalid)
        self.assertEqual(head,self.f.git.head())
        payload=self.f.base/'synthesis.json';payload.write_bytes(encoded(dict(pin=month['definition_ref'],period=self.month)))
        script='''
import json,os,sys
from spikes.monitoring_synthesis import WatchSynthesis
v=json.load(open(sys.argv[3]))
def stop(stage):
 if stage=='synthesis-frozen':os._exit(73)
WatchSynthesis(sys.argv[1]).prepare(sys.argv[2],v['pin'],v['period'],checkpoint=stop)
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.f.node),self.f.project,str(payload)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,73,result.stderr)
        upstream=next(d['definition'] for d in self.model.read(self.f.project)['definitions'] if d['watch_id']==week['watch_id'])
        upstream['evaluation']['revision']='after-freeze'
        self.save(upstream,week['watch_id'],[week['definition_ref']])
        result=self.service.prepare(self.f.project,month['definition_ref'],self.month)
        rule_pin=result['run']['rules_ref'];rules=json.loads(self.f.git.snapshot(rule_pin['commit_id'])[rule_pin['path']])
        self.assertEqual(rules['input_definitions'][0]['definition_ref']['artifact_id'],week['definition_ref']['artifact_id'])
        before=self.f.git.head();self.assertEqual(result,self.service.prepare(self.f.project,month['definition_ref'],self.month));self.assertEqual(before,self.f.git.head())
        value=next(d['definition'] for d in self.model.read(self.f.project)['definitions'] if d['watch_id']==month['watch_id'])
        value['report']['instructions']='Changed instructions';changed=self.save(value,month['watch_id'],[month['definition_ref']])
        with self.assertRaisesRegex(ValidationError,'frozen intent'):
            self.service.prepare(self.f.project,changed['definition_ref'],self.month)

    def test_input_correction_marks_report_stale_without_rewriting_it(self):
        week,cfg=self.weekly();month,_=self.monthly(week,'allow-incomplete')
        issued,_=self.issue(week,windows(cfg['schedule'],self.month,'ending-in-period')[0]);monthly,_=self.issue(month,self.month)
        self.assertFalse(self.service.freshness(self.f.project,monthly)['potentially_stale'])
        original=self.f.record(issued);value=deepcopy(original['value'])
        value['approval'].update(actor_id=None,at=None)
        value['markdown']=None
        value.update(corrects=issued,correction_reason='Corrected input evidence')
        correction=self.f.store('ReportSnapshot',value,confirm=True,markdown='\n'.join(['# Přehled','Nebyla doložena významná změna.','## Omezení','Correction']))
        self.assertFalse(self.service.freshness(self.f.project,correction)['potentially_stale'])
        before=self.f.git.head();state=self.service.freshness(self.f.project,monthly)
        self.assertTrue(state['potentially_stale']);self.assertEqual(before,self.f.git.head());self.assertEqual(self.f.record(issued),original)

    def test_weekly_combines_daily_findings_multiple_watches_and_explicit_search_capture(self):
        from tests.test_rss_pilot import rss
        daily_value=definition();daily=self.save(daily_value)
        at=datetime.fromisoformat('2026-10-01T12:00:00+02:00').timestamp()
        collector=RSSMonitoring(self.f.node,clock=lambda:at,fetcher=lambda *a,**kw:dict(status=200,raw=rss(),validators={}))
        collector.configure(dict(project_id=self.f.project,watch_id=daily['watch_id'],input_id=daily_value['inputs'][0]['id'],
            definition_ref=daily['definition_ref'],enabled=True,mode='queue-all'),confirm=True);collector.tick(self.f.project)
        second=self.save(definition('Second daily source'))
        value=definition('Combined weekly','weekly',upstream=daily['watch_id'])
        value['inputs'][0].update(take='findings',policy=dict(window='ending-in-period',approval='selected',missing='wait'))
        other=deepcopy(value['inputs'][0]);other.update(id=str(uuid4()),watch_id=second['watch_id']);other['policy']['missing']='allow-incomplete'
        value['inputs'].append(other)
        search=deepcopy(daily_value['inputs'][0]);search.update(id=str(uuid4()),connector='web-search',locator='https://example.test/search');value['inputs'].append(search)
        combined=self.save(value)
        request=request_from_bytes(self.f.project,self.f.git.head(),'search.md',b'Synthetic reviewed search result: unverified claim.',
            'Approved supplemental search capture','Test only',[],'project',source_url='https://example.test/search')
        receipt=Sources(self.f.node).import_source(request,str(uuid4()))
        source=self.f.service.pin(self.f.project,request['artifact_id'],receipt['commit_id'])
        period=windows(dict(kind='weekly',timezone='Europe/Prague',start='2026-03-01'),self.month,'overlap')[0]
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('No implicit search')):
            issued,result=self.issue(combined,period,external_refs=[dict(input_id=search['id'],ref=source)])
        record=self.f.record(issued);manifest=record['value']['synthesis']['manifest_ref']
        plan=json.loads(self.f.git.snapshot(manifest['commit_id'])[manifest['path']])
        self.assertEqual([len(i['refs']) for i in plan['inputs']],[1,0,1]);self.assertFalse(result['complete'])
        traced=self.service.trace(self.f.project,issued)
        self.assertTrue(any(n['type']=='SourceFinding' for n in traced['nodes']))
        self.assertTrue(any(n['ref']['artifact_id']==source['artifact_id'] for n in traced['nodes']))

    def test_paused_definition_cannot_publish_and_cross_level_trace_reaches_source(self):
        week_value=definition('Historical weekly','weekly');week_value['schedule']['start']='2025-01-01'
        week_value['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        week_value['inputs'][0]['connector']='web-search';week=self.save(week_value)
        request=request_from_bytes(self.f.project,self.f.git.head(),'search.md',b'Reviewed source claim, not corroboration.',
            'Historical search capture','Synthetic late capture',[],'project',source_url='https://example.test/search')
        receipt=Sources(self.f.node).import_source(request,str(uuid4()));source=self.f.service.pin(self.f.project,request['artifact_id'],receipt['commit_id'])
        month_value=definition('Historical monthly','monthly',upstream=week['watch_id']);month_value['schedule']['start']='2025-01-01'
        month_value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete');month=self.save(month_value)
        annual_value=definition('Historical annual','annual',upstream=month['watch_id']);annual_value['schedule']['start']='2025-01-01'
        annual_value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete');annual=self.save(annual_value)
        period=calendar_period('2025-10-06T00:00:00+02:00','weekly','Europe/Prague','iso-calendar-v1')
        self.issue(week,period,external_refs=[dict(input_id=week_value['inputs'][0]['id'],ref=source)])
        month_period=calendar_period('2025-10-01T00:00:00+02:00','monthly','Europe/Prague','iso-calendar-v1');self.issue(month,month_period)
        annual_period=calendar_period('2025-01-01T00:00:00+01:00','annual','Europe/Prague','iso-calendar-v1')
        result=self.service.execute(self.f.project,annual['definition_ref'],annual_period)
        preview=self.service.scheduler.preview(result['run']['run_id'])
        paused=deepcopy(annual_value);paused['active']=False;updated=self.save(paused,annual['watch_id'],[annual['definition_ref']])
        with self.assertRaisesRegex(ValidationError,'changed or paused'):
            self.service.publish(result['run']['run_id'],preview['approval_digest'],confirm=True)
        self.assertEqual(self.service.scheduler.get(result['run']['run_id'])['state'],'review')
        # A distinct active annual watch can publish its own explicitly incomplete intent.
        other=self.save(annual_value);issued,_=self.issue(other,annual_period)
        traced=self.service.trace(self.f.project,issued)
        self.assertTrue(any(n['ref']['artifact_id']==source['artifact_id'] for n in traced['nodes']))
        self.assertGreaterEqual(sum(n['type']=='ReportSnapshot' for n in traced['nodes']),3)

    def test_publication_crashes_before_and_after_ref_recover_one_issued_report(self):
        period=calendar_period('2026-10-05T00:00:00+02:00','weekly','Europe/Prague','iso-calendar-v1')
        for stage in ('before-ref','ref-updated'):
            with self.subTest(stage=stage):
                week,_=self.weekly();result=self.service.execute(self.f.project,week['definition_ref'],period)
                preview=self.service.scheduler.preview(result['run']['run_id']);run_id=result['run']['run_id']
                script='''
import os,sys
from spikes.monitoring_synthesis import WatchSynthesis
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
WatchSynthesis(sys.argv[1]).publish(sys.argv[2],sys.argv[3],confirm=True,checkpoint=stop)
'''
                child=subprocess.run([sys.executable,'-c',script,str(self.f.node),run_id,preview['approval_digest'],stage],capture_output=True,text=True,timeout=30)
                self.assertEqual(child.returncode,73,child.stderr)
                result=self.service.publish(run_id,preview['approval_digest'],confirm=True);self.assertEqual(result['state'],'completed')
                head=self.f.git.head();again=self.service.publish(run_id,preview['approval_digest'],confirm=True)
                self.assertEqual(result,again);self.assertEqual(head,self.f.git.head())

    def test_daily_synthesis_expired_lease_is_unknown_and_explicit_retry_keeps_inputs(self):
        value=definition('Daily stored evidence','daily');value['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        value['inputs'][0]['policy']=dict(window='ending-in-period',approval='captured',missing='allow-incomplete')
        watch=self.save(value);period=calendar_period('2026-10-01T00:00:00+02:00','daily','Europe/Prague','iso-calendar-v1')
        prepared=self.service.prepare(self.f.project,watch['definition_ref'],period);run_id=prepared['run']['run_id']
        self.service.scheduler.claim(run_id,str(uuid4()),lease_seconds=1)
        with self.service.scheduler.db() as db:until=db.execute('SELECT lease_until FROM runs WHERE run_id=?',(run_id,)).fetchone()[0]
        self.service.scheduler.clock=lambda:until+1
        unknown=self.service.execute(self.f.project,watch['definition_ref'],period);self.assertEqual(unknown['state'],'unknown')
        with self.assertRaises(ValidationError):self.service.retry(run_id,confirm=True)
        self.service.scheduler.reconcile_no_effect(run_id,confirm=True)
        result=self.service.retry(run_id,confirm=True);self.assertEqual(result['state'],'review')
        self.assertEqual(result['manifest_ref'],prepared['manifest_ref'])
