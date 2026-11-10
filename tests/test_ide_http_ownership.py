# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""HTTP admission never replaces queue locks or native human-review recovery."""
from contextlib import closing
import fcntl
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

from spikes.desktop_management import DesktopManagementHandler
from spikes.ide_bridge_panel import review as native_review
from spikes.local_api import Handler, running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_queue import TaskQueue
from tests import test_ide_bridge_panel as fixtures
from tests import test_project_http_ownership as ownership


class IDEHTTPOwnershipTests(unittest.TestCase):
    post = ownership.ProjectHTTPOwnershipTests.post

    def setUp(self):
        self.f = fixtures.BridgePanelTests('test_review_task_completion_replays_without_second_commit')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.record = self.f.session()
        self.node = self.f.node; self.pid = self.f.project
        self.service = self.f.service; self.projects = Projects(self.node)
        self.queue = TaskQueue(self.node); self.owner = ProjectCreation(self.node).author_id()

    def test_queue_bridge_and_review_share_one_independent_http_owner(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        original = TaskQueue.execute
        def blocked(queue, *args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Queue owner not released')
            return original(queue, *args, **kwargs)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.ide_bridge_service = self.service
            with patch.object(TaskQueue, 'execute', blocked):
                worker = threading.Thread(target=lambda: results.append(self.post(
                    server, '/v1/task-queue', {'project_id': self.pid, 'action': 'status'})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.post(server, '/v1/ide-bridge/status',
                        {'project_id': self.pid}, token='invalid')[0], 401)
                    code, payload, _ = self.post(server, '/v1/ide-bridge/status', {'project_id': self.pid})
                    self.assertEqual(code, 503, payload)
                    self.assertEqual(payload['outcome'], 'not-started')
                    self.assertEqual(self.post(server, '/v1/counter', {'action': 'increment'})[0], 200)
                    self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.pid})[0], 200)
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0][0], 200, results)
            server.application_lane.acquire(); server.provider_lane.acquire()
            try:
                self.assertEqual(self.post(server, '/v1/ide-bridge/status', {'project_id': self.pid})[0], 200)
            finally:
                server.provider_lane.release(); server.application_lane.release()

    def test_bridge_sqlite_busy_is_not_credential_failure_or_state_loss(self):
        path = self.service.root / 'bridge.sqlite'
        before = path.read_bytes()
        token = self.f.created['pairing']['token']
        request = {'connection_id': self.record['connection_id'], 'action': 'status'}
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.ide_bridge_service = self.service
            with closing(sqlite3.connect(path)) as owner:
                owner.execute('BEGIN EXCLUSIVE')
                code, payload, _ = self.post(server, '/v1/ide-bridge/connection/exchange', request, token=token)
                self.assertEqual(code, 503, payload)
                self.assertEqual(payload['outcome'], 'unknown')
                self.assertEqual(payload['retry'], 'same-operation')
                self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.pid})[0], 200)
                owner.rollback()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.post(server, '/v1/ide-bridge/connection/exchange', request, token=token)[0], 200)
        with self.service.database() as db:
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 5000)

    def test_native_queue_collision_is_http_unknown_and_preserves_selection(self):
        current = self.queue.execute({'project_id': self.pid, 'action': 'status'}, self.owner)
        self.queue.execute({'project_id': self.pid, 'action': 'add', 'task_id': 'TASK-01',
                            'revision': current['revision'], 'expected_head': current['expected_head']}, self.owner)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.ide_bridge_service = self.service
            with self.queue._lock(self.pid, self.owner) as path:
                before = path.read_bytes()
                code, payload, _ = self.post(server, '/v1/task-queue', {'project_id': self.pid, 'action': 'status'})
                self.assertEqual(code, 503, payload)
                self.assertEqual(payload['outcome'], 'unknown')
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaisesRegex(ValueError, 'Frontu'):
                    with self.queue._lock(self.pid, self.owner):
                        self.fail('Native lock policy changed')
            code, state, _ = self.post(server, '/v1/task-queue', {'project_id': self.pid, 'action': 'status'})
            self.assertEqual(code, 200, state)
            self.assertEqual(state['task_ids'], ['TASK-01'])

    def test_ide_credential_is_revalidated_after_admission(self):
        original = Handler._in_request_lane
        entered = []
        def revoke_before_owner(handler, operation, **kwargs):
            if handler.path == '/v1/ide-bridge/connection/exchange':
                self.assertEqual(handler.bridge_connection['connection_id'], self.record['connection_id'])
                entered.append(True)
                self.service.connection_revoke(None, self.record['connection_id'])
            return original(handler, operation, **kwargs)
        head = self.projects.repository(self.pid).head()
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.ide_bridge_service = self.service
            with patch.object(Handler, '_in_request_lane', revoke_before_owner), \
                 patch.object(self.service, 'connection_exchange', side_effect=AssertionError('revoked dispatch')):
                code, _, _ = self.post(server, '/v1/ide-bridge/connection/exchange',
                    {'connection_id': self.record['connection_id'], 'action': 'status'},
                    token=self.f.created['pairing']['token'])
                self.assertEqual(code, 401)
        self.assertEqual(entered, [True])
        self.assertEqual(self.projects.repository(self.pid).head(), head)

    def test_busy_after_review_intent_recovers_same_operation_once(self):
        message = self.f.send()
        request = self.f.review(message)
        head = self.projects.repository(self.pid).head()
        workspace = self.projects.workspace(self.pid)
        held = []
        def checkpoint(stage):
            if stage == 'intent-prepared':
                handle = (workspace.journal.state / 'writer.lock').open('a+b')
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(handle)
        def interrupted(actor, body):
            return native_review(self.service, actor, body, checkpoint=checkpoint)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.ide_bridge_service = self.service
            try:
                with patch.object(self.service, 'review', side_effect=interrupted):
                    code, payload, _ = self.post(server, '/v1/ide-bridge/review', request)
                self.assertEqual(code, 503, payload)
                self.assertEqual(payload['outcome'], 'unknown')
                self.assertEqual(self.projects.repository(self.pid).head(), head)
            finally:
                for handle in held: handle.close()
            with self.service.database() as db:
                saved = json.loads(db.execute('SELECT record FROM reviews WHERE session=? AND id=?',
                    (request['session_id'], request['message_id'])).fetchone()[0])
            self.assertEqual(saved['state'], 'prepared')
            self.assertEqual(saved['request'], request)
            code, receipt, _ = self.post(server, '/v1/ide-bridge/review', request)
            self.assertEqual(code, 200, receipt)
            self.assertEqual(receipt['state'], 'completed')
            self.assertEqual(receipt['request']['operation_id'], request['operation_id'])
            self.assertEqual(self.post(server, '/v1/ide-bridge/review', request)[1], receipt)
        git = self.projects.repository(self.pid)
        self.assertEqual(git.run('rev-list', '--count', head+'..HEAD').stdout.strip(), '1')
