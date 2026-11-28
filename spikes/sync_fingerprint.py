# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Cheap, signed per-peer content inventories; never a substitute for publication."""
from collections import OrderedDict
import logging
import threading
import time
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
from uuid import uuid4

from spikes.administration import AccessDenied, identifier
from spikes.federation_accounts import canonical
from spikes.git_budget import git_budget
from spikes.http_deadline import DeadlineHTTPSConnection
from spikes.http_request_budget import RequestReadTimeout
from spikes.metadata import require
from spikes.peer_transport import CONTENT_STATE_TIMEOUT, private_peer_endpoint
from spikes.project_replication import _signature, _verify
from spikes.request_ownership import ProjectBusy, bounded_project_requests, safe_busy_resource

_log = logging.getLogger(__name__)
# A content state answer slower than this is logged: the sender gives up at
# CONTENT_STATE_TIMEOUT, and without timing a router cannot be diagnosed.
SLOW_STATE_MS = 5000

PATH = '/v1/federation/content-state'
CONTENT_TYPE = 'application/vnd.federated-workspace.content-state-v1+json'
MAX_BODY = 128 * 1024
MAX_PROJECTS = 256
HEX = re.compile('[0-9a-f]{64}')


class StateUnavailable(ValueError):
    """One project could not supply a current manifest snapshot."""



_check_lock = threading.Lock()
_checks = OrderedDict()


def note(node, peer, project, outcome, error=None):
    """Bounded observation only; never a stored dirty flag or recovery authority."""
    key = (str(Path(node).absolute()), peer, project)
    with _check_lock:
        _checks[key] = dict(state=outcome, checked=time.monotonic(),
                            error_type=type(error).__name__ if error is not None else None)
        if isinstance(error, ProjectBusy):
            _checks[key]['busy_resource'] = safe_busy_resource(error.busy_resource)
        _checks.move_to_end(key)
        while len(_checks) > 128: _checks.popitem(last=False)


def observation(node, peer, project):
    with _check_lock:
        value = _checks.get((str(Path(node).absolute()), peer, project))
        if value is None: return None
        return dict(state=value['state'], age_seconds=max(0, int(time.monotonic()-value['checked'])),
                    error_type=value['error_type'],
                    **({'busy_resource': value['busy_resource']} if 'busy_resource' in value else {}))


def observations(node):
    root = str(Path(node).absolute())
    with _check_lock:
        keys = [(peer, project) for stored, peer, project in _checks if stored == root]
    return [(peer, project, observation(node, peer, project)) for peer, project in keys]


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def snapshot(authority, project_id, refs, chats, pool):
    local, peer, shares, commit = authority
    from spikes.federation_sync import _policy
    policy = digest({'local': local, 'peer': peer['id'], 'registry': commit,
                     'scope': _policy(peer, shares, project_id)})
    return {'fingerprint': digest({'refs': refs, 'chats': chats,
                                  'pool': hashlib.sha256(pool).hexdigest(),
                                  'policy': policy}), 'policy': policy}


@bounded_project_requests()
@git_budget(15)
def collect(service, peer_id, project_id, *, authority=None):
    """Fingerprint one local project inside an HTTP-sized budget."""
    return _collect(service, peer_id, project_id, authority=authority)


def _collect(service, peer_id, project_id, *, authority=None):
    """Fingerprint one project under the caller's ownership and Git budget.

    ``authority`` lets a caller that already read it (and re-checks it after
    all projects) skip two registry reads per project.
    """
    from spikes.federation_sync import _authority, _binding, _inventory, _policy
    from spikes.projects import Projects
    from spikes.project_chat_sync import export_project
    from spikes.pool_sync import export
    verify = authority is None
    authority = _authority(service, peer_id) if verify else authority
    scope = _policy(authority[1], authority[2], project_id)
    refs, chats, pool = [], [], b''
    if scope is not None and _binding(service.node, project_id) is not None:
        refs = _inventory(Projects(service.node).repository(project_id), scope)
        chats, _ = export_project(service.node, service, peer_id, project_id, read_only=True)
        if scope == {'mode': 'all'} and authority[1]['sharing_level'] == 'same-team':
            pool = export(service.node, project_id, read_only=True)
    require(not verify or _authority(service, peer_id) == authority, 'Content state authority changed')
    return snapshot(authority, project_id, refs, chats, pool)


def validate(value, *, response):
    fields = {'schema_version', 'source_node_id', 'recipient_node_id', 'nonce', 'projects'}
    require(isinstance(value, dict) and set(value) == fields
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'Invalid content state manifest')
    for key in ('source_node_id', 'recipient_node_id', 'nonce'): identifier(value[key])
    if not response:
        projects = value['projects']
        require(isinstance(projects, list) and len(projects) <= MAX_PROJECTS
                and all(isinstance(p, str) for p in projects)
                and projects == sorted(set(projects)), 'Invalid requested content projects')
        for project in projects: identifier(project)
    if response:
        rows = value['projects']
        require(isinstance(rows, list) and len(rows) <= MAX_PROJECTS, 'Content state exceeds project limit')
        ids = []
        for row in rows:
            require(isinstance(row, dict) and set(row) == {'id', 'fingerprint', 'policy'},
                    'Invalid content state row')
            identifier(row['id']); ids.append(row['id'])
            if row['fingerprint'] is None and row['policy'] is None:
                continue
            for key in ('fingerprint', 'policy'):
                require(isinstance(row[key], str) and HEX.fullmatch(row[key]), 'Invalid content fingerprint')
        require(ids == sorted(set(ids)), 'Duplicate or unordered content state')
    return value


@bounded_project_requests()
@git_budget(15)
def receive(service, envelope):
    """Synchronous answer for a sender without the state stream."""
    return _answer(service, envelope)


def receive_background(service, envelope):
    """Streamed answer (AUDIT-B7-T1): runs in a background job thread, so
    SQLite and flocks use their native waits and one budget bounds all
    projects instead of the sender's single HTTP deadline. Read-only: no
    journal, index or registry is written; a lost job leaves nothing behind."""
    from spikes.peer_transport import BACKGROUND_STATE_BUDGET
    with git_budget(BACKGROUND_STATE_BUDGET):
        return _answer(service, envelope)


def _answer(service, envelope):
    from spikes.federation_sync import _authority, _policy
    from spikes.configuration import parse_node, read_config
    request = validate(envelope.get('state_request') if isinstance(envelope, dict) else None, response=False)
    authority = _authority(service, request['source_node_id'])
    local, peer, shares, _ = authority
    _verify(envelope, peer['fingerprint'], 'state_request')
    require(envelope['signer_node_id'] == peer['id'] and request['recipient_node_id'] == local,
            'Content state request targets another node')
    projects = sorted(set(request['projects']) | {row['project_id'] for row in
                      parse_node(read_config(service.node), location=service.node)['projects']
                      if _policy(peer, shares, row['project_id']) is not None})
    require(len(projects) <= MAX_PROJECTS, 'Content state exceeds project limit')
    rows = []
    started = time.monotonic(); slowest = 0
    for project in projects:
        begun = time.monotonic()
        try:
            current = _collect(service, peer['id'], project, authority=authority)
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, ProjectBusy):
            # One damaged/unavailable project must not block healthy projects.
            current = {'fingerprint': None, 'policy': None}
        slowest = max(slowest, time.monotonic() - begun)
        rows.append(dict(id=project, **current))
    elapsed = round((time.monotonic() - started) * 1000)
    if elapsed >= SLOW_STATE_MS:
        _log.warning('content_state_slow elapsed_ms=%d projects=%d slowest_project_ms=%d '
                     'unavailable=%d', elapsed, len(rows), round(slowest * 1000),
                     sum(row['fingerprint'] is None for row in rows))
    require(_authority(service, peer['id']) == authority, 'Content state authority changed')
    value = dict(schema_version=1, source_node_id=local, recipient_node_id=peer['id'],
                 nonce=request['nonce'], projects=rows)
    return _signature(service.root, validate(value, response=True), local, 'state_manifest')


@bounded_project_requests()
def probe(service, peer_id, *, ca=None, projects=(), cancelled=None):
    """None means explicit legacy endpoint; transport/auth failures never mean clean.

    A peer that knows the state stream computes the answer in a background
    job and sends heartbeats, so a slow peer (many projects, a router) is
    waited for; only silence (HEARTBEAT_IDLE_TIMEOUT) or the overall
    CONTENT_STATE_MAX_WAIT fail the check. An older peer answers directly.
    """
    from spikes.content_receive_jobs import STATE_STREAM_TYPE, read_frames
    from spikes.peer_transport import CONTENT_STATE_MAX_WAIT, HEARTBEAT_IDLE_TIMEOUT
    from spikes.federation_sync import _authority
    from spikes.network_backend import private_root
    authority = _authority(service, peer_id)
    local, peer, _, _ = authority
    require(peer.get('endpoint'), 'Content state peer endpoint is unavailable')
    parsed, address = private_peer_endpoint(
        peer['endpoint'], invalid='Invalid content state endpoint',
        private='Content state requires a private IP address')
    request = dict(schema_version=1, source_node_id=local, recipient_node_id=peer_id, nonce=str(uuid4()), projects=sorted(set(projects)))
    validate(request, response=False)
    raw = canonical(_signature(service.root, request, local, 'state_request'))
    context = ssl.create_default_context(cafile=str(ca or private_root(service.node)/(peer_id+'-ca.pem')))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = DeadlineHTTPSConnection(str(address), parsed.port or 443, context=context, timeout=CONTENT_STATE_TIMEOUT)
    response = None
    try:
        connection.request('POST', PATH, body=raw, headers={
            'Content-Type': CONTENT_TYPE, 'Host': parsed.netloc, 'Accept': STATE_STREAM_TYPE})
        response = connection.getresponse()
        status = response.status
        if status == 200 and response.getheader('Content-Type') == STATE_STREAM_TYPE:
            connection.extend_deadline(CONTENT_STATE_MAX_WAIT, idle=HEARTBEAT_IDLE_TIMEOUT)
            kind, body = read_frames(response.readline, response.read,
                                     cancelled=cancelled or (lambda: False))
            if kind == 'error':
                status, body = body['status'], b''
        else:
            body = response.read(MAX_BODY + 1)
        connection.check_deadline()
        require(len(body) <= MAX_BODY, 'Content state response exceeds limit')
        if status in {404, 405, 415}: return None
        require(status == 200, 'Content state request rejected')
        envelope = json.loads(body)
        value = validate(_verify(envelope, peer['fingerprint'], 'state_manifest')['state_manifest'], response=True)
        require(envelope['signer_node_id'] == peer_id and value['source_node_id'] == peer_id
                and value['recipient_node_id'] == local and value['nonce'] == request['nonce'],
                'Content state response does not match request')
        require(_authority(service, peer_id) == authority, 'Content state authority changed')
        return {row['id']: (None if row['fingerprint'] is None else
                            {k: row[k] for k in ('fingerprint', 'policy')})
                for row in value['projects']}
    finally:
        if response is not None: response.close()
        connection.close()


@bounded_project_requests()
def receipt(service, response):
    """Sign the stored response snapshot, including on an exact native replay."""
    from spikes.federation_sync import _database
    exchange = response['exchange']
    with _database(service.node) as db:
        row = db.execute('SELECT state FROM response_states WHERE operation_id=?',
                         (exchange['operation_id'],)).fetchone()
    if row is None: return None
    value = dict(operation_id=exchange['operation_id'], project_id=exchange['project_id'],
                 source_node_id=exchange['source_node_id'], recipient_node_id=exchange['recipient_node_id'],
                 response_sha256=digest(response), state=json.loads(row[0]))
    return _signature(service.root, value, exchange['source_node_id'], 'state_receipt')


def verify_receipt(envelope, response, peer):
    value = _verify(envelope, peer['fingerprint'], 'state_receipt')['state_receipt']
    exchange = response['exchange']
    expected = {key: exchange[key] for key in
                ('operation_id', 'project_id', 'source_node_id', 'recipient_node_id')}
    require(isinstance(value, dict) and set(value) == set(expected) | {'response_sha256', 'state'}
            and all(value[key] == v for key, v in expected.items())
            and envelope['signer_node_id'] == exchange['source_node_id']
            and value['response_sha256'] == digest(response), 'Receipt differs from content response')
    state = value['state']
    require(isinstance(state, dict) and set(state) == {'fingerprint', 'policy'}
            and all(isinstance(v, str) and HEX.fullmatch(v) for v in state.values()),
            'Invalid receipt state')
    return state


def reply(handler):
    if (handler.single('Host') != handler.local_authority or handler.headers.get_all('Origin', [])
            or handler.headers.get_all('Authorization', []) or handler.headers.get_all('Transfer-Encoding')
            or handler.headers.get_all('Expect') or handler.single('Content-Type') != CONTENT_TYPE):
        return handler.send_error(403)
    length = handler.single('Content-Length')
    if (length is None or not length.isascii() or not length.isdecimal()
            or len(length) > len(str(MAX_BODY)) or not 2 <= int(length) <= MAX_BODY):
        return handler.send_error(413)
    try:
        raw = handler.rfile.read(int(length))
        require(len(raw) == int(length), 'Incomplete content state request')
        from spikes.content_receive_jobs import STATE_STREAM_TYPE
        if handler.single('Accept') == STATE_STREAM_TYPE:
            return _reply_streamed(handler, raw)
        result = receive(handler.server.administration, json.loads(raw))
        require(len(canonical(result)) <= MAX_BODY, 'Content state exceeds limit')
        return handler.reply(200, result)
    except RequestReadTimeout:
        raise
    except ProjectBusy:
        return handler.reply(503, {'error': 'Content state is busy'})
    except AccessDenied:
        return handler.reply(403, {'error': 'Content state is not authorized'})
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
        return handler.reply(422, {'error': 'Content state is unavailable'})


def _answer_job(service, envelope):
    def run():
        body = canonical(receive_background(service, envelope))
        require(len(body) <= MAX_BODY, 'Content state exceeds limit')
        return body
    return run


def _reply_streamed(handler, raw):
    """Compute the state answer in a background job and stream heartbeats.

    The answer is read-only, so there is no crash boundary to recover: a lost
    connection or process only loses the answer, and the sender's next check
    asks again with a new nonce.
    """
    from spikes.content_receive_jobs import STATE_JOBS, STATE_STREAM_TYPE, error_frame, stream
    service = handler.server.administration
    try:
        envelope = json.loads(raw)
        request = validate(envelope.get('state_request') if isinstance(envelope, dict) else None,
                           response=False)
        job = STATE_JOBS.start_or_attach(Path(service.node).absolute(), request['nonce'], raw,
                                         _answer_job(service, envelope),
                                         phase_source=lambda: 'content-state')
    except Exception as exc:  # noqa: BLE001 - typed statuses, never exception text
        if isinstance(exc, AccessDenied):
            return handler.reply(403, {'error': 'Content state is not authorized'})
        frame = error_frame(exc)
        return handler.reply(frame['status'], {'error': 'Content state is busy'}
                             if frame['status'] == 503 else {'error': 'Content state is unavailable'})
    handler.close_connection = True
    handler.send_response_only(200)
    handler.send_header('Content-Type', STATE_STREAM_TYPE)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Connection', 'close')
    handler.end_headers()
    def write(chunk):
        handler.wfile.write(chunk); handler.wfile.flush()
    try:
        stream(job, write)
    except OSError:
        pass  # the sender went away; a read-only answer needs no recovery
