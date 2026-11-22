# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Recovery across native commits and local receipts, without replaying effects."""
import json
import subprocess
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.task_activities import TaskActivities
from spikes.task_records import TaskRecords
from spikes.task_work import TaskWork
from tests import test_task_work as fixtures


class TaskRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskWorkTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.work = self.f.service; self.handle = self.f.handle
        self.view = self.work.execute(self.f.start_request())
        self.activities = TaskActivities(self.work)

    def save_request(self):
        return dict(operation_id=str(uuid4()), document=dict(project_id=self.f.f.pid,
            artifact_id=str(uuid4()), base_head=self.work.projects.repository(self.f.f.pid).head(),
            title='Inventory', body='# PRIVATE inventory\n', new=True))

    def begin(self, request, route='/v1/artifacts/editor/save'):
        return self.activities.begin(self.handle, self.work.status(self.handle)['context_revision'], route, request)

    def events(self, view):
        return next(s for s in view['sessions'] if s['work_session_id'] == self.view['active_session_id'])['activities']

    def test_process_death_after_native_save_recovers_original_session_once(self):
        request = self.save_request(); event = self.begin(request)
        script = '''import json,os,sys
from spikes.task_work import TaskWork
from spikes.task_activities import TaskActivities
from spikes.artifacts import Artifacts
work=TaskWork(sys.argv[1]);request=json.loads(sys.argv[3])
with TaskActivities(work).observe(sys.argv[2]):
 Artifacts(sys.argv[1]).save(request['document'],request['operation_id'])
os._exit(79)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.f.f.node), event, json.dumps(request)])
        self.assertEqual(result.returncode, 79)
        git = self.work.projects.repository(self.f.f.pid); head = git.head()
        restarted = TaskWork(self.f.f.node)
        with patch.object(Artifacts, 'save', side_effect=AssertionError('No repeated save')):
            view = restarted.status(self.handle)
            recovered = self.events(view)[0]
            self.assertEqual(recovered['outcome'], 'succeeded')
            self.assertEqual(recovered['offer']['state'], 'pending')
            self.assertNotIn('není potvrzen', recovered['offer']['comment'])
            self.assertNotIn('PRIVATE', json.dumps(recovered))
            self.assertEqual(restarted.status(self.handle), view)
        self.assertEqual(git.head(), head)
        self.assertFalse(view['sessions'][0]['current_task']['checked'])

    def test_wrong_native_digest_and_missing_receipt_remain_unknown(self):
        request = self.save_request(); event = self.begin(request)
        Artifacts(self.f.f.node).save(dict(request['document'], body='Different effect'), request['operation_id'])
        self.assertEqual(self.events(self.work.status(self.handle))[0]['outcome'], 'unknown')
        request = self.save_request(); self.begin(request)
        self.assertTrue(all(e['outcome'] == 'unknown' for e in self.events(self.work.status(self.handle))))

    def test_observer_binds_other_native_routes_and_restores_context(self):
        from spikes.operation_observer import native_observer
        request = self.save_request()
        event = self.begin(request, '/v1/presentations/save')
        with self.activities.observe(event):
            Artifacts(self.f.f.node).save(request['document'], request['operation_id'])
        self.assertIsNone(native_observer.get())
        self.assertEqual(self.events(self.work.status(self.handle))[0]['outcome'], 'succeeded')

    def test_lost_save_stays_with_original_task_after_switch_and_concurrent_refresh(self):
        from concurrent.futures import ThreadPoolExecutor
        request = self.save_request(); self.begin(request)
        Artifacts(self.f.f.node).save(request['document'], request['operation_id'])
        # The old result is not yet reconciled while another task is activated.
        with patch.object(TaskActivities, 'reconcile'):
            switched = self.work.execute(self.f.start_request('TASK-X', 'switch'))
        head = self.work.projects.repository(self.f.f.pid).head()
        with ThreadPoolExecutor(max_workers=2) as pool:
            views = list(pool.map(lambda _: TaskWork(self.f.f.node).status(self.handle), range(2)))
        for view in views:
            self.assertEqual(view['active_session_id'], switched['active_session_id'])
            self.assertEqual(self.events(view)[0]['context']['task_id'], 'TASK-A')
            self.assertEqual(self.events(view)[0]['outcome'], 'succeeded')
            self.assertEqual(next(s for s in view['sessions'] if s['work_session_id']==switched['active_session_id'])['activities'], [])
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(), head)

    def test_revocation_and_other_window_do_not_reconcile_local_receipt(self):
        request = self.save_request(); self.begin(request)
        Artifacts(self.f.f.node).save(request['document'], request['operation_id'])
        other = {k:v for k,v in self.work.create_window().items() if k.startswith('window_')}
        self.work.status(other)
        self.assertEqual(self.activities.for_session(self.handle, self.view['active_session_id'])[0]['outcome'], 'unknown')
        self.work.can_write = lambda pid: False
        self.work.status(self.handle)
        self.work.can_write = lambda pid: True
        self.assertEqual(self.activities.for_session(self.handle, self.view['active_session_id'])[0]['outcome'], 'unknown')
        self.assertEqual(self.events(self.work.status(self.handle))[0]['outcome'], 'succeeded')

    def test_confirmed_commit_reconciles_but_unpublished_confirmation_waits(self):
        request = self.save_request(); self.begin(request)
        Artifacts(self.f.f.node).save(request['document'], request['operation_id'])
        view = self.work.status(self.handle); event = self.events(view)[0]
        service = TaskRecords(self.work)
        confirmation = dict(self.handle, action='record-publish', operation_id=str(uuid4()),
            work_session_id=self.view['active_session_id'], event_ids=[event['event_id']],
            offer_revisions=[event['offer']['revision']], comment='Ready for review',
            selected_checklist=None, expected_head=self.work.projects.repository(self.f.f.pid).head(), privacy='project')
        def stop(stage):
            if stage == 'task-record-intent-prepared': raise RuntimeError('crash')
        with self.assertRaises(RuntimeError): service.execute(confirmation, checkpoint=stop)
        git = self.work.projects.repository(self.f.f.pid); before = git.head()
        self.assertEqual(self.events(self.work.status(self.handle))[0]['offer']['state'], 'pending')
        self.assertEqual(git.head(), before)
        def committed(stage):
            if stage == 'task-record-after-project': raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):
            service.execute(dict(self.handle, action='record-recover', operation_id=confirmation['operation_id']), checkpoint=committed)
        head = git.head()
        recovered = TaskWork(self.f.f.node).status(self.handle)
        self.assertEqual(self.events(recovered)[0]['offer']['state'], 'confirmed')
        self.assertEqual(len(recovered['sessions'][0]['task_records']), 1)
        self.assertEqual(recovered['sessions'][0]['record_pending'], [])
        self.work.status(self.handle); self.assertEqual(git.head(), head)

    def test_completed_chat_is_read_from_journal_unknown_is_not_retried(self):
        from spikes.chat_threads import ChatThreads
        self.work.chat_state_dir.mkdir(mode=0o700)
        store = ChatThreads(self.work.chat_state_dir)
        thread, turn, run, message = [str(uuid4()) for _ in range(4)]
        owner = dict(node_id=self.work.node_id, user_id=self.work.user_id)
        store.create(thread_id=thread, **owner, created_at='2026-11-22T00:00:00Z', project_id=self.f.f.pid)
        request = dict(project_id=self.f.f.pid, thread_id=thread, turn_id=turn, run_id=run,
                       message_id=message, content='PRIVATE prompt')
        self.begin(request, '/v1/chat/send')
        store.prepare_turn(thread_id=thread, **owner, turn_id=turn, message_id=message,
            content='PRIVATE prompt', privacy='confidential', created_at='2026-11-22T00:00:01Z')
        store.bind_run(turn_id=turn, **owner, run_id=run)
        self.assertEqual(self.events(self.work.status(self.handle))[0]['outcome'], 'unknown')
        store.complete(turn_id=turn, **owner, run_id=run, message_id=str(uuid4()), content='PRIVATE answer',
            privacy='confidential', created_at='2026-11-22T00:00:02Z')
        event = self.events(self.work.status(self.handle))[0]
        self.assertEqual(event['outcome'], 'succeeded'); self.assertEqual(event['privacy'], 'confidential')
        self.assertNotIn('PRIVATE', json.dumps(event))

    def test_completed_turn_with_different_input_is_not_success_proof(self):
        from spikes.chat_threads import ChatThreads
        self.work.chat_state_dir.mkdir(mode=0o700)
        store = ChatThreads(self.work.chat_state_dir)
        thread, turn, run, message = [str(uuid4()) for _ in range(4)]
        owner = dict(node_id=self.work.node_id, user_id=self.work.user_id)
        store.create(thread_id=thread, **owner, created_at='2026-11-22T00:00:00Z', project_id=self.f.f.pid)
        self.begin(dict(project_id=self.f.f.pid, thread_id=thread, turn_id=turn, run_id=run,
                        message_id=message, content='Different request'), '/v1/chat/send')
        store.prepare_turn(thread_id=thread, **owner, turn_id=turn, message_id=message,
            content='Original request', privacy='project', created_at='2026-11-22T00:00:01Z')
        store.bind_run(turn_id=turn, **owner, run_id=run)
        store.complete(turn_id=turn, **owner, run_id=run, message_id=str(uuid4()), content='Answer',
            privacy='project', created_at='2026-11-22T00:00:02Z')
        self.assertEqual(self.events(self.work.status(self.handle))[0]['outcome'], 'unknown')
