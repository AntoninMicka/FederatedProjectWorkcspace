# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Signed exchange of project existence without project content or Git history."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import ssl
import stat
import subprocess
import threading
from urllib.parse import urlsplit

from spikes.administration import Administration, AccessDenied, identifier, label
from spikes.federation_accounts import canonical
from spikes.metadata import require
from spikes.network_backend import private_root
from spikes.project_replication import _signature, _verify
from spikes.projects import Projects


PATH = '/v1/federation/catalog'
CONTENT_TYPE = 'application/vnd.federated-workspace.catalog-v1+json'
PURPOSE = 'project-existence-catalog-v1'
MAX_PROJECTS = 256
MAX_BODY = 128 * 1024


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class CatalogStore:
    """Durable node-local outbound revisions and inbound peer projections."""

    def __init__(self, node):
        self.root = private_root(node)
        self.path = self.root / 'federation-catalog.sqlite'

    def _open(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe federation catalog store')
        finally:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS outbound ('
                   'peer_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, '
                   'digest TEXT NOT NULL, projects TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS inbound ('
                   'peer_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, '
                   'digest TEXT NOT NULL, projects TEXT NOT NULL, '
                   'updated_at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS runtime ('
                   'peer_id TEXT PRIMARY KEY, state TEXT NOT NULL, '
                   'detail TEXT NOT NULL, updated_at TEXT NOT NULL)')
        db.commit()
        return db

    def outbound(self, peer_id, projects):
        identifier(peer_id)
        raw = canonical(projects).decode('ascii')
        digest = hashlib.sha256(raw.encode('ascii')).hexdigest()
        with closing(self._open()) as db, db:
            row = db.execute(
                'SELECT revision,digest,projects FROM outbound WHERE peer_id=?',
                (peer_id,)).fetchone()
            if row and row[1] == digest:
                require(row[2] == raw, 'Catalog digest collision')
                return row[0], projects
            revision = row[0] + 1 if row else 1
            db.execute('INSERT OR REPLACE INTO outbound VALUES (?,?,?,?)',
                       (peer_id, revision, digest, raw))
        return revision, projects

    def accept(self, peer_id, revision, projects):
        identifier(peer_id)
        raw = canonical(projects).decode('ascii')
        digest = hashlib.sha256(raw.encode('ascii')).hexdigest()
        now = _now()
        with closing(self._open()) as db, db:
            row = db.execute(
                'SELECT revision,digest FROM inbound WHERE peer_id=?',
                (peer_id,)).fetchone()
            if row and revision < row[0]:
                return False
            if row and revision == row[0]:
                require(row[1] == digest, 'Catalog revision changed content')
                return False
            db.execute('INSERT OR REPLACE INTO inbound VALUES (?,?,?,?,?)',
                       (peer_id, revision, digest, raw, now))
        return True

    def runtime(self, peer_id, state, detail=''):
        identifier(peer_id)
        require(state in {'idle', 'waiting', 'offline', 'rejected', 'error'},
                'Invalid catalog runtime state')
        require(isinstance(detail, str) and len(detail) <= 500,
                'Invalid catalog runtime detail')
        with closing(self._open()) as db, db:
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?)',
                       (peer_id, state, detail, _now()))

    def projections(self):
        with closing(self._open()) as db:
            rows = db.execute(
                'SELECT peer_id,revision,projects,updated_at FROM inbound '
                'ORDER BY peer_id').fetchall()
        result = []
        for peer_id, revision, raw, updated_at in rows:
            for project in json.loads(raw):
                result.append(dict(project, peer_id=peer_id,
                                   revision=revision, updated_at=updated_at))
        return result

    def statuses(self):
        with closing(self._open()) as db:
            return {row[0]: {'state': row[1], 'detail': row[2],
                             'updated_at': row[3]}
                    for row in db.execute(
                        'SELECT peer_id,state,detail,updated_at FROM runtime')}


def validate_catalog(value):
    expected = {'schema_version', 'purpose', 'source_node_id',
                'recipient_node_id', 'revision', 'projects'}
    require(isinstance(value, dict) and set(value) == expected
            and value.get('schema_version') == 1
            and value.get('purpose') == PURPOSE,
            'Invalid project catalog')
    identifier(value['source_node_id']); identifier(value['recipient_node_id'])
    require(value['source_node_id'] != value['recipient_node_id']
            and type(value['revision']) is int and value['revision'] >= 1
            and isinstance(value['projects'], list)
            and len(value['projects']) <= MAX_PROJECTS,
            'Invalid project catalog identity or size')
    seen = set()
    for project in value['projects']:
        require(isinstance(project, dict) and set(project) == {'id', 'title'},
                'Project catalog exposes unsupported fields')
        identifier(project['id']); label(project['title'])
        require(project['id'] not in seen, 'Duplicate catalog project')
        seen.add(project['id'])
    require(value['projects'] == sorted(value['projects'], key=lambda row: row['id']),
            'Project catalog must be sorted')
    return value


def _authority(service, peer_id):
    identifier(peer_id)
    with service.locked() as (_, state, commit, _):
        peer = next((item for item in state['peers'] if item['id'] == peer_id), None)
        if (not peer or peer['trust'] != 'approved'
                or peer['sharing_level'] == 'unspecified'):
            raise AccessDenied('Project catalog requires an approved sharing peer')
        return state['node_id'], dict(peer), list(state['project_shares']), commit


def _selected_projects(peer, shares, catalog):
    allowed = None
    if peer['sharing_level'] != 'same-team':
        allowed = {item['project_id'] for item in shares
                   if item['peer_id'] == peer['id']}
    rows = [{'id': item['id'], 'title': item['title']}
            for item in catalog if item.get('available')
            and (allowed is None or item['id'] in allowed)]
    require(len(rows) <= MAX_PROJECTS, 'Project catalog exceeds limit')
    return sorted(rows, key=lambda row: row['id'])


def prepare(service, peer_id):
    local_id, peer, shares, commit = _authority(service, peer_id)
    projects = _selected_projects(
        peer, shares, Projects(service.node).catalog())
    # A policy change while project metadata was read must not publish a stale
    # scope. The scheduler can safely retry from the new registry commit.
    current_id, current_peer, current_shares, current_commit = _authority(
        service, peer_id)
    require((current_id, current_peer, current_shares, current_commit)
            == (local_id, peer, shares, commit),
            'Project sharing policy changed during catalog preparation')
    revision, projects = CatalogStore(service.node).outbound(peer_id, projects)
    payload = validate_catalog({
        'schema_version': 1, 'purpose': PURPOSE,
        'source_node_id': local_id, 'recipient_node_id': peer_id,
        'revision': revision, 'projects': projects,
    })
    return _signature(service.root, payload, local_id, 'catalog'), peer


def receive(service, envelope):
    require(isinstance(envelope, dict) and isinstance(envelope.get('catalog'), dict),
            'Missing project catalog')
    candidate = validate_catalog(envelope['catalog'])
    local_id, peer, _, _ = _authority(service, candidate['source_node_id'])
    require(candidate['recipient_node_id'] == local_id
            and envelope.get('signer_node_id') == peer['id'],
            'Project catalog targets another node')
    payload = validate_catalog(_verify(
        envelope, peer['fingerprint'], 'catalog')['catalog'])
    CatalogStore(service.node).accept(
        peer['id'], payload['revision'], payload['projects'])
    CatalogStore(service.node).runtime(peer['id'], 'idle',
                                       'Catalog received')
    response, _ = prepare(service, peer['id'])
    return response


def synchronize(node, peer_id, *, deployment='desktop', ca=None):
    service = Administration(node, deployment=deployment)
    envelope, peer = prepare(service, peer_id)
    if not peer.get('endpoint'):
        raise AccessDenied('Peer can synchronize only when it connects')
    parsed = urlsplit(peer['endpoint'])
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            'Invalid catalog peer endpoint')
    address = ipaddress.ip_address(parsed.hostname)
    require(address.version == 4 and not address.is_unspecified
            and (address.is_private or address.is_loopback),
            'Catalog peer must use a private IPv4 address')
    ca = Path(ca) if ca else private_root(node) / (peer_id + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(
        str(address), parsed.port or 443, context=context, timeout=15)
    try:
        raw = canonical(envelope)
        require(len(raw) <= MAX_BODY, 'Project catalog request exceeds limit')
        connection.request('POST', PATH, body=raw, headers={
            'Content-Type': CONTENT_TYPE, 'Host': parsed.netloc})
        response = connection.getresponse()
        response_raw = response.read(MAX_BODY + 1)
        require(len(response_raw) <= MAX_BODY,
                'Project catalog response exceeds limit')
        if response.status != 200:
            raise AccessDenied('Peer rejected project catalog')
        response_envelope = json.loads(response_raw)
    finally:
        connection.close()
    returned = validate_catalog(_verify(
        response_envelope, peer['fingerprint'], 'catalog')['catalog'])
    local_id, current_peer, _, _ = _authority(service, peer_id)
    require(current_peer['fingerprint'] == peer['fingerprint']
            and returned['source_node_id'] == peer_id
            and returned['recipient_node_id'] == local_id,
            'Project catalog response does not match peer')
    store = CatalogStore(node)
    store.accept(peer_id, returned['revision'], returned['projects'])
    store.runtime(peer_id, 'idle', 'Catalog synchronized')
    return returned


class CatalogControl:
    def __init__(self, node, *, deployment):
        self.node = node
        self.deployment = deployment
        self.administration = Administration(node, deployment=deployment)
        self.store = CatalogStore(node)

    def view(self):
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = self.administration.request(actor, {'action': 'list'})
        approved = {peer['id'] for peer in state['peers']
                    if peer['trust'] == 'approved'
                    and peer['sharing_level'] != 'unspecified'}
        return {
            'remote_projects': [row for row in self.store.projections()
                                if row['peer_id'] in approved],
            'catalog_statuses': {key: value for key, value in self.store.statuses().items()
                                 if key in approved},
        }

    def synchronize(self, peer_id):
        try:
            result = synchronize(
                self.node, peer_id, deployment=self.deployment)
        except AccessDenied as exc:
            self.store.runtime(peer_id, 'rejected', str(exc))
            raise
        except (ConnectionError, TimeoutError, ssl.SSLError, OSError) as exc:
            self.store.runtime(peer_id, 'offline', type(exc).__name__)
            raise
        except (ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
            self.store.runtime(peer_id, 'error', str(exc))
            raise
        return result

    def run_automatic(self):
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = self.administration.request(actor, {'action': 'list'})
        for peer in state['peers']:
            if (peer['trust'] == 'approved'
                    and peer['sharing_level'] in {'same-team', 'same-company'}
                    and peer.get('endpoint')):
                try:
                    self.synchronize(peer['id'])
                except Exception:
                    pass


class CatalogScheduler:
    def __init__(self, node, *, deployment, interval=60):
        self.control = CatalogControl(node, deployment=deployment)
        self.interval = interval
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(
                target=self._run, name='federation-catalog', daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            self.control.run_automatic()
            self.stopping.wait(self.interval)

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
            self.thread = None


def reply(handler):
    if (handler.single('Host') != handler.local_authority
            or handler.headers.get_all('Origin', [])
            or handler.headers.get_all('Authorization', [])
            or handler.headers.get_all('Transfer-Encoding')
            or handler.headers.get_all('Expect')
            or handler.single('Content-Type') != CONTENT_TYPE):
        return handler.send_error(403)
    length = handler.single('Content-Length')
    if (length is None or not length.isascii() or not length.isdecimal()
            or len(length) > len(str(MAX_BODY))
            or not 2 <= int(length) <= MAX_BODY):
        return handler.send_error(413)
    try:
        raw = handler.rfile.read(int(length))
        require(len(raw) == int(length), 'Incomplete project catalog')
        result = receive(handler.server.administration, json.loads(raw))
        return handler.reply(200, result)
    except AccessDenied:
        return handler.reply(403, {'error': 'Project catalog is not authorized'})
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError,
            json.JSONDecodeError):
        return handler.reply(422, {'error': 'Project catalog was rejected'})
