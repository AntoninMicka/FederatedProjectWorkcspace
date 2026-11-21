# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import socket
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from spikes.http_deadline import DeadlineHTTPSConnection
from spikes.network_backend import NetworkBackend


class HTTPDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.tls = NetworkBackend(Path(cls.temp.name) / 'node.json').generate(
            '127.0.0.1', 8443, '127.0.0.0/8')
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(cls.tls['cert'], cls.tls['key'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def peer(self, serve, *, handshake=True, budget=.35):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen()
        listener.settimeout(2)
        stop = threading.Event()
        errors = []

        def run():
            try:
                with listener.accept()[0] as raw:
                    raw.settimeout(2)
                    if not handshake:
                        stop.wait(2)
                        return
                    with self.server_context.wrap_socket(raw, server_side=True) as conn:
                        header = b''
                        while b'\r\n\r\n' not in header:
                            chunk = conn.recv(1)
                            if not chunk:
                                return
                            header += chunk
                        serve(conn, stop)
            except OSError:
                pass  # Expected when the deadline closes the peer connection.
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run, daemon=True); thread.start()
        def cleanup():
            stop.set(); listener.close(); thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        self.addCleanup(cleanup)
        context = ssl.create_default_context(cafile=self.tls['ca'])
        connection = DeadlineHTTPSConnection('127.0.0.1', listener.getsockname()[1],
                                            context=context, timeout=budget)
        self.addCleanup(connection.close)
        return connection

    def test_http10_body_survives_connection_auto_close(self):
        connection = self.peer(lambda conn, stop: conn.sendall(
            b'HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\nhello'), budget=2)
        connection.request('GET', '/')
        response = connection.getresponse()
        with response:
            self.assertEqual(response.read(), b'hello')
        connection.check_deadline()

    def assert_bounded(self, connection, body=None):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            connection.request('POST' if body else 'GET', '/', body=body)
            with connection.getresponse() as response:
                response.read()
            connection.check_deadline()
        self.assertLess(time.monotonic() - start, 1.5)

    def test_extended_deadline_follows_liveness_frames_after_http10_head(self):
        # A streaming peer keeps an HTTP/1.0 response alive past the original
        # budget as long as every frame arrives within the idle limit.
        def serve(conn, stop):
            conn.sendall(b'HTTP/1.0 200 OK\r\n\r\n')
            for _ in range(8):
                conn.sendall(b'beat\n')
                if stop.wait(.1):
                    return
            conn.sendall(b'done\n')
        connection = self.peer(serve, budget=.35)
        connection.request('GET', '/')
        response = connection.getresponse()
        self.assertIsNone(connection.sock)  # detached by http.client for HTTP/1.0
        self.assertTrue(connection.connected)
        connection.extend_deadline(5, idle=.3)
        with response:
            lines = [response.readline() for _ in range(9)]
        self.assertEqual(lines[-1], b'done\n')
        connection.check_deadline()

    def test_extended_deadline_still_ends_a_silent_peer(self):
        def serve(conn, stop):
            conn.sendall(b'HTTP/1.0 200 OK\r\n\r\nbeat\n')
            stop.wait(2)
        connection = self.peer(serve, budget=1)
        connection.request('GET', '/')
        response = connection.getresponse()
        connection.extend_deadline(5, idle=.2)
        start = time.monotonic()
        with response, self.assertRaises(TimeoutError):
            self.assertEqual(response.readline(), b'beat\n')
            response.readline()
        self.assertLess(time.monotonic() - start, 1)

    def test_extending_requires_a_connection_and_a_valid_idle_budget(self):
        connection = DeadlineHTTPSConnection('127.0.0.1', 9, context=ssl.create_default_context(),
                                            timeout=1)
        self.assertFalse(connection.connected)
        with self.assertRaisesRegex(ValueError, 'unconnected'):
            connection.extend_deadline(5, idle=1)

    def test_trickling_headers_cannot_extend_budget(self):
        def serve(conn, stop):
            for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n':
                conn.sendall(bytes([byte]))
                if stop.wait(.025):
                    break
        self.assert_bounded(self.peer(serve))

    def test_trickling_fixed_and_chunked_bodies_cannot_extend_budget(self):
        for chunked in (False, True):
            with self.subTest(chunked=chunked):
                def serve(conn, stop):
                    conn.sendall(b'HTTP/1.1 200 OK\r\n' + (
                        b'Transfer-Encoding: chunked' if chunked else b'Content-Length: 100') + b'\r\n\r\n')
                    for _ in range(100):
                        conn.sendall(b'1\r\nx\r\n' if chunked else b'x')
                        if stop.wait(.025):
                            break
                self.assert_bounded(self.peer(serve))

    def test_tls_handshake_is_bounded(self):
        self.assert_bounded(self.peer(lambda *_: None, handshake=False))

    def test_stalled_upload_is_bounded(self):
        self.assert_bounded(self.peer(lambda conn, stop: stop.wait(2)), b'x' * (16 * 1024 * 1024))

    def test_tls_trust_is_still_checked(self):
        connection = self.peer(lambda *_: None)
        connection._context = ssl.create_default_context()
        with self.assertRaises(ssl.SSLCertVerificationError):
            connection.request('GET', '/')

    def test_tls_peer_address_is_still_verified(self):
        connection = self.peer(lambda *_: None)
        connection.host = '127.0.0.2'  # Connect to .1, require the wrong SAN.
        with self.assertRaises(ssl.SSLCertVerificationError):
            connection.request('GET', '/')

    def test_connect_and_handshake_share_budget(self):
        clock = [10.0]
        raw = unittest.mock.Mock()
        tls = unittest.mock.Mock()
        raw.connect.side_effect = lambda *_: clock.__setitem__(0, clock[0] + .06)
        tls.do_handshake.side_effect = lambda: clock.__setitem__(0, clock[0] + .03)
        context = ssl.create_default_context()
        with patch('spikes.http_deadline.time.monotonic', side_effect=lambda: clock[0]), \
                patch('spikes.http_deadline.socket.socket', return_value=raw), \
                patch.object(context, 'wrap_socket', return_value=tls):
            connection = DeadlineHTTPSConnection('127.0.0.1', context=context, timeout=.1)
            connection.connect()
            self.assertAlmostEqual(raw.settimeout.call_args.args[0], .1)
            self.assertAlmostEqual(tls.settimeout.call_args.args[0], .04)
            clock[0] += .02
            with self.assertRaises(TimeoutError):
                connection.check_deadline()
            connection.close()

    def test_hostnames_and_invalid_budgets_are_rejected(self):
        context = ssl.create_default_context()
        with self.assertRaises(ValueError):
            DeadlineHTTPSConnection('example.invalid', context=context, timeout=1)
        for budget in (True, 0, -1, float('inf'), float('nan')):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                DeadlineHTTPSConnection('127.0.0.1', context=context, timeout=budget)
