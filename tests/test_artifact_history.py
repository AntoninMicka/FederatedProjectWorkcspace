"""History must read committed versions without touching drafts, refs or pending work."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.artifact_history import ArtifactHistory
from spikes.artifacts import Artifacts, main_todo_id
from spikes.journal import snapshot
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.storage import Git, StaleIndex
from spikes.workspace import PendingOperation


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'; self.root = self.base / 'project'
        self.id = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))['id']
        self.artifacts = Artifacts(self.node); self.history = ArtifactHistory(self.node)
        self.git = Git(self.root); self.entity = main_todo_id(self.id)
        self.initial = self.git.head()
        self.first = self.save('First', '- [ ] Task\n', new=True)
        self.second = self.save('Second', '- [x] Task\n')

    def save(self, title, body, *, new=False):
        return self.artifacts.save(dict(project_id=self.id, artifact_id=self.entity, base_head=self.git.head(),
                                       title=title, body=body, new=new), str(uuid4()))['commit_id']

    def projection(self):
        ws = self.artifacts.workspace(self.id)
        with closing(sqlite3.connect(ws.journal.database)) as db:
            journal = (db.execute('SELECT * FROM operations ORDER BY id').fetchall(), db.execute('SELECT * FROM pending').fetchall())
        return (self.git.head(), self.git.run('write-tree').stdout, snapshot(self.root), journal,
                ws.index.path.read_bytes(), (self.root / 'project.json').read_bytes())

    def test_versions_metadata_diff_and_dirty_worktree_stay_unchanged(self):
        path = self.root / 'artifacts' / self.entity / 'content.md'
        path.write_text('UNSAVED DRAFT')
        before = self.projection()
        view = self.history.list(self.id, self.entity, self.second)
        self.assertEqual([row['commit_id'] for row in view['versions']], [self.second, self.first])
        self.assertTrue(all(row['available'] for row in view['versions']))
        self.assertTrue(view['versions'][0]['date']); self.assertIn('local.invalid', view['versions'][0]['email'])
        result = self.history.compare(self.id, self.entity, self.second, self.first, self.second)
        self.assertEqual(result['before']['body'], '- [ ] Task\n')
        self.assertEqual(result['after']['metadata']['title'], 'Second')
        self.assertIn('+- [x] Task', result['diff']); self.assertIn('"title": "First"', result['diff'])
        self.assertNotIn('UNSAVED', result['diff'])
        self.assertEqual(self.projection(), before)
        same = self.history.compare(self.id, self.entity, self.second, self.first, self.first)
        self.assertEqual(same['diff'], '')

    def test_unregistered_invalid_foreign_revision_and_stale_head_are_rejected(self):
        for project, entity, head in [(str(uuid4()), self.entity, self.second), (self.id, '../x', self.second),
                                      (self.id, self.entity, 'HEAD')]:
            with self.assertRaises(ValidationError): self.history.list(project, entity, head)
        with self.assertRaises(StaleIndex): self.history.list(self.id, self.entity, self.first)
        tree = self.git.run('rev-parse', self.first + '^{tree}').stdout.strip()
        foreign = self.git.run('commit-tree', tree, input='Unreachable\n').stdout.strip()
        before = self.projection()
        for revision in (foreign, '--all', 'HEAD', tree):
            with self.assertRaises((ValidationError, subprocess.SubprocessError)):
                self.history.compare(self.id, self.entity, self.second, revision, self.second)
        self.assertEqual(self.projection(), before)

    def test_pending_and_busy_are_not_recovered(self):
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):
            self.artifacts.save(dict(project_id=self.id, artifact_id=self.entity, base_head=self.second,
                                     title='Pending', body='Pending', new=False), str(uuid4()), checkpoint=crash)
        before = self.projection()
        with self.assertRaises(PendingOperation): self.history.list(self.id, self.entity, self.second)
        with self.assertRaises(PendingOperation): self.history.compare(self.id, self.entity, self.second, self.first, self.second)
        self.assertEqual(self.projection(), before)
        self.artifacts.open(self.id)
        ws = self.artifacts.workspace(self.id)
        with ws.journal.lock():
            with self.assertRaises(BlockingIOError): self.history.list(self.id, self.entity, self.git.head())
        with self.assertRaises(TimeoutError): ArtifactHistory(self.node, timeout=-1).list(self.id, self.entity, self.git.head())

    def test_rename_invalid_history_and_historical_project_metadata(self):
        meta_path = self.root / 'artifacts' / self.entity / 'metadata.json'
        valid = meta_path.read_bytes()
        meta = json.loads(valid); meta['privacy'] = 'INVALID'; meta_path.write_text(json.dumps(meta))
        invalid = self.git.commit('Invalid historical projection')
        meta_path.write_bytes(valid)
        body_path = meta_path.parent / 'content.md'; body_path.rename(meta_path.parent / 'renamed.md')
        meta = json.loads(valid); meta['file'] = 'renamed.md'; meta_path.write_text(json.dumps(meta))
        config = self.root / 'project.json'; project = json.loads(config.read_bytes()); project['title'] = 'Renamed project'
        config.write_text(json.dumps(project)); latest = self.git.commit('Rename document and project')
        rows = self.history.list(self.id, self.entity, latest)['versions']
        self.assertFalse(next(row for row in rows if row['commit_id'] == invalid)['available'])
        with self.assertRaises(ValidationError): self.history.compare(self.id, self.entity, latest, invalid, latest)
        result = self.history.compare(self.id, self.entity, latest, self.first, latest)
        self.assertEqual(result['after']['metadata']['file'], 'renamed.md')
        self.assertIn('renamed.md', result['diff']); self.assertNotIn('project.json', result['diff'])

    def test_full_history_retains_both_merge_branches_and_filters_other_paths(self):
        self.git.run('checkout', '-b', 'side', self.first)
        side = self.save('Side', '- [ ] Side\n')
        self.git.run('checkout', 'main')
        self.git.run('merge', '--no-commit', '--no-ff', 'side', check=False)
        folder = self.root / 'artifacts' / self.entity
        (folder / 'content.md').write_text('- [x] Merged\n')
        meta = json.loads(self.git.run('show', self.second + ':artifacts/' + self.entity + '/metadata.json').stdout)
        (folder / 'metadata.json').write_text(json.dumps(meta))
        merged = self.git.commit('Resolve both branches')
        (self.root / 'README.txt').write_text('unrelated'); latest = self.git.commit('Unrelated')
        view = self.history.list(self.id, self.entity, latest)
        ids = {row['commit_id'] for row in view['versions']}
        self.assertTrue({side, self.first, self.second, merged} <= ids)
        self.assertNotIn(latest, ids)
        result = self.history.compare(self.id, self.entity, latest, side, self.second)
        self.assertIn('Side', result['before']['body'])
        with patch('spikes.artifact_history.MAX_VERSIONS', 2):
            limited = self.history.list(self.id, self.entity, latest)
            self.assertEqual(len(limited['versions']), 2); self.assertTrue(limited['truncated'])

    def test_deletion_recreation_and_diff_drivers_do_not_hide_or_execute_content(self):
        folder = self.root / 'artifacts' / self.entity
        files = {p.name: p.read_bytes() for p in folder.iterdir()}
        for path in folder.iterdir(): path.unlink()
        deleted = self.git.commit('Delete document')
        for name, data in files.items(): (folder / name).write_bytes(data)
        recreated = self.git.commit('Recreate same identity')
        (self.root / '.gitattributes').write_text('*.md -diff\n')
        latest = self.git.commit('Binary diff attribute')
        sentinel = self.base / 'external-called'
        driver = self.base / 'driver'
        import shlex
        driver.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(sentinel)) + '\nexit 1\n')
        driver.chmod(0o700)
        self.git.run('config', 'diff.external', str(driver))
        rows = self.history.list(self.id, self.entity, latest)['versions']
        self.assertTrue(next(row for row in rows if row['commit_id'] == deleted)['deleted'])
        removed = self.history.compare(self.id, self.entity, latest, self.second, deleted)
        self.assertIsNone(removed['after']); self.assertIn('-- [x] Task', removed['diff'])
        restored = self.history.compare(self.id, self.entity, latest, deleted, recreated)
        self.assertEqual(restored['after']['body'], '- [x] Task\n')
        self.assertIn('+- [x] Task', restored['diff'])
        self.assertFalse(sentinel.exists())

    def test_head_changed_during_read_is_not_returned(self):
        ws = self.artifacts.workspace(self.id)
        real_head = ws.git.head
        calls = []
        def head():
            calls.append(True)
            return real_head() if len(calls) == 1 else self.first
        with patch.object(self.history.artifacts, 'workspace', return_value=ws), patch.object(ws.git, 'head', side_effect=head):
            with self.assertRaises(StaleIndex): self.history.list(self.id, self.entity, self.second)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires native Qt history dialog')
    def test_native_history_preserves_draft_and_displays_readonly_versions(self):
        script = '''
import sys,time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from spikes.artifacts import Artifacts
from spikes.desktop_editor import EditorDialog
from spikes.desktop_history import HistoryDialog
app=QApplication([])
def idle(dialog):
    end=time.monotonic()+15
    while dialog.busy and time.monotonic()<end:
        app.processEvents();time.sleep(.01)
    assert not dialog.busy, dialog.status.text()
editor=EditorDialog(Artifacts(sys.argv[1]),sys.argv[2],todo=True)
editor.show();idle(editor)
editor.body.setPlainText('LOCAL DRAFT <img src=x>')
checked=[]
def history_test():
    dialog=app.activeModalWidget()
    if not isinstance(dialog,HistoryDialog) or dialog.busy:
        QTimer.singleShot(20,history_test);return
    try:
        assert dialog.newer.count()==2
        dialog.compare_button.click();idle(dialog)
        assert '- [x] Task' in dialog.body.toPlainText(),dialog.status.text()
        assert 'metadata.json' in dialog.diff.toPlainText()
        assert 'Second' in dialog.metadata.toPlainText()
        assert all(w.isReadOnly() for w in (dialog.body,dialog.metadata,dialog.diff,dialog.info))
        dialog.newer.setCurrentIndex(1)
        assert not dialog.body.toPlainText()
        dialog.compare_button.click();idle(dialog)
        assert '- [ ] Task' in dialog.body.toPlainText()
        def fail(*args): raise RuntimeError('Changed HEAD')
        dialog.service.compare=fail
        dialog.compare_button.click();idle(dialog)
        assert not dialog.body.toPlainText() and not dialog.diff.toPlainText()
        assert 'Changed HEAD' in dialog.status.text()
        checked.append(True)
    finally: dialog.reject()
QTimer.singleShot(20,history_test)
editor.history_button.click()
assert checked and editor.dirty and editor.body.toPlainText()=='LOCAL DRAFT <img src=x>'
editor.dirty=False;editor.close()
print('history verified')
'''
        before = self.projection()
        result = subprocess.run([sys.executable, '-c', script, str(self.node), self.id],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('history verified', result.stdout)
        self.assertEqual(self.projection(), before)
