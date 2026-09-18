# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Publish immutable project records from authoritative node-local chat threads."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from spikes.chat_threads import ChatThreads, MAX_MESSAGE, PRIVACY, TERMINAL
from spikes.configuration import committed_project, parse_node, read_config
from spikes.metadata import MAX_FILE, pairs, require, timestamp, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
MARKER = '<!-- fpw-chat-snapshot-v1\n'
END = '\n-->\n'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def parse_snapshot(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_FILE, 'Invalid chat snapshot size')
    try:
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise ValueError('Chat snapshot must be UTF-8') from exc
    require(text.count(MARKER) == 1, 'Missing or duplicate chat snapshot record')
    payload = text.split(MARKER, 1)[1].split(END, 1)
    require(len(payload) == 2, 'Unclosed chat snapshot record')
    depth, quoted, escape = 0, False, False
    for char in payload[0]:
        if quoted:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            require(depth <= 16, 'Chat snapshot nesting exceeds 16')
        elif char in ']}':
            depth -= 1
    try:
        envelope = json.loads(payload[0], object_pairs_hook=pairs,
                              parse_constant=lambda _: require(False, 'Non-finite JSON number'))
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid chat snapshot JSON') from exc
    require(isinstance(envelope, dict) and set(envelope) == {'record', 'record_sha256'},
            'Invalid chat snapshot envelope')
    record = envelope['record']
    fields = {'schema', 'mode', 'snapshot_id', 'project_id', 'thread_id', 'thread_revision',
              'assignment_revision', 'start_sequence', 'end_sequence', 'created_at',
              'privacy', 'base', 'messages', 'turns'}
    require(isinstance(record, dict) and set(record) == fields
            and record.get('schema') == 'fpw-chat-snapshot-v1',
            'Unknown chat snapshot schema')
    require(record['mode'] in {'full', 'delta'}, 'Invalid chat snapshot mode')
    uuid(record['snapshot_id']); uuid(record['project_id']); uuid(record['thread_id'])
    timestamp(record['created_at'])
    require(record['privacy'] in PRIVACY_ORDER, 'Invalid chat snapshot privacy')
    for field in ('thread_revision', 'assignment_revision', 'start_sequence', 'end_sequence'):
        require(type(record[field]) is int and record[field] >= 0,
                'Invalid chat snapshot counter')
    require(1 <= record['start_sequence'] <= record['end_sequence'],
            'Invalid chat snapshot sequence range')
    require(isinstance(record['messages'], list) and isinstance(record['turns'], list),
            'Invalid chat snapshot collections')
    require(record['mode'] == 'delta' or record['base'] is None,
            'Full chat snapshot cannot have a base')
    if record['mode'] == 'delta':
        require(isinstance(record['base'], dict)
                and set(record['base']) == {'snapshot_id', 'record_sha256',
                                             'end_sequence', 'thread_revision'},
                'Invalid delta base')
        uuid(record['base']['snapshot_id'])
        require(isinstance(record['base']['record_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', record['base']['record_sha256']),
                'Invalid delta base digest')
        require(type(record['base']['end_sequence']) is int
                and type(record['base']['thread_revision']) is int
                and record['base']['thread_revision'] >= 0
                and record['start_sequence'] == record['base']['end_sequence'] + 1,
                'Delta sequence does not follow its base')
    message_fields = {'message_id', 'sequence', 'role', 'content', 'content_sha256',
                      'privacy', 'author_id', 'created_at', 'supersedes_id'}
    require(len(record['messages']) == record['end_sequence'] - record['start_sequence'] + 1,
            'Chat snapshot sequence range differs from its messages')
    for offset, message in enumerate(record['messages']):
        require(isinstance(message, dict) and set(message) == message_fields,
                'Invalid chat snapshot message')
        uuid(message['message_id'])
        require(message['sequence'] == record['start_sequence'] + offset
                and message['role'] in {'user', 'assistant'}
                and isinstance(message['content'], str)
                and 0 < len(message['content'].encode('utf-8')) <= MAX_MESSAGE
                and message['privacy'] in PRIVACY,
                'Invalid chat snapshot message')
        require(hashlib.sha256(message['content'].encode('utf-8')).hexdigest()
                == message['content_sha256'], 'Chat snapshot message digest mismatch')
        if message['role'] == 'user':
            uuid(message['author_id'])
        else:
            require(isinstance(message['author_id'], str)
                    and message['author_id'].startswith('backend:'),
                    'Invalid assistant author')
            uuid(message['author_id'].removeprefix('backend:'))
        timestamp(message['created_at'])
        if message['supersedes_id'] is not None:
            uuid(message['supersedes_id'])
    require(record['privacy'] == max((item['privacy'] for item in record['messages']),
                                     key=PRIVACY_ORDER.__getitem__),
            'Chat snapshot privacy is not the strictest message privacy')
    turn_fields = {'turn_id', 'user_message_id', 'run_id', 'assistant_message_id',
                   'state', 'error', 'manifest_id'}
    for turn in record['turns']:
        require(isinstance(turn, dict) and set(turn) == turn_fields,
                'Invalid chat snapshot turn')
        uuid(turn['turn_id']); uuid(turn['user_message_id'])
        for field in ('run_id', 'assistant_message_id', 'manifest_id'):
            if turn[field] is not None:
                uuid(turn[field])
        require(turn['state'] in {'prepared', 'run-bound', 'completed'} | TERMINAL
                and (turn['error'] is None or isinstance(turn['error'], str)),
                'Invalid chat snapshot turn')
    digest = hashlib.sha256(_canonical(record)).hexdigest()
    require(isinstance(envelope['record_sha256'], str)
            and envelope['record_sha256'] == digest, 'Chat snapshot digest mismatch')
    return record, digest


class ChatRecords:
    def __init__(self, node_path, projects, *, state_dir=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.chat'))

    def _identity(self):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        return node['id'], ProjectCreation(self.node_path).author_id()

    def _threads(self):
        info = self.state_dir.stat()
        require(self.state_dir.absolute() == self.state_dir.resolve()
                and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Chat state directory requires owned mode 0700 without symlinks')
        return ChatThreads(self.state_dir)

    def assign(self, *, project_id, thread_id, expected_revision,
               checkpoint=lambda stage: None):
        uuid(project_id); uuid(thread_id)
        workspace = self.projects.workspace(project_id, blocking=False)
        committed_project(workspace.git, workspace.git.head(), project_id)
        node_id, user_id = self._identity()
        return self._threads().assign_project(
            thread_id=thread_id, node_id=node_id, user_id=user_id,
            project_id=project_id, expected_revision=expected_revision,
            checkpoint=checkpoint)

    def publish(self, request, operation_id, *, checkpoint=lambda stage: None):
        required = {'project_id', 'thread_id', 'expected_thread_revision', 'expected_head',
                    'snapshot_id', 'mode', 'title', 'created_at',
                    'base_snapshot_id', 'base_snapshot_sha256'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid chat snapshot request')
        for key in ('project_id', 'thread_id', 'snapshot_id'):
            uuid(request[key])
        uuid(operation_id)
        require(type(request['expected_thread_revision']) is int
                and request['expected_thread_revision'] >= 0, 'Invalid thread revision')
        require(isinstance(request['expected_head'], str)
                and re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head']),
                'Invalid expected project commit')
        require(request['mode'] in {'full', 'delta'}, 'Invalid snapshot mode')
        require(isinstance(request['title'], str) and request['title'].strip() == request['title']
                and 0 < len(request['title']) <= 200
                and not any(c in request['title'] for c in '\0\r\n'), 'Invalid snapshot title')
        timestamp(request['created_at'])
        if request['mode'] == 'full':
            require(request['base_snapshot_id'] is None
                    and request['base_snapshot_sha256'] is None,
                    'Full snapshot cannot have a base')
        else:
            uuid(request['base_snapshot_id'])
            require(isinstance(request['base_snapshot_sha256'], str)
                    and re.fullmatch(r'[0-9a-f]{64}', request['base_snapshot_sha256']),
                    'Delta snapshot requires a base digest')

        workspace = self.projects.workspace(request['project_id'], blocking=False)
        node_id, user_id = self._identity()
        author = user_id
        intent = dict(request, action='publish-chat-snapshot', author_id=author)

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'], 'Project changed before chat publication')
            committed_project(ws.git, head, request['project_id'])
            files = ws.git.snapshot(head)
            entities = validate_snapshot(files)
            require(request['snapshot_id'] not in entities, 'Snapshot ID already exists')
            thread = self._threads().get(request['thread_id'], node_id, user_id)
            require(thread['project_id'] == request['project_id'],
                    'Chat thread is not assigned to this project')
            require(thread['revision'] == request['expected_thread_revision'],
                    'Chat thread changed before publication')
            start = 1
            base = None
            if request['mode'] == 'delta':
                base_id = request['base_snapshot_id']
                meta = entities.get(base_id)
                require(meta is not None and meta['kind'] == 'snapshot' and 'file' in meta,
                        'Delta base snapshot is missing')
                base_record, base_digest = parse_snapshot(
                    files[f'artifacts/{base_id}/{meta["file"]}'])
                require(base_digest == request['base_snapshot_sha256'],
                        'Delta base snapshot digest mismatch')
                require(base_record['snapshot_id'] == base_id
                        and base_record['privacy'] == meta['privacy']
                        and base_record['project_id'] == request['project_id']
                        and base_record['thread_id'] == request['thread_id'],
                        'Delta base belongs to a different chat')
                start = base_record['end_sequence'] + 1
                base = {'snapshot_id': base_id, 'record_sha256': base_digest,
                        'end_sequence': base_record['end_sequence'],
                        'thread_revision': base_record['thread_revision']}
            messages = [item for item in thread['messages'] if item['sequence'] >= start]
            require(bool(messages), 'Snapshot contains no new messages')
            message_ids = {item['message_id'] for item in messages}
            turns = [item for item in thread['turns']
                     if item['user_message_id'] in message_ids
                     or item['assistant_message_id'] in message_ids]
            privacy = max((item['privacy'] for item in messages), key=PRIVACY_ORDER.__getitem__)
            record = {'schema': 'fpw-chat-snapshot-v1', 'mode': request['mode'],
                      'snapshot_id': request['snapshot_id'],
                      'project_id': request['project_id'], 'thread_id': request['thread_id'],
                      'thread_revision': thread['revision'], 'assignment_revision': thread['assignment_revision'],
                      'start_sequence': messages[0]['sequence'], 'end_sequence': messages[-1]['sequence'],
                      'created_at': request['created_at'], 'privacy': privacy, 'base': base,
                      'messages': messages, 'turns': turns}
            digest = hashlib.sha256(_canonical(record)).hexdigest()
            envelope = _canonical({'record': record, 'record_sha256': digest}).decode('utf-8')
            readable = '\n\n'.join(
                f"### {'Uživatel' if item['role'] == 'user' else 'Asistent'}\n\n{item['content']}"
                for item in messages)
            content = (f'# {request["title"]}\n\n{MARKER}{envelope}{END}\n{readable}\n').encode('utf-8')
            require(len(content) <= MAX_FILE, 'Chat snapshot exceeds artifact limit')
            relations = ([{'type': 'derived-from', 'target_id': request['base_snapshot_id']}]
                         if request['mode'] == 'delta' else [])
            meta = {'schema_version': 1, 'id': request['snapshot_id'],
                    'title': request['title'], 'kind': 'snapshot',
                    'created_at': request['created_at'], 'author_id': author,
                    'privacy': privacy, 'provenance': 'snapshot', 'file': 'snapshot.md',
                    'relations': relations}
            prefix = f'artifacts/{request["snapshot_id"]}/'
            changes = {prefix + 'snapshot.md': content,
                       prefix + 'metadata.json': (json.dumps(meta, ensure_ascii=False,
                           sort_keys=True, indent=2) + '\n').encode('utf-8')}
            return changes, 'Local workspace author', author + '@local.invalid', 'Publish chat snapshot'

        return workspace.transact(operation_id, intent, prepare,
                                  expected_head=request['expected_head'], checkpoint=checkpoint)
