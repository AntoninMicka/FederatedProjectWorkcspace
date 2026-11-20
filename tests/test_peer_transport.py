# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B5-T1: one peer address policy and named network budgets."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from spikes import peer_transport
from spikes.federation_catalog import CatalogScheduler
from spikes.federation_sync import ContentSyncScheduler
from spikes.metadata import ValidationError
from spikes.peer_transport import private_peer_endpoint, stop_timeout
from spikes.replication_control import ReplicationScheduler

MESSAGES = dict(invalid='Invalid test endpoint', private='Test peer must use a private IPv4 address')


class PeerPolicyTests(unittest.TestCase):
    def test_private_and_loopback_ipv4_origins_are_allowed(self):
        for endpoint, address in (('https://192.168.1.20:8443', '192.168.1.20'),
                                  ('https://10.1.2.3', '10.1.2.3'),
                                  ('https://127.0.0.1:9000/', '127.0.0.1')):
            with self.subTest(endpoint=endpoint):
                parsed, result = private_peer_endpoint(endpoint, **MESSAGES)
                self.assertEqual(str(result), address)
                self.assertEqual(result.version, 4)
                self.assertEqual(parsed.scheme, 'https')

    def test_public_ipv6_hostname_and_unspecified_are_refused_explicitly(self):
        for endpoint in ('https://8.8.8.8', 'https://100.64.0.1', 'https://[fd00::1]:8443',
                         'https://[::1]', 'https://peer.example', 'https://0.0.0.0:8443'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValidationError, '^Test peer must use a private IPv4 address$'):
                    private_peer_endpoint(endpoint, **MESSAGES)

    def test_non_origin_urls_are_invalid(self):
        for endpoint in ('http://192.168.1.2', 'https://192.168.1.2/api', 'https://u:p@192.168.1.2',
                         'https://192.168.1.2?x=1', 'https://192.168.1.2#f'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValidationError, '^Invalid test endpoint$'):
                    private_peer_endpoint(endpoint, **MESSAGES)


class CallerPolicyTests(unittest.TestCase):
    """Every former copy now calls the shared policy with its unchanged messages."""

    def assert_refused(self, call, message):
        with self.assertRaisesRegex(ValidationError, '^' + message + '$'):
            call()

    def test_replication_allows_loopback_like_other_peers(self):
        from spikes import project_replication
        authority = {'peer': {'id': 'peer', 'endpoint': 'https://[fd00::1]'}}
        with patch.object(project_replication, 'prepare', return_value=({}, b'', authority, 0)):
            self.assert_refused(lambda: project_replication.send(Path('/x'), 'r', 'o', None),
                                'Replication peer must use a private IPv4 address')
        _, address = private_peer_endpoint('https://127.0.0.1', invalid='i', private='p')
        self.assertTrue(address.is_private and address.is_loopback)

    def test_catalog_content_rss_and_state_keep_their_messages(self):
        from spikes import federation_catalog, federation_sync, rss_subscription_sync, sync_fingerprint
        peer = {'id': 'peer', 'endpoint': 'https://peer.example', 'fingerprint': 'f'}
        with patch.object(federation_catalog, 'Administration'), \
                patch.object(federation_catalog, 'prepare', return_value=({}, peer)):
            self.assert_refused(lambda: federation_catalog.synchronize(Path('/x'), 'peer'),
                                'Catalog peer must use a private IPv4 address')
        self.assert_refused(lambda: rss_subscription_sync.exchange(Path('/x'), peer, {}),
                            'RSS peer requires private IPv4')
        service = MagicMock()
        with patch('spikes.federation_sync._authority', return_value=('local', peer, None, None)):
            self.assert_refused(lambda: sync_fingerprint.probe(service, 'peer', projects=[]),
                                'Content state requires private IPv4')
        source = Path(federation_sync.__file__).read_text()
        self.assertIn("private='Content sync peer must use a private IPv4 address'", source)
        for module in (federation_catalog, federation_sync, rss_subscription_sync, sync_fingerprint):
            self.assertFalse(hasattr(module, 'ipaddress'), module.__name__)


class BudgetTests(unittest.TestCase):
    def test_scheduler_stop_deadline_is_derived_from_its_exchange_budget(self):
        self.assertEqual(peer_transport.SHUTDOWN_MARGIN, 5)
        self.assertEqual(CatalogScheduler.STOP_TIMEOUT, stop_timeout(peer_transport.CATALOG_EXCHANGE_TIMEOUT))
        self.assertEqual(ContentSyncScheduler.STOP_TIMEOUT, stop_timeout(peer_transport.CONTENT_SYNC_TIMEOUT))
        self.assertEqual(ReplicationScheduler.STOP_TIMEOUT, stop_timeout(peer_transport.REPLICATION_TIMEOUT))
        # Values unchanged by the rename (former literals 20, 65 and 35 s).
        self.assertEqual((CatalogScheduler.STOP_TIMEOUT, ContentSyncScheduler.STOP_TIMEOUT,
                          ReplicationScheduler.STOP_TIMEOUT), (20, 65, 35))

    def test_transports_use_the_named_budget(self):
        from spikes import federation_catalog
        peer = {'id': 'peer', 'endpoint': 'https://192.168.1.5:8443'}
        with patch.object(federation_catalog, 'Administration'), \
                patch.object(federation_catalog, 'prepare', return_value=({}, peer)), \
                patch.object(federation_catalog.ssl, 'create_default_context'), \
                patch.object(federation_catalog, 'DeadlineHTTPSConnection',
                             side_effect=RuntimeError('stop')) as connection:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                federation_catalog.synchronize(Path('/x'), 'peer', ca='/x/ca.pem')
        self.assertEqual(connection.call_args.kwargs['timeout'], peer_transport.CATALOG_EXCHANGE_TIMEOUT)

    def test_web_bind_refuses_ipv6_explicitly(self):
        from spikes.web_server import make_server
        with self.assertRaisesRegex(ValueError, 'IPv6 is not supported'):
            make_server('fd00::1', 0, '192.168.100.0/24', 'c', 'k', 't', 'n')


if __name__ == '__main__':
    unittest.main()
