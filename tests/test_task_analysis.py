# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import hashlib
import json
import unittest
from uuid import uuid4
from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.task_analysis import BEGIN,validate_input
from spikes.task_activities import TaskActivities
from spikes.task_records import TaskRecords
from tests import test_task_work as fixtures

class TaskAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TaskWorkTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.f.save('- [ ] [TASK-A] Analyze inventory\n  - type: task\n  - [ ] Inspect network\n- [ ] [TASK-X] UNSELECTED PRIVATE SIBLING\n')
        self.work=self.f.service;self.handle=self.f.handle
        request=self.f.start_request();request['selected_checklist']=0
        self.view=self.work.execute(request);self.activities=TaskActivities(self.work)

    def context(self):
        return self.work.execute(dict(self.handle,action='analysis-context',context_revision=self.work.status(self.handle)['context_revision']))

    def request(self,context):
        return dict(project_id=self.f.f.pid,expected_head=self.work.projects.repository(self.f.f.pid).head(),thread_id=str(uuid4()),
            turn_id=str(uuid4()),message_id=str(uuid4()),run_id=str(uuid4()),manifest_id=str(uuid4()),assistant_message_id=str(uuid4()),
            selected_message_ids=[],content=context['text']+'\n\nAnalyze possible solutions.',privacy=context['privacy'],created_at='2026-11-21T18:00:00Z')

    def test_context_is_scoped_read_only_and_pins_selected_checklist(self):
        before=self.work.projects.repository(self.f.f.pid).head();context=self.context()
        self.assertIn('Inspect network',context['text']);self.assertNotIn('UNSELECTED PRIVATE SIBLING',context['text'])
        self.assertEqual(context['sha256'],hashlib.sha256(context['text'].encode()).hexdigest())
        self.assertEqual(json.loads(context['text'].split('\n',1)[1].rsplit('\n',1)[0])['selected_checklist'],0)
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),before)
        self.assertEqual(self.activities.for_session(self.handle,self.view['active_session_id']),[])

    def test_dispatch_context_cannot_lower_privacy_or_follow_changed_task(self):
        context=self.context();request=self.request(context)
        event=self.activities.begin(self.handle,self.view['context_revision'],'/v1/chat/send',request)
        with self.assertRaises(ValueError):validate_input(self.activities,event,dict(request,privacy='public'),context['sha256'])
        with self.assertRaises(ValueError):validate_input(self.activities,event,request,'0'*64)
        validate_input(self.activities,event,request,context['sha256'])
        self.assertEqual(self.activities.for_session(self.handle,self.view['active_session_id'])[0]['task_input']['sha256'],context['sha256'])
        self.f.f.save('- [ ] [TASK-A] Changed requirements\n  - [ ] Inspect network\n- [ ] [TASK-X] Other\n')
        with self.assertRaises(ValueError):self.context()
        self.work.can_write=lambda pid:False
        with self.assertRaises(ValueError):validate_input(self.activities,event,request,context['sha256'])

    def test_local_only_task_context_is_rejected_by_external_manifest_boundary(self):
        from spikes.context_builder import ContextBuilder,Authority,Target,AdHocInput
        from spikes.task_record_schema import encoded
        ws=self.work.projects.workspace(self.f.f.pid);head=ws.git.head()
        path='artifacts/'+main_todo_id(self.f.f.pid)+'/metadata.json'
        meta=json.loads(ws.git.snapshot(head)[path]);meta['privacy']='local-only'
        ws.transact(str(uuid4()),dict(action='test-classification'),lambda workspace:({path:encoded(meta)},'Test author','test@local.invalid','Classify test task'),expected_head=head)
        context=self.context();self.assertEqual(context['privacy'],'local-only')
        builder=ContextBuilder(ws,self.f.f.pid)
        authority=Authority('test-task-analysis',self.work.user_id,self.work.node_id,'task-analysis-v1',frozenset())
        with self.assertRaises(ValueError):builder.prepare(manifest_id=str(uuid4()),run_id=str(uuid4()),authority=authority,
            target=Target(str(uuid4()),'one','external-provider','test-target','test-model'),
            ad_hoc_inputs=(AdHocInput(str(uuid4()),context['text'].encode(),context['privacy']),))

    def test_model_manifest_saved_output_and_confirmed_record_keep_run_and_conversation(self):
        from spikes.chat_service import ChatService
        from spikes.chat_records import ChatRecords
        from tests.test_chat_service import FakeAdapter
        calls=[];chat=ChatService(self.f.f.node, self.work.projects,adapter_factory=lambda runs:FakeAdapter(runs,calls))
        binding=dict(schema_version=1,binding_id=str(uuid4()),revision='one',adapter='ollama',boundary='same-node',endpoint='http://127.0.0.1:11434',model='fake-test',target_id='local-process')
        chat.configure(binding)
        from unittest.mock import patch
        from spikes.ollama_backend import OllamaAdapter
        with patch.object(OllamaAdapter,'discover_models',return_value=['fake-test']):chat.refresh_ollama_models(binding)
        selection=chat.model_selection_status();offer=next(item for item in selection['offers'] if item['adapter_id']=='ollama' and item['provider_model_id']=='fake-test')
        context=self.context();self.assertEqual(calls,[]);request=self.request(context)
        request['run_choice']=dict(mode='brainstorming',adapter='ollama',model='fake-test',selection_revision=selection['revision'],offer_id=offer['offer_id'])
        event=self.activities.begin(self.handle,self.view['context_revision'],'/v1/chat/send',request)
        validate_input(self.activities,event,request,context['sha256'])
        result=chat.send(**request);self.activities.finish(event,200,result)
        payload=json.loads(calls[0][1].payload)
        self.assertIn(context['text'],'\n'.join(base64.b64decode(part['content_b64']).decode() for part in payload['inputs']))
        thread=result['thread'];answer=next(item for item in thread['messages'] if item['role']=='assistant')
        output=dict(project_id=self.f.f.pid,thread_id=thread['thread_id'],expected_thread_revision=thread['revision'],
            expected_head=self.work.projects.repository(self.f.f.pid).head(),artifact_id=str(uuid4()),title='Analysis result',
            body=answer['content'],created_at=request['created_at'],message_ids=[answer['message_id']],snapshot_id=None,snapshot_sha256=None)
        operation=str(uuid4());output_request=dict(output,operation_id=operation)
        saved_event=self.activities.begin(self.handle,self.work.status(self.handle)['context_revision'],'/v1/chat/output',output_request)
        receipt=ChatRecords(self.f.f.node,self.work.projects).publish_output(output,operation)
        self.activities.finish(saved_event,200,receipt)
        events=self.activities.for_session(self.handle,self.view['active_session_id'])
        service=TaskRecords(self.work)
        service.execute(dict(self.handle,action='record-publish',operation_id=str(uuid4()),work_session_id=self.view['active_session_id'],
            event_ids=[saved_event],offer_revisions=[next(e['offer']['revision'] for e in events if e['event_id']==saved_event)],comment='Analysis verified',selected_checklist=0,
            expected_head=self.work.projects.repository(self.f.f.pid).head(),privacy='project'))
        record=service.for_session(self.handle,self.view['active_session_id'])[0][0]
        self.assertTrue(any(ref.get('run_id')==request['run_id'] for e in record['events'] for ref in e['request_references']+e['result_references']))
        self.assertEqual(record['outputs'][0]['artifact_id'],output['artifact_id'])
        self.assertFalse(self.f.active()['current_task']['checked'])
