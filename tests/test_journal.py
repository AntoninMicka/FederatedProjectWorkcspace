import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from spikes.journal import Journal, RecoveryConflict, snapshot
from spikes.metadata import ValidationError, validate_snapshot
from spikes.storage import Git, Index
from tests.fixtures import ENTITY, OTHER, encoded, source, metadata, markdown


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.state = self.base / 'state'
        self.journal = Journal(self.root, self.state)

    def crash(self, stage, operation='import'):
        script = '''
import os, sys
from spikes.journal import Journal
from tests.fixtures import ENTITY, source
journal = Journal(sys.argv[1], sys.argv[2])
changes = source()
if sys.argv[4] == 'rename':
    changes = source(name='renamed.pdf')
    changes[f'artifacts/{ENTITY}/source.pdf'] = None
elif sys.argv[4] == 'delete':
    changes = {path: None for path in source()}
def checkpoint(stage):
    if stage == sys.argv[3]:
        os._exit(73)
journal.apply(changes, checkpoint)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.state), stage, operation],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 73, result.stderr)

    def test_process_exit_at_each_import_boundary(self):
        for stage in ['prepared', 'file:0', 'file:1', 'applied', 'completed']:
            with self.subTest(stage=stage):
                self.crash(stage)
                reopened = Journal(self.root, self.state)
                reopened.recover()
                self.assertEqual(snapshot(self.root), source())
                self.assertFalse(reopened.recover())
                reopened.apply({path: None for path in source()})

    def test_rename_and_delete_recovery(self):
        self.journal.apply(source())
        self.crash('file:0', 'rename')
        self.journal.recover()
        self.assertEqual(snapshot(self.root), source(name='renamed.pdf'))
        self.journal.apply({path: None for path in source(name='renamed.pdf')})
        self.journal.apply(source())
        self.crash('file:0', 'delete')
        self.journal.recover()
        self.assertEqual(snapshot(self.root), {})

    def test_intervening_edit_is_not_overwritten(self):
        self.crash('file:0')
        sidecar = self.root / f'artifacts/{ENTITY}/metadata.json'
        edited = encoded(metadata(file='source.pdf', description='User edit'))
        sidecar.write_bytes(edited)
        with self.assertRaises(RecoveryConflict):
            self.journal.recover()
        self.assertEqual(sidecar.read_bytes(), edited)
        self.assertFalse((sidecar.parent / 'source.pdf').exists())
        with self.assertRaises(ValidationError):
            self.journal.apply(source())

    def test_invalid_pair_does_not_write_and_symlink_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.journal.apply({f'artifacts/{ENTITY}/source.pdf': b'%PDF'})
        self.assertEqual(snapshot(self.root), {})
        outside = self.base / 'outside'
        outside.mkdir()
        (self.root / 'artifacts').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValidationError):
            self.journal.apply(source())
        self.assertEqual(list(outside.iterdir()), [])

    def test_commit_and_index_after_recovery(self):
        git = Git(self.root)
        git.run('init', '--initial-branch=main')
        self.crash('file:0')
        self.journal.recover()
        validate_snapshot(snapshot(self.root))
        git.commit('Recovered import')
        db = Index(self.base / 'index.sqlite')
        db.rebuild(git)
        self.assertEqual(db.read(git), [(ENTITY, 'Test')])
        self.assertEqual(git.run('show', f'HEAD:artifacts/{ENTITY}/source.pdf', binary=True).stdout,
                         source()[f'artifacts/{ENTITY}/source.pdf'])

    def test_referenced_artifact_cannot_be_deleted_alone(self):
        files = source()
        files[f'artifacts/{OTHER}/document.md'] = markdown(metadata(
            entity_id=OTHER, relations=[{'type': 'cites', 'target_id': ENTITY}]))
        self.journal.apply(files)
        with self.assertRaises(ValidationError):
            self.journal.apply({path: None for path in source()})
        self.assertEqual(snapshot(self.root), files)

    def test_recovery_can_itself_be_interrupted(self):
        self.crash('prepared')
        script = """
import os, sys
from spikes.journal import Journal
def checkpoint(stage):
    if stage == 'file:0':
        os._exit(74)
Journal(sys.argv[1], sys.argv[2]).recover(checkpoint)
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.state)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 74, result.stderr)
        self.journal.recover()
        self.assertEqual(snapshot(self.root), source())

    def test_state_must_be_outside_project_and_bound_to_root(self):
        with self.assertRaises(ValidationError):
            Journal(self.root, self.root / 'state')
        other = self.base / 'other'
        other.mkdir()
        with self.assertRaises(ValidationError):
            Journal(other, self.state)
