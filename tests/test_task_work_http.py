# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from tests import test_web_server as fixtures


class TaskWorkHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        code,data,_=self.f.create_project('Work context');self.assertEqual(code,200,data)
        self.pid=json.loads(data)['id'];self.node=self.f.root/'node.json'
        head=self.f.server.projects.plan_view(self.pid)['commit_id']
        self.head=Artifacts(self.node).save(dict(project_id=self.pid,artifact_id=main_todo_id(self.pid),
            base_head=head,title='Roadmap',body='- [ ] [TASK-A] Private task title\n- [ ] [TASK-X] X\n',new=True),str(uuid4()))['commit_id']

    def post(self,body,headers=None,code=200):
        actual,data,_=self.f.request(path='/v1/task-work',body=json.dumps(body),headers=headers)
        self.assertEqual(actual,code,data)
        return json.loads(data)

    def admin(self,body):
        code,data,_=self.f.request(path='/v1/administration',body=json.dumps(body))
        self.assertEqual(code,200,data);return json.loads(data)

    def test_authenticated_owner_project_roles_revocation_and_window_proof(self):
        owner=self.post({'action':'window'});handle={k:v for k,v in owner.items() if k.startswith('window_')}
        inspected=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        started=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**inspected))
        self.assertEqual(started['operation']['state'],'completed')
        state=self.admin({'action':'list'})
        state=self.admin(dict(action='create-user',expected_commit=state['commit_id'],name='Worker',node_role='member'))
        user=state['users'][0];headers={'Authorization':'Bearer '+state['access_key']}
        self.post(dict(handle,action='status'),headers,code=422)
        member=self.post({'action':'window'},headers);member={k:v for k,v in member.items() if k.startswith('window_')}
        self.post(dict(member,action='inspect',project_id=self.pid,task_id='TASK-X',expected_head=self.head),headers,code=403)
        self.post(dict(action='window',user_id=owner['user_id']),headers,code=422)
        state=self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],
            active=True,node_role='member',memberships={self.pid:'reader'}))
        self.post(dict(member,action='inspect',project_id=self.pid,task_id='TASK-X',expected_head=self.head),headers,code=403)
        state=self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],
            active=True,node_role='member',memberships={self.pid:'editor'}))
        head=self.f.server.projects.plan_view(self.pid)['commit_id']
        target=self.post(dict(member,action='inspect',project_id=self.pid,task_id='TASK-X',expected_head=head),headers)
        worked=self.post(dict(member,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-X',selected_checklist=None,**target),headers)
        active=next(s for s in worked['sessions'] if s['work_session_id']==worked['active_session_id'])
        self.assertEqual(active['user_id'],user['id'])
        self.assertNotEqual(started['active_session_id'],worked['active_session_id'])
        self.assertEqual(self.post(dict(handle,action='status'))['active_session_id'],started['active_session_id'])
        state=self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],
            active=True,node_role='member',memberships={}))
        blocked=self.post(dict(member,action='status'),headers)
        selected=blocked['sessions'][0]
        self.assertIsNone(selected['title']);self.assertNotIn('current_task',selected)
        self.post(dict(member,action='capture',context_revision=blocked['context_revision']),headers,code=422)
        paused=self.post(dict(member,action='pause',operation_id=str(uuid4()),context_revision=blocked['context_revision'],
            work_session_id=selected['work_session_id'],session_revision=selected['revision']),headers)
        self.assertIsNone(paused['active_session_id'])

    def test_restore_reply_replay_and_revoked_old_window_are_end_to_end(self):
        window=self.post({'action':'window'});handle={k:v for k,v in window.items() if k.startswith('window_')}
        view=self.post(dict(handle,action='status'))
        request=dict(handle,action='restore',operation_id=str(uuid4()),context_revision=view['context_revision'])
        recovered=self.post(request);again=self.post(request)
        self.assertEqual(recovered['window'],again['window'])
        self.assertEqual(recovered['context_revision'],again['context_revision'])
        self.post(dict(handle,action='status'),code=422)
        self.assertEqual(self.post(dict(again['window'],action='status'))['context_revision'],again['context_revision'])

    def test_native_save_import_delete_receipts_and_replay_keep_original_task(self):
        from spikes.source_import import request_from_bytes
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        def start(task, switch=False):
            view=self.post(dict(handle,action='status'))
            head=self.f.server.projects.plan_view(self.pid)['commit_id']
            pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id=task,expected_head=head))
            request=dict(handle,action='switch' if switch else 'start',operation_id=str(uuid4()),
                context_revision=view['context_revision'],project_id=self.pid,task_id=task,selected_checklist=None,**pin)
            if switch:
                session=next(s for s in view['sessions'] if s['work_session_id']==view['active_session_id'])
                request.update(work_session_id=session['work_session_id'],session_revision=session['revision'])
            return self.post(request)
        view=start('TASK-A');original=view['active_session_id']
        headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=view['context_revision']))}
        artifact=str(uuid4());operation=str(uuid4())
        document=dict(project_id=self.pid,artifact_id=artifact,base_head=self.f.server.projects.plan_view(self.pid)['commit_id'],
                      title='Inventory',body='# SECRET inventory\n',new=True)
        request=dict(operation_id=operation,document=document)
        code,data,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(request),headers=headers)
        self.assertEqual(code,200,data);receipt=json.loads(data)
        view=start('TASK-X',True)
        code,data,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(request),headers=headers)
        self.assertEqual(code,200,data);self.assertEqual(json.loads(data)['commit_id'],receipt['commit_id'])
        view=self.post(dict(handle,action='status'));old=next(s for s in view['sessions'] if s['work_session_id']==original)
        self.assertEqual(len(old['activities']),1);event=old['activities'][0]
        self.assertEqual(event['outcome'],'succeeded');self.assertNotIn('SECRET',json.dumps(event))
        self.assertTrue(any(ref.get('commit_id')==receipt['commit_id'] for ref in event['result_references']))
        self.assertFalse(old['current_task']['checked'])
        headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=view['context_revision']))}
        source=request_from_bytes(self.pid,self.f.server.projects.plan_view(self.pid)['commit_id'],'source.md',b'# source\n','Source','',[],'project')
        code,data,_=self.f.request(path='/v1/sources/import',body=json.dumps(dict(operation_id=str(uuid4()),source=source)),headers=headers)
        self.assertEqual(code,200,data)
        current=self.post(dict(handle,action='status'))
        active=next(s for s in current['sessions'] if s['work_session_id']==current['active_session_id'])
        self.assertEqual(active['activities'][0]['kind'],'source-import')
        self.assertTrue(any(ref.get('artifact_id')==source['artifact_id'] for ref in active['activities'][0]['request_references']))
        self.assertEqual(active['task_records'],[])
        head=json.loads(data)['commit_id']
        code,data,_=self.f.request(path='/v1/artifacts/delete/preview',body=json.dumps(dict(project_id=self.pid,artifact_id=artifact,expected_head=head)))
        self.assertEqual(code,200,data);preview=json.loads(data)
        code,data,_=self.f.request(path='/v1/artifacts/delete/confirm',body=json.dumps(dict(project_id=self.pid,artifact_id=artifact,
            base_head=head,preview_sha256=preview['preview_sha256'],operation_id=str(uuid4()))),headers=headers)
        self.assertEqual(code,200,data)
        current=self.post(dict(handle,action='status'))
        active=next(s for s in current['sessions'] if s['work_session_id']==current['active_session_id'])
        self.assertEqual([e['kind'] for e in active['activities']],['source-import','artifact-delete'])
        # A stale pinned context rejects before entering the native writer.
        before=self.f.server.projects.plan_view(self.pid)['commit_id']
        bad=dict(request,operation_id=str(uuid4()),document=dict(document,base_head=before,artifact_id=str(uuid4())))
        code,_,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(bad),headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=-1))})
        self.assertEqual(code,422)
        self.assertEqual(self.f.server.projects.plan_view(self.pid)['commit_id'],before)

    def test_stream_terminal_receipt_is_recorded_before_delivery_after_task_switch(self):
        from unittest.mock import patch
        from spikes.task_work import TaskWork
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin))
        original=view['active_session_id'];headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=view['context_revision']))}
        request=dict(project_id=self.pid,expected_head=self.f.server.projects.plan_view(self.pid)['commit_id'],
            **{k:str(uuid4()) for k in ['thread_id','turn_id','message_id','run_id','manifest_id','assistant_message_id']},
            selected_message_ids=[],content='SECRET PROMPT',privacy='project',created_at='2026-11-21T15:00:00Z')
        def send(payload,delta,status):
            # Another user action switches the context while the native run is in flight.
            work=TaskWork(self.node);current=work.status(handle)
            head=work.projects.plan_view(self.pid)['commit_id'];pin=work.inspect(handle,self.pid,'TASK-X',head)
            session=next(s for s in current['sessions'] if s['work_session_id']==original)
            work.execute(dict(handle,action='switch',operation_id=str(uuid4()),context_revision=current['context_revision'],
                project_id=self.pid,task_id='TASK-X',selected_checklist=None,work_session_id=original,session_revision=session['revision'],**pin))
            delta('SECRET RESPONSE')
            return {'turn':{'turn_id':payload['turn_id'],'run_id':payload['run_id'],'state':'completed'},'content':'SECRET RESPONSE'}
        with patch.object(self.f.server.chat_service,'send_stream',side_effect=send) as native:
            code,data,_=self.f.request(path='/v1/chat/send-stream',body=json.dumps(request),headers=headers)
            self.assertEqual(code,200,data);self.assertIn(b'"type":"result"',data);self.assertEqual(native.call_count,1)
        current=self.post(dict(handle,action='status'));old=next(s for s in current['sessions'] if s['work_session_id']==original)
        event=old['activities'][0];self.assertEqual(event['outcome'],'succeeded')
        self.assertTrue(any(ref.get('run_id')==request['run_id'] for ref in event['result_references']))
        self.assertNotIn('SECRET',json.dumps(event))
        new=next(s for s in current['sessions'] if s['work_session_id']==current['active_session_id'])
        self.assertEqual(new['task_id'],'TASK-X');self.assertEqual(new['activities'],[])

    def test_failed_activity_finalization_preserves_native_success_and_unknown_intent(self):
        from unittest.mock import patch
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin))
        request=dict(operation_id=str(uuid4()),document=dict(project_id=self.pid,artifact_id=str(uuid4()),
            base_head=self.f.server.projects.plan_view(self.pid)['commit_id'],title='Inventory',body='# Inventory\n',new=True))
        headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=view['context_revision']))}
        with patch('spikes.task_activities.TaskActivities.finish',side_effect=OSError('disk unavailable')):
            code,data,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(request),headers=headers)
            self.assertEqual(code,200,data)
        committed=json.loads(data)['commit_id']
        current=self.post(dict(handle,action='status'));self.assertEqual(current['sessions'][0]['activities'][0]['outcome'],'unknown')
        code,data,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(request),headers=headers)
        self.assertEqual(code,200,data);self.assertEqual(json.loads(data)['commit_id'],committed)
        current=self.post(dict(handle,action='status'));self.assertEqual(current['sessions'][0]['activities'][0]['outcome'],'succeeded')

    def test_explicit_task_input_checks_digest_scope_and_privacy_before_model_dispatch(self):
        from unittest.mock import patch
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin))
        context=self.post(dict(handle,action='analysis-context',context_revision=view['context_revision']))
        base=dict(project_id=self.pid,expected_head=view['sessions'][0]['validated_head'],selected_message_ids=[],
            content=context['text']+'\nAnalyze',privacy=context['privacy'],created_at='2026-11-21T18:00:00Z')
        with patch.object(self.f.server.chat_service,'send',return_value={'thread':{},'state':'completed'}) as native:
            for privacy,declared,expected in [('public',context['sha256'],422),('project','0'*64,422),('project',None,422),('project',context['sha256'],200)]:
                request=dict(base,privacy=privacy,**{k:str(uuid4()) for k in ['thread_id','turn_id','message_id','run_id','manifest_id','assistant_message_id']})
                envelope=dict(handle,context_revision=view['context_revision'])
                if declared is not None:envelope['task_input_sha256']=declared
                code,data,_=self.f.request(path='/v1/chat/send',body=json.dumps(request),headers={'X-FPW-Task-Work':json.dumps(envelope)})
                self.assertEqual(code,expected,data)
            self.assertEqual(native.call_count,1)
        state=self.post(dict(handle,action='status'));events=state['sessions'][0]['activities']
        self.assertEqual(len(events),4);self.assertEqual(events[-1]['task_input']['sha256'],context['sha256'])
        self.assertFalse(state['sessions'][0]['current_task']['checked'])

    def test_existing_artifact_can_be_attached_with_explicit_confirmation(self):
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin));sid=view['active_session_id']
        artifact=str(uuid4())
        receipt=Artifacts(self.node).save(dict(project_id=self.pid,artifact_id=artifact,
            base_head=view['sessions'][0]['validated_head'],title='Existing inventory',body='# Existing bytes\n',new=True),str(uuid4()))
        options=self.post(dict(handle,action='record-attachment-options',work_session_id=sid))
        self.assertIn(artifact,[item['id'] for item in options['items']])
        self.assertEqual(self.post(dict(handle,action='status'))['sessions'][0]['task_records'],[])
        request=dict(handle,action='record-attach',operation_id=str(uuid4()),work_session_id=sid,
            artifact_id=artifact,comment='Attached earlier inventory',selected_checklist=None,
            expected_head=options['expected_head'],privacy=options['privacy'])
        result=self.post(request);record=result['sessions'][0]['task_records'][0]
        self.assertEqual(record['events'][0]['kind'],'artifact-attach')
        self.assertEqual(record['outputs'][0]['commit_id'],receipt['commit_id'])
        self.assertEqual(result['sessions'][0]['activities'],[])
        self.assertEqual(self.post(request)['operation']['result'],result['operation']['result'])
        self.post(dict(request,artifact_id=str(uuid4())),code=422)
        self.assertFalse(result['sessions'][0]['current_task']['checked'])

    def test_reviewed_record_http_preserves_pin_history_privacy_and_human_acceptance(self):
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin));sid=view['active_session_id']
        artifact=str(uuid4());request=dict(operation_id=str(uuid4()),document=dict(project_id=self.pid,artifact_id=artifact,
            base_head=view['sessions'][0]['validated_head'],title='Inventory',body='# Original inventory\n',new=True))
        code,data,_=self.f.request(path='/v1/artifacts/editor/save',body=json.dumps(request),headers={'X-FPW-Task-Work':json.dumps(dict(handle,context_revision=view['context_revision']))})
        self.assertEqual(code,200,data)
        state=self.post(dict(handle,action='status'));session=state['sessions'][0];event=session['activities'][0]
        publish=dict(handle,action='record-publish',operation_id=str(uuid4()),work_session_id=sid,
            event_ids=[event['event_id']],offer_revisions=[event['offer']['revision']],comment='Verified inventory',
            selected_checklist=None,expected_head=session['validated_head'],privacy='project')
        self.assertEqual(session['task_records'],[])
        self.assertNotEqual(event['offer']['state'],'confirmed')
        confirmed=self.post(publish);record=confirmed['sessions'][0]['task_records'][0]
        git=self.f.server.projects.repository(self.pid)
        body=git.snapshot(git.head())['artifacts/'+main_todo_id(self.pid)+'/content.md'].decode()
        self.assertIn('Verified inventory',body)
        self.assertIn('artifacts/'+artifact+'/content.md',body)
        self.assertNotIn('Original inventory',body)

        self.assertEqual(record['revisions'][0]['comment'],'Verified inventory')
        self.assertFalse(confirmed['sessions'][0]['current_task']['checked'])
        self.assertEqual(self.post(publish)['operation']['result'],confirmed['operation']['result'])
        result=self.post(dict(handle,action='record-output',project_id=self.pid,record_id=record['id'],output_index=0,version='original',page=1))
        self.assertIn('Original inventory',result['text'])
        amended=self.post(dict(handle,action='record-amend',operation_id=str(uuid4()),work_session_id=sid,
            record_id=record['id'],record_revision=1,comment='Corrected note',selected_checklist=None,expected_head=record['validated_head']))
        history=amended['sessions'][0]['task_records'][0]['revisions']
        self.assertEqual([r['comment'] for r in history],['Verified inventory','Corrected note'])
        other={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        self.post(dict(publish,**other),code=422)

    def test_saved_work_reclaim_and_human_completion_use_authenticated_owner(self):
        handle={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        pin=self.post(dict(handle,action='inspect',project_id=self.pid,task_id='TASK-A',expected_head=self.head))
        view=self.post(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
            project_id=self.pid,task_id='TASK-A',selected_checklist=None,**pin))
        saved=self.post({'action':'history'})['sessions'][0]
        state=self.admin({'action':'list'})
        state=self.admin(dict(action='create-user',expected_commit=state['commit_id'],name='Other worker',node_role='member'))
        headers={'Authorization':'Bearer '+state['access_key']};user=state['users'][0]
        self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],active=True,node_role='member',memberships={self.pid:'editor'}))
        self.assertEqual(self.post({'action':'history'},headers)['sessions'],[])
        other={k:v for k,v in self.post({'action':'window'},headers).items() if k.startswith('window_')}
        reclaim=dict(other,action='reclaim',operation_id=str(uuid4()),context_revision=0,work_session_id=saved['work_session_id'],
            session_revision=saved['revision'],target_context_revision=saved['target_context_revision'],confirmed=True)
        self.post(reclaim,headers,code=422)
        fresh={k:v for k,v in self.post({'action':'window'}).items() if k.startswith('window_')}
        result=self.post(dict(reclaim,**fresh));self.post(dict(handle,action='status'),code=422)
        selected=next(s for s in result['sessions'] if s['work_session_id']==saved['work_session_id'])
        complete=dict(result['window'],action='complete',operation_id=str(uuid4()),context_revision=result['context_revision'],
            work_session_id=selected['work_session_id'],session_revision=selected['revision'],expected_head=selected['validated_head'],confirmed=True)
        self.post(dict(complete,confirmed=False),code=422)
        finished=self.post(complete);self.assertTrue(finished['sessions'][0]['current_task']['checked'])
        self.assertEqual(finished['sessions'][0]['state'],'closed');self.assertIsNone(finished['active_session_id'])

    def test_roadmap_records_are_visible_to_project_reader_without_work_session(self):
        self.test_reviewed_record_http_preserves_pin_history_privacy_and_human_acceptance()
        head=self.f.server.projects.plan_view(self.pid)['commit_id']
        query=dict(action='record-list',project_id=self.pid,task_id='TASK-A',expected_head=head)
        own=self.post(query);self.assertEqual(len(own['records']),1);self.assertEqual(len(own['activities']),1)
        state=self.admin({'action':'list'})
        state=self.admin(dict(action='create-user',expected_commit=state['commit_id'],name='Read only reviewer',node_role='member'))
        headers={'Authorization':'Bearer '+state['access_key']};user=state['users'][0]
        state=self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],active=True,node_role='member',memberships={self.pid:'reader'}))
        result=self.post(query,headers);self.assertEqual(len(result['records']),1);self.assertEqual(result['activities'],[])
        record=result['records'][0]
        preview=self.post(dict(action='record-preview',project_id=self.pid,task_id='TASK-A',expected_head=head,record_id=record['id'],output_index=0,version='original',page=1),headers)
        self.assertIn('Original inventory',preview['text'])
        self.admin(dict(action='update-user',expected_commit=state['commit_id'],user_id=user['id'],active=True,node_role='member',memberships={}))
        self.post(query,headers,code=422)
