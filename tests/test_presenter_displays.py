# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native role selection and display-change recovery, without a WebEngine GPU."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication, QMainWindow
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
        self.configurations = []
        self.closed = []
        self.errors = []
        self.manager = PresenterDisplays(
            self.app, self.speaker, self.audience,
            configuration_callback=self.configurations.append,
            closed_callback=lambda: self.closed.append(True),
            error_callback=self.errors.append)

    def tearDown(self):
        self.manager.stop()
        self.speaker.close()
        self.audience.close()
        self.app.processEvents()

    def test_open_identifies_and_rejects_same_screen(self):
        self.assertFalse(self.audience.isVisible())
        self.manager.open()
        configuration = self.configurations[-1]
        self.assertEqual(configuration['speaker'], 0)
        self.assertEqual(configuration['audience'], -1)
        self.assertEqual(len(configuration['screens']), len(self.app.screens()))
        self.manager.identify_selection(configuration['token'], 0, -1)
        self.assertEqual(len(self.manager.markers), len(self.app.screens()))
        self.assertIn('Displej 1', self.manager.markers[0].text())
        with self.assertRaises(ValueError):
            self.manager.apply_selection(configuration['token'], 0, 0)
        self.manager.apply_selection(configuration['token'], 0, -1)
        self.assertTrue(self.closed)
        self.assertFalse(self.audience.isVisible())
        self.assertTrue(self.speaker.isVisible())
        self.assertEqual(self.manager.markers, [])

    def test_change_hides_output_and_reopens_selector_cancel_stays_hidden(self):
        self.manager.open()
        self.audience.show()
        self.manager.changed()
        self.assertFalse(self.audience.isVisible())
        self.assertTrue(self.manager.refresh.isActive())
        self.manager.configure()
        self.assertGreaterEqual(len(self.configurations), 2)
        self.manager.cancel_configuration()
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
            configuration = self.configurations[-1]
            self.manager.apply_selection(configuration['token'], 0, 1)
            self.assertEqual(place.call_count, 2)
            self.assertEqual(place.call_args.args, (self.audience, extra_screen))
            self.assertEqual(place.call_args.kwargs, {'fullscreen': True})
            app.screens.return_value = [real_screen]
            self.manager.changed()
            self.manager.configure()
            configuration = self.configurations[-1]
            self.assertEqual(configuration['audience'], -1)
            self.assertEqual(len(configuration['screens']), 1)

    def test_stop_cancels_pending_dialog_and_identifiers(self):
        self.manager.open()
        self.manager.changed()
        self.manager.stop()
        self.assertFalse(self.manager.active)
        self.assertFalse(self.manager.refresh.isActive())
        self.assertIsNone(self.manager.selection_token)
        self.assertEqual(self.manager.markers, [])
        self.assertFalse(self.audience.isVisible())
