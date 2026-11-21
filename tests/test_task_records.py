# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4
from copy import deepcopy
from spikes.artifacts import Artifacts
from spikes.metadata import validate_snapshot,validate_transition
from spikes.task_activities import TaskActivities
from spikes.task_records import TaskRecords
from spikes.task_record_schema import encoded,records
from tests import test_task_work as fixtures


class TaskRecordTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TaskWorkTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.work=self.f.service;self.handle=self.f.handle
        self.view=self.work.execute(self.f.start_request());self.sid=self.view['active_session_id']
        self.service=TaskRecords(self.work);self.activity=TaskActivities(self.work)
        self.aid=str(uuid4());self.events=[]
        self.saved('# Original inventory\n',True)

    def saved(self,body,new=False):
        pid=self.f.f.pid;head=self.work.projects.repository(pid).head()
        request=dict(operation_id=str(uuid4()),document=dict(project_id=pid,artifact_id=self.aid,base_head=head,title='Inventory',body=body,new=new))
        identifier=self.activity.begin(self.handle,self.work.status(self.handle)['context_revision'],'/v1/artifacts/editor/save',request)
        receipt=Artifacts(self.f.f.node).save(request['document'],request['operation_id'])
        self.activity.finish(identifier,200,receipt);self.events.append(identifier);return receipt

    def request(self,**extra):
        values={e['event_id']:e for e in self.activity.for_session(self.handle,self.sid)}
        request=dict(self.handle,action='record-publish',operation_id=str(uuid4()),work_session_id=self.sid,
            event_ids=list(self.events),offer_revisions=[values[i]['offer']['revision'] for i in self.events],
            comment='Inventář je připraven ke kontrole.',selected_checklist=None,
            expected_head=self.work.projects.repository(self.f.f.pid).head(),privacy='project')
        request.update(extra);return request

    def record(self):
        return self.service.for_session(self.handle,self.sid)[0][0]

    def test_confirmation_writes_task_text_atomically_and_keeps_context_usable(self):
        from spikes.markdown_documents import document,main_todo_id
        git=self.work.projects.repository(self.f.f.pid)
        before=git.snapshot(git.head())
        self.assertEqual(self.service.for_session(self.handle,self.sid)[0],[])
        request=self.request();result=self.service.execute(request)
        current=git.snapshot(git.head());entities=validate_snapshot(current)
        body=document(current,entities,main_todo_id(self.f.f.pid))['body']
        self.assertIn('Inventář je připraven ke kontrole.',body)
        self.assertIn('artifacts/'+self.aid+'/content.md',body)
        self.assertNotIn('Original inventory',body)
        self.assertFalse(self.f.active()['blocked'])
        self.assertFalse(self.f.active()['current_task']['checked'])
        record=self.record();marker='<!-- fpw-task-record:'+record['id']+' -->'
        self.assertEqual(body.count(marker),1)
        head=git.head();self.service.execute(request);self.assertEqual(git.head(),head)
        self.assertEqual(set(before)-set(current),set())
        changed=[path for path in before if before[path]!=current[path]]
        self.assertEqual(changed,['artifacts/'+main_todo_id(self.f.f.pid)+'/content.md'])
        amend=dict(self.handle,action='record-amend',operation_id=str(uuid4()),work_session_id=self.sid,
            record_id=record['id'],record_revision=1,comment='Upravený komentář',selected_checklist=None,expected_head=head)
        self.service.execute(amend)
        body=document(git.snapshot(git.head()),validate_snapshot(git.snapshot(git.head())),main_todo_id(self.f.f.pid))['body']
        self.assertEqual(body.count(marker),1);self.assertIn('Upravený komentář',body)
        self.assertFalse(self.f.active()['blocked'])
        self.saved('# Next saved output\n')
        self.assertEqual(len(self.activity.for_session(self.handle,self.sid)),2)

    def test_task_text_does_not_disclose_more_private_comment_and_fake_marker_cannot_hide_edits(self):
        from spikes.markdown_documents import document,main_todo_id
        self.service.execute(self.request(privacy='confidential',comment='SECRET PRIVATE COMMENT'))
        git=self.work.projects.repository(self.f.f.pid);head=git.head()
        files=git.snapshot(head);entities=validate_snapshot(files)
        doc=document(files,entities,main_todo_id(self.f.f.pid))
        self.assertNotIn('SECRET PRIVATE COMMENT',doc['body'])
        self.assertIn('Připojen záznam práce',doc['body'])
        self.assertFalse(self.f.active()['blocked'])
        edited=doc['body'].replace('  - status: in progress','  - status: in progress\n  - Changed requirements <!-- fpw-task-record:'+str(uuid4())+' -->',1)
        self.assertNotEqual(edited,doc['body'])
        Artifacts(self.f.f.node).save(dict(project_id=self.f.f.pid,artifact_id=doc['id'],base_head=head,
            title=doc['title'],body=edited,new=False),str(uuid4()))
        self.assertTrue(self.f.active()['blocked'])

    def test_confirm_group_exact_outputs_replay_amend_and_immutable_history(self):
        first=self.work.projects.repository(self.f.f.pid).head();self.saved('# Revised inventory\n')
        request=self.request();view=self.service.execute(request)
        self.assertEqual(view['operation']['state'],'completed');record=self.record()
        self.assertEqual(len(record['events']),2);self.assertEqual(len(record['outputs']),2)
        self.assertEqual(record['outputs'][0]['commit_id'],first)
        self.assertFalse(self.f.active()['current_task']['checked'])
        head=self.work.projects.repository(self.f.f.pid).head()
        self.service.execute(request);self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),head)
        amended=dict(self.handle,action='record-amend',operation_id=str(uuid4()),work_session_id=self.sid,record_id=record['id'],
            record_revision=1,comment='Opravený komentář.',selected_checklist=None,expected_head=head)
        self.service.execute(amended);current=self.record()
        self.assertEqual([r['comment'] for r in current['revisions']],[request['comment'],'Opravený komentář.'])
        self.assertEqual(current['outputs'],record['outputs'])
        git=self.work.projects.repository(self.f.f.pid);files=git.snapshot(git.head());bad=dict(files)
        value=deepcopy(records(files,validate_snapshot(files))[record['id']]);value['revisions'][0]['comment']='Rewrite'
        bad['artifacts/'+record['id']+'/task-work.json']=encoded(value)
        with self.assertRaises(ValueError):validate_transition(files,bad)

    def test_offer_draft_defer_dismiss_reopen_and_cas_survive_refresh_without_git_write(self):
        before=self.work.projects.repository(self.f.f.pid).head()
        for state in ['draft','deferred','dismissed','draft']:
            request=self.request(action='record-offer',state=state,comment='Rozepsaný komentář')
            request.pop('expected_head');request.pop('privacy')
            self.service.execute(request);self.service.execute(request)
            event=self.activity.for_session(self.handle,self.sid)[0]
            self.assertEqual(event['offer']['state'],state);self.assertEqual(event['offer']['comment'],request['comment'])
            with self.assertRaises(ValueError):self.service.execute(dict(request,operation_id=str(uuid4())))
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),before)

    def test_original_and_current_preview_after_edit_and_delete(self):
        self.service.execute(self.request());record=self.record();self.saved('# New version\n')
        request=dict(self.handle,action='record-output',project_id=self.f.f.pid,record_id=record['id'],output_index=0,version='original',page=1)
        self.assertIn('Original inventory',self.service.execute(request)['text'])
        self.assertIn('New version',self.service.execute(dict(request,version='current'))['text'])
        from spikes.artifact_actions import ArtifactActions
        actions=ArtifactActions(self.f.f.node);head=self.work.projects.repository(self.f.f.pid).head()
        preview=actions.deletion_preview(self.f.f.pid,self.aid,head)
        actions.delete(self.f.f.pid,self.aid,head,preview['preview_sha256'],str(uuid4()))
        self.assertIn('Original inventory',self.service.execute(request)['text'])
        with self.assertRaises(ValueError):self.service.execute(dict(request,version='current'))

    def test_pending_recovery_retains_original_intent_after_native_commit(self):
        request=self.request()
        def stop(stage):
            if stage=='task-record-after-project':raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):self.service.execute(request,checkpoint=stop)
        committed=self.work.projects.repository(self.f.f.pid).head()
        self.assertEqual(len(self.service.for_session(self.handle,self.sid)[1]),1)
        with self.assertRaises(ValueError):self.service.execute(dict(self.handle,action='record-cancel',operation_id=request['operation_id']))
        self.service.execute(dict(self.handle,action='record-recover',operation_id=request['operation_id']))
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),committed)
        self.assertEqual(self.activity.for_session(self.handle,self.sid)[0]['offer']['state'],'confirmed')

    def test_cancel_before_native_write_keeps_draft_and_blocks_duplicate_reservation(self):
        request=self.request()
        def stop(stage):
            if stage=='task-record-intent-prepared':raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):self.service.execute(request,checkpoint=stop)
        with self.assertRaises(ValueError):self.service.execute(self.request())
        self.service.execute(dict(self.handle,action='record-cancel',operation_id=request['operation_id']))
        self.assertEqual(self.activity.for_session(self.handle,self.sid)[0]['offer']['state'],'draft')
        self.service.execute(self.request());self.assertEqual(len(self.service.for_session(self.handle,self.sid)[0]),1)

    def test_revoked_rights_wrong_window_low_privacy_and_stale_head_fail_closed(self):
        request=self.request();self.work.can_write=lambda pid:False
        with self.assertRaises(ValueError):self.service.execute(request)
        self.work.can_write=lambda pid:True
        other={k:v for k,v in self.work.create_window().items() if k.startswith('window_')}
        with self.assertRaises(ValueError):self.service.execute(dict(request,**other))
        with self.assertRaises(ValueError):self.service.execute(dict(request,privacy='public'))
        with self.assertRaises(ValueError):self.service.execute(dict(request,expected_head='a'*40))
        self.assertEqual(self.service.for_session(self.handle,self.sid)[0],[])

    def test_process_death_at_record_intent_native_commit_and_finalization_boundaries(self):
        import subprocess,sys
        for stage in ['task-record-before-intent-commit','task-record-intent-prepared','task-record-after-project','task-record-before-finalize']:
            with self.subTest(stage=stage):
                fixture=TaskRecordTests();fixture.setUp()
                try:
                    request=fixture.request()
                    script='''import json,os,sys
from spikes.task_work import TaskWork
from spikes.task_records import TaskRecords
service=TaskRecords(TaskWork(sys.argv[1]))
def stop(stage):
 if stage==sys.argv[3]:os._exit(79)
service.execute(json.loads(sys.argv[2]),checkpoint=stop)
'''
                    result=subprocess.run([sys.executable,'-c',script,str(fixture.f.f.node),json.dumps(request),stage])
                    self.assertEqual(result.returncode,79)
                    if stage=='task-record-before-intent-commit':fixture.service.execute(request)
                    else:fixture.service.execute(dict(fixture.handle,action='record-recover',operation_id=request['operation_id']))
                    git=fixture.work.projects.repository(fixture.f.f.pid);head=git.head()
                    fixture.service.execute(request)
                    self.assertEqual(git.head(),head)
                    self.assertEqual(len(fixture.service.for_session(fixture.handle,fixture.sid)[0]),1)
                finally:fixture.doCleanups()

    def test_failed_unknown_and_late_switched_events_keep_provenance_without_claiming_outputs(self):
        request=dict(operation_id=str(uuid4()),project_id=self.f.f.pid,run_id=str(uuid4()))
        event=self.activity.begin(self.handle,self.work.status(self.handle)['context_revision'],'/v1/external/send',request)
        self.events=[event]
        self.work.execute(self.f.start_request('TASK-X','switch'))
        # Unknown is an honest annotation, never a saved result or an accepted task.
        self.service.execute(self.request(comment='Běh nemá potvrzený výsledek.'))
        record=self.record();self.assertEqual(record['outputs'],[])
        self.assertEqual(record['context']['task_id'],'TASK-A');self.assertEqual(record['events'][0]['outcome'],'unknown')
        self.assertEqual(self.f.active()['task_id'],'TASK-X')

    def test_closed_schema_rejects_completion_state_duplicate_events_and_unknown_version(self):
        self.service.execute(self.request());record=self.record();git=self.work.projects.repository(self.f.f.pid)
        files=git.snapshot(git.head());path='artifacts/'+record['id']+'/task-work.json'
        base=records(files,validate_snapshot(files))[record['id']]
        for change in [lambda r:r.update(checked=True),lambda r:r['events'].append(deepcopy(r['events'][0])),
                       lambda r:r.update(schema='fpw-task-record-v99'),lambda r:r['outputs'][0].update(path='../secret')]:
            candidate=deepcopy(base);change(candidate);bad=dict(files);bad[path]=encoded(candidate)
            with self.assertRaises(ValueError):validate_snapshot(bad)

    def test_invalid_offer_input_does_not_reserve_event_or_write_project(self):
        head=self.work.projects.repository(self.f.f.pid).head()
        for invalid in [dict(event_ids=[{}]),dict(comment=None),dict(selected_checklist=True)]:
            with self.assertRaises(ValueError):self.service.execute(self.request(**invalid))
        request=self.request(action='record-offer',state={});request.pop('expected_head');request.pop('privacy')
        with self.assertRaises(ValueError):self.service.execute(request)
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),head)

    def test_native_output_does_not_relabel_input_artifacts_as_results(self):
        input_id=str(uuid4());head=self.work.projects.repository(self.f.f.pid).head()
        Artifacts(self.f.f.node).save(dict(project_id=self.f.f.pid,artifact_id=input_id,base_head=head,title='Input',body='# Input only\n',new=True),str(uuid4()))
        self.saved('# Final result\n')
        event=self.activity.for_session(self.handle,self.sid)[-1]
        event['request_references'].append({'artifact_id':input_id})
        # Publishing operations use their native result identity, not all input refs.
        event['kind']='artifact-publish'
        outputs=self.service.outputs([event])
        self.assertEqual([o['artifact_id'] for o in outputs],[self.aid])

    def test_roadmap_reads_git_records_without_window_and_separates_own_local_activity(self):
        self.service.execute(self.request());head=self.work.projects.repository(self.f.f.pid).head()
        query=dict(action='record-list',project_id=self.f.f.pid,task_id='TASK-A',expected_head=head)
        own=self.service.execute(query);self.assertEqual(len(own['records']),1);self.assertEqual(len(own['activities']),1)
        from spikes.task_work import TaskWork
        reader=TaskWork(self.f.f.node,str(uuid4()),can_read=lambda pid:True,can_write=lambda pid:False)
        service=TaskRecords(reader)
        with self.work._db() as db:windows=db.execute('SELECT count(*) FROM windows').fetchone()[0]
        result=service.execute(query);self.assertEqual(len(result['records']),1);self.assertEqual(result['activities'],[])
        record=result['records'][0]
        preview=service.execute(dict(action='record-preview',project_id=self.f.f.pid,task_id='TASK-A',expected_head=head,
            record_id=record['id'],output_index=0,version='original',page=1))
        self.assertIn('Original inventory',preview['text'])
        with self.work._db() as db:self.assertEqual(db.execute('SELECT count(*) FROM windows').fetchone()[0],windows)
        with self.assertRaises(ValueError):service.execute(dict(query,expected_head='a'*40))
        with self.assertRaises(ValueError):service.execute(dict(action='record-preview',project_id=self.f.f.pid,task_id='TASK-X',expected_head=head,
            record_id=record['id'],output_index=0,version='original',page=1))
        reader.can_read=lambda pid:False
        with self.assertRaises(ValueError):service.execute(query)

    def test_roadmap_exposes_unconfirmed_native_files_and_draft_without_changing_offer(self):
        request=self.request(action='record-offer',state='deferred',comment='Saved draft for roadmap')
        request.pop('privacy');request.pop('expected_head');self.service.execute(request)
        head=self.work.projects.repository(self.f.f.pid).head()
        query=dict(action='record-list',project_id=self.f.f.pid,task_id='TASK-A',expected_head=head)
        result=self.service.execute(query)
        self.assertEqual(result['records'],[]);event=result['activities'][0]
        self.assertEqual(event['offer']['state'],'deferred');self.assertEqual(event['offer']['comment'],'Saved draft for roadmap')
        self.assertEqual(event['outputs'][0]['artifact_id'],self.aid)
        preview=self.service.execute(dict(action='record-activity-preview',project_id=self.f.f.pid,task_id='TASK-A',expected_head=head,
            event_id=event['event_id'],output_index=0,version='original',page=1))
        self.assertIn('Original inventory',preview['text'])
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),head)
        self.assertEqual(self.activity.for_session(self.handle,self.sid)[0]['offer'],event['offer'])

    def test_roadmap_keeps_git_records_visible_when_local_activity_store_is_unavailable(self):
        from unittest.mock import patch
        self.service.execute(self.request());head=self.work.projects.repository(self.f.f.pid).head()
        with patch.object(self.service.activities,'for_task',side_effect=OSError('local store unavailable')):
            result=self.service.execute(dict(action='record-list',project_id=self.f.f.pid,task_id='TASK-A',expected_head=head))
        self.assertEqual(len(result['records']),1);self.assertTrue(result['activities_unavailable'])
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(),head)
