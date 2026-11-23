# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import copy
import json
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.markdown_patch import apply, complete, context, scan, SCHEMA, MarkdownPatchError
from spikes.metadata import validate_snapshot
from spikes.ollama_backend import OllamaAdapter
from spikes.roadmap_additions import ROLE, OUTPUT, materialize, parents, output_schema
from spikes.roadmap_append_context import requests_new_tasks
from spikes.task_graph import parse_main_todo, project_task_graph, _validate_hierarchy
from tests import test_task_file_edit as fixtures
from tests.fixtures import ENTITY

BODY = '''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [FTIC-M02] Návrh
  - type: milestone
  - Původní poznámka
  - [ ] [FTIC-B02] Návrhová dávka
    - type: batch
    - [x] [FTIC-T02-03] Existující úkol
      - type: task
      - status: in progress
      - Zachovat popis
- [ ] [FTIC-M03] Implementace
  - type: milestone
  - [ ] [FTIC-B03] Implementační dávka
    - type: batch
    - [ ] [FTIC-T03-01] Původní implementace
      - type: task
'''


def proposal(parent='FTIC-B02'):
    return dict(kind=OUTPUT, additions=[dict(parent_id=parent, batch_id=None,
        batch_title=None, batch_description=None, tasks=[
            dict(id='AGENT-ANALYSIS',title='Analyzovat agenta',description='Potřeby uzlu',depends_on=[]),
            dict(id='AGENT-IMPLEMENT',title='Implementovat agenta',description='',depends_on=['AGENT-ANALYSIS'])])])


class AdditionTests(unittest.TestCase):
    def test_actual_failure_is_bad_generated_indentation_not_a_broken_original(self):
        parse_main_todo(BODY)
        blocks = scan(BODY)
        anchor = next(b for b in blocks if '[FTIC-T02-03]' in BODY[b.start:b.end])
        value = dict(kind='markdown-patch',changes=[dict(block_id=anchor.id,action='replace',destination_id=None,
            content='    - [x] [FTIC-T02-03] Existující úkol\n    - type: task\n'
                '    - [ ] [AGENT-ANALYSIS] Analýza\n    - type: task\n')])
        generated = apply(BODY, complete(value,BODY))
        with self.assertRaisesRegex(ValueError,'Uzel FTIC-T02-03 nemá platný type'):
            _validate_hierarchy(parse_main_todo(generated)[0])

    def test_czech_addition_requests_and_multiple_explicitly_typed_parents(self):
        for text in ['doplnit do seznamu úkolů úkoly pro analýzu a implementaci sw agenta',
                     'doplň seznam úkolů o úkoly pro návrh', 'vytvoř nové úkoly', 'add tasks']:
            self.assertTrue(requests_new_tasks(text))
        for text in ['uprav existující úkol','přesuň úkoly','zkontroluj seznam úkolů']:
            self.assertFalse(requests_new_tasks(text))
        available = parents(context(BODY,schema=SCHEMA))
        self.assertEqual(set(available), {'FTIC-M02','FTIC-M03','FTIC-B02','FTIC-B03'})
        self.assertNotIn('FTIC-T02-03',output_schema(context(BODY,schema=SCHEMA))['properties']['additions']['items']['properties']['parent_id']['enum'])

    def test_application_renders_metadata_dependencies_crlf_and_preserves_existing_bytes(self):
        for original in [BODY, BODY.replace('\n','\r\n')]:
            with self.subTest(crlf='\r' in original):
                patch = materialize(proposal(),original)
                edited = apply(original,patch)
                before,_ = parse_main_todo(original); after,_ = parse_main_todo(edited)
                for identifier,node in before.items():
                    for key in ['type','title','checked','parent_id','description_lines','relations','status_mode']:
                        self.assertEqual(node.get(key),after[identifier].get(key))
                self.assertEqual(after['AGENT-IMPLEMENT']['type'],'task')
                self.assertEqual(after['AGENT-IMPLEMENT']['parent_id'],'FTIC-B02')
                newline='\r\n' if '\r' in original else '\n'
                content=patch['changes'][0]['content']
                self.assertEqual(edited.replace(content,'',1),original)
                self.assertIn('      - type: task'+newline,content)

    def test_new_batch_selected_milestone_and_injection_duplicate_or_wrong_parent_rejected(self):
        value=proposal('FTIC-M03');value['additions'][0].update(batch_id='AGENT-BATCH',batch_title='Agent',batch_description='')
        patch=materialize(value,BODY);nodes,_=parse_main_todo(apply(BODY,patch))
        self.assertEqual(nodes['AGENT-BATCH']['parent_id'],'FTIC-M03')
        self.assertEqual(nodes['AGENT-ANALYSIS']['parent_id'],'AGENT-BATCH')
        for mutate in [lambda v:v['additions'][0].update(parent_id='FTIC-T02-03'),
                       lambda v:v['additions'][0]['tasks'][0].update(id='FTIC-T02-03'),
                       lambda v:v['additions'][0]['tasks'][0].update(title='Injected\n- [x] [OTHER-TASK] X'),
                       lambda v:v['additions'][0]['tasks'][0].update(checked=True)]:
            bad=copy.deepcopy(proposal());mutate(bad)
            with self.assertRaises(ValueError):materialize(bad,BODY)
        value=proposal();value['additions'][0]['tasks'][0]['description']='type: milestone'
        nodes,_=parse_main_todo(apply(BODY,materialize(value,BODY)))
        self.assertEqual(nodes['AGENT-ANALYSIS']['type'],'task')

    def test_selected_parent_scope_preserves_metadata_and_refuses_another_milestone(self):
        blocks=scan(BODY)
        header=next(b for b in blocks if '[FTIC-M02]' in BODY[b.start:b.end])
        ids=[header.id,blocks[blocks.index(header)+1].id]
        scope=context(BODY,ids,schema=SCHEMA)
        self.assertEqual(set(parents(scope)),{'FTIC-M02'})
        value=proposal('FTIC-M02');value['additions'][0].update(batch_id='AGENT-BATCH',batch_title='Agent',batch_description='')
        patch=materialize(value,BODY,ids)
        edited=apply(BODY,patch,selected_ids=scope['allowed_block_ids'])
        nodes,_=parse_main_todo(edited)
        self.assertEqual(nodes['FTIC-M02']['description_lines'],['Původní poznámka'])
        self.assertEqual(nodes['AGENT-BATCH']['parent_id'],'FTIC-M02')
        value['additions'][0]['parent_id']='FTIC-M03'
        with self.assertRaises(ValueError):materialize(value,BODY,ids)


class AdditionRouteTests(unittest.TestCase):
    setUp=fixtures.FileEditTests.setUp
    request=fixtures.FileEditTests.request
    pin_run_choice=fixtures.FileEditTests.pin_run_choice
    route_request=fixtures.FileEditTests.route_request
    create_document=fixtures.FileEditTests.create_document
    generate=fixtures.FileEditTests.generate
    confirmation=fixtures.FileEditTests.confirmation

    def seed(self):
        target=main_todo_id(ENTITY)
        Artifacts(self.node_path).save(dict(project_id=ENTITY,artifact_id=target,new=True,title='Plán',body=BODY,
            base_head=self.git.head()),str(uuid4()))
        return target

    def test_task_scope_refuses_before_model_and_invalid_model_additions_never_write_or_retry(self):
        target=self.seed()
        service,request,calls=self.generate(target,content='doplň seznam úkolů o úkoly pro agenta')
        selected=next(b.id for b in scan(BODY) if '[FTIC-T02-03]' in BODY[b.start:b.end])
        request['task_plan'].update(edit_format='blocks',edit_block_ids=[selected])
        before=self.git.head()
        with self.assertRaisesRegex(ValueError,'Samotný task'):
            service.task_route(request)
        self.assertEqual(calls,[])
        request['task_plan'].pop('edit_block_ids')
        with self.assertRaises(MarkdownPatchError):
            service.task_route(request)  # Existing fixture answers artifact-draft, not typed additions.
        self.assertEqual(len(calls),1);self.assertEqual(self.git.head(),before)
        self.assertEqual(service.task_outcomes(project_id=ENTITY),[])

    def test_real_route_schema_manifest_preview_and_confirm_keep_original_tasks(self):
        target=self.seed()
        service,request,calls=self.generate(target,content='doplnit do seznamu úkolů úkoly pro analýzu a implementaci sw agenta')
        request['task_plan']['edit_format']='blocks'
        def transport(binding,raw):
            wire=json.loads(raw);calls.append(wire)
            self.assertEqual(wire['format']['properties']['kind']['enum'],[OUTPUT])
            self.assertIn('The application renders Markdown',wire['system'])
            value=proposal();value['additions'][0]['tasks'][0]['depends_on']=['FTIC-T02-03']
            return dict(model=binding.model,response=json.dumps(value))
        service.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport)
        before=self.git.head();service.task_route(request)
        self.assertEqual(self.git.head(),before)
        preview=service.task_preview_file_edit(dict(project_id=ENTITY,task_id=request['task_id']))
        self.assertEqual(preview['body'].count('[FTIC-T02-03]'),1)
        result=service.task_confirm_file_edit(self.confirmation(preview))
        self.assertEqual(result['state'],'completed');self.assertEqual(len(calls),1)
        files=self.git.snapshot(self.git.head());graph=project_task_graph(files,validate_snapshot(files),ENTITY,self.git.head())
        self.assertEqual(graph['status'],'ready')
        original=next(n for n in graph['nodes'] if n['id']=='FTIC-T02-03')
        self.assertTrue(original['checked']);self.assertEqual(original['status'],'completed')
        self.assertEqual(original['status_mode'],'in progress')
