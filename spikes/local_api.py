# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""M0 transport comparison, not an application server. Linux only; no persistence."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import gzip
import json
import logging
import os
from pathlib import Path
import secrets
import socket
from socketserver import ThreadingMixIn, UnixStreamServer
import stat
import struct
import tempfile
import threading
import time

from spikes.http_request_budget import RequestReadTimeout, request_reader
from spikes.http_ingress import HeaderAdmission
from spikes.backend_availability import BackendAvailability
from spikes.http_admission_policy import LANES, ROUTE_LANES, PROJECT_ROUTES, PROJECT_READ_ROUTES, RESERVED_ROUTES, ACTION_LANES, DIAGNOSTIC_ACTIONS, STREAM_ROUTES, SERVICE_ROUTES, request_lane
from spikes.request_ownership import BoundedWaitingLane, ConcurrentReadLane, ProjectLanes, ProjectBusy, bounded_project_requests

from spikes.metadata import parse_json, ValidationError


def _accepts_project_gzip(headers):
    accepted = False
    for line in headers.get_all('Accept-Encoding', []):
        for item in line.split(','):
            parts = [part.strip().lower() for part in item.split(';')]
            if parts[0] != 'gzip':
                continue
            quality = 1.0
            try:
                for parameter in parts[1:]:
                    if parameter.startswith('q='):
                        quality = float(parameter[2:])
            except ValueError:
                continue
            if quality == 0:
                return False
            accepted = accepted or 0 < quality <= 1
    return accepted

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
        reserve_ui = bool(getattr(handler, 'reserve_ui_worker', False))
        self.worker_limit = max_workers + int(reserve_ui)
        self.post_slots = threading.BoundedSemaphore(max_workers) if reserve_ui else None
        self._worker_slots = threading.BoundedSemaphore(max_workers + int(reserve_ui))
        self._ordinary_worker_slots = threading.BoundedSemaphore(max_workers)
        for name in LANES:
            setattr(self, name + '_lane', threading.Lock())
        # One queued IDE operation absorbs ordinary cross-client overlap.
        # Never let multiple waiting requests consume the entire worker pool.
        self.ide_queue_lane = BoundedWaitingLane()
        # Discovery only reads committed snapshots and native shared checkpoints.
        # Keep one ordinary worker available even in a minimum-size pool.
        self.ide_status_lane = ConcurrentReadLane(max_workers - 1)
        self.project_read_lane = ConcurrentReadLane(max_workers - 1)
        self.backend_availability = BackendAvailability()
        self.project_lanes = ProjectLanes()
        self.request_lane_timeout = lane_timeout
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_clean = None
        self._worker_condition = threading.Condition()
        self._active_requests = set()
        self._request_details = {}
        self._admission_rejections = 0
        self._admission_open = True
        super().__init__(server_address, handler)
        self.header_admission = HeaderAdmission(self._dispatch_ready_request, self._reject_request,
            seconds=getattr(handler, 'request_read_seconds', 60),
            static_paths=getattr(handler, 'assets', {}))

    def process_request(self, request, client_address):
        with self._worker_condition:
            if not self._admission_open:
                self.shutdown_request(request)
                return
        self.header_admission.add(request, client_address)

    def _reject_request(self, request, *, code=503):
        with self._worker_condition:
            self._admission_rejections += 1
        payload = b'{"error":"server busy"}' if code == 503 else b'{"error":"request rejected"}'
        try:
            request.settimeout(.1)
            request.sendall(('HTTP/1.0 '+str(code)+' Request Rejected\r\n').encode() +
                b'Content-Type: application/json\r\nContent-Length: '+str(len(payload)).encode()+
                b'\r\nCache-Control: no-store\r\nRetry-After: 1\r\nConnection: close\r\n\r\n'+payload)
        except OSError:
            pass
        self.shutdown_request(request)

    def _dispatch_ready_request(self, request, client_address, reserved):
        with self._worker_condition:
            if not self._admission_open:
                self.shutdown_request(request)
                return
        ordinary = not reserved
        if ordinary and not self._ordinary_worker_slots.acquire(blocking=False):
            return self._reject_request(request)
        if not self._worker_slots.acquire(blocking=False):
            if ordinary:
                self._ordinary_worker_slots.release()
            logging.getLogger(__name__).warning(
                'http_admission_rejected reason=worker_limit requests=%s',
                self.http_diagnostics()['requests'])
            # No handler, authentication or dispatch ran. Give fetch a bounded
            # HTTP failure rather than an unexplained closed connection.
            return self._reject_request(request)
        with self._worker_condition:
            if not self._admission_open:
                self._worker_slots.release()
                if ordinary:
                    self._ordinary_worker_slots.release()
                self.shutdown_request(request)
                return
            self._active_requests.add(request)
            self._request_details[request] = {'kind': 'headers', 'stage': 'reading',
                                              'started': time.monotonic(), 'ordinary': ordinary}
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self._worker_condition:
                self._active_requests.discard(request)
                self._request_details.pop(request, None)
                self._worker_condition.notify_all()
            self._worker_slots.release()
            if ordinary:
                self._ordinary_worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._worker_condition:
                self._active_requests.discard(request)
                item = self._request_details.pop(request, {})
                self._worker_condition.notify_all()
            self._worker_slots.release()
            if item.get('ordinary'):
                self._ordinary_worker_slots.release()

    def active_worker_count(self):
        with self._worker_condition:
            return len(self._active_requests)

    def http_diagnostics(self):
        with self._worker_condition:
            active = [{'kind': item['kind'], 'stage': item['stage'],
                       'operation': item.get('operation', 'unclassified'),
                       **({'action': item['action']} if 'action' in item else {}),
                       **({'project_id': item['project_id']} if 'project_id' in item else {}),
                       'elapsed_ms': round((time.monotonic() - item['started']) * 1000)}
                      for item in self._request_details.values()]
            rejected = self._admission_rejections
        return {'active_workers': self.active_worker_count(),
                'pending_headers': self.header_admission.count(),
                'worker_limit': self.worker_limit,
                'admission_rejections': rejected,
                'requests': active,
                'ui_capacity_reserved': self.post_slots is not None,
                'lanes_busy': {name + '_lane': getattr(self, name + '_lane').locked()
                               for name in LANES}}

    def describe_request(self, request, kind, stage, operation=None, project_id=None):
        with self._worker_condition:
            item = self._request_details.get(request)
            if item is not None:
                item.update(kind=kind, stage=stage)
                if operation is not None:
                    item['operation'] = operation
                if project_id is not None:
                    item['project_id'] = project_id

    def describe_request_action(self, request, path, body):
        action = body.get('action') if isinstance(body, dict) else None
        if not isinstance(action, str) or action not in DIAGNOSTIC_ACTIONS.get(path, ()):
            return
        with self._worker_condition:
            item = self._request_details.get(request)
            if item is not None:
                item['action'] = action

    def shutdown(self):
        with self._worker_condition:
            self._admission_open = False
        self.ide_queue_lane.close()
        self.header_admission.close()
        return super().shutdown()

    def server_close(self):
        self.ide_queue_lane.close()
        ingress_clean = self.header_admission.close()
        monitoring=getattr(self,'monitoring',None)
        monitoring_clean=monitoring.close() if monitoring else True
        deadline = time.monotonic() + self.shutdown_timeout
        with self._worker_condition:
            self._admission_open = False
            clean = self._worker_condition.wait_for(
                lambda: not self._active_requests,
                timeout=self.shutdown_timeout)
            active = tuple(self._active_requests)
        probe_clean = self.backend_availability.close(deadline - time.monotonic())
        self.shutdown_clean = clean and probe_clean and monitoring_clean and ingress_clean
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
    request_read_seconds = 60

    def setup(self):
        self.request.settimeout(1)
        super().setup()
        self.rfile.close()
        elapsed = time.monotonic() - getattr(self.request, 'header_started', time.monotonic())
        self.rfile = request_reader(self.request, max(.001, self.request_read_seconds-elapsed))

    def log_message(self, *args):
        pass  # Do not log request URLs, headers, tokens or payloads.

    def log_error(self, format, *args):
        # BaseHTTPRequestHandler sends socket timeouts here, otherwise silently
        # discarded by log_message. Never interpolate its request/error text.
        reason = 'socket_timeout' if format.startswith('Request timed out') else 'http_error'
        logging.getLogger(__name__).warning('http_request_failed reason=%s', reason)

    def reply(self, code, payload):
        project_view = code == 200 and self.path == '/v1/projects/open'
        compact = project_view or code == 200 and self.path == '/v1/federation/rss-subscriptions'
        data = (json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
                if compact else json.dumps(payload).encode())
        compressed = False
        if project_view and len(data) >= 1024 and _accepts_project_gzip(self.headers):
            packed = gzip.compress(data, compresslevel=1, mtime=0)
            if len(packed) < len(data):
                data = packed; compressed = True
        self.close_connection = True
        self.send_response_only(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        if project_view:
            self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        if code == 503:
            self.send_header('Retry-After', '1')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # The browser can close an in-flight request while a page/profile
            # is shutting down. The response has no durable effect to recover.
            self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error': 'request rejected'})

    def end_headers(self):
        super().end_headers()
        self.response_started = True

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

    def _in_request_lane(self, operation, *, lane_name='application_lane', typed_busy=False):
        lane = getattr(self.server, lane_name, None)
        if lane is None:
            # Small unit fixtures may compose this handler with an already
            # sequential HTTPServer; only BoundedHTTPServer enables concurrency.
            return operation()
        describe = getattr(self.server, 'describe_request', lambda *args: None)
        # Only literal declared routes can enter diagnostics. Unknown URLs and
        # query strings may contain secrets and must never be retained.
        operation_name = self.path if self.path in self.post_paths or self.path in ROUTE_LANES else 'unclassified'
        kind = 'content-sync' if self.path == '/v1/federation/content-sync' else lane_name
        describe(self.request, kind, 'waiting', operation_name)
        # Only the IDE lane has a single waiting slot. Other domains retain
        # short admission waits so they cannot park the whole HTTP pool.
        timeout = self.server.request_lane_timeout
        if getattr(self.server, 'post_slots', None) is not None and lane_name != 'ide_queue_lane':
            timeout = min(0.1, timeout)
        acquired = lane.acquire(timeout=timeout)
        if not acquired:
            logging.getLogger(__name__).warning('http_request_busy lane=%s requests=%s',
                lane_name, (self.server.http_diagnostics()['requests']
                    if hasattr(self.server, 'http_diagnostics') else []))
            if typed_busy:
                raise ProjectBusy('HTTP operation owner is busy', outcome='not-started')
            return self.reply(503, {'error': 'server busy'})
        try:
            describe(self.request, kind, 'processing')
            return operation()
        finally:
            lane.release()

    def do_POST(self):
        slots = getattr(self.server, 'post_slots', None)
        if self.path in RESERVED_ROUTES:
            slots = None
        if slots is not None and not slots.acquire(blocking=False):
            logging.getLogger(__name__).warning('http_request_busy reason=ui_worker_reserved')
            return self.reply(503, {'error': 'server busy'})
        try:
            return self._admitted_POST()
        finally:
            if slots is not None:
                slots.release()

    def _admitted_POST(self):
        with bounded_project_requests():
            try:
                if (self.path in PROJECT_ROUTES or self.path in ACTION_LANES
                        or self.path in STREAM_ROUTES or self.path in SERVICE_ROUTES):
                    return self._do_POST()
                return self._in_request_lane(
                    self._do_POST, lane_name=request_lane(self.path))
            except RequestReadTimeout:
                return self.reply(503, {'error': 'request read timeout',
                    'outcome': 'not-started', 'retry': 'same-operation'})
            except ProjectBusy as exc:
                payload = {'error': 'resource busy',
                           'retry': 'same-operation', 'outcome': exc.outcome,
                           'busy_resource': exc.busy_resource}
                if getattr(self, 'response_started', False):
                    # A stream already sent HTTP 200. Report its terminal error
                    # inside NDJSON, never append a second HTTP response.
                    self.close_connection = True
                    if self.path in STREAM_ROUTES:
                        try:
                            self.wfile.write(json.dumps(dict(payload, type='error', status=503)).encode()+b'\n')
                            self.wfile.flush()
                        except OSError:
                            pass
                    return
                return self.reply(503, payload)

    def _dispatch_request(self, request):
        describe_action = getattr(self.server, 'describe_request_action', lambda *args: None)
        describe_action(self.request, self.path, request)
        if self.path in (STREAM_ROUTES | SERVICE_ROUTES) and isinstance(request, dict):
            from uuid import UUID
            pid = request.get('project_id')
            try:
                if isinstance(pid, str) and str(UUID(pid)) == pid:
                    self.server.describe_request(self.request, request_lane(self.path, request), 'waiting', self.path, pid)
            except (ValueError, AttributeError):
                pass
        if self.path in ACTION_LANES or self.path in STREAM_ROUTES or self.path in SERVICE_ROUTES:
            return self._in_request_lane(lambda: self.dispatch(request),
                lane_name=request_lane(self.path, request), typed_busy=self.path in SERVICE_ROUTES)
        if self.path not in PROJECT_ROUTES:
            return self.dispatch(request)
        from uuid import UUID
        field = PROJECT_ROUTES[self.path]
        scope = request.get(field) if field and isinstance(request, dict) else request
        try:
            project_id = scope['project_id']
            if not isinstance(project_id, str) or str(UUID(project_id)) != project_id:
                raise ValueError('Invalid project ID')
        except (KeyError, TypeError, ValueError, AttributeError):
            return self.send_error(400)
        lanes = getattr(self.server, 'project_lanes', None)
        if lanes is None:
            return self.dispatch(request)
        describe = getattr(self.server, 'describe_request', lambda *args: None)
        if self.path in PROJECT_READ_ROUTES:
            describe(self.request, 'project_read_lane', 'waiting', self.path, project_id)
            return self._in_request_lane(lambda: self.dispatch(request),
                lane_name='project_read_lane', typed_busy=True)
        describe(self.request, 'project', 'waiting', self.path, project_id)
        with lanes.acquire(project_id, min(0.1, self.server.request_lane_timeout)):
            describe(self.request, 'project', 'processing', self.path, project_id)
            return self.dispatch(request)

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
        describe = getattr(self.server, 'describe_request', lambda *args: None)
        describe(self.request, 'request-body', 'reading', self.path)
        try:
            body = self.rfile.read(int(length))
            if len(body) != int(length):
                return self.send_error(400)
            request = parse_json(body, self.max_body)
        except (ValidationError, UnicodeError, ValueError):
            return self.send_error(400)
        self._dispatch_request(request)

    def do_GET(self):
        return self._in_request_lane(self._do_GET)

    def _do_GET(self):
        self.send_error(405)

    do_HEAD = do_GET
    do_OPTIONS = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET


class UnixAPI(UnixStreamServer):
    def server_close(self):
        monitoring=getattr(self,'monitoring',None)
        if monitoring is not None:monitoring.close()
        sampler = getattr(self, 'backend_availability', None)
        if sampler is not None:
            sampler.close(SHUTDOWN_GRACE_SECONDS)
        return super().server_close()

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
        for name in LANES:
            setattr(server, name + '_lane', threading.Lock())
        server.backend_availability = BackendAvailability()
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
