# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import unittest
from uuid import uuid4

from spikes.reporting_schema import digest,encoded
from spikes.reporting_scheduler import calendar_period
from spikes.synthesis_analysis import build,render
from tests import test_monitoring_synthesis as synthesis_fixtures


class NativeAnalysisTests(unittest.TestCase):
    for _name in ('save','weekly','monthly','issue'):
        locals()[_name]=getattr(synthesis_fixtures.SynthesisTests,_name)

    def setUp(self):synthesis_fixtures.SynthesisTests.setUp(self)

    def publish_evidence_week(self,week,period,previous_event=None,previous_assessment=None,maturity=1):
        prepared=self.service.prepare(self.f.project,week['definition_ref'],period);run=prepared['run']
        source_value=self.f.record(self.f.source())['value'];source_value.update(task_ref=run['task_ref'],imported_at=None)
        source=self.f.store('Source',source_value)
        old=self.f.record(previous_event) if previous_event else None
        claim=deepcopy(old['value']['claims'][0]) if old else dict(claim_id=str(uuid4()),text='Pilot in a declared scope',scope='Test facility',stage='pilot')
        value=dict(schema='fpw-reporting-event-v1',task_ref=run['task_ref'],title='Shared event',summary='Same event across weekly reports',
            event_date=dict(precision='unknown',start=None,end=None,basis=[]),detected_at=None,imported_at=None,categories=[],entities=[],geographies=[],tags=[],
            sources=[source],claims=[claim],assessments=[],correction_reason='Updated weekly context' if old else None)
        event=self.f.store('Event',value,[previous_event] if old else [],old['entity_id'] if old else None)
        task=self.f.record(run['task_ref']);entity=self.f.record(event)['entity_id']
        old_assessment=self.f.record(previous_assessment) if previous_assessment else None
        review=self.f.review();review['policy_revision']=run['rules_ref']
        assessment=self.f.store('EvidenceAssessment',dict(schema='fpw-reporting-assessment-v1',task_ref=run['task_ref'],
            subject=dict(event_id=entity,claim_id=claim['claim_id'],claim_sha256=digest(encoded(claim))),scale_ref=task['value']['scale_ref'],
            ratings=dict(maturity=maturity,relevance=5,novelty=None,impact=None,confidence='high'),
            evidence=[dict(source_ref=source,locator=None,relation='supports',independence_group=None,rationale='Explicit primary-source human review')],
            limitations=['Reference-only evidence'],review=review),[previous_assessment] if old_assessment else [],
            old_assessment['entity_id'] if old_assessment else None,confirm=True)
        attached=self.f.record(event)['value'];attached.update(assessments=[assessment],correction_reason='Attach reviewed assessment')
        event=self.f.store('Event',attached,[event],entity)
        selected_run=run|dict(input_head=self.f.git.head(),knowledge_cutoff=self.service.scheduler.stamp())
        value,markdown,_=self.service.monitoring.synthesize(self.f.project,dict(privacy='project',inputs=[],name='Weekly evidence',
            periods={'weekly':'Preserve exact event and assessment revisions'}),selected_run)
        issued=self.f.store('ReportSnapshot',value,confirm=True,markdown=markdown)
        return event,assessment,issued

    def test_native_weekly_event_is_counted_once_in_month_and_through_annual_summary(self):
        from tests.test_monitoring_definitions import definition
        self.month=calendar_period('2025-10-01T00:00:00+02:00','monthly','Europe/Prague','iso-calendar-v1')
        cfg=definition('Historical weeks','weekly');cfg['schedule']['start']='2025-01-01'
        cfg['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        cfg['inputs'][0]['policy']=dict(window='ending-in-period',approval='captured',missing='allow-incomplete');week=self.save(cfg)
        monthly_value=definition('Analytical month','monthly',upstream=week['watch_id']);monthly_value['schedule']['start']='2025-01-01'
        monthly_value['report']['analysis']=dict(revision='month-1',input_level='weekly',target=None,
            case_studies=[dict(ref=self.f.policy,status='ongoing',note='Case remains explicitly ongoing')])
        monthly_value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete');month=self.save(monthly_value)
        from spikes.monitoring_synthesis import windows
        periods=windows(cfg['schedule'],self.month,'ending-in-period')
        event,assessment,one=self.publish_evidence_week(week,periods[0])
        event,assessment,two=self.publish_evidence_week(week,periods[1],event,assessment,3)
        monthly,result=self.issue(month,self.month)
        record=self.f.record(monthly);pin=record['value']['analysis_ref']
        ledger=json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']])
        self.assertEqual(ledger['unique_events'],1);self.assertEqual(ledger['events'][0]['claims'][0]['trend'],'progress')
        self.assertTrue(ledger['gaps']);self.assertEqual(ledger['events'][0]['current_date']['precision'],'unknown')
        self.assertEqual(record['value']['reproducibility'],'limited-inputs')
        self.assertFalse(self.service.freshness(self.f.project,monthly)['potentially_stale'])
        self.assertEqual({r['artifact_id'] for r in ledger['events'][0]['reported_in']},{one['artifact_id'],two['artifact_id']})
        self.assertTrue(any(n['ref']['artifact_id']==event['artifact_id'] for n in self.service.trace(self.f.project,monthly)['nodes']))
        year_period=calendar_period('2025-01-01T00:00:00+01:00','annual','Europe/Prague','iso-calendar-v1')
        for parent,level in [(month,'monthly'),(week,'weekly')]:
            annual_value=definition('Analytical year from '+level,'annual',upstream=parent['watch_id']);annual_value['schedule']['start']='2025-01-01'
            annual_value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete')
            annual_value['report']['analysis']=dict(revision='annual-1',input_level=level,case_studies=[],target=None)
            annual=self.save(annual_value);issued,_=self.issue(annual,year_period)
            annual_ref=self.f.record(issued)['value']['analysis_ref'];analysis=json.loads(self.f.git.snapshot(annual_ref['commit_id'])[annual_ref['path']])
            self.assertEqual(analysis['unique_events'],1);self.assertEqual(analysis['events'][0]['claims'][0]['trend'],'progress')
            self.assertEqual(analysis['input_levels'][0]['kind'],level)
            self.assertTrue(any(p['artifact_id']==event['artifact_id'] for p in analysis['evidence_refs']))
            self.assertFalse(self.service.freshness(self.f.project,issued)['potentially_stale'])
            if level=='monthly':
                self.assertEqual(analysis['case_studies'][0]['status'],'ongoing')
                self.assertEqual(analysis['case_studies'][0]['declared_in']['artifact_id'],month['definition_ref']['artifact_id'])
            else:self.assertEqual(analysis['case_studies'],[])

    def test_captured_reporting_json_and_ordinary_case_json_remain_opaque(self):
        from datetime import datetime,timezone
        from tests.test_monitoring_definitions import definition
        record=self.f.record(self.f.event());raw_id=str(uuid4());doc_id=str(uuid4());changes={}
        at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        for id_,kind,content in [(raw_id,'source',encoded(record)),(doc_id,'document',b'{"ordinary":true}')]:
            changes[f'artifacts/{id_}/record.json']=content
            changes[f'artifacts/{id_}/metadata.json']=encoded(dict(schema_version=1,id=id_,title='Opaque capture',kind=kind,
                created_at=at,author_id=self.f.author,privacy='project',provenance='user',file='record.json'))
        self.f.ws.apply(changes,author_name='Synthetic',author_email='test@example.invalid',message='Synthetic opaque inputs')
        source=self.f.service.pin(self.f.project,raw_id);case=self.f.service.pin(self.f.project,doc_id)
        value=definition('Opaque source analysis','weekly');value['inputs'][0]['connector']='web-search'
        value['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'],
            analysis=dict(revision='opaque-test',input_level='mixed',case_studies=[dict(ref=case,status='unknown',note='No inferred case state')],target=None))
        watch=self.save(value);period=calendar_period('2026-10-05T00:00:00+02:00','weekly','Europe/Prague','iso-calendar-v1')
        issued,_=self.issue(watch,period,external_refs=[dict(input_id=value['inputs'][0]['id'],ref=source)])
        pin=self.f.record(issued)['value']['analysis_ref'];ledger=json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']])
        self.assertEqual(ledger['unique_events'],0);self.assertEqual(ledger['case_studies'][0]['status'],'unknown')
        self.assertEqual(ledger['sources'][0]['ref']['artifact_id'],raw_id)
        # A later display-title edit must not rewrite the historical ledger.
        path=f'artifacts/{raw_id}/metadata.json';meta=json.loads(self.f.git.snapshot(self.f.git.head())[path]);meta['title']='Renamed after publication'
        self.f.ws.apply({path:encoded(meta)},author_name='Synthetic',author_email='test@example.invalid',message='Rename source display metadata')
        self.f.service.read(self.f.project)
        self.assertEqual(json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']]),ledger)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.store={};self.project=str(uuid4());self.claim_id=str(uuid4());self.event_id=str(uuid4());self.assessment_id=str(uuid4())
        self.period=calendar_period('2026-10-01T00:00:00+02:00','monthly','Europe/Prague','iso-calendar-v1')
        self.claim=dict(claim_id=self.claim_id,text='Operational claim',scope='Test facility',stage='pilot')
        self.source=self.row('Source',dict(title='Primary',capture_state='reference-only',raw_ref=None,availability='available',source_role='primary'))
        self.scale=self.row('EvaluationScale',dict(title='Scale one'))
        self.policy=self.add(str(uuid4()),dict(schema='synthetic-method-v1'))
        self.task=self.row('ReportingTask',dict(scope={},source_policy=self.policy,selection_policy=self.policy))
        self.upstream=self.row('WatchDefinition',dict(schedule=dict(kind='weekly')))
        self.definition=dict(report=dict(instructions='Assess original versus current, uncertainty and gaps.'))

    def row(self,kind,value,entity=None,previous=None,at='2026-10-01T12:00:00Z'):
        id_=str(uuid4());record=dict(type=kind,entity_id=entity or str(uuid4()),revision_id=id_,recorded_at=at,previous=previous or [],value=value)
        return self.add(id_,record,'record.json')

    def add(self,id_,value,name='content.md'):
        raw=encoded(value);ref=dict(project_id=self.project,artifact_id=id_,path=f'artifacts/{id_}/{name}',commit_id='a'*40,sha256=digest(raw))
        self.store[id_]=(dict(kind='document',file=name,privacy='project',created_at='2026-10-01T12:00:00Z'),value if name=='record.json' else None,raw)
        return ref

    def assessment(self,maturity,previous=None,scale=None,relation='supports',reviewed=True,claim=None):
        return self.row('EvidenceAssessment',dict(task_ref=self.task,subject=dict(event_id=self.event_id,claim_id=self.claim_id,claim_sha256=digest(encoded(claim or self.claim))),
            scale_ref=scale or self.scale,ratings=dict(maturity=maturity,confidence='high'),review=dict(decision='confirmed') if reviewed else None,
            evidence=[dict(source_ref=self.source,relation=relation,independence_group=None)]),self.assessment_id,[previous] if previous else [],
            at='2026-10-20T12:00:00Z' if previous else '2026-10-01T12:00:00Z')

    def event(self,assessment,previous=None,claim=None):
        return self.row('Event',dict(task_ref=self.task,title='Claimed breakthrough',claims=[claim or self.claim],sources=[self.source],assessments=[assessment]),
            self.event_id,[previous] if previous else [],at='2026-10-20T12:00:00Z' if previous else '2026-10-01T12:00:00Z')

    def report(self,event,assessment):
        return self.row('ReportSnapshot',dict(period=self.period,knowledge_cutoff='2026-11-01T12:00:00Z',events=[event],assessments=[assessment],
            sources=[self.source],stories=[],corrects=None,correction_reason=None,limitations=['Reference-only evidence']))

    def ledger(self,reports,definition=None):
        plan=dict(schema='fpw-watch-input-manifest-v1',definition_ref=self.upstream,period=self.period,knowledge_cutoff='2026-11-01T12:00:00Z',
            inputs=[dict(input_id='weeks',kind='watch',definition_ref=self.upstream,take='reports',refs=reports,missing=[])])
        pin=self.add(str(uuid4()),plan)
        return build(plan,pin,definition or self.definition,lambda p:self.store[p['artifact_id']])

    def test_repeated_event_is_one_and_same_reviewed_scale_supports_three_trends(self):
        for maturity,expected in [(3,'progress'),(2,'stagnation'),(1,'regression')]:
            with self.subTest(expected=expected):
                first=self.assessment(2);old=self.event(first);last=self.assessment(maturity,first);new=self.event(last,old)
                ledger=self.ledger([self.report(old,first),self.report(new,last)])
                self.assertEqual(ledger['unique_events'],1);self.assertEqual(len(ledger['events'][0]['reported_in']),2)
                self.assertEqual(ledger['events'][0]['claims'][0]['trend'],expected)
                self.assertEqual(len(ledger['events'][0]['versions']),2)

    def test_marketing_and_model_review_absence_never_become_confirmed_progress(self):
        first=self.assessment(2,reviewed=False);old=self.event(first);last=self.assessment(5,first,reviewed=False);new=self.event(last,old)
        ledger=self.ledger([self.report(old,first),self.report(new,last)])
        claim=ledger['events'][0]['claims'][0];self.assertEqual(claim['trustworthiness'],'unverified');self.assertEqual(claim['trend'],'insufficient-evidence')
        self.assertIn('Nedostatek důkazů',render(ledger));self.assertEqual(ledger['unique_events'],1)

    def test_changed_scale_and_changed_claim_do_not_produce_progress(self):
        first=self.assessment(1);old=self.event(first)
        other=self.row('EvaluationScale',dict(title='Different scale'))
        last=self.assessment(5,first,scale=other);new=self.event(last,old)
        claim=self.ledger([self.report(old,first),self.report(new,last)])['events'][0]['claims'][0]
        self.assertEqual(claim['trend'],'methodology-change');self.assertTrue(claim['methodology_changed'])
        edited=self.claim|dict(scope='Different facility');last=self.assessment(5,first,claim=edited);new=self.event(last,old,edited)
        claim=self.ledger([self.report(old,first),self.report(new,last)])['events'][0]['claims'][0]
        self.assertEqual(claim['trend'],'claim-change');self.assertNotEqual(claim['original'],claim['current'])

    def test_contradictions_remain_visible_and_case_state_is_explicit(self):
        first=self.assessment(2);old=self.event(first);last=self.assessment(5,first,relation='contradicts');new=self.event(last,old)
        definition=deepcopy(self.definition);definition['report']['analysis']=dict(revision='annual-2',case_studies=[dict(ref=self.source,status='abandoned',note='Explicitly abandoned branch')])
        ledger=self.ledger([self.report(old,first),self.report(new,last)],definition)
        claim=ledger['events'][0]['claims'][0];self.assertTrue(claim['contradictions']);self.assertEqual(claim['trend'],'conflicting-evidence')
        text=render(ledger);self.assertIn('Explicitly abandoned branch',text);self.assertIn('abandoned',text);self.assertIn('Rozpor',text)

    def test_identical_titles_need_reviewed_dedup_and_retraction_restores_separate_events(self):
        first=self.assessment(1);event=self.event(first)
        other=self.row('Event',deepcopy(self.store[event['artifact_id']][1]['value']))
        one=self.report(event,first);two=self.report(other,first)
        self.assertEqual(self.ledger([one,two])['unique_events'],2)
        old_id=self.store[event['artifact_id']][1]['entity_id'];other_id=self.store[other['artifact_id']][1]['entity_id'];decision=str(uuid4())
        value=dict(events=[event,other],decisions=[dict(decision_id=decision,kind='duplicate',event_ids=[old_id,other_id],canonical_event_id=old_id,reverses=None,
            reason='Explicit reviewed duplicate',review=dict(decision='confirmed'))])
        story=self.row('Story',value);story_report_value=deepcopy(self.store[one['artifact_id']][1]['value']);story_report_value['stories']=[story]
        with_story=self.row('ReportSnapshot',story_report_value)
        self.assertEqual(self.ledger([one,two,with_story])['unique_events'],1)
        changed=deepcopy(value);changed['decisions'].append(dict(decision_id=str(uuid4()),kind='retract',event_ids=[old_id,other_id],canonical_event_id=None,reverses=decision,
            reason='Reviewed reversal',review=dict(decision='confirmed')))
        replacement=self.row('Story',changed,self.store[story['artifact_id']][1]['entity_id'],[story],at='2026-10-20T12:00:00Z')
        story_report_value['stories']=[replacement];new_report=self.row('ReportSnapshot',story_report_value)
        self.assertEqual(self.ledger([one,two,new_report])['unique_events'],2)

    def test_equal_timestamps_use_revision_ancestry_instead_of_uuid_order(self):
        from unittest.mock import patch
        from uuid import UUID
        with patch('tests.test_synthesis_analysis.uuid4',side_effect=[UUID('f'*32),UUID('0'*32)]):
            first=self.assessment(1);last=self.assessment(3,first)
        row=deepcopy(self.store[last['artifact_id']][1]);row['recorded_at']=self.store[first['artifact_id']][1]['recorded_at']
        last=self.add(last['artifact_id'],row,'record.json')
        old=self.event(first);new=self.event(last,old)
        ledger=self.ledger([self.report(old,first),self.report(new,last)])
        claim=ledger['events'][0]['claims'][0];self.assertEqual(claim['trend'],'progress')
        self.assertEqual(claim['original_assessment']['ratings']['maturity'],1);self.assertEqual(claim['current_assessment']['ratings']['maturity'],3)

    def test_changed_method_policy_with_same_scale_is_not_progress(self):
        first=self.assessment(1);old=self.event(first)
        changed_policy=self.add(str(uuid4()),dict(schema='synthetic-method-v2'))
        self.task=self.row('ReportingTask',dict(scope={},source_policy=changed_policy,selection_policy=changed_policy))
        last=self.assessment(5,first);new=self.event(last,old)
        claim=self.ledger([self.report(old,first),self.report(new,last)])['events'][0]['claims'][0]
        self.assertEqual(claim['trend'],'methodology-change');self.assertTrue(claim['methodology_changed'])
