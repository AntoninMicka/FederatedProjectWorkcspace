# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
from types import MappingProxyType
import hashlib
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.context_builder import ContextBuilder,Authority,Target,ProjectInput,AdHocInput,TaskInstruction,PreparedContext
from spikes.markdown_documents import main_todo_id
from spikes.metadata import validate_snapshot
from spikes.ollama_backend import OllamaAdapter
from spikes.roadmap_append_context import SCHEMA,build,requests_new_tasks
from tests import test_task_file_edit as fixtures
from tests.fixtures import ENTITY

BODY='''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-DEV] DEV
  - type: milestone
  - [ ] [OLD-BATCH] Existing batch
    - type: batch
    - [x] [OLD-TASK] Existing task
      - type: task
      - DO_NOT_EXPORT_OLD_DESCRIPTION
'''


class AppendContextTests(unittest.TestCase):
    setUp=fixtures.FileEditTests.setUp
    request=fixtures.FileEditTests.request
    pin_run_choice=fixtures.FileEditTests.pin_run_choice
    route_request=fixtures.FileEditTests.route_request
    create_document=fixtures.FileEditTests.create_document
    generate=fixtures.FileEditTests.generate

    def seed(self):
        target=main_todo_id(ENTITY)
        Artifacts(self.node_path).save(dict(project_id=ENTITY,artifact_id=target,new=True,title='Roadmap',
            body=BODY+''.join(f'    - [ ] [OLD-{i}] Existing task {i}\n      - type: task\n      - DO_NOT_EXPORT_OLD_DESCRIPTION\n' for i in range(500)),base_head=self.git.head()),str(uuid4()))
        return target

    def prepared(self):
        target=self.seed();node,user=self.service._identity();run=str(uuid4());focus=str(uuid4())
        authority=Authority('append-test',user,node,'task-output-file-edit-patch-v5',frozenset({target}))
        destination=Target(str(uuid4()),'rev','same-node','local','model')
        builder=ContextBuilder(self.service.projects.workspace(ENTITY),ENTITY)
        value=builder.prepare(manifest_id=str(uuid4()),run_id=run,authority=authority,target=destination,
            project_inputs=(ProjectInput(target,projection=SCHEMA),),ad_hoc_inputs=(AdHocInput(focus,b'Add tasks','project'),),
            task=TaskInstruction('task-output','task-output-file-edit-patch-v5','Append tasks',focus))
        return builder,value,authority,destination

    def test_manifest_discloses_projection_and_keeps_original_hash_privacy(self):
        builder,prepared,authority,destination=self.prepared()
        record=prepared.manifest['inputs'][0];payload=json.loads(prepared.payload)
        source=base64.b64decode(payload['inputs'][0]['content_b64'])
        self.assertIn('projection',record);self.assertEqual(SCHEMA,record['projection']['schema'])
        self.assertEqual('project',record['privacy']);self.assertGreater(record['size'],len(source)*10)
        self.assertEqual(hashlib.sha256(source).hexdigest(),record['projection']['projection_sha256'])
        self.assertNotIn(b'DO_NOT_EXPORT_OLD_DESCRIPTION',source)
        self.assertIn(b'MILESTONE-DEV',source)
        self.assertEqual(prepared.payload,builder.authorize_for_dispatch(prepared,authority=authority,target=destination).payload)

    def test_forged_projection_payload_is_rejected_even_with_recomputed_envelope_hash(self):
        builder,prepared,authority,destination=self.prepared()
        payload=json.loads(prepared.payload);payload['inputs'][0]['content_b64']=base64.b64encode(b'Injected body').decode()
        encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        manifest=dict(prepared.manifest);manifest['payload_sha256']=hashlib.sha256(encoded).hexdigest();manifest['payload_size']=len(encoded)
        raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        forged=PreparedContext(MappingProxyType(manifest),raw,encoded)
        with self.assertRaisesRegex(ValueError,'projection payload changed'):
            builder.authorize_for_dispatch(forged,authority=authority,target=destination)

    def test_unknown_projection_and_revoked_authority_are_rejected(self):
        from dataclasses import replace
        builder,prepared,authority,destination=self.prepared()
        with self.assertRaises(ValueError):
            builder.authorize_for_dispatch(prepared,authority=replace(authority,readable_entities=frozenset()),target=destination)
        with self.assertRaisesRegex(ValueError,'Unknown project context projection'):
            builder.prepare(manifest_id=str(uuid4()),run_id=str(uuid4()),authority=authority,target=destination,
                            project_inputs=(ProjectInput(next(iter(authority.readable_entities)),projection='other'),))

    def routed(self,bad=False):
        target=self.seed();service,request,calls=self.generate(target)
        request['content']='vytvoř nové ukoly: čtyři požadované funkce';request['task_plan']['edit_format']='patch'
        def transport(binding,raw):
            wire=json.loads(raw);calls.append(wire)
            marker='Source '+target+':\n';scope=json.JSONDecoder().raw_decode(wire['prompt'].split(marker,1)[1])[0]
            anchor=scope['insertion_anchor'];prefix=scope['id_prefix']
            additions=f'  - [ ] [{prefix}-BATCH] New feature\n    - type: batch\n'
            for i in range(4):additions+=f'    - [ ] [{prefix}-T{i+1}] Requested item {i+1}\n      - type: task\n'
            edits=[{'before':anchor,'after':anchor+additions}]
            if bad:edits=[{'before':'[x] [OLD-TASK]','after':'[ ] [OLD-TASK]'}]
            return {'model':binding.model,'response':json.dumps(dict(schema_version=1,kind='artifact-patch',title='Roadmap',edits=edits))}
        service.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport)
        return service,request,calls

    def test_new_task_request_gets_only_projection_and_remains_a_model_proposal(self):
        service,request,calls=self.routed();head=self.git.head();result=service.task_route(request)
        self.assertEqual(head,self.git.head());self.assertNotIn('DO_NOT_EXPORT_OLD_DESCRIPTION',calls[0]['prompt'])
        self.assertEqual(SCHEMA,result['projection']['file_edit_context']['schema'])
        preview=service.task_preview_file_edit(dict(project_id=ENTITY,task_id=request['task_id']))
        self.assertIn('Requested item 4',preview['body']);self.assertIn('[x] [OLD-TASK]',preview['body'])
        self.assertEqual(1,len(calls))

    def test_model_cannot_change_existing_task_through_append_projection(self):
        service,request,calls=self.routed(bad=True);head=self.git.head()
        with self.assertRaisesRegex(ValueError,'preserve its exact insertion anchor'):service.task_route(request)
        self.assertEqual(head,self.git.head());self.assertEqual([],service.task_outcomes(project_id=ENTITY))

    def test_creation_gate_does_not_select_ordinary_document_edits(self):
        self.assertTrue(requests_new_tasks('vytvoř nové ukoly: první ...'))
        self.assertTrue(requests_new_tasks('doplň ukol: ...'))
        self.assertFalse(requests_new_tasks('uprav existující úkol'))
