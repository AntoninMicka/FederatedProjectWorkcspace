from contextlib import closing
import json
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from spikes.journal import RecoveryConflict, snapshot
from spikes.metadata import ValidationError
from spikes.storage import Git
from spikes.workspace import PendingOperation, Workspace
from tests.fixtures import ENTITY, OTHER, source, registry


IDENTITY = dict(author_name='Alice Example', author_email='alice@example.invalid', message='Import source')


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.state = self.base / 'state'
        self.git = Git(self.root)
        self.git.run('init', '--initial-branch=main')
        self.git.run('commit', '--allow-empty', '-m', 'Initial project')
        self.initial = self.git.head()
        self.workspace = Workspace(self.root, self.state)

    def active(self):
        with closing(sqlite3.connect(self.workspace.journal.database)) as db, db:
            row = db.execute('SELECT record FROM operations WHERE done=0').fetchone()
            return json.loads(row[0]) if row else None

    def crash(self, stage, *, recovery=False, changes=None):
        script = '''
import json, os, sys
from spikes.workspace import Workspace
from tests.fixtures import source
workspace = Workspace(sys.argv[1], sys.argv[2])
def checkpoint(stage):
    if stage == sys.argv[3]:
        os._exit(73)
if sys.argv[4] == 'recover':
    workspace.recover(checkpoint)
else:
    changes = source() if sys.argv[5] == 'null' else {
        path: None if value is None else bytes.fromhex(value)
        for path, value in json.loads(sys.argv[5]).items()}
    workspace.apply(changes, author_name='Alice Example', author_email='alice@example.invalid',
                    message='Import source', checkpoint=checkpoint)
'''
        payload = None if changes is None else {p: None if v is None else v.hex() for p, v in changes.items()}
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.state), stage,
                                 'recover' if recovery else 'apply', json.dumps(payload)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 73, result.stderr)

    def test_process_crashes_at_every_persistent_boundary(self):
        stages = ['prepared', 'file:0', 'file:1', 'applied', 'files-applied', 'commit-created',
                  'commit-ready', 'ref-updated', 'committed', 'git-indexed', 'indexed', 'completed']
        for stage in stages:
            with self.subTest(stage=stage):
                self.crash(stage)
                pending = self.active()
                candidate = pending['commit_id'] if pending else self.git.head()
                if pending:
                    with self.assertRaises(PendingOperation):
                        self.workspace.read()
                    with self.assertRaises(PendingOperation):
                        self.workspace.apply(source(), **IDENTITY)
                    with self.assertRaises(ValidationError):
                        self.workspace.journal.recover()
                reopened = Workspace(self.root, self.state)
                receipt = reopened.recover()
                commit = self.git.head()
                if candidate:
                    self.assertEqual(commit, candidate)
                if receipt:
                    self.assertEqual(reopened.receipt(receipt['operation_id']), receipt)
                self.assertIsNone(reopened.recover())
                self.assertEqual(self.git.head(), commit)
                self.assertEqual(self.git.run('rev-list', '--count', 'HEAD').stdout.strip(), '2')
                self.assertEqual(self.git.run('show', '-s', '--format=%an <%ae>|%cn <%ce>', 'HEAD').stdout.strip(),
                                 'Alice Example <alice@example.invalid>|Alice Example <alice@example.invalid>')
                self.assertEqual(self.git.snapshot(commit), source())
                self.assertEqual(snapshot(self.root), source())
                self.assertEqual(reopened.read(), [(ENTITY, 'Test')])
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
                self.git.run('reset', '--hard', self.initial)

    def test_recovery_itself_can_crash_repeatedly(self):
        self.crash('prepared')
        operation_id = self.active()['operation_id']
        for stage in ('file:0', 'files-applied', 'commit-ready', 'ref-updated', 'indexed'):
            self.crash(stage, recovery=True)
            self.assertEqual(self.active()['operation_id'], operation_id)
        receipt = self.workspace.recover()
        self.assertEqual(receipt['operation_id'], operation_id)
        self.assertEqual(self.git.run('rev-list', '--count', 'HEAD').stdout.strip(), '2')
        self.assertIsNone(self.workspace.recover())

    def test_import_rename_delete_keep_exact_bytes_and_paths(self):
        (self.root / 'unrelated.txt').write_text('Keep me')
        self.git.commit('Unrelated baseline')
        original = self.git.head()
        first = self.workspace.apply(source(), **IDENTITY)
        self.assertEqual(self.git.run('show', '-s', '--format=%P', first['commit_id']).stdout.strip(), original)
        self.assertEqual(set(self.git.run('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').stdout.splitlines()),
                         set(source()))
        changes = source(name='renamed.pdf')
        changes[f'artifacts/{ENTITY}/source.pdf'] = None
        self.crash('file:0', changes=changes)
        self.workspace.recover()
        self.assertEqual(self.git.snapshot(self.git.head()), source(name='renamed.pdf'))
        self.crash('ref-updated', changes={p: None for p in source(name='renamed.pdf')})
        self.workspace.recover()
        self.assertEqual(self.workspace.read(), [])
        self.assertEqual((self.root / 'unrelated.txt').read_text(), 'Keep me')

    def test_dirty_staged_untracked_and_ignored_inputs_are_refused(self):
        path = self.root / 'foreign.txt'
        path.write_text('base')
        self.git.commit('Foreign base')
        base = self.git.head()
        for staged in (False, True):
            path.write_text('user edit')
            if staged:
                self.git.run('add', '--', 'foreign.txt')
            with self.assertRaises(ValidationError):
                self.workspace.apply(source(), **IDENTITY)
            self.assertIsNone(self.active())
            self.assertEqual(path.read_text(), 'user edit')
            self.assertEqual(self.git.head(), base)
            self.git.run('reset', '--hard', base)
        path = self.root / 'untracked.txt'
        path.write_text('user work')
        with self.assertRaises(ValidationError):
            self.workspace.apply(source(), **IDENTITY)
        path.unlink()
        (self.root / '.gitignore').write_text('artifacts/\n')
        self.git.commit('Ignore artifacts')
        for relative, data in source().items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with self.assertRaises(ValidationError):
            self.workspace.apply(source(), **IDENTITY)

    def test_invalid_noop_and_missing_identity_leave_no_pending_record(self):
        for changes, identity in [({f'artifacts/{ENTITY}/source.pdf': b'bad'}, IDENTITY),
                                  ({}, IDENTITY), (source(), dict(IDENTITY, author_name=''))]:
            with self.assertRaises(ValidationError):
                self.workspace.apply(changes, **identity)
            self.assertIsNone(self.active())
            self.assertEqual(snapshot(self.root), {})
            self.assertEqual(self.git.head(), self.initial)
        self.workspace.apply(source(), **IDENTITY)

    def test_head_branch_and_foreign_staging_changes_stop_recovery(self):
        self.crash('prepared')
        self.git.run('commit', '--allow-empty', '-m', 'External change')
        external = self.git.head()
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()
        self.assertEqual(self.git.head(), external)
        self.assertEqual(snapshot(self.root), {})
        self.git.run('reset', '--hard', self.initial)
        self.git.run('switch', '-c', 'other')
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()
        self.git.run('switch', 'main')
        (self.root / 'foreign.txt').write_text('user edit')
        self.git.run('add', '--', 'foreign.txt')
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()
        self.assertEqual(self.git.run('show', ':foreign.txt').stdout, 'user edit')
        self.assertIsNotNone(self.active())

    def test_intervening_edits_before_and_after_commit_are_preserved(self):
        for stage in ('file:0', 'commit-ready', 'ref-updated'):
            with self.subTest(stage=stage):
                # Isolate each conflict without trying to auto-resolve the previous one.
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory) / 'project'
                    root.mkdir()
                    git = Git(root)
                    git.run('init', '--initial-branch=main')
                    git.run('commit', '--allow-empty', '-m', 'Initial')
                    workspace = Workspace(root, Path(directory) / 'state')
                    def stop(current):
                        if current == stage:
                            raise RuntimeError('Simulated interruption')
                    with self.assertRaises(RuntimeError):
                        workspace.apply(source(), **IDENTITY, checkpoint=stop)
                    path = root / f'artifacts/{ENTITY}/metadata.json'
                    path.write_bytes(b'user edit')
                    head = git.head()
                    with self.assertRaises(RecoveryConflict):
                        workspace.recover()
                    self.assertEqual(path.read_bytes(), b'user edit')
                    self.assertEqual(git.head(), head)

    def test_compare_and_swap_does_not_overwrite_changed_head(self):
        external = []
        def change_head(stage):
            if stage == 'before-ref':
                external.append(self.git.run('commit-tree', self.git.run('rev-parse', 'HEAD^{tree}').stdout.strip(),
                                             '-p', self.initial, '-m', 'External').stdout.strip())
                self.git.run('update-ref', 'refs/heads/main', external[0], self.initial)
        with self.assertRaises(subprocess.CalledProcessError):
            self.workspace.apply(source(), **IDENTITY, checkpoint=change_head)
        self.assertEqual(self.git.head(), external[0])
        self.assertEqual(self.active()['state'], 'commit-ready')
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()

    def test_index_failure_keeps_pending_and_recovers_without_duplicate_commit(self):
        with patch.object(self.workspace.index, 'rebuild', side_effect=RuntimeError('Index unavailable')):
            with self.assertRaises(RuntimeError):
                self.workspace.apply(source(), **IDENTITY)
        commit = self.git.head()
        with self.assertRaises(PendingOperation):
            self.workspace.read()
        self.workspace.recover()
        self.assertEqual(self.git.head(), commit)
        self.workspace.index.path.unlink()
        reopened = Workspace(self.root, self.state)
        self.assertEqual(reopened.read(), [(ENTITY, 'Test')])

    def test_foreign_staging_after_ref_update_is_not_overwritten(self):
        self.crash('ref-updated')
        (self.root / 'foreign.txt').write_text('staged edit')
        self.git.run('add', '--', 'foreign.txt')
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()
        self.assertEqual(self.git.run('show', ':foreign.txt').stdout, 'staged edit')
        self.assertIsNotNone(self.active())

    def test_failure_before_intent_commit_rolls_back_both_records(self):
        prepare = self.workspace.journal._prepare
        def fail_after_prepare(db, changes):
            prepare(db, changes)
            raise RuntimeError('Before intent commit')
        with patch.object(self.workspace.journal, '_prepare', side_effect=fail_after_prepare):
            with self.assertRaises(RuntimeError):
                self.workspace.apply(source(), **IDENTITY)
        self.assertIsNone(self.active())
        with closing(sqlite3.connect(self.workspace.journal.database)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pending').fetchone()[0], 0)
        self.assertEqual(snapshot(self.root), {})
        self.assertEqual(self.git.head(), self.initial)
        self.workspace.apply(source(), **IDENTITY)

    def test_rollback_of_published_head_requires_manual_resolution(self):
        self.crash('committed')
        self.git.run('update-ref', 'refs/heads/main', self.initial)
        with self.assertRaises(RecoveryConflict):
            self.workspace.recover()
        self.assertEqual(self.git.head(), self.initial)
        self.assertIsNotNone(self.active())

    def test_two_writers_share_lock_and_second_observes_first_commit(self):
        script = '''
import sys
from spikes.workspace import Workspace
from tests.fixtures import OTHER, registry, source
print('starting', flush=True)
w = Workspace(sys.argv[1], sys.argv[2])
def checkpoint(stage):
    if stage == 'prepared' and sys.argv[3] == 'first':
        print('locked', flush=True)
        sys.stdin.readline()
changes = source() if sys.argv[3] == 'first' else {f'registries/decisions/{OTHER}.json': registry('Second', OTHER)}
r = w.apply(changes, author_name='Writer', author_email='writer@example.invalid', message='Write', checkpoint=checkpoint)
print(r['commit_id'], flush=True)
'''
        first = subprocess.Popen([sys.executable, '-c', script, str(self.root), str(self.state), 'first'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = None
        try:
            self.assertEqual(first.stdout.readline().strip(), 'starting')
            self.assertEqual(first.stdout.readline().strip(), 'locked')
            second = subprocess.Popen([sys.executable, '-c', script, str(self.root), str(self.state), 'second'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(second.stdout.readline().strip(), 'starting')
            self.assertEqual(select.select([second.stdout], [], [], 0.15)[0], [])
            out1, err1 = first.communicate('\n', timeout=15)
            out2, err2 = second.communicate(timeout=15)
            self.assertEqual(first.returncode, 0, err1)
            self.assertEqual(second.returncode, 0, err2)
            self.assertEqual(self.git.run('show', '-s', '--format=%P', out2.strip()).stdout.strip(), out1.strip())
            self.assertEqual(self.workspace.read(), [(ENTITY, 'Test'), (OTHER, 'Second')])
        finally:
            for process in (first, second):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)
