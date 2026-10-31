# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Scoped panel reads and durable, human-only IDE message review."""
import base64
import hashlib
import json
import re
import time

from spikes.metadata import require, safe_path, uuid, validate_snapshot, validate_transition
from spikes.projects import Projects
from spikes.markdown_documents import document
from spikes.roadmap_validation import _actor
from spikes.task_graph import project_task_graph, TASK, CHECKLIST
from spikes.administration import Administration

MAX_TEXT = 1024 * 1024


def bounded_history(value, *, sessions=False):
    """Keep complete newest messages within the ordinary-file reader limit."""
    from spikes.ide_bridge import canonical
    groups = value['sessions'] if sessions else [value]
    lists = [(group, group['messages']) for group in groups]
    for group, _ in lists:
        group['messages'] = []
    value['history_truncated'] = any(len(rows) >= 100 for _, rows in lists)
    size = len(canonical(value).encode()) + 1024
    require(size <= 2 * MAX_TEXT, 'Document catalog exceeds panel limit')
    for group, rows in lists:
        for row in rows:
            length = len(canonical(row).encode()) + 1
            if size + length > 2 * MAX_TEXT:
                value['history_truncated'] = True
                return value
            group['messages'].append(row); size += length
    return value


def reviewer(service, actor, project_id):
    if not service.network and actor is None:
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
    if service.network and not (Administration.is_admin(actor) and (actor or {}).get('id') is None):
        with Administration(service.node).read_locked() as state:
            actor = next((u for u in state['users'] if u['active']
                and u['id'] == (actor or {}).get('id')
                and u['credential_ref'] == (actor or {}).get('credential_ref')), None)
    service.require_editor(actor, project_id)
    return actor


def validate_checklist(message, tasks):
    values = message.get('checklist', [])
    require(isinstance(values, list) and len(values) <= 200, 'Invalid checklist proposal')
    task = next((t for t in tasks if t['id'] == message['task_id']), None)
    require(not values or task is not None and message['kind'] in {'completed', 'progress'},
            'Checklist requires a task progress proposal')
    seen = set()
    for item in values:
        require(isinstance(item, dict) and set(item) == {'index', 'checked'}
                and type(item['index']) is int and 0 <= item['index'] < len(task['checklist'])
                and type(item['checked']) is bool and item['index'] not in seen,
                'Unknown or duplicate checklist item')
        seen.add(item['index'])
    require(message['kind'] != 'progress' or bool(values), 'Progress needs checklist selections')


def authorize(service, record):
    actor = service.connection_actor(record)
    service.require_editor(actor, record['project_id'])
    with service.database() as db:
        row = db.execute('SELECT revoked FROM sessions WHERE id=?', (record['session_id'],)).fetchone()
        require(row and not row['revoked'] and record['expires_at'] > time.time(), 'Mapping revoked or expired')
        if record.get('connection_id'):
            row = db.execute('SELECT revoked FROM connections WHERE id=?', (record['connection_id'],)).fetchone()
            require(row and not row['revoked'], 'Workspace connection revoked')
def live(service, record):
    authorize(service, record)
    view = service.projects.open(record['project_id'])
    require(not view['read_only'], 'Project is read-only')
    return view


def pinned(service, record):
    current = live(service, record)
    git = service.projects.repository(record['project_id'])
    files = git.snapshot(record['snapshot']['commit_id'])
    entities = validate_snapshot(files)
    require(all(m['privacy'] != 'local-only' for m in entities.values()), 'Pinned project contains local-only data')
    require(git.head() == current['commit_id'], 'Project changed during panel read')
    return files, entities, current


def content(files, meta):
    prefix = 'artifacts/' + meta['id'] + '/'
    if 'file' in meta:
        path = prefix + meta['file']
    else:
        choices = [p for p in files if p.startswith(prefix)]
        require(len(choices) == 1, 'Unsupported document layout')
        path = choices[0]
    require(path in files and len(files[path]) <= MAX_TEXT, 'Document exceeds text limit')
    raw = files[path]
    raw.decode('utf-8')
    require(b'\0' not in raw, 'Binary document is not a text preview')
    return path, raw


def rule_scope(raw, path, tasks):
    if not path.endswith('.json'):
        return {'kind': 'project'}
    value = json.loads(raw)
    require(isinstance(value, dict) and set(value) == {'schema', 'scope', 'body'}
            and value['schema'] == 'fpw-agent-rules-v1' and isinstance(value['body'], str) and bool(value['body'].strip())
            and '\0' not in value['body'], 'Invalid agent rules document')
    scope = value['scope']
    require(isinstance(scope, dict), 'Invalid agent rule scope')
    if scope.get('kind') == 'project':
        require(set(scope) == {'kind'}, 'Invalid project rule scope')
    elif scope.get('kind') == 'directory':
        require(set(scope) == {'kind', 'path'}, 'Invalid directory rule scope')
        safe_path(scope['path'])
    elif scope.get('kind') == 'task':
        require(set(scope) == {'kind', 'task_id'} and isinstance(scope['task_id'], str) and scope['task_id'] in {
            t['id'] for t in tasks}, 'Unknown rule task')
    else:
        raise ValueError('Unknown agent rule scope')
    return scope


def descriptors(files, entities, tasks):
    result = []
    for identifier, meta in entities.items():
        if meta['kind'] not in {'document', 'source', 'snapshot'} or meta['privacy'] == 'local-only':
            continue
        row = dict(artifact_id=identifier, title=meta['title'], privacy=meta['privacy'],
                   agent_rules='agent-rules' in meta.get('tags', []))
        try:
            path, raw = content(files, meta)
            row.update(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), available=True)
            if row['agent_rules']:
                row['scope'] = rule_scope(raw, path, tasks)
        except (ValueError, UnicodeError):
            row.update(available=False, reason='Neplatná pravidla, binární obsah nebo příliš velký text.')
        result.append(row)
    return sorted(result, key=lambda row: (row['title'], row['artifact_id']))


def panel(service, record):
    files, entities, current = pinned(service, record)
    messages = []
    with service.database() as db:
        for row in db.execute('SELECT m.*,s.record AS session_record FROM messages m '
                              'JOIN sessions s ON s.id=m.session ORDER BY m.rowid DESC LIMIT 2000'):
            owner = json.loads(row['session_record'])
            if owner['project_id'] != record['project_id'] or owner.get('connection_id') != record.get('connection_id'):
                continue
            if not record.get('connection_id') and row['session'] != record['session_id']:
                continue
            review = db.execute('SELECT record FROM reviews WHERE session=? AND id=?',
                                (row['session'], row['id'])).fetchone()
            messages.append(dict(session_id=row['session'], message=json.loads(row['record']),
                                 receipt=json.loads(row['receipt']), review=json.loads(review['record']) if review else None))
            if len(messages) == 100:
                break
    current = live(service, record)
    return bounded_history(dict(session_id=record['session_id'], project_id=record['project_id'],
                revision=record['snapshot']['revision'], current_head=current['commit_id'],
                stale=current['commit_id'] != record['snapshot']['commit_id'],
                export_documents=record.get('export_documents', False),
                documents=descriptors(files, entities, record['snapshot']['tasks']) if record.get('export_documents') else [],
                messages=messages))


def read_document(service, record, artifact_id):
    uuid(artifact_id)
    require(record.get('export_documents'), 'Document export is not enabled for this mapping')
    files, entities, current = pinned(service, record)
    require(artifact_id in entities, 'Document belongs to another project or revision')
    require(artifact_id in {item['id'] for item in current['artifacts']}, 'Document no longer available in current project')
    item = next((row for row in descriptors(files, {artifact_id: entities[artifact_id]},
                                           record['snapshot']['tasks']) if row['available']), None)
    require(item is not None, 'Document is not available for text export')
    _, raw = content(files, entities[artifact_id])
    current = live(service, record)
    return dict(item, session_id=record['session_id'], project_id=record['project_id'],
                revision=record['snapshot']['revision'], stale=current['commit_id'] != record['snapshot']['commit_id'],
                content_base64=base64.b64encode(raw).decode('ascii'))


def _changes(files, project_id, head, message):
    entities = validate_snapshot(files)
    graph = project_task_graph(files, entities, project_id, head)
    require(graph['status'] == 'ready', 'Invalid project task graph')
    task = next((t for t in graph['nodes'] if t['id'] == message['task_id']), None)
    require(task is not None, 'Review task disappeared')
    require(task['type'] in {None, 'task'}, 'Only leaf task proposals can change completion')
    validate_checklist(message, graph['nodes'])
    candidate = dict(files)
    doc = document(files, entities, task['source']['artifact_id'])
    path = doc['path']; lines = doc['body'].splitlines(keepends=True)
    if message.get('checklist'):
        start = task['line']; rows = []
        fence = None
        for i in range(start, len(lines)):
            marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', lines[i])
            if marker:
                token, tail = marker.groups()
                if fence is None:
                    fence = (token[0], len(token))
                elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                    fence = None
                continue
            if fence:
                continue
            if TASK.match(lines[i]):
                break
            if CHECKLIST.match(lines[i]):
                rows.append(i)
        require(len(rows) == len(task['checklist']), 'Checklist source mapping differs')
        for change in message['checklist']:
            i = rows[change['index']]
            lines[i] = re.sub(r'^(\s*[-+*]\s+\[)[ xX](\])',
                             lambda m: m[1] + ('x' if change['checked'] else ' ') + m[2], lines[i], count=1)
    prefix = files[path][:-len(doc['body'].encode())] if doc['body'] else files[path]
    candidate[path] = prefix + ''.join(lines).encode()
    if message['kind'] in {'completed', 'progress'}:
        updated = project_task_graph(candidate, validate_snapshot(candidate), project_id, head)
        task = next(t for t in updated['nodes'] if t['id'] == message['task_id'])
        if message['kind'] == 'completed':
            require(all(item['checked'] for item in task['checklist']), 'Complete or review remaining checklist first')
        index = task['line'] - 1
        require(TASK.match(lines[index]).group(3) == task['id'], 'Task source mapping differs')
        checked = message['kind'] == 'completed' or task['checked'] and all(item['checked'] for item in task['checklist'])
        lines[index] = re.sub(r'^(\s*[-+*]\s+\[)[ xX](\])', lambda m: m[1]+('x' if checked else ' ')+m[2], lines[index], count=1)
        candidate[path] = prefix + ''.join(lines).encode()
    validate_transition(files, candidate)
    require(project_task_graph(candidate, validate_snapshot(candidate), project_id, head)['status'] == 'ready',
            'Review produces invalid task graph')
    return {path: raw for path, raw in candidate.items() if raw != files.get(path)}


def review(service, actor, request, *, checkpoint=lambda stage: None):
    from spikes.ide_bridge import canonical, MAX_MESSAGE
    require(isinstance(request, dict) and set(request) == {'project_id', 'session_id',
        'message_id', 'decision', 'note', 'expected_head', 'operation_id'}, 'Invalid review request')
    for key in ('project_id', 'session_id', 'message_id', 'operation_id'):
        uuid(request[key])
    require(request['decision'] in {'accepted', 'rejected'} and isinstance(request['note'], str)
            and len(request['note'].encode()) <= MAX_MESSAGE and '\0' not in request['note'], 'Invalid review decision')
    require(isinstance(request['expected_head'], str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',
            request['expected_head']), 'Expected exact review HEAD')
    actor = reviewer(service, actor, request['project_id'])
    local = Projects(service.node)
    workspace = local.workspace(request['project_id'])
    with service.database() as db:
        row = db.execute('SELECT s.record,m.record AS message FROM sessions s JOIN messages m '
                         'ON m.session=s.id WHERE s.id=? AND m.id=?',
                         (request['session_id'], request['message_id'])).fetchone()
        require(row is not None, 'Unknown review message')
        record, message = json.loads(row['record']), json.loads(row['message'])
        require(record['project_id'] == request['project_id'], 'Review project mismatch')
        prior = db.execute('SELECT record FROM reviews WHERE session=? AND id=?',
                           (request['session_id'], request['message_id'])).fetchone()
    if prior:
        intent = json.loads(prior['record'])
        require(intent['request'] == request, 'Review already has another decision')
        if intent['state'] == 'completed':
            return intent
    else:
        view = service.projects.open(request['project_id'])
        require(not view['read_only'] and view['commit_id'] == request['expected_head'], 'Review HEAD changed or read-only')
        mutate = request['decision'] == 'accepted' and message['kind'] in {'completed', 'progress'}
        if mutate:
            authorize(service, record)
            require(record['snapshot']['commit_id'] == view['commit_id']
                    and message['revision'] == record['snapshot']['revision'],
                    'Stale proposal must be reviewed again')
            require(_changes(workspace.git.snapshot(view['commit_id']), request['project_id'],
                             view['commit_id'], message), 'Proposal produces no project change')
        intent = dict(request=request, state='prepared', mutate=mutate,
                      reviewed_by=(actor or {}).get('id'), reviewed_at=int(time.time()), result=None)
        with service.database() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT record FROM reviews WHERE session=? AND id=?',
                               (request['session_id'], request['message_id'])).fetchone()
            if prior:
                intent = json.loads(prior['record'])
                require(intent['request'] == request, 'Review already has another decision')
            else:
                db.execute('INSERT INTO reviews VALUES (?,?,?)',
                           (request['session_id'], request['message_id'], canonical(intent)))
        checkpoint('intent-prepared')
    require(intent['reviewed_by'] == (actor or {}).get('id') or Administration.is_admin(actor),
            'Resume review as its original reviewer or administrator')
    if intent['reviewed_by'] != (actor or {}).get('id'):
        intent['recovered_by'] = (actor or {}).get('id')
    effectless_stale = False
    if intent['mutate']:
        # A prepared bridge intent may outlive its original HEAD without ever
        # reaching the project journal. Such an intent is terminally stale;
        # an existing native operation must instead recover its exact receipt.
        with workspace.journal.lock(), workspace.journal.connect() as db:
            native = db.execute('SELECT 1 FROM operations WHERE id=?', (request['operation_id'],)).fetchone()
            effectless_stale = not native and workspace.git.head() != request['expected_head']
        if effectless_stale:
            intent['result'] = {'status': 'stale', 'reason': 'Project changed before native preparation'}
    if intent['mutate'] and not effectless_stale:
        author = _actor(service.node)
        def prepare(active):
            authorize(service, record)
            require(active.git.head() == request['expected_head'], 'Review HEAD changed')
            changes = _changes(active.git.snapshot(request['expected_head']), request['project_id'],
                               request['expected_head'], message)
            require(changes, 'Proposal produces no project change')
            return changes, 'Local workspace author', author+'@local.invalid', 'Accept reviewed IDE task proposal'
        # Project writer rechecks permissions when a new native mutation starts.
        original_guard = workspace.write_guard
        def guard():
            if original_guard:
                original_guard()
            reviewer(service, actor, request['project_id'])
        workspace.write_guard = guard
        result = workspace.transact(request['operation_id'], dict(review=request, message=message), prepare,
                                    expected_head=request['expected_head'], checkpoint=checkpoint)
        intent['result'] = dict(commit_id=result['commit_id'], operation_id=result['operation_id'])
    checkpoint('before-outcome')
    intent['state'] = 'completed'
    intent['outcome'] = 'stale' if effectless_stale else request['decision']
    with service.database() as db:
        db.execute('UPDATE reviews SET record=? WHERE session=? AND id=?',
                   (canonical(intent), request['session_id'], request['message_id']))
    checkpoint('outcome-published')
    return intent
