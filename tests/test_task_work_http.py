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
