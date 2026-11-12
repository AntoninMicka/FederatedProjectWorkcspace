# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Regression boundaries from A01--A06, using temporary state and loopback only."""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.local_api import Handler, running_api
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from tests import test_project_http_ownership as ownership


class HTTPP1Tests(unittest.TestCase):
    post = ownership.ProjectHTTPOwnershipTests.post

    def test_execution_owners_do_not_block_status_control_or_body_parsing(self):
        for held, independent in (
                ('/v1/chat/send-stream', ['/v1/chat/status', '/v1/tasks/cancel', '/v1/chat/configure']),
                ('/v1/monitoring/run', ['/v1/monitoring/view', '/v1/monitoring/cancel'])):
            with self.subTest(held=held):
                entered, release = threading.Event(), threading.Event()
                dispatched = []
                class H(Handler):
                    reserve_ui_worker = True
                    post_paths = {held, *independent}
                    def dispatch(self, request):
                        dispatched.append(self.path)
                        if self.path == held:
                            entered.set()
                            if not release.wait(5):
                                raise AssertionError('Execution not released')
                        self.reply(200, {'ok': True})
                with running_api('http', handler=H) as server:
                    result = []
                    worker = threading.Thread(target=lambda: result.append(self.post(server, held, {})))
                    worker.start()
                    try:
                        self.assertTrue(entered.wait(2))
                        for route in independent:
                            self.assertEqual(self.post(server, route, {})[0], 200)
                        self.assertEqual(self.post(server, independent[0], {}, token='invalid')[0], 401)
                        code, busy, _ = self.post(server, held, {})
                        self.assertEqual(code, 503)
                        self.assertEqual(busy['outcome'], 'not-started')
                    finally:
                        release.set(); worker.join(5)
                    self.assertEqual(result[0][0], 200)
                    self.assertEqual(dispatched.count(held), 1)

    def test_incomplete_headers_leave_diagnostics_and_normal_workers_available(self):
        class H(Handler):
            reserve_ui_worker = True
            post_paths = {'/v1/diagnostics/status', '/v1/chat/status'}
            def dispatch(self, request):
                self.reply(200, {'ok': True})
        with running_api('http', handler=H) as server:
            sockets = []
            try:
                for _ in range(server.worker_limit):
                    client = socket.create_connection(server.server_address, timeout=2)
                    sockets.append(client); client.sendall(b'POST /v1/chat/status HTTP/1.1\r\nHost: ')
                deadline = time.monotonic() + .5
                while server.header_admission.count() < len(sockets) and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(server.header_admission.count(), len(sockets))
                self.assertEqual(server.active_worker_count(), 0)
                self.assertEqual(self.post(server, '/v1/diagnostics/status', {})[0], 200)
                self.assertEqual(self.post(server, '/v1/chat/status', {})[0], 200)
            finally:
                for client in sockets:
                    client.close()
        self.assertTrue(server.shutdown_clean)

    def test_partial_authenticated_bodies_do_not_hold_provider_owner_or_diagnostic_slot(self):
        class H(Handler):
            reserve_ui_worker = True
            post_paths = {'/v1/chat/status', '/v1/diagnostics/status', '/v1/tasks/run-control'}
            assets = {'/fixed': None}
            def _do_GET(self):
                self.reply(200, {'ok': True})
            def dispatch(self, request):
                self.reply(200, {'ok': True})
        with running_api('http', handler=H) as server:
            sockets = []
            try:
                for _ in range(4):
                    client = socket.create_connection(server.server_address, timeout=2)
                    sockets.append(client)
                    client.sendall((f'POST /v1/chat/status HTTP/1.1\r\nHost: {server.authority}\r\n'
                        f'Authorization: Bearer {server.token}\r\nContent-Type: application/json\r\n'
                        'Content-Length: 2\r\n\r\n{').encode())
                deadline = time.monotonic() + .5
                while server.active_worker_count() < 4 and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(server.active_worker_count(), 4)
                self.assertFalse(server.provider_status_lane.locked())
                for path, code in (('/fixed', b' 200 '), ('/oauth/callback', b' 503 ')):
                    with socket.create_connection(server.server_address, timeout=2) as client:
                        client.sendall(f'GET {path} HTTP/1.1\r\nHost: {server.authority}\r\n\r\n'.encode())
                        self.assertIn(code, client.recv(4096).split(b'\r\n', 1)[0])
                self.assertEqual(self.post(server, '/v1/diagnostics/status', {})[0], 200)
                self.assertEqual(self.post(server, '/v1/tasks/run-control', {})[0], 200)
                self.assertEqual(self.post(server, '/v1/tasks/run-control', {}, token='invalid')[0], 401)
            finally:
                for client in sockets:
                    client.sendall(b'}'); client.close()

    def test_stalled_tls_handshakes_do_not_own_accept_or_application_workers(self):
        from tests import test_web_server
        f = test_web_server.WebTests(); f.setUp(); self.addCleanup(f.doCleanups)
        clients = []
        try:
            for _ in range(f.server.worker_limit):
                clients.append(socket.create_connection(f.server.server_address, timeout=2))
            started = time.monotonic()
            code, body, _ = f.request(path='/v1/diagnostics/status')
            self.assertEqual(code, 200, body)
            self.assertLess(time.monotonic()-started, 1.5)
        finally:
            for client in clients:
                client.close()

    def test_header_intake_is_bounded_and_oversized_headers_never_dispatch(self):
        called = []
        class H(Handler):
            reserve_ui_worker = True
            def dispatch(self, request):
                called.append(request)
                super().dispatch(request)
        with running_api('http', handler=H) as server:
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall((f'POST /v1/counter HTTP/1.1\r\nHost: {server.authority}\r\n'
                                'X-Fill: ').encode()+b'x'*65536+b'\r\n\r\n')
                self.assertIn(b' 431 ', client.recv(4096).split(b'\r\n', 1)[0])
            server.header_admission.capacity = 2
            clients = []
            try:
                for _ in range(2):
                    client = socket.create_connection(server.server_address, timeout=2)
                    clients.append(client); client.sendall(b'GET / HTTP/1.1\r\nHost: ')
                deadline = time.monotonic()+.5
                while server.header_admission.count()<2 and time.monotonic()<deadline:
                    time.sleep(.005)
                with socket.create_connection(server.server_address, timeout=2) as extra:
                    self.assertIn(b' 503 ', extra.recv(4096).split(b'\r\n', 1)[0])
                self.assertEqual(server.header_admission.count(), 2)
                self.assertEqual(server.active_worker_count(), 0)
            finally:
                for client in clients:
                    client.close()
        self.assertEqual(called, [])

    def test_monitoring_status_and_prepared_cancel_reach_native_scheduler_during_execution(self):
        from tests.test_reporting_scheduler import ReportingSchedulerTests
        from spikes.monitoring import Monitoring
        from spikes.projects import Projects
        from spikes.desktop_management import DesktopManagementHandler
        f = ReportingSchedulerTests(); f.setUp(); self.addCleanup(f.doCleanups)
        run = f.enqueue(); service = Monitoring(f.node, Projects(f.node)); service._scheduler = f.scheduler
        entered, release = threading.Event(), threading.Event()
        def long_run(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Monitoring execution not released')
            return f.scheduler.get(run['run_id'])
        with running_api('http', handler=DesktopManagementHandler, projects=service.projects) as server:
            server.monitoring = service
            result = []
            with patch.object(service, 'run_now', side_effect=long_run):
                worker = threading.Thread(target=lambda: result.append(self.post(server,
                    '/v1/monitoring/run', dict(project_id=f.project, watch_id=str(uuid4()), kind='weekly'))))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    code, body, _ = self.post(server, '/v1/monitoring/view', {'project_id': f.project})
                    self.assertEqual(code, 200, body)
                    code, cancelled, _ = self.post(server, '/v1/monitoring/cancel',
                        dict(project_id=f.project, run_id=run['run_id'], confirm=True))
                    self.assertEqual(code, 200, cancelled)
                    self.assertEqual(cancelled['state'], 'cancelled')
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result[0][0], 200, result)
                self.assertEqual(f.scheduler.get(run['run_id'])['state'], 'cancelled')


class SnapshotP1Tests(unittest.TestCase):
    def test_slow_pure_view_does_not_own_writer_and_rejects_changed_head(self):
        from spikes.artifacts import Artifacts
        from spikes.storage import Git, StaleIndex
        f = ownership.ProjectHTTPOwnershipTests(); f.setUp(); self.addCleanup(f.doCleanups)
        pid = f.ids[0]; ws = f.projects.workspace(pid)
        head = ws.git.head()
        f.projects.open(pid)
        entered, release = threading.Event(), threading.Event()
        original = Git.snapshot; outcome = []
        def pause(git, *args, **kwargs):
            if threading.current_thread().name == 'pure-view':
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Read not released')
            return original(git, *args, **kwargs)
        def read():
            try:
                with bounded_project_requests():
                    f.projects.plan_view(pid)
            except Exception as exc:
                outcome.append(exc)
        with patch.object(Git, 'snapshot', pause):
            worker = threading.Thread(target=read, name='pure-view'); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                other = f.projects.workspace(pid, for_snapshot=True)
                with bounded_project_requests():
                    self.assertEqual(other.snapshot_checkpoint(), head)
                self.assertEqual(f.projects.plan_view(pid)['commit_id'], head)
                changed = Artifacts(f.node).save(dict(project_id=pid, artifact_id=str(uuid4()),
                    base_head=head, new=True, title='Concurrent write', body='Text'), str(uuid4()))
                self.assertNotEqual(changed['commit_id'], head)
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], StaleIndex)


class SQLiteP1Tests(unittest.TestCase):
    def test_reporting_getters_and_reopen_coexist_with_reserved_writer(self):
        from tests.test_reporting_scheduler import ReportingSchedulerTests
        from spikes.reporting_scheduler import ReportingScheduler
        f = ReportingSchedulerTests(); f.setUp(); self.addCleanup(f.doCleanups)
        run = f.enqueue()
        with closing(sqlite3.connect(f.scheduler.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            with bounded_project_requests():
                self.assertEqual(f.scheduler.get(run['run_id']), run)
                reopened = ReportingScheduler(f.node)
                self.assertEqual(reopened.get(run['run_id']), run)
                with self.assertRaises(ProjectBusy):
                    f.scheduler.cancel(run['run_id'], confirm=True)
            writer.rollback()
        self.assertEqual(f.scheduler.cancel(run['run_id'], confirm=True)['state'], 'cancelled')

    def test_julia_readers_and_native_execution_capacity_preserve_prepared_intent(self):
        from tests.test_julia_computation import JuliaComputationTests
        from spikes.julia_computation import claim_execution_slot
        f = JuliaComputationTests(); f.setUp(); self.addCleanup(f.doCleanups)
        executor, first = f.prepare()
        _, second = f.prepare(executor=executor, value=43)
        with closing(sqlite3.connect(executor.store.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            with bounded_project_requests():
                self.assertEqual(executor.store.get(first['operation_id'], f.node_id, f.user_id)['state'], 'prepared')
                self.assertEqual(len(executor.store.list(f.project_id, f.node_id, f.user_id)), 2)
            writer.rollback()
        slot = claim_execution_slot(executor, first['operation_id'])
        try:
            with self.assertRaises(ProjectBusy) as busy:
                executor.execute(second['operation_id'], f.node_id, f.user_id, second['approval_digest'])
            self.assertEqual(busy.exception.outcome, 'not-started')
            self.assertEqual(executor.store.get(second['operation_id'], f.node_id, f.user_id)['state'], 'prepared')
        finally:
            os.close(slot)
        released = claim_execution_slot(executor, second['operation_id']); os.close(released)

    def test_julia_service_capacity_is_shared_and_released_on_completion_and_start_failure(self):
        from tests.test_julia_computation import JuliaComputationTests
        from spikes.julia_workspace import JuliaWorkspaceService
        from spikes.projects import Projects
        f = JuliaComputationTests(); f.setUp(); self.addCleanup(f.doCleanups)
        executor, first = f.prepare()
        _, second = f.prepare(executor=executor, value=43)
        services = [JuliaWorkspaceService(f.node, Projects(f.node), executor_factory=lambda git: executor)
                    for _ in range(2)]
        for service in services:
            service.identity = lambda user_id=None: (f.node_id, f.user_id)
        def request(record):
            return dict(project_id=f.project_id, operation_id=record['operation_id'],
                        approval_digest=record['approval_digest'])
        entered, release = threading.Event(), threading.Event()
        original = executor._execute
        def long_execute(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Julia executor not released')
            return original(*args, **kwargs)
        with patch.object(executor, '_execute', side_effect=long_execute):
            services[0].execute(request(first))
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(ProjectBusy) as busy:
                    services[1].execute(request(second))
                self.assertEqual(busy.exception.outcome, 'not-started')
                self.assertEqual(executor.store.get(second['operation_id'], f.node_id, f.user_id)['state'], 'prepared')
                self.assertEqual(services[1]._workers, {})
                script = '''
from pathlib import Path
from types import SimpleNamespace
from spikes.julia_computation import JuliaRunStore, claim_execution_slot
from spikes.request_ownership import ProjectBusy
import sys
root=Path(sys.argv[1])
try: claim_execution_slot(SimpleNamespace(state_dir=root,store=JuliaRunStore(root)),sys.argv[2])
except ProjectBusy: sys.exit(0)
sys.exit(1)
'''
                other = subprocess.run([sys.executable, '-c', script, str(executor.state_dir), second['operation_id']],
                                       capture_output=True, text=True, timeout=3)
                self.assertEqual(other.returncode, 0, other.stderr)
            finally:
                release.set()
                for worker in list(services[0]._workers.values()):
                    worker.join(5)
        self.assertEqual(executor.store.get(first['operation_id'], f.node_id, f.user_id)['state'], 'succeeded')
        with patch.object(threading.Thread, 'start', side_effect=RuntimeError('start failed')):
            with self.assertRaisesRegex(RuntimeError, 'start failed'):
                services[1].execute(request(second))
        self.assertEqual(services[1]._workers, {})
        services[1].execute(request(second))
        for worker in list(services[1]._workers.values()):
            worker.join(5)
        self.assertEqual(executor.store.get(second['operation_id'], f.node_id, f.user_id)['state'], 'succeeded')

    def test_julia_orphan_capacity_is_not_freed_by_process_lock_disappearance(self):
        from tests.test_julia_computation import JuliaComputationTests
        from spikes.julia_computation import claim_execution_slot
        f = JuliaComputationTests(); f.setUp(); self.addCleanup(f.doCleanups)
        executor, first = f.prepare()
        _, second = f.prepare(executor=executor, value=43)
        slot = claim_execution_slot(executor, first['operation_id'])
        executor.store.transition(first['operation_id'], f.node_id, f.user_id, {'prepared'}, 'dispatching')
        os.close(slot)  # Same flock release as an owning process crash.
        with self.assertRaises(ProjectBusy):
            claim_execution_slot(executor, second['operation_id'])
        self.assertEqual(executor.reconcile(first['operation_id'], f.node_id, f.user_id)['state'], 'unknown')
        with self.assertRaises(ProjectBusy):
            claim_execution_slot(executor, second['operation_id'])
        self.assertEqual(executor.store.get(second['operation_id'], f.node_id, f.user_id)['state'], 'prepared')
