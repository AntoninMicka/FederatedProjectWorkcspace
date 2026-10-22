# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Signed, grant-bound project replication with durable CAS recovery."""
import base64
from contextlib import closing
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat
import struct
import subprocess
import tempfile
from urllib.parse import urlsplit

from spikes.administration import Administration, identifier
from spikes.configuration import committed_project, parse_node, read_config
from spikes.federation_accounts import MappingSignatures, canonical, openssl
from spikes.git_transfer import MAX_BUNDLE, git_run, validate_history
from spikes.journal import RecoveryConflict, sync_dir
from spikes.metadata import require
from spikes.network_backend import private_root
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.workspace import PendingOperation


PATH = '/v1/federation/replicate'
CONTENT_TYPE = 'application/vnd.federated-workspace.replication-v1'
MAX_ENVELOPE = 16 * 1024
MAX_BODY = 4 + MAX_ENVELOPE + MAX_BUNDLE
HASH = re.compile(r'[a-f0-9]{40}|[a-f0-9]{64}')


def _journal_path(node):
    path = private_root(node) / 'git-transfer-journal.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1
                and not info.st_mode & 0o077, 'Unsafe replication journal')
    finally:
        os.close(fd)
    return path


def _exclusive_file(path, data):
    parent = Path(path).parent
    fd, temporary = tempfile.mkstemp(prefix='.replication-', dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        sync_dir(parent)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _sync_tree(root):
    for directory, _, names in os.walk(root):
        for name in names:
            fd = os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_dir(directory)


def _signature(root, payload, signer_node_id, field):
    identity = MappingSignatures(root)
    public = identity.public_key()
    signed = {field: payload, 'signer_node_id': signer_node_id}
    with tempfile.TemporaryDirectory(dir=root) as directory:
        message = Path(directory) / 'message'
        message.write_bytes(canonical(signed))
        signature = openssl('pkeyutl', '-sign', '-rawin', '-inkey', str(identity.key),
                            '-in', str(message))
    return dict(signed, public_key=base64.b64encode(public).decode(),
                signature=base64.b64encode(signature).decode())


def _verify(envelope, fingerprint, field):
    expected = {field, 'signer_node_id', 'public_key', 'signature'}
    require(isinstance(envelope, dict) and set(envelope) == expected,
            'Invalid replication signature envelope')
    require(isinstance(envelope['signer_node_id'], str), 'Invalid replication signer')
    require(isinstance(envelope['public_key'], str) and len(envelope['public_key']) <= 128
            and isinstance(envelope['signature'], str) and len(envelope['signature']) <= 128,
            'Invalid replication signature encoding')
    public = base64.b64decode(envelope['public_key'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    require(len(public) == 44
            and public[:12] == bytes.fromhex('302a300506032b6570032100')
            and len(signature) == 64
            and hashlib.sha256(public).hexdigest() == fingerprint,
            'Unpinned replication signer')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'public').write_bytes(public)
        (root / 'signature').write_bytes(signature)
        (root / 'message').write_bytes(canonical({
            field: envelope[field], 'signer_node_id': envelope['signer_node_id']}))
        openssl('pkeyutl', '-verify', '-pubin', '-keyform', 'DER',
                '-inkey', str(root / 'public'), '-rawin', '-in', str(root / 'message'),
                '-sigfile', str(root / 'signature'))
    return envelope


def validate_request(request):
    fields = {'schema_version', 'operation_id', 'grant_id', 'grant_digest',
              'project_id', 'ref', 'source_node_id', 'recipient_node_id',
              'expected_base', 'candidate_head', 'bundle_size', 'bundle_sha256'}
    require(isinstance(request, dict) and set(request) == fields
            and type(request['schema_version']) is int
            and request['schema_version'] == 1, 'Invalid replication request')
    for field in ('operation_id', 'grant_id', 'project_id', 'source_node_id',
                  'recipient_node_id'):
        identifier(request[field])
    require(request['source_node_id'] != request['recipient_node_id'],
            'Replication nodes must differ')
    require(request['ref'] == 'refs/heads/main', 'Unsupported replication ref')
    require(request['expected_base'] is None
            or isinstance(request['expected_base'], str)
            and HASH.fullmatch(request['expected_base']), 'Invalid expected base')
    require(isinstance(request['candidate_head'], str)
            and HASH.fullmatch(request['candidate_head']), 'Invalid candidate HEAD')
    for field in ('grant_digest', 'bundle_sha256'):
        require(isinstance(request[field], str)
                and re.fullmatch(r'[a-f0-9]{64}', request[field]),
                'Invalid replication digest')
    require(type(request['bundle_size']) is int
            and 0 < request['bundle_size'] <= MAX_BUNDLE,
            'Invalid replication bundle size')
    return request


def request_digest(request):
    return hashlib.sha256(canonical(validate_request(request))).hexdigest()


def validate_receipt(receipt):
    fields = {'schema_version', 'operation_id', 'request_sha256', 'grant_id',
              'project_id', 'ref', 'status', 'head'}
    require(isinstance(receipt, dict) and set(receipt) == fields
            and receipt['schema_version'] == 1, 'Invalid replication receipt')
    for field in ('operation_id', 'grant_id', 'project_id'):
        identifier(receipt[field])
    require(receipt['ref'] == 'refs/heads/main' and receipt['status'] == 'applied'
            and isinstance(receipt['head'], str) and HASH.fullmatch(receipt['head'])
            and isinstance(receipt['request_sha256'], str)
            and re.fullmatch(r'[a-f0-9]{64}', receipt['request_sha256']),
            'Invalid replication receipt fields')
    return receipt


def encode_body(envelope, payload):
    raw = canonical(envelope)
    require(0 < len(raw) <= MAX_ENVELOPE and len(payload) <= MAX_BUNDLE,
            'Replication request exceeds limits')
    return struct.pack('!I', len(raw)) + raw + payload


def decode_body(body):
    require(isinstance(body, bytes) and 4 < len(body) <= MAX_BODY,
            'Invalid replication body size')
    size = struct.unpack('!I', body[:4])[0]
    require(0 < size <= MAX_ENVELOPE and 4 + size < len(body),
            'Invalid replication envelope size')
    from spikes.metadata import parse_json
    return parse_json(body[4:4 + size], MAX_ENVELOPE), body[4 + size:]


class ReplicationReceiver:
    def __init__(self, node, administration=None):
        self.node = Path(node).absolute()
        self.administration = administration or Administration(self.node)

    def _authority(self, envelope, payload):
        require(isinstance(envelope, dict) and 'request' in envelope,
                'Missing replication request')
        request = validate_request(envelope['request'])
        authority = self.administration.active_replication(
            request['grant_id'], 'read-only-replica')
        spec = authority['spec']
        require(request['grant_digest'] == hashlib.sha256(canonical(spec)).hexdigest()
                and request['project_id'] == spec['project_id']
                and request['ref'] == spec['ref']
                and request['source_node_id'] == authority['remote']['node_id']
                and request['recipient_node_id'] == authority['local']['node_id']
                and envelope.get('signer_node_id') == authority['remote']['node_id'],
                'Replication request does not match active grant')
        _verify(envelope, authority['remote']['fingerprint'], 'request')
        require(len(payload) == request['bundle_size']
                and hashlib.sha256(payload).hexdigest() == request['bundle_sha256'],
                'Replication bundle differs from signed request')
        return request, authority

    def _validate_bundle(self, request, payload, privacy):
        root = private_root(self.node)
        with tempfile.TemporaryDirectory(prefix='replication-verify-', dir=root) as directory:
            directory = Path(directory)
            bundle = directory / 'project.bundle'
            bundle.write_bytes(payload)
            repo = directory / 'repo.git'; repo.mkdir(mode=0o700)
            git = Git(repo)
            git_run(git, 'init', '--bare', '--template=', '--initial-branch=main')
            git_run(git, 'bundle', 'verify', str(bundle))
            git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags',
                    str(bundle), 'refs/heads/main:refs/heads/candidate')
            candidate = git_run(git, 'rev-parse', 'refs/heads/candidate').stdout.strip()
            require(candidate == request['candidate_head'], 'Bundle HEAD differs from request')
            validate_history(git, candidate, request['project_id'], frozenset(privacy))
            if request['expected_base'] is not None:
                require(git_run(git, 'cat-file', '-e',
                                request['expected_base'] + '^{commit}', check=False).returncode == 0,
                        'Expected base is absent from bundle')
                require(git_run(git, 'merge-base', '--is-ancestor',
                                request['expected_base'], candidate,
                                check=False).returncode == 0,
                        'Candidate is not a fast-forward')

    def _store(self, envelope, payload):
        request = envelope['request']; digest = request_digest(request)
        encoded = canonical(envelope).decode('ascii')
        with closing(sqlite3.connect(_journal_path(self.node), timeout=60)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS replication_inbound (
                operation_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                envelope TEXT NOT NULL, bundle BLOB NOT NULL, receipt TEXT)''')
            row = db.execute(
                'SELECT request_digest,envelope,bundle,receipt FROM replication_inbound '
                'WHERE operation_id=?', (request['operation_id'],)).fetchone()
            if row:
                require(row[0] == digest and row[1] == encoded and bytes(row[2]) == payload,
                        'Replication operation ID belongs to another request')
                receipt = json.loads(row[3]) if row[3] else None
            else:
                db.execute('INSERT INTO replication_inbound VALUES (?,?,?,?,NULL)',
                           (request['operation_id'], digest, encoded, payload))
                receipt = None
            db.commit()
        return digest, receipt

    def _binding(self, project_id):
        node = parse_node(read_config(self.node), location=self.node)
        return next((row for row in node['projects']
                     if row['project_id'] == project_id), None)

    def _update(self, request, payload, authority, checkpoint):
        require(request['expected_base'] is not None,
                'Existing replica requires an expected base')
        workspace = Projects(self.node).workspace(request['project_id'], blocking=False)
        marker = {
            'kind': 'external-replication',
            'operation_id': request['operation_id'],
            'request_digest': request_digest(request),
            'base_head': request['expected_base'],
            'commit_id': request['candidate_head'],
            'branch': request['ref'],
            'state': 'prepared',
        }
        staging = 'refs/workspace/replication/' + request['operation_id']
        with workspace.journal.lock(), workspace.journal.connect() as db:
            row = db.execute('SELECT record,done FROM operations WHERE id=?',
                             (request['operation_id'],)).fetchone()
            if row:
                saved = json.loads(row[0])
                require(set(saved) == set(marker)
                        and saved.get('state') in {'prepared', 'committed', 'indexed'}
                        and all(saved.get(key) == marker[key]
                                for key in marker if key != 'state'),
                        'Project operation ID belongs to another request')
                if row[1]:
                    require(workspace.git.head() == request['candidate_head'],
                            'Completed replication HEAD changed')
                    return request['candidate_head']
                marker = saved
            else:
                require(not workspace._active(db)
                        and not db.execute('SELECT 1 FROM pending').fetchone(),
                        'Project has another unfinished operation')
                require(workspace._branch() == request['ref'],
                        'Replica branch changed')
                require(workspace.git.head() == request['expected_base'],
                        'Replica diverged from expected base')
                require(not git_run(workspace.git, 'status', '--porcelain',
                                    '--untracked-files=all').stdout,
                        'Read-only replica worktree is not clean')
                db.execute('INSERT INTO operations(id,record) VALUES (?,?)',
                           (request['operation_id'], json.dumps(marker)))
                db.commit(); checkpoint('prepared')

            head = workspace.git.head()
            require(head in {request['expected_base'], request['candidate_head']},
                    'Replica diverged during recovery')
            if head == request['expected_base']:
                require(workspace._branch() == request['ref']
                        and not git_run(workspace.git, 'status', '--porcelain',
                                        '--untracked-files=all').stdout,
                        'Read-only replica changed during recovery')
                with tempfile.NamedTemporaryFile(dir=workspace.journal.state) as bundle:
                    bundle.write(payload); bundle.flush(); os.fsync(bundle.fileno())
                    git_run(workspace.git, '-c', 'protocol.file.allow=always', 'fetch',
                            '--no-tags', bundle.name,
                            'refs/heads/main:' + staging)
                received = git_run(workspace.git, 'rev-parse', staging).stdout.strip()
                require(received == request['candidate_head'], 'Staged HEAD differs')
                validate_history(workspace.git, received, request['project_id'],
                                 frozenset(authority['spec']['privacy']))
                require(git_run(workspace.git, 'merge-base', '--is-ancestor',
                                request['expected_base'], received,
                                check=False).returncode == 0,
                        'Replica update is not a fast-forward')
                # Revalidate policy at the linearization boundary.
                self.administration.active_replication(
                    request['grant_id'], 'read-only-replica')
                checkpoint('staged')
                git_run(workspace.git, 'update-ref', request['ref'], received,
                        request['expected_base'])
                checkpoint('ref-updated')
            else:
                base_tree = git_run(workspace.git, 'rev-parse',
                                    request['expected_base'] + '^{tree}').stdout.strip()
                require(git_run(workspace.git, 'write-tree').stdout.strip() == base_tree
                        and git_run(workspace.git, 'diff-files', '--quiet',
                                    check=False).returncode == 0
                        and not git_run(workspace.git, 'ls-files', '--others',
                                        '--exclude-standard').stdout,
                        'Working copy changed after replication CAS')
            marker['state'] = 'committed'
            db.execute('UPDATE operations SET record=? WHERE id=?',
                       (json.dumps(marker), request['operation_id']))
            db.commit(); checkpoint('committed')
            git_run(workspace.git, 'read-tree', '--reset', '-u', request['candidate_head'])
            committed_project(workspace.git, request['candidate_head'],
                              request['project_id'])
            indexed = workspace.index.rebuild(workspace.git, checkpoint=checkpoint)
            require(indexed == request['candidate_head'], 'Replica changed during index rebuild')
            marker['state'] = 'indexed'
            db.execute('UPDATE operations SET record=?,done=1 WHERE id=?',
                       (json.dumps(marker), request['operation_id']))
            db.commit()
            git_run(workspace.git, 'update-ref', '-d', staging,
                    request['candidate_head'], check=False)
            checkpoint('completed')
            return request['candidate_head']

    def _initial(self, request, payload, authority, checkpoint):
        require(request['expected_base'] is None, 'Initial replica must not have a base')
        root = private_root(self.node)
        stage = root / 'replication-staging' / request['operation_id']
        stage.parent.mkdir(mode=0o700, exist_ok=True)
        stage.mkdir(mode=0o700, exist_ok=True)
        require(stage == stage.resolve() and stage.stat().st_uid == os.getuid()
                and not stage.stat().st_mode & 0o077,
                'Unsafe initial replication stage')
        intent = stage / 'intent.json'
        expected = canonical(request)
        if intent.exists():
            require(not intent.is_symlink() and intent.read_bytes() == expected,
                    'Initial replication intent changed')
        else:
            _exclusive_file(intent, expected)
        destination_parent = self.node.parent / 'projects'
        destination_parent.mkdir(mode=0o700, exist_ok=True)
        require(destination_parent == destination_parent.resolve()
                and destination_parent.stat().st_uid == os.getuid()
                and not destination_parent.stat().st_mode & 0o022,
                'Unsafe replica destination parent')
        destination = destination_parent / ('project-' + request['project_id'])
        repo = stage / 'repo'
        ready = stage / 'ready.json'
        if not repo.exists() and not destination.exists():
            with tempfile.TemporaryDirectory(prefix='initial-', dir=stage) as temporary:
                candidate = Path(temporary) / 'repo'; candidate.mkdir(mode=0o700)
                git = Git(candidate)
                git_run(git, 'init', '--template=', '--initial-branch=main')
                (candidate / '.git').chmod(0o700)
                with tempfile.NamedTemporaryFile(dir=stage) as bundle:
                    bundle.write(payload); bundle.flush(); os.fsync(bundle.fileno())
                    git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags',
                            bundle.name, 'refs/heads/main:refs/remotes/incoming/main')
                received = git_run(git, 'rev-parse',
                                   'refs/remotes/incoming/main').stdout.strip()
                require(received == request['candidate_head'], 'Initial replica HEAD differs')
                git_run(git, 'update-ref', 'refs/heads/main', received, '0' * 40)
                git_run(git, 'read-tree', '--reset', '-u', received)
                _sync_tree(candidate)
                os.rename(candidate, repo); sync_dir(stage)
        if repo.exists() and not ready.exists():
            git = Git(repo)
            received = git.head()
            require(received == request['candidate_head']
                    and not git_run(git, 'status', '--porcelain',
                                    '--untracked-files=all').stdout,
                    'Initial replica staging is incomplete')
            info = repo.stat()
            _exclusive_file(ready, json.dumps({
                'dev': info.st_dev, 'ino': info.st_ino, 'head': received,
            }, sort_keys=True).encode())
            checkpoint('initial-staged')
        require(ready.exists() and not ready.is_symlink(),
                'Initial replica staging is incomplete')
        identity = json.loads(ready.read_text())
        if not destination.exists():
            self.administration.active_replication(
                request['grant_id'], 'read-only-replica')
            os.rename(repo, destination); sync_dir(destination_parent)
            checkpoint('initial-published')
        info = destination.stat()
        require(info.st_dev == identity['dev'] and info.st_ino == identity['ino'],
                'Initial replica destination collision')
        git = Git(destination)
        require(git.head() == request['candidate_head']
                and not git_run(git, 'status', '--porcelain',
                                '--untracked-files=all').stdout,
                'Initial replica changed before registration')
        creator = ProjectCreation(self.node)
        if creator.database.exists():
            creator.recover()
        binding = self._binding(request['project_id'])
        if not binding:
            creator.register(destination, request['operation_id'], checkpoint=checkpoint)
        else:
            require(binding['root'] == str(destination),
                    'Project UUID is registered elsewhere')
        Projects(self.node).open(request['project_id'])
        checkpoint('completed')
        return request['candidate_head']

    def receive(self, envelope, payload, checkpoint=lambda stage: None):
        request, authority = self._authority(envelope, payload)
        self._validate_bundle(request, payload, authority['spec']['privacy'])
        digest, saved_receipt = self._store(envelope, payload)
        if saved_receipt:
            _verify(saved_receipt, authority['local']['fingerprint'], 'receipt')
            receipt = validate_receipt(saved_receipt['receipt'])
            require(receipt['request_sha256'] == digest,
                    'Stored receipt belongs to another request')
            return saved_receipt
        binding = self._binding(request['project_id'])
        if request['expected_base'] is None:
            head = self._initial(request, payload, authority, checkpoint)
        else:
            require(binding is not None, 'Existing replica is not registered')
            head = self._update(request, payload, authority, checkpoint)
        receipt = {
            'schema_version': 1,
            'operation_id': request['operation_id'],
            'request_sha256': digest,
            'grant_id': request['grant_id'],
            'project_id': request['project_id'],
            'ref': request['ref'],
            'status': 'applied',
            'head': head,
        }
        envelope_receipt = _signature(
            self.administration.root, validate_receipt(receipt),
            authority['local']['node_id'], 'receipt')
        with closing(sqlite3.connect(_journal_path(self.node), timeout=60)) as db:
            with db:
                changed = db.execute(
                    'UPDATE replication_inbound SET receipt=? '
                    'WHERE operation_id=? AND request_digest=? AND receipt IS NULL',
                    (canonical(envelope_receipt).decode('ascii'),
                     request['operation_id'], digest))
                require(changed.rowcount == 1, 'Replication receipt publication changed')
        return envelope_receipt


def prepare(node, replication_id, operation_id, expected_base, *, deployment='desktop'):
    require(expected_base is None or isinstance(expected_base, str)
            and HASH.fullmatch(expected_base), 'Invalid expected replica base')
    service = Administration(node, deployment=deployment)
    authority = service.active_replication(replication_id, 'primary')
    spec = authority['spec']
    context = {
        'kind': 'replication',
        'grant_id': replication_id,
        'project_id': spec['project_id'],
        'source_node_id': authority['local']['node_id'],
        'recipient_node_id': authority['remote']['node_id'],
        'privacy': spec['privacy'],
        'expected_base': expected_base,
    }
    from spikes.transfer_outbox import prepare_bundle
    payload, head, count = prepare_bundle(node, context, operation_id)
    current = service.active_replication(replication_id, 'primary')
    require(current['spec'] == spec and current['remote'] == authority['remote'],
            'Replication authority changed during bundle preparation')
    request = validate_request({
        'schema_version': 1,
        'operation_id': operation_id,
        'grant_id': replication_id,
        'grant_digest': hashlib.sha256(canonical(spec)).hexdigest(),
        'project_id': spec['project_id'],
        'ref': spec['ref'],
        'source_node_id': authority['local']['node_id'],
        'recipient_node_id': authority['remote']['node_id'],
        'expected_base': expected_base,
        'candidate_head': head,
        'bundle_size': len(payload),
        'bundle_sha256': hashlib.sha256(payload).hexdigest(),
    })
    envelope = _signature(service.root, request, authority['local']['node_id'], 'request')
    return envelope, payload, authority, count


def send(node, replication_id, operation_id, expected_base, *, ca=None,
         deployment='desktop'):
    envelope, payload, authority, count = prepare(
        node, replication_id, operation_id, expected_base, deployment=deployment)
    peer = authority['peer']; parsed = urlsplit(peer['endpoint'])
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            'Invalid replication peer endpoint')
    address = ipaddress.ip_address(parsed.hostname)
    require(address.version == 4 and address.is_private and not address.is_unspecified,
            'Replication peer must use a private IPv4 address')
    ca = Path(ca) if ca else private_root(node) / (peer['id'] + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(
        str(address), parsed.port or 443, context=context, timeout=30)
    try:
        connection.request('POST', PATH, body=encode_body(envelope, payload), headers={
            'Content-Type': CONTENT_TYPE,
            'Host': parsed.netloc,
        })
        response = connection.getresponse()
        raw = response.read(MAX_ENVELOPE + 1)
        require(response.status == 200 and len(raw) <= MAX_ENVELOPE,
                'Replication peer rejected request')
        receipt_envelope = json.loads(raw)
    finally:
        connection.close()
    _verify(receipt_envelope, authority['remote']['fingerprint'], 'receipt')
    receipt = validate_receipt(receipt_envelope['receipt'])
    require(receipt['operation_id'] == operation_id
            and receipt['request_sha256'] == request_digest(envelope['request'])
            and receipt['grant_id'] == replication_id
            and receipt['head'] == envelope['request']['candidate_head'],
            'Replication receipt does not match request')
    from spikes.transfer_outbox import complete
    complete(node, operation_id, envelope['request']['bundle_sha256'],
             canonical(receipt_envelope).decode('ascii'))
    return {'head': receipt['head'], 'commit_count': count, 'receipt': receipt_envelope}


def reply(handler):
    if (handler.single('Host') != handler.server.authority
            or handler.headers.get_all('Origin', [])
            or handler.headers.get_all('Authorization', [])
            or handler.headers.get_all('Transfer-Encoding')
            or handler.headers.get_all('Expect')
            or handler.single('Content-Type') != CONTENT_TYPE):
        return handler.send_error(403)
    length = handler.single('Content-Length')
    if (length is None or not length.isascii() or not length.isdecimal()
            or len(length) > len(str(MAX_BODY)) or not 4 < int(length) <= MAX_BODY):
        return handler.send_error(413)
    try:
        body = handler.rfile.read(int(length))
        require(len(body) == int(length), 'Incomplete replication body')
        envelope, payload = decode_body(body)
        result = ReplicationReceiver(
            handler.server.node, handler.server.administration).receive(envelope, payload)
        return handler.reply(200, result)
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError,
            RecoveryConflict, PendingOperation):
        return handler.reply(422, {'error': 'Replication request rejected'})
