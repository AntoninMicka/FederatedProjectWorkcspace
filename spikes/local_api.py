"""M0 transport comparison, not an application server. Linux only; no persistence."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
from socketserver import UnixStreamServer
import stat
import struct
import tempfile
import threading

from spikes.metadata import parse_json, ValidationError

MAX_BODY = 4096


class Handler(BaseHTTPRequestHandler):
    # One request per connection; never accept pipelined mutations.
    protocol_version = 'HTTP/1.0'

    def setup(self):
        self.request.settimeout(1)
        super().setup()

    def log_message(self, *args):
        pass  # Do not log request URLs, headers, tokens or payloads.

    def reply(self, code, payload):
        data = json.dumps(payload).encode()
        self.close_connection = True
        self.send_response_only(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error': 'request rejected'})

    def single(self, name):
        values = self.headers.get_all(name, [])
        return values[0] if len(values) == 1 else None

    def do_POST(self):
        if self.single('Host') != self.server.authority:
            return self.send_error(403)
        origin = self.headers.get_all('Origin', [])
        # Missing Origin is reserved for token-authenticated native clients.
        # null/file origins and foreign browser origins are not accepted.
        if origin and origin != [self.server.origin]:
            return self.send_error(403)
        auth = self.single('Authorization') or ''
        if not hmac.compare_digest(auth.encode('utf-8'),
                                   ('Bearer ' + self.server.token).encode()):
            return self.send_error(401)
        if self.headers.get_all('Sec-Fetch-Site', []) not in ([], ['same-origin'], ['none']):
            return self.send_error(403)
        if self.path != '/v1/counter':
            return self.send_error(404)
        # JSON + non-ambient Authorization + no CORS is the CSRF contract.
        if self.single('Content-Type') != 'application/json':
            return self.send_error(415)
        if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect'):
            return self.send_error(400)
        length = self.single('Content-Length')
        if length is None or not length.isascii() or not length.isdecimal():
            return self.send_error(400)
        if len(length) > 4 or not 0 < int(length) <= MAX_BODY:
            return self.send_error(413)
        try:
            body = self.rfile.read(int(length))
            if len(body) != int(length):
                return self.send_error(400)
            request = parse_json(body)
            if request != {'action': 'increment'}:
                return self.send_error(400)
        except (ValidationError, UnicodeError, ValueError):
            return self.send_error(400)
        self.server.counter += 1
        self.reply(200, {'value': self.server.counter})

    def do_GET(self):
        self.send_error(405)

    do_HEAD = do_GET
    do_OPTIONS = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET


class UnixAPI(UnixStreamServer):
    def verify_request(self, request, client_address):
        _, uid, _ = struct.unpack('3i', request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return uid == self.allowed_uid


def private_directory(path):
    """Validate caller-owned runtime parent; no chmod of somebody else's directory."""
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('runtime directory must be owned by this user with mode 0700')
    if path.absolute() != path.resolve():
        raise ValueError('runtime directory must not contain symlinks')
    return path


@contextmanager
def running_api(transport, runtime=None):
    """Yield in-process endpoint/token to test driver; no token file or public bootstrap."""
    directory = None
    if transport == 'unix':
        parent = private_directory(runtime)
        directory = tempfile.TemporaryDirectory(prefix='api-', dir=parent)
        endpoint = str(Path(directory.name) / 'api.sock')
        try:
            server = UnixAPI(endpoint, Handler)
            os.chmod(endpoint, 0o600)
        except BaseException:
            directory.cleanup()
            raise
        server.allowed_uid = os.getuid()
        server.authority = 'workspace.local'
    elif transport == 'http':
        server = HTTPServer(('127.0.0.1', 0), Handler)
        server.authority = f'127.0.0.1:{server.server_port}'
    else:
        raise ValueError('unknown transport')
    server.origin = 'http://' + server.authority
    server.token = secrets.token_urlsafe(32)
    server.counter = 0
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        server.token = ''
        if directory:
            directory.cleanup()
