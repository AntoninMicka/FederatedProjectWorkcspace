# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Task history lives in task Markdown; SQLite holds unfinished intents only."""
import base64
import hashlib
import json
import re
from uuid import UUID, uuid5

from spikes.markdown_documents import document
from spikes.metadata import require, validate_snapshot
from spikes.plan_item_editor import item_span
from spikes.task_graph import project_task_graph
from spikes.task_work import canonical

PATTERN = re.compile(r'(?m)^[ \t]*> Záznam Workspace .*?<!-- fpw-task-history:([A-Za-z0-9+/=]+) -->\r?$')
TYPES = {'task-activity', 'task-record-publish', 'task-record-offer'}
ROW_FIELDS = {'id', 'user_id', 'window_id', 'request', 'doc'}


def escaped(value):
    value = ' '.join(value.split()).replace('&', '&amp;')
    value = re.sub(r'([\\`*_{}\[\]()<>!|])', r'\\\1', value)
    return value


def line(envelope):
    from spikes.task_records import offer
    row = envelope['row']; op = json.loads(row['doc'])
    kind = op['record_type']
    if kind == 'task-activity':
        state = offer(op)
        content = state['comment']
        detail = {'succeeded': 'provedeno', 'failed': 'neúspěšné', 'unknown': 'výsledek neověřen'}[op['outcome']]
        if state['state'] in {'draft', 'deferred', 'dismissed'}:
            detail += '; '+{'draft': 'rozepsáno', 'deferred': 'odloženo', 'dismissed': 'odmítnuto'}[state['state']]
        outputs = []
    elif kind == 'task-record-publish':
        record = op['record']
        content = ' | '.join(revision['comment'] for revision in record['revisions'])
        detail = 'záznam práce'
        outputs = record['outputs']
    else:
        body = json.loads(row['request'])
        content = body['comment']
        detail = {'draft': 'rozepsáno', 'deferred': 'odloženo', 'dismissed': 'odmítnuto'}[body['state']]
        outputs = []
    links = list(dict.fromkeys('['+escaped(o['title'])+']('+o['path']+')' for o in outputs
        if o['project_id'] == envelope['project_id']))
    payload = base64.b64encode(canonical(envelope).encode()).decode()
    return ('> Záznam Workspace — '+escaped(content)+'; '+detail+
        ('; výstupy: '+', '.join(links) if links else '')+' <!-- fpw-task-history:'+payload+' -->')


def decode(match):
    envelope = json.loads(base64.b64decode(match[1], validate=True))
    require(set(envelope) == {'row', 'project_id', 'task_id'}, 'Invalid task history envelope')
    row = envelope['row']; require(set(row) == ROW_FIELDS, 'Invalid task history row')
    op = json.loads(row['doc'])
    require(op.get('record_type') in TYPES, 'Invalid task history type')
    if op['record_type'] == 'task-activity':
        context = op['context']
        require(op['event_id'] == row['id'] and op['author_id'] == row['user_id'], 'Activity owner differs')
    elif op['record_type'] == 'task-record-publish':
        from spikes.task_record_schema import validate
        validate(op['record'])
        require(op['state'] == 'completed', 'Unfinished task record in history')
        context = op['record']['context']
    else:
        require(op['state'] == 'completed', 'Unfinished task offer in history')
        context = envelope
    require(context['project_id'] == envelope['project_id'] and context['task_id'] == envelope['task_id'],
        'History belongs to another task')
    require(match[0].strip() == line(envelope), 'Task history was edited; resolve the conflict before continuing')
    return envelope


def rows(files, pid):
    entities = validate_snapshot(files)
    graph = project_task_graph(files, entities, pid, '0'*40)
    require(graph['status'] == 'ready', 'Roadmapa nemá platný graf; záznamy nelze ověřit.')
    result = {}
    for task in graph['nodes']:
        doc = document(files, entities, task['source']['artifact_id'])
        start, end = item_span(doc['body'], task['id'])
        for match in PATTERN.finditer(doc['body'][start:end]):
            envelope = decode(match)
            require(envelope['project_id'] == pid and envelope['task_id'] == task['id'],
                'History belongs to another task')
            row = envelope['row']
            require(row['id'] not in result, 'Duplicate task history')
            result[row['id']] = row
    return result


class ActivityText:
    def __init__(self, work):
        self.work = work

    def read(self, pid):
        require(self.work.can_read(pid), 'Právo číst úkol bylo odebráno.')
        git = self.work.projects.repository(pid); head = git.head()
        result = rows(git.snapshot(head), pid)
        require(git.head() == head, 'Projekt se změnil; obnovte kontext.')
        return result

    def lookup(self, identifier, window_id=None):
        with self.work._db() as db:
            sessions = db.execute('SELECT doc FROM sessions WHERE user_id=?',
                (self.work.user_id,)).fetchall() if db else []
        projects = dict.fromkeys(json.loads(s[0])['project_id'] for s in sessions
            if window_id is None or json.loads(s[0])['window_id'] == window_id)
        for pid in projects:
            if not self.work.can_read(pid):
                continue
            row = self.read(pid).get(identifier)
            if row:
                require(row['user_id'] == self.work.user_id and (window_id is None or row['window_id'] == window_id),
                    'Operation ID belongs to another owner/window')
                return row
        return None

    def envelope(self, row):
        op = json.loads(row['doc'])
        if op['record_type'] == 'task-activity': context = op['context']
        elif op['record_type'] == 'task-record-publish': context = op['record']['context']
        else:
            body = json.loads(row['request'])
            with self.work._db() as db:
                context = self.work._session(db, body['work_session_id'], row['window_id'])
        return dict(row=dict(row), project_id=context['project_id'], task_id=context['task_id'])

    def write(self, row, *, checkpoint=lambda stage: None):
        from spikes.task_record_schema import PRIVACY, encoded
        envelope = self.envelope(row); op = json.loads(row['doc']); pid = envelope['project_id']
        self.work._authorize(pid)
        ws = self.work.projects.workspace(pid, blocking=False)
        ws.recover()
        head = ws.git.head(); files = ws.git.snapshot(head)
        current = rows(files, pid).get(row['id'])
        if current == dict(row): return
        operation_id = str(uuid5(UUID(row['id']), 'task-text:'+head+':'+hashlib.sha256(canonical(envelope).encode()).hexdigest()))
        def prepare(workspace):
            self.work._authorize(pid)
            files = workspace.git.snapshot(head); entities = validate_snapshot(files)
            graph = project_task_graph(files, entities, pid, head)
            task = next((t for t in graph['nodes'] if t['id'] == envelope['task_id']), None)
            require(task is not None, 'Původní úkol byl odstraněn; záznam zůstává v journalu.')
            doc = document(files, entities, task['source']['artifact_id'])
            privacy = op.get('privacy', 'local-only') if op['record_type'] == 'task-activity' else op.get('record', {}).get('privacy', 'project')
            changes = {}
            if PRIVACY[privacy] > PRIVACY[entities[doc['id']]['privacy']]:
                require(not self.work.network or privacy != 'local-only', 'Local-only history cannot cross the network boundary')
                meta = dict(entities[doc['id']], privacy=privacy)
                changes['artifacts/'+doc['id']+'/metadata.json'] = encoded(meta)
            start, end = item_span(doc['body'], task['id']); block = doc['body'][start:end]
            newline = '\r\n' if '\r\n' in block else '\n'
            indent = re.match(r'[ \t]*', block)[0]+'  '
            replacement = indent+line(envelope)
            if current:
                old = next((m for m in PATTERN.finditer(block) if decode(m)['row']['id'] == row['id']), None)
                require(old is not None, 'Task history changed')
                block = block[:old.start()]+replacement+block[old.end():]
            else:
                block = block.rstrip('\r\n')+newline+replacement+newline
            body = doc['body'][:start]+block+doc['body'][end:]
            raw = files[doc['path']]; prefix = raw[:-len(doc['body'].encode())] if doc['body'] else raw
            changes[doc['path']] = prefix+body.encode()
            return changes, 'Workspace user', self.work.user_id+'@local.invalid', 'Record history in '+task['id']
        ws.transact(operation_id, dict(action='task-history-text', envelope=envelope, base_head=head),
            prepare, expected_head=head, checkpoint=checkpoint)
        checkpoint('task-history-text-committed')
        require(self.read(pid).get(row['id']) == dict(row), 'Task history readback failed')

    def drain(self, identifiers=None, *, checkpoint=lambda stage: None):
        """Commit/read back exact rows before deleting finished intents from SQLite."""
        with self.work._db() as db:
            pending = db.execute('SELECT * FROM operations WHERE user_id=?', (self.work.user_id,)).fetchall() if db else []
        migrated = []
        for original in pending:
            if identifiers is not None and original['id'] not in identifiers: continue
            op = json.loads(original['doc'])
            if op.get('record_type') not in TYPES: continue
            if op['record_type'] == 'task-activity':
                if (op['outcome'] == 'unknown' and 'response_code' not in op) or op.get('offer', {}).get('pending_operation_id'): continue
            elif op['state'] != 'completed': continue
            with self.work._operation_lock(original['id']):
                with self.work._db() as db:
                    row = db.execute('SELECT * FROM operations WHERE id=? AND user_id=?',
                        (original['id'], self.work.user_id)).fetchone()
                if row is None or dict(row) != dict(original): continue
                self.write(dict(row), checkpoint=checkpoint)
                with self.work._db(write=True) as db:
                    db.execute('PRAGMA secure_delete=ON')
                    deleted = db.execute('DELETE FROM operations WHERE id=? AND user_id=? AND doc=? AND request=?',
                        (row['id'], self.work.user_id, row['doc'], row['request'])).rowcount
                    require(deleted == 1, 'Task history changed before cleanup; retry the operation')
                    checkpoint('task-history-text-before-delete-commit')
                migrated.append(row['id'])
        return migrated
