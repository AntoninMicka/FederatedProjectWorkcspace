# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from spikes.storage import Git, Index, StaleIndex
from tests.fixtures import ENTITY, registry, markdown


class StorageSpike(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.desktop = self.root / 'desktop'
        self.desktop.mkdir()
        self.git = Git(self.desktop)
        self.git.run('init', '--initial-branch=main')
        self.write(self.git, 'Shared base')
        self.base = self.git.commit('Initial entity')
        self.db = Index(self.root / 'index.sqlite')
        self.db.rebuild(self.git)

    def write(self, git, title, name=ENTITY, entity_id=ENTITY):
        folder = git.root / 'registries' / 'decisions'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{name}.json').write_bytes(registry(title, entity_id))

    def test_snapshot_batches_binary_files_and_preserves_fixed_commit(self):
        expected = self.git.snapshot(self.base)
        additions = {'artifacts/raw/empty': b'', 'artifacts/raw/žluťoučký\tname\n.bin': b'\x00\xff\nblob 20\n',
                     'artifacts/raw/copy.bin': b'\x00\xff\nblob 20\n', 'artifacts/raw/executable': b'#!/bin/sh\n'}
        for name, raw in additions.items():
            target = self.desktop / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (self.desktop / 'artifacts/raw/executable').chmod(0o755)
        commit = self.git.commit('Binary files')
        (self.desktop / 'artifacts/raw/empty').write_bytes(b'uncommitted')
        with patch.object(self.git, 'run', wraps=self.git.run) as run:
            result = self.git.snapshot(commit, env_extra={'GIT_NO_REPLACE_OBJECTS': '1'})
        self.assertEqual(expected | additions, result)
        self.assertEqual(2, run.call_count, 'snapshot must not spawn one Git process per file')
        self.assertTrue(all(call.kwargs['env_extra'] == {'GIT_NO_REPLACE_OBJECTS': '1'}
                            for call in run.call_args_list))
        self.assertEqual(expected, self.git.snapshot(self.base))
        empty = self.git.run('mktree', input='').stdout.strip()
        self.assertEqual({}, self.git.snapshot(empty))

    def test_snapshot_rejects_limits_before_reading_blob_content(self):
        for name, limit in [('MAX_FILE', 1), ('MAX_SNAPSHOT', 1)]:
            with self.subTest(limit=name), patch('spikes.storage.' + name, limit), \
                    patch.object(self.git, 'run', wraps=self.git.run) as run:
                with self.assertRaisesRegex(ValueError, 'Snapshot exceeds limits'):
                    self.git.snapshot(self.base)
                self.assertEqual(1, run.call_count)
        entry = '100644 blob ' + 'a' * 40 + ' 0\tregistries/decisions/x.json\0'
        with patch.object(self.git, 'run') as run:
            run.return_value.stdout = entry * 10001
            with self.assertRaisesRegex(ValueError, 'Snapshot exceeds limits'):
                self.git.snapshot(self.base)
            self.assertEqual(1, run.call_count)

    def test_snapshot_rejects_symlinks_before_reading_content(self):
        target = self.desktop / 'artifacts/raw/link'
        target.parent.mkdir(parents=True)
        target.symlink_to('/etc/passwd')
        commit = self.git.commit('Unsupported symlink')
        with patch.object(self.git, 'run', wraps=self.git.run) as run:
            with self.assertRaisesRegex(ValueError, 'Non-regular Git entry'):
                self.git.snapshot(commit)
            self.assertEqual(1, run.call_count)

    def test_snapshot_rejects_malformed_or_truncated_batch(self):
        original = self.git.run
        for corrupt in [lambda raw: raw.replace(b' blob ', b' tree ', 1),
                        lambda raw: b'0' + raw[1:], lambda raw: raw[:-1],
                        lambda raw: raw + b'extra', lambda raw: b'missing\n']:
            def changed(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[:2] == ('cat-file', '--batch'):
                    result.stdout = corrupt(result.stdout)
                return result
            with self.subTest(corrupt=corrupt), patch.object(self.git, 'run', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'Git batch'):
                    self.git.snapshot(self.base)

    def test_divergence_abort_and_resolution_preserve_history(self):
        peer = Git(self.root / 'server')
        self.git.run('clone', '--no-hardlinks', str(self.desktop), str(peer.root))
        self.write(self.git, 'Desktop edit')
        local = self.git.commit('Desktop offline')
        self.db.rebuild(self.git)
        self.write(peer, 'Server edit')
        remote = peer.commit('Server offline')
        self.git.run('fetch', str(peer.root), 'main')
        result = self.git.run('merge', '--no-edit', 'FETCH_HEAD', check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.git.head(), local)
        path = f'registries/decisions/{ENTITY}.json'
        for stage, title in [(1, 'Shared base'), (2, 'Desktop edit'), (3, 'Server edit')]:
            self.assertEqual(json.loads(self.git.run('show', f':{stage}:{path}').stdout)['title'], title)
        with self.assertRaises(ValueError):
            self.db.rebuild(self.git)
        self.assertEqual(self.db.read(self.git), [(ENTITY, 'Desktop edit')])
        self.git.run('merge', '--abort')
        self.assertEqual(self.git.head(), local)
        self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
        self.git.run('merge', '--no-edit', remote, check=False)
        self.write(self.git, 'Human resolution')
        self.git.commit('Resolve both edits')
        parents = self.git.run('show', '-s', '--format=%P', 'HEAD').stdout.split()
        self.assertEqual(parents, [local, remote])
        self.db.rebuild(self.git)
        self.assertEqual(self.db.read(self.git), [(ENTITY, 'Human resolution')])

    def test_recovery_after_commit_before_index_update(self):
        self.write(self.git, 'Committed before crash')
        self.git.commit('New state')
        reopened = Index(self.db.path)
        with self.assertRaises(StaleIndex):
            reopened.read(self.git)
        reopened.rebuild(self.git)
        self.assertEqual(reopened.read(self.git), [(ENTITY, 'Committed before crash')])
        self.db.path.unlink()
        rebuilt = Index(self.db.path)
        rebuilt.rebuild(self.git)
        self.assertEqual(rebuilt.read(self.git), reopened.read(self.git))

    def test_invalid_merge_projection_does_not_replace_previous_index(self):
        artifact = self.git.root / 'artifacts' / ENTITY
        artifact.mkdir(parents=True)
        (artifact / 'duplicate.md').write_bytes(markdown())
        self.git.commit('Semantically invalid state')
        with self.assertRaisesRegex(ValueError, 'Duplicate ID'):
            self.db.rebuild(self.git)
        with closing(sqlite3.connect(self.db.path)) as db, db:
            self.assertEqual(db.execute('SELECT commit_id FROM state').fetchone()[0], self.base)
            self.assertEqual(db.execute('SELECT title FROM entities').fetchall(), [('Shared base',)])
        with self.assertRaises(StaleIndex):
            self.db.read(self.git)

    def test_projection_reads_commit_not_uncommitted_edits(self):
        self.write(self.git, 'Unsaved draft')
        self.db.rebuild(self.git)
        self.assertEqual(self.db.read(self.git), [(ENTITY, 'Shared base')])


if __name__ == '__main__':
    unittest.main()
