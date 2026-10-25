# SPDX-FileCopyrightText: 2026 Antonín Micka
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spikes.backend_catalog import (BackendResetJournal, ModelPreferences,
                                    backend_catalog, durable_unlink,
                                    resource_metric)


class BackendCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'state'
        self.root.mkdir(mode=0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def test_catalog_includes_non_model_services_without_secrets(self):
        value = backend_catalog({'atlascloud-text': {
            'configured': True, 'availability': 'available', 'detail': 'connected'}})
        rows = {item['backend_id']: item for item in value['backends']}
        self.assertIn('text-generation', rows['atlascloud-text']['services'])
        self.assertIn('storage-import', rows['google-drive']['services'])
        self.assertFalse(rows['google-drive']['configured'])
        self.assertNotIn('credential', str(value).lower())
        self.assertEqual(value, backend_catalog({'atlascloud-text': {
            'configured': True, 'availability': 'available', 'detail': 'connected'}}))

    def test_preferences_are_atomic_cas_ordering(self):
        store = ModelPreferences(self.root)
        self.assertEqual(store.load()['revision'], 0)
        saved = store.save(['model-b', 'model-a'], 0)
        self.assertEqual(saved['preferred_model_ids'], ['model-b', 'model-a'])
        self.assertEqual(store.load(), saved)
        self.assertEqual(oct(store.path.stat().st_mode & 0o777), '0o600')
        with self.assertRaisesRegex(ValueError, 'changed before save'):
            store.save(['model-a'], 0)
        with self.assertRaisesRegex(ValueError, 'Duplicate|Invalid preferred'):
            store.save(['model-a', 'model-a'], 1)

    def test_preferences_reject_unsafe_file(self):
        store = ModelPreferences(self.root)
        store.save(['model-a'], 0)
        os.chmod(store.path, 0o644)
        with self.assertRaisesRegex(ValueError, 'Unsafe model preference'):
            store.load()

    def test_reset_journal_is_durable_and_recoverable(self):
        journal = BackendResetJournal(self.root, 'openai-responses')
        value = journal.begin(['credential:openai-test'])
        self.assertEqual(journal.load(), value)
        self.assertEqual(oct(journal.path.stat().st_mode & 0o777), '0o600')
        profile = self.root / 'profile.json'
        profile.write_text('{}')
        self.assertTrue(durable_unlink(profile))
        self.assertFalse(durable_unlink(profile))
        journal.finish()
        self.assertIsNone(journal.load())

    def test_free_and_prepaid_tokens_are_balances_not_consumption(self):
        free = resource_metric(backend_id='atlascloud-text',
            kind='free-token-balance', name='free_tokens', value=1200,
            unit='tokens', scope='account', fetched_at='2026-10-25T00:00:00Z')
        prepaid = resource_metric(backend_id='atlascloud-text',
            kind='prepaid-token-balance', name='prepaid_tokens', value=5000,
            unit='tokens', scope='account', fetched_at='2026-10-25T00:00:00Z')
        self.assertEqual((free['kind'], prepaid['kind']),
                         ('free-token-balance', 'prepaid-token-balance'))
        stale = resource_metric(backend_id='atlascloud-text',
            kind='prepaid-token-balance', name='prepaid_tokens', value=5000,
            unit='tokens', scope='account', status='stale',
            fetched_at='2026-10-25T00:00:00Z')
        self.assertEqual((stale['status'], stale['value']), ('stale', 5000))
        with self.assertRaisesRegex(ValueError, 'resource value'):
            resource_metric(backend_id='atlascloud-text', kind='consumption',
                name='tokens', value=None, unit='tokens', scope='run')

    def test_shared_ui_exposes_backend_and_read_only_model_tables(self):
        from spikes.desktop_ui import HTML, JS
        for marker in ('id="backend-catalog-table"', 'id="settings-models-tab"',
                       'id="settings-models-table"', 'id="settings-model-detail"',
                       'id="atlascloud-run-usage"', 'id="resource-atlascloud-balance"',
                       'id="backend-settings-dialog"', 'id="backend-reset-dialog"',
                       'id="backend-settings-legacy" hidden'):
            self.assertIn(marker, HTML)
        self.assertIn("'/v1/backend-catalog/status'", JS)
        self.assertIn("'/v1/backend-catalog/reset'", JS)
        self.assertIn("'/v1/model-selection/status'", JS)
        self.assertIn("configure.textContent='Nastavit'", JS)
        self.assertIn("reset.textContent='Resetovat'", JS)
        self.assertIn("providers.get('atlascloud-text')", JS)
        self.assertNotIn('innerHTML', JS[JS.index('function renderBackendCatalog'):JS.index('function selectSettingsTab')])


if __name__ == '__main__':
    unittest.main()
