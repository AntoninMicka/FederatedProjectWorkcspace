# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native state remains authoritative when HTTP monitoring ownership is split."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from spikes.monitoring import Monitoring
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.rss_sources import RSSSources
from tests import test_project_http_ownership as ownership
from tests.test_rss_pilot import rss


class MonitoringOwnershipTests(unittest.TestCase):
    post = ownership.ProjectHTTPOwnershipTests.post

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.node = self.root / 'node.json'
        self.pid = ProjectCreation(self.node).create('Monitoring owner', self.root / 'project', str(uuid4()))['id']
        self.projects = Projects(self.node)
        self.service = Monitoring(self.node, self.projects)

    def test_blocked_monitoring_does_not_block_other_domains(self):
        entered, release = threading.Event(), threading.Event()
        responses = []
        original = self.service.view
        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Monitoring owner not released')
            return original(*args, **kwargs)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.monitoring = self.service
            server.rss_sources = RSSSources(channels=())
            with patch.object(self.service, 'view', side_effect=blocked):
                worker = threading.Thread(target=lambda: responses.append(
                    self.post(server, '/v1/monitoring/view', {'project_id': self.pid})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.post(server, '/v1/monitoring/rss-status',
                        {'project_id': self.pid}, token='invalid')[0], 401)
                    status, payload, _ = self.post(server, '/v1/monitoring/rss-status', {'project_id': self.pid})
                    self.assertEqual(status, 503, payload)
                    self.assertEqual(payload['outcome'], 'not-started')
                    self.assertEqual(self.post(server, '/v1/counter', {'action': 'increment'})[0], 200)
                    self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.pid})[0], 200)
                    self.assertEqual(self.post(server, '/v1/rss-sources/view', {})[0], 200)
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(responses[0][0], 200, responses)
            server.application_lane.acquire(); server.provider_lane.acquire(); server.julia_lane.acquire()
            try:
                self.assertEqual(self.post(server, '/v1/monitoring/rss-status', {'project_id': self.pid})[0], 200)
            finally:
                server.julia_lane.release(); server.provider_lane.release(); server.application_lane.release()

    def test_manual_rss_fetch_does_not_block_monitoring_or_project(self):
        entered, release = threading.Event(), threading.Event()
        responses = []
        def fetcher(url):
            entered.set()
            if not release.wait(5):
                raise AssertionError('RSS owner not released')
            return rss(url)
        cache = RSSSources(channels=({'id': 'test', 'name': 'Feed', 'url': 'https://example.org/feed'},), fetcher=fetcher)
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.monitoring = self.service; server.rss_sources = cache
            worker = threading.Thread(target=lambda: responses.append(
                self.post(server, '/v1/rss-sources/refresh', {'channel_id': 'test'})))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                status, payload, _ = self.post(server, '/v1/rss-sources/view', {})
                self.assertEqual(status, 503, payload)
                self.assertEqual(payload['outcome'], 'not-started')
                self.assertEqual(self.post(server, '/v1/monitoring/rss-status', {'project_id': self.pid})[0], 200)
                self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.pid})[0], 200)
            finally:
                release.set(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(responses[0][0], 200, responses)
            self.assertEqual(cache.view()['channels'][0]['state'], 'ready')

    def test_scheduler_and_pool_sqlite_collision_is_http_unknown_and_preserves_state(self):
        scheduler = self.service.scheduler
        pools = self.service.composable.pools
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.monitoring = self.service
            for path, route in ((scheduler.path, '/v1/monitoring/rss-status'),
                                (pools.path, '/v1/monitoring/blocks')):
                with self.subTest(database=path.name), closing(sqlite3.connect(path)) as owner:
                    before = path.read_bytes()
                    owner.execute('BEGIN EXCLUSIVE')
                    started = time.monotonic()
                    status, payload, _ = self.post(server, route, {'project_id': self.pid})
                    self.assertEqual(status, 503, payload)
                    self.assertEqual(payload['outcome'], 'unknown')
                    self.assertEqual(payload['retry'], 'same-operation')
                    self.assertLess(time.monotonic() - started, 1)
                    self.assertEqual(self.post(server, '/v1/projects/open', {'project_id': self.pid})[0], 200)
                    owner.rollback()
                    self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.post(server, route, {'project_id': self.pid})[0], 200)
        for owner in (scheduler, pools):
            with owner.db() as db:
                self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 30000)
            with bounded_project_requests(), owner.db() as db:
                self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0], 0)

    def test_lazy_services_are_single_flight_and_http_contention_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        value = object(); results = []
        def create(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Initialization not released')
            return value
        with patch('spikes.monitoring.ReportingScheduler', side_effect=create) as factory:
            workers = [threading.Thread(target=lambda: results.append(self.service.scheduler)) for _ in range(2)]
            workers[0].start()
            try:
                self.assertTrue(entered.wait(2)); workers[1].start()
                with bounded_project_requests(), self.assertRaises(ProjectBusy):
                    _ = self.service.scheduler
            finally:
                release.set()
                for worker in workers:
                    if worker.ident is not None: worker.join(3)
            self.assertFalse(any(worker.is_alive() for worker in workers))
            self.assertEqual(results, [value, value]); self.assertEqual(factory.call_count, 1)

    def test_rss_cache_and_native_refresh_owners_are_bounded_only_for_http(self):
        service = RSSSources(channels=())
        with service.lock:
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                service.view()
        with service.refresh_lock:
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                service.refresh('all')
            with self.assertRaisesRegex(ValueError, 'probíhá'):
                service.refresh('all')
        self.assertEqual(service.view()['entries'], [])

    def test_collector_collision_is_typed_busy_in_http(self):
        # Native callers still receive their original nonblocking flock error.
        with self.service.collector.locked():
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                with self.service.collector.locked():
                    self.fail('Acquired an occupied collector')
            with self.assertRaises(BlockingIOError):
                with self.service.collector.locked():
                    self.fail('Native collector lock changed policy')
