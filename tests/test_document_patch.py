# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4

from spikes.document_patch import apply_patch, requires_patch, LARGE_BYTES, LARGE_LINES
from spikes.ai_outcome import AITaskOutcome
from spikes.ollama_backend import OllamaAdapter
from spikes.task_plan import ExplicitTaskPlan
from tests import test_task_file_edit as fixtures
from tests.fixtures import ENTITY


class ExactPatchTests(unittest.TestCase):
    def test_independent_edits_preserve_unicode_crlf_order_and_final_newline(self):
        original='# Žluťoučký\r\n\r\nPrvní.\r\nDruhý.\r\n'
        self.assertEqual('# Žluťoučký\r\n\r\nZměna.\r\nDruhý.\r\nKonec.',apply_patch(original,[
            {'before':'Druhý.\r\n','after':'Druhý.\r\nKonec.'},
            {'before':'První.','after':'Změna.'}]))
        self.assertEqual('',apply_patch('Remove',[{'before':'Remove','after':''}]))
        self.assertEqual('New',apply_patch('',[{'before':'','after':'New'}]))

    def test_ambiguous_missing_overlapping_sequential_and_empty_anchors_fail_closed(self):
        cases=[('same same',[{'before':'same','after':'new'}]),
               ('aaaa',[{'before':'aaa','after':'new'}]),
               ('original',[{'before':'absent','after':'new'}]),
               ('abcdef',[{'before':'abc','after':'x'},{'before':'bcd','after':'y'}]),
               ('original',[{'before':'original','after':'next'},{'before':'next','after':'end'}]),
               ('original',[{'before':'','after':'new'}])]
        for original,edits in cases:
            with self.subTest(edits=edits),self.assertRaises(ValueError):apply_patch(original,edits)

    def test_closed_bounded_patch_contract(self):
        good=dict(schema_version=1,kind='artifact-patch',title='Title',edits=[{'before':'a','after':'b'}])
        self.assertEqual(good,AITaskOutcome.parse(good).serialize())
        for edits in [[],[{'before':'a','after':'a'}],[{'before':'x'*4097,'after':'b'}],
                      [{'before':'a','after':'b','path':'../other'}],
                      [{'before':'a','after':'b\0'}],[{'before':'a','after':'b'}]*65,
                      [{'before':'a','after':'b'*65536}]]:
            with self.subTest(edits=str(edits)[:80]),self.assertRaises(ValueError):AITaskOutcome.parse(good|{'edits':edits})
        with self.assertRaises(ValueError):AITaskOutcome.parse(good|{'path':'other.md'})

    def test_patch_diagnostics_distinguish_noop_size_anchor_and_overlap(self):
        from spikes.document_patch import PatchValidationError
        cases=[('original',[{'before':'original','after':'original'}],'patch-no-change'),
               ('x'*4097,[{'before':'x'*4097,'after':'new'}],'patch-anchor-too-large'),
               ('original',[{'before':'absent','after':'new'}],'patch-anchor-mismatch'),
               ('abcdef',[{'before':'abc','after':'x'},{'before':'bcd','after':'y'}],'patch-overlap')]
        for original,edits,code in cases:
            with self.subTest(code=code),self.assertRaises(PatchValidationError) as error:
                apply_patch(original,edits)
            self.assertEqual(code,error.exception.code)

    def test_large_threshold_counts_bytes_and_lines_at_exact_boundary(self):
        self.assertFalse(requires_patch('x'*(LARGE_BYTES-1)))
        self.assertTrue(requires_patch('x'*LARGE_BYTES))
        self.assertTrue(requires_patch('ž'*(LARGE_BYTES//2)))
        self.assertFalse(requires_patch('x\n'*(LARGE_LINES-1)))
        self.assertTrue(requires_patch('x\n'*LARGE_LINES))


class PatchTaskTests(unittest.TestCase):
    setUp=fixtures.FileEditTests.setUp
    request=fixtures.FileEditTests.request
    pin_run_choice=fixtures.FileEditTests.pin_run_choice
    route_request=fixtures.FileEditTests.route_request
    create_document=fixtures.FileEditTests.create_document
    generate=fixtures.FileEditTests.generate
    confirmation=fixtures.FileEditTests.confirmation

    def patch_task(self, original='Before\nKeep\n', edits=None, edit_format='patch'):
        target=self.create_document(original)
        service,request,calls=self.generate(target)
        if edit_format is not None:request['task_plan']['edit_format']=edit_format
        edits=edits if edits is not None else [{'before':'Before\n','after':'After\n'}]
        def transport(binding,raw):
            calls.append(json.loads(raw))
            return dict(model=binding.model,response=json.dumps(dict(schema_version=1,kind='artifact-patch',title='Rename ignored',edits=edits)))
        service.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport)
        return service,request,calls

    def preview(self,service,request,**fields):
        return service.task_preview_file_edit(dict(project_id=ENTITY,task_id=request['task_id'],**fields))

    def test_patch_is_pinned_validated_then_opened_in_editor_without_writes(self):
        service,request,calls=self.patch_task();head=self.git.head()
        routed=service.task_route(request)
        self.assertEqual(head,self.git.head())
        self.assertEqual('artifact-patch',routed['projection']['outcome']['kind'])
        self.assertEqual('Selected document',routed['projection']['outcome']['title'])
        self.assertIn('never the complete document',calls[0]['prompt'])
        self.assertEqual(['artifact-patch'],calls[0]['format']['properties']['kind']['enum'])
        preview=self.preview(service,request)
        self.assertEqual('After\nKeep\n',preview['body'])
        self.assertIn('-Before',preview['diff']);self.assertEqual(head,self.git.head())
        edited=self.preview(service,request,body='Edited by user\nKeep\n')
        confirmed=self.confirmation(edited);result=service.task_confirm_file_edit(confirmed)
        self.assertEqual('completed',result['state']);self.assertEqual(result,service.task_confirm_file_edit(confirmed))
        self.assertEqual('Edited by user\nKeep\n',self.git.snapshot(self.git.head())[f'artifacts/{confirmed["artifact_id"]}/content.md'].decode())
        self.assertEqual('1',self.git.run('rev-list','--count',head+'..HEAD').stdout.strip())

    def test_large_input_forces_patch_even_if_full_or_legacy_requested(self):
        for original in ['Before\n'+'x'*(LARGE_BYTES), 'Before\n'+'line\n'*LARGE_LINES]:
            for mode in ['full',None]:
                with self.subTest(mode=mode,length=len(original)):
                    service,request,calls=self.patch_task(original,edit_format=mode)
                    service.task_route(request)
                    self.assertEqual(['artifact-patch'],calls[0]['format']['properties']['kind']['enum'])
                    self.assertEqual(original.replace('Before\n','After\n',1),self.preview(service,request)['body'])

    def test_large_input_cannot_return_full_document_as_fallback(self):
        service,request,calls=self.generate(self.create_document('Before\n'+'x'*LARGE_BYTES))
        request['task_plan']['edit_format']='full';head=self.git.head()
        with self.assertRaises(ValueError):service.task_route(request)
        self.assertEqual(head,self.git.head());self.assertEqual(1,len(calls))

    def test_small_full_mode_and_legacy_serialization_remain_compatible(self):
        service,request,calls=self.generate()
        plan=ExplicitTaskPlan.parse(request['task_plan']);self.assertEqual(request['task_plan'],plan.serialize())
        request['task_plan']['edit_format']='full';service.task_route(request)
        self.assertEqual(['artifact-draft'],calls[0]['format']['properties']['kind']['enum'])
        self.assertEqual('Proposed body\n',self.preview(service,request)['body'])
        with self.assertRaises(ValueError):ExplicitTaskPlan.parse(request['task_plan']|{'edit_format':'fuzzy'})

    def test_bad_anchors_or_invalid_graph_never_become_prepared_outcomes(self):
        for edits in [[{'before':'missing','after':'new'}],[{'before':'Before','after':'new'},{'before':'Before\n','after':'other'}]]:
            with self.subTest(edits=edits):
                service,request,_=self.patch_task(edits=edits);head=self.git.head()
                with self.assertRaises(ValueError):service.task_route(request)
                self.assertEqual(head,self.git.head())
                self.assertFalse(service.task_outcomes(project_id=ENTITY,thread_id=request['thread_id']))

    def test_stale_patch_and_cancel_never_write(self):
        service,request,_=self.patch_task();service.task_route(request)
        self.create_document('Concurrent commit');head=self.git.head()
        with self.assertRaises(ValueError):self.preview(service,request)
        self.assertEqual('cancelled',service.task_cancel(dict(task_id=request['task_id']))['state'])
        self.assertEqual(head,self.git.head())

    def test_patch_approval_survives_lost_reply_without_applying_twice(self):
        service,request,_=self.patch_task();service.task_route(request)
        confirmation=self.confirmation(self.preview(service,request))
        def stop(stage):
            if stage=='file-edit-before-outcome':raise RuntimeError('lost response')
        with self.assertRaises(RuntimeError):service.task_confirm_file_edit(confirmation,checkpoint=stop)
        head=self.git.head()
        restored=self.preview(service,request)
        self.assertTrue(restored['pending_confirmation']);self.assertEqual(confirmation,restored['confirmation'])
        service.task_confirm_file_edit(confirmation);self.assertEqual(head,self.git.head())

    def test_patch_cannot_introduce_roadmap_cycle(self):
        from spikes.artifacts import Artifacts
        from spikes.markdown_documents import main_todo_id
        target=main_todo_id(ENTITY)
        original='- [ ] [TASK-A] A\n- [ ] [TASK-B] B\n  - depends_on: TASK-A\n'
        Artifacts(self.node_path).save(dict(project_id=ENTITY,artifact_id=target,new=True,
            title='Roadmap',body=original,base_head=self.git.head()),str(uuid4()))
        service,request,_=self.generate(target);request['task_plan']['edit_format']='patch'
        def transport(binding,raw):
            return dict(model=binding.model,response=json.dumps(dict(schema_version=1,kind='artifact-patch',title='Roadmap',
                edits=[{'before':'- [ ] [TASK-A] A','after':'- [ ] [TASK-A] A\n  - depends_on: TASK-B'}])))
        service.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport)
        head=self.git.head()
        with self.assertRaises(ValueError):service.task_route(request)
        self.assertEqual(head,self.git.head())

    def test_process_crash_during_native_patch_write_resumes_original_body_once(self):
        import subprocess
        import sys
        from spikes.chat_service import ChatService
        from spikes.projects import Projects
        service,request,_=self.patch_task();service.task_route(request)
        confirmation=self.confirmation(self.preview(service,request));before=self.git.head()
        code='''
import json,os,sys
from spikes.chat_service import ChatService
from spikes.projects import Projects
service=ChatService(sys.argv[1],Projects(sys.argv[1]),state_dir=sys.argv[2])
def stop(stage):
 if stage=='files-applied':os._exit(73)
service.task_confirm_file_edit(json.loads(sys.argv[3]),checkpoint=stop)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.node_path),str(self.chat_state),json.dumps(confirmation)],capture_output=True,timeout=30)
        self.assertEqual(73,result.returncode,result.stderr)
        restarted=ChatService(self.node_path,Projects(self.node_path),state_dir=self.chat_state)
        restored=self.preview(restarted,request)
        self.assertTrue(restored['pending_confirmation']);self.assertEqual('After\nKeep\n',restored['body'])
        restarted.task_confirm_file_edit(confirmation)
        self.assertEqual('1',self.git.run('rev-list','--count',before+'..HEAD').stdout.strip())
        self.assertEqual('',self.git.run('status','--porcelain').stdout)

    def test_stream_explains_unchanged_patch_without_reporting_unknown_transport(self):
        from spikes.desktop_ui import DesktopHandler
        from spikes.local_api import running_api
        from spikes.ollama_backend import OllamaRuns
        from tests import test_local_api
        service,request,_=self.patch_task();head=self.git.head();calls=[]
        def stream(binding,raw,delta,status,*,control):
            calls.append(json.loads(raw))
            return dict(model=binding.model,response=json.dumps(dict(schema_version=1,kind='artifact-patch',title='Title',edits=[{'before':'Before\n','after':'Before\n'}])))
        service.adapter_factory=lambda runs:OllamaAdapter(runs,stream_transport=stream)
        with running_api('http',handler=DesktopHandler) as server:
            server.chat_service=service;server.projects=service.projects
            raw=test_local_api.LocalAPITests().request(server,path='/v1/tasks/route-stream',body=json.dumps(request).encode())
        events=[json.loads(line) for line in raw.split(b'\r\n\r\n',1)[1].splitlines()]
        error=next(event for event in events if event['type']=='error')
        self.assertEqual('patch-no-change',error['diagnostic'])
        self.assertEqual('invalid-proposal',error['outcome']);self.assertEqual(422,error['status'])
        self.assertIn('text před a po je stejný',error['error'])
        self.assertNotIn('Původní běh',error['error'])
        self.assertEqual(1,len(calls));self.assertEqual(head,self.git.head())
        self.assertEqual(4096,calls[0]['format']['properties']['edits']['items']['properties']['before']['maxLength'])
        self.assertEqual('succeeded',OllamaRuns(self.chat_state).get(request['run_id'])['state'])
        self.assertEqual([],service.task_outcomes(project_id=ENTITY,thread_id=request['thread_id']))
