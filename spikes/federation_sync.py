# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bidirectional, policy-scoped native Git bundle synchronization."""
import hashlib
import http.client
import ipaddress
import json
import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import ssl
import stat
import struct
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.administration import Administration, AccessDenied, identifier
from spikes.configuration import committed_project, parse_node, read_config
from spikes.federation_accounts import canonical
from spikes.git_transfer import MAX_BUNDLE, git_run, validate_history
from spikes.journal import sync_dir
from spikes.metadata import require
from spikes.network_backend import private_root
from spikes.project_creation import ProjectCreation
from spikes.project_replication import _signature, _verify
from spikes.projects import Projects
from spikes.storage import Git


PATH = '/v1/federation/content-sync'
CONTENT_TYPE = 'application/vnd.federated-workspace.content-sync-v1'
MAX_ENVELOPE = 64 * 1024
MAX_BODY = 4 + MAX_ENVELOPE + MAX_BUNDLE
HASH = re.compile(r'[a-f0-9]{40}|[a-f0-9]{64}')
MAX_REFS = 64
PRIVACY = frozenset({'public', 'project', 'confidential'})


class SyncConflict(ValueError):
    pass


class SyncRejected(ValueError):
    pass


def _journal_path(node):
    path = private_root(node) / 'federation-content-sync.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe content sync journal')
    finally:
        os.close(fd)
    return path


@contextmanager
def _database(node):
    db = sqlite3.connect(_journal_path(node), timeout=60)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS inbound (
                operation_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                envelope TEXT NOT NULL, bundle BLOB NOT NULL,
                response_envelope TEXT, response_bundle BLOB);
            CREATE TABLE IF NOT EXISTS outbound (
                peer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                operation_id TEXT NOT NULL, envelope TEXT NOT NULL,
                bundle BLOB NOT NULL, local_refs TEXT NOT NULL,
                PRIMARY KEY(peer_id, project_id));
            CREATE TABLE IF NOT EXISTS accepted (
                peer_id TEXT NOT NULL, project_id TEXT NOT NULL, refs TEXT NOT NULL,
                PRIMARY KEY(peer_id, project_id));
            CREATE TABLE IF NOT EXISTS runtime (
                peer_id TEXT NOT NULL, project_id TEXT NOT NULL, state TEXT NOT NULL,
                detail TEXT NOT NULL, last_sent TEXT NOT NULL, last_remote TEXT NOT NULL,
                PRIMARY KEY(peer_id, project_id));
        ''')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()


def _ref(value):
    if (not isinstance(value, str) or not value.startswith('refs/heads/')
            or len(value) > 255 or value.endswith(('/', '.'))
            or '..' in value or '@{' in value or '\\' in value
            or any(ord(char) < 33 or char in '~^:?*[' for char in value)):
        raise ValueError('Invalid shared branch ref')
    return value


def _refs(value):
    require(isinstance(value, list) and len(value) <= MAX_REFS,
            'Invalid shared branch inventory')
    result, seen = [], set()
    for item in value:
        require(isinstance(item, dict) and set(item) == {'ref', 'head'},
                'Invalid shared branch item')
        ref = _ref(item['ref'])
        require(isinstance(item['head'], str) and HASH.fullmatch(item['head'])
                and ref not in seen, 'Invalid shared branch head')
        seen.add(ref); result.append({'ref': ref, 'head': item['head']})
    require(result == sorted(result, key=lambda row: row['ref']),
            'Shared branch inventory must be sorted')
    return result


def _scope(value, level):
    require(isinstance(value, dict), 'Invalid sharing scope')
    if level == 'same-team':
        require(value == {'mode': 'all'}, 'Invalid same-team scope')
    else:
        require(set(value) == {'mode', 'branches', 'revision'}
                and value['mode'] in {'all-except-hidden', 'selected-only'}
                and type(value['revision']) is int and value['revision'] >= 1,
                'Invalid same-company scope')
        branches = [_ref(branch) for branch in value['branches']]
        require(branches == sorted(set(branches))
                and (value['mode'] != 'selected-only' or branches),
                'Invalid same-company branches')
    return value


def _scope_allows(scope, ref):
    if scope['mode'] == 'all':
        return True
    selected = ref in scope['branches']
    return selected if scope['mode'] == 'selected-only' else not selected


def validate_exchange(value):
    fields = {'schema_version', 'operation_id', 'project_id', 'source_node_id',
              'recipient_node_id', 'sharing_level', 'scope', 'refs',
              'known_remote_refs', 'bundle_size', 'bundle_sha256'}
    require(isinstance(value, dict) and set(value) == fields
            and value['schema_version'] == 1, 'Invalid content sync exchange')
    for field in ('operation_id', 'project_id', 'source_node_id', 'recipient_node_id'):
        identifier(value[field])
    require(value['source_node_id'] != value['recipient_node_id']
            and value['sharing_level'] in {'same-team', 'same-company'},
            'Invalid content sync participants')
    scope = _scope(value['scope'], value['sharing_level'])
    refs = _refs(value['refs']); _refs(value['known_remote_refs'])
    require(all(_scope_allows(scope, row['ref']) for row in refs),
            'Branch inventory exceeds signed scope')
    require(type(value['bundle_size']) is int
            and 0 <= value['bundle_size'] <= MAX_BUNDLE,
            'Invalid content sync bundle size')
    require(isinstance(value['bundle_sha256'], str)
            and re.fullmatch(r'[a-f0-9]{64}', value['bundle_sha256']),
            'Invalid content sync bundle digest')
    require((value['bundle_size'] == 0) == (not refs),
            'Empty content sync transfer must have no refs')
    return value


def encode_body(envelope, payload):
    raw = canonical(envelope)
    require(0 < len(raw) <= MAX_ENVELOPE and len(payload) <= MAX_BUNDLE,
            'Content sync body exceeds limits')
    return struct.pack('!I', len(raw)) + raw + payload


def decode_body(body):
    require(isinstance(body, bytes) and 4 < len(body) <= MAX_BODY,
            'Invalid content sync body')
    size = struct.unpack('!I', body[:4])[0]
    require(0 < size <= MAX_ENVELOPE and 4 + size <= len(body),
            'Invalid content sync envelope size')
    from spikes.metadata import parse_json
    return parse_json(body[4:4 + size], MAX_ENVELOPE), body[4 + size:]


def _authority(service, peer_id):
    identifier(peer_id)
    with service.locked() as (_, state, commit, _):
        peer = next((row for row in state['peers'] if row['id'] == peer_id), None)
        if (not peer or peer['trust'] != 'approved'
                or peer['sharing_level'] not in {'same-team', 'same-company'}):
            raise AccessDenied('Content sync requires an approved internal peer')
        return state['node_id'], dict(peer), list(state['project_shares']), commit


def _policy(peer, shares, project_id):
    if peer['sharing_level'] == 'same-team':
        return {'mode': 'all'}
    share = next((row for row in shares
                  if row['peer_id'] == peer['id']
                  and row['project_id'] == project_id), None)
    if not share:
        return None
    return {'mode': share['branch_mode'], 'branches': share['branches'],
            'revision': share['revision']}


def _binding(node, project_id):
    parsed = parse_node(read_config(node), location=node)
    return next((row for row in parsed['projects']
                 if row['project_id'] == project_id), None)


def _inventory(git, scope):
    raw = git_run(git, 'for-each-ref', '--format=%(refname) %(objectname)',
                  'refs/heads/').stdout.splitlines()
    rows = []
    for line in raw:
        ref, head = line.split(' ', 1)
        _ref(ref)
        if _scope_allows(scope, ref):
            require(HASH.fullmatch(head), 'Invalid local branch head')
            rows.append({'ref': ref, 'head': head})
    return sorted(rows, key=lambda row: row['ref'])


def _build_bundle(node, project_id, scope):
    binding = _binding(node, project_id)
    if binding is None:
        return [], b''
    workspace = Projects(node).workspace(project_id, blocking=False)
    with workspace.journal.lock(), workspace.journal.connect() as db:
        workspace._branch(); workspace._read_locked(db)
        require(not git_run(workspace.git, 'status', '--porcelain',
                            '--untracked-files=all').stdout,
                'Shared project worktree must be clean')
        refs = _inventory(workspace.git, scope)
        require(refs, 'Sharing scope selects no local branch')
        for row in refs:
            validate_history(workspace.git, row['head'], project_id, PRIVACY)
        with tempfile.TemporaryDirectory(prefix='sharing-sync-') as directory:
            bundle = Path(directory) / 'project.bundle'
            git_run(workspace.git, 'bundle', 'create', str(bundle),
                    *[row['ref'] for row in refs])
            require(bundle.stat().st_size <= MAX_BUNDLE,
                    'Content sync bundle exceeds 64 MiB')
            payload = bundle.read_bytes()
        require(_inventory(workspace.git, scope) == refs,
                'Shared branches changed during bundle preparation')
        return refs, payload


def _verify_bundle(node, exchange, payload):
    require(len(payload) == exchange['bundle_size']
            and hashlib.sha256(payload).hexdigest() == exchange['bundle_sha256'],
            'Content sync bundle differs from signed exchange')
    if not payload:
        return
    root = private_root(node)
    with tempfile.TemporaryDirectory(prefix='sharing-verify-', dir=root) as directory:
        directory = Path(directory)
        bundle = directory / 'project.bundle'; bundle.write_bytes(payload)
        repo = directory / 'repo.git'; repo.mkdir(mode=0o700)
        git = Git(repo); git_run(git, 'init', '--bare', '--template=')
        listed = git_run(git, 'bundle', 'list-heads', str(bundle)).stdout.splitlines()
        actual = sorted([{'head': line.split()[0], 'ref': line.split()[1]}
                         for line in listed], key=lambda row: row['ref'])
        require(actual == exchange['refs'], 'Git bundle refs differ from signed inventory')
        git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags',
                str(bundle), *[row['ref'] + ':' + row['ref'] for row in actual])
        for row in actual:
            validate_history(git, row['head'], exchange['project_id'], PRIVACY)


def _stage_refs(git, payload, operation_id, refs, directory):
    with tempfile.NamedTemporaryFile(dir=directory) as bundle:
        bundle.write(payload); bundle.flush(); os.fsync(bundle.fileno())
        mappings = []
        for row in refs:
            suffix = row['ref'][len('refs/heads/'):]
            target = 'refs/workspace/sharing/' + operation_id + '/' + suffix
            mappings.append(row['ref'] + ':' + target)
        git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags',
                bundle.name, *mappings)


def _apply_existing(node, exchange, payload, checkpoint, authorize):
    project_id = exchange['project_id']; operation_id = exchange['operation_id']
    workspace = Projects(node).workspace(project_id, blocking=False)
    current_ref = workspace._branch()
    conflict = False; current_update = None
    with workspace.journal.lock(), workspace.journal.connect() as db:
        existing_operation = db.execute(
            'SELECT record,done FROM operations WHERE id=?',
            (operation_id,)).fetchone()
        active = workspace._active(db)
        require((not active or active.get('operation_id') == operation_id)
                and not db.execute('SELECT 1 FROM pending').fetchone(),
                'Project has another unfinished operation')
        if existing_operation and not existing_operation[1]:
            saved = json.loads(existing_operation[0])
            require(saved.get('kind') == 'external-replication'
                    and saved.get('request_digest')
                    == hashlib.sha256(canonical(exchange)).hexdigest(),
                    'Project operation ID belongs to another sync')
            require(workspace.git.head() == saved['commit_id'],
                    'Interrupted content sync HEAD changed')
            git_run(workspace.git, 'read-tree', '--reset', '-u', saved['commit_id'])
            committed_project(workspace.git, saved['commit_id'], project_id)
            indexed = workspace.index.rebuild(workspace.git, checkpoint=checkpoint)
            require(indexed == saved['commit_id'],
                    'Project changed during content sync recovery')
            saved['state'] = 'indexed'
            db.execute('UPDATE operations SET record=?,done=1 WHERE id=?',
                       (json.dumps(saved), operation_id)); db.commit()
        require(not git_run(workspace.git, 'status', '--porcelain',
                            '--untracked-files=all').stdout,
                'Shared project worktree must be clean')
        _stage_refs(workspace.git, payload, operation_id, exchange['refs'],
                    workspace.journal.state)
        authorize()
        for row in exchange['refs']:
            ref, candidate = row['ref'], row['head']
            suffix = ref[len('refs/heads/'):]
            stage = 'refs/workspace/sharing/' + operation_id + '/' + suffix
            received = git_run(workspace.git, 'rev-parse', stage).stdout.strip()
            require(received == candidate, 'Staged branch differs from signed inventory')
            local_result = git_run(workspace.git, 'rev-parse', '--verify', ref,
                                   check=False)
            local = local_result.stdout.strip() if local_result.returncode == 0 else None
            if local == candidate:
                continue
            if local is None or git_run(workspace.git, 'merge-base', '--is-ancestor',
                                        local, candidate, check=False).returncode == 0:
                if ref == current_ref:
                    current_update = (local, candidate)
                else:
                    git_run(workspace.git, 'update-ref', ref, candidate,
                            local or '0' * 40)
            elif git_run(workspace.git, 'merge-base', '--is-ancestor',
                         candidate, local, check=False).returncode != 0:
                incoming = ('refs/federation/incoming/'
                            + exchange['source_node_id'] + '/'
                            + operation_id + '/' + suffix)
                old = git_run(workspace.git, 'rev-parse', '--verify', incoming,
                              check=False)
                git_run(workspace.git, 'update-ref', incoming, candidate,
                        old.stdout.strip() if old.returncode == 0 else '0' * 40)
                conflict = True
        if current_update:
            base, candidate = current_update
            marker = {'kind': 'external-replication', 'operation_id': operation_id,
                      'request_digest': hashlib.sha256(canonical(exchange)).hexdigest(),
                      'base_head': base, 'commit_id': candidate,
                      'branch': current_ref, 'state': 'prepared'}
            row = db.execute('SELECT record,done FROM operations WHERE id=?',
                             (operation_id,)).fetchone()
            if row:
                saved = json.loads(row[0])
                require(all(saved.get(key) == value for key, value in marker.items()
                            if key != 'state'),
                        'Project operation ID belongs to another sync')
            else:
                db.execute('INSERT INTO operations(id,record) VALUES (?,?)',
                           (operation_id, json.dumps(marker)))
                db.commit(); checkpoint('prepared')
            head = workspace.git.head()
            require(head in {base, candidate}, 'Current branch changed during sync')
            if head == base:
                git_run(workspace.git, 'update-ref', current_ref, candidate, base)
                checkpoint('ref-updated')
            marker['state'] = 'committed'
            db.execute('UPDATE operations SET record=? WHERE id=?',
                       (json.dumps(marker), operation_id)); db.commit()
            git_run(workspace.git, 'read-tree', '--reset', '-u', candidate)
            committed_project(workspace.git, candidate, project_id)
            indexed = workspace.index.rebuild(workspace.git, checkpoint=checkpoint)
            require(indexed == candidate, 'Project changed during sync index rebuild')
            marker['state'] = 'indexed'
            db.execute('UPDATE operations SET record=?,done=1 WHERE id=?',
                       (json.dumps(marker), operation_id)); db.commit()
        for row in exchange['refs']:
            suffix = row['ref'][len('refs/heads/'):]
            git_run(workspace.git, 'update-ref', '-d',
                    'refs/workspace/sharing/' + operation_id + '/' + suffix,
                    row['head'], check=False)
    return conflict


def _sync_tree(root):
    for parent, _, names in os.walk(root):
        for name in names:
            fd = os.open(Path(parent) / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_dir(parent)


def _apply_initial(node, exchange, payload, checkpoint, authorize):
    root = private_root(node)
    stage = root / 'sharing-staging' / exchange['operation_id']
    stage.parent.mkdir(mode=0o700, exist_ok=True); stage.mkdir(mode=0o700, exist_ok=True)
    require(stage == stage.resolve() and stage.stat().st_uid == os.getuid()
            and not stage.stat().st_mode & 0o077,
            'Unsafe sharing stage')
    destination_parent = Path(node).parent / 'projects'
    destination_parent.mkdir(mode=0o700, exist_ok=True)
    require(destination_parent == destination_parent.resolve()
            and destination_parent.stat().st_uid == os.getuid()
            and not destination_parent.stat().st_mode & 0o022,
            'Unsafe shared project destination parent')
    destination = destination_parent / ('project-' + exchange['project_id'])
    repo = stage / 'repo'
    intent = stage / 'intent.json'; expected_intent = canonical(exchange)
    if intent.exists():
        require(not intent.is_symlink() and intent.read_bytes() == expected_intent,
                'Initial sharing intent changed')
    else:
        fd = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(expected_intent); handle.flush(); os.fsync(handle.fileno())
        sync_dir(stage)
    chosen = next((row['ref'] for row in exchange['refs']
                   if row['ref'] == 'refs/heads/main'), exchange['refs'][0]['ref'])
    ready = stage / 'ready.json'
    if not repo.exists() and not destination.exists():
        repo.mkdir(mode=0o700)
        git = Git(repo); git_run(git, 'init', '--template=',
                                 '--initial-branch=' + chosen[len('refs/heads/'):])
        (repo / '.git').chmod(0o700)
        _stage_refs(git, payload, exchange['operation_id'], exchange['refs'], stage)
        for row in exchange['refs']:
            suffix = row['ref'][len('refs/heads/'):]
            source = 'refs/workspace/sharing/' + exchange['operation_id'] + '/' + suffix
            git_run(git, 'update-ref', row['ref'], row['head'], '0' * 40)
            git_run(git, 'update-ref', '-d', source, row['head'])
        git_run(git, 'symbolic-ref', 'HEAD', chosen)
        git_run(git, 'read-tree', '--reset', '-u', dict(
            (row['ref'], row['head']) for row in exchange['refs'])[chosen])
        _sync_tree(repo)
    if repo.exists() and not ready.exists():
        git = Git(repo)
        require(_inventory(git, {'mode': 'all'}) == exchange['refs']
                and not git_run(git, 'status', '--porcelain',
                                '--untracked-files=all').stdout,
                'Initial sharing stage differs from signed inventory')
        info = repo.stat()
        fd = os.open(ready, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'dev': info.st_dev, 'ino': info.st_ino}, handle,
                      sort_keys=True)
            handle.flush(); os.fsync(handle.fileno())
        sync_dir(stage); checkpoint('initial-staged')
    require(ready.exists() and not ready.is_symlink(),
            'Initial sharing stage is incomplete')
    identity = json.loads(ready.read_text())
    if not destination.exists():
        authorize()
        os.rename(repo, destination); sync_dir(destination_parent)
        checkpoint('initial-published')
    info = destination.stat()
    require(info.st_dev == identity['dev'] and info.st_ino == identity['ino'],
            'Initial sharing destination collision')
    git = Git(destination)
    require(committed_project(git, git.head(), exchange['project_id']),
            'Initial shared project metadata differs')
    creator = ProjectCreation(node)
    if creator.database.exists():
        creator.recover()
    if _binding(node, exchange['project_id']) is None:
        creator.register(destination, exchange['operation_id'], checkpoint=checkpoint)
    else:
        require(_binding(node, exchange['project_id'])['root'] == str(destination),
                'Shared project UUID is registered elsewhere')
    Projects(node).open(exchange['project_id'])
    return False


def _apply(node, exchange, payload, checkpoint=lambda stage: None,
           authorize=lambda: None):
    if not payload:
        return False
    _verify_bundle(node, exchange, payload)
    if _binding(node, exchange['project_id']) is None:
        return _apply_initial(node, exchange, payload, checkpoint, authorize)
    return _apply_existing(node, exchange, payload, checkpoint, authorize)


def _prepare(service, peer_id, project_id, operation_id, known_remote_refs,
             *, force_bundle):
    local_id, peer, shares, commit = _authority(service, peer_id)
    scope = _policy(peer, shares, project_id)
    refs, payload = ([], b'') if scope is None else _build_bundle(
        service.node, project_id, scope)
    if not force_bundle:
        payload = b''
    current = _authority(service, peer_id)
    require(current == (local_id, peer, shares, commit),
            'Sharing policy changed during sync preparation')
    exchange = validate_exchange({
        'schema_version': 1, 'operation_id': operation_id,
        'project_id': project_id, 'source_node_id': local_id,
        'recipient_node_id': peer_id, 'sharing_level': peer['sharing_level'],
        'scope': scope or ({'mode': 'all'} if peer['sharing_level'] == 'same-team'
                           else {'mode': 'selected-only', 'branches': ['refs/heads/main'],
                                 'revision': 1}),
        'refs': refs if payload else [],
        'known_remote_refs': _refs(known_remote_refs),
        'bundle_size': len(payload),
        'bundle_sha256': hashlib.sha256(payload).hexdigest(),
    })
    return _signature(service.root, exchange, local_id, 'exchange'), payload, peer, refs


class SyncReceiver:
    def __init__(self, node, administration=None):
        self.node = Path(node).absolute()
        self.service = administration or Administration(self.node)

    def receive(self, envelope, payload, checkpoint=lambda stage: None):
        require(isinstance(envelope, dict) and isinstance(envelope.get('exchange'), dict),
                'Missing content sync exchange')
        exchange = validate_exchange(envelope['exchange'])
        local_id, peer, _, _ = _authority(self.service, exchange['source_node_id'])
        require(exchange['recipient_node_id'] == local_id
                and exchange['sharing_level'] == peer['sharing_level']
                and envelope.get('signer_node_id') == peer['id'],
                'Content sync exchange does not match relationship')
        _verify(envelope, peer['fingerprint'], 'exchange')
        _verify_bundle(self.node, exchange, payload)
        digest = hashlib.sha256(canonical(envelope) + payload).hexdigest()
        encoded = canonical(envelope).decode('ascii')
        with _database(self.node) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT request_digest,envelope,bundle,'
                             'response_envelope,response_bundle FROM inbound '
                             'WHERE operation_id=?', (exchange['operation_id'],)).fetchone()
            if row:
                require(row[0] == digest and row[1] == encoded
                        and bytes(row[2]) == payload,
                        'Content sync operation ID belongs to another request')
                if row[3] is not None:
                    return json.loads(row[3]), bytes(row[4])
            else:
                db.execute('INSERT INTO inbound VALUES (?,?,?,?,NULL,NULL)',
                           (exchange['operation_id'], digest, encoded, payload))
        def authorize():
            current_id, current_peer, _, _ = _authority(
                self.service, exchange['source_node_id'])
            require(current_id == local_id
                    and current_peer['fingerprint'] == peer['fingerprint']
                    and current_peer['sharing_level'] == exchange['sharing_level'],
                    'Content sync authority changed before publication')
        conflict = _apply(self.node, exchange, payload, checkpoint, authorize)
        with _database(self.node) as db:
            if payload:
                db.execute('INSERT OR REPLACE INTO accepted VALUES (?,?,?)',
                           (peer['id'], exchange['project_id'],
                            canonical(exchange['refs']).decode('ascii')))
            accepted = db.execute('SELECT refs FROM accepted WHERE peer_id=? '
                                  'AND project_id=?',
                                  (peer['id'], exchange['project_id'])).fetchone()
        known = exchange['known_remote_refs']
        response, response_payload, _, local_refs = _prepare(
            self.service, peer['id'], exchange['project_id'],
            exchange['operation_id'], exchange['refs'],
            force_bundle=True)
        response_exchange = response['exchange']
        if local_refs == known:
            response_exchange = dict(response_exchange, refs=[], bundle_size=0,
                                     bundle_sha256=hashlib.sha256(b'').hexdigest())
            response = _signature(self.service.root, validate_exchange(response_exchange),
                                  local_id, 'exchange')
            response_payload = b''
        response = dict(response, accepted_source_refs=(json.loads(accepted[0])
                        if accepted else []), conflict=conflict)
        raw_response = canonical(response).decode('ascii')
        with _database(self.node) as db:
            changed = db.execute('UPDATE inbound SET response_envelope=?,response_bundle=? '
                                 'WHERE operation_id=? AND response_envelope IS NULL',
                                 (raw_response, response_payload,
                                  exchange['operation_id']))
            require(changed.rowcount == 1, 'Content sync response publication changed')
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)', (
                peer['id'], exchange['project_id'],
                'conflict' if conflict else 'idle',
                'Divergent history preserved' if conflict else 'Content synchronized',
                canonical(local_refs).decode('ascii'),
                canonical(exchange['refs'] if payload else
                          (json.loads(accepted[0]) if accepted else [])).decode('ascii')))
        return response, response_payload


def synchronize(node, peer_id, project_id, *, deployment='desktop', ca=None):
    service = Administration(node, deployment=deployment)
    with _database(node) as db:
        runtime = db.execute('SELECT last_sent,last_remote FROM runtime '
                             'WHERE peer_id=? AND project_id=?',
                             (peer_id, project_id)).fetchone()
        pending = db.execute('SELECT operation_id,envelope,bundle,local_refs '
                             'FROM outbound WHERE peer_id=? AND project_id=?',
                             (peer_id, project_id)).fetchone()
    last_sent = json.loads(runtime[0]) if runtime else []
    last_remote = json.loads(runtime[1]) if runtime else []
    if pending:
        operation_id = pending[0]; envelope = json.loads(pending[1])
        payload = bytes(pending[2]); local_refs = json.loads(pending[3])
        local_id, peer, shares, _ = _authority(service, peer_id)
        current_scope = _policy(peer, shares, project_id)
        expected_scope = (current_scope or
                          ({'mode': 'all'} if peer['sharing_level'] == 'same-team'
                           else {'mode': 'selected-only',
                                 'branches': ['refs/heads/main'], 'revision': 1}))
        if (envelope['exchange']['source_node_id'] != local_id
                or envelope['exchange']['sharing_level'] != peer['sharing_level']
                or envelope['exchange']['scope'] != expected_scope):
            # A narrowed/revoked policy must never resend stale bytes. A peer
            # that already received them cannot be made to forget them.
            with _database(node) as db:
                db.execute('DELETE FROM outbound WHERE peer_id=? AND project_id=?',
                           (peer_id, project_id))
            return synchronize(node, peer_id, project_id,
                               deployment=deployment, ca=ca)
    else:
        operation_id = str(uuid4())
        envelope, payload, peer, local_refs = _prepare(
            service, peer_id, project_id, operation_id, last_remote,
            force_bundle=True)
        if local_refs == last_sent:
            exchange = dict(envelope['exchange'], refs=[], bundle_size=0,
                            bundle_sha256=hashlib.sha256(b'').hexdigest())
            envelope = _signature(service.root, validate_exchange(exchange),
                                  exchange['source_node_id'], 'exchange')
            payload = b''
        with _database(node) as db:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                       (peer_id, project_id, operation_id,
                        canonical(envelope).decode('ascii'), payload,
                        canonical(local_refs).decode('ascii')))
    if not peer.get('endpoint'):
        raise AccessDenied('Peer can synchronize content only when it connects')
    parsed = urlsplit(peer['endpoint'])
    require(parsed.scheme == 'https' and not parsed.path.strip('/')
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment,
            'Invalid content sync peer endpoint')
    address = ipaddress.ip_address(parsed.hostname)
    require(address.version == 4 and not address.is_unspecified
            and (address.is_private or address.is_loopback),
            'Content sync peer must use a private IPv4 address')
    ca = Path(ca) if ca else private_root(node) / (peer_id + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(
        str(address), parsed.port or 443, context=context, timeout=60)
    try:
        connection.request('POST', PATH, body=encode_body(envelope, payload), headers={
            'Content-Type': CONTENT_TYPE, 'Host': parsed.netloc})
        response = connection.getresponse(); body = response.read(MAX_BODY + 1)
        require(len(body) <= MAX_BODY, 'Content sync response exceeds limit')
        if response.status == 409:
            raise SyncConflict('Peer reported a content conflict')
        if response.status != 200:
            raise SyncRejected('Peer rejected content sync')
        response_envelope, response_payload = decode_body(body)
    finally:
        connection.close()
    require(set(response_envelope) == {'exchange', 'signer_node_id', 'public_key',
                                       'signature', 'accepted_source_refs', 'conflict'},
            'Invalid content sync response')
    require(type(response_envelope['conflict']) is bool,
            'Invalid content sync conflict state')
    returned = validate_exchange(_verify(
        {key: response_envelope[key] for key in
         ('exchange', 'signer_node_id', 'public_key', 'signature')},
        peer['fingerprint'], 'exchange')['exchange'])
    require(returned['operation_id'] == operation_id
            and returned['source_node_id'] == peer_id
            and returned['recipient_node_id'] == envelope['exchange']['source_node_id']
            and returned['project_id'] == project_id,
            'Content sync response does not match request')
    def authorize_response():
        current_id, current_peer, _, _ = _authority(service, peer_id)
        require(current_id == envelope['exchange']['source_node_id']
                and current_peer['fingerprint'] == peer['fingerprint']
                and current_peer['sharing_level'] == returned['sharing_level'],
                'Content sync authority changed before response publication')
    conflict = _apply(node, returned, response_payload,
                      authorize=authorize_response)
    accepted = _refs(response_envelope['accepted_source_refs'])
    sent = local_refs if accepted == local_refs else last_sent
    remote = returned['refs'] if response_payload else last_remote
    state = 'conflict' if conflict or response_envelope['conflict'] else 'idle'
    with _database(node) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)',
                   (peer_id, project_id, state,
                    'Divergent history preserved' if state == 'conflict'
                    else 'Content synchronized',
                    canonical(sent).decode('ascii'), canonical(remote).decode('ascii')))
        db.execute('DELETE FROM outbound WHERE peer_id=? AND project_id=?',
                   (peer_id, project_id))
    return {'state': state, 'local_refs': sent, 'remote_refs': remote}


class ContentSyncControl:
    def __init__(self, node, *, deployment):
        self.node = Path(node).absolute(); self.deployment = deployment
        self.service = Administration(node, deployment=deployment)

    def statuses(self):
        with _database(self.node) as db:
            rows = db.execute('SELECT peer_id,project_id,state,detail FROM runtime').fetchall()
        return {peer + ':' + project: {'state': state, 'detail': detail}
                for peer, project, state, detail in rows}

    def synchronize(self, peer_id, project_id):
        try:
            root = private_root(self.node)
            fd = os.open(root / 'federation-content-sync.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                return synchronize(self.node, peer_id, project_id,
                                   deployment=self.deployment)
        except SyncConflict as exc:
            state = 'conflict'; detail = str(exc); error = exc
        except (AccessDenied, SyncRejected) as exc:
            state = 'rejected'; detail = str(exc); error = exc
        except (ConnectionError, TimeoutError, ssl.SSLError, OSError) as exc:
            state = 'offline'; detail = type(exc).__name__; error = exc
        except (ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
            state = 'error'; detail = str(exc); error = exc
        with _database(self.node) as db:
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)',
                       (peer_id, project_id, state, detail, '[]', '[]'))
        raise error

    def run_automatic(self):
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = self.service.request(actor, {'action': 'list'})
        from spikes.federation_catalog import CatalogStore
        remote = CatalogStore(self.node).projections()
        local = {row['id'] for row in Projects(self.node).catalog() if row['available']}
        for peer in state['peers']:
            if (peer['trust'] != 'approved'
                    or peer['sharing_level'] not in {'same-team', 'same-company'}
                    or not peer.get('endpoint')):
                continue
            projects = set(local)
            projects.update(row['project_id'] for row in remote
                            if row['peer_id'] == peer['id'])
            if peer['sharing_level'] == 'same-company':
                local_selected = {row['project_id'] for row in state['project_shares']
                                  if row['peer_id'] == peer['id']}
                remote_selected = {row['project_id'] for row in remote
                                   if row['peer_id'] == peer['id']}
                projects &= local_selected | remote_selected
            for project_id in sorted(projects):
                try:
                    self.synchronize(peer['id'], project_id)
                except Exception:
                    pass


class ContentSyncScheduler:
    def __init__(self, node, *, deployment, interval=60):
        self.control = ContentSyncControl(node, deployment=deployment)
        self.interval = interval; self.stopping = threading.Event(); self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run,
                                           name='federation-content-sync', daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            self.control.run_automatic(); self.stopping.wait(self.interval)

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=65); self.thread = None


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
            or len(length) > len(str(MAX_BODY))
            or not 4 < int(length) <= MAX_BODY):
        return handler.send_error(413)
    try:
        body = handler.rfile.read(int(length))
        require(len(body) == int(length), 'Incomplete content sync body')
        envelope, payload = decode_body(body)
        response, response_payload = SyncReceiver(
            handler.server.node, handler.server.administration).receive(envelope, payload)
        raw = encode_body(response, response_payload)
        handler.send_response(200); handler.send_header('Content-Type', CONTENT_TYPE)
        handler.send_header('Content-Length', str(len(raw))); handler.end_headers()
        handler.wfile.write(raw)
    except SyncConflict:
        return handler.reply(409, {'error': 'Content histories diverged'})
    except (ValueError, AccessDenied, OSError, sqlite3.Error, subprocess.SubprocessError):
        return handler.reply(422, {'error': 'Content sync request rejected'})
