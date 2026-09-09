from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

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
