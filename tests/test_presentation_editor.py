# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native editor interactions, persistence and retry after an uncertain save."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from spikes.desktop_presentation_editor import PresentationEditorDialog
except ImportError:
    PresentationEditorDialog = None

from spikes.presentation_documents import PresentationDocuments, main_order
from spikes.project_creation import ProjectCreation
from tests.test_presentation_documents import PNG


@unittest.skipIf(PresentationEditorDialog is None, 'PySide6 is unavailable')
class PresentationEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name); self.node = base / 'node.json'
        self.project = ProjectCreation(self.node).create('Editor project', str(base / 'project'), str(uuid4()))['id']
        self.service = PresentationDocuments(self.node)
        self.dialog = PresentationEditorDialog(self.service, self.project)
        self.dialog.show(); self.wait_ready()

    def wait_ready(self):
        deadline = time.monotonic() + 15
        while self.dialog.busy and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.01)
        self.assertFalse(self.dialog.busy, self.dialog.status.text())
        self.app.processEvents()

    def tearDown(self):
        self.wait_ready()
        for worker in self.dialog.workers:
            worker.wait()
        self.dialog.dirty = False; self.dialog.pending = None; self.dialog.close()

    def test_edit_links_both_directions_save_reopen_and_explicit_use(self):
        emitted = []; self.dialog.selected.connect(emitted.append)
        self.dialog.deck_title.setText('Edited deck')
        self.dialog.title.setText('First')
        self.dialog.bullets.setPlainText('Point one\nPoint two')
        self.dialog.notes.setPlainText('Private only')
        self.dialog.repeat.setChecked(True)
        self.dialog.reveal.setCurrentIndex(1)
        self.dialog.set_wallpaper(PNG)
        first = self.dialog.slide_id
        self.dialog.add('main'); self.dialog.title.setText('Second'); second = self.dialog.slide_id
        self.dialog.add('backup'); self.dialog.title.setText('Answer'); backup = self.dialog.slide_id
        # Reverse side: shared backup also belongs to the first slide.
        for index in range(self.dialog.backups.count()):
            self.dialog.backups.item(index).setCheckState(Qt.CheckState.Checked)
        for slide in self.dialog.deck['slides'][:2]:
            self.assertIn(backup, slide['backups'])
        self.dialog.slide_id = second; self.dialog.refresh()
        self.dialog.previous.setCurrentIndex(0); self.dialog.neighbor(True)
        self.assertEqual(main_order(self.dialog.deck), [second, first])
        self.assertFalse(self.dialog.use_button.isEnabled())
        self.dialog.save(); self.wait_ready()
        self.assertFalse(self.dialog.dirty, self.dialog.status.text())
        self.assertEqual(emitted, [])  # Save must not project anything.
        view = PresentationDocuments(self.node).open(self.project)
        stored = view['documents'][0]['deck']
        self.assertEqual(stored['title'], 'Edited deck')
        slide = next(s for s in stored['slides'] if s['id'] == first)
        self.assertEqual(slide['wallpaper'], PNG)
        self.assertTrue(slide['repeat'])
        self.assertEqual(slide['reveal'], 'step')
        self.assertEqual(slide['bullets'], ['Point one', 'Point two'])
        self.assertTrue(self.dialog.use_button.isEnabled())
        self.dialog.use()
        self.assertEqual(emitted[0]['slides'][0]['title'], 'Second')
        self.assertEqual(emitted[0]['backups'][0]['after_slides'], [0, 1])
        self.assertFalse(self.dialog.isVisible())
        self.dialog.loaded(view)
        self.assertEqual(self.dialog.deck, stored)
        self.dialog.slide_id = first; self.dialog.refresh()
        self.assertTrue(self.dialog.repeat.isChecked())
        self.assertEqual(self.dialog.reveal.currentData(), 'step')

    def test_uncertain_save_freezes_draft_and_retries_same_operation(self):
        original = self.service.save
        calls = []
        def fail_after_commit(request, operation):
            calls.append(operation)
            receipt = original(request, operation)
            if len(calls) == 1:
                raise RuntimeError('Lost result after commit')
            return receipt
        with patch.object(self.service, 'save', side_effect=fail_after_commit):
            self.dialog.save(); self.wait_ready()
            self.assertIsNotNone(self.dialog.pending)
            self.assertFalse(self.dialog.content.isEnabled())
            self.assertFalse(self.dialog.use_button.isEnabled())
            self.dialog.save(); self.wait_ready()
        self.assertEqual(calls[0], calls[1])
        self.assertIsNone(self.dialog.pending)
        self.assertEqual(len(self.service.open(self.project)['documents']), 1)
        self.assertTrue(self.dialog.use_button.isEnabled())

    def test_cancel_keeps_draft_and_invalid_save_stays_private(self):
        self.dialog.title.setText('')
        self.dialog.save()
        self.assertIsNone(self.dialog.pending)
        self.assertEqual(self.service.open(self.project)['documents'], [])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.dialog.reject()
        self.assertTrue(self.dialog.isVisible())
        self.assertTrue(self.dialog.dirty)
