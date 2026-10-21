# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only project Check & Repair diagnostics."""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.configuration import parse_node, read_config
from spikes.project_creation import ProjectCreation
from spikes.project_repair import ProjectDiagnostics
from spikes.storage import Git
from tests.fixtures import ENTITY, encoded, markdown, metadata


def filesystem_snapshot(*roots):
    result = {}
    for root in roots:
        root = Path(root)
        if not os.path.lexists(root):
            result[str(root)] = None
            continue
        paths = [root]
        if root.is_dir() and not root.is_symlink():
            paths.extend(sorted(root.rglob('*')))
        for path in paths:
            info = path.lstat()
            row = [info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                   info.st_nlink, info.st_size, info.st_mtime_ns]
            if stat.S_ISREG(info.st_mode):
                row.append(hashlib.sha256(path.read_bytes()).hexdigest())
            elif stat.S_ISLNK(info.st_mode):
                row.append(os.readlink(path))
            result[str(path)] = row
    return result


class ProjectDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project repair ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.created = ProjectCreation(self.node).create(
            'Repair fixture', self.root, str(uuid4()))
        self.project_id = self.created['id']
        binding = parse_node(read_config(self.node), location=self.node)['projects'][0]
        self.state = Path(binding['state_dir'])
        self.service = ProjectDiagnostics(self.node)

    @staticmethod
    def codes(report):
        return {item['code'] for item in report['findings']}

    def test_healthy_check_is_stable_and_changes_no_filesystem_bytes_or_metadata(self):
        before = filesystem_snapshot(self.node, self.root, self.state)
        objects = Git(self.root).run('count-objects', '-v').stdout
        first = self.service.check(self.project_id)
        second = self.service.check(self.project_id)
        self.assertEqual(first['status'], 'healthy')
        self.assertEqual(first['findings'], [])
        self.assertEqual(first['check_token'], second['check_token'])
        self.assertEqual(filesystem_snapshot(self.node, self.root, self.state), before)
        self.assertEqual(Git(self.root).run('count-objects', '-v').stdout, objects)

    def test_missing_index_is_repairable_but_check_does_not_create_it(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        before = filesystem_snapshot(self.node, self.root, self.state)
        result = self.service.check(self.project_id)
        self.assertEqual(result['status'], 'repairable')
        self.assertEqual(self.codes(result), {'index-missing'})
        self.assertEqual(result['findings'][0]['action'], 'rebuild-index')
        self.assertFalse(index.exists())
        self.assertEqual(filesystem_snapshot(self.node, self.root, self.state), before)

    def test_stale_diverged_legacy_unsupported_and_invalid_indexes_are_distinct(self):
        index = self.state / 'index.sqlite'
        artifact = self.root / 'artifacts' / ENTITY / 'content.md'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(markdown(metadata('Changed', ENTITY)))
        Git(self.root).commit('Change project')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-stale'})
        self.assertEqual(result['status'], 'repairable')

        # Return to a current index, then forge its rows without changing HEAD.
        from spikes.storage import Index
        Index(index).rebuild(Git(self.root))
        with closing(sqlite3.connect(index)) as db, db:
            db.execute("UPDATE entities SET title='Forged'")
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-diverged'})
        self.assertEqual(result['status'], 'manual')

        index.unlink()
        with closing(sqlite3.connect(index)) as db, db:
            db.execute('CREATE TABLE state(singleton INTEGER PRIMARY KEY,commit_id TEXT NOT NULL)')
            db.execute('CREATE TABLE entities(id TEXT PRIMARY KEY,title TEXT NOT NULL)')
        index.chmod(0o600)
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-legacy'})
        self.assertEqual(result['status'], 'repairable')

        with closing(sqlite3.connect(index)) as db, db:
            db.execute('ALTER TABLE entities ADD COLUMN unexpected TEXT')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-invalid'})

        with closing(sqlite3.connect(index)) as db, db:
            db.execute('PRAGMA user_version=77')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-unsupported'})
        self.assertEqual(result['status'], 'manual')

        index.write_bytes(b'not sqlite')
        before = index.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-invalid'})
        self.assertEqual(index.read_bytes(), before)

    def test_journal_intents_are_repairable_and_corruption_is_manual(self):
        journal = self.state / 'journal.sqlite'
        operation = str(uuid4())
        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('INSERT INTO operations VALUES (?,?,0)',
                       (operation, json.dumps({'operation_id': operation})))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-operation-active'})
        self.assertEqual(result['findings'][0]['action'], 'resume-operation')

        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('DELETE FROM operations WHERE done=0')
            db.execute('INSERT INTO pending VALUES (?,?,?)',
                       (f'artifacts/{ENTITY}/content.md', None, b'pending'))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-pending'})
        self.assertEqual(result['status'], 'repairable')

        journal.write_bytes(b'broken journal')
        before = journal.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-invalid'})
        self.assertEqual(result['status'], 'manual')
        self.assertEqual(journal.read_bytes(), before)

    def test_project_configuration_snapshot_and_git_states_have_stable_codes(self):
        config = self.root / 'project.json'
        current = json.loads(config.read_text())
        config.write_bytes(encoded(dict(current, title='Uncommitted')))
        result = self.service.check(self.project_id)
        self.assertIn('project-worktree-mismatch', self.codes(result))
        self.assertIn('git-dirty', self.codes(result))
        self.assertEqual(result['status'], 'manual')

        config.write_bytes(encoded(dict(current, id=str(uuid4()))))
        Git(self.root).commit('Wrong project ID')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'project-id-mismatch'})
        self.assertEqual(result['status'], 'manual')

        config.write_bytes(encoded(current)); Git(self.root).commit('Restore config')
        artifact = self.root / 'artifacts' / ENTITY / 'content.md'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'invalid metadata'); Git(self.root).commit('Invalid snapshot')
        result = self.service.check(self.project_id)
        self.assertIn('project-snapshot-invalid', self.codes(result))

    def test_missing_unsafe_and_busy_layers_fail_closed_without_paths(self):
        moved = self.base / 'moved'
        self.root.rename(moved)
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'root-missing'})
        self.assertEqual(result['findings'][0]['action'], 'repair-location')
        self.assertNotIn(str(self.base), json.dumps(result))
        moved.rename(self.root)

        self.root.chmod(0o777)
        result = self.service.check(self.project_id)
        self.assertIn('root-unsafe', self.codes(result))
        self.root.chmod(0o755)

        lock = self.state / 'writer.lock'
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.service.check(self.project_id)
        self.assertIn('writer-busy', self.codes(result))
        self.assertEqual(result['status'], 'retry')

    def test_registration_and_concurrent_change_fail_closed(self):
        self.node.write_bytes(b'{bad')
        before = self.node.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'registration-invalid'})
        self.assertNotIn('bad', json.dumps(result))
        self.assertEqual(self.node.read_bytes(), before)

        # A changing observation invalidates every partial finding.
        self.node.write_bytes(encoded({'schema_version': 1, 'id': str(uuid4()),
            'name': 'Node', 'projects': []}))
        with patch.object(self.service, '_fingerprint',
                          side_effect=[{'version': 1}, {'version': 2}]):
            result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'state-changed'})
        self.assertEqual(result['status'], 'retry')

    def test_duplicate_registration_and_unsafe_state_entry_are_specific(self):
        node = parse_node(read_config(self.node), location=self.node)
        node['projects'].append(dict(node['projects'][0]))
        self.node.write_bytes(encoded(node))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'registration-duplicate'})

        node['projects'].pop(); self.node.write_bytes(encoded(node))
        unsafe = self.state / 'foreign-directory'; unsafe.mkdir()
        result = self.service.check(self.project_id)
        self.assertIn('state-unsafe', self.codes(result))
        self.assertEqual(result['status'], 'manual')


if __name__ == '__main__':
    unittest.main()
