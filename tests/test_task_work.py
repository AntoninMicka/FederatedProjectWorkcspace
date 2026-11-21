# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_work import TaskWork
from tests import test_task_queue as fixtures


class TaskWorkTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskQueueTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.user = ProjectCreation(self.f.node).author_id()
        self.service = TaskWork(self.f.node, self.user)
        self.handle = {k:v for k,v in self.service.create_window().items() if k.startswith('window_')}

    def status(self, handle=None):
        return self.service.status(handle or self.handle)

    def active(self, view=None):
        view = view or self.status()
        return next(s for s in view['sessions'] if s['work_session_id']==view['active_session_id'])

    def start_request(self, task='TASK-A', action='start', handle=None):
        handle = handle or self.handle; view = self.status(handle)
        head = Projects(self.f.node).repository(self.f.pid).head()
        target = self.service.inspect(handle,self.f.pid,task,head)
        request = dict(handle,action=action,operation_id=str(uuid4()),context_revision=view['context_revision'],
                       project_id=self.f.pid,task_id=task,selected_checklist=None,**target)
        if action=='switch':
            session=self.active(view);request.update(work_session_id=session['work_session_id'],session_revision=session['revision'])
        return request

    def change(self, action, session=None, **extra):
        view=self.status();session=session or self.active(view)
        return self.service.execute(dict(self.handle,action=action,operation_id=str(uuid4()),
            context_revision=view['context_revision'],work_session_id=session['work_session_id'],
            session_revision=session['revision'],**extra))

    def test_start_without_checklist_pause_resume_close_and_proposal_are_distinct(self):
        request=self.start_request();view=self.service.execute(request)
        self.assertEqual(view['operation']['state'],'completed')
        session=self.active(view);self.assertFalse(session['blocked'])
        self.assertEqual(session['definition_pin']['project_commit'],Projects(self.f.node).repository(self.f.pid).head())
        self.assertNotEqual(session['requested_pin']['project_commit'],session['definition_pin']['project_commit'])
        self.assertEqual(session['current_task']['status'],'in progress');self.assertFalse(session['current_task']['checked'])
        self.assertEqual(session['current_task']['checklist'],[])
        head=Projects(self.f.node).repository(self.f.pid).head()
        paused=self.change('pause');self.assertIsNone(paused['active_session_id'])
        paused_session=paused['sessions'][0];self.assertEqual(paused_session['state'],'paused')
        resumed=self.change('resume',paused_session);self.assertEqual(self.active(resumed)['work_session_id'],session['work_session_id'])
        proposal=self.change('propose-completion',comment='Hotový návrh, čeká na review.')
        current=self.active(proposal)
        self.assertEqual(current['completion_proposals'][0]['state'],'pending')
        self.assertFalse(current['current_task']['checked'])
        self.assertEqual(head,Projects(self.f.node).repository(self.f.pid).head())
        closed=self.change('close');self.assertIsNone(closed['active_session_id'])
        self.assertEqual(closed['sessions'][0]['state'],'closed')
        with self.assertRaises(ValueError):self.change('resume',closed['sessions'][0])
        self.assertEqual(Projects(self.f.node).plan_view(self.f.pid)['plan']['nodes'][0]['status'],'in progress')

    def test_replay_and_stale_context_and_different_request_under_same_id(self):
        request=self.start_request();first=self.service.execute(request)
        head=Projects(self.f.node).repository(self.f.pid).head()
        replay=self.service.execute(request)
        self.assertEqual(replay['active_session_id'],first['active_session_id'])
        self.assertEqual(replay['context_revision'],first['context_revision'])
        self.assertEqual(head,Projects(self.f.node).repository(self.f.pid).head())
        with self.assertRaises(ValueError):self.service.execute(dict(request,task_id='TASK-X'))
        with self.assertRaises(ValueError):self.service.execute(dict(request,operation_id=str(uuid4())))
        with self.assertRaises(ValueError):self.service.execute(dict(request,user_id=str(uuid4())))

    def test_switch_keeps_late_capture_with_original_session_and_isolates_other_window(self):
        self.service.execute(self.start_request());captured=self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        original=captured['work_session_id'];other={k:v for k,v in self.service.create_window().items() if k.startswith('window_')}
        self.service.execute(self.start_request('TASK-X',handle=other))
        self.assertEqual(self.status()['active_session_id'],original)
        switched=self.service.execute(self.start_request('TASK-X','switch'))
        self.assertEqual(self.active(switched)['task_id'],'TASK-X')
        old=next(s for s in switched['sessions'] if s['work_session_id']==original)
        self.assertEqual(old['state'],'paused')
        self.assertEqual(captured['task_id'],'TASK-A');self.assertEqual(captured['work_session_id'],original)
        self.assertEqual(self.service.capture(other,context_revision=self.status(other)['context_revision'])['task_id'],'TASK-X')
        self.assertNotEqual(self.service.capture(other,context_revision=self.status(other)['context_revision'])['work_session_id'],self.service.capture(self.handle,context_revision=self.status()['context_revision'])['work_session_id'])

    def test_start_and_completion_dependencies_and_sum_do_not_share_a_gate(self):
        self.f.save('- [ ] [PRE-01] Before\n  - status: in progress\n- [ ] [TARGET-01] Target\n  - depends_on: PRE-01\n')
        view=self.service.execute(self.start_request('TARGET-01'));session=self.active(view)
        self.assertFalse(session['blocked']);self.assertFalse(session['current_task']['completion_ready'])
        proposed=self.change('propose-completion',comment='Připraveno k posouzení')
        self.assertFalse(self.active(proposed)['completion_proposals'][0]['completion_ready'])
        self.f.save('- [ ] [PRE-01] Before\n  - status: in progress\n- [ ] [OTHER-01] Other\n  - status: in progress\n- [ ] [TARGET-01] Target\n  - depends_on: PRE-01, OTHER-01\n')
        self.assertIn('Zadání se změnilo',self.active()['blocked'])
        with self.assertRaises(ValueError):self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        with self.assertRaises(ValueError):self.start_request('TARGET-01')
        self.f.save('- [SUM] [GROUP-01] Group\n  - type: batch\n  - [ ] [CHILD-01] Child\n    - type: task\n')
        with self.assertRaises(ValueError):self.start_request('GROUP-01')

    def test_unrelated_commits_and_work_state_keep_pin_but_definition_change_blocks(self):
        self.service.execute(self.start_request());pin=self.active()['definition_pin']
        body=fixtures.BODY.replace('- [ ] [TASK-A] A','- [ ] [TASK-A] A\n  - status: in progress')
        self.f.save(body+'\nAn unrelated paragraph.\n')
        self.assertFalse(self.active()['blocked']);self.assertEqual(self.active()['definition_pin'],pin)
        self.f.save(body.replace('[TASK-A] A','[TASK-A] Changed task'))
        self.assertIn('Zadání se změnilo',self.active()['blocked'])
        with self.assertRaises(ValueError):self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        self.assertEqual(self.active()['definition_pin'],pin)
        self.change('close')
        new=self.service.execute(self.start_request());self.assertNotEqual(self.active(new)['definition_pin'],pin)

    def test_permissions_readonly_completed_and_window_proofs_fail_closed(self):
        request=self.start_request();self.service.execute(request)
        with self.assertRaises(ValueError):TaskWork(self.f.node,str(uuid4())).status(self.handle)
        with self.assertRaises(ValueError):self.service.status(dict(self.handle,window_token='x'*32))
        self.service.can_read=lambda pid:False
        view=self.status();self.assertIsNone(self.active(view)['title']);self.assertNotIn('current_task',self.active(view))
        with self.assertRaises(ValueError):self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        self.change('pause',self.active(view))
        self.service.can_read=lambda pid:True
        with patch.object(self.service.projects,'plan_view',side_effect=lambda pid:dict(Projects(self.f.node).plan_view(pid),read_only=True)):
            with self.assertRaises(ValueError):self.start_request('TASK-X')
        with self.assertRaises(ValueError):self.start_request('TASK-DONE')
        with self.assertRaises(ValueError):self.start_request('TASK-D')

    def test_explicit_restore_pauses_session_and_old_revision_cannot_redirect_it(self):
        view=self.service.execute(self.start_request());session=self.active(view)
        request=dict(self.handle,action='restore',context_revision=view['context_revision'],operation_id=str(uuid4()))
        old_handle=dict(self.handle)
        restored=self.service.execute(request)
        self.handle=restored['window']
        with self.assertRaises(ValueError):self.service.status(old_handle)
        self.assertIsNone(restored['active_session_id']);self.assertEqual(restored['sessions'][0]['state'],'paused')
        with self.assertRaises(ValueError):self.service.execute(dict(self.handle,action='pause',operation_id=str(uuid4()),
            context_revision=view['context_revision'],work_session_id=session['work_session_id'],session_revision=session['revision']))
        self.assertEqual(self.service.execute(request)['context_revision'],restored['context_revision'])
        self.assertEqual(self.service.execute(request)['window'],self.handle)
        self.assertEqual(self.change('resume',restored['sessions'][0])['active_session_id'],session['work_session_id'])

    def test_interruptions_before_and_after_native_commit_recover_original_operation(self):
        for stage in ['task-work-before-intent-commit','task-work-intent-prepared','prepared','files-applied',
                      'ref-updated','indexed','task-work-after-project','task-work-project-recorded',
                      'task-work-before-finalize','task-work-after-finalize']:
            with self.subTest(stage=stage):
                f=fixtures.TaskQueueTests();f.setUp()
                try:
                    service=TaskWork(f.node);handle={k:v for k,v in service.create_window().items() if k.startswith('window_')}
                    inspected=service.inspect(handle,f.pid,'TASK-A',f.head)
                    request=dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,
                                 project_id=f.pid,task_id='TASK-A',selected_checklist=None,**inspected)
                    def fail(at):
                        if at==stage:raise RuntimeError('interruption')
                    with self.assertRaisesRegex(RuntimeError,'interruption'):service.execute(request,checkpoint=fail)
                    resumed=TaskWork(f.node).execute(request)
                    self.assertEqual(resumed['operation']['state'],'completed')
                    self.assertEqual(len(resumed['sessions']),1);self.assertFalse(resumed['sessions'][0]['blocked'])
                    git=Projects(f.node).repository(f.pid)
                    self.assertEqual(len(git.run('rev-list',f.head+'..HEAD').stdout.splitlines()),1)
                    replay=TaskWork(f.node).execute(request)
                    self.assertEqual(replay['active_session_id'],resumed['active_session_id'])
                finally:f.doCleanups()

    def test_stale_recovery_preserves_old_context_and_cancellation_cannot_undo_native_write(self):
        self.service.execute(self.start_request());old=self.active()['work_session_id']
        request=self.start_request('TASK-X','switch')
        def stop(stage):
            if stage=='task-work-intent-prepared':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.service.execute(request,checkpoint=stop)
        self.assertEqual(self.status()['active_session_id'],old)
        with self.assertRaises(ValueError):self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        self.f.save(fixtures.BODY+'\nNew project commit\n')
        with self.assertRaises(ValueError):self.service.execute(dict(self.handle,action='recover',operation_id=request['operation_id']))
        view=self.status();self.assertIsNone(view['pending']);self.assertEqual(view['active_session_id'],old)
        replay=self.service.execute(request);self.assertEqual(replay['operation']['state'],'rejected')
        request=self.start_request('TASK-X','switch')
        def after(stage):
            if stage=='task-work-after-project':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.service.execute(request,checkpoint=after)
        with self.assertRaises(ValueError):self.service.execute(dict(self.handle,action='cancel',operation_id=request['operation_id']))
        restored=self.service.execute(dict(self.handle,action='recover',operation_id=request['operation_id']))
        self.assertEqual(self.active(restored)['task_id'],'TASK-X')

    def test_revoke_after_commit_blocks_activation_without_losing_recoverable_intent(self):
        request=self.start_request()
        def revoke(stage):
            if stage=='task-work-after-project':self.service.can_write=lambda pid:False
        with self.assertRaises(ValueError):self.service.execute(request,checkpoint=revoke)
        view=self.status();self.assertIsNone(view['active_session_id']);self.assertEqual(view['pending']['state'],'blocked')
        self.service.can_write=lambda pid:True
        result=self.service.execute(dict(self.handle,action='recover',operation_id=request['operation_id']))
        self.assertEqual(self.active(result)['task_id'],'TASK-A')

    def test_process_death_replays_sqlite_intent_and_native_git_once(self):
        script='''
import json,os,sys
from spikes.task_work import TaskWork
request=json.loads(sys.argv[2])
def stop(stage):
 if stage==sys.argv[3]:os._exit(39)
TaskWork(sys.argv[1]).execute(request,checkpoint=stop)
'''
        for stage in ('task-work-intent-prepared','prepared','ref-updated','task-work-after-project','task-work-after-finalize'):
            with self.subTest(stage=stage):
                f=fixtures.TaskQueueTests();f.setUp()
                try:
                    service=TaskWork(f.node);handle={k:v for k,v in service.create_window().items() if k.startswith('window_')}
                    request=dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,project_id=f.pid,
                                 task_id='TASK-A',selected_checklist=None,**service.inspect(handle,f.pid,'TASK-A',f.head))
                    result=subprocess.run([sys.executable,'-c',script,str(f.node),json.dumps(request),stage],capture_output=True,timeout=20)
                    self.assertEqual(result.returncode,39,result.stderr)
                    recovered=service.execute(request);self.assertEqual(len(recovered['sessions']),1)
                    self.assertFalse(recovered['sessions'][0]['blocked'])
                    self.assertEqual(len(Projects(f.node).repository(f.pid).run('rev-list',f.head+'..HEAD').stdout.splitlines()),1)
                finally:f.doCleanups()

    def test_store_unsafe_scope_and_future_schema_are_not_reset(self):
        with closing(sqlite3.connect(self.service.path)) as db:db.execute('PRAGMA user_version=99')
        before=self.service.path.read_bytes()
        with self.assertRaises(ValueError):self.status()
        self.assertEqual(before,self.service.path.read_bytes())
        with closing(sqlite3.connect(self.service.path)) as db:db.execute('PRAGMA user_version=1')
        self.service.path.chmod(0o644)
        with self.assertRaises(ValueError):self.status()
        self.service.path.chmod(0o600)
        target=self.service.path.with_suffix('.original');self.service.path.rename(target);self.service.path.symlink_to(target)
        with self.assertRaises(ValueError):self.status()

    def test_pending_reservation_and_operation_owner_prevent_competing_start_or_cancel(self):
        request=self.start_request()
        def stop(stage):
            if stage=='task-work-intent-prepared':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.service.execute(request,checkpoint=stop)
        with self.assertRaises(ValueError):self.service.execute(self.start_request('TASK-X'))
        with self.service._operation_lock(request['operation_id']):
            with self.assertRaises(BlockingIOError):self.service.execute(request)
            with self.assertRaises(BlockingIOError):self.service.execute(dict(self.handle,action='cancel',operation_id=request['operation_id']))
        cancelled=self.service.execute(dict(self.handle,action='cancel',operation_id=request['operation_id']))
        self.assertIsNone(cancelled['active_session_id']);self.assertIsNone(cancelled['pending'])
        self.assertEqual(cancelled['operation']['state'],'rejected')
        self.assertEqual(Projects(self.f.node).repository(self.f.pid).head(),self.f.head)

    def test_window_capability_is_not_persisted_in_request_or_session_payload(self):
        request=self.start_request();view=self.service.execute(request)
        self.assertNotIn(self.handle['window_token'].encode(),self.service.path.read_bytes())
        old=dict(self.handle)
        restored=self.service.execute(dict(old,action='restore',context_revision=view['context_revision'],operation_id=str(uuid4())))
        with self.assertRaises(ValueError):self.service.capture(old,context_revision=view['context_revision'])
        self.assertNotIn(restored['window']['window_token'].encode(),self.service.path.read_bytes())

    def test_checklist_progress_is_not_a_definition_edit_and_selection_is_bounded(self):
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - [ ] Check one\n  - [ ] Check two\n')
        request=self.start_request();request['selected_checklist']=1
        view=self.service.execute(request);session=self.active(view)
        self.assertEqual(session['selected_checklist'],1)
        pin=session['definition_pin']
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - status: in progress\n  - [x] Check one\n  - [ ] Check two\n')
        self.assertFalse(self.active()['blocked']);self.assertEqual(self.active()['definition_pin'],pin)
        self.change('pause')
        bad=self.start_request();bad['selected_checklist']=True
        with self.assertRaises(ValueError):self.service.execute(bad)
        bad['selected_checklist']=2
        with self.assertRaises(ValueError):self.service.execute(bad)

    def test_changed_definition_rebind_closes_old_segment_and_keeps_prior_pin(self):
        self.service.execute(self.start_request());old=self.active();pin=old['definition_pin']
        self.f.save(fixtures.BODY.replace('[TASK-A] A','[TASK-A] Revised A'))
        self.assertTrue(self.active()['blocked'])
        revised=self.service.execute(self.start_request('TASK-A','switch'))
        current=self.active(revised);self.assertFalse(current['blocked'])
        self.assertNotEqual(current['work_session_id'],old['work_session_id'])
        self.assertEqual(current['previous_work_session_id'],old['work_session_id'])
        historical=next(s for s in revised['sessions'] if s['work_session_id']==old['work_session_id'])
        self.assertEqual(historical['state'],'closed');self.assertEqual(historical['closed_reason'],'definition-updated')
        self.assertEqual(historical['definition_pin'],pin)

    def test_restore_during_native_completion_cannot_activate_under_revoked_window_token(self):
        request=self.start_request();replacement={}
        def claim(stage):
            if stage=='task-work-after-project':
                view=self.status()
                result=self.service.execute(dict(self.handle,action='restore',operation_id=str(uuid4()),context_revision=view['context_revision']))
                replacement.update(result['window'])
        with self.assertRaises(ValueError):self.service.execute(request,checkpoint=claim)
        with self.assertRaises(ValueError):self.status()
        self.handle=replacement
        self.assertIsNotNone(self.status()['pending']);self.assertIsNone(self.status()['active_session_id'])
        recovered=self.service.execute(dict(self.handle,action='recover',operation_id=request['operation_id']))
        self.assertFalse(self.active(recovered)['blocked'])
        self.assertEqual(len(Projects(self.f.node).repository(self.f.pid).run('rev-list',self.f.head+'..HEAD').stdout.splitlines()),1)

    def test_cross_project_switch_with_same_task_id_retains_origin(self):
        from spikes.artifacts import Artifacts
        from spikes.markdown_documents import main_todo_id
        self.service.execute(self.start_request());old=self.active()
        captured=self.service.capture(self.handle,context_revision=self.status()['context_revision'])
        pid=ProjectCreation(self.f.node).create('Another project',str(self.f.root/'another'),str(uuid4()))['id']
        head=Projects(self.f.node).repository(pid).head()
        head=Artifacts(self.f.node).save(dict(project_id=pid,artifact_id=main_todo_id(pid),base_head=head,
            title='Another plan',body='- [ ] [TASK-A] Same ID in another project\n',new=True),str(uuid4()))['commit_id']
        target=self.service.inspect(self.handle,pid,'TASK-A',head)
        view=self.status()
        result=self.service.execute(dict(self.handle,action='switch',operation_id=str(uuid4()),context_revision=view['context_revision'],
            project_id=pid,task_id='TASK-A',selected_checklist=None,work_session_id=old['work_session_id'],session_revision=old['revision'],**target))
        self.assertEqual(self.active(result)['project_id'],pid)
        self.assertEqual(captured['project_id'],self.f.pid)
        original=next(s for s in result['sessions'] if s['work_session_id']==old['work_session_id'])
        self.assertEqual(original['state'],'paused');self.assertEqual(original['project_id'],self.f.pid)

    def test_network_service_without_authenticated_project_policy_is_denied(self):
        network=TaskWork(self.f.node,self.user,network=True)
        with self.assertRaises(ValueError):network.inspect(self.handle,self.f.pid,'TASK-A',self.f.head)
        self.assertEqual(Projects(self.f.node).repository(self.f.pid).head(),self.f.head)

    def test_checklist_context_selection_replays_without_changing_git_or_completion(self):
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - [ ] First condition\n  - [x] Second condition\n')
        view=self.service.execute(self.start_request());session=self.active(view)
        before=Projects(self.f.node).repository(self.f.pid).head()
        original=self.service.capture(self.handle,context_revision=view['context_revision'])
        request=dict(self.handle,action='select-checklist',operation_id=str(uuid4()),context_revision=view['context_revision'],
            work_session_id=session['work_session_id'],session_revision=session['revision'],selected_checklist=1)
        selected=self.service.execute(request);active=self.active(selected)
        self.assertEqual(active['selected_checklist'],1)
        self.assertEqual(active['project_title'],'Queue')
        captured=self.service.capture(self.handle,context_revision=selected['context_revision'])
        self.assertEqual(captured['selected_checklist'],1);self.assertIsNone(original['selected_checklist'])
        self.assertEqual([p['checked'] for p in active['current_task']['checklist']],[False,True])
        self.assertFalse(active['current_task']['checked'])
        self.assertEqual(before,Projects(self.f.node).repository(self.f.pid).head())
        self.assertEqual(self.service.execute(request)['context_revision'],selected['context_revision'])
        with self.assertRaises(ValueError):self.service.execute(dict(request,operation_id=str(uuid4()),selected_checklist=0))
        clear=dict(request,operation_id=str(uuid4()),context_revision=selected['context_revision'],session_revision=active['revision'],selected_checklist=None)
        cleared=self.service.execute(clear);self.assertIsNone(self.active(cleared)['selected_checklist'])

    def test_checklist_selection_rejects_wrong_type_closed_stale_definition_and_revoked_rights(self):
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - [ ] First\n')
        view=self.service.execute(self.start_request());session=self.active(view)
        request=dict(self.handle,action='select-checklist',operation_id=str(uuid4()),context_revision=view['context_revision'],
            work_session_id=session['work_session_id'],session_revision=session['revision'],selected_checklist=0)
        for value in [True,-1,1,'0']:
            with self.subTest(value=value),self.assertRaises(ValueError):self.service.execute(dict(request,selected_checklist=value))
        self.service.can_write=lambda pid:False
        with self.assertRaises(ValueError):self.service.execute(request)
        self.assertNotIn('project_title',self.active())
        self.service.can_write=lambda pid:True
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - status: in progress\n  - [ ] Changed\n')
        with self.assertRaises(ValueError):self.service.execute(request)
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - status: in progress\n  - [ ] First\n')
        closed=self.change('close');session=closed['sessions'][0]
        with self.assertRaises(ValueError):self.service.execute(dict(request,context_revision=closed['context_revision'],session_revision=session['revision']))

    def test_complete_marks_native_task_and_closes_session_without_checking_other_work(self):
        view=self.service.execute(self.start_request());session=self.active(view)
        request=dict(self.handle,action='complete',operation_id=str(uuid4()),context_revision=view['context_revision'],
            work_session_id=session['work_session_id'],session_revision=session['revision'],expected_head=session['validated_head'],confirmed=True)
        completed=self.service.execute(request);self.assertIsNone(completed['active_session_id'])
        self.assertTrue(completed['sessions'][0]['current_task']['checked'])
        self.assertEqual(completed['sessions'][0]['closed_reason'],'task-completed')
        head=Projects(self.f.node).repository(self.f.pid).head();self.service.execute(request)
        self.assertEqual(Projects(self.f.node).repository(self.f.pid).head(),head)

    def test_complete_blocks_unreviewed_checklist_and_running_dependencies(self):
        self.f.save('- [ ] [TASK-A] A\n  - type: task\n  - [ ] Pending point\n')
        view=self.service.execute(self.start_request());session=self.active(view)
        request=dict(self.handle,action='complete',operation_id=str(uuid4()),context_revision=view['context_revision'],
            work_session_id=session['work_session_id'],session_revision=session['revision'],expected_head=session['validated_head'],confirmed=True)
        with self.assertRaisesRegex(ValueError,'checklistu'):self.service.execute(request)
        self.assertEqual(self.active()['state'],'active');self.assertIsNone(self.status()['pending'])

    def test_history_after_restart_reclaims_same_session_with_explicit_owner_proof(self):
        view=self.service.execute(self.start_request());sid=view['active_session_id']
        restarted=TaskWork(self.f.node,self.user)
        saved=restarted.execute({'action':'history'})['sessions'][0]
        self.assertEqual(saved['work_session_id'],sid)
        fresh={k:v for k,v in restarted.create_window().items() if k.startswith('window_')}
        request=dict(fresh,action='reclaim',operation_id=str(uuid4()),context_revision=0,work_session_id=sid,
            session_revision=saved['revision'],target_context_revision=saved['target_context_revision'],confirmed=True)
        recovered=restarted.execute(request);self.assertIsNone(recovered['active_session_id'])
        self.assertEqual(recovered['sessions'][0]['state'],'paused')
        self.assertEqual(restarted.execute(request)['window'],recovered['window'])
        with self.assertRaises(ValueError):self.service.status(self.handle)
        resumed=restarted.execute(dict(recovered['window'],action='resume',operation_id=str(uuid4()),context_revision=recovered['context_revision'],
            work_session_id=sid,session_revision=recovered['sessions'][0]['revision']))
        self.assertEqual(resumed['active_session_id'],sid)
        self.assertEqual(resumed['sessions'][0]['definition_pin'],self.active(view)['definition_pin'])

    def test_complete_paused_task_keeps_another_active_task_and_recovery_survives_process_death(self):
        first=self.service.execute(self.start_request());aid=first['active_session_id']
        other=self.service.execute(self.start_request('TASK-X','switch'));bid=other['active_session_id']
        selected=next(s for s in other['sessions'] if s['work_session_id']==aid)
        request=dict(self.handle,action='complete',operation_id=str(uuid4()),context_revision=other['context_revision'],
            work_session_id=aid,session_revision=selected['revision'],expected_head=selected['validated_head'],confirmed=True)
        script='''import json,os,sys
from spikes.task_work import TaskWork
def stop(stage):
 if stage=='task-work-after-project':os._exit(78)
TaskWork(sys.argv[1]).execute(json.loads(sys.argv[2]),checkpoint=stop)
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.f.node),json.dumps(request)])
        self.assertEqual(result.returncode,78)
        head=Projects(self.f.node).repository(self.f.pid).head()
        self.service.execute(dict(self.handle,action='recover',operation_id=request['operation_id']))
        final=self.status();self.assertEqual(final['active_session_id'],bid)
        self.assertEqual(next(s for s in final['sessions'] if s['work_session_id']==aid)['closed_reason'],'task-completed')
        self.assertFalse(self.active(final)['current_task']['checked'])
        self.assertEqual(Projects(self.f.node).repository(self.f.pid).head(),head)

    def test_completion_requires_finished_dependencies_and_explicit_confirmation(self):
        self.f.save('- [ ] [PRE-A] Prerequisite\n  - status: in progress\n- [ ] [TASK-A] A\n  - depends_on: PRE-A\n')
        view=self.service.execute(self.start_request());session=self.active(view)
        request=dict(self.handle,action='complete',operation_id=str(uuid4()),context_revision=view['context_revision'],
            work_session_id=session['work_session_id'],session_revision=session['revision'],expected_head=session['validated_head'],confirmed=True)
        with self.assertRaisesRegex(ValueError,'závislostí'):self.service.execute(request)
        with self.assertRaises(ValueError):self.service.execute(dict(request,confirmed=False))
        self.assertEqual(self.active()['state'],'active')

    def test_reclaim_cannot_cross_users_or_overwrite_newer_context(self):
        view=self.service.execute(self.start_request());saved=self.service.history()['sessions'][0]
        fresh={k:v for k,v in self.service.create_window().items() if k.startswith('window_')}
        request=dict(fresh,action='reclaim',operation_id=str(uuid4()),context_revision=0,work_session_id=saved['work_session_id'],
            session_revision=saved['revision'],target_context_revision=saved['target_context_revision'],confirmed=True)
        outsider=TaskWork(self.f.node,str(uuid4()));self.assertEqual(outsider.history()['sessions'],[])
        other={k:v for k,v in outsider.create_window().items() if k.startswith('window_')}
        with self.assertRaises(ValueError):outsider.execute(dict(request,**other))
        with self.assertRaises(ValueError):self.service.execute(dict(request,target_context_revision=999))
        self.assertEqual(self.status()['active_session_id'],view['active_session_id'])
        self.service.can_write=lambda pid:False
        self.assertEqual(self.service.history()['sessions'],[])
        with self.assertRaises(ValueError):self.service.execute(request)
