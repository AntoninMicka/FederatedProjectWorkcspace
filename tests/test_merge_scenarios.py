"""Controlled local merge scenarios, not a production synchronization service."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from spikes.metadata import validate_snapshot, ValidationError
from spikes.storage import Git, Index, StaleIndex
from tests.fixtures import ENTITY, OTHER, encoded, registry, source


class MergeScenarios(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = Git(self.root / 'local')
        self.local.root.mkdir()
        self.local.run('init', '--initial-branch=main')
        self.files = source()
        self.write(self.local, self.files)
        self.base = self.local.commit('Shared source')
        self.peer = Git(self.root / 'peer')
        self.local.run('clone', '--no-hardlinks', str(self.local.root), str(self.peer.root))
        self.index = Index(self.root / 'index.sqlite')
        self.index.rebuild(self.local)

    def write(self, git, files):
        for name, data in files.items():
            path = git.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def merge(self):
        self.local.run('fetch', str(self.peer.root), 'main')
        return self.local.run('merge', '--no-commit', '--no-ff', 'FETCH_HEAD', check=False)

    def candidate(self):
        tree = self.local.run('write-tree').stdout.strip()
        return self.local.snapshot(tree)

    def assert_parents(self, local, remote):
        self.assertEqual(self.local.run('show', '-s', '--format=%P', 'HEAD').stdout.split(), [local, remote])

    def test_delete_against_edit_abort_and_explicit_keep_resolution(self):
        path = f'artifacts/{ENTITY}/source.pdf'
        changed = b'%PDF-1.7\x00edited\xff\r\n'
        self.write(self.local, {path: changed})
        local = self.local.commit('Edit source')
        self.index.rebuild(self.local)
        for name in self.files:
            (self.peer.root / name).unlink()
        remote = self.peer.commit('Delete entire artifact')
        validate_snapshot(self.peer.snapshot(remote))
        self.assertNotEqual(self.merge().returncode, 0)
        self.assertEqual(self.local.run('show', ':1:' + path, binary=True).stdout, self.files[path])
        self.assertEqual(self.local.run('show', ':2:' + path, binary=True).stdout, changed)
        self.assertNotEqual(self.local.run('show', ':3:' + path, check=False).returncode, 0)
        with self.assertRaisesRegex(ValueError, 'Unresolved merge'):
            self.index.rebuild(self.local)
        self.assertEqual(self.index.read(self.local), [(ENTITY, 'Test')])
        self.local.run('merge', '--abort')
        self.assertEqual(self.local.head(), local)
        self.assertEqual(self.local.run('status', '--porcelain').stdout, '')
        self.assertNotEqual(self.merge().returncode, 0)
        # Human chooses to keep the edited artifact AND its deleted metadata.
        self.write(self.local, dict(self.files, **{path: changed}))
        self.local.run('add', '--', f'artifacts/{ENTITY}')
        validate_snapshot(self.candidate())
        self.local.run('commit', '-m', 'Human keeps complete edited artifact')
        self.assert_parents(local, remote)
        self.index.rebuild(self.local)
        self.assertEqual(self.local.snapshot(self.local.head())[path], changed)

    def test_rename_against_edit_keeps_content_and_sidecar_together(self):
        folder = f'artifacts/{ENTITY}'
        old, new, sidecar = folder + '/source.pdf', folder + '/renamed.pdf', folder + '/metadata.json'
        self.local.run('mv', old, new)
        meta = json.loads(self.files[sidecar])
        meta['file'] = 'renamed.pdf'
        self.write(self.local, {sidecar: encoded(meta)})
        local = self.local.commit('Rename source and sidecar reference')
        changed = self.files[old] + b'peer annotation\n'
        meta = json.loads(self.files[sidecar])
        meta['title'] = 'Peer title'
        self.write(self.peer, {old: changed, sidecar: encoded(meta)})
        remote = self.peer.commit('Edit content and title')
        validate_snapshot(self.local.snapshot(local))
        validate_snapshot(self.peer.snapshot(remote))
        self.assertEqual(self.merge().returncode, 0)
        files = self.candidate()
        self.assertNotIn(old, files)
        self.assertEqual(files[new], changed)
        self.assertEqual(validate_snapshot(files)[ENTITY]['title'], 'Peer title')
        # Text edits alone do not protect the pair: an incorrect human choice is rejected.
        broken = dict(files)
        broken[sidecar] = self.files[sidecar]
        with self.assertRaisesRegex(ValidationError, 'Missing or extra sidecar content'):
            validate_snapshot(broken)
        self.local.run('commit', '-m', 'Accept validated rename and edit')
        self.assert_parents(local, remote)
        self.index.rebuild(self.local)
        self.assertEqual(self.index.read(self.local), [(ENTITY, 'Peer title')])

    def test_text_clean_merge_with_dangling_relation_is_rejected(self):
        for name in self.files:
            (self.local.root / name).unlink()
        local = self.local.commit('Remove source')
        self.index.rebuild(self.local)
        decision = json.loads(registry('New decision', OTHER))
        decision['relations'] = [{'type': 'depends_on', 'target_id': ENTITY}]
        self.write(self.peer, {f'registries/decisions/{OTHER}.json': encoded(decision)})
        remote = self.peer.commit('Reference existing source')
        validate_snapshot(self.local.snapshot(local))
        validate_snapshot(self.peer.snapshot(remote))
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.local.run('ls-files', '-u').stdout, '')
        with self.assertRaisesRegex(ValidationError, 'Dangling relation'):
            validate_snapshot(self.candidate())
        self.assertEqual(self.local.head(), local)
        self.assertEqual(self.index.read(self.local), [])
        self.local.run('merge', '--abort')
        self.assertEqual(self.local.head(), local)
        self.assertEqual(self.local.run('status', '--porcelain').stdout, '')
        # Negative test: deliberately bypass the publication gate, then exercise Index.
        self.assertEqual(self.merge().returncode, 0)
        self.local.run('commit', '-m', 'Deliberately invalid merge for rejection test')
        self.assert_parents(local, remote)
        with self.assertRaisesRegex(ValidationError, 'Dangling relation'):
            self.index.rebuild(self.local)
        with closing(sqlite3.connect(self.index.path)) as db:
            self.assertEqual(db.execute('SELECT commit_id FROM state').fetchone()[0], local)
            self.assertEqual(db.execute('SELECT * FROM entities').fetchall(), [])
        with self.assertRaises(StaleIndex):
            self.index.read(self.local)
        self.write(self.local, self.files)
        repaired = self.local.commit('Human restores referenced source')
        self.index.rebuild(self.local)
        self.assertEqual(len(self.index.read(self.local)), 2)
        validate_snapshot(self.local.snapshot(repaired))
