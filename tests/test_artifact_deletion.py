# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Deletion acceptance over real Git, durable journal, index and native Qt."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts, main_todo_id
from spikes.journal import RecoveryConflict
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.storage import Git
from tests.fixtures import encoded, markdown, metadata


class ArtifactDeletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.node = Path(temp.name) / 'node.json'
        self.root = Path(temp.name) / 'project'
        self.id = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))['id']
        self.service = Artifacts(self.node)
        self.git = Git(self.root)

    def create(self, *, frontmatter=False, id_=None):
        id_ = id_ or str(uuid4())
        if frontmatter:
            path = self.root / 'artifacts' / id_ / 'note.md'
            path.parent.mkdir(parents=True)
            path.write_bytes(markdown(metadata('Frontmatter', id_)))
            self.git.commit('Add frontmatter document')
        else:
            self.service.save(dict(project_id=self.id, artifact_id=id_, base_head=self.git.head(),
                                   title='<b>Document</b>', body='Original\n', new=True), str(uuid4()))
        return id_

    def request(self, id_):
        return dict(project_id=self.id, artifact_id=id_, base_head=self.git.head())

    def test_sidecar_frontmatter_history_projection_and_receipt(self):
        for frontmatter in (False, True):
            with self.subTest(frontmatter=frontmatter):
                id_ = self.create(frontmatter=frontmatter)
                other = self.create()
                request, operation = self.request(id_), str(uuid4())
                before = self.git.snapshot(request['base_head'])
                owned = {p: v for p, v in before.items() if p.startswith(f'artifacts/{id_}/')}
                receipt = self.service.delete(request, operation)
                after = self.git.snapshot(self.git.head())
                self.assertEqual(after, {p: v for p, v in before.items() if p not in owned})
                self.assertNotIn(id_, validate_snapshot(after))
                self.assertIn(other, validate_snapshot(after))
                self.assertEqual(self.git.snapshot(request['base_head']), before)
                self.assertEqual(self.git.run('rev-list', '--count', request['base_head'] + '..HEAD').stdout.strip(), '1')
                ws = self.service.workspace(self.id)
                ws.index.path.unlink()
                view = self.service.open(self.id)
                self.assertNotIn(id_, {d['id'] for d in view['documents']})
                self.assertNotIn(id_, ws.read_projection()['entities'])
                self.create()
                later = self.git.head()
                self.assertEqual(self.service.delete(request, operation), receipt)
                self.assertEqual(self.git.head(), later)
                with self.assertRaises(ValidationError):
                    self.service.delete(dict(request, artifact_id=other), operation)
                self.assertIsNone(ws.recover())
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    def test_incoming_artifact_and_registry_relations_block_before_preparation(self):
        id_, other = self.create(), self.create()
        sidecar = self.root / 'artifacts' / other / 'metadata.json'
        original = sidecar.read_bytes()
        meta = json.loads(original)
        meta['relations'] = [dict(type='references', target_id=id_)]
        sidecar.write_bytes(encoded(meta)); self.git.commit('Incoming artifact relation')
        with self.assertRaises(ValidationError): self.service.delete(self.request(id_), str(uuid4()))
        self.assertIsNone(self.service.workspace(self.id).recover())
        sidecar.write_bytes(original)
        registry_id = str(uuid4())
        path = self.root / 'registries' / 'decisions' / (registry_id + '.json')
        path.parent.mkdir(parents=True)
        path.write_bytes(encoded(dict(metadata('Decision', registry_id), kind='decisions',
                                      status='proposed', body='Decision',
                                      relations=[dict(type='depends_on', target_id=id_)])))
        self.git.commit('Incoming registry relation')
        with self.assertRaises(ValidationError): self.service.delete(self.request(id_), str(uuid4()))
        self.assertIsNone(self.service.workspace(self.id).recover())
        self.assertTrue((self.root / 'artifacts' / id_ / 'content.md').exists())

    def test_self_and_outgoing_relations_disappear_and_main_todo_can_be_recreated(self):
        id_, other = self.create(id_=main_todo_id(self.id)), self.create()
        path = self.root / 'artifacts' / id_ / 'metadata.json'
        meta = json.loads(path.read_bytes())
        meta['relations'] = [dict(type='references', target_id=id_), dict(type='references', target_id=other)]
        path.write_bytes(encoded(meta)); self.git.commit('Self and outgoing relations')
        self.service.delete(self.request(id_), str(uuid4()))
        self.assertEqual(self.service.workspace(self.id).read_projection()['relations'], [])
        self.assertIsNone(self.service.projects.open(self.id)['main_todo'])
        self.create(id_=id_)
        self.assertEqual(self.service.open(self.id)['main_todo_id'], id_)

    def test_stale_dirty_staged_busy_and_invalid_requests_leave_no_operation(self):
        id_ = self.create(); request = self.request(id_)
        with self.service.workspace(self.id).journal.lock():
            with self.assertRaises(BlockingIOError): self.service.delete(request, str(uuid4()))
        for invalid in (dict(request, extra=True), dict(request, artifact_id=str(uuid4())),
                        dict(request, base_head='invalid'), dict(request, project_id=str(uuid4()))):
            with self.assertRaises((ValidationError, ValueError)):
                self.service.delete(invalid, str(uuid4()))
        path = self.root / 'artifacts' / id_ / 'content.md'
        for staged in (False, True):
            path.write_text('Foreign edit')
            if staged: self.git.run('add', '--', str(path.relative_to(self.root)))
            with self.assertRaises(ValidationError): self.service.delete(request, str(uuid4()))
            self.assertEqual(path.read_text(), 'Foreign edit')
            self.assertIsNone(self.service.workspace(self.id).recover())
            self.git.run('reset', '--', str(path.relative_to(self.root)))
            path.write_text('Original\n')
        self.create()
        with self.assertRaises(ValidationError): self.service.delete(request, str(uuid4()))
        self.assertIsNone(self.service.workspace(self.id).recover())

    def test_source_is_rejected_and_save_operation_id_cannot_be_reused(self):
        id_ = str(uuid4()); operation = str(uuid4())
        save = dict(project_id=self.id, artifact_id=id_, base_head=self.git.head(),
                    title='Document', body='Original\n', new=True)
        self.service.save(save, operation)
        with self.assertRaises(ValidationError): self.service.delete(self.request(id_), operation)
        path = self.root / 'artifacts' / id_ / 'metadata.json'
        meta = json.loads(path.read_bytes()); meta.update(kind='source', provenance='external')
        path.write_bytes(encoded(meta)); self.git.commit('Source document')
        with self.assertRaises(ValidationError): self.service.delete(self.request(id_), str(uuid4()))
        self.assertIsNone(self.service.workspace(self.id).recover())

    def test_invalid_committed_snapshot_is_rejected_before_preparation(self):
        id_, other = self.create(), self.create()
        path = self.root / 'artifacts' / other / 'metadata.json'
        meta = json.loads(path.read_bytes())
        meta['relations'] = [dict(type='references', target_id=str(uuid4()))]
        path.write_bytes(encoded(meta)); self.git.commit('Invalid dangling relation')
        before = self.git.head()
        with self.assertRaises(ValidationError): self.service.delete(self.request(id_), str(uuid4()))
        self.assertEqual(self.git.head(), before)
        self.assertTrue((self.root / 'artifacts' / id_ / 'content.md').exists())
        self.assertIsNone(self.service.workspace(self.id).recover())

    def test_foreign_recreation_during_partial_delete_is_preserved(self):
        id_ = self.create(); request, operation = self.request(id_), str(uuid4())
        def interrupt(stage):
            if stage == 'file:0': raise RuntimeError('Interrupted deletion')
        with self.assertRaises(RuntimeError): self.service.delete(request, operation, checkpoint=interrupt)
        path = self.root / 'artifacts' / id_ / 'content.md'
        path.write_text('Foreign replacement')
        with self.assertRaises(RecoveryConflict): self.service.open(self.id)
        self.assertEqual(path.read_text(), 'Foreign replacement')
        self.assertEqual(self.git.head(), request['base_head'])
        path.unlink()
        self.service.open(self.id)
        self.assertEqual(self.service.delete(request, operation)['commit_id'], self.git.head())

    def test_process_crashes_recover_deletion_once_at_every_boundary(self):
        script = '''
import json, os, sys
from spikes.artifacts import Artifacts
def checkpoint(stage):
    if stage == sys.argv[4]: os._exit(73)
Artifacts(sys.argv[1]).delete(json.loads(sys.argv[2]), sys.argv[3], checkpoint=checkpoint)
'''
        stages = ('prepared', 'file:0', 'file:1', 'applied', 'files-applied', 'commit-created',
                  'commit-ready', 'before-ref', 'ref-updated', 'committed', 'git-indexed',
                  'index-cleared', 'index-entities', 'index-relations', 'index-state',
                  'index-published', 'indexed', 'completed')
        for frontmatter in (False, True):
            for stage in stages:
                if frontmatter and stage == 'file:1': continue
                with self.subTest(frontmatter=frontmatter, stage=stage):
                    id_ = self.create(frontmatter=frontmatter)
                    request, operation = self.request(id_), str(uuid4())
                    result = subprocess.run([sys.executable, '-c', script, str(self.node),
                        json.dumps(request), operation, stage], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    view = Artifacts(self.node).open(self.id)
                    receipt = self.service.delete(request, operation)
                    self.assertEqual(receipt['commit_id'], view['commit_id'])
                    self.assertNotIn(id_, {d['id'] for d in view['documents']})
                    self.assertNotIn(id_, self.service.workspace(self.id).read_projection()['entities'])
                    self.assertEqual(self.git.run('rev-list', '--count', request['base_head'] + '..HEAD').stdout.strip(), '1')
                    self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
                    self.assertIsNone(self.service.workspace(self.id).recover())

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt widgets')
    def test_native_confirmation_cancel_lost_reply_retry_and_refresh(self):
        id_ = self.create()
        script = r'''
import sys, time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from spikes.artifacts import Artifacts
from spikes.desktop_editor import EditorDialog
app = QApplication([])
service = Artifacts(sys.argv[1])
original = service.delete
calls = []
def delete(request, operation):
    calls.append((request, operation))
    receipt = original(request, operation)
    if len(calls) == 1: raise RuntimeError('Lost reply')
    return receipt
service.delete = delete
def idle(dialog):
    deadline = time.monotonic() + 10
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert not dialog.busy, dialog.status.text()
def answer(button):
    box = app.activeModalWidget()
    assert isinstance(box, QMessageBox)
    assert box.textFormat() == Qt.TextFormat.PlainText
    assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
    box.button(button).click()
dialog = EditorDialog(service, sys.argv[2]); dialog.show(); idle(dialog)
refreshed = []
dialog.saved.connect(refreshed.append)
head = dialog.view['commit_id']
dialog.body.setPlainText('Unsaved draft')
QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
dialog.delete_button.click()
assert dialog.dirty and dialog.body.toPlainText() == 'Unsaved draft'
assert not calls and service.workspace(sys.argv[2]).git.head() == head
QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
dialog.delete_button.click(); idle(dialog)
assert dialog.pending_delete and dialog.pending and dialog.body.isReadOnly()
assert dialog.body.toPlainText() == 'Unsaved draft'
assert dialog.save_button.text() == 'Zopakovat smazání'
assert not dialog.delete_button.isEnabled() and not refreshed
operation = dialog.pending[1]
dialog.save_button.click(); idle(dialog)
assert len(calls) == 2 and calls[0] == calls[1]
assert service.workspace(sys.argv[2]).receipt(operation)
assert not dialog.pending and not dialog.pending_delete
assert sys.argv[3] not in [d['id'] for d in dialog.view['documents']]
assert dialog.current['new'] and not dialog.delete_button.isEnabled()
assert refreshed == [sys.argv[2]]
assert dialog.status.text() == 'Dokument odstraněn. Historie zůstává v Gitu.'
# Reload resumes a prepared deletion even if the reply failed before commit.
service.delete = original
request = dict(project_id=sys.argv[2], artifact_id=sys.argv[3],
               base_head=service.workspace(sys.argv[2]).git.head(),
               title='Recreated', body='Persisted', new=True)
service.save(request, str(__import__('uuid').uuid4()))
dialog.dirty = False
dialog.reload(); idle(dialog)
def interrupted(request, operation):
    def checkpoint(stage):
        if stage == 'prepared': raise RuntimeError('Interrupted before files')
    return original(request, operation, checkpoint=checkpoint)
service.delete = interrupted
QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
dialog.delete_button.click(); idle(dialog)
assert dialog.pending_delete
assert (service.workspace(sys.argv[2]).git.root / ('artifacts/' + sys.argv[3] + '/content.md')).exists()
operation = dialog.pending[1]
def discard():
    box = app.activeModalWidget()
    assert isinstance(box, QMessageBox)
    box.button(QMessageBox.StandardButton.Discard).click()
QTimer.singleShot(0, discard)
dialog.reload_button.click(); idle(dialog)
assert service.workspace(sys.argv[2]).receipt(operation)
assert not dialog.pending and not dialog.pending_delete
assert sys.argv[3] not in [d['id'] for d in dialog.view['documents']]
# The empty draft requires confirmation on closing; terminate only after workers stop.
for worker in dialog.workers: worker.wait()
dialog.dirty = False; dialog.close(); app.processEvents()
print('native deletion verified')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.node), self.id, id_],
                                capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native deletion verified', result.stdout)
