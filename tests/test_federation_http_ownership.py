# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Slow transfers do not own cancellation, node preferences or project reads."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration
from spikes.application_access import ApplicationAccess
from spikes.desktop_management import DesktopManagementHandler
from spikes.federation_catalog import CatalogStore
from spikes.federation_sync import _database, _journal_path, ManualSyncTasks
from spikes.gamepad_settings import GamepadSettings, DEFAULT_GAMEPAD_SETTINGS
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.user_profile import UserProfile
from tests import test_project_http_ownership as ownership


class FederationHTTPOwnershipTests(unittest.TestCase):
    post = ownership.ProjectHTTPOwnershipTests.post

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.node = self.root / 'node.json'
        self.pid = ProjectCreation(self.node).create('Transfer', self.root / 'project', str(uuid4()))['id']
        self.projects = Projects(self.node)
        Administration(self.node, deployment='desktop').request(
            {'id': None, 'node_role': 'federation-admin', 'memberships': {}}, {'action': 'list'})

    def test_slow_catalog_allows_cancel_settings_project_and_node_requests(self):
        entered, release = threading.Event(), threading.Event(); results = []
        def transfer(*args):
            entered.set()
            if not release.wait(5): raise AssertionError('Transfer not released')
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.administration = Administration(self.node, deployment='desktop')
            with patch('spikes.federation_catalog.CatalogControl.synchronize', transfer), \
                    patch('spikes.federation_catalog.CatalogControl.view', return_value={}), \
                    patch('spikes.federation_sync.ContentSyncControl.cancel', return_value=False), \
                    patch('spikes.federation_sync.ContentSyncControl.statuses', return_value={}):
                worker = threading.Thread(target=lambda: results.append(self.post(server,
                    '/v1/federation/catalog/reconcile', {'peer_id': str(uuid4())})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    code, busy, _ = self.post(server, '/v1/federation/catalog/reconcile', {'peer_id': str(uuid4())})
                    self.assertEqual(code, 503, busy)
                    self.assertEqual(busy['outcome'], 'not-started')
                    self.assertEqual(self.post(server, '/v1/federation/catalog/reconcile', {}, token='bad')[0], 401)
                    server.application_lane.acquire(); server.provider_lane.acquire()
                    try:
                        for path, body in [('/v1/federation/content/cancel', {'peer_id': str(uuid4()), 'project_id': self.pid}),
                                           ('/v1/projects/open', {'project_id': self.pid}),
                                           ('/v1/counter', {'action': 'increment'})]:
                            self.assertEqual(self.post(server, path, body)[0], 200, path)
                    finally:
                        server.provider_lane.release(); server.application_lane.release()
                finally:
                    release.set(); worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0][0], 200, results)

    def test_transfer_native_busy_is_not_swallowed_as_conflict(self):
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.administration = Administration(self.node, deployment='desktop')
            for path, method, body in [
                    ('/v1/federation/catalog/reconcile', 'spikes.federation_catalog.CatalogControl.synchronize', {'peer_id': str(uuid4())}),
                    ('/v1/replications/sync', 'spikes.replication_control.ReplicationControl.synchronize', {'replication_id': str(uuid4())}),
                    ('/v1/federation/content/cancel', 'spikes.federation_sync.ContentSyncControl.cancel', {'peer_id': str(uuid4()), 'project_id': self.pid})]:
                with self.subTest(path=path), patch(method, side_effect=ProjectBusy('native owner')):
                    code, result, _ = self.post(server, path, body)
                    self.assertEqual(code, 503, result)
                    self.assertEqual(result['outcome'], 'unknown')

    def test_preferences_and_federation_databases_fail_fast_and_recover(self):
        profile = UserProfile(self.node)
        original = dict(name='Original', email='', phone='', web='')
        profile.save(original)
        gamepad = GamepadSettings(self.node); gamepad.save(DEFAULT_GAMEPAD_SETTINGS)
        access = ApplicationAccess(self.node, '127.0.0.0/8')
        access.confirm(access.preview({'mode': 'localhost', 'allowed': []}, '127.0.0.1'), '127.0.0.1', False)
        catalog = CatalogStore(self.node); catalog.outbound(str(uuid4()), [])
        with _database(self.node): pass
        operations = [(profile.path, lambda: profile.save(dict(original, name='Changed'))),
                      (gamepad.path, lambda: gamepad.save(DEFAULT_GAMEPAD_SETTINGS)),
                      (access.path, lambda: access.confirm(access.preview({'mode': 'unrestricted', 'allowed': []}, '127.0.0.1'), '127.0.0.1', False)),
                      (catalog.path, lambda: catalog.outbound(str(uuid4()), [])),
                      (_journal_path(self.node), lambda: self.write_sync_setting())]
        for path, operation in operations:
            with self.subTest(path=path.name), closing(sqlite3.connect(path)) as db:
                db.execute('BEGIN EXCLUSIVE')
                with bounded_project_requests(), self.assertRaises(ProjectBusy): operation()
                db.rollback()
                with bounded_project_requests(): operation()
        self.assertEqual(profile.load()['name'], 'Changed')

    def write_sync_setting(self):
        with _database(self.node) as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (1,0,0)')

    def test_manual_sync_mutex_contention_is_bounded_without_creating_tasks(self):
        tasks = ManualSyncTasks(); peer = str(uuid4())
        # The native/background owner can hold its mutex while persisting state.
        with tasks.lock:
            with bounded_project_requests():
                for call in (lambda: tasks.active(self.node, peer, self.pid),
                             lambda: tasks.start(self.node, 'desktop', peer, self.pid),
                             lambda: tasks.cancel(self.node, peer, self.pid)):
                    with self.assertRaises(ProjectBusy): call()
            self.assertEqual(tasks.tasks, {})
        with bounded_project_requests():
            self.assertFalse(tasks.active(self.node, peer, self.pid))

    def test_source_import_shares_nested_project_owner_before_dispatch(self):
        with running_api('http', handler=DesktopManagementHandler, projects=self.projects) as server:
            server.administration = Administration(self.node, deployment='desktop')
            with server.project_lanes.acquire(self.pid, .1):
                code, payload, _ = self.post(server, '/v1/sources/import',
                    {'operation_id': str(uuid4()), 'source': {'project_id': self.pid}})
                self.assertEqual(code, 503, payload)
                self.assertEqual(payload['outcome'], 'not-started')
