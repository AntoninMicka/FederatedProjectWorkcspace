"""Real loopback and Unix sockets; no internet, credentials, Git or LLM calls."""
from contextlib import contextmanager, redirect_stderr
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest

from spikes.local_api import MAX_BODY, private_directory, running_api


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
