# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import Authority
from spikes.metadata import ValidationError
from spikes.monitoring_filters import SCHEMA, evaluate, FilterPreviews, validate_pipeline
from spikes.monitoring_evaluation import MonitoringEvaluation, SCHEMA as EVALUATION
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaRuns, UnknownRun
from spikes.reporting import operation_uuid
from spikes.reporting_schema import digest, encoded
from spikes.rss_monitoring import RSSMonitoring
from spikes.source_connectors import SourceContext, RSSConnector
from spikes.rss_reader import parse_feed
from tests import test_reporting as fixtures
from tests.test_monitoring_definitions import definition
from tests.test_rss_pilot import rss


def keywords(**changes):
    return dict(id='topic', kind='keywords', fields=['title', 'content'], all=['first'], any=[], none=[], case_sensitive=False) | changes


def pipeline(*steps, revision='rules-1'):
    return dict(schema=SCHEMA, revision=revision, steps=list(steps or [keywords()]))


def source(title='First', identifier='one'):
    feed=parse_feed(rss(title=title, identifier=identifier), 'https://example.test/feed.xml')
    return RSSConnector().normalize_entry(feed['entries'][0], SourceContext('test',feed['url'],
        '2026-11-07T01:00:00Z','project','test',channel='News'),feed['raw_sha256'])


class FilterTests(unittest.TestCase):
    def test_keywords_combine_all_any_none_and_case_across_selected_fields(self):
        item=source('FIRST solar');rule=keywords(all=['first','solar'],any=['inert','other'],none=['advertisement'])
        self.assertEqual(evaluate(pipeline(rule),[item])['results'][0]['decision'],'selected')
        for change in (dict(all=['missing']),dict(any=['missing']),dict(none=['inert']),dict(case_sensitive=True)):
            with self.subTest(change=change):
                result=evaluate(pipeline(rule|change),[item])['results'][0]
                self.assertEqual(result['decision'],'discarded');self.assertIn('topic',result['reason'])
        self.assertEqual(evaluate(pipeline(keywords(fields=['author'])),[item])['results'][0]['decision'],'discarded')

    def test_regex_flags_modes_invalid_and_real_catastrophic_expression_are_bounded(self):
        rule=dict(id='pattern',kind='regex',fields=['title'],pattern='first',flags=['IGNORECASE'],match='fullmatch',negate=False)
        self.assertEqual(evaluate(pipeline(rule),[source()])['results'][0]['decision'],'selected')
        self.assertEqual(evaluate(pipeline(rule|dict(flags=[])),[source()])['results'][0]['decision'],'discarded')
        started=time.monotonic()
        for pattern in ('[','(a+)+$'):
            result=evaluate(pipeline(rule|dict(pattern=pattern)),[source('a'*4000+'!')])['results'][0]
            self.assertEqual(result['decision'],'error');self.assertIn('Regex' if pattern!='[' else 'regular',result['reason'])
        self.assertLess(time.monotonic()-started,3)
        self.assertEqual(evaluate(pipeline(rule),[source()])['results'][0]['decision'],'selected')

    def test_restrictions_no_language_guessing_and_dedup_is_explicit(self):
        item=source();rule=dict(id='channel',kind='restrict',channels=['News'],languages=['cs'],required_fields=['title'])
        self.assertEqual(evaluate(pipeline(rule),[item])['results'][0]['decision'],'discarded')
        self.assertEqual(evaluate(pipeline(rule),[item],languages={item['id']:'cs'})['results'][0]['decision'],'selected')
        other=source(identifier='two');rule=dict(id='unique',kind='dedup',field='content_sha256')
        result=evaluate(pipeline(rule),[item,other])['results']
        self.assertEqual([r['decision'] for r in result],['selected','discarded'])
        self.assertEqual(evaluate(pipeline(rule),[item],previous=[other])['results'][0]['decision'],'discarded')
        self.assertEqual(evaluate(pipeline(rule),[item],previous=[item])['results'][0]['decision'],'selected')

    def test_closed_rules_bounds_and_no_steps_after_handoff(self):
        for rule in (keywords(fields=['unknown']),keywords(case_sensitive=1),keywords(all=['x'*513])):
            with self.subTest(rule=rule),self.assertRaises(ValidationError):validate_pipeline(pipeline(rule))
        with self.assertRaises(ValidationError):validate_pipeline(pipeline(dict(id='end',kind='handoff'),keywords()))


class FilterRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.model=MonitoringDefinitions(self.f.node);self.watch=str(uuid4());self.calls=[];self.clock=[time.time()]
        def fetch(url,*,validators):
            self.calls.append(url);return dict(status=200,raw=rss(),validators={})
        self.runtime=RSSMonitoring(self.f.node,clock=lambda:self.clock[0],fetcher=fetch)

    def configure(self,rules,previous=None):
        value=definition();value['selection']['pipeline']=rules
        self.saved=self.model.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=self.watch,
            previous=[previous] if previous else [],privacy='project',definition=value),str(uuid4()))
        self.config=dict(project_id=self.f.project,watch_id=self.watch,input_id=value['inputs'][0]['id'],
            definition_ref=self.saved['definition_ref'],enabled=True,mode='pipeline')
        self.runtime.configure(self.config,confirm=True)
        return value

    def finding(self):return self.runtime.status(self.f.project)['findings'][0]

    def test_worker_persists_deciding_rule_preview_has_no_publication_and_history_survives(self):
        rules=pipeline(keywords(none=['first']));self.configure(rules);self.runtime.tick(self.f.project)
        finding=self.finding();self.assertEqual(finding['value']['stage'],'discarded')
        selection=finding['value']['selection'];self.assertIn('topic',selection['reason'])
        self.assertEqual(selection['audit']['pipeline'],rules)
        pin=self.f.service.pin(self.f.project,finding['revision_id']);head=self.f.git.head()
        preview=FilterPreviews(self.f.node).preview(self.f.project,rules,finding_refs=[pin])
        self.assertEqual(preview['results'][0]['decision'],'discarded');self.assertEqual(self.f.git.head(),head)
        old=self.saved['definition_ref'];self.configure(pipeline(keywords(),revision='rules-2'),old)
        self.assertEqual(self.f.record(pin),finding)
        self.assertEqual(FilterPreviews(self.f.node).preview(self.f.project,rules,finding_refs=[pin])['results'],preview['results'])

    def test_invalid_regex_is_a_captured_failure_worker_completes_and_never_calls_llm(self):
        self.configure(pipeline(dict(id='bad-regex',kind='regex',fields=['title'],pattern='[',flags=[],match='search',negate=False)))
        with patch('spikes.ollama_backend.OllamaAdapter.dispatch',side_effect=AssertionError('LLM must not run')):
            self.runtime.tick(self.f.project)
        self.assertEqual(self.finding()['value']['stage'],'failed')
        self.assertEqual(self.runtime.status(self.f.project)['polls'][0]['state'],'completed')

    def test_optional_content_dedup_crosses_channels_without_merging_source_identities(self):
        value=definition();value['selection']['pipeline']=pipeline(keywords(),dict(id='unique',kind='dedup',field='content_sha256'))
        other=deepcopy(value['inputs'][0]);other['id']=str(uuid4());other['locator']='https://example.test/other-feed';value['inputs'].append(other)
        saved=self.model.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=self.watch,
            previous=[],privacy='project',definition=value),str(uuid4()))
        for source_ in value['inputs']:
            self.runtime.configure(dict(project_id=self.f.project,watch_id=self.watch,input_id=source_['id'],
                definition_ref=saved['definition_ref'],enabled=True,mode='pipeline'),confirm=True)
        self.runtime.tick(self.f.project)
        findings=self.runtime.status(self.f.project)['findings']
        self.assertEqual(sorted(r['value']['stage'] for r in findings),['discarded','pending'])
        self.assertEqual(len({r['entity_id'] for r in findings}),2)
        self.assertIn('unique',next(r for r in findings if r['value']['stage']=='discarded')['value']['selection']['reason'])


class EvaluationTests(FilterRuntimeTests):
    # This suite shares fixture/helpers only, not inherited filter tests.
    test_worker_persists_deciding_rule_preview_has_no_publication_and_history_survives=None
    test_invalid_regex_is_a_captured_failure_worker_completes_and_never_calls_llm=None
    test_optional_content_dedup_crosses_channels_without_merging_source_identities=None

    def setUp(self):
        super().setUp()
        self.binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='binding-1',adapter='ollama',
            boundary='same-node',endpoint='http://127.0.0.1:11434',model='synthetic-model',target_id='local-process'))
        self.step=dict(id='classify',kind='llm',role='classifier',instructions='Identify topic claims; separate potential significance from evidence.',target=self.binding.target().__dict__)
        self.rules=pipeline(keywords(),self.step,dict(id='assess',kind='assessment'),dict(id='report',kind='handoff'))
        self.configure(self.rules);self.runtime.tick(self.f.project)
        self.pin=self.f.service.pin(self.f.project,self.finding()['revision_id'])
        self.authority=Authority('monitoring-test',self.f.author,str(uuid4()),'policy-1',
            frozenset([self.saved['definition_ref']['artifact_id'],self.pin['artifact_id']]))
        self.result=dict(schema=EVALUATION,decision='selected',reason='Topic match; claim remains unverified',relevance=5,
            significance=5,trustworthiness='unverified',claims=['Marketing breakthrough assertion'],limitations=['No independent operational evidence'])
        root=self.f.base/'monitoring-backend';root.mkdir(mode=0o700);self.runs=OllamaRuns(root);self.model_calls=[]
        def transport(binding,request):
            self.model_calls.append(request);return dict(model=binding.model,response=json.dumps(self.result),done=True)
        self.adapter=OllamaAdapter(self.runs,transport=transport,runtime_probe=lambda binding:dict(status='unknown'))
        self.evaluator=MonitoringEvaluation(self.f.node,self.adapter)

    def prepare(self,**changes):
        args=dict(project_id=self.f.project,definition_ref=self.saved['definition_ref'],finding_ref=self.pin,run_id=str(uuid4()),
            manifest_id=str(uuid4()),authority=self.authority,binding=self.binding);args.update(changes)
        return self.evaluator.prepare(**args)

    def test_cheap_filter_gates_llm_and_unknown_never_uses_fallback_or_retries(self):
        self.assertEqual(self.finding()['value']['stage'],'captured');self.assertEqual(self.model_calls,[])
        prepared=self.prepare()
        def offline(*args):self.model_calls.append('offline');raise OSError('offline')
        self.adapter.transport=offline
        with self.assertRaises(UnknownRun):self.evaluator.dispatch(prepared,authority=self.authority,binding=self.binding)
        with self.assertRaises(UnknownRun):self.evaluator.dispatch(prepared,authority=self.authority,binding=self.binding)
        self.assertEqual(len(self.model_calls),1)
        with self.assertRaisesRegex(ValidationError,'successful result'):self.evaluator.preview(prepared,authority=self.authority,binding=self.binding)
        with self.assertRaisesRegex(ValidationError,'target changed'):self.prepare(binding=replace(self.binding,model='other'))

    def test_high_relevance_never_confirms_breakthrough_exact_audit_accept_and_replay(self):
        prepared=self.prepare();head=self.f.git.head()
        self.evaluator.dispatch(prepared,authority=self.authority,binding=self.binding)
        preview=self.evaluator.preview(prepared,authority=self.authority,binding=self.binding)
        self.assertEqual(self.f.git.head(),head);self.assertTrue(preview['handoff'])
        operation=str(uuid4())
        with self.assertRaisesRegex(ValidationError,'confirmation'):
            self.evaluator.accept(prepared,operation,preview['approval_digest'],authority=self.authority,binding=self.binding)
        receipt=self.evaluator.accept(prepared,operation,preview['approval_digest'],authority=self.authority,binding=self.binding,confirm=True)
        self.assertEqual(receipt,self.evaluator.accept(prepared,operation,preview['approval_digest'],authority=self.authority,binding=self.binding,confirm=True))
        audit=json.loads(self.f.git.snapshot(self.f.git.head())[f"artifacts/{operation_uuid(operation,'assistance')}/assistance.json"])
        self.assertEqual(audit['context']['target'],self.step['target']);self.assertEqual(audit['result'],self.result)
        self.assertNotIn('session_id',audit['context']);self.assertEqual(self.finding()['value']['stage'],'pending')
        self.assertEqual(self.finding()['provenance']['run_refs'],[audit['run_ref']])
        records=self.f.service.read(self.f.project)['records']
        self.assertFalse(any(r['type']=='Event' for r in records));self.assertEqual(len(self.model_calls),1)

    def test_rejected_before_llm_cannot_prepare(self):
        rules=deepcopy(self.rules);rules['steps'][0]['none']=['first']
        self.configure(rules,self.saved['definition_ref']);self.runtime.tick(self.f.project)
        finding=next(r for r in self.runtime.status(self.f.project)['findings']
                     if r['value']['definition_ref']==self.saved['definition_ref'])
        pin=self.f.service.pin(self.f.project,finding['revision_id'])
        with self.assertRaisesRegex(ValidationError,'cheap filters'):
            self.prepare(finding_ref=pin)
        self.assertEqual(self.model_calls,[])

    def _crash_publication(self,stage):
        prepared=self.prepare();self.evaluator.dispatch(prepared,authority=self.authority,binding=self.binding)
        preview=self.evaluator.preview(prepared,authority=self.authority,binding=self.binding);operation=str(uuid4())
        path=self.f.base/'evaluation-plan.json';path.write_bytes(encoded(preview))
        script='''
import json,os,sys
from spikes.reporting import Reporting
preview=json.load(open(sys.argv[2]))
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
Reporting(sys.argv[1]).apply(preview['request'],sys.argv[3],confirm=True,_assistance=preview['assistance'],checkpoint=stop)
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.f.node),str(path),operation,stage],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,73,result.stderr)
        receipt=self.evaluator.accept(prepared,operation,preview['approval_digest'],authority=self.authority,binding=self.binding,confirm=True)
        self.assertEqual(receipt['commit_id'],self.f.git.head());self.assertEqual(self.finding()['value']['stage'],'pending')
        self.assertEqual(len(self.model_calls),1)

    def test_assisted_finding_recovers_crash_before_git_ref_without_second_llm(self):self._crash_publication('before-ref')

    def test_assisted_finding_recovers_crash_after_git_ref_without_second_llm(self):self._crash_publication('ref-updated')

    def test_model_claiming_confirmation_is_invalid_and_revoked_access_stops_dispatch(self):
        prepared=self.prepare();revoked=replace(self.authority,readable_entities=frozenset())
        with self.assertRaisesRegex(ValidationError,'revoked'):self.evaluator.dispatch(prepared,authority=revoked,binding=self.binding)
        self.result['trustworthiness']='confirmed'
        self.evaluator.dispatch(prepared,authority=self.authority,binding=self.binding)
        with self.assertRaisesRegex(ValidationError,'breakthrough'):self.evaluator.preview(prepared,authority=self.authority,binding=self.binding)
