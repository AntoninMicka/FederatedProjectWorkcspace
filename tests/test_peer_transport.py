# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B5-T1: one dual-stack address policy and named network budgets."""
import ipaddress
import json
import socket
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from spikes import peer_transport
from spikes.federation_catalog import CatalogScheduler
from spikes.federation_sync import ContentSyncScheduler
from spikes.http_deadline import DeadlineHTTPSConnection
from spikes.metadata import ValidationError
from spikes.network_backend import NetworkBackend, ProbeHandler
from spikes.peer_transport import (canonical_address, origin, private_address, private_lan,
                                   private_peer_endpoint, stop_timeout)
from spikes.replication_control import ReplicationScheduler
from spikes.web_server import WebServer

MESSAGES = dict(invalid='Invalid test endpoint', private='Test peer must use a private IP address')
REFUSED = ('https://8.8.8.8', 'https://100.64.0.1', 'https://[2001:db8::1]', 'https://[2a00::1]',
           'https://[fe80::1]', 'https://[fe80::1%25eth0]', 'https://[::ffff:192.168.1.2]',
           'https://[::]:8443', 'https://peer.example', 'https://0.0.0.0:8443')


class AddressPolicyTests(unittest.TestCase):
    def test_private_ipv4_and_ipv6_origins_are_allowed(self):
        for endpoint, address, netloc in (
                ('https://192.168.1.20:8443', '192.168.1.20', '192.168.1.20:8443'),
                ('https://10.1.2.3', '10.1.2.3', '10.1.2.3'),
                ('https://127.0.0.1:9000/', '127.0.0.1', '127.0.0.1:9000'),
                ('https://[fd12:3456::1]:8443', 'fd12:3456::1', '[fd12:3456::1]:8443'),
                ('https://[FD00:0:0::0001]:8443', 'fd00::1', '[fd00::1]:8443'),
                ('https://[::1]', '::1', '[::1]')):
            with self.subTest(endpoint=endpoint):
                parsed, result = private_peer_endpoint(endpoint, **MESSAGES)
                self.assertEqual(str(result), address)
                self.assertEqual(parsed.scheme, 'https')
                # Host header uses the canonical spelling the receiver compares with.
                self.assertEqual(parsed.netloc, netloc)

    def test_public_link_local_mapped_hostname_and_unspecified_are_refused(self):
        # 2001:db8::/32 is "private" for ipaddress but is not a unique local address.
        for endpoint in REFUSED:
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValidationError, '^Test peer must use a private IP address$'):
                    private_peer_endpoint(endpoint, **MESSAGES)

    def test_non_origin_urls_are_invalid(self):
        for endpoint in ('http://192.168.1.2', 'https://192.168.1.2/api', 'https://u:p@192.168.1.2',
                         'https://192.168.1.2?x=1', 'https://[fd00::1]#f'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValidationError, '^Invalid test endpoint$'):
                    private_peer_endpoint(endpoint, **MESSAGES)

    def test_lan_origin_and_canonical_address(self):
        for value, allowed in (('192.168.100.0/24', True), ('10.0.0.0/8', True), ('10.0.0.0/7', False),
                               ('8.8.8.0/24', False), ('fd00:1::/64', True), ('fc00::/7', True),
                               ('fe80::/64', False), ('2001:db8::/32', False)):
            with self.subTest(lan=value):
                self.assertEqual(private_lan(ipaddress.ip_network(value)), allowed)
        self.assertEqual(origin('fd00::1', 8443), 'https://[fd00::1]:8443')
        self.assertEqual(origin('192.168.1.5', 8443), 'https://192.168.1.5:8443')
        # A dual-stack socket reports IPv4 clients as mapped; checks see plain IPv4.
        self.assertEqual(canonical_address('::ffff:127.0.0.1'), ipaddress.ip_address('127.0.0.1'))
        self.assertTrue(canonical_address('::ffff:127.0.0.1').is_loopback)
        self.assertFalse(private_address(ipaddress.ip_address('::')))


class CallerPolicyTests(unittest.TestCase):
    """Every former copy calls the shared policy with its own message."""

    def assert_refused(self, call, message):
        with self.assertRaisesRegex(ValidationError, '^' + message + '$'):
            call()

    def test_federation_transports_use_shared_policy(self):
        from spikes import (federation_catalog, federation_enrollment, federation_probe,
                            federation_sync, project_replication, rss_subscription_sync,
                            sync_fingerprint)
        peer = {'id': 'peer', 'endpoint': 'https://peer.example', 'fingerprint': 'f'}
        with patch.object(project_replication, 'prepare', return_value=({}, b'', {'peer': peer}, 0)):
            self.assert_refused(lambda: project_replication.send(Path('/x'), 'r', 'o', None),
                                'Replication peer must use a private IP address')
        with patch.object(federation_catalog, 'Administration'), \
                patch.object(federation_catalog, 'prepare', return_value=({}, peer)):
            self.assert_refused(lambda: federation_catalog.synchronize(Path('/x'), 'peer'),
                                'Catalog peer must use a private IP address')
        self.assert_refused(lambda: rss_subscription_sync.exchange(Path('/x'), peer, {}),
                            'RSS peer requires a private IP address')
        with patch('spikes.federation_sync._authority', return_value=('local', peer, None, None)):
            self.assert_refused(lambda: sync_fingerprint.probe(MagicMock(), 'peer', projects=[]),
                                'Content state requires a private IP address')
        with patch.object(federation_enrollment, 'Administration'), \
                patch.object(federation_enrollment, 'request_envelope', return_value=({}, peer)):
            self.assert_refused(lambda: federation_enrollment.enroll(Path('/x'), 'peer', 'a' * 43),
                                'Enrollment server must use a private IP address')
        self.assert_refused(lambda: federation_probe.check_peer('https://peer.example', '/x', 'peer', 'f'),
                            r'Test podporuje pouze privátní IP adresy uzlů \(IPv4 nebo IPv6\).')
        source = Path(federation_sync.__file__).read_text()
        self.assertIn("private='Content sync peer must use a private IP address'", source)
        for module in (federation_catalog, federation_sync, rss_subscription_sync, sync_fingerprint,
                       project_replication, federation_enrollment, federation_probe):
            self.assertFalse(hasattr(module, 'ipaddress'), module.__name__)


class TransportTests(unittest.TestCase):
    def test_deadline_connection_uses_the_address_family(self):
        self.assertEqual(DeadlineHTTPSConnection('fd00::1', 8443, context=None, timeout=1).family,
                         socket.AF_INET6)
        self.assertEqual(DeadlineHTTPSConnection('192.168.1.5', 8443, context=None, timeout=1).family,
                         socket.AF_INET)
        with self.assertRaises(ValueError):
            DeadlineHTTPSConnection('peer.example', 8443, context=None, timeout=1)

    def test_web_listener_family_and_bracketed_authority(self):
        server = WebServer(('::1', 0), ProbeHandler)
        self.addCleanup(server.server_close)
        self.assertEqual(server.socket.family, socket.AF_INET6)
        handler = object.__new__(ProbeHandler)
        handler.connection = SimpleNamespace(getsockname=lambda: ('::1', 8443, 0, 0))
        with patch('spikes.desktop_ui.DesktopHandler.setup'):
            ProbeHandler.setup(handler)
        self.assertEqual(handler.local_authority, '[::1]:8443')

    def test_web_server_validates_lan_and_bind_family(self):
        from spikes.web_server import make_server
        for bind, lan, message in (
                ('192.168.1.2', 'fd00::/64', 'same IP version'),
                ('fd00::2', '192.168.1.0/24', 'same IP version'),
                ('workspace.local', 'fd00::/64', 'literal IPv4 or IPv6 bind address'),
                ('fe80::1', 'fe80::/64', 'private LAN subnet'),
                ('8.8.8.8', '8.8.8.0/24', 'private LAN subnet')):
            with self.subTest(bind=bind, lan=lan):
                with self.assertRaisesRegex(ValueError, message):
                    make_server(bind, 0, lan, 'c', 'k', 't', 'n')

    def test_desktop_backend_accepts_ipv6_lan_address(self):
        backend = NetworkBackend(Path('/x/node.json'))
        base = dict(port=8443, cert='c', key='k', ca='a', enabled=False)
        backend.validate(dict(base, bind='fd00::5', lan='fd00::/64'))
        backend.validate(dict(base, bind='192.168.1.5', lan='192.168.1.0/24'))
        for bind, lan in (('::1', 'fd00::/64'), ('fe80::5', 'fe80::/64'), ('fd00::5', '192.168.1.0/24'),
                          ('fd01::5', 'fd00::/64'), (3232235781, '192.168.1.0/24')):
            with self.subTest(bind=bind, lan=lan):
                with self.assertRaisesRegex(ValueError, 'privátní IP adresu desktopu'):
                    backend.validate(dict(base, bind=bind, lan=lan))
        backend.config, backend.server = dict(base, bind='fd00::5'), object()
        self.assertEqual(backend.endpoint, 'https://[fd00::5]:8443')

    def test_address_candidates_offer_unique_local_ipv6(self):
        from spikes.deployment_targets import address_candidates
        interfaces = [{'addr_info': [{'local': value} for value in (
            '127.0.0.1', '192.168.1.5', '8.8.8.8', '::1', 'fe80::1', 'fd00::5', '2a00::5')]}]
        result = SimpleNamespace(stdout=json.dumps(interfaces).encode())
        with patch('spikes.deployment_targets.subprocess.run', return_value=result) as run:
            self.assertEqual(address_candidates(),
                             ['https://192.168.1.5:8443', 'https://[fd00::5]:8443'])
        self.assertNotIn('-4', run.call_args.args[0])


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
        peer = {'id': 'peer', 'endpoint': 'https://[fd00::5]:8443'}
        with patch.object(federation_catalog, 'Administration'), \
                patch.object(federation_catalog, 'prepare', return_value=({}, peer)), \
                patch.object(federation_catalog.ssl, 'create_default_context'), \
                patch.object(federation_catalog, 'DeadlineHTTPSConnection',
                             side_effect=RuntimeError('stop')) as connection:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                federation_catalog.synchronize(Path('/x'), 'peer', ca='/x/ca.pem')
        self.assertEqual(connection.call_args.args[0], 'fd00::5')
        self.assertEqual(connection.call_args.kwargs['timeout'], peer_transport.CATALOG_EXCHANGE_TIMEOUT)


if __name__ == '__main__':
    unittest.main()
