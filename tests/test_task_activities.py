# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from spikes.task_activities import TaskActivities, references
from spikes.task_work import TaskWork
from tests import test_task_work as fixtures


class TaskActivityTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskWorkTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.work = self.f.service; self.handle = self.f.handle
        self.view = self.work.execute(self.f.start_request())
        self.service = TaskActivities(self.work)
        self.request = dict(project_id=self.f.f.pid, operation_id=str(uuid4()),
                            artifact_id=str(uuid4()), content='SECRET BODY')

    def begin(self, request=None, route='/v1/artifacts/editor/save'):
        return self.service.begin(self.handle, self.work.status(self.handle)['context_revision'],
                                  route, request or self.request)

    def events(self, session=None):
        return self.service.for_session(self.handle, session or self.view['active_session_id'])

    def test_durable_intent_receipt_replay_and_no_content_or_completion(self):
        identifier = self.begin(); self.assertEqual(self.events()[0]['outcome'], 'unknown')
        head = self.f.f.head
        self.service.finish(identifier, 200, dict(commit_id=head, artifact_id=self.request['artifact_id'], body='SECRET RESULT'))
        event = self.events()[0]
        self.assertEqual(event['outcome'], 'succeeded'); self.assertEqual(event['context']['selected_checklist'], None)
        self.assertEqual(event['result_references'], [dict(commit_id=head, artifact_id=self.request['artifact_id'])])
        self.assertNotIn('SECRET', json.dumps(event))
        self.assertEqual(self.begin(), identifier); self.assertEqual(len(self.events()), 1)
        self.service.finish(identifier, 422, {'error': 'bad replay'})
        self.assertEqual(self.events()[0]['outcome'], 'succeeded')
        self.assertFalse(self.f.active()['current_task']['checked'])
        with self.assertRaises(ValueError): self.begin(dict(self.request, content='changed'))

    def test_late_result_and_replay_remain_with_original_session_after_switch(self):
        identifier = self.begin()
        other = self.work.execute(self.f.start_request('TASK-X', 'switch'))
        self.assertNotEqual(other['active_session_id'], self.view['active_session_id'])
        self.service.finish(identifier, 200, {'run_id': str(uuid4())})
        self.assertEqual(self.begin(), identifier)
        self.assertEqual(self.events()[0]['context']['task_id'], 'TASK-A')
        self.assertEqual(self.events(other['active_session_id']), [])
        self.begin(dict(self.request, operation_id=str(uuid4())))
        self.assertEqual(self.events(other['active_session_id'])[0]['context']['task_id'], 'TASK-X')

    def test_stale_window_cross_owner_and_revocation_cannot_dispatch_or_read(self):
        with self.assertRaises(ValueError):
            self.service.begin(self.handle, -1, '/v1/artifacts/editor/save', self.request)
        identifier = self.begin()
        other = {k: v for k, v in self.work.create_window().items() if k.startswith('window_')}
        with self.assertRaises(ValueError): self.service.begin(other, 0, '/v1/artifacts/editor/save', self.request)
        self.work.can_write = lambda pid: False
        with self.assertRaises(ValueError): self.begin()
        with self.assertRaises(ValueError): self.events()
        self.assertNotIn('activities', self.work.status(self.handle)['sessions'][0])
        # Completion is metadata-only even if permission was revoked after native dispatch.
        self.service.finish(identifier, 409, {'outcome': 'unknown'})

    def test_stream_and_nonstream_group_one_turn_failed_and_unknown_are_distinct(self):
        request = dict(project_id=self.f.f.pid, run_id=str(uuid4()), turn_id=str(uuid4()))
        identifier = self.begin(request, '/v1/chat/send-stream')
        self.assertEqual(self.begin(request, '/v1/chat/send'), identifier)
        self.service.finish(identifier, 502, {'error': 'SECRET backend text'})
        self.assertEqual(self.events()[0]['outcome'], 'failed')
        self.service.finish(identifier, 409, {'outcome': 'unknown'})
        self.assertEqual(self.events()[0]['outcome'], 'unknown')
        self.assertNotIn('SECRET', json.dumps(self.events()))

    def test_target_permissions_and_local_receipts_do_not_cross_web_trust_boundary(self):
        self.begin()
        self.work.network = True
        self.assertEqual(self.events(), [])
        self.work.network = False
        target = str(uuid4()); self.work.can_read = lambda pid: pid != target
        with self.assertRaises(ValueError): self.begin(dict(self.request, project_id=target))
        self.work.can_read = lambda pid: True
        self.begin(dict(self.request, project_id=target, operation_id=str(uuid4())))
        self.work.can_read = lambda pid: pid != target
        self.assertEqual(len(self.events()), 1)

    def test_process_exit_leaves_original_unknown_without_native_retry(self):
        script = '''import json,os,sys
from spikes.task_work import TaskWork
from spikes.task_activities import TaskActivities
work=TaskWork(sys.argv[1]);data=json.loads(sys.argv[2])
TaskActivities(work).begin(data['handle'],data['revision'],'/v1/artifacts/editor/save',data['request'])
os._exit(27)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.f.f.node),
            json.dumps(dict(handle=self.handle, revision=self.view['context_revision'], request=self.request))])
        self.assertEqual(result.returncode, 27)
        self.assertEqual(self.events()[0]['outcome'], 'unknown')
        self.assertEqual(self.begin(), self.events()[0]['event_id'])

    def test_reference_extractor_is_bounded_and_skips_content(self):
        value = {'body': {'artifact_id': 'SECRET'}, 'result': {'artifact_id': str(uuid4())}}
        self.assertEqual(references(value), [value['result']])

    def test_native_commit_survives_process_exit_before_activity_finalization(self):
        from spikes.artifacts import Artifacts
        from spikes.projects import Projects
        request=dict(operation_id=str(uuid4()),document=dict(project_id=self.f.f.pid,
            artifact_id=str(uuid4()),base_head=Projects(self.f.f.node).repository(self.f.f.pid).head(),
            title='Inventory',body='# Inventory\n',new=True))
        script='''import json,os,sys
from spikes.task_work import TaskWork
from spikes.task_activities import TaskActivities
from spikes.artifacts import Artifacts
work=TaskWork(sys.argv[1]);data=json.loads(sys.argv[2]);r=data['request']
TaskActivities(work).begin(data['handle'],data['revision'],'/v1/artifacts/editor/save',r)
Artifacts(work.node).save(r['document'],r['operation_id'])
os._exit(28)
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.f.f.node),json.dumps(dict(
            handle=self.handle,revision=self.view['context_revision'],request=request))])
        self.assertEqual(result.returncode,28)
        committed=Projects(self.f.f.node).repository(self.f.f.pid).head()
        self.assertEqual(self.events()[0]['outcome'],'unknown')
        # Only an explicit native replay reconciles the receipt. The recorder never writes Git.
        identifier=self.begin(request)
        receipt=Artifacts(self.f.f.node).save(request['document'],request['operation_id'])
        self.assertEqual(receipt['commit_id'],committed)
        self.service.finish(identifier,200,receipt)
        self.assertEqual(self.events()[0]['outcome'],'succeeded')
        self.assertEqual(Projects(self.f.f.node).repository(self.f.f.pid).head(),committed)

    def test_registry_contains_only_existing_native_routes_and_search_rounds_are_separate(self):
        from spikes.desktop_ui import DesktopHandler
        from spikes.task_activities import ROUTES
        self.assertLessEqual(set(ROUTES),DesktopHandler.post_paths)
        request=dict(task_id=str(uuid4()),search_id=str(uuid4()),approved=True)
        first=self.begin(request,'/v1/tasks/search/confirm')
        second=self.begin(dict(request,search_id=str(uuid4())),'/v1/tasks/search/confirm')
        self.assertNotEqual(first,second)
        self.assertEqual(len(self.events()),2)

    def test_model_proposal_is_not_promoted_to_artifact_evidence(self):
        identifier=self.begin()
        self.service.finish(identifier,200,{'state':'prepared','outcome':{'artifact_id':'invented','content':'SECRET'}})
        self.assertEqual(self.events()[0]['outcome'],'succeeded')
        self.assertEqual(self.events()[0]['result_references'],[])
        second=self.begin(dict(self.request,operation_id=str(uuid4())))
        self.service.finish(second,200,{'projection':{'state':'unknown'}})
        self.assertEqual(self.events()[1]['outcome'],'unknown')
