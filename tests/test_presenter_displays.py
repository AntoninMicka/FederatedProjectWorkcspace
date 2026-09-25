# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native role selection and display-change recovery, without a WebEngine GPU."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QComboBox, QDialogButtonBox
    from spikes.desktop_displays import PresenterDisplays
except ImportError:
    PresenterDisplays = None


@unittest.skipIf(PresenterDisplays is None, 'PySide6 is unavailable')
class PresenterDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.speaker = QMainWindow()
        self.audience = QMainWindow()
        self.speaker.show()
        self.manager = PresenterDisplays(self.app, self.speaker, self.audience)

    def tearDown(self):
        self.manager.stop()
        self.speaker.close()
        self.audience.close()
        self.app.processEvents()

    def controls(self):
        speaker, audience = self.manager.dialog.findChildren(QComboBox)
        buttons = self.manager.dialog.findChild(QDialogButtonBox)
        return speaker, audience, buttons

    def test_open_identifies_and_rejects_same_screen(self):
        self.assertFalse(self.audience.isVisible())
        self.manager.open()
        speaker, audience, buttons = self.controls()
        self.assertEqual(len(self.manager.markers), len(self.app.screens()))
        self.assertIn('Displej 1', self.manager.markers[0].text())
        audience.setCurrentIndex(speaker.currentIndex() + 1)
        self.assertFalse(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        audience.setCurrentIndex(0)
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        self.assertIsNone(self.manager.dialog)
        self.assertFalse(self.audience.isVisible())
        self.assertTrue(self.speaker.isVisible())
        self.assertEqual(self.manager.markers, [])

    def test_change_hides_output_and_reopens_selector_cancel_stays_hidden(self):
        self.manager.open()
        self.manager.dialog.reject()
        self.audience.show()
        self.manager.changed()
        self.assertFalse(self.audience.isVisible())
        self.assertTrue(self.manager.refresh.isActive())
        self.manager.configure()
        self.assertIsNotNone(self.manager.dialog)
        self.manager.dialog.reject()
        self.assertFalse(self.audience.isVisible())
        self.manager.stop()
        self.manager.changed()
        self.assertFalse(self.manager.refresh.isActive())

    def test_two_screens_apply_and_removed_selection_not_reused(self):
        real_screen = self.app.primaryScreen()
        extra_screen = Mock()
        extra_screen.name.return_value = 'Projector'
        extra_screen.geometry.return_value = real_screen.geometry()
        app = Mock()
        app.screens.return_value = [real_screen, extra_screen]
        self.manager.stop()
        self.manager.app = app
        with patch.object(self.manager, 'identify'), patch.object(self.manager, 'place') as place:
            self.manager.open()
            _, audience, buttons = self.controls()
            audience.setCurrentIndex(2)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
            self.assertEqual(place.call_count, 2)
            self.assertEqual(place.call_args.args, (self.audience, extra_screen))
            self.assertEqual(place.call_args.kwargs, {'fullscreen': True})
            app.screens.return_value = [real_screen]
            self.manager.changed()
            self.manager.configure()
            _, audience, _ = self.controls()
            self.assertEqual(audience.currentData(), -1)
            self.assertEqual(audience.count(), 2)

    def test_stop_cancels_pending_dialog_and_identifiers(self):
        self.manager.open()
        self.manager.changed()
        self.manager.stop()
        self.assertFalse(self.manager.active)
        self.assertFalse(self.manager.refresh.isActive())
        self.assertIsNone(self.manager.dialog)
        self.assertEqual(self.manager.markers, [])
        self.assertFalse(self.audience.isVisible())
