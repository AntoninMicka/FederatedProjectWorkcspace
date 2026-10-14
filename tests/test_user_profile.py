# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local contact profile durability and generated presentation content."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from spikes.user_profile import UserProfile, validate_profile, PROFILE_FIELDS
from spikes.presentation_closing import closing_slide
from spikes.desktop_ui import presentation_status, presentation_public_payload
from spikes.presentation_documents import project_deck
from tests.test_presentation_documents import sample

PROFILE = dict(name='Jana Nováková', email='jana@example.invalid', phone='+420 123 456 789', web='https://example.invalid')


class UserProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.node = Path(self.temp.name) / 'node.json'
        self.store = UserProfile(self.node)

    def test_save_restart_and_process_crash_keep_whole_profile(self):
        self.assertEqual(self.store.load(), {key: '' for key in PROFILE_FIELDS})
        self.assertFalse(self.store.path.exists())
        self.store.save(PROFILE)
        self.assertEqual(UserProfile(self.node).load(), PROFILE)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        script = "from spikes.user_profile import UserProfile; import os,sys,json; UserProfile(sys.argv[1]).save(json.loads(sys.argv[2]), checkpoint=lambda: os._exit(73))"
        changed = dict(PROFILE, name='Changed')
        result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(changed)])
        self.assertEqual(result.returncode, 73)
        self.assertEqual(UserProfile(self.node).load(), PROFILE)
        # First-ever save may leave an empty database/table; treat it as an empty profile.
        other = Path(self.temp.name) / 'other.json'
        result = subprocess.run([sys.executable, '-c', script, str(other), json.dumps(changed)])
        self.assertEqual(result.returncode, 73)
        self.assertEqual(UserProfile(other).load(), {key: '' for key in PROFILE_FIELDS})
        self.store.save(changed); self.assertEqual(UserProfile(self.node).load(), changed)

    def test_validation_precedes_write_and_never_infers_contacts(self):
        for value in (dict(PROFILE, name='a' * 101), dict(PROFILE, phone='bad\nline'),
                      dict(PROFILE, email=1), dict(PROFILE, extra='x'), {'name': 'Incomplete'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.save(value)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(closing_slide()['contacts'], [])
        self.assertEqual(closing_slide()['qr'], '')

    def test_session_snapshots_profile_and_only_explicit_projection_is_public(self):
        self.store.save(PROFILE)
        source = project_deck(sample(), 'one')
        server = SimpleNamespace(user_profile=self.store, presentation_selected_deck=source)
        session = presentation_status(server, start=True)
        final = session['slides'][-1]
        self.assertTrue(final['closing']); self.assertEqual(len(session['slides']), 4)
        self.assertEqual(len(source['slides']), 3)
        self.assertEqual(final['title'], 'Prostor pro Vaše dotazy')
        self.assertFalse(presentation_public_payload(server)['visible'])
        self.store.save(dict(PROFILE, name='New profile'))
        shown = presentation_public_payload(server, dict(action='show', slide=3,
            slide_id=final['id'], deck_revision='one', rows=0))
        self.assertEqual(shown['content']['contacts'], list(PROFILE.values()))
        self.assertNotIn('notes', shown['content'])
        new = presentation_status(server, start=True)
        self.assertEqual(new['slides'][-1]['contacts'][0], 'New profile')
        self.assertEqual(presentation_public_payload(server), shown)
        server.presentation_selected_deck = project_deck(sample(), 'two')
        with self.assertRaises(ValueError):
            presentation_public_payload(server, dict(action='show', slide_id=final['id'], deck_revision='one'))
        self.assertEqual(presentation_public_payload(server), shown)

    def test_qr_decodes_exact_unicode_contact_text(self):
        try:
            import zxingcpp
            from PIL import Image
        except ImportError:
            self.skipTest('Optional independent QR decoder zxing-cpp and Pillow')
        result = closing_slide(PROFILE)
        raw = base64.b64decode(result['qr'].split(',', 1)[1])
        decoded = zxingcpp.read_barcode(Image.open(io.BytesIO(raw)))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.text, '\n'.join(PROFILE.values()))


class UserProfileDialogTests(unittest.TestCase):
    def test_native_settings_save_and_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        try:
            from PySide6.QtWidgets import QApplication
            from spikes.desktop_user_profile import UserProfileDialog
        except ImportError:
            self.skipTest('Requires Qt widgets')
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            store = UserProfile(Path(directory) / 'node.json')
            dialog = UserProfileDialog(store)
            for key, value in PROFILE.items():
                dialog.fields[key].setText(value)
            dialog.save_button.click()
            self.assertEqual(store.load(), PROFILE)
            reopened = UserProfileDialog(UserProfile(Path(directory) / 'node.json'))
            self.assertEqual({key: field.text() for key, field in reopened.fields.items()}, PROFILE)
            reopened.reject(); dialog.close(); app.processEvents()
