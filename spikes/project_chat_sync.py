# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Project-scoped RW chat payload for the bidirectional federation sync."""
import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5

from spikes.administration import AccessDenied
from spikes.chat_threads import ChatThreads, TERMINAL
from spikes.federation_accounts import canonical
from spikes.metadata import require, timestamp, uuid


MAX_CHAT_PAYLOAD = 16 * 1024 * 1024
MAX_PROJECT_THREADS = 64
TRANSFERABLE_PRIVACY = {'public', 'project', 'confidential'}


def chat_root(node):
    node = Path(node).absolute()
    return node.parent / ('.' + node.name + '.chat')


def _mapping_rows(service, peer_id, project_id):
    """Return active exact local->remote user bindings for one shared project."""
    with service.locked() as (_, state, _, _):
        local_node_id = state['node_id']
        rows = []
        for mapping in state['mappings']:
            spec = mapping['spec']
            if (project_id not in spec['project_ids']
                    or not service.mapping_active(state, mapping)):
                continue
            try:
                local, remote, peer = service.mapping_context(state, spec)
            except (AccessDenied, ValueError, OSError):
                continue
            if peer['id'] == peer_id:
                rows.append({'mapping_id': spec['id'],
                             'local_user_id': local['user_id'],
                             'remote_user_id': remote['user_id']})
        rows.sort(key=lambda row: (row['local_user_id'], row['remote_user_id'],
                                  row['mapping_id']))
        return local_node_id, rows


def active_mapping_count(service, peer_id, project_id):
    """Return exact active mappings for a project without exposing identities."""
    return len(_mapping_rows(service, peer_id, project_id)[1])


def _validate_thread(thread, project_id, *, source_node_id, source_user_id):
    fields = {'thread_id', 'node_id', 'user_id', 'status', 'classification',
              'created_at', 'revision', 'project_id', 'assignment_revision',
              'response_language', 'forked_from_thread_id', 'forked_from_digest',
              'messages', 'turns'}
    require(isinstance(thread, dict) and set(thread) == fields,
            'Invalid synchronized chat thread')
    for value in (thread['thread_id'], thread['node_id'], thread['user_id']):
        uuid(value)
    require(thread['node_id'] == source_node_id
            and thread['user_id'] == source_user_id
            and thread['project_id'] == project_id,
            'Synchronized chat owner or project differs')
    timestamp(thread['created_at'])
    require(thread['status'] in {'active', 'archived'}
            and thread['classification'] in {'brainstorming', 'orchestration'}
            and type(thread['revision']) is int and thread['revision'] >= 0
            and type(thread['assignment_revision']) is int
            and thread['assignment_revision'] >= 1,
            'Invalid synchronized chat metadata')
    if thread['forked_from_thread_id'] is None:
        require(thread['forked_from_digest'] is None,
                'Chat fork digest requires an origin')
    else:
        uuid(thread['forked_from_thread_id'])
        require(isinstance(thread['forked_from_digest'], str)
                and len(thread['forked_from_digest']) == 64,
                'Invalid synchronized chat fork provenance')
    messages = thread['messages']; turns = thread['turns']
    require(isinstance(messages, list) and isinstance(turns, list),
            'Invalid synchronized chat contents')
    message_ids = set()
    for sequence, message in enumerate(messages, 1):
        require(isinstance(message, dict) and set(message) == {
            'message_id', 'sequence', 'role', 'content', 'content_sha256',
            'privacy', 'author_id', 'created_at', 'supersedes_id'},
            'Invalid synchronized chat message')
        uuid(message['message_id']); timestamp(message['created_at'])
        raw = message['content'].encode('utf-8') if isinstance(
            message['content'], str) else b''
        require(message['sequence'] == sequence
                and message['message_id'] not in message_ids
                and message['role'] in {'user', 'assistant'}
                and message['privacy'] in TRANSFERABLE_PRIVACY
                and bool(raw.strip()) and len(raw) <= 1024 * 1024
                and hashlib.sha256(raw).hexdigest() == message['content_sha256'],
                'Invalid or local-only synchronized chat message')
        message_ids.add(message['message_id'])
        if message['supersedes_id'] is not None:
            uuid(message['supersedes_id'])
            require(message['supersedes_id'] in message_ids,
                    'Synchronized chat supersedes an unavailable message')
        if message['role'] == 'user':
            require(message['author_id'] == source_user_id,
                    'Synchronized user message has another author')
        else:
            require(isinstance(message['author_id'], str)
                    and message['author_id'].startswith('backend:'),
                    'Invalid synchronized assistant author')
            uuid(message['author_id'].removeprefix('backend:'))
    seen_turns = set()
    assistant_runs = {}
    for turn in turns:
        require(isinstance(turn, dict) and set(turn) == {
            'turn_id', 'user_message_id', 'run_id', 'assistant_message_id',
            'state', 'error', 'manifest_id', 'response_language',
            'language_source', 'language_compliance'},
            'Invalid synchronized chat turn')
        uuid(turn['turn_id']); uuid(turn['user_message_id'])
        require(turn['turn_id'] not in seen_turns
                and turn['user_message_id'] in message_ids
                and turn['state'] in ({'completed'} | TERMINAL),
                'Active or invalid chat turn cannot be synchronized')
        seen_turns.add(turn['turn_id'])
        for field in ('run_id', 'assistant_message_id', 'manifest_id'):
            if turn[field] is not None:
                uuid(turn[field])
        require(turn['assistant_message_id'] is None
                or turn['assistant_message_id'] in message_ids,
                'Synchronized turn references an unavailable message')
        if turn['assistant_message_id'] is not None:
            require(turn['run_id'] is not None
                    and turn['assistant_message_id'] not in assistant_runs,
                    'Synchronized assistant message has an invalid run')
            assistant_runs[turn['assistant_message_id']] = turn['run_id']
    for message in messages:
        if message['role'] == 'assistant':
            require(assistant_runs.get(message['message_id'])
                    == message['author_id'].removeprefix('backend:'),
                    'Synchronized assistant author differs from its turn')
    return thread


def _normalized(thread):
    value = copy.deepcopy(thread)
    value.pop('node_id'); value.pop('user_id')
    for message in value['messages']:
        if message['role'] == 'user':
            message['author_id'] = 'mapped-owner'
    return value


def digest(thread):
    return hashlib.sha256(canonical(_normalized(thread))).hexdigest()


def inventory(payload):
    return sorted(({'thread_id': row['thread']['thread_id'],
                    'digest': digest(row['thread'])}
                   for row in payload.get('threads', [])),
                  key=lambda row: row['thread_id'])


def export_project(node, service, peer_id, project_id):
    local_node_id, mappings = _mapping_rows(service, peer_id, project_id)
    root = chat_root(node)
    if not root.exists() or not mappings:
        value = {'schema_version': 1, 'project_id': project_id,
                 'source_node_id': local_node_id,
                 'recipient_node_id': peer_id, 'threads': []}
        return [], canonical(value)
    store = ChatThreads(root); rows = []
    for mapping in mappings:
        for thread in store.list(local_node_id, mapping['local_user_id']):
            if thread['project_id'] != project_id:
                continue
            # A local-only or in-flight thread remains entirely node-local.
            if (any(message['privacy'] == 'local-only'
                    for message in thread['messages'])
                    or any(turn['state'] not in ({'completed'} | TERMINAL)
                           for turn in thread['turns'])):
                continue
            _validate_thread(thread, project_id, source_node_id=local_node_id,
                             source_user_id=mapping['local_user_id'])
            rows.append({'mapping_id': mapping['mapping_id'],
                         'source_user_id': mapping['local_user_id'],
                         'recipient_user_id': mapping['remote_user_id'],
                         'thread': thread})
    require(len(rows) <= MAX_PROJECT_THREADS,
            'Shared project has more than 64 transferable chat threads')
    rows.sort(key=lambda row: row['thread']['thread_id'])
    require(len({row['thread']['thread_id'] for row in rows}) == len(rows),
            'A shared chat thread is owned by more than one mapped user')
    value = {'schema_version': 1, 'project_id': project_id,
             'source_node_id': local_node_id, 'recipient_node_id': peer_id,
             'threads': rows}
    raw = canonical(value)
    require(len(raw) <= MAX_CHAT_PAYLOAD,
            'Project chat payload exceeds 16 MiB')
    return inventory(value), raw


def validate_payload(raw, *, project_id, source_node_id, recipient_node_id,
                     service):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_CHAT_PAYLOAD,
            'Invalid project chat payload size')
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid project chat payload') from exc
    require(isinstance(value, dict) and set(value) == {
        'schema_version', 'project_id', 'source_node_id',
        'recipient_node_id', 'threads'} and value['schema_version'] == 1
        and value['project_id'] == project_id
        and value['source_node_id'] == source_node_id
        and value['recipient_node_id'] == recipient_node_id
        and isinstance(value['threads'], list)
        and len(value['threads']) <= MAX_PROJECT_THREADS,
        'Project chat payload differs from signed exchange')
    local_node_id, mappings = _mapping_rows(service, source_node_id, project_id)
    require(local_node_id == recipient_node_id,
            'Project chat payload targets another node')
    allowed = {(row['mapping_id'], row['remote_user_id'], row['local_user_id'])
               for row in mappings}
    seen = set()
    for row in value['threads']:
        require(isinstance(row, dict) and set(row) == {
            'mapping_id', 'source_user_id', 'recipient_user_id', 'thread'},
            'Invalid project chat mapping envelope')
        require((row['mapping_id'], row['source_user_id'],
                 row['recipient_user_id']) in allowed,
                'Project chat lacks an active exact user mapping')
        _validate_thread(row['thread'], project_id,
                         source_node_id=source_node_id,
                         source_user_id=row['source_user_id'])
        thread_id = row['thread']['thread_id']
        require(thread_id not in seen, 'Duplicate synchronized chat thread')
        seen.add(thread_id)
    require(canonical(value) == raw, 'Project chat payload is not canonical')
    return value


def validate_export_authority(raw, *, project_id, source_node_id,
                              recipient_node_id, service):
    """Recheck a durable outbound payload without rebuilding its bytes."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_CHAT_PAYLOAD,
            'Invalid outbound project chat payload')
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid outbound project chat payload') from exc
    require(value.get('project_id') == project_id
            and value.get('source_node_id') == source_node_id
            and value.get('recipient_node_id') == recipient_node_id,
            'Outbound project chat payload targets another scope')
    local_node_id, mappings = _mapping_rows(service, recipient_node_id, project_id)
    require(local_node_id == source_node_id,
            'Outbound project chat source identity changed')
    allowed = {(row['mapping_id'], row['local_user_id'], row['remote_user_id'])
               for row in mappings}
    require(all((row.get('mapping_id'), row.get('source_user_id'),
                 row.get('recipient_user_id')) in allowed
                for row in value.get('threads', [])),
            'Outbound project chat mapping changed before transport')
    return value


def _read(db, thread_id):
    row = db.execute('SELECT node_id,user_id,status,classification,created_at,revision,'
                     'next_sequence,project_id,assignment_revision,response_language,'
                     'forked_from_thread_id,forked_from_digest FROM threads '
                     'WHERE thread_id=?', (thread_id,)).fetchone()
    if row is None:
        return None
    messages = [dict(zip(
        ('message_id', 'sequence', 'role', 'content', 'content_sha256', 'privacy',
         'author_id', 'created_at', 'supersedes_id'),
        item[:3] + (item[3].decode('utf-8'),) + item[4:]))
        for item in db.execute('SELECT message_id,sequence,role,content,content_sha256,'
                               'privacy,author_id,created_at,supersedes_id FROM messages '
                               'WHERE thread_id=? ORDER BY sequence', (thread_id,))]
    turns = [dict(zip(
        ('turn_id', 'user_message_id', 'run_id', 'assistant_message_id', 'state',
         'error', 'manifest_id', 'response_language', 'language_source',
         'language_compliance'), item))
        for item in db.execute('SELECT turn_id,user_message_id,run_id,assistant_message_id,'
                               'state,error,manifest_id,response_language,language_source,'
                               'language_compliance FROM turns WHERE thread_id=? ORDER BY rowid',
                               (thread_id,))]
    return {'thread_id': thread_id, 'node_id': row[0], 'user_id': row[1],
            'status': row[2], 'classification': row[3], 'created_at': row[4],
            'revision': row[5], 'project_id': row[7],
            'assignment_revision': row[8], 'response_language': row[9],
            'forked_from_thread_id': row[10], 'forked_from_digest': row[11],
            'messages': messages, 'turns': turns}


def _localize(thread, node_id, user_id):
    value = copy.deepcopy(thread); value['node_id'] = node_id; value['user_id'] = user_id
    for message in value['messages']:
        if message['role'] == 'user':
            message['author_id'] = user_id
    return value


def _insert(db, thread):
    db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        thread['thread_id'], thread['node_id'], thread['user_id'],
        thread['classification'], thread['status'], thread['created_at'],
        thread['revision'], len(thread['messages']), thread['project_id'],
        thread['assignment_revision'], thread['response_language'],
        thread['forked_from_thread_id'], thread['forked_from_digest']))
    for message in thread['messages']:
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)', (
            message['message_id'], thread['thread_id'], message['sequence'],
            message['role'], message['content'].encode('utf-8'),
            message['content_sha256'], message['privacy'], message['author_id'],
            message['created_at'], message['supersedes_id']))
    for turn in thread['turns']:
        db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?,?,?)', (
            turn['turn_id'], thread['thread_id'], turn['user_message_id'],
            turn['run_id'], turn['assistant_message_id'], turn['state'],
            turn['error'], turn['manifest_id'], turn['response_language'],
            turn['language_source'], turn['language_compliance']))


def _replace(db, thread):
    thread_id = thread['thread_id']
    require(db.execute('SELECT 1 FROM deletions WHERE thread_id=?',
                       (thread_id,)).fetchone() is None,
            'Synchronized chat deletion is in progress')
    db.execute('DELETE FROM turns WHERE thread_id=?', (thread_id,))
    db.execute('DELETE FROM messages WHERE thread_id=?', (thread_id,))
    db.execute('DELETE FROM threads WHERE thread_id=?', (thread_id,))
    _insert(db, thread)


def _lineage(older, newer):
    stable = ('thread_id', 'classification', 'created_at', 'project_id',
              'assignment_revision', 'forked_from_thread_id', 'forked_from_digest')
    if any(older[key] != newer[key] for key in stable):
        return False
    old_messages = _normalized(older)['messages']
    new_messages = _normalized(newer)['messages']
    old_turns = older['turns']; new_turns = newer['turns']
    if (old_messages != new_messages[:len(old_messages)]
            or old_turns != new_turns[:len(old_turns)]
            or newer['revision'] < older['revision']):
        return False
    if older['status'] == 'archived' and newer['status'] != 'archived':
        return False
    return (len(new_messages), len(new_turns), newer['revision']) != (
        len(old_messages), len(old_turns), older['revision'])


def _fork(thread, original_thread_id, losing_digest):
    namespace = UUID(original_thread_id)
    fork_id = str(uuid5(namespace, 'federation-fork:' + losing_digest))
    value = copy.deepcopy(thread)
    message_ids = {message['message_id']: str(uuid5(
        UUID(fork_id), 'message:' + message['message_id']))
        for message in value['messages']}
    run_ids = {turn['run_id']: str(uuid5(UUID(fork_id), 'run:' + turn['run_id']))
               for turn in value['turns'] if turn['run_id'] is not None}
    for message in value['messages']:
        message['message_id'] = message_ids[message['message_id']]
        if message['supersedes_id'] is not None:
            message['supersedes_id'] = message_ids[message['supersedes_id']]
        if message['role'] == 'assistant':
            old_run = message['author_id'].removeprefix('backend:')
            message['author_id'] = 'backend:' + run_ids[old_run]
    for turn in value['turns']:
        turn['turn_id'] = str(uuid5(UUID(fork_id), 'turn:' + turn['turn_id']))
        turn['user_message_id'] = message_ids[turn['user_message_id']]
        if turn['assistant_message_id'] is not None:
            turn['assistant_message_id'] = message_ids[turn['assistant_message_id']]
        if turn['run_id'] is not None:
            turn['run_id'] = run_ids[turn['run_id']]
    value['thread_id'] = fork_id
    value['forked_from_thread_id'] = original_thread_id
    value['forked_from_digest'] = losing_digest
    return value


def apply_payload(node, value, *, checkpoint=lambda stage: None):
    root = chat_root(node); root.mkdir(mode=0o700, exist_ok=True)
    store = ChatThreads(root); conflicts = []
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in value['threads']:
            incoming = _localize(row['thread'], value['recipient_node_id'],
                                 row['recipient_user_id'])
            local = _read(db, incoming['thread_id'])
            if local is None:
                _insert(db, incoming); continue
            require(local['node_id'] == value['recipient_node_id']
                    and local['user_id'] == row['recipient_user_id']
                    and local['project_id'] == value['project_id'],
                    'Synchronized thread ID belongs to another local owner')
            local_digest, incoming_digest = digest(local), digest(incoming)
            if local_digest == incoming_digest:
                continue
            if _lineage(local, incoming):
                _replace(db, incoming); continue
            if _lineage(incoming, local):
                continue
            winner, loser, losing_digest = ((local, incoming, incoming_digest)
                if local_digest < incoming_digest
                else (incoming, local, local_digest))
            fork = _fork(loser, incoming['thread_id'], losing_digest)
            existing_fork = _read(db, fork['thread_id'])
            if existing_fork is None:
                _insert(db, fork)
            else:
                require(digest(existing_fork) == digest(fork),
                        'Deterministic chat fork ID has different contents')
            if digest(local) != digest(winner):
                _replace(db, winner)
            conflicts.append({'thread_id': incoming['thread_id'],
                              'fork_thread_id': fork['thread_id']})
        checkpoint('chats-applied')
        db.commit()
    return conflicts
