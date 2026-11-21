# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bidirectional, policy-scoped native Git bundle synchronization."""
from spikes.http_request_budget import RequestReadTimeout
import hashlib
import json
import os
import fcntl
from collections import deque
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from spikes.request_ownership import ProjectBusy, bounded_project_requests, bounded_process_lock, safe_busy_resource
from spikes.background_workers import report_failure
from spikes.peer_transport import (BACKGROUND_RECEIVE_BUDGET, CONTENT_RECEIVE_BUDGET,
                                   CONTENT_SYNC_MAX_WAIT, CONTENT_SYNC_TIMEOUT,
                                   HEARTBEAT_IDLE_TIMEOUT, private_peer_endpoint,
                                   stop_timeout)
import re
import sqlite3
import ssl
import stat
import struct
import subprocess
import tempfile
import threading
import logging
import time
from uuid import uuid4

from spikes.administration import (
    Administration, AccessDenied, content_policy, content_policy_allows,
    identifier,
)
from spikes.configuration import committed_project, parse_node, read_config
from spikes.federation_accounts import MappingSignatures, canonical
from spikes.http_deadline import DeadlineHTTPSConnection
from spikes.git_budget import GitDeadlineExceeded, git_budget
from spikes.git_transfer import MAX_BUNDLE, git_run
from spikes.history_validation import validate_histories
from spikes.sync_retry import automatic_retry
from spikes.journal import sync_dir
from spikes.metadata import peer_unsupported_version, require, require_version
from spikes.network_backend import private_root
from spikes.project_creation import ProjectCreation
from spikes.project_replication import _signature, _verify
from spikes.project_chat_sync import (
    MAX_CHAT_PAYLOAD, active_mapping_count,
    apply_payload as apply_chat_payload,
    export_project as export_project_chats, inventory as chat_inventory,
    validate_export_authority, validate_payload as validate_chat_payload,
)
from spikes.projects import Projects
from spikes.sqlite_ownership import sqlite_connection
from spikes.storage import Git
from spikes.sync_diagnostics import (observed, received, phase, peer_progress,
                                     snapshot as sync_diagnostic, current_phase, safe_peer_phase)
from spikes.content_receive_jobs import STREAM_TYPE, read_frames



PATH = '/v1/federation/content-sync'
CONTENT_TYPE = 'application/vnd.federated-workspace.content-sync-v2'
MAX_ENVELOPE = 64 * 1024
MAX_POOL_PAYLOAD = 8 * 1024 * 1024
MAX_BODY = 4 + MAX_ENVELOPE + MAX_BUNDLE + MAX_CHAT_PAYLOAD + MAX_POOL_PAYLOAD
HASH = re.compile(r'[a-f0-9]{40}|[a-f0-9]{64}')
MAX_REFS = 64
PRIVACY = frozenset({'public', 'project', 'confidential'})


@dataclass(frozen=True, repr=False)
class _VerifiedInboundBundle:
    """Request-local proof of the exact Git bytes validated before publication."""
    operation_id: str
    project_id: str
    source_node_id: str
    recipient_node_id: str
    source_fingerprint: str
    scope: bytes
    refs: tuple
    payload: bytes


class SyncConflict(ValueError):
    pass


class SyncRejected(ValueError):
    pass


class SyncCancelled(Exception):
    pass


class PeerTimeout(TimeoutError):
    """The peer accepted the connection but did not answer within the budget.

    Not "offline" (AUDIT-B7-T1): the peer is reachable and may still be
    working on the same saved operation, which the next attempt replays.
    """


class OutboundDeferred(Exception):
    """Another outbound sync of this node owns the send lane (AUDIT-B7-T1).

    Raised only for a caller that asked to skip instead of wait (automatic
    checks). Nothing was started: no runtime state, diagnostic or journal
    entry is written, so the visible state stays that of the last real run.
    """
    not_started = True


class SyncBusy(Exception):
    """Transient refusal; diagnostic codes never authorize recovery/retry."""
    def __init__(self, message='Content sync is busy', *, resource='unknown', peer_phase=None):
        super().__init__(message)
        self.busy_resource = safe_busy_resource(resource)
        self.peer_phase = safe_peer_phase(peer_phase) or safe_peer_phase(current_phase())


@contextmanager
def _inbound_lock(node):
    # Separate from the outbound lock: two nodes must be able to receive while
    # their outbound workers wait for the other node's response. This lock also
    # covers callers through a second listener and direct/native receivers.
    path = private_root(node) / 'federation-content-receive.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe content receive lock')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncBusy('Content receiver is busy', resource='incoming-capacity') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


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
    from spikes.sqlite_ownership import sqlite_connection
    with sqlite_connection(_journal_path(node), timeout=60,
                           resource='Content synchronization journal') as db:
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
            CREATE TABLE IF NOT EXISTS prepared_states (
                operation_id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS response_states (
                operation_id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS confirmed_states (
                peer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                local_state TEXT NOT NULL, remote_state TEXT NOT NULL,
                PRIMARY KEY(peer_id, project_id));
            CREATE TABLE IF NOT EXISTS settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                revision INTEGER NOT NULL CHECK(revision>=0),
                automatic_enabled INTEGER NOT NULL CHECK(automatic_enabled IN (0,1)));
        ''')
        yield db


def _sync_state(value):
    if value is None:
        return {'refs': [], 'chats': []}
    parsed = json.loads(value) if isinstance(value, str) else value
    # Journals written by protocol v1 contained only the ref inventory.
    if isinstance(parsed, list):
        return {'refs': _refs(parsed), 'chats': []}
    require(isinstance(parsed, dict) and set(parsed) == {'refs', 'chats'},
            'Invalid stored content sync state')
    return {'refs': _refs(parsed['refs']), 'chats': _chat_inventory(parsed['chats'])}


def project_conflict_statuses(node, project_id):
    """Read the last peer conflict reports without starting/recovering sync."""
    node = Path(node).absolute()
    root = node.parent / ('.' + node.name + '.network')
    if not root.exists():
        return []
    path = private_root(node) / 'federation-content-sync.sqlite'
    if not path.exists():
        return []
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and not info.st_mode & 0o077, 'Unsafe content sync journal')
    with sqlite_connection(path.as_uri() + '?mode=ro', uri=True, timeout=2,
                           resource='Content sync conflict status') as db:
        return [{'peer_id': row[0]} for row in db.execute(
            "SELECT peer_id FROM runtime WHERE project_id=? AND state='conflict' ORDER BY peer_id",
            (project_id,))]


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
    return content_policy_allows(scope, ref)


EXCHANGE_VERSIONS = frozenset({2, 3})


def validate_exchange(value):
    fields = {'schema_version', 'operation_id', 'project_id', 'source_node_id',
              'recipient_node_id', 'sharing_level', 'scope', 'refs',
              'known_remote_refs', 'bundle_size', 'bundle_sha256',
              'chat_inventory', 'known_remote_chats', 'chat_size',
              'chat_sha256'}
    require(isinstance(value, dict), 'Invalid content sync exchange')
    require_version(value.get('schema_version'), EXCHANGE_VERSIONS, 'content-sync')
    if value['schema_version'] == 3:
        fields |= {'pool_size', 'pool_sha256'}
        require(type(value.get('pool_size')) is int and 0 < value['pool_size'] <= MAX_POOL_PAYLOAD and
                isinstance(value.get('pool_sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', value['pool_sha256']),
                'Invalid pool transfer metadata')
        require(value.get('sharing_level') == 'same-team' and value.get('scope') == {'mode': 'all'},
                'Pool synchronization requires full same-team project sharing')
    require(set(value) == fields, 'Invalid content sync exchange')
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
    chats = _chat_inventory(value['chat_inventory'])
    _chat_inventory(value['known_remote_chats'])
    require(type(value['chat_size']) is int
            and 0 <= value['chat_size'] <= MAX_CHAT_PAYLOAD
            and isinstance(value['chat_sha256'], str)
            and re.fullmatch(r'[a-f0-9]{64}', value['chat_sha256'])
            and ((value['chat_size'] == 0) == (not chats)),
            'Invalid project chat payload metadata')
    return value


def _chat_inventory(value):
    require(isinstance(value, list) and len(value) <= 64,
            'Invalid project chat inventory')
    result = []
    for row in value:
        require(isinstance(row, dict) and set(row) == {'thread_id', 'digest'},
                'Invalid project chat inventory item')
        identifier(row['thread_id'])
        require(isinstance(row['digest'], str)
                and re.fullmatch(r'[a-f0-9]{64}', row['digest']),
                'Invalid project chat digest')
        result.append(dict(row))
    require(result == sorted(result, key=lambda row: row['thread_id'])
            and len({row['thread_id'] for row in result}) == len(result),
            'Project chat inventory must be sorted and unique')
    return result


def encode_body(envelope, payload):
    raw = canonical(envelope)
    require(0 < len(raw) <= MAX_ENVELOPE
            and len(payload) <= MAX_BUNDLE + MAX_CHAT_PAYLOAD + MAX_POOL_PAYLOAD,
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
    with service.read_current() as (_, state, commit, _):
        peer = next((row for row in state['peers'] if row['id'] == peer_id), None)
        if (not peer or peer['trust'] != 'approved'
                or peer['sharing_level'] not in {'same-team', 'same-company'}):
            raise AccessDenied('Content sync requires an approved internal peer')
        return state['node_id'], dict(peer), list(state['project_shares']), commit


def _policy(peer, shares, project_id):
    return content_policy(peer, shares, project_id)


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


def _bundle_snapshot(workspace, scope, expected=None):
    """Brief native owner for snapshot admission/final publication checks."""
    workspace.repair_index()
    with workspace.journal.lock(shared=True), workspace.journal.connect() as db:
        if workspace._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
            raise SyncBusy('Shared project has an unfinished publication', resource='pending-publication')
        workspace._branch()
        refs = _inventory(workspace.git, scope)
        if expected is not None and refs != expected:
            raise SyncBusy('Shared branches changed during bundle preparation', resource='snapshot-changed')
        workspace._read_shared(db)
        # Shared readers must not race for .git/index.lock via opportunistic refresh.
        if git_run(workspace.git, 'status', '--porcelain', '--untracked-files=all',
                   env_extra={'GIT_OPTIONAL_LOCKS': '0'}).stdout:
            raise SyncConflict('Shared project worktree has local changes')
        require(refs, 'Sharing scope selects no local branch')
        # External Git users do not acquire our journal flock either.
        if _inventory(workspace.git, scope) != refs:
            raise SyncBusy('Shared branches changed during snapshot admission', resource='snapshot-changed')
        return refs


@git_budget()
def _build_bundle(node, project_id, scope, *, verified=None, peer_known_refs=None):
    binding = _binding(node, project_id)
    if binding is None:
        return [], b''
    workspace = Projects(node).workspace(project_id, blocking=False, for_read=True)
    refs = _bundle_snapshot(workspace, scope)
    if peer_known_refs is not None and refs == _refs(peer_known_refs):
        # No bytes are exported; the next request observes any subsequent head.
        return refs, b''
    if (verified is not None and verified.payload
            and verified.project_id == project_id and verified.scope == canonical(scope)
            and verified.refs == tuple((row['ref'], row['head']) for row in refs)):
        _bundle_snapshot(workspace, scope, refs)
        return refs, verified.payload

    # Git objects named by captured heads are immutable. Do not own a project
    # writer while traversing history, fetching objects or verifying a pack.
    with tempfile.TemporaryDirectory(prefix='sharing-sync-') as directory:
        root = Path(directory)
        (root / 'export.git').mkdir(mode=0o700)
        exported = Git(root / 'export.git')
        git_run(exported, 'init', '--bare', '--template=')
        git_run(exported, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags',
                str(workspace.git.root),
                *[row['head'] + ':' + row['ref'] for row in refs])
        bundle = root / 'project.bundle'
        git_run(exported, 'bundle', 'create', str(bundle), *[row['ref'] for row in refs])
        require(bundle.stat().st_size <= MAX_BUNDLE, 'Content sync bundle exceeds 64 MiB')
        payload = bundle.read_bytes()
        # Keep validation of the exact exported graph, not only source history.
        _validate_git_bundle(payload, refs, project_id, root / 'verify.git')
    if _binding(node, project_id) != binding:
        raise SyncBusy('Project registration changed during bundle preparation', resource='snapshot-changed')
    _bundle_snapshot(workspace, scope, refs)
    return refs, payload


def _payloads(exchange, payload):
    expected = exchange['bundle_size'] + exchange['chat_size'] + exchange.get('pool_size', 0)
    require(len(payload) == expected, 'Content sync payload has another size')
    boundary = exchange['bundle_size']
    return payload[:boundary], payload[boundary:boundary+exchange['chat_size']]


def _pool_payload(exchange, payload):
    size = exchange.get('pool_size', 0)
    return payload[-size:] if size else b''


def _trusted_heads(node, project_id):
    """Branch heads of the receiver's own project history (AUDIT-B7-T1).

    Commits reachable from them were validated when they entered this
    repository, by the local writer or by an earlier verified receive, so an
    incoming bundle needs no second validation of them. Only refs/heads count;
    staging refs of unfinished receives never become trusted. No local project
    (an initial share) means no trusted history.
    """
    binding = _binding(node, project_id)
    if binding is None:
        return []
    try:
        raw = git_run(Git(Path(binding['root'])), 'for-each-ref', '--format=%(objectname)',
                      'refs/heads/').stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(set(raw))[:64]


@git_budget()
def _validate_git_bundle(payload, refs, project_id, repo, trusted=()):
    """Check the native bundle in an isolated object store.

    Every commit not reachable from ``trusted`` (the receiver's own validated
    heads that the bundle also contains) is validated; see _trusted_heads.
    """
    repo.mkdir(mode=0o700)
    git=Git(repo);git_run(git,'init','--bare','--template=')
    bundle=repo.parent/('verify-'+str(uuid4())+'.bundle');bundle.write_bytes(payload)
    try:
        listed=git_run(git,'bundle','list-heads',str(bundle)).stdout.splitlines()
        actual=sorted([{'head':line.split()[0],'ref':line.split()[1]} for line in listed],key=lambda row:row['ref'])
        require(actual==refs,'Git bundle refs differ from signed inventory')
        git_run(git,'-c','protocol.file.allow=always','fetch','--no-tags',str(bundle),
                *[row['ref']+':'+row['ref'] for row in actual])
        present = [head for head in trusted
                   if git_run(git, 'cat-file', '-e', head + '^{commit}', check=False).returncode == 0]
        validate_histories(git, [row['head'] for row in actual], project_id, PRIVACY, trusted=present)
    finally:
        bundle.unlink(missing_ok=True)


def _verify_payload(exchange, payload):
    """Check bounded signed payload parts, without traversing Git history."""
    bundle_payload, chat_payload = _payloads(exchange, payload)
    require(hashlib.sha256(bundle_payload).hexdigest() == exchange['bundle_sha256'],
            'Content sync bundle differs from signed exchange')
    require(hashlib.sha256(chat_payload).hexdigest() == exchange['chat_sha256'],
            'Project chat payload differs from signed exchange')
    pools = _pool_payload(exchange, payload)
    if pools:
        require(hashlib.sha256(pools).hexdigest() == exchange['pool_sha256'], 'Pool payload digest differs')
        from spikes.pool_sync import validate
        validate(pools, exchange['project_id'])
    return bundle_payload, chat_payload


def _verify_incoming_payload(exchange, payload, service):
    bundle_payload, chat_payload = _verify_payload(exchange, payload)
    chats = None
    if chat_payload:
        require(service is not None, 'Chat payload validation requires local authority')
        chats = validate_chat_payload(
            chat_payload, project_id=exchange['project_id'],
            source_node_id=exchange['source_node_id'],
            recipient_node_id=exchange['recipient_node_id'], service=service)
        require(chat_inventory(chats) == exchange['chat_inventory'],
                'Project chat payload differs from signed inventory')
    return bundle_payload, chats


def _verify_bundle(node, exchange, payload, service=None):
    bundle_payload, chats = _verify_incoming_payload(exchange, payload, service)
    if bundle_payload:
        root = private_root(node)
        with tempfile.TemporaryDirectory(prefix='sharing-verify-', dir=root) as directory:
            directory = Path(directory)
            _validate_git_bundle(bundle_payload,exchange['refs'],exchange['project_id'],directory/'repo.git',
                                 trusted=_trusted_heads(node, exchange['project_id']))
    return bundle_payload, chats


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
           authorize=lambda: None, service=None):
    if not payload:
        return False
    _verify_bundle(node, exchange, payload, service)
    return _apply_verified_history(node, exchange, payload, checkpoint, authorize, service,
                                   stage='local-publication')


def _apply_verified_history(node, exchange, payload, checkpoint, authorize, service,
                            *, stage='receive-publication'):
    """Publish only the exact bytes whose Git history this call verified.

    Receiver admission already validated history before persisting its intent.
    Other callers enter through _apply. Never reuse this trust across requests;
    integrity and current non-Git authority are checked again before publishing.
    """
    if not payload:
        return False
    bundle_payload, chats = _verify_incoming_payload(exchange, payload, service)
    pools = _pool_payload(exchange,payload)
    if pools:
        phase(stage + '-pools')
        authorize()
        from spikes.pool_sync import prepare
        prepare(node,exchange['project_id'],pools,operation_id=exchange['operation_id'],
                source_node_id=exchange['source_node_id'],checkpoint=checkpoint)
    conflict = False
    if bundle_payload:
        phase(stage + '-git')
        if _binding(node, exchange['project_id']) is None:
            conflict = _apply_initial(
                node, exchange, bundle_payload, checkpoint, authorize)
        else:
            conflict = _apply_existing(
                node, exchange, bundle_payload, checkpoint, authorize)
    if chats is not None:
        # The durable inbound request is the cross-store recovery authority.
        # Retry first makes Git idempotently current, then atomically applies
        # chats; a crash between those effects rolls forward from the same bytes.
        phase(stage + '-chats')
        authorize()
        chats = validate_chat_payload(
            canonical(chats), project_id=exchange['project_id'],
            source_node_id=exchange['source_node_id'],
            recipient_node_id=exchange['recipient_node_id'], service=service)
        conflict = bool(apply_chat_payload(
            node, chats, checkpoint=checkpoint)) or conflict
    pools = _pool_payload(exchange, payload)
    if pools and not conflict:
        phase(stage + '-pool-apply')
        authorize()
        from spikes.pool_sync import apply
        apply(node, exchange['project_id'], pools, checkpoint=checkpoint,
              operation_id=exchange['operation_id'], source_node_id=exchange['source_node_id'])
    return conflict


def _prepare(service, peer_id, project_id, operation_id, known_remote_refs,
             *, known_remote_chats=None, force_bundle, verified=None, peer_known_refs=None, captured_state=None):
    local_id, peer, shares, commit = _authority(service, peer_id)
    scope = _policy(peer, shares, project_id)
    if verified is not None and not (
            verified.operation_id == operation_id
            and verified.project_id == project_id
            and verified.source_node_id == peer_id
            and verified.recipient_node_id == local_id
            and verified.source_fingerprint == peer['fingerprint']
            and verified.scope == canonical(scope)):
        verified = None
    refs, bundle_payload = ([], b'') if scope is None else _build_bundle(
        service.node, project_id, scope, verified=verified, peer_known_refs=peer_known_refs)
    chats, chat_payload = ([], b'') if scope is None else export_project_chats(
        service.node, service, peer_id, project_id)
    if not chats:
        chat_payload = b''
    if not force_bundle:
        bundle_payload = b''; chat_payload = b''
    current = _authority(service, peer_id)
    require(current == (local_id, peer, shares, commit),
            'Sharing policy changed during sync preparation')
    exchange = validate_exchange({
        'schema_version': 2, 'operation_id': operation_id,
        'project_id': project_id, 'source_node_id': local_id,
        'recipient_node_id': peer_id, 'sharing_level': peer['sharing_level'],
        'scope': scope or ({'mode': 'all'} if peer['sharing_level'] == 'same-team'
                           else {'mode': 'selected-only', 'branches': ['refs/heads/main'],
                                 'revision': 1}),
        'refs': refs if bundle_payload else [],
        'known_remote_refs': _refs(known_remote_refs),
        'bundle_size': len(bundle_payload),
        'bundle_sha256': hashlib.sha256(bundle_payload).hexdigest(),
        'chat_inventory': chats if chat_payload else [],
        'known_remote_chats': _chat_inventory(known_remote_chats or []),
        'chat_size': len(chat_payload),
        'chat_sha256': hashlib.sha256(chat_payload).hexdigest(),
    })
    pool_payload = b''
    if force_bundle and scope == {'mode': 'all'} and peer['sharing_level'] == 'same-team':
        from spikes.pool_sync import export
        pool_payload = export(service.node, project_id)
        if pool_payload:
            require(_inventory(Projects(service.node).workspace(project_id).git, scope) == refs,
                    'Project changed during pool export; retry with a current snapshot')
    if pool_payload:
        exchange = validate_exchange(dict(exchange, schema_version=3, pool_size=len(pool_payload),
            pool_sha256=hashlib.sha256(pool_payload).hexdigest()))
    require(_authority(service, peer_id) == (local_id, peer, shares, commit), 'Pool sharing policy changed')
    if captured_state is not None:
        from spikes.sync_fingerprint import snapshot
        captured_state.update(snapshot((local_id, peer, shares, commit), project_id,
                                       refs, chats, pool_payload))
    payload = bundle_payload + chat_payload + pool_payload
    return (_signature(service.root, exchange, local_id, 'exchange'), payload,
            peer, refs, chats)


class SyncReceiver:
    def __init__(self, node, administration=None):
        self.node = Path(node).absolute()
        self.service = administration or Administration(self.node)

    @received
    def receive(self, envelope, payload, checkpoint=lambda stage: None, *, background=False):
        # A background receive job (content_receive_jobs) is not an HTTP worker:
        # SQLite keeps its native waits there and history verification gets the
        # longer background budget. Flock owners stay non-blocking either way.
        owner = nullcontext() if background else bounded_project_requests()
        budget = BACKGROUND_RECEIVE_BUDGET if background else CONTENT_RECEIVE_BUDGET
        try:
            with owner, _inbound_lock(self.node):
                return self._receive(envelope, payload, checkpoint, budget=budget)
        except (BlockingIOError, ProjectBusy) as exc:
            raise SyncBusy('Content project is busy', resource=getattr(exc, 'busy_resource', 'native-owner')) from exc
        except GitDeadlineExceeded as exc:
            exc.busy_resource = 'git-budget'
            exc.peer_phase = safe_peer_phase(current_phase())
            raise

    def _replay(self, exchange, payload, response, response_payload, *, authority):
        # Only reached after exact equality with a completed durable request.
        # Its historical Git semantics are already validated, but authority is
        # live: both incoming chat mappings and outgoing cached bytes matter.
        phase('receive-replay')
        _verify_incoming_payload(exchange, payload, self.service)
        require(isinstance(response, dict) and set(response) == {
            'exchange', 'signer_node_id', 'public_key', 'signature',
            'accepted_source_refs', 'accepted_source_chats', 'conflict'},
            'Invalid saved content sync response')
        identity = MappingSignatures(self.service.root)
        require(identity.key.is_file()
                and (identity.root / 'federation-key.identity').is_file(),
                'Saved response requires the original local identity')
        signed = {key: response[key] for key in
                  ('exchange', 'signer_node_id', 'public_key', 'signature')}
        returned = validate_exchange(_verify(
            signed, identity.identity()['fingerprint'], 'exchange')['exchange'])
        _refs(response['accepted_source_refs'])
        _chat_inventory(response['accepted_source_chats'])
        require(type(response['conflict']) is bool, 'Invalid saved conflict state')
        local_id, peer, shares, commit = authority
        require(returned['operation_id'] == exchange['operation_id']
                and returned['project_id'] == exchange['project_id']
                and returned['source_node_id'] == local_id
                and response['signer_node_id'] == local_id
                and returned['recipient_node_id'] == peer['id']
                and returned['sharing_level'] == peer['sharing_level']
                and peer['sharing_level'] == exchange['sharing_level'],
                'Saved response authority changed')
        scope = _policy(peer, shares, exchange['project_id'])
        expected_scope = scope or {'mode': 'selected-only',
                                  'branches': ['refs/heads/main'], 'revision': 1}
        require(returned['scope'] == expected_scope
                and (not response_payload or scope is not None),
                'Saved response exceeds current project sharing policy')
        binding = _binding(self.node, exchange['project_id'])
        if response_payload:
            require(binding is not None, 'Saved response project is no longer registered')
            # Current registration/metadata must still be available. Attaching
            # a read-only Git handle must not initialize or wait for a journal.
            Projects(self.node).repository(exchange['project_id'])
        _, chats = _verify_payload(returned, response_payload)
        if chats:
            validate_export_authority(chats, project_id=exchange['project_id'],
                source_node_id=local_id, recipient_node_id=peer['id'], service=self.service)
        # A concurrent registry change during the checks is not permission to
        # send stale bytes. Keep the original journal unchanged on refusal.
        require(_authority(self.service, peer['id']) == (local_id, peer, shares, commit),
                'Content sync authority changed during replay')
        require(_binding(self.node, exchange['project_id']) == binding,
                'Project registration changed during replay')
        return response, response_payload

    def _receive(self, envelope, payload, checkpoint, *, budget=CONTENT_RECEIVE_BUDGET):
        require(isinstance(envelope, dict) and isinstance(envelope.get('exchange'), dict),
                'Missing content sync exchange')
        exchange = validate_exchange(envelope['exchange'])
        authority = _authority(self.service, exchange['source_node_id'])
        local_id, peer, _, _ = authority
        require(exchange['recipient_node_id'] == local_id
                and exchange['sharing_level'] == peer['sharing_level']
                and envelope.get('signer_node_id') == peer['id'],
                'Content sync exchange does not match relationship')
        _verify(envelope, peer['fingerprint'], 'exchange')
        digest = hashlib.sha256(canonical(envelope) + payload).hexdigest()
        encoded = canonical(envelope).decode('ascii')
        saved = None
        with _database(self.node) as db:
            row = db.execute('SELECT request_digest,envelope,bundle,'
                             'response_envelope,response_bundle FROM inbound '
                             'WHERE operation_id=?', (exchange['operation_id'],)).fetchone()
            if row:
                require(row[0] == digest and row[1] == encoded
                        and bytes(row[2]) == payload,
                        'Content sync operation ID belongs to another request')
                if row[3] is not None:
                    require(row[4] is not None, 'Incomplete saved content sync response')
                    saved = (json.loads(row[3]), bytes(row[4]))
        if saved is not None:
            return self._replay(exchange, payload, *saved, authority=authority)
        phase('receive-check-destination')
        if _binding(self.node, exchange['project_id']) is not None:
            # A completed replay needs no publication. An interrupted project
            # operation must retain its existing roll-forward path, including
            # its own dirty worktree. Only reject otherwise unowned local edits.
            workspace = Projects(self.node).workspace(exchange['project_id'], blocking=False)
            with workspace.journal.lock(), workspace.journal.connect() as project_db:
                recovering = (workspace._active(project_db)
                              or project_db.execute('SELECT 1 FROM pending').fetchone())
                if not recovering and git_run(
                        workspace.git, 'status', '--porcelain',
                        '--untracked-files=all').stdout:
                    raise SyncConflict('Destination has local changes; review project conflicts')
        phase('receive-verify-history')
        with git_budget(budget):
            bundle, _ = _verify_bundle(self.node, exchange, payload, self.service)
        verified = _VerifiedInboundBundle(
            exchange['operation_id'], exchange['project_id'], peer['id'], local_id, peer['fingerprint'],
            canonical(exchange['scope']),
            tuple((row['ref'], row['head']) for row in exchange['refs']), bytes(bundle))
        # No new intent is persisted until full validation has succeeded.
        # The receiver lock spans lookup, validation and response publication.
        if row is None:
            with _database(self.node) as db:
                db.execute('INSERT INTO inbound VALUES (?,?,?,?,NULL,NULL)',
                           (exchange['operation_id'], digest, encoded, payload))
        def authorize():
            current_id, current_peer, _, _ = _authority(
                self.service, exchange['source_node_id'])
            require(current_id == local_id
                    and current_peer['fingerprint'] == peer['fingerprint']
                    and current_peer['sharing_level'] == exchange['sharing_level'],
                    'Content sync authority changed before publication')
        phase('receive-publication')
        conflict = _apply_verified_history(
            self.node, exchange, payload, checkpoint, authorize, self.service)
        with _database(self.node) as db:
            if exchange['bundle_size'] or exchange['chat_size']:
                previous = db.execute('SELECT refs FROM accepted WHERE peer_id=? '
                                      'AND project_id=?',
                                      (peer['id'], exchange['project_id'])).fetchone()
                accepted_state = _sync_state(previous[0] if previous else None)
                if exchange['bundle_size']:
                    accepted_state['refs'] = exchange['refs']
                if exchange['chat_size']:
                    accepted_state['chats'] = exchange['chat_inventory']
                db.execute('INSERT OR REPLACE INTO accepted VALUES (?,?,?)',
                           (peer['id'], exchange['project_id'],
                            canonical(accepted_state).decode('ascii')))
            accepted = db.execute('SELECT refs FROM accepted WHERE peer_id=? '
                                  'AND project_id=?',
                                  (peer['id'], exchange['project_id'])).fetchone()
        known = exchange['known_remote_refs']
        known_chats = exchange['known_remote_chats']
        phase('receive-prepare-response')
        response_state = {}
        response, response_payload, _, local_refs, local_chats = _prepare(
            self.service, peer['id'], exchange['project_id'],
            exchange['operation_id'], exchange['refs'],
            known_remote_chats=exchange['chat_inventory'], force_bundle=True,
            verified=verified, peer_known_refs=known, captured_state=response_state)
        response_exchange = response['exchange']
        response_bundle, response_chats = _payloads(
            response_exchange, response_payload)
        if local_refs == known:
            response_exchange = dict(response_exchange, refs=[], bundle_size=0,
                                     bundle_sha256=hashlib.sha256(b'').hexdigest())
            response_bundle = b''
        if local_chats == known_chats:
            response_exchange = dict(response_exchange, chat_inventory=[], chat_size=0,
                                     chat_sha256=hashlib.sha256(b'').hexdigest())
            response_chats = b''
        response_payload = response_bundle + response_chats + _pool_payload(response_exchange, response_payload)
        if local_refs == known or local_chats == known_chats:
            response = _signature(self.service.root, validate_exchange(response_exchange),
                                  local_id, 'exchange')
        accepted_state = _sync_state(accepted[0] if accepted else None)
        response = dict(response, accepted_source_refs=accepted_state['refs'],
                        accepted_source_chats=accepted_state['chats'], conflict=conflict)
        raw_response = canonical(response).decode('ascii')
        with _database(self.node) as db:
            changed = db.execute('UPDATE inbound SET response_envelope=?,response_bundle=? '
                                 'WHERE operation_id=? AND response_envelope IS NULL',
                                 (raw_response, response_payload,
                                  exchange['operation_id']))
            require(changed.rowcount == 1, 'Content sync response publication changed')
            db.execute('INSERT OR REPLACE INTO response_states VALUES (?,?)',
                       (exchange['operation_id'], canonical(response_state).decode('ascii')))
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)', (
                peer['id'], exchange['project_id'],
                'conflict' if conflict else 'idle',
                'Divergent history preserved' if conflict else 'Content synchronized',
                canonical({'refs': local_refs, 'chats': local_chats}).decode('ascii'),
                canonical({'refs': (exchange['refs'] if exchange['bundle_size'] else
                                     accepted_state['refs']),
                           'chats': (exchange['chat_inventory'] if exchange['chat_size'] else
                                    accepted_state['chats'])}).decode('ascii')))
        return response, response_payload


@observed
def synchronize(node, peer_id, project_id, *, deployment='desktop', ca=None,
                cancelled=None, state_manifest=False):
    phase('prepare')
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise SyncCancelled('Content sync cancelled before preparation')
    service = Administration(node, deployment=deployment)
    with _database(node) as db:
        runtime = db.execute('SELECT last_sent,last_remote FROM runtime '
                             'WHERE peer_id=? AND project_id=?',
                             (peer_id, project_id)).fetchone()
        pending = db.execute('SELECT operation_id,envelope,bundle,local_refs '
                             'FROM outbound WHERE peer_id=? AND project_id=?',
                             (peer_id, project_id)).fetchone()
    last_sent = _sync_state(runtime[0] if runtime else None)
    last_remote = _sync_state(runtime[1] if runtime else None)
    if pending:
        operation_id = pending[0]; envelope = json.loads(pending[1])
        payload = bytes(pending[2]); local_state = _sync_state(pending[3])
        local_refs, local_chats = local_state['refs'], local_state['chats']
        local_id, peer, shares, _ = _authority(service, peer_id)
        current_scope = _policy(peer, shares, project_id)
        expected_scope = (current_scope or
                          ({'mode': 'all'} if peer['sharing_level'] == 'same-team'
                           else {'mode': 'selected-only',
                                 'branches': ['refs/heads/main'], 'revision': 1}))
        stale_chat_authority = False
        if envelope.get('exchange', {}).get('schema_version') in {2, 3}:
            _, pending_chats = _payloads(envelope['exchange'], payload)
            if pending_chats:
                try:
                    validate_export_authority(
                        pending_chats, project_id=project_id,
                        source_node_id=local_id, recipient_node_id=peer_id,
                        service=service)
                except (AccessDenied, ValueError):
                    stale_chat_authority = True
        if (envelope.get('exchange', {}).get('schema_version') not in {2, 3}
                or envelope['exchange']['source_node_id'] != local_id
                or envelope['exchange']['sharing_level'] != peer['sharing_level']
                or envelope['exchange']['scope'] != expected_scope
                or stale_chat_authority):
            # A narrowed/revoked policy must never resend stale bytes. A peer
            # that already received them cannot be made to forget them.
            with _database(node) as db:
                db.execute('DELETE FROM outbound WHERE peer_id=? AND project_id=?',
                           (peer_id, project_id))
                db.execute('DELETE FROM prepared_states WHERE operation_id=?', (operation_id,))
            return synchronize(node, peer_id, project_id,
                               deployment=deployment, ca=ca, cancelled=cancelled, state_manifest=state_manifest)
    else:
        operation_id = str(uuid4())
        prepared_state = {}
        envelope, payload, peer, local_refs, local_chats = _prepare(
            service, peer_id, project_id, operation_id, last_remote['refs'],
            known_remote_chats=[] if state_manifest else last_remote['chats'], force_bundle=True,
            peer_known_refs=last_sent['refs'], captured_state=prepared_state)
        exchange = envelope['exchange']
        bundle_payload, chat_payload = _payloads(exchange, payload)
        changed = False
        if local_refs == last_sent['refs']:
            exchange = dict(envelope['exchange'], refs=[], bundle_size=0,
                            bundle_sha256=hashlib.sha256(b'').hexdigest())
            bundle_payload = b''; changed = True
        if local_chats == last_sent['chats'] and not state_manifest:
            exchange = dict(exchange, chat_inventory=[], chat_size=0,
                            chat_sha256=hashlib.sha256(b'').hexdigest())
            chat_payload = b''; changed = True
        if changed:
            envelope = _signature(service.root, validate_exchange(exchange),
                                  exchange['source_node_id'], 'exchange')
            payload = bundle_payload + chat_payload + _pool_payload(exchange, payload)
        with _database(node) as db:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                       (peer_id, project_id, operation_id,
                        canonical(envelope).decode('ascii'), payload,
                        canonical({'refs': local_refs, 'chats': local_chats})
                        .decode('ascii')))
            db.execute('INSERT INTO prepared_states VALUES (?,?)',
                       (operation_id, canonical(prepared_state).decode('ascii')))
    if cancelled():
        raise SyncCancelled('Content sync cancelled before transport')
    if not peer.get('endpoint'):
        raise AccessDenied('Peer can synchronize content only when it connects')
    parsed, address = private_peer_endpoint(
        peer['endpoint'], invalid='Invalid content sync peer endpoint',
        private='Content sync peer must use a private IP address')
    ca = Path(ca) if ca else private_root(node) / (peer_id + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = DeadlineHTTPSConnection(
        str(address), parsed.port or 443, context=context, timeout=CONTENT_SYNC_TIMEOUT)
    response = None
    try:
        phase('upload')
        connection.request('POST', PATH, body=encode_body(envelope, payload), headers={
            'Content-Type': CONTENT_TYPE, 'Host': parsed.netloc, 'Accept': STREAM_TYPE,
            **({'X-FPW-State-Receipt': '1'} if state_manifest else {})})
        phase('wait-response')
        response = connection.getresponse()
        if response.status == 200 and response.getheader('Content-Type') == STREAM_TYPE:
            # The peer works in the background and proves liveness with
            # heartbeats: wait per frame, not for one fixed exchange budget.
            connection.extend_deadline(CONTENT_SYNC_MAX_WAIT, idle=HEARTBEAT_IDLE_TIMEOUT)
            phase('peer-working')
            kind, outcome = read_frames(
                response.readline, response.read, cancelled=cancelled,
                on_heartbeat=lambda value: peer_progress(value.get('peer_phase')))
            phase('download')
            if kind == 'error':
                status, body = outcome['status'], canonical(outcome)
            else:
                status, body = 200, outcome
        else:
            phase('download')
            status, body = response.status, response.read(MAX_BODY + 1)
        connection.check_deadline()
        require(len(body) <= MAX_BODY, 'Content sync response exceeds limit')
        if status == 409:
            raise SyncConflict('Peer reported a content conflict')
        if status == 503:
            diagnostic = {}
            if len(body) <= 4096:
                try:
                    value = json.loads(body)
                    if isinstance(value, dict): diagnostic = value
                except (ValueError, UnicodeError): pass
            raise SyncBusy('Peer is temporarily busy; retry the same operation',
                resource=safe_busy_resource(diagnostic.get('busy_resource')),
                peer_phase=safe_peer_phase(diagnostic.get('peer_phase')))
        if status != 200:
            typed = peer_unsupported_version(body, subject=peer_id)
            raise SyncRejected('Peer rejected content sync' + (f': {typed}' if typed else ''))
        response_envelope, response_payload = decode_body(body)
    except TimeoutError as exc:
        if not connection.connected:
            raise  # never connected: the peer is unreachable
        raise PeerTimeout('Peer did not answer content sync in time') from exc
    finally:
        if response is not None:
            response.close()
        connection.close()
    if cancelled():
        raise SyncCancelled('Content sync cancelled before local publication')
    signed_receipt = response_envelope.pop('state_receipt', None) if state_manifest else None
    require(set(response_envelope) == {'exchange', 'signer_node_id', 'public_key',
                                       'signature', 'accepted_source_refs',
                                       'accepted_source_chats', 'conflict'},
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
    remote_state = None
    if signed_receipt is not None:
        from spikes.sync_fingerprint import verify_receipt
        remote_state = verify_receipt(signed_receipt, response_envelope, peer)
    phase('local-publication')
    conflict = _apply(node, returned, response_payload,
                      authorize=authorize_response, service=service)
    accepted = _refs(response_envelope['accepted_source_refs'])
    accepted_chats = _chat_inventory(response_envelope['accepted_source_chats'])
    sent = {'refs': (local_refs if accepted == local_refs else last_sent['refs']),
            'chats': (local_chats if accepted_chats == local_chats
                      else last_sent['chats'])}
    remote = {'refs': (returned['refs'] if returned['bundle_size']
                       else last_remote['refs']),
              'chats': (returned['chat_inventory'] if returned['chat_size']
                        else last_remote['chats'])}
    state = 'conflict' if conflict or response_envelope['conflict'] else 'idle'
    with _database(node) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)',
                   (peer_id, project_id, state,
                    'Divergent history preserved' if state == 'conflict'
                    else 'Content synchronized',
                    canonical(sent).decode('ascii'), canonical(remote).decode('ascii')))
        prepared = db.execute('SELECT state FROM prepared_states WHERE operation_id=?',
                              (operation_id,)).fetchone()
        if (state == 'idle' and accepted == local_refs and accepted_chats == local_chats
                and prepared is not None and remote_state is not None):
            db.execute('INSERT OR REPLACE INTO confirmed_states VALUES (?,?,?,?)',
                       (peer_id, project_id, prepared[0], canonical(remote_state).decode('ascii')))
        else:
            db.execute('DELETE FROM confirmed_states WHERE peer_id=? AND project_id=?',
                       (peer_id, project_id))
        db.execute('DELETE FROM prepared_states WHERE operation_id=?', (operation_id,))
        db.execute('DELETE FROM outbound WHERE peer_id=? AND project_id=?',
                   (peer_id, project_id))
    return {'state': state, 'local_refs': sent['refs'], 'remote_refs': remote['refs'],
            'local_chats': sent['chats'], 'remote_chats': remote['chats']}


class ContentSyncControl:
    def __init__(self, node, *, deployment):
        self.node = Path(node).absolute(); self.deployment = deployment
        self.service = Administration(node, deployment=deployment)

    def statuses(self):
        with _database(self.node) as db:
            rows = db.execute('SELECT peer_id,project_id,state,detail,last_sent,'
                              'last_remote FROM runtime').fetchall()
        stale = [(peer, project) for peer, project, state, _, _, _ in rows
                 if state in {'queued', 'running', 'cancelling'}
                 and not _MANUAL_SYNCS.active(self.node, peer, project)]
        if stale:
            with _database(self.node) as db:
                for peer, project in stale:
                    db.execute(
                        "UPDATE runtime SET state='cancelled',detail=? "
                        'WHERE peer_id=? AND project_id=? '
                        "AND state IN ('queued','running','cancelling')",
                        ('Synchronization was interrupted before completion',
                         peer, project))
            with _database(self.node) as db:
                rows = db.execute(
                    'SELECT peer_id,project_id,state,detail,last_sent,last_remote '
                    'FROM runtime').fetchall()
        from spikes.sync_fingerprint import observation, observations
        result = {}
        for peer, project, state, detail, sent, remote in rows:
            sent_state, remote_state = _sync_state(sent), _sync_state(remote)
            result[peer + ':' + project] = {
                'state': state, 'detail': detail,
                'automatic_check': observation(self.node, peer, project),
                'automatic_retry_after': automatic_retry.remaining((str(self.node), peer, project)),
                'diagnostic': sync_diagnostic(self.node, peer, project, direction='outbound'),
                'chat_summary': {
                    'shared': len(sent_state['chats']),
                    'received': len(remote_state['chats']),
                    'active_mappings': active_mapping_count(
                        self.service, peer, project),
                },
            }
        for peer, project, check in observations(self.node):
            result.setdefault(peer + ':' + project, {
                'state': 'needed', 'detail': 'Content has not yet been confirmed',
                'automatic_check': check})
        return result

    def settings(self):
        with _database(self.node) as db:
            row = db.execute(
                'SELECT revision,automatic_enabled FROM settings WHERE singleton=1'
            ).fetchone()
        if row is None:
            return {'schema_version': 1, 'revision': 0,
                    'automatic_enabled': True}
        require(type(row[0]) is int and row[0] >= 0 and row[1] in {0, 1},
                'Invalid content sync settings')
        return {'schema_version': 1, 'revision': row[0],
                'automatic_enabled': bool(row[1])}

    def configure(self, *, automatic_enabled, expected_revision):
        require(type(automatic_enabled) is bool
                and type(expected_revision) is int and expected_revision >= 0,
                'Invalid content sync settings request')
        with _database(self.node) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT revision,automatic_enabled FROM settings WHERE singleton=1'
            ).fetchone()
            current_revision = 0 if row is None else row[0]
            require(current_revision == expected_revision,
                    'Content sync settings changed; reload administration')
            revision = current_revision + 1
            db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)',
                       (revision, int(automatic_enabled)))
        return {'schema_version': 1, 'revision': revision,
                'automatic_enabled': automatic_enabled}

    def candidates(self):
        """Return one policy projection used by automatic and manual-all sync."""
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = self.service.request(actor, {'action': 'list'})
        from spikes.federation_catalog import CatalogStore
        remote = CatalogStore(self.node).projections()
        local = {row['id'] for row in Projects(self.node).catalog()
                 if row['available']}
        runtime = self.statuses()
        rows = []
        for peer in state['peers']:
            projects = set(local)
            projects.update(row['id'] for row in remote
                            if row['peer_id'] == peer['id'])
            local_selected = {row['project_id'] for row in state['project_shares']
                              if row['peer_id'] == peer['id']}
            remote_selected = {row['id'] for row in remote
                               if row['peer_id'] == peer['id']}
            for project_id in sorted(projects):
                reason = None
                if peer['trust'] != 'approved': reason = 'peer-not-approved'
                elif peer['sharing_level'] not in {'same-team', 'same-company'}:
                    reason = 'not-internal-sharing'
                elif not peer.get('endpoint'): reason = 'endpoint-unavailable'
                elif (peer['sharing_level'] == 'same-company'
                      and project_id not in local_selected | remote_selected):
                    reason = 'project-not-selected'
                elif runtime.get(peer['id'] + ':' + project_id, {}).get('state') == 'conflict':
                    reason = 'conflict-requires-decision'
                rows.append({'peer_id': peer['id'], 'project_id': project_id,
                             'eligible': reason is None, 'reason': reason})
        return rows

    @observed
    @bounded_project_requests()
    def synchronize(self, peer_id, project_id, *, cancelled=None, owner_wait=0, state_manifest=False,
                    defer_when_busy=False):
        try:
            identifier(peer_id); identifier(project_id)
            # A streamed exchange may own the send lane for minutes; the manual
            # worker (a background thread, cancellable) waits up to that cap.
            require(type(owner_wait) in (int, float) and 0 <= owner_wait <= CONTENT_SYNC_MAX_WAIT,
                    'Invalid synchronization admission wait')
            if cancelled is not None and cancelled():
                raise SyncCancelled('Content sync cancelled before ownership')
            root = private_root(self.node)
            fd = os.open(root / 'federation-content-sync.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a+b') as lock:
                info = os.fstat(lock.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and info.st_nlink == 1 and not info.st_mode & 0o077,
                        'Unsafe content send lock')
                phase('wait-lock')
                # Preserve capacity one without accumulating background workers
                # in an uninterruptible queue behind a stalled peer transfer.
                deadline = time.monotonic() + owner_wait
                while True:
                    if cancelled is not None and cancelled():
                        raise SyncCancelled('Content sync cancelled before ownership')
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if defer_when_busy:
                            raise OutboundDeferred('Another outbound content sync is running')
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise
                        # Only the one background manual worker waits here.
                        # No HTTP worker, new envelope or dispatched request.
                        time.sleep(min(.05, remaining))
                result = synchronize(self.node, peer_id, project_id,
                                     deployment=self.deployment, cancelled=cancelled,
                                     **({'state_manifest': True} if state_manifest else {}))
                automatic_retry.succeeded((str(self.node), peer_id, project_id))
                return result
        except OutboundDeferred:
            raise  # nothing started; keep the last real runtime state
        except SyncCancelled as exc:
            state = 'cancelled'; detail = str(exc); error = exc
        except SyncConflict as exc:
            state = 'conflict'; detail = str(exc); error = exc
        except GitDeadlineExceeded as exc:
            exc.busy_resource = 'git-budget'
            state = 'busy'; detail = 'History verification timed out; saved operation retained'; error = exc
        except (SyncBusy, ProjectBusy, BlockingIOError) as exc:
            if isinstance(exc, BlockingIOError) and current_phase() == 'wait-lock':
                exc.busy_resource = 'outbound-capacity'
            state = 'busy'; detail = 'Synchronization deferred; saved operation retained'; error = exc
        except (AccessDenied, SyncRejected) as exc:
            state = 'rejected'; detail = str(exc); error = exc
        except PeerTimeout as exc:
            state = 'unanswered'; detail = str(exc); error = exc
        except (ConnectionError, TimeoutError, ssl.SSLError, OSError) as exc:
            state = 'offline'; detail = type(exc).__name__; error = exc
        except (ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
            state = 'error'; detail = str(exc); error = exc
        except Exception as exc:
            # Unknown class: record a generic durable error, never only vanish.
            state = 'error'; detail = type(exc).__name__; error = exc
        with _database(self.node) as db:
            previous = db.execute(
                'SELECT last_sent,last_remote FROM runtime '
                'WHERE peer_id=? AND project_id=?',
                (peer_id, project_id)).fetchone() or ('[]', '[]')
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)',
                       (peer_id, project_id, state, detail, *previous))
        raise error

    def start(self, peer_id, project_id):
        return _MANUAL_SYNCS.start(self.node, self.deployment,
                                   peer_id, project_id)

    def start_all(self):
        result = {'started': 0, 'already_running': 0,
                  'skipped': 0, 'errors': 0, 'targets': []}
        for candidate in self.candidates():
            row = dict(candidate)
            if not candidate['eligible']:
                result['skipped'] += 1; row['state'] = 'skipped'
            else:
                try:
                    changed = self.start(candidate['peer_id'], candidate['project_id'])
                except Exception as exc:
                    result['errors'] += 1; row['state'] = 'error'
                    row['reason'] = type(exc).__name__
                else:
                    key = 'started' if changed else 'already_running'
                    result[key] += 1; row['state'] = key.replace('_', '-')
            result['targets'].append(row)
        return result

    def cancel(self, peer_id, project_id):
        return _MANUAL_SYNCS.cancel(self.node, peer_id, project_id)

    @bounded_project_requests()
    def run_automatic(self, cancelled=None):
        if not self.settings()['automatic_enabled']:
            return {'enabled': False, 'attempted': 0}
        attempted = 0
        if _MANUAL_SYNCS.any_active(self.node):
            return {'enabled': True, 'attempted': 0}
        from spikes.sync_fingerprint import probe, collect, note, StateUnavailable
        manifests = {}
        probe_errors = {}
        candidates = self.candidates()
        for candidate in candidates:
            if _MANUAL_SYNCS.any_active(self.node): break
            if not candidate['eligible']: continue
            peer_id, project_id = candidate['peer_id'], candidate['project_id']
            key = (str(self.node), peer_id, project_id)
            if not automatic_retry.ready(key): continue
            if peer_id not in manifests:
                probe_started = time.monotonic()
                try:
                    manifests[peer_id] = probe(self.service, peer_id, projects=sorted({
                        row['project_id'] for row in candidates
                        if row['peer_id'] == peer_id and row['eligible']}),
                        **({'cancelled': cancelled} if cancelled is not None else {}))
                except Exception as exc:
                    probe_errors[peer_id] = exc
                    # Type and duration only: no endpoint, path or exception text.
                    logging.getLogger(__name__).warning(
                        'content_state_failed error_type=%s elapsed_ms=%d',
                        type(exc).__name__, round((time.monotonic() - probe_started) * 1000))
                    # Unknown/offline is not permission to start expensive fallback.
                    manifests[peer_id] = False
            manifest = manifests[peer_id]
            if manifest is False:
                note(self.node, peer_id, project_id, 'unavailable', probe_errors[peer_id])
                continue
            try:
                if manifest is not None:
                    if project_id in manifest and manifest[project_id] is None:
                        raise StateUnavailable('Peer project snapshot is unavailable')
                    with _database(self.node) as db:
                        confirmed = db.execute('SELECT local_state,remote_state FROM confirmed_states '
                            'WHERE peer_id=? AND project_id=?', (peer_id, project_id)).fetchone()
                        pending = db.execute('SELECT 1 FROM outbound WHERE peer_id=? AND project_id=?',
                                             (peer_id, project_id)).fetchone()
                    if not pending:
                        local_state = collect(self.service, peer_id, project_id)
                        if (confirmed and json.loads(confirmed[0]) == local_state
                                and json.loads(confirmed[1]) == manifest.get(project_id)):
                            note(self.node, peer_id, project_id, 'unchanged')
                            continue
                # The state check can wait on a working peer for minutes; a
                # manual sync started meanwhile owns the send lane first.
                if _MANUAL_SYNCS.any_active(self.node): break
                attempted += 1
                try:
                    self.synchronize(peer_id, project_id, defer_when_busy=True,
                                     **({'cancelled': cancelled} if cancelled is not None else {}),
                                     **({'state_manifest': True} if manifest is not None else {}))
                except OutboundDeferred:
                    # Not a failure and not a retry backoff: another outbound
                    # sync of this node is running. The next round checks again.
                    attempted -= 1
                    break
                note(self.node, peer_id, project_id, 'legacy' if manifest is None else 'changed')
                automatic_retry.succeeded(key)
            except (TimeoutError, SyncBusy, ProjectBusy) as exc:
                note(self.node, peer_id, project_id, 'unavailable', exc)
                automatic_retry.failed(key)
            except Exception as exc:
                note(self.node, peer_id, project_id, 'unavailable', exc)
        return {'enabled': True, 'attempted': attempted}


class ManualSyncTasks:
    """Volatile workers over the durable content-sync journal.

    Cancellation is cooperative and stops before the next local publication.
    A remote peer may already have accepted the request, so cancellation never
    attempts a destructive rollback; a later retry reconciles both histories.
    """
    def __init__(self, *, max_pending=64):
        require(type(max_pending) is int and max_pending > 0, 'Invalid manual sync capacity')
        self.lock = threading.Lock()
        self.tasks = {}
        self.workers = {}
        self.max_pending = max_pending

    @staticmethod
    def _key(node, peer_id, project_id):
        return str(Path(node).absolute()), peer_id, project_id

    def active(self, node, peer_id, project_id):
        key = self._key(node, peer_id, project_id)
        with bounded_process_lock(self.lock, resource='Manual content synchronization'):
            task = self.tasks.get(key)
            return bool(task and task['thread'].is_alive())

    def any_active(self, node):
        root = str(Path(node).absolute())
        with bounded_process_lock(self.lock, resource='Manual content synchronization'):
            return any(key[0] == root and task['thread'].is_alive()
                       for key, task in self.tasks.items())

    def start(self, node, deployment, peer_id, project_id):
        identifier(peer_id); identifier(project_id)
        key = self._key(node, peer_id, project_id)
        with bounded_process_lock(self.lock, resource='Manual content synchronization'):
            current = self.tasks.get(key)
            if current and current['thread'].is_alive():
                return False
            require(sum(k[0] == key[0] for k in self.tasks) < self.max_pending,
                    'Manual synchronization queue is full')
            worker = self.workers.get(key[0])
            fresh = worker is None
            if fresh:
                worker = {'queue': deque(), 'thread': threading.Thread(
                    target=self._drain, args=(key[0],),
                    name='manual-federation-content-sync', daemon=True)}
            stopping = threading.Event()
            self._status(node, peer_id, project_id, 'queued',
                         'Content synchronization is queued')
            self.tasks[key] = {'thread': worker['thread'], 'stopping': stopping,
                               'node': Path(node).absolute(), 'deployment': deployment}
            worker['queue'].append(key)
            if fresh:
                self.workers[key[0]] = worker
                try:
                    worker['thread'].start()
                except BaseException:
                    self.tasks.pop(key, None)
                    self.workers.pop(key[0], None)
                    raise
        return True

    def _drain(self, root):
        while True:
            with self.lock:
                worker = self.workers[root]
                if not worker['queue']:
                    self.workers.pop(root)
                    return
                key = worker['queue'].popleft()
                task = self.tasks[key]
            try:
                if task['stopping'].is_set():
                    self._status(task['node'], key[1], key[2], 'cancelled',
                                 'Content sync cancelled before dispatch')
                else:
                    self._status(task['node'], key[1], key[2], 'running',
                                 'Content synchronization is running')
                    self._run(task['node'], task['deployment'], key[1], key[2],
                              task['stopping'], key)
            except Exception as exc:
                # A failed status write must not strand the volatile node queue.
                # Native journal recovery remains authoritative; never resend.
                report_failure('manual-content-sync', exc, target=f'{key[1]}/{key[2]}',
                               expected=(SyncBusy, SyncCancelled))
            finally:
                with self.lock:
                    if self.tasks.get(key) is task:
                        self.tasks.pop(key, None)

    def cancel(self, node, peer_id, project_id):
        identifier(peer_id); identifier(project_id)
        key = self._key(node, peer_id, project_id)
        with bounded_process_lock(self.lock, resource='Manual content synchronization'):
            task = self.tasks.get(key)
            if not task or not task['thread'].is_alive():
                return False
            task['stopping'].set()
            self._status(node, peer_id, project_id, 'cancelling',
                         'Cancellation requested; waiting for a safe boundary')
        return True

    @staticmethod
    def _status(node, peer_id, project_id, state, detail):
        with _database(node) as db:
            previous = db.execute(
                'SELECT last_sent,last_remote FROM runtime '
                'WHERE peer_id=? AND project_id=?',
                (peer_id, project_id)).fetchone() or ('[]', '[]')
            db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?,?,?,?)',
                       (peer_id, project_id, state, detail, *previous))

    def _run(self, node, deployment, peer_id, project_id, stopping, key):
        completed = False
        try:
            ContentSyncControl(node, deployment=deployment).synchronize(
                peer_id, project_id, cancelled=stopping.is_set, owner_wait=CONTENT_SYNC_MAX_WAIT)
            completed = True
        except Exception as exc:
            # synchronize() already recorded the durable runtime state.
            report_failure('manual-content-sync', exc, target=f'{peer_id}/{project_id}',
                           expected=(SyncBusy, SyncCancelled))
        finally:
            if completed and stopping.is_set():
                self._status(node, peer_id, project_id, 'idle',
                             'Content sync completed before cancellation')


_MANUAL_SYNCS = ManualSyncTasks()


class ContentSyncScheduler:
    NAME, STOP_TIMEOUT = 'federation-content-sync', stop_timeout(CONTENT_SYNC_TIMEOUT)

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
            try:
                # A streamed exchange can wait on a working peer for minutes;
                # stopping cancels it at the next heartbeat.
                self.control.run_automatic(cancelled=self.stopping.is_set)
                delay = self.interval
            except Exception as exc:
                # Registry/catalog startup can race another scheduler. A
                # transient read failure must not permanently kill content
                # synchronization for the rest of the process lifetime.
                report_failure(self.NAME, exc)
                delay = min(self.interval, 5)
            self.stopping.wait(delay)

    def stop(self, timeout=None):
        """Return whether the worker finished; a live worker stays referenced."""
        from spikes.background_workers import drain
        self.stopping.set()
        clean, self.thread = drain(self.thread, self.STOP_TIMEOUT if timeout is None else timeout)
        return clean


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
            or not 4 < int(length) <= MAX_BODY):
        return handler.send_error(413)
    from spikes.content_receive_jobs import STREAM_TYPE
    if handler.single('Accept') == STREAM_TYPE:
        return _reply_streamed(handler, int(length))
    try:
        body = handler.rfile.read(int(length))
        require(len(body) == int(length), 'Incomplete content sync body')
        envelope, payload = decode_body(body)
        response, response_payload = SyncReceiver(
            handler.server.node, handler.server.administration).receive(envelope, payload)
        if handler.single('X-FPW-State-Receipt') == '1':
            from spikes.sync_fingerprint import receipt
            signed_receipt = receipt(handler.server.administration, response)
            if signed_receipt is not None:
                response = dict(response, state_receipt=signed_receipt)
        raw = encode_body(response, response_payload)
        handler.send_response(200); handler.send_header('Content-Type', CONTENT_TYPE)
        handler.send_header('Content-Length', str(len(raw))); handler.end_headers()
        handler.wfile.write(raw)
    except RequestReadTimeout:
        raise
    except (SyncBusy, ProjectBusy, GitDeadlineExceeded) as exc:
        return handler.reply(503, {'error': 'Content receiver is busy',
            'busy_resource': safe_busy_resource(getattr(exc, 'busy_resource',
                'git-budget' if isinstance(exc, GitDeadlineExceeded) else None)),
            'peer_phase': safe_peer_phase(getattr(exc, 'peer_phase', None))})
    except SyncConflict:
        return handler.reply(409, {'error': 'Content sync requires a conflict decision'})
    except (ValueError, AccessDenied, OSError, sqlite3.Error, subprocess.SubprocessError):
        return handler.reply(422, {'error': 'Content sync request rejected'})


def _receive_job(node, administration, envelope, payload, state_receipt):
    def run():
        response, response_payload = SyncReceiver(node, administration).receive(
            envelope, payload, background=True)
        if state_receipt:
            from spikes.sync_fingerprint import receipt
            signed_receipt = receipt(administration, response)
            if signed_receipt is not None:
                response = dict(response, state_receipt=signed_receipt)
        return encode_body(response, response_payload)
    return run


def _reply_streamed(handler, length):
    """Receive in a background job and stream heartbeats until its outcome.

    Crash boundaries are those of the synchronous receiver: the job runs the
    same SyncReceiver.receive, whose inbound journal and project journal own
    recovery. Losing the connection only stops the heartbeat stream.
    """
    from spikes.content_receive_jobs import JOBS, STREAM_TYPE, error_frame, stream
    try:
        body = handler.rfile.read(length)
        require(len(body) == length, 'Incomplete content sync body')
        envelope, payload = decode_body(body)
        exchange = envelope.get('exchange') if isinstance(envelope, dict) else None
        require(isinstance(exchange, dict), 'Missing content sync exchange')
        operation_id = identifier(exchange.get('operation_id'))
        peer_id = identifier(exchange.get('source_node_id'))
        project_id = identifier(exchange.get('project_id'))
        node = handler.server.node
        job = JOBS.start_or_attach(
            Path(node).absolute(), operation_id, body,
            _receive_job(node, handler.server.administration, envelope, payload,
                         handler.single('X-FPW-State-Receipt') == '1'),
            phase_source=lambda: (sync_diagnostic(node, peer_id, project_id,
                                                  direction='inbound') or {}).get('phase'))
    except RequestReadTimeout:
        raise
    except Exception as exc:  # noqa: BLE001 - mapped to the same typed statuses
        frame = error_frame(exc)
        return handler.reply(frame['status'], {key: value for key, value in frame.items()
                                               if key not in {'type', 'status'}})
    handler.close_connection = True
    handler.send_response_only(200)
    handler.send_header('Content-Type', STREAM_TYPE)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Connection', 'close')
    handler.end_headers()
    def write(raw):
        handler.wfile.write(raw); handler.wfile.flush()
    try:
        stream(job, write)
    except OSError:
        pass  # the sender went away; the job continues and stays attachable
