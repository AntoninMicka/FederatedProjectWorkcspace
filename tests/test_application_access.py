# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from spikes.application_access import (ApplicationAccess, DEFAULT_SETTINGS,
                                        validate_settings)


class ApplicationAccessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.node = Path(self.temporary.name) / 'node.json'
        self.access = ApplicationAccess(self.node, '192.168.50.0/24')

    def test_default_preserves_private_lan_and_always_allows_loopback(self):
        self.assertEqual(DEFAULT_SETTINGS, self.access.settings)
        self.assertTrue(self.access.allows('127.0.0.1'))
        self.assertTrue(self.access.allows('192.168.50.23'))
        self.assertFalse(self.access.allows('192.168.51.23'))

    def test_modes_cover_local_allowlist_and_unrestricted(self):
        local = {'mode': 'localhost', 'allowed': []}
        allowed = {'mode': 'allowlist', 'allowed': ['203.0.113.4', '2001:db8::/48']}
        open_policy = {'mode': 'unrestricted', 'allowed': []}
        self.assertFalse(self.access.allows('192.168.50.2', local))
        self.assertTrue(self.access.allows('203.0.113.4', allowed))
        self.assertFalse(self.access.allows('203.0.113.5', allowed))
        self.assertTrue(self.access.allows('2001:db8::10', allowed))
        self.assertTrue(self.access.allows('8.8.8.8', open_policy))

    def test_validation_is_exact_and_fail_closed(self):
        self.assertEqual({'mode': 'allowlist', 'allowed': ['192.0.2.4', '10.0.0.0/8']},
                         validate_settings({'mode': 'allowlist',
                                            'allowed': ['192.0.2.4', '10.0.0.0/8', '192.0.2.4']}))
        invalid = [
            {'mode': 'other', 'allowed': []},
            {'mode': 'allowlist', 'allowed': []},
            {'mode': 'localhost', 'allowed': ['192.0.2.4']},
            {'mode': 'allowlist', 'allowed': ['10.0.0.1/8']},
            {'mode': 'allowlist', 'allowed': ['0.0.0.0/0']},
            {'mode': 'allowlist', 'allowed': ['host.example']},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings(value)

    def test_preview_confirm_is_bound_to_revision_peer_and_disconnect(self):
        settings = {'mode': 'localhost', 'allowed': []}
        plan = self.access.preview(settings, '192.168.50.10')
        self.assertFalse(plan['current_client_allowed'])
        with self.assertRaises(ValueError):
            self.access.confirm(plan, '192.168.50.10', False)
        result = self.access.confirm(plan, '192.168.50.10', True)
        self.assertEqual(settings, result['settings'])
        self.assertEqual(settings, ApplicationAccess(self.node, '192.168.50.0/24').settings)
        self.assertEqual(0o600, self.access.path.stat().st_mode & 0o777)
        with self.assertRaises(ValueError):
            self.access.confirm(plan, '192.168.50.10', True)

    def test_interrupted_transaction_keeps_previous_policy(self):
        first = self.access.preview({'mode': 'unrestricted', 'allowed': []}, '127.0.0.1')
        self.access.confirm(first, '127.0.0.1', False)
        second = self.access.preview({'mode': 'localhost', 'allowed': []}, '127.0.0.1')
        with self.assertRaises(RuntimeError):
            self.access.confirm(second, '127.0.0.1', False,
                                checkpoint=lambda: (_ for _ in ()).throw(RuntimeError('stop')))
        self.assertEqual('unrestricted', ApplicationAccess(self.node, '192.168.50.0/24').settings['mode'])

    def test_invalid_durable_value_fails_closed_on_start(self):
        self.access.path.touch(mode=0o600)
        with sqlite3.connect(self.access.path) as db:
            db.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('INSERT INTO settings VALUES (1, ?)',
                       (json.dumps({'mode': 'unrestricted', 'allowed': ['0.0.0.0/0']}),))
        with self.assertRaises(ValueError):
            ApplicationAccess(self.node, '192.168.50.0/24')


if __name__ == '__main__':
    unittest.main()
