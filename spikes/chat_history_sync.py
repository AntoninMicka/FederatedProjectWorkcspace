# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit, signed transfer of immutable read-only chat history snapshots."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import ssl
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

from spikes.administration import Administration, AccessDenied
from spikes.chat_threads import ChatThreads
from spikes.configuration import parse_node, read_config
from spikes.federation_accounts import canonical
from spikes.metadata import require, timestamp, uuid
from spikes.network_backend import private_root
from spikes.project_creation import ProjectCreation
from spikes.project_replication import _signature, _verify


PATH = '/v1/federation/chat-history'
CONTENT_TYPE = 'application/vnd.federated-workspace.chat-history-v1+json'
MAX_BODY = 16 * 1024 * 1024
MAX_THREADS = 32
TERMINAL_TURNS = {'completed', 'failed', 'cancelled', 'unknown'}
INTERNAL_LEVELS = {'same-team', 'same-company'}


class ChatHistoryRejected(ValueError):
    pass


def _chat_root(node):
    return Path(node).absolute().parent / ('.' + Path(node).name + '.chat')


def _path(node):
    root = private_root(node)
    path = root / 'chat-history-sync.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe chat history sync store')
    finally:
        os.close(fd)
    return path


@contextmanager
def _database(node):
    db = sqlite3.connect(_path(node), timeout=30)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS outbound(
                operation_id TEXT PRIMARY KEY, peer_id TEXT NOT NULL,
                mapping_id TEXT NOT NULL, package TEXT NOT NULL,
                state TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbound(
                operation_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(
                snapshot_id TEXT PRIMARY KEY, source_node_id TEXT NOT NULL,
                source_user_id TEXT NOT NULL, recipient_user_id TEXT NOT NULL,
                original_thread_id TEXT NOT NULL, snapshot_digest TEXT NOT NULL,
                operation_id TEXT NOT NULL, received_at TEXT NOT NULL,
                thread TEXT NOT NULL,
                UNIQUE(source_node_id,source_user_id,recipient_user_id,
                       original_thread_id,snapshot_digest));
        ''')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _state(service):
    actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
    return service.request(actor, {'action': 'list'})


def _authority(service, peer_id, mapping_id, *, expected_user=None):
    uuid(peer_id); uuid(mapping_id)
    state = _state(service)
    peer = next((item for item in state['peers'] if item['id'] == peer_id), None)
    require(peer is not None and peer['trust'] == 'approved'
            and peer['sharing_level'] in INTERNAL_LEVELS,
            'Chat history requires an approved internal peer')
    mapping = next((item for item in state['mappings']
                    if item['spec']['id'] == mapping_id), None)
    require(mapping is not None and service.mapping_active(state, mapping),
            'Chat history requires an active bilateral account mapping')
    local, remote, mapped_peer = service.mapping_context(state, mapping['spec'])
    require(mapped_peer['id'] == peer_id, 'Mapping belongs to another peer')
    if expected_user is not None:
        require(local['user_id'] == expected_user,
                'Mapping does not contain the current chat owner')
    return state, peer, mapping['spec'], local, remote


def _validate_thread(thread, *, source_node_id, source_user_id, project_ids,
                     sharing_level):
    fields = {'thread_id', 'node_id', 'user_id', 'status', 'classification',
              'created_at', 'revision', 'project_id', 'assignment_revision',
              'response_language', 'messages', 'turns'}
    require(isinstance(thread, dict) and set(thread) == fields,
            'Invalid chat history snapshot')
    for value in (thread['thread_id'], thread['node_id'], thread['user_id']):
        uuid(value)
    require(thread['node_id'] == source_node_id and thread['user_id'] == source_user_id,
            'Chat history owner differs from signed package')
    timestamp(thread['created_at'])
    require(thread['status'] in {'active', 'archived'}
            and thread['classification'] in {'brainstorming', 'orchestration'}
            and type(thread['revision']) is int and thread['revision'] >= 0
            and type(thread['assignment_revision']) is int
            and thread['assignment_revision'] >= 0,
            'Invalid chat history metadata')
    project_id = thread['project_id']
    if project_id is None:
        require(sharing_level == 'same-team',
                'Unassigned histories are limited to same-team peers')
    else:
        uuid(project_id)
        require(project_id in project_ids, 'Chat history project is outside mapping scope')
    require(isinstance(thread['messages'], list) and isinstance(thread['turns'], list),
            'Invalid chat history contents')
    message_ids = set()
    for sequence, message in enumerate(thread['messages'], 1):
        expected = {'message_id', 'sequence', 'role', 'content', 'content_sha256',
                    'privacy', 'author_id', 'created_at', 'supersedes_id'}
        require(isinstance(message, dict) and set(message) == expected,
                'Invalid chat history message')
        uuid(message['message_id']); timestamp(message['created_at'])
        require(message['message_id'] not in message_ids
                and message['sequence'] == sequence
                and message['role'] in {'user', 'assistant'}
                and message['privacy'] in {'public', 'project', 'confidential'}
                and isinstance(message['content'], str)
                and bool(message['content'].strip())
                and len(message['content'].encode()) <= 1024 * 1024
                and hashlib.sha256(message['content'].encode()).hexdigest()
                    == message['content_sha256'],
                'Invalid or local-only chat history message')
        message_ids.add(message['message_id'])
        if message['supersedes_id'] is not None:
            uuid(message['supersedes_id'])
            require(message['supersedes_id'] in message_ids,
                    'Chat message supersedes an unavailable message')
        if message['role'] == 'user':
            uuid(message['author_id'])
        else:
            require(isinstance(message['author_id'], str)
                    and message['author_id'].startswith('backend:'),
                    'Invalid chat message author')
            uuid(message['author_id'].removeprefix('backend:'))
    turn_ids = set()
    for turn in thread['turns']:
        expected = {'turn_id', 'user_message_id', 'run_id', 'assistant_message_id',
                    'state', 'error', 'manifest_id', 'response_language',
                    'language_source', 'language_compliance'}
        require(isinstance(turn, dict) and set(turn) == expected,
                'Invalid chat history turn')
        uuid(turn['turn_id']); uuid(turn['user_message_id'])
        require(turn['turn_id'] not in turn_ids and turn['state'] in TERMINAL_TURNS
                and turn['user_message_id'] in message_ids,
                'Active or invalid chat turn cannot be transferred')
        turn_ids.add(turn['turn_id'])
        for key in ('run_id', 'assistant_message_id', 'manifest_id'):
            if turn[key] is not None:
                uuid(turn[key])
        require(turn['assistant_message_id'] is None
                or turn['assistant_message_id'] in message_ids,
                'Chat turn references an unavailable message')
    return thread


def validate_package(package, *, service):
    fields = {'schema_version', 'operation_id', 'source_node_id',
              'recipient_node_id', 'source_user_id', 'recipient_user_id',
              'mapping_id', 'created_at', 'threads'}
    require(isinstance(package, dict) and set(package) == fields
            and package['schema_version'] == 1,
            'Invalid chat history package')
    for key in ('operation_id', 'source_node_id', 'recipient_node_id',
                'source_user_id', 'recipient_user_id', 'mapping_id'):
        uuid(package[key])
    timestamp(package['created_at'])
    require(isinstance(package['threads'], list)
            and 1 <= len(package['threads']) <= MAX_THREADS,
            'Chat history package must contain 1-32 threads')
    state, peer, spec, local, remote = _authority(
        service, package['source_node_id'], package['mapping_id'])
    require(package['recipient_node_id'] == state['node_id']
            and package['recipient_user_id'] == local['user_id']
            and package['source_user_id'] == remote['user_id'],
            'Chat history package does not match bilateral mapping')
    seen = set()
    for thread in package['threads']:
        _validate_thread(thread, source_node_id=package['source_node_id'],
                         source_user_id=package['source_user_id'],
                         project_ids=spec['project_ids'],
                         sharing_level=peer['sharing_level'])
        require(thread['thread_id'] not in seen, 'Duplicate chat history thread')
        seen.add(thread['thread_id'])
    return package, peer


def prepare(node, peer_id, mapping_id, thread_ids, operation_id):
    node = Path(node).absolute(); uuid(operation_id)
    require(isinstance(thread_ids, list) and 1 <= len(thread_ids) <= MAX_THREADS
            and len(set(thread_ids)) == len(thread_ids),
            'Select 1-32 unique chat threads')
    service = Administration(node, deployment='desktop')
    node_id = parse_node(read_config(node), location=node)['id']
    user_id = ProjectCreation(node).author_id()
    _, peer, spec, local, remote = _authority(
        service, peer_id, mapping_id, expected_user=user_id)
    require(local['node_id'] == node_id, 'Mapping local node differs from chat node')
    root = _chat_root(node)
    require(root.exists(), 'Chat history is not initialized')
    store = ChatThreads(root)
    threads = [store.get(thread_id, node_id, user_id) for thread_id in thread_ids]
    package = {'schema_version': 1, 'operation_id': operation_id,
        'source_node_id': node_id, 'recipient_node_id': peer_id,
        'source_user_id': user_id, 'recipient_user_id': remote['user_id'],
        'mapping_id': mapping_id,
        'created_at': datetime.now(timezone.utc).isoformat(
            timespec='microseconds').replace('+00:00', 'Z'),
        'threads': threads}
    for thread in threads:
        _validate_thread(thread, source_node_id=node_id, source_user_id=user_id,
                         project_ids=spec['project_ids'],
                         sharing_level=peer['sharing_level'])
    envelope = _signature(service.root, package, node_id, 'package')
    raw = canonical(envelope)
    require(len(raw) <= MAX_BODY, 'Chat history package exceeds 16 MiB')
    with _database(node) as db:
        row = db.execute('SELECT peer_id,mapping_id,package,state,detail FROM outbound '
                         'WHERE operation_id=?', (operation_id,)).fetchone()
        expected = (peer_id, mapping_id, raw.decode('ascii'))
        if row:
            require(row[:3] == expected, 'Operation ID belongs to another chat transfer')
        else:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                       (operation_id, peer_id, mapping_id, expected[2], 'prepared',
                        'Signed package stored before transport'))
            db.commit()
    return envelope


class ChatHistoryReceiver:
    def __init__(self, node, service=None):
        self.node = Path(node).absolute()
        self.service = service or Administration(node, deployment='web')

    def receive(self, envelope):
        require(isinstance(envelope, dict) and 'package' in envelope,
                'Missing chat history package')
        package = envelope['package']
        package, peer = validate_package(package, service=self.service)
        verified = _verify(envelope, peer['fingerprint'], 'package')['package']
        require(verified == package and envelope['signer_node_id'] == package['source_node_id'],
                'Chat history signature does not match package')
        raw = canonical(envelope); digest = hashlib.sha256(raw).hexdigest()
        accepted = []
        with _database(self.node) as db:
            row = db.execute('SELECT request_digest,receipt FROM inbound WHERE operation_id=?',
                             (package['operation_id'],)).fetchone()
            if row:
                require(row[0] == digest, 'Chat transfer operation ID was reused')
                return json.loads(row[1])
            received_at = datetime.now(timezone.utc).isoformat(
                timespec='microseconds').replace('+00:00', 'Z')
            for thread in package['threads']:
                thread_raw = canonical(thread)
                snapshot_digest = hashlib.sha256(thread_raw).hexdigest()
                snapshot_id = hashlib.sha256((package['source_node_id'] + ':'
                    + package['source_user_id'] + ':' + package['recipient_user_id']
                    + ':' + thread['thread_id'] + ':'
                    + snapshot_digest).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)',
                    (snapshot_id, package['source_node_id'], package['source_user_id'],
                     package['recipient_user_id'], thread['thread_id'], snapshot_digest,
                     package['operation_id'], received_at, thread_raw.decode('ascii')))
                accepted.append({'thread_id': thread['thread_id'],
                                 'snapshot_digest': snapshot_digest})
            receipt_value = {'schema_version': 1,
                'operation_id': package['operation_id'],
                'source_node_id': package['source_node_id'],
                'recipient_node_id': package['recipient_node_id'],
                'accepted': accepted}
            receipt = _signature(self.service.root, receipt_value,
                                 package['recipient_node_id'], 'receipt')
            db.execute('INSERT INTO inbound VALUES (?,?,?)',
                       (package['operation_id'], digest,
                        canonical(receipt).decode('ascii')))
            db.commit()
        return receipt


def received(node, *, recipient_user_id=None):
    with _database(node) as db:
        if recipient_user_id is not None:
            uuid(recipient_user_id)
        rows = db.execute('SELECT snapshot_id,source_node_id,source_user_id,'
            'recipient_user_id,original_thread_id,snapshot_digest,operation_id,'
            'received_at,thread FROM snapshots '
            + ('WHERE recipient_user_id=? ' if recipient_user_id is not None else '')
            + 'ORDER BY received_at,snapshot_id',
            (() if recipient_user_id is None else (recipient_user_id,))).fetchall()
    result = []
    groups = {}
    for row in rows:
        groups.setdefault((row[1], row[2], row[3], row[4]), []).append(row[5])
    for row in rows:
        thread = json.loads(row[8])
        thread.update({'read_only': True, 'snapshot_id': row[0],
            'source_node_id': row[1], 'source_user_id': row[2],
            'recipient_user_id': row[3], 'original_thread_id': row[4],
            'snapshot_digest': row[5], 'operation_id': row[6],
            'received_at': row[7],
            'divergent': len(groups[(row[1], row[2], row[3], row[4])]) > 1})
        result.append(thread)
    return result


def options(node):
    service = Administration(node, deployment='desktop')
    state = _state(service); user_id = ProjectCreation(node).author_id()
    peers = []
    for mapping in state['mappings']:
        if not service.mapping_active(state, mapping):
            continue
        try:
            local, remote, peer = service.mapping_context(state, mapping['spec'])
        except (AccessDenied, ValueError):
            continue
        if (local['user_id'] == user_id and peer['sharing_level'] in INTERNAL_LEVELS
                and peer.get('endpoint')):
            peers.append({'peer_id': peer['id'], 'name': peer['name'],
                'sharing_level': peer['sharing_level'],
                'mapping_id': mapping['spec']['id'],
                'project_ids': mapping['spec']['project_ids'],
                'recipient_user_id': remote['user_id']})
    return {'peers': peers}


def _send(node, operation_id):
    service = Administration(node, deployment='desktop')
    with _database(node) as db:
        row = db.execute('SELECT peer_id,mapping_id,package,state FROM outbound '
                         'WHERE operation_id=?', (operation_id,)).fetchone()
    require(row is not None, 'Unknown chat history operation')
    peer_id, mapping_id, raw, state = row
    require(state in {'prepared', 'unknown'}, 'Chat history operation is already complete')
    _, peer, _, _, _ = _authority(service, peer_id, mapping_id,
                                   expected_user=ProjectCreation(node).author_id())
    require(peer.get('endpoint'), 'Peer has no direct endpoint')
    parsed = urlsplit(peer['endpoint'])
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            'Invalid chat history peer endpoint')
    address = ipaddress.ip_address(parsed.hostname)
    require(address.version == 4 and not address.is_unspecified
            and (address.is_private or address.is_loopback),
            'Chat history peer must use private IPv4')
    ca = private_root(node) / (peer_id + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(str(address), parsed.port or 443,
                                              context=context, timeout=60)
    dispatched = False
    try:
        connection.request('POST', PATH, body=raw.encode('ascii'), headers={
            'Content-Type': CONTENT_TYPE, 'Host': parsed.netloc})
        dispatched = True
        response = connection.getresponse(); body = response.read(MAX_BODY + 1)
        require(len(body) <= MAX_BODY, 'Chat history response exceeds limit')
        if response.status != 200:
            raise ChatHistoryRejected('Peer rejected chat history transfer')
        receipt = json.loads(body)
        package = json.loads(raw)['package']
        verified = _verify(receipt, peer['fingerprint'], 'receipt')['receipt']
        require(isinstance(verified, dict) and set(verified) == {
            'schema_version', 'operation_id', 'source_node_id',
            'recipient_node_id', 'accepted'}
            and verified['schema_version'] == 1
            and isinstance(verified['accepted'], list),
            'Invalid chat history receipt')
        require(verified['operation_id'] == operation_id
                and verified['source_node_id'] == package['source_node_id']
                and verified['recipient_node_id'] == peer_id,
                'Chat history receipt does not match operation')
        expected = [{'thread_id': item['thread_id'],
            'snapshot_digest': hashlib.sha256(canonical(item)).hexdigest()}
            for item in package['threads']]
        require(verified['accepted'] == expected,
                'Peer receipt does not cover every selected snapshot')
    except Exception as exc:
        with _database(node) as db:
            db.execute('UPDATE outbound SET state=?,detail=? WHERE operation_id=?',
                       ('rejected' if isinstance(exc, ChatHistoryRejected) else
                        ('unknown' if dispatched else 'prepared'),
                        'Peer explicitly rejected the package'
                        if isinstance(exc, ChatHistoryRejected) else
                        ('Transport outcome is unknown' if dispatched
                         else 'Transport did not start'), operation_id)); db.commit()
        raise
    finally:
        connection.close()
    with _database(node) as db:
        db.execute('UPDATE outbound SET state=?,detail=? WHERE operation_id=?',
                   ('succeeded', 'Signed receipt verified', operation_id)); db.commit()
    return status(node)


def status(node):
    with _database(node) as db:
        rows = db.execute('SELECT operation_id,peer_id,mapping_id,state,detail '
                          'FROM outbound ORDER BY rowid DESC').fetchall()
    return {'operations': [dict(zip(
        ('operation_id', 'peer_id', 'mapping_id', 'state', 'detail'), row))
        for row in rows], 'received': received(node), **options(node)}


def synchronize(node, request):
    require(isinstance(request, dict) and set(request) == {
        'operation_id', 'peer_id', 'mapping_id', 'thread_ids'},
        'Invalid chat history synchronization request')
    prepare(node, request['peer_id'], request['mapping_id'],
            request['thread_ids'], request['operation_id'])
    return _send(node, request['operation_id'])


def reconcile(node, request):
    require(isinstance(request, dict) and set(request) == {'operation_id'},
            'Invalid chat history reconcile request')
    uuid(request['operation_id'])
    return _send(node, request['operation_id'])


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
            or not 0 < int(length) <= MAX_BODY):
        return handler.send_error(413)
    try:
        body = handler.rfile.read(int(length))
        require(len(body) == int(length), 'Incomplete chat history body')
        envelope = json.loads(body)
        receipt = ChatHistoryReceiver(handler.server.node,
            Administration(handler.server.node, deployment='desktop')).receive(envelope)
        raw = canonical(receipt)
        handler.send_response(200)
        handler.send_header('Content-Type', CONTENT_TYPE)
        handler.send_header('Content-Length', str(len(raw)))
        handler.end_headers(); handler.wfile.write(raw)
    except (ValueError, AccessDenied, OSError, sqlite3.Error, json.JSONDecodeError):
        return handler.reply(422, {'error': 'Chat history transfer rejected'})
