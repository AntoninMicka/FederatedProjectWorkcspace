# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exercise actual DNS processes, TLS and trickling provider responses."""
import http.client
import socket
import ssl
import time
import unittest
from unittest.mock import patch

from spikes.http_deadline import _Deadline
from spikes.provider_deadline import budget_connection, _addresses
from spikes.task_stream import RunDeadline
from tests import test_http_deadline as peers


class ProviderDeadlineTests(unittest.TestCase):
    peer = peers.HTTPDeadlineTests.peer

    @classmethod
    def setUpClass(cls):
        peers.HTTPDeadlineTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        peers.HTTPDeadlineTests.tearDownClass.__func__(cls)

    def connection(self, serve, seconds=.2):
        peer = self.peer(serve, budget=seconds)
        connection = budget_connection(http.client.HTTPSConnection(peer.host, peer.port,
            context=peer._context, timeout=seconds), seconds)
        self.addCleanup(connection.close)
        return connection

    def test_dns_child_is_killed_at_deadline(self):
        started = time.monotonic()
        with patch('spikes.provider_deadline._RESOLVE', 'import time; time.sleep(10)'), \
                self.assertRaises(TimeoutError):
            _addresses('provider.invalid', 443, _Deadline(.1))
        self.assertLess(time.monotonic()-started, 1)

    def test_cancel_interrupts_resolver_before_connect_limit(self):
        import threading
        control = RunDeadline(lambda value: None, soft=30)
        control.start(); self.addCleanup(control.close)
        timer = threading.Timer(.1, control.stop)
        timer.start(); self.addCleanup(timer.join)
        started = time.monotonic()
        with patch('spikes.provider_deadline._RESOLVE', 'import time; time.sleep(10)'), \
                self.assertRaises(TimeoutError):
            _addresses('provider.invalid', 443, control)
        self.assertLess(time.monotonic()-started, 1)
        self.assertEqual(control.reason, 'user-stopped')

    def test_dns_works_and_numeric_addresses_skip_process(self):
        rows = _addresses('localhost', 443, _Deadline(3))
        self.assertTrue(any(row[0] in (socket.AF_INET, socket.AF_INET6) for row in rows))
        with patch('spikes.provider_deadline.subprocess.Popen', side_effect=AssertionError('Unexpected DNS')):
            self.assertEqual(_addresses('127.0.0.1', 80, _Deadline(1))[0][-1], ('127.0.0.1', 80))

    def test_trickling_headers_and_body_obey_one_budget(self):
        for header in (False, True):
            def serve(conn, stop):
                data = b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n' if header else b'x'*100
                if not header:
                    conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n')
                for byte in data:
                    conn.sendall(bytes([byte]))
                    if stop.wait(.025): break
            with self.subTest(header=header):
                connection = self.connection(serve)
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    connection.request('GET', '/')
                    connection.getresponse().read()
                connection.close()
                self.assertLess(time.monotonic()-started, 1)

    def test_http10_response_is_closed_by_connection_owner(self):
        connection = self.connection(lambda conn, stop: conn.sendall(
            b'HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\nhello'), seconds=2)
        connection.request('GET', '/')
        response = connection.getresponse()
        self.assertEqual(response.read(2), b'he')
        connection.close()
        self.assertTrue(response.isclosed())

    def test_tls_verifies_original_hostname_before_dispatch(self):
        connection = self.connection(lambda conn, stop: self.fail('Untrusted TLS request reached peer'))
        connection.host = 'provider.invalid'
        with patch('spikes.provider_deadline._addresses', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 0, ('127.0.0.1', connection.port))]), \
                self.assertRaises(ssl.SSLCertVerificationError):
            connection.request('GET', '/')

    def test_explicit_run_extension_updates_absolute_transport_budget(self):
        now = [0]
        control = RunDeadline(lambda value: None, soft=10, clock=lambda: now[0])
        control.started = 0
        self.addCleanup(control.close)
        now[0] = 19
        self.assertEqual(control.remaining(), 1)
        control.extend(); self.assertEqual(control.remaining(), 81)
        now[0] = 100
        with self.assertRaises(TimeoutError): control.remaining()
        self.assertEqual(control.reason, 'hard-timeout')
