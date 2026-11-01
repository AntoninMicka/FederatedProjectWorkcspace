# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.markdown_patch import SCHEMA
from spikes.markdown_self_tuning import (BASELINE, Campaign, ExperimentalAdapter,
    check_result, configuration, fixtures, recommend, tuning_proposal)
from tests import test_ollama_backend as ollama_fixtures
from spikes.ollama_backend import OllamaBinding, _OllamaTransportUnknown
from spikes.context_builder import DispatchHandoff


class SelfTuningTests(unittest.TestCase):
    def test_candidate_cannot_change_oracles_scopes_or_unbounded_settings(self):
        for field,value in [('num_predict',999999),('temperature',1),('temperature',True),
                            ('instruction_suffix','x'*2001),('disable_validation',True)]:
            with self.subTest(field=field),self.assertRaises(ValueError):configuration(dict(BASELINE,**{field:value}))
        with self.assertRaises(ValueError):tuning_proposal(dict(BASELINE,hypothesis='test',oracle='always-pass'))

    def test_recommendation_requires_training_improvement_and_no_holdout_regression(self):
        def rows(a,b,c,d):return [dict(case=k,split=s,first_pass=v) for k,s,v in
            [('a','train',a),('b','train',b),('c','holdout',c),('d','holdout',d)]]
        baseline=rows(True,False,True,True)
        self.assertTrue(recommend(baseline,rows(True,True,True,True)))
        self.assertFalse(recommend(baseline,rows(True,True,True,False)))
        self.assertFalse(recommend(baseline,rows(True,False,True,True)))
        self.assertFalse(recommend(rows(False,False,False,False),rows(True,False,False,False)))

    def campaign(self, **kwargs):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        binding=OllamaBinding.parse(ollama_fixtures.OllamaBindingTests().binding())
        return Campaign(Path(temporary.name)/'evidence',binding,['gemma3'],**kwargs)

    def factory(self, calls):
        cases=fixtures()
        def factory(runs, options):
            def transport(binding,raw,delta,status,*,control):
                wire=json.loads(raw);calls.append(wire)
                if 'tuning a Markdown' in wire['prompt']:
                    # Held-out case names/data must never reach the tuner.
                    self.assertNotIn('four-tasks',wire['prompt']);self.assertNotIn('x=1',wire['prompt'])
                    value=dict(hypothesis='Use narrow insertions',instruction_suffix='Use narrow insertions.',num_predict=2048,temperature=0)
                else:
                    prompt=wire['prompt']
                    # v3 prompts are plain Markdown with <<id kind>> marker lines, no hashes.
                    self.assertNotIn('expected_hash',prompt);self.assertNotIn('sha256:',prompt)
                    self.assertEqual(False,wire['think']);self.assertIn('num_ctx',wire['options'])
                    blocks=[dict(block_id=m[1],kind=m[2],content=m[3],
                                 title=m[3].lstrip('#').strip() if m[2]=='heading' else None)
                            for m in re.finditer(r'^<<(\S+) ([^\s>]+)[^>]*>>\n(.*?)(?=\n<<|\n\nRead-only|\n\n|\Z)',prompt,re.S|re.M)]
                    if 'Previous proposal was rejected.' not in wire['system'] and not options['instruction_suffix'] and 'Do existující dávky' in prompt:
                        value=dict(schema_version=1,kind='direct-answer',content='Wrong kind')
                    else:
                        if 'V kapitole Bezpečnost' in prompt:
                            block=next(b for b in blocks if b['content'].startswith('Změny'))
                            action='replace';content='Změny se nejprve ověřují a až poté ukládají.\r\n';dest=None
                        elif 'Přesuň celou kapitolu' in prompt:
                            block=next(b for b in blocks if b.get('title')=='První')
                            dest=next(b for b in blocks if b.get('title')=='Druhá')
                            action='move_section';content=None
                        elif 'Do existující dávky' in prompt:
                            block=blocks[-1];dest=None;action='insert_after'
                            content='    - [ ] [EVAL-QUEUE-TASK] '+cases[1]['titles'][0]+'\n      - type: task\n'
                        else:
                            block=blocks[-1];dest=None;action='insert_after'
                            content='  - [ ] [EVAL-NEW-BATCH] Evaluation batch\n    - type: batch\n'
                            for i,title in enumerate(cases[3]['titles']):
                                content+=f'    - [ ] [EVAL-NEW-TASK-{i}] {title}\n      - type: task\n'
                        value=dict(kind='markdown-patch',
                            changes=[dict(block_id=block['block_id'],action=action,content=content,
                                          destination_id=dest['block_id'] if dest else None)])
                return dict(model=binding.model,response=json.dumps(value),done_reason='stop')
            return ExperimentalAdapter(runs,options,stream_transport=transport)
        return factory

    def test_complete_loop_repairs_then_tunes_without_source_or_fixture_writes(self):
        calls=[];campaign=self.campaign(adapter_factory=self.factory(calls))
        head=campaign.head;report=campaign.run()
        self.assertEqual('finished',report['state']);self.assertEqual(head,campaign.git.head())
        self.assertEqual('',campaign.git.run('status','--porcelain').stdout)
        self.assertEqual(2,len(report['profiles']))
        baseline,candidate=report['profiles']
        queue=next(r for r in baseline['results'] if r['case']=='queue-task')
        self.assertFalse(queue['first_pass']);self.assertTrue(queue['after_repair'])
        self.assertTrue(all(r['first_pass'] for r in candidate['results']))
        self.assertEqual('human-review-only',report['recommendations'][0]['status'])
        ids=[r['run_id'] for r in report['runs']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(any(r['parent_run_id'] for r in report['runs'] if r['purpose']=='repair'))
        self.assertTrue((campaign.root/'report.md').exists())
        self.assertTrue(all((campaign.root/(id_+'-manifest.json')).exists() for id_ in ids))

    def test_unknown_runs_are_not_repaired_and_budget_prevents_further_dispatch(self):
        calls=[]
        def factory(runs,options):
            def unknown(*args,**kwargs):calls.append(1);raise _OllamaTransportUnknown('lost',code='transport-interrupted')
            return ExperimentalAdapter(runs,options,stream_transport=unknown)
        campaign=self.campaign(adapter_factory=factory,max_calls=1)
        report=campaign.run()
        self.assertEqual(1,len(calls));self.assertEqual(1,report['calls'])
        self.assertEqual('unknown',report['runs'][0]['state'])
        self.assertFalse(report['all_after_repair']);self.assertTrue(report['budget_exhausted'])
        self.assertEqual([],report['recommendations'])

    def test_existing_evidence_directory_is_never_overwritten(self):
        campaign=self.campaign()
        binding=campaign.binding
        before=(campaign.root/'report.json').read_bytes()
        with self.assertRaises(FileExistsError):Campaign(campaign.root,binding,['gemma3'])
        self.assertEqual(before,(campaign.root/'report.json').read_bytes())

    def test_generation_settings_are_part_of_the_immutable_request_digest(self):
        campaign=self.campaign()
        handoff=DispatchHandoff(str(uuid4()),str(uuid4()),'a'*64,campaign.binding.target(),b'plain fixture prompt')
        from spikes.ollama_backend import OllamaRuns
        runs=OllamaRuns(campaign.service._root())
        first=ExperimentalAdapter(runs,dict(BASELINE))
        second=ExperimentalAdapter(runs,dict(BASELINE,temperature=.1))
        a=first._request(handoff,campaign.binding,None,'text')
        self.assertEqual(a,first._request(handoff,campaign.binding,None,'text'))
        b=second._request(handoff,campaign.binding,None,'text')
        self.assertNotEqual(a[1],b[1]);self.assertNotEqual(a[2],b[2])
