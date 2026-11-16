# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import Authority
from spikes.metadata import ValidationError,validate_snapshot
from spikes.monitoring import ident
from spikes.ollama_backend import OllamaAdapter,OllamaBinding,OllamaRuns,UnknownRun
from spikes.reporting_schema import encoded
from spikes.synthesis_model import ModelExecution,validate_result,SCHEMA
from tests import test_monitoring_synthesis as synthesis_fixtures
from tests.test_monitoring_definitions import definition


class ModelSynthesisTests(unittest.TestCase):
    for _name in ('save','weekly','monthly','issue'):
        locals()[_name]=getattr(synthesis_fixtures.SynthesisTests,_name)

    def setUp(self):
        synthesis_fixtures.SynthesisTests.setUp(self)
        self.week,_=self.weekly();self.value=definition('Analytical month','monthly',upstream=self.week['watch_id'])
        self.value['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete')
        self.binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='v1',adapter='ollama',
            boundary='same-node',endpoint='http://127.0.0.1:11434',model='synthetic-analyst',target_id='local-process'))
        self.value['report']['mode']='llm'
        self.value['report']['analysis']=dict(revision='month-analysis-1',input_level='weekly',
            case_studies=[dict(ref=self.f.policy,status='ongoing',note='Explicit case state, not inferred completion')],target=vars(self.binding.target()))
        self.watch=self.save(self.value)
        self.prepared=self.service.prepare(self.f.project,self.watch['definition_ref'],self.month);self.run_id=self.prepared['run']['run_id']
        metas=validate_snapshot(self.f.git.snapshot(self.f.git.head()))
        ids=set(metas)|{ident(self.run_id,'analysis')}
        self.authority=Authority('analytical-test',self.f.author,str(uuid4()),'policy-v1',frozenset(ids))
        root=self.f.base/'analytical-runs';root.mkdir(mode=0o700);self.runs=OllamaRuns(root);self.calls=[]
        self.result=dict(schema=SCHEMA,overview='Synthetic assessment; missing inputs remain unknown.',annotations=[])
        def transport(binding,request):
            self.calls.append(request);return dict(model=binding.model,response=json.dumps(self.result),done=True)
        self.adapter=OllamaAdapter(self.runs,transport=transport,runtime_probe=lambda binding:dict(status='unknown'))
        self.execution=ModelExecution(self.adapter,self.binding,self.authority)

    def execute(self,**kw):
        return self.service.execute(self.f.project,self.watch['definition_ref'],self.month,model_execution=self.execution,**kw)

    def test_explicit_model_context_review_and_publication_keep_ledger_and_target(self):
        with self.assertRaisesRegex(ValidationError,'Explicit model execution'):
            self.service.execute(self.f.project,self.watch['definition_ref'],self.month)
        result=self.execute();self.assertEqual(result['state'],'review');self.assertEqual(len(self.calls),1)
        self.assertNotIn('assistance_context',result['run'])
        preview=self.service.scheduler.preview(self.run_id);value=preview['request']['records'][0]['value']
        self.assertEqual(value['generation']['mode'],'assisted')
        doc=value['generation']['context_manifest_ref'];audit=json.loads(self.f.git.snapshot(doc['commit_id'])[doc['path']])
        self.assertEqual(audit['context']['target'],vars(self.binding.target()));self.assertNotIn('session_id',audit['context'])
        self.assertEqual(audit['ledger_ref'],value['analysis_ref']);self.assertEqual(audit['result'],self.result)
        self.assertIn(self.f.policy['artifact_id'],{i['input_id'] for i in audit['context']['inputs']})
        issued=self.service.publish(self.run_id,preview['approval_digest'],confirm=True)
        self.assertNotIn('assistance_context',issued)
        record=self.f.record(issued['workspace_receipt']['snapshot']);self.assertEqual(record['value']['analysis_ref'],value['analysis_ref'])
        self.assertEqual(self.execute()['state'],'completed');self.assertEqual(len(self.calls),1)

    def test_unknown_backend_cannot_be_retried_with_another_model_or_scheduler_attempt(self):
        def unavailable(*a):self.calls.append('unavailable');raise OSError('offline')
        self.adapter.transport=unavailable
        with self.assertRaises(UnknownRun):self.execute()
        self.assertEqual(self.service.scheduler.get(self.run_id)['state'],'unknown')
        with self.assertRaises(ValidationError):self.service.retry(self.run_id,confirm=True,model_execution=self.execution)
        self.service.scheduler.reconcile_no_effect(self.run_id,confirm=True)
        changed=replace(self.execution,binding=replace(self.binding,model='other-model'))
        with self.assertRaisesRegex(ValidationError,'target changed'):
            self.service.retry(self.run_id,confirm=True,model_execution=changed)
        with self.assertRaises(UnknownRun):self.service.retry(self.run_id,confirm=True,model_execution=self.execution)
        self.assertEqual(len(self.calls),1)

    def test_revoked_input_access_stops_model_before_transport(self):
        self.execution=replace(self.execution,authority=replace(self.authority,readable_entities=frozenset()))
        with self.assertRaisesRegex(ValidationError,'revoked'):self.execute()
        self.assertEqual(self.calls,[])

    def test_model_cannot_promote_a_claim_or_invent_evidence(self):
        claim=dict(event_id=str(uuid4()),claim_id=str(uuid4()),trend='insufficient-evidence',evidence_refs=[])
        ledger=dict(events=[dict(claims=[claim])]);annotation=dict(event_id=claim['event_id'],claim_id=claim['claim_id'],trend='progress',explanation='Fake promotion',evidence_refs=[])
        with self.assertRaisesRegex(ValidationError,'promote'):validate_result(dict(schema=SCHEMA,overview='Test',annotations=[annotation]),ledger)
        annotation['trend']=claim['trend'];annotation['evidence_refs']=[dict(fake='source')]
        with self.assertRaisesRegex(ValidationError,'invented'):validate_result(dict(schema=SCHEMA,overview='Test',annotations=[annotation]),ledger)

    def test_cached_success_survives_render_failure_without_second_provider_call(self):
        def broken(*a,**kw):raise ValueError('Interrupted after model result')
        # The deterministic renderer runs before model dispatch; interrupt only
        # the model renderer, after the provider journal stores its success.
        with patch('spikes.synthesis_model.render',side_effect=broken):
            with self.assertRaisesRegex(ValueError,'Interrupted'):self.execute()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.service.scheduler.get(self.run_id)['state'],'failed')
        result=self.service.retry(self.run_id,confirm=True,model_execution=self.execution)
        self.assertEqual(result['state'],'review');self.assertEqual(len(self.calls),1)

    def _crash(self,stage):
        params=dict(definition_ref=self.watch['definition_ref'],period=self.month,binding=vars(self.binding),
            authority=vars(self.authority)|dict(readable_entities=list(self.authority.readable_entities)),result=self.result)
        path=self.f.base/'model-input.json';path.write_bytes(encoded(params));calls=self.f.base/'child-calls.txt'
        script='''
import json,os,sys
from pathlib import Path
from spikes.context_builder import Authority
from spikes.ollama_backend import OllamaRuns,OllamaAdapter,OllamaBinding
from spikes.monitoring_synthesis import WatchSynthesis
from spikes.synthesis_model import ModelExecution
v=json.load(open(sys.argv[3]));a=v['authority'];a['readable_entities']=frozenset(a['readable_entities'])
binding=OllamaBinding(**v['binding'])
def transport(binding,request):
 with open(sys.argv[6],'a') as stream:stream.write('call\\n')
 return dict(model=binding.model,response=json.dumps(v['result']),done=True)
adapter=OllamaAdapter(OllamaRuns(Path(sys.argv[4])),transport=transport,runtime_probe=lambda b:dict(status='unknown'))
def checkpoint(stage):
 if stage==sys.argv[5]:os._exit(73)
WatchSynthesis(sys.argv[1]).execute(sys.argv[2],v['definition_ref'],v['period'],
 model_execution=ModelExecution(adapter,binding,Authority(**a)),checkpoint=checkpoint)
'''
        root=self.f.base/'analytical-runs'
        child=subprocess.run([sys.executable,'-c',script,str(self.f.node),self.f.project,str(path),str(root),stage,str(calls)],
            capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,73,child.stderr)
        with self.service.scheduler.db() as db:until=db.execute('SELECT lease_until FROM runs WHERE run_id=?',(self.run_id,)).fetchone()[0]
        self.service.scheduler.clock=lambda:until+1
        self.assertEqual(self.execute()['state'],'unknown')
        self.service.scheduler.reconcile_no_effect(self.run_id,confirm=True)
        result=self.service.retry(self.run_id,confirm=True,model_execution=self.execution)
        self.assertEqual(result['state'],'review')
        child_count=len(calls.read_text().splitlines()) if calls.exists() else 0
        self.assertEqual(child_count+len(self.calls),1)

    def test_real_exit_after_context_bind_restores_original_model_intent(self):self._crash('synthesis-model-bound')

    def test_real_exit_after_backend_success_reuses_result_without_second_call(self):self._crash('synthesis-model-result')
