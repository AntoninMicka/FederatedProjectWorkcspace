# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Project-level removal, trash, recovery and fail-closed inventory tests."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.configuration import parse_node, read_config
from spikes.project_creation import CreationConflict, ProjectCreation
from spikes.project_deletion import ProjectDeletion
from spikes.project_deletion_actions import ProjectDeletionActions
from spikes.projects import Projects
from spikes.storage import Git
from spikes.chat_threads import ChatThreads
from spikes.administration import Administration


class ProjectDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project deletion ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.created = ProjectCreation(self.node).create(
            'Project to remove', self.root, str(uuid4()))
        self.project_id = self.created['id']
        self.service = ProjectDeletion(self.node)

    def binding(self):
        return parse_node(read_config(self.node), location=self.node)['projects'][0]

    def confirm(self, mode, operation=None, checkpoint=lambda stage: None):
        preview = self.service.preview(self.project_id, mode)
        return self.service.confirm(preview, operation or str(uuid4()), checkpoint=checkpoint)

    def test_preview_is_exact_and_clear_derived_rebuilds(self):
        Projects(self.node).open(self.project_id)
        state = Path(self.binding()['state_dir'])
        self.assertTrue((state / 'index.sqlite').exists())
        preview = self.service.preview(self.project_id, 'clear-derived')
        self.assertEqual(preview['root'], str(self.root))
        self.assertEqual(preview['head'], self.created['commit_id'])
        self.assertTrue(preview['index_present'])
        self.assertEqual(preview['blockers'], [])
        receipt = self.service.confirm(preview, str(uuid4()))
        self.assertFalse((state / 'index.sqlite').exists())
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'], self.created['commit_id'])
        self.assertTrue((state / 'index.sqlite').exists())
        self.assertFalse(receipt['unregistered'])

    def test_unregister_preserves_repository_state_and_is_idempotent(self):
        state = Path(self.binding()['state_dir'])
        operation = str(uuid4())
        preview = self.service.preview(self.project_id, 'unregister')
        receipt = self.service.confirm(preview, operation)
        self.assertEqual(receipt, self.service.confirm(preview, operation))
        self.assertEqual(parse_node(read_config(self.node), location=self.node)['projects'], [])
        self.assertEqual(Git(self.root).head(), self.created['commit_id'])
        self.assertTrue(state.exists())

    def test_trash_moves_exact_directories_and_restore_recovers_registration(self):
        state = Path(self.binding()['state_dir'])
        preview = self.service.preview(self.project_id, 'trash')
        operation = str(uuid4())
        receipt = self.service.confirm(preview, operation)
        trash = Path(receipt['trash_path'])
        self.assertFalse(self.root.exists()); self.assertFalse(state.exists())
        self.assertEqual(Git(trash / 'repository').head(), self.created['commit_id'])
        self.assertTrue((trash / 'state' / 'journal.sqlite').exists())
        self.assertEqual(parse_node(read_config(self.node), location=self.node)['projects'], [])
        restore_operation = str(uuid4())
        restored = self.service.restore(operation, restore_operation)
        self.assertEqual(restored, self.service.restore(operation, restore_operation))
        self.assertTrue(restored['restored'])
        self.assertFalse(trash.exists())
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'], self.created['commit_id'])

    def test_trash_recovers_at_each_persistent_boundary(self):
        for stage in ('prepared', 'trash-created', 'root-trashed', 'state-trashed',
                      'node-published'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(
                    prefix='case ', dir=self.base) as folder:
                base = Path(folder); node = base / 'node.json'; root = base / 'project'
                created = ProjectCreation(node).create('Case', root, str(uuid4()))
                service = ProjectDeletion(node); preview = service.preview(created['id'], 'trash')
                operation = str(uuid4())
                with self.assertRaises(RuntimeError):
                    service.confirm(preview, operation, checkpoint=lambda current:
                        (_ for _ in ()).throw(RuntimeError('stop')) if current == stage else None)
                receipt = service.recover()
                self.assertEqual(receipt, service.confirm(preview, operation))
                self.assertFalse(root.exists())
                self.assertEqual(parse_node(read_config(node), location=node)['projects'], [])
                self.assertEqual(Git(Path(receipt['trash_path']) / 'repository').head(),
                                 created['commit_id'])

    def test_pending_workspace_transfer_and_unknown_search_block(self):
        state = Path(self.binding()['state_dir'])
        with sqlite3.connect(state / 'journal.sqlite') as db:
            db.execute("INSERT INTO operations VALUES (?,?,0)", (str(uuid4()), '{}'))
            db.commit()
        with self.assertRaisesRegex((ValueError, CreationConflict), 'Workspace operaci'):
            self.service.preview(self.project_id, 'trash')
        with sqlite3.connect(state / 'journal.sqlite') as db:
            db.execute('DELETE FROM operations WHERE done=0'); db.commit()

        network = self.base / '.node.json.network'; network.mkdir(mode=0o700)
        with sqlite3.connect(network / 'git-transfer-journal.sqlite') as db:
            db.execute('CREATE TABLE transfers(operation_id TEXT PRIMARY KEY,context TEXT,head TEXT,'
                       'commit_count INTEGER,digest TEXT,bundle BLOB,done INTEGER DEFAULT 0)')
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,0)',
                       (str(uuid4()), '{"project_id":"' + self.project_id + '"}',
                        self.created['commit_id'], 1, 'a' * 64, b'x'))
            db.commit()
        (network / 'git-transfer-journal.sqlite').chmod(0o600)
        preview = self.service.preview(self.project_id, 'trash')
        self.assertTrue(any('Git přenos' in item for item in preview['blockers']))

        chat = self.base / '.node.json.chat'; chat.mkdir(mode=0o700)
        with sqlite3.connect(chat / 'search-runs.sqlite') as db:
            db.execute('CREATE TABLE searches(search_id TEXT,task_id TEXT,node_id TEXT,user_id TEXT,'
                       'project_id TEXT,request_json TEXT,request_digest TEXT,preview_json TEXT,'
                       'preview_sha256 TEXT,binding_json TEXT,state TEXT,result_json TEXT,error TEXT,'
                       'error_code TEXT)')
            db.execute('INSERT INTO searches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       tuple(str(uuid4()) for _ in range(4)) + (self.project_id, '{}', 'a'*64,
                       '{}', 'b'*64, '{}', 'unknown', None, None, None))
            db.commit()
        (chat / 'search-runs.sqlite').chmod(0o600)
        preview = self.service.preview(self.project_id, 'trash')
        self.assertTrue(any('neurčitý' in item for item in preview['blockers']))

    def test_administration_membership_blocks_until_explicit_revocation(self):
        administration = Administration(self.node)
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = administration.request(actor, {'action': 'list'})
        state = administration.request(actor, {'action': 'create-user',
            'expected_commit': state['commit_id'], 'name': 'Project member',
            'node_role': 'member'})
        user = state['users'][0]
        state = administration.request(actor, {'action': 'update-user',
            'expected_commit': state['commit_id'], 'user_id': user['id'],
            'active': True, 'node_role': 'member',
            'memberships': {self.project_id: 'reader'}})
        preview = self.service.preview(self.project_id, 'trash')
        self.assertEqual(preview['administration']['memberships'], 1)
        self.assertTrue(any('účtu' in item for item in preview['blockers']))

        administration.request(actor, {'action': 'update-user',
            'expected_commit': state['commit_id'], 'user_id': user['id'],
            'active': True, 'node_role': 'member', 'memberships': {}})
        self.assertEqual(self.service.preview(self.project_id, 'trash')['blockers'], [])

    def test_purge_requires_empty_project_history_and_second_preview(self):
        removal = self.confirm('trash')
        preview = self.service.purge_preview(removal['operation_id'])
        operation = str(uuid4())
        result = self.service.purge(preview, operation)
        self.assertEqual(result, self.service.purge(preview, operation))
        self.assertTrue(result['purged'])
        self.assertFalse(Path(removal['trash_path']).exists())
        self.assertTrue(result['remote_copies_preserved'])

    def test_completed_chat_history_is_preserved_and_blocks_purge(self):
        chat = self.base / '.node.json.chat'; chat.mkdir(mode=0o700)
        ChatThreads(chat).create(thread_id=str(uuid4()), node_id=str(uuid4()),
            user_id=str(uuid4()), created_at='2026-10-13T10:00:00Z',
            project_id=self.project_id)
        preview = self.service.preview(self.project_id, 'trash')
        self.assertEqual(preview['node_records']['records'], 1)
        self.assertEqual(preview['node_records']['unknown_or_active'], 0)
        removal = self.service.confirm(preview, str(uuid4()))
        purge = self.service.purge_preview(removal['operation_id'])
        self.assertTrue(purge['blockers'])
        with self.assertRaises(CreationConflict):
            self.service.purge(purge, str(uuid4()))
        self.assertTrue(Path(removal['trash_path']).exists())

    def test_purge_unlinks_symlink_without_following_external_target(self):
        outside = self.base / 'outside'; outside.mkdir(); sentinel = outside / 'keep'
        sentinel.write_text('preserve')
        (self.root / 'external-link').symlink_to(outside, target_is_directory=True)
        removal = self.confirm('trash')
        preview = self.service.purge_preview(removal['operation_id'])
        self.service.purge(preview, str(uuid4()))
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_action_adapter_rejects_tampered_or_unissued_preview(self):
        actions = ProjectDeletionActions(self.node)
        plan = actions.preview({'project_id': self.project_id, 'mode': 'trash'})
        changed = dict(plan, root=str(self.base / 'other'))
        with self.assertRaises(ValueError):
            actions.confirm({'preview': changed, 'operation_id': str(uuid4())})
        fresh = ProjectDeletionActions(self.node)
        with self.assertRaises(ValueError):
            fresh.confirm({'preview': plan, 'operation_id': str(uuid4())})

    def test_restore_and_purge_are_recoverable_operations(self):
        removal = self.confirm('trash')
        restore_operation = str(uuid4())
        with self.assertRaises(RuntimeError):
            self.service.restore(removal['operation_id'], restore_operation,
                checkpoint=lambda stage: (_ for _ in ()).throw(RuntimeError('stop'))
                if stage == 'root-restored' else None)
        restored = self.service.recover()
        self.assertEqual(restored, self.service.restore(removal['operation_id'], restore_operation))
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'], self.created['commit_id'])

        removal = self.confirm('trash', str(uuid4()))
        preview = self.service.purge_preview(removal['operation_id'])
        purge_operation = str(uuid4())
        with self.assertRaises(RuntimeError):
            self.service.purge(preview, purge_operation,
                checkpoint=lambda stage: (_ for _ in ()).throw(RuntimeError('stop'))
                if stage == 'purged' else None)
        purged = self.service.recover()
        self.assertEqual(purged, self.service.purge(preview, purge_operation))
        self.assertFalse(Path(removal['trash_path']).exists())


if __name__ == '__main__':
    unittest.main()
