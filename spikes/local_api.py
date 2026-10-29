# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""M0 transport comparison, not an application server. Linux only; no persistence."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
from socketserver import ThreadingMixIn, UnixStreamServer
import stat
import struct
import tempfile
import threading

from spikes.metadata import parse_json, ValidationError

MAX_BODY = 4096
MAX_HTTP_WORKERS = 4
REQUEST_LANE_TIMEOUT = 2
SHUTDOWN_GRACE_SECONDS = 225


class BoundedHTTPServer(ThreadingMixIn, HTTPServer):
    """Bounded HTTP workers; handlers retain one socket and response owner."""
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address, handler, *, max_workers=MAX_HTTP_WORKERS,
                 lane_timeout=REQUEST_LANE_TIMEOUT,
                 shutdown_timeout=SHUTDOWN_GRACE_SECONDS):
        if type(max_workers) is not int or max_workers < 2:
            raise ValueError('HTTP server requires at least two bounded workers')
        if not isinstance(lane_timeout, (int, float)) or lane_timeout <= 0:
            raise ValueError('Request lane timeout must be positive')
        if not isinstance(shutdown_timeout, (int, float)) or shutdown_timeout <= 0:
            raise ValueError('Shutdown timeout must be positive')
        self._worker_slots = threading.BoundedSemaphore(max_workers)
        self.application_lane = threading.Lock()
        self.telemetry_lane = threading.Lock()
        self.request_lane_timeout = lane_timeout
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_clean = None
        self._worker_condition = threading.Condition()
        self._active_requests = set()
        self._admission_open = True
        super().__init__(server_address, handler)

    def process_request(self, request, client_address):
        with self._worker_condition:
            if not self._admission_open:
                self.shutdown_request(request)
                return
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._worker_condition:
            if not self._admission_open:
                self._worker_slots.release()
                self.shutdown_request(request)
                return
            self._active_requests.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self._worker_condition:
                self._active_requests.discard(request)
                self._worker_condition.notify_all()
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._worker_condition:
                self._active_requests.discard(request)
                self._worker_condition.notify_all()
            self._worker_slots.release()

    def active_worker_count(self):
        with self._worker_condition:
            return len(self._active_requests)

    def shutdown(self):
        with self._worker_condition:
            self._admission_open = False
        return super().shutdown()

    def server_close(self):
        with self._worker_condition:
            self._admission_open = False
            clean = self._worker_condition.wait_for(
                lambda: not self._active_requests,
                timeout=self.shutdown_timeout)
            active = tuple(self._active_requests)
        self.shutdown_clean = clean
        if not clean:
            for request in active:
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    request.close()
                except OSError:
                    pass
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    # One request per connection; never accept pipelined mutations.
    protocol_version = 'HTTP/1.0'
    max_body = MAX_BODY

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
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # The browser can close an in-flight request while a page/profile
            # is shutting down. The response has no durable effect to recover.
            self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error': 'request rejected'})

    def single(self, name):
        values = self.headers.get_all(name, [])
        return values[0] if len(values) == 1 else None

    post_paths = {'/v1/counter'}

    def authorized(self, auth):
        return hmac.compare_digest(auth.encode('utf-8'),
                                   ('Bearer ' + self.server.token).encode())

    def request_authority(self):
        authority = self.single('Host')
        return authority if authority == self.server.authority else None

    def request_origin(self, authority):
        return self.server.origin if authority == self.server.authority else None

    def dispatch(self, request):
        if request != {'action': 'increment'}:
            return self.send_error(400)
        self.server.counter += 1
        self.reply(200, {'value': self.server.counter})

    def _in_request_lane(self, operation, *, telemetry=False):
        lane = getattr(self.server,
                       'telemetry_lane' if telemetry else 'application_lane', None)
        if lane is None:
            # Small unit fixtures may compose this handler with an already
            # sequential HTTPServer; only BoundedHTTPServer enables concurrency.
            return operation()
        if not lane.acquire(timeout=self.server.request_lane_timeout):
            return self.reply(503, {'error': 'server busy'})
        try:
            return operation()
        finally:
            lane.release()

    def do_POST(self):
        return self._in_request_lane(
            self._do_POST,
            telemetry=self.path == '/v1/node-telemetry/status')

    def _do_POST(self):
        authority = self.request_authority()
        if authority is None:
            return self.send_error(403)
        origin = self.headers.get_all('Origin', [])
        # Missing Origin is reserved for token-authenticated native clients.
        # null/file origins and foreign browser origins are not accepted.
        if origin and origin != [self.request_origin(authority)]:
            return self.send_error(403)
        auth = self.single('Authorization') or ''
        if not self.authorized(auth):
            return self.send_error(401)
        if self.headers.get_all('Sec-Fetch-Site', []) not in ([], ['same-origin'], ['none']):
            return self.send_error(403)
        if self.path not in self.post_paths:
            return self.send_error(404)
        # JSON + non-ambient Authorization + no CORS is the CSRF contract.
        if self.single('Content-Type') != 'application/json':
            return self.send_error(415)
        if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect'):
            return self.send_error(400)
        length = self.single('Content-Length')
        if length is None or not length.isascii() or not length.isdecimal():
            return self.send_error(400)
        if len(length) > len(str(self.max_body)) or not 0 < int(length) <= self.max_body:
            return self.send_error(413)
        try:
            body = self.rfile.read(int(length))
            if len(body) != int(length):
                return self.send_error(400)
            request = parse_json(body, self.max_body)
        except (ValidationError, UnicodeError, ValueError):
            return self.send_error(400)
        self.dispatch(request)

    def do_GET(self):
        return self._in_request_lane(self._do_GET)

    def _do_GET(self):
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
def running_api(transport, runtime=None, *, handler=Handler, projects=None,
                max_workers=MAX_HTTP_WORKERS, lane_timeout=REQUEST_LANE_TIMEOUT,
                shutdown_timeout=SHUTDOWN_GRACE_SECONDS):
    """Yield in-process endpoint/token to test driver; no token file or public bootstrap."""
    directory = None
    if transport == 'unix':
        parent = private_directory(runtime)
        directory = tempfile.TemporaryDirectory(prefix='api-', dir=parent)
        endpoint = str(Path(directory.name) / 'api.sock')
        try:
            server = UnixAPI(endpoint, handler)
            os.chmod(endpoint, 0o600)
        except BaseException:
            directory.cleanup()
            raise
        server.allowed_uid = os.getuid()
        server.authority = 'workspace.local'
        server.application_lane = threading.Lock()
        server.telemetry_lane = threading.Lock()
        server.request_lane_timeout = REQUEST_LANE_TIMEOUT
    elif transport == 'http':
        server = BoundedHTTPServer(('127.0.0.1', 0), handler,
            max_workers=max_workers, lane_timeout=lane_timeout,
            shutdown_timeout=shutdown_timeout)
        server.authority = f'127.0.0.1:{server.server_port}'
    else:
        raise ValueError('unknown transport')
    server.origin = 'http://' + server.authority
    server.token = secrets.token_urlsafe(32)
    server.counter = 0
    server.projects = projects
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
