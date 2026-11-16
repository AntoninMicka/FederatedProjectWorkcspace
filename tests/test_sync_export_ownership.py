# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Export immutable heads without owning the project writer during Git work."""
import threading
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes import federation_sync as sync
from spikes.projects import Projects
from spikes.request_ownership import bounded_project_requests
from tests import test_federation_sync as fixtures


class SyncExportOwnershipTests(unittest.TestCase):
    setUp = fixtures.FederationSyncTests.setUp
    state = fixtures.FederationSyncTests.state
    change = fixtures.FederationSyncTests.change
    exchange = fixtures.FederationSyncTests.exchange
    commit_marker = fixtures.FederationSyncTests.commit_marker

    def blocked_export(self, index, action):
        workspace = Projects(self.nodes[index]).workspace(self.project_id)
        root = workspace.git.root
        entered, release = threading.Event(), threading.Event()
        result, errors = [], []
        original = sync.validate_histories
        def blocked(git, *args, **kwargs):
            if not entered.is_set():
                entered.set()
                if not release.wait(5): raise AssertionError('Export validation not released')
            return original(git, *args, **kwargs)
        def export():
            try: result.append(sync._build_bundle(self.nodes[index], self.project_id, {'mode':'all'}))
            except Exception as exc: errors.append(exc)
        with patch('spikes.federation_sync.validate_histories', side_effect=blocked):
            worker = threading.Thread(target=export); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                with bounded_project_requests(): action(workspace)
            finally:
                release.set(); worker.join(10)
        self.assertFalse(worker.is_alive())
        return result, errors

    def test_slow_export_validation_does_not_reject_incoming_sync_or_project_view(self):
        self.commit_marker(0, 'Initial')
        self.exchange(0, 1)
        envelope, payload, _, _, _ = sync._prepare(self.services[0], self.node_ids[1],
            self.project_id, str(uuid4()), [], force_bundle=True)
        def incoming(workspace):
            view = Projects(self.nodes[1]).dashboard_view(self.project_id)
            self.assertEqual(view['commit_id'], workspace.git.head())
            response, body = sync.SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
            self.assertEqual(response['accepted_source_refs'], envelope['exchange']['refs'])
        result, errors = self.blocked_export(1, incoming)
        self.assertEqual(errors, [])
        self.assertTrue(result[0][1])

    def test_concurrent_native_commit_is_preserved_and_export_becomes_busy(self):
        self.commit_marker(0, 'Original')
        heads = []
        result, errors = self.blocked_export(0, lambda workspace:
            heads.append(self.commit_marker(0, 'Concurrent native write')))
        self.assertEqual(result, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], sync.SyncBusy)
        self.assertEqual(Projects(self.nodes[0]).repository(self.project_id).head(), heads[0])

    def test_dirty_edit_during_export_is_retained_and_requires_conflict_decision(self):
        self.commit_marker(0, 'Original')
        saved=[]
        def edit(workspace):
            path=next(workspace.git.root / name for name in workspace.git.snapshot(workspace.git.head())
                      if name.endswith('.md'))
            path.write_bytes(path.read_bytes()+b'\nUncommitted edit\n');saved.append(path)
        result, errors=self.blocked_export(0,edit)
        self.assertEqual(result,[]);self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],sync.SyncConflict)
        self.assertTrue(saved[0].read_bytes().endswith(b'Uncommitted edit\n'))

    def test_pending_native_write_during_export_keeps_its_recovery_and_one_commit(self):
        from tests.fixtures import markdown,metadata
        before=Projects(self.nodes[0]).repository(self.project_id).head()
        artifact=str(uuid4());path=f'artifacts/{artifact}/document.md'
        def prepare(workspace):
            def crash(stage):
                if stage=='prepared':raise RuntimeError('Native crash')
            with self.assertRaises(RuntimeError):
                workspace.apply({path:markdown(metadata(title='Pending',entity_id=artifact))},
                    author_name='Tester',author_email='test@example.invalid',
                    message='Pending native write',checkpoint=crash)
        result,errors=self.blocked_export(0,prepare)
        self.assertEqual(result,[]);self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],sync.SyncBusy)
        workspace=Projects(self.nodes[0]).workspace(self.project_id)
        self.assertEqual(workspace.git.head(),before)
        workspace.recover()
        self.assertIn(path,workspace.git.snapshot(workspace.git.head()))
        self.assertEqual(workspace.git.run('rev-list','--count',before+'..HEAD').stdout.strip(),'1')

    def test_legacy_export_validation_allows_read_and_native_commit_is_not_lost(self):
        from spikes import git_transfer
        from spikes.request_ownership import ProjectBusy
        self.commit_marker(0,'Original')
        entered,release=threading.Event(),threading.Event();errors=[];heads=[]
        original=git_transfer.validate_history
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(5):raise AssertionError('Export not released')
            return original(*args,**kwargs)
        def export():
            try:git_transfer.export_bundle(self.nodes[0],self.project_id,sync.PRIVACY)
            except Exception as exc:errors.append(exc)
        with patch('spikes.git_transfer.validate_history',side_effect=blocked):
            worker=threading.Thread(target=export);worker.start()
            try:
                self.assertTrue(entered.wait(2))
                with bounded_project_requests():
                    Projects(self.nodes[0]).dashboard_view(self.project_id)
                    heads.append(self.commit_marker(0,'Concurrent write during replica export'))
            finally:release.set();worker.join(10)
        self.assertFalse(worker.is_alive());self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],ProjectBusy)
        self.assertEqual(Projects(self.nodes[0]).repository(self.project_id).head(),heads[0])

    def test_legacy_export_rejects_registration_removed_while_validating(self):
        from spikes import git_transfer
        from spikes.request_ownership import ProjectBusy
        entered,release=threading.Event(),threading.Event();errors=[];results=[]
        original=git_transfer.validate_history
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(5):raise AssertionError('Export not released')
            return original(*args,**kwargs)
        def export():
            try:results.append(git_transfer.export_bundle(self.nodes[0],self.project_id,sync.PRIVACY))
            except Exception as exc:errors.append(exc)
        before=self.nodes[0].read_bytes()
        with patch('spikes.git_transfer.validate_history',side_effect=blocked):
            worker=threading.Thread(target=export);worker.start()
            try:
                self.assertTrue(entered.wait(2))
                node=json.loads(before);node['projects']=[]
                self.nodes[0].write_text(json.dumps(node))
            finally:release.set();worker.join(10)
        self.assertFalse(worker.is_alive());self.assertEqual(results,[])
        self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ProjectBusy)
        self.assertEqual(json.loads(self.nodes[0].read_text())['projects'],[])
