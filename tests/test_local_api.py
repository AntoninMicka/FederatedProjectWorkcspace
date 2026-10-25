# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Real loopback and Unix sockets; no internet, credentials, Git or LLM calls."""
from contextlib import contextmanager, redirect_stderr
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from spikes.local_api import Handler, MAX_BODY, private_directory, running_api


class LocalAPITests(unittest.TestCase):
    @contextmanager
    def servers(self):
        with tempfile.TemporaryDirectory() as runtime:
            with running_api('unix', runtime) as unix, running_api('http') as http:
                yield unix, http

    def connect(self, server):
        if isinstance(server.server_address, str):
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(3)
            client.connect(server.server_address)
            return client
        return socket.create_connection(server.server_address, timeout=3)

    def request(self, server, *, method='POST', path='/v1/counter', headers=None,
                body=b'{"action":"increment"}', extra=(), raw=None):
        fields = {'Host': server.authority, 'Authorization': 'Bearer ' + server.token,
                  'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        for key, value in (headers or {}).items():
            if value is None:
                fields.pop(key, None)
            else:
                fields[key] = value
        message = (f'{method} {path} HTTP/1.1\r\n' +
                   ''.join(f'{k}: {v}\r\n' for k, v in [*fields.items(), *extra]) + '\r\n').encode() + body
        with self.connect(server) as client:
            client.sendall(message if raw is None else raw)
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while data := client.recv(65536):
                chunks.append(data)
        return b''.join(chunks)

    def rejected(self, server, **kwargs):
        previous = server.counter
        response = self.request(server, **kwargs)
        self.assertTrue(response.startswith(b'HTTP/1.0 4'), response[:80])
        self.assertEqual(server.counter, previous)
        self.assertNotIn(b'Access-Control-Allow-Origin', response)
        self.assertNotIn(server.token.encode(), response)

    def test_exact_telemetry_status_completes_beside_application_request(self):
        entered = threading.Event()
        release = threading.Event()

        class LaneHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/block',
                                                '/v1/node-telemetry/status'}

            def dispatch(self, request):
                if self.path == '/v1/block':
                    entered.set()
                    if not release.wait(3):
                        return self.reply(504, {'error': 'test timeout'})
                    return self.reply(200, {'released': True})
                if self.path == '/v1/node-telemetry/status':
                    return self.reply(200, {'monitor': 'available'})
                return super().dispatch(request)

        with running_api('http', handler=LaneHandler) as server:
            result = {}
            blocked = threading.Thread(target=lambda: result.setdefault(
                'response', self.request(server, path='/v1/block', body=b'{}')))
            blocked.start()
            try:
                self.assertTrue(entered.wait(1))
                response = self.request(server, path='/v1/node-telemetry/status',
                                        body=b'{}')
                head, body = response.split(b'\r\n\r\n', 1)
                self.assertIn(b' 200 ', head)
                self.assertEqual({'monitor': 'available'}, json.loads(body))
            finally:
                release.set()
                blocked.join(3)
            self.assertFalse(blocked.is_alive())
            self.assertIn(b' 200 ', result['response'].split(b'\r\n', 1)[0])

    def test_concurrent_write_is_rejected_before_dispatch(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/block'}

            def dispatch(self, request):
                if self.path == '/v1/block':
                    entered.set()
                    if not release.wait(2):
                        return self.reply(504, {'error': 'test timeout'})
                    return self.reply(200, {'released': True})
                return super().dispatch(request)

        with running_api('http', handler=BlockingHandler,
                         lane_timeout=0.05) as server:
            blocked = threading.Thread(target=lambda: self.request(
                server, path='/v1/block', body=b'{}'))
            blocked.start()
            try:
                self.assertTrue(entered.wait(1))
                response = self.request(server)
                self.assertIn(b' 503 ', response.split(b'\r\n', 1)[0])
                self.assertEqual(server.counter, 0)
            finally:
                release.set()
                blocked.join(2)
            self.assertFalse(blocked.is_alive())

    def test_four_worker_limit_rejects_excess_connection_without_new_thread(self):
        application_entered = threading.Event()
        telemetry_entered = threading.Event()
        release = threading.Event()

        class SaturatingHandler(Handler):
            post_paths = Handler.post_paths | {
                '/v1/block', '/v1/node-telemetry/status'}

            def dispatch(self, request):
                if self.path == '/v1/block':
                    application_entered.set()
                    release.wait(3)
                    return self.reply(200, {'released': True})
                if self.path == '/v1/node-telemetry/status':
                    telemetry_entered.set()
                    release.wait(3)
                    return self.reply(200, {'released': True})
                return super().dispatch(request)

        responses = []
        with running_api('http', handler=SaturatingHandler,
                         lane_timeout=2) as server:
            def request(path):
                try:
                    responses.append(self.request(server, path=path, body=b'{}'))
                except OSError:
                    responses.append(b'')

            clients = [threading.Thread(target=request, args=(path,)) for path in (
                '/v1/block', '/v1/node-telemetry/status', '/v1/counter',
                '/v1/counter')]
            for client in clients[:2]:
                client.start()
            self.assertTrue(application_entered.wait(1))
            self.assertTrue(telemetry_entered.wait(1))
            for client in clients[2:]:
                client.start()
            deadline = time.monotonic() + 1
            while server.active_worker_count() != 4 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(server.active_worker_count(), 4)
            excess = self.request(server, path='/v1/counter', body=b'{}')
            self.assertEqual(excess, b'')
            self.assertEqual(server.active_worker_count(), 4)
            release.set()
            for client in clients:
                client.join(3)
            self.assertTrue(all(not client.is_alive() for client in clients))
            self.assertEqual(len(responses), 4)

    def test_clean_shutdown_waits_for_owned_request(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/block'}

            def dispatch(self, request):
                entered.set()
                release.wait(2)
                return self.reply(200, {'released': True})

        manager = running_api('http', handler=BlockingHandler,
                              shutdown_timeout=0.5)
        server = manager.__enter__()
        client = threading.Thread(target=lambda: self.request(
            server, path='/v1/block', body=b'{}'))
        client.start()
        self.assertTrue(entered.wait(1))
        releaser = threading.Timer(0.1, release.set)
        releaser.start()
        started = time.monotonic()
        manager.__exit__(None, None, None)
        elapsed = time.monotonic() - started
        client.join(1)
        releaser.join(1)
        self.assertTrue(server.shutdown_clean)
        self.assertFalse(client.is_alive())
        self.assertGreaterEqual(elapsed, 0.08)

    def test_shutdown_deadline_closes_client_and_returns_as_crash_boundary(self):
        entered = threading.Event()
        release = threading.Event()
        client_finished = threading.Event()

        class BlockingHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/block'}

            def dispatch(self, request):
                entered.set()
                release.wait(2)
                try:
                    return self.reply(200, {'released': True})
                except OSError:
                    return None

        manager = running_api('http', handler=BlockingHandler,
                              shutdown_timeout=0.05)
        server = manager.__enter__()
        def request():
            try:
                self.request(server, path='/v1/block', body=b'{}')
            except OSError:
                pass
            finally:
                client_finished.set()
        client = threading.Thread(target=request)
        client.start()
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        manager.__exit__(None, None, None)
        elapsed = time.monotonic() - started
        self.assertFalse(server.shutdown_clean)
        self.assertLess(elapsed, 0.5)
        self.assertTrue(client_finished.wait(1))
        release.set()
        client.join(1)
        self.assertFalse(client.is_alive())
        deadline = time.monotonic() + 1
        while server.active_worker_count() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(server.active_worker_count(), 0)

    def test_same_contract_and_bind_permissions(self):
        with self.servers() as servers:
            unix, http = servers
            self.assertEqual(http.server_address[0], '127.0.0.1')
            self.assertEqual(Path(unix.server_address).stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(unix.server_address).parent.stat().st_mode & 0o777, 0o700)
            for server in servers:
                for value, headers in [(1, {}), (2, {'Origin': server.origin, 'Sec-Fetch-Site': 'same-origin'})]:
                    response = self.request(server, headers=headers)
                    head, body = response.split(b'\r\n\r\n', 1)
                    self.assertIn(b' 200 ', head)
                    self.assertIn(b'Cache-Control: no-store', head)
                    self.assertEqual(json.loads(body), {'value': value})
            socket_path = Path(unix.server_address)
        self.assertFalse(socket_path.exists())

    def test_authentication_cannot_be_replaced_by_origin_cookie_or_query(self):
        with self.servers() as servers:
            for server in servers:
                for auth in (None, '', 'Bearer wrong', 'Basic test', 'Bearer é'):
                    self.rejected(server, headers={'Authorization': auth, 'Origin': server.origin})
                self.rejected(server, headers={'Authorization': None, 'Cookie': 'token=' + server.token})
                self.rejected(server, path='/v1/counter?token=' + server.token, headers={'Authorization': None})
                self.rejected(server, extra=[('Authorization', 'Bearer ' + server.token)])

    def test_host_origin_csrf_and_methods(self):
        with self.servers() as servers:
            for server in servers:
                for host in (None, 'evil.example', 'localhost', server.authority + '.evil'):
                    self.rejected(server, headers={'Host': host})
                for origin in ('null', 'file://', 'https://evil.example', server.origin + '.evil', server.origin + '/'):
                    self.rejected(server, headers={'Origin': origin})
                for name, value in [('Host', server.authority), ('Origin', server.origin)]:
                    self.rejected(server, headers={name: value}, extra=[(name, value)])
                for site in ('cross-site', 'same-site'):
                    self.rejected(server, headers={'Sec-Fetch-Site': site})
                for kind in ('text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data'):
                    self.rejected(server, headers={'Content-Type': kind})
                for method in ('GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE'):
                    self.rejected(server, method=method)
                self.rejected(server, path='http://' + server.authority + '/v1/counter')
                self.rejected(server, path='/v1/counter?x=1')

    def test_framing_schema_limits_and_no_payload_logging(self):
        capture = io.StringIO()
        with redirect_stderr(capture), self.servers() as servers:
            for server in servers:
                for body in (b'{}', b'[]', b'invalid', b'{"action":"increment","action":"increment"}',
                             b'{"action":"increment","extra":1}', b'\xff', b'x' * (MAX_BODY + 1)):
                    self.rejected(server, body=body)
                for length in (None, '-1', 'no', '99999999999999999999', '4000'):
                    self.rejected(server, headers={'Content-Length': length})
                for key, value in [('Content-Length', '22'), ('Content-Type', 'application/json')]:
                    self.rejected(server, extra=[(key, value)])
                self.rejected(server, headers={'Transfer-Encoding': 'chunked'})
                self.rejected(server, headers={'Expect': '100-continue'})
        self.assertEqual(capture.getvalue(), '')

    def test_restart_rotates_token_and_resets_only_volatile_state(self):
        with tempfile.TemporaryDirectory() as runtime:
            for transport in ('unix', 'http'):
                with running_api(transport, runtime) as server:
                    old_token = server.token
                    self.assertIn(b' 200 ', self.request(server))
                with running_api(transport, runtime) as server:
                    self.assertNotEqual(server.token, old_token)
                    self.rejected(server, headers={'Authorization': 'Bearer ' + old_token})
                    self.assertEqual(server.counter, 0)
                    self.assertIn(b' 200 ', self.request(server))

    def test_unix_peer_uid_and_runtime_validation(self):
        with tempfile.TemporaryDirectory() as runtime:
            root = Path(runtime)
            with running_api('unix', root) as server:
                # Real kernel SO_PEERCRED compared against deliberately mismatched policy.
                # A separate-user process is not impersonated by this test.
                server.allowed_uid = os.getuid() + 1
                with self.connect(server) as client:
                    self.assertEqual(client.recv(1), b'')
                self.assertEqual(server.counter, 0)
            link = root / 'link'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                private_directory(link)
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                with running_api('unix', root):
                    self.fail('unsafe parent accepted')
            root.chmod(0o700)

    def test_stalled_client_and_pipeline_do_not_mutate_twice(self):
        with self.servers() as servers:
            for server in servers:
                with self.connect(server) as client:
                    client.sendall(b'POST /v1/counter HTTP/1.1\r\n')
                    # Server closes the stalled connection after its read timeout.
                    self.assertEqual(client.recv(1), b'')
                self.assertEqual(server.counter, 0)
                body = b'{"action":"increment"}'
                message = (f'POST /v1/counter HTTP/1.1\r\nHost: {server.authority}\r\n'
                           f'Authorization: Bearer {server.token}\r\n'
                           f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
                response = self.request(server, raw=message + message)
                self.assertIn(b' 200 ', response)
                self.assertEqual(server.counter, 1)
