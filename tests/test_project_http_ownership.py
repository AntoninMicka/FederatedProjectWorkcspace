# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import fcntl
import http.client
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.request_ownership import ProjectBusy, ProjectLanes, bounded_project_requests, bounded_flock
from spikes.administration import Administration
from spikes.chat_service import ChatService


class ProjectHTTPOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.node = self.root / 'node.json'
        self.ids = [ProjectCreation(self.node).create(
            'Project ' + str(i), self.root / str(i), str(uuid4()))['id'] for i in range(2)]
        self.projects = Projects(self.node)

    def post(self, server, path, body, *, token=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST', path, body=json.dumps(body), headers={
                'Authorization': 'Bearer ' + (server.token if token is None else token),
                'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            connection.close()

    def test_sqlite_index_and_journal_collision_release_http_worker(self):
        ws = self.projects.workspace(self.ids[0])
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            for path in (ws.index.path, ws.journal.database):
                with self.subTest(database=path.name), closing(sqlite3.connect(path)) as owner:
                    owner.execute('BEGIN EXCLUSIVE')
                    started = time.monotonic()
                    status, payload, headers = self.post(server, '/v1/projects/open',
                                                        {'project_id': self.ids[0]})
                    self.assertEqual(status, 503, payload)
                    self.assertEqual(payload['outcome'], 'unknown')
                    self.assertEqual(headers['Retry-After'], '1')
                    self.assertLess(time.monotonic() - started, 1)
                    self.assertEqual(self.post(server, '/v1/projects/open',
                                              {'project_id': self.ids[1]})[0], 200)
                    owner.rollback()
                self.assertEqual(self.post(server, '/v1/projects/open',
                                          {'project_id': self.ids[0]})[0], 200)

    def test_conflict_status_contention_is_busy_without_hiding_conflicts(self):
        from spikes.federation_sync import _database, _journal_path
        peer_id = str(uuid4())
        with _database(self.node) as db:
            db.execute('INSERT INTO runtime VALUES (?,?,?,?,?,?)',
                       (peer_id, self.ids[0], 'conflict', '', '', ''))
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            with closing(sqlite3.connect(_journal_path(self.node))) as owner:
                owner.execute('BEGIN EXCLUSIVE')
                started = time.monotonic()
                status, payload, _ = self.post(server, '/v1/projects/open',
                                               {'project_id': self.ids[0]})
                self.assertEqual(status, 503, payload)
                self.assertLess(time.monotonic() - started, 1)
                owner.rollback()
            status, payload, _ = self.post(server, '/v1/projects/open',
                                           {'project_id': self.ids[0]})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload['sync_conflicts'], [{'peer_id': peer_id}])

    def test_julia_owner_is_independent_and_status_bypasses_long_julia_work(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        class Julia:
            def definitions(inner, project_id, expected_head):
                entered.set()
                if not release.wait(4):
                    raise AssertionError('Test Julia owner was not released')
                return {'definitions': []}
            def status(inner, project_id, operation_id=None, **kwargs):
                return {'runs': []}
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.julia_workspace = Julia()
            body = {'project_id': self.ids[0], 'expected_head': 'unused-fixture-head'}
            worker = threading.Thread(target=lambda: results.append(
                self.post(server, '/v1/julia/definitions', body)))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.post(server, '/v1/julia/status',
                    {'project_id': self.ids[0]}, token='invalid')[0], 401)
                # AUDIT-B2-T2: status has its own read lane; other Julia work
                # (here a second definitions request) remains serialized.
                status, payload, _ = self.post(server, '/v1/julia/status',
                                               {'project_id': self.ids[0]})
                self.assertEqual(status, 200, payload)
                status, payload, _ = self.post(server, '/v1/julia/definitions', body)
                self.assertEqual(status, 503, payload)
                self.assertEqual(payload['outcome'], 'not-started')
                self.assertEqual(self.post(server, '/v1/counter', {'action': 'increment'})[0], 200)
                self.assertEqual(self.post(server, '/v1/projects/open',
                                          {'project_id': self.ids[1]})[0], 200)
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0][0], 200)
            # The reverse direction also matters: application/provider owners
            # cannot prevent an independent Julia status request.
            server.application_lane.acquire(); server.provider_lane.acquire()
            try:
                self.assertEqual(self.post(server, '/v1/julia/status',
                                          {'project_id': self.ids[0]})[0], 200)
            finally:
                server.provider_lane.release(); server.application_lane.release()

    def test_slow_project_read_allows_same_and_other_project_reads(self):
        entered, release = threading.Event(), threading.Event()
        original = Projects.open
        results = []
        def opening(projects, pid):
            if pid == self.ids[0] and not entered.is_set():
                entered.set()
                if not release.wait(4):
                    raise AssertionError('Test owner was not released')
            return original(projects, pid)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            with patch.object(Projects, 'open', opening):
                thread = threading.Thread(target=lambda: results.append(self.post(
                    server, '/v1/projects/open', {'project_id': self.ids[0]})))
                thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.post(server, '/v1/projects/open',
                        {'project_id': self.ids[0]}, token='invalid')[0], 401)
                    status, payload, headers = self.post(server, '/v1/projects/open',
                        {'project_id': self.ids[0]})
                    self.assertEqual(status, 200, payload)
                    status, payload, _ = self.post(server, '/v1/projects/open',
                        {'project_id': self.ids[1]})
                    self.assertEqual(status, 200, payload)
                    self.assertEqual(payload['id'], self.ids[1])
                    self.assertEqual(self.post(server, '/v1/counter', {'action':'increment'})[0], 200)
                    active = server.http_diagnostics()['requests']
                    self.assertTrue(any(row.get('project_id') == self.ids[0]
                        and row['operation'] == '/v1/projects/open' for row in active))
                finally:
                    release.set(); thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(results[0][0], 200)
                self.assertEqual(server.project_lanes.entries, {})

    def test_desktop_http_journal_contention_is_bounded_and_does_not_fill_workers(self):
        ws = self.projects.workspace(self.ids[0])
        before = ws.git.head()
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            with (ws.journal.state / 'writer.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                for _ in range(6):
                    status, payload, _ = self.post(server, '/v1/projects/open',
                        {'project_id': self.ids[0]})
                    self.assertEqual(status, 503, payload)
                    self.assertEqual(payload['retry'], 'same-operation')
                self.assertEqual(self.post(server, '/v1/projects/open',
                    {'project_id': self.ids[1]})[0], 200)
                self.assertEqual(ws.git.head(), before)
            self.assertEqual(self.post(server, '/v1/projects/open',
                {'project_id': self.ids[0]})[0], 200)

    def test_project_is_not_admitted_before_validated_request_body(self):
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            with patch.object(server.project_lanes, 'acquire', side_effect=AssertionError('admission')):
                self.assertEqual(self.post(server, '/v1/projects/open', {})[0], 400)
                self.assertEqual(self.post(server, '/v1/projects/open',
                    {'project_id':'not-a-project'})[0], 400)
                self.assertEqual(self.post(server, '/v1/projects/open',
                    {'project_id':self.ids[0]}, token='invalid')[0], 401)

    def test_owner_registry_releases_on_failure_and_nested_scope_is_shared(self):
        lanes = ProjectLanes()
        with self.assertRaises(RuntimeError):
            with lanes.acquire(self.ids[0], .01):
                with self.assertRaises(ProjectBusy):
                    with lanes.acquire(self.ids[0], .01):
                        self.fail('Duplicate owner')
                with lanes.acquire(self.ids[1], .01):
                    pass
                raise RuntimeError('Dispatch failed')
        self.assertEqual(lanes.entries, {})

    def test_node_registry_collision_inside_http_context_is_bounded(self):
        service = Administration(self.node)
        with service.locked():
            with bounded_project_requests():
                with self.assertRaises(ProjectBusy):
                    with service.locked():
                        self.fail('Concurrent registry owner')
                with self.assertRaises(ProjectBusy):
                    with service.read_locked():
                        self.fail('Read-only authentication waited for registry owner')
        with service.locked():
            pass

    def test_busy_after_stream_headers_is_a_terminal_frame_not_second_http_response(self):
        from spikes.local_api import Handler
        class Streaming(Handler):
            post_paths = Handler.post_paths | {'/v1/chat/send-stream'}
            def dispatch(self, request):
                if self.path != '/v1/chat/send-stream':
                    return super().dispatch(request)
                self.send_response_only(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.end_headers()
                self.wfile.write(b'{"type":"status","status":"preparing"}\n')
                raise ProjectBusy('Native owner unavailable')
        with running_api('http', handler=Streaming) as server:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                connection.request('POST', '/v1/chat/send-stream', body='{}', headers={
                    'Content-Type':'application/json','Authorization':'Bearer '+server.token})
                response = connection.getresponse(); raw = response.read()
                self.assertEqual(response.status, 200)
                frames = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(frames[-1], {'type':'error','status':503,
                    'error':'resource busy','outcome':'unknown','retry':'same-operation',
                    'busy_resource':'unknown'})
                self.assertEqual(self.post(server, '/v1/counter', {'action':'increment'})[0], 200)
            finally:
                connection.close()

    def test_common_file_owner_bounds_shared_and_exclusive_wait_without_changing_native_wait(self):
        path = self.root / 'owner.lock'
        entered, starting = threading.Event(), threading.Event()
        def native_reader():
            with path.open('a+b') as reader:
                starting.set()
                bounded_flock(reader, fcntl.LOCK_SH, resource='Test owner')
                entered.set()
        with path.open('a+b') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX)
            with path.open('a+b') as contender, bounded_project_requests():
                for mode in (fcntl.LOCK_EX, fcntl.LOCK_SH):
                    with self.assertRaises(ProjectBusy):
                        bounded_flock(contender, mode, resource='Test owner')
            thread = threading.Thread(target=native_reader, daemon=True); thread.start()
            self.assertTrue(starting.wait(1))
            self.assertFalse(entered.wait(.05), 'HTTP context leaked to native ownership')
        thread.join(2)
        self.assertTrue(entered.is_set())
        self.assertFalse(thread.is_alive())

    def test_backend_configuration_contention_releases_application_capacity(self):
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.chat_service = ChatService(self.node, self.projects)
            with server.chat_service.backend_configuration_lock:
                status, payload, _ = self.post(server, '/v1/chat/configure', {})
                self.assertEqual(status, 503, payload)
                self.assertEqual(payload['retry'], 'same-operation')
                self.assertEqual(self.post(server, '/v1/counter', {'action':'increment'})[0], 200)
                self.assertEqual(self.post(server, '/v1/projects/open',
                    {'project_id':self.ids[1]})[0], 200)
            # Acquiring the same RLock again inside a native caller is still
            # reentrant; the domain validation runs and rejects this payload.
            with server.chat_service.backend_configuration_lock:
                with self.assertRaises(ValueError):
                    server.chat_service.configure({})
