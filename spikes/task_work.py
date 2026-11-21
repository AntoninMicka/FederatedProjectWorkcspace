# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local working sessions; project Git remains the task-state authority (ADR 0088)."""
from contextlib import contextmanager
import hashlib
import fcntl
import os
import stat
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import time
from uuid import UUID, uuid4, uuid5

from spikes.administration import AccessDenied
from spikes.configuration import parse_node, read_config
from spikes.journal import sync_dir
from spikes.local_api import private_directory
from spikes.markdown_documents import document
from spikes.metadata import require, uuid, validate_snapshot
from spikes.plan_item_editor import item_span
from spikes.plan_progress import progress_changes
from spikes.request_ownership import bounded_flock
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.sqlite_ownership import store_connection
from spikes.task_graph import project_task_graph, dependency_start_blockers, TASK_ID
from spikes.workspace import PendingOperation


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class TaskWork:
    def __init__(self, node, user_id=None, *, network=False, can_read=None,
                 can_write=None):
        self.node = Path(node).absolute()
        self.node_id = parse_node(read_config(self.node), location=self.node)['id']
        self.user_id = user_id or ProjectCreation(self.node).author_id(); uuid(self.user_id)
        self.projects = Projects(self.node, network=network)
        self.network = network
        # A network adapter must supply its authenticated project policy.
        self.can_read = can_read if can_read is not None else (lambda pid: not network)
        self.can_write = can_write if can_write is not None else (lambda pid: not network)
        self.root = self.node.parent / ('.' + self.node.name + '.task-work')
        self.path = self.root / 'contexts.sqlite'

    @contextmanager
    def _db(self, *, write=False):
        if not self.root.exists() and not write:
            yield None
            return
        if write:
            try:
                self.root.mkdir(mode=0o700)
            except FileExistsError:
                pass
            else:
                sync_dir(self.root.parent)
        private_directory(self.root)
        outside = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--show-toplevel'],
                                 capture_output=True, timeout=5)
        require(outside.returncode == 128, 'Task work storage must be outside Git')
        db = store_connection(self.path, 'Unsafe task work store', readonly=not write)
        if db is None:
            yield None
            return
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version == 0 and write:
                require(not db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone(),
                        'Unknown task work schema; migration required')
                db.execute('CREATE TABLE identity(node_id TEXT NOT NULL)')
                db.execute('INSERT INTO identity VALUES(?)', (self.node_id,))
                db.execute('CREATE TABLE windows(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,secret TEXT NOT NULL,doc TEXT NOT NULL)')
                db.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,window_id TEXT NOT NULL,doc TEXT NOT NULL)')
                db.execute('CREATE TABLE operations(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,window_id TEXT NOT NULL,request TEXT NOT NULL,doc TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
                version = 1
            require(version == 1, 'Unsupported task work schema; explicit migration required')
            require(self._node_matches(db), 'Task work node identity changed')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def _node_matches(self, db):
        rows = db.execute('SELECT node_id FROM identity').fetchall()
        return len(rows) == 1 and rows[0][0] == self.node_id

    @contextmanager
    def _operation_lock(self, operation_id):
        uuid(operation_id)
        private_directory(self.root)
        fd = os.open(self.root / (operation_id + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, 'Unsafe operation lock')
            bounded_flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, resource='Task work operation')
            yield
        finally:
            os.close(fd)

    def create_window(self):
        identifier, token = str(uuid4()), secrets.token_urlsafe(32)
        state = dict(revision=0, active=None, pending=None)
        with self._db(write=True) as db:
            db.execute('INSERT INTO windows VALUES(?,?,?,?)',
                       (identifier, self.user_id, digest(token), canonical(state)))
        return dict(window_id=identifier, window_token=token, node_id=self.node_id, user_id=self.user_id)

    def _window(self, db, handle):
        uuid(handle.get('window_id'))
        token = handle.get('window_token')
        require(isinstance(token, str) and 20 <= len(token) <= 256, 'Pracovní okno není ověřené.')
        row = db.execute('SELECT * FROM windows WHERE id=?', (handle['window_id'],)).fetchone() if db else None
        require(row is not None and row['user_id'] == self.user_id
                and hmac.compare_digest(row['secret'], digest(token)), 'Pracovní okno není dostupné tomuto uživateli.')
        return json.loads(row['doc'])

    def _session(self, db, identifier, window_id):
        uuid(identifier)
        row = db.execute('SELECT * FROM sessions WHERE id=?', (identifier,)).fetchone()
        require(row is not None and row['user_id'] == self.user_id and row['window_id'] == window_id,
                'Pracovní relace není dostupná v tomto okně.')
        return json.loads(row['doc'])

    def _operation(self, db, identifier, window_id):
        row = db.execute('SELECT * FROM operations WHERE id=?', (identifier,)).fetchone() if db else None
        require(row is None or (row['user_id'] == self.user_id and row['window_id'] == window_id),
                'Operation ID belongs to another owner/window')
        return row

    @staticmethod
    def _save_window(db, handle, state):
        db.execute('UPDATE windows SET doc=? WHERE id=?', (canonical(state), handle['window_id']))

    @staticmethod
    def _save_session(db, session):
        db.execute('INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc',
                   (session['work_session_id'], session['user_id'], session['window_id'], canonical(session)))

    @staticmethod
    def _save_operation(db, identifier, doc):
        db.execute('UPDATE operations SET doc=? WHERE id=?', (canonical(doc), identifier))

    def _authorize(self, pid):
        uuid(pid)
        if not self.can_read(pid) or not self.can_write(pid):
            raise AccessDenied('Právo pracovat na úkolu bylo odebráno.')

    def _model(self, pid, task_id):
        self._authorize(pid)
        view = self.projects.plan_view(pid)
        require(not view.get('read_only'), 'Projekt je pouze pro čtení.')
        git = self.projects.repository(pid)
        require(git.head() == view['commit_id'], 'Projekt se změnil; obnovte kontext.')
        model = self._pin(git.snapshot(view['commit_id']), pid, task_id, view['commit_id'])
        require(git.head() == view['commit_id'], 'Projekt se změnil; obnovte kontext.')
        return model

    def _pin(self, files, pid, task_id, head):
        entities = validate_snapshot(files)
        if self.network:
            require(all(e['privacy'] != 'local-only' for e in entities.values()), 'Project contains local-only data')
        graph = project_task_graph(files, entities, pid, head)
        require(graph['status'] == 'ready', 'Roadmapa nemá platný graf.')
        nodes = {n['id']: n for n in graph['nodes']}; task = nodes.get(task_id)
        require(task is not None, 'Úkol již není v roadmapě.')
        require(task['type'] in {None, 'task'} and not any(n['parent_id'] == task_id for n in graph['nodes']),
                'Zahajte konkrétní úkol, nikoli skupinu.')
        doc = document(files, entities, task['source']['artifact_id'])
        start, end = item_span(doc['body'], task_id)
        pin = dict(project_commit=head, plan_revision=graph['revision'], source=task['source'],
                   fragment_sha256=hashlib.sha256(doc['body'][start:end].encode()).hexdigest())
        signature = digest(dict(id=task_id, type=task['type'], parent_id=task['parent_id'], title=task['title'],
            description=task['description'], source=task['source'], depends_on=task['depends_on'],
            checklist=[p['text'] for p in task['checklist']]))
        return dict(pin=pin, signature=signature, task=task,
                    blockers=dependency_start_blockers(task['depends_on'], nodes), title=task['title'])

    @staticmethod
    def _startable(model):
        require(not model['task']['checked'], 'Dokončený úkol nelze zahájit.')
        require(not model['blockers'], 'Zahájení blokují předpoklady: ' + ', '.join(model['blockers']))

    def _projection(self, session):
        safe = {k: session[k] for k in ('work_session_id', 'project_id', 'task_id', 'state', 'revision')}
        try:
            model = self._model(session['project_id'], session['task_id'])
            if model['task']['checked']:
                reason = 'Úkol už byl dokončen.'
            elif model['signature'] != session['definition_signature']:
                reason = 'Zadání se změnilo; je nutná reconciliace a nový pracovní úsek.'
            elif model['blockers']:
                reason = 'Zahájení blokují předpoklady: ' + ', '.join(model['blockers'])
            else:
                reason = ''
            return dict(session, title=model['title'], current_task=model['task'],
                        validated_head=model['pin']['project_commit'], blocked=reason)
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, PendingOperation) as exc:
            # Never expose a cached title/body after access or privacy changes.
            return dict(safe, blocked=str(exc), title=None)

    def status(self, handle):
        with self._db() as db:
            state = self._window(db, handle)
            rows = db.execute('SELECT doc FROM sessions WHERE window_id=? AND user_id=? ORDER BY rowid DESC LIMIT 50',
                              (handle['window_id'], self.user_id)).fetchall()
            sessions = [json.loads(r[0]) for r in rows]
            if state['active'] and not any(s['work_session_id'] == state['active'] for s in sessions):
                sessions.insert(0, self._session(db, state['active'], handle['window_id']))
            pending = self._operation(db, state['pending'], handle['window_id']) if state['pending'] else None
        items = [self._projection(s) for s in sessions]
        return dict(context_revision=state['revision'], active_session_id=state['active'],
                    sessions=items, pending=None if not pending else dict(operation_id=pending['id'], **json.loads(pending['doc'])))

    def inspect(self, handle, pid, task_id, expected_head):
        with self._db() as db:
            self._window(db, handle)
        model = self._model(pid, task_id); self._startable(model)
        require(model['pin']['project_commit'] == expected_head, 'Roadmapa se změnila; nejprve ji obnovte.')
        return dict(expected_head=expected_head, fragment_sha256=model['pin']['fragment_sha256'])

    def capture(self, handle, *, context_revision):
        with self._db() as db:
            window = self._window(db, handle)
            require(type(context_revision) is int and window['revision'] == context_revision, 'Pracovní kontext se změnil; nejprve jej zobrazte.')
            require(window['pending'] is None, 'Nejprve obnovte rozpracované zahájení.')
            require(window['active'] is not None, 'Žádný aktivní pracovní kontext.')
            session = self._session(db, window['active'], handle['window_id'])
        projection = self._projection(session)
        require(not projection['blocked'], projection['blocked'])
        return {k: session[k] for k in ('work_session_id', 'definition_pin', 'project_id', 'task_id', 'node_id', 'user_id')}

    def execute(self, request, *, checkpoint=lambda stage: None):
        require(isinstance(request, dict), 'Invalid task work request')
        action = request.get('action')
        if action == 'window':
            require(set(request) == {'action'}, 'Invalid window request')
            return self.create_window()
        common = {'action', 'window_id', 'window_token'}
        extra = dict(status=set(), capture={'context_revision'}, inspect={'project_id','task_id','expected_head'},
                     recover={'operation_id'}, cancel={'operation_id'},
                     start={'operation_id','context_revision','project_id','task_id','expected_head','fragment_sha256','selected_checklist'},
                     switch={'operation_id','context_revision','project_id','task_id','expected_head','fragment_sha256','selected_checklist','work_session_id','session_revision'},
                     resume={'operation_id','context_revision','work_session_id','session_revision'},
                     pause={'operation_id','context_revision','work_session_id','session_revision'},
                     close={'operation_id','context_revision','work_session_id','session_revision'},
                     restore={'operation_id','context_revision'},
                     **{'propose-completion': {'operation_id','context_revision','work_session_id','session_revision','comment'}})
        require(isinstance(action, str) and action in extra and set(request) == common | extra[action], 'Invalid task work action/fields')
        if action == 'status':
            return self.status(request)
        if action == 'capture':
            return self.capture(request, context_revision=request['context_revision'])
        if action == 'inspect':
            return self.inspect(request, request['project_id'], request['task_id'], request['expected_head'])
        uuid(request['operation_id'])
        if action == 'restore':
            return self._restore(request)
        if action in {'recover','cancel'}:
            with self._db() as db:
                self._window(db, request)
                row = self._operation(db, request['operation_id'], request['window_id'])
                require(row is not None, 'Pracovní operace neexistuje.')
                original, op = json.loads(row['request']), json.loads(row['doc'])
            if action == 'cancel':
                require(op['state'] in {'prepared','blocked'}, 'Tuto operaci nelze zrušit.')
                with self._operation_lock(request['operation_id']):
                    with self._db() as db:
                        self._window(db, request)
                        row = self._operation(db, request['operation_id'], request['window_id'])
                        op = json.loads(row['doc'])
                        require(op['state'] in {'prepared','blocked'}, 'Operace už byla dokončena.')
                    ws = self.projects.workspace(op['target']['project_id'], blocking=False)
                    with ws.journal.lock(shared=True), ws.journal.connect() as db:
                        require(not db.execute('SELECT 1 FROM operations WHERE id=?', (op['project_operation_id'],)).fetchone()
                                and not op.get('project_result'), 'Projektový zápis již začal; dokončete jeho obnovu.')
                    self._reject(request, 'Zrušeno uživatelem.')
            elif op['state'] in {'prepared','blocked'}:
                self._run(original, op, request, checkpoint)
            return self._response(request)
        require(type(request['context_revision']) is int and request['context_revision'] >= 0, 'Invalid context revision')
        if 'work_session_id' in request:
            uuid(request['work_session_id'])
            require(type(request['session_revision']) is int and request['session_revision'] >= 1, 'Invalid session revision')
        body = {k: v for k, v in request.items() if k != 'window_token'}
        with self._db() as db:
            self._window(db, request)
            prior = self._operation(db, request['operation_id'], request['window_id'])
            if prior:
                require(prior['request'] == canonical(body), 'Operation ID belongs to a different request')
                op = json.loads(prior['doc'])
        if prior:
            if op['state'] in {'prepared','blocked'}:
                self._run(body, op, request, checkpoint)
            return self._response(request)
        model = None
        if action in {'start','switch'}:
            require(isinstance(request['task_id'], str) and TASK_ID.fullmatch(request['task_id']), 'Invalid task ID')
            model = self._model(request['project_id'], request['task_id']); self._startable(model)
            require(model['pin']['project_commit'] == request['expected_head']
                    and model['pin']['fragment_sha256'] == request['fragment_sha256'], 'Zadání se změnilo; obnovte plán.')
            selected = request['selected_checklist']
            require(selected is None or type(selected) is int and 0 <= selected < len(model['task']['checklist']), 'Invalid checklist selection')
        elif action in {'resume','propose-completion'}:
            with self._db() as db:
                session = self._session(db, request['work_session_id'], request['window_id'])
            model = self._model(session['project_id'], session['task_id']); self._startable(model)
            require(model['signature'] == session['definition_signature'], 'Zadání se změnilo; zahajte nový pracovní úsek.')
        if action == 'propose-completion':
            require(isinstance(request['comment'], str) and len(request['comment']) <= 4000 and '\0' not in request['comment'], 'Invalid proposal comment')
        with self._db(write=True) as db:
            window = self._window(db, request)
            require(window['pending'] is None and window['revision'] == request['context_revision'], 'Pracovní kontext se změnil; obnovte jej.')
            session = None
            if 'work_session_id' in request:
                session = self._session(db, request['work_session_id'], request['window_id'])
                require(session['revision'] == request['session_revision'], 'Pracovní relace se změnila.')
            if action in {'start','resume'}:
                require(window['active'] is None, 'Okno už má aktivní úkol; použijte Přepnout.')
            if action in {'pause','switch'}:
                require(window['active'] == request['work_session_id'] and session['state'] == 'active', 'Relace není aktivní.')
            if action == 'resume':
                require(session['state'] == 'paused', 'Pokračovat lze pouze v pozastavené relaci.')
            if action == 'close':
                require(session['state'] != 'closed', 'Relace už je ukončená.')
            if action in {'start','switch','resume'}:
                target = dict(project_id=session['project_id'] if action == 'resume' else request['project_id'],
                              task_id=session['task_id'] if action == 'resume' else request['task_id'],
                              model=model, selected_checklist=session.get('selected_checklist') if action == 'resume' else request['selected_checklist'])
                op = dict(state='prepared', target=target, old_active=window['active'],
                          work_session_id=session['work_session_id'] if action == 'resume' else str(uuid5(UUID(request['operation_id']), 'task-work-session-v1')),
                          project_operation_id=str(uuid5(UUID(request['operation_id']), 'task-work-progress-v1')))
                # Keep definitions out of the local operational store.
                op['target']['model'] = {k:model[k] for k in ('pin','signature')}
                window['pending'] = request['operation_id']
            else:
                op = dict(state='completed')
                if action in {'pause','close'}:
                    session.update(state='paused' if action == 'pause' else 'closed', revision=session['revision']+1, updated_at=time.time())
                    if action == 'close': session['closed_reason'] = 'user-ended'
                    self._save_session(db, session)
                    if window['active'] == session['work_session_id']: window['active'] = None
                elif action == 'propose-completion':
                    proposal = dict(id=request['operation_id'], state='pending', comment=request['comment'],
                                    definition_pin=model['pin'], completion_ready=model['task']['completion_ready'])
                    require(len(session.get('completion_proposals', [])) < 200, 'Limit návrhů této relace byl dosažen.')
                    session['completion_proposals'] = session.get('completion_proposals', []) + [proposal]
                    session.update(revision=session['revision']+1, updated_at=time.time()); self._save_session(db, session)
            window['revision'] += 1
            self._save_window(db, request, window)
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',
                       (request['operation_id'], self.user_id, request['window_id'], canonical(body), canonical(op)))
            checkpoint('task-work-before-intent-commit')
        checkpoint('task-work-intent-prepared')
        if op['state'] == 'prepared':
            self._run(body, op, request, checkpoint)
        return self._response(request)

    def _restore(self, request):
        """Explicitly reclaim a window; rotate its capability, with lost-reply replay."""
        uuid(request['window_id'])
        require(type(request['context_revision']) is int and request['context_revision'] >= 0,
                'Invalid context revision')
        token = request.get('window_token')
        require(isinstance(token, str) and 20 <= len(token) <= 256, 'Pracovní okno není ověřené.')
        body = {k:v for k,v in request.items() if k != 'window_token'}
        new_token = hmac.new(token.encode(), ('task-work-restore-v1/'+request['operation_id']).encode(), hashlib.sha256).hexdigest()
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM windows WHERE id=?', (request['window_id'],)).fetchone()
            require(row is not None and row['user_id'] == self.user_id, 'Pracovní okno není dostupné.')
            prior = self._operation(db, request['operation_id'], request['window_id'])
            if prior:
                op = json.loads(prior['doc'])
                require(prior['request'] == canonical(body) and op.get('old_secret') == digest(token)
                        and hmac.compare_digest(row['secret'], digest(new_token)), 'Okno už bylo převzato jinou operací.')
            else:
                window = self._window(db, request)
                require(window['revision'] == request['context_revision'], 'Pracovní kontext se změnil; obnovte jej.')
                if window['active']:
                    session = self._session(db, window['active'], request['window_id'])
                    session.update(state='paused', revision=session['revision']+1, updated_at=time.time())
                    self._save_session(db, session)
                window.update(active=None, revision=window['revision']+1)
                db.execute('UPDATE windows SET secret=?,doc=? WHERE id=?',
                           (digest(new_token), canonical(window), request['window_id']))
                op = dict(state='completed', old_secret=digest(token))
                db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',
                    (request['operation_id'],self.user_id,request['window_id'],canonical(body),canonical(op)))
        handle = dict(window_id=request['window_id'], window_token=new_token, operation_id=request['operation_id'])
        return dict(self._response(handle), window=dict(window_id=handle['window_id'],window_token=new_token))

    def _response(self, handle):
        result = self.status(handle)
        with self._db() as db:
            self._window(db, handle)
            row = self._operation(db, handle['operation_id'], handle['window_id'])
            op = json.loads(row['doc'])
        result['operation'] = dict(operation_id=handle['operation_id'], state=op['state'], error=op.get('error'), result=op.get('result'))
        return result

    def _reject(self, handle, reason):
        with self._db(write=True) as db:
            window = self._window(db, handle)
            row = self._operation(db, handle['operation_id'], handle['window_id']); op = json.loads(row['doc'])
            require(window['pending'] == handle['operation_id'], 'Pending operation differs')
            op.update(state='rejected', error=reason)
            window.update(pending=None, revision=window['revision']+1)
            self._save_window(db, handle, window); self._save_operation(db, handle['operation_id'], op)

    def _run(self, body, op, handle, checkpoint):
        with self._operation_lock(body['operation_id']):
            with self._db() as db:
                self._window(db, handle)
                row = self._operation(db, body['operation_id'], handle['window_id'])
                op = json.loads(row['doc'])
                require(row['request'] == canonical(body), 'Operation request differs')
                if op['state'] in {'completed','rejected'}:
                    return
            self._run_owned(body, op, handle, checkpoint)

    def _run_owned(self, body, op, handle, checkpoint):
        target = op['target']; pid, task_id = target['project_id'], target['task_id']
        ws = self.projects.workspace(pid, blocking=False)
        try:
            self._authorize(pid)
            require(not self.projects.replication(pid) or self.projects.replication(pid)['role'] != 'read-only-replica', 'Projekt je pouze pro čtení.')
            if not op.get('project_result'):
                base = target['model']['pin']['project_commit']
                project_request = dict(action='task-work-start', user_id=self.user_id,
                    window_id=handle['window_id'], task_id=task_id, expected_head=base,
                    fragment_sha256=target['model']['pin']['fragment_sha256'])
                def prepare(workspace):
                    head = workspace.git.head(); require(head == base, 'Roadmapa se změnila; obnovte plán.')
                    files = workspace.git.snapshot(head); model = self._pin(files, pid, task_id, head)
                    require(model['pin'] == target['model']['pin'], 'Zadání se změnilo.')
                    changes = progress_changes(files, pid, head, task_id)
                    return changes, 'Local workspace author', self.user_id+'@local.invalid', 'Start task '+task_id
                with ws.journal.lock(shared=True), ws.journal.connect() as db:
                    native = db.execute('SELECT 1 FROM operations WHERE id=?', (op['project_operation_id'],)).fetchone()
                    no_op = False
                    if not native:
                        require(not ws._active(db) and not db.execute('SELECT 1 FROM pending').fetchone(), 'Projekt má nedokončenou operaci.')
                        require(ws.git.head() == base, 'Roadmapa se změnila; obnovte plán.')
                        no_op = not progress_changes(ws.git.snapshot(base), pid, base, task_id)
                if no_op:
                    head = base
                else:
                    receipt = ws.transact(op['project_operation_id'], project_request, prepare,
                                          expected_head=base, checkpoint=checkpoint)
                    head = receipt['commit_id']
                effective = self._pin(ws.git.snapshot(head), pid, task_id, head)
                require(effective['signature'] == target['model']['signature'], 'Progress changed the task definition')
                checkpoint('task-work-after-project')
                op['project_result'] = effective['pin']
                with self._db(write=True) as db:
                    self._window(db, handle); self._save_operation(db, body['operation_id'], op)
                checkpoint('task-work-project-recorded')
            self._authorize(pid)
            with self._db(write=True) as db:
                window = self._window(db, handle)
                row = self._operation(db, body['operation_id'], handle['window_id'])
                if json.loads(row['doc'])['state'] == 'completed':
                    return
                require(window['pending'] == body['operation_id'], 'Pracovní rezervace se změnila.')
                now = time.time()
                if op['old_active']:
                    previous = self._session(db, op['old_active'], handle['window_id'])
                    revised = (previous['project_id'] == pid and previous['task_id'] == task_id
                               and previous['definition_signature'] != target['model']['signature'])
                    previous.update(state='closed' if revised else 'paused', revision=previous['revision']+1, updated_at=now)
                    if revised:
                        previous['closed_reason'] = 'definition-updated'
                    self._save_session(db, previous)
                if body['action'] == 'resume':
                    session = self._session(db, op['work_session_id'], handle['window_id'])
                    session.update(state='active', revision=session['revision']+1, updated_at=now)
                else:
                    prior_session = op['old_active']
                    if prior_session is None:
                        for prior in db.execute('SELECT doc FROM sessions WHERE window_id=? AND user_id=? ORDER BY rowid DESC', (handle['window_id'], self.user_id)):
                            candidate = json.loads(prior[0])
                            if candidate['project_id'] == pid and candidate['task_id'] == task_id:
                                prior_session = candidate['work_session_id']
                                break
                    session = dict(schema_version=1, work_session_id=op['work_session_id'], user_id=self.user_id, node_id=self.node_id,
                        window_id=handle['window_id'], project_id=pid, task_id=task_id, definition_pin=op['project_result'],
                        requested_pin=target['model']['pin'], definition_signature=target['model']['signature'],
                        state='active', revision=1, created_at=now, updated_at=now, closed_reason=None,
                        selected_checklist=target['selected_checklist'], previous_work_session_id=prior_session)
                self._save_session(db, session)
                window.update(active=op['work_session_id'], pending=None, revision=window['revision']+1)
                self._save_window(db, handle, window)
                op.update(state='completed', result=dict(work_session_id=op['work_session_id'], project_commit=op['project_result']['project_commit']))
                self._save_operation(db, body['operation_id'], op)
                checkpoint('task-work-before-finalize')
            checkpoint('task-work-after-finalize')
        except ValueError as exc:
            with ws.journal.lock(shared=True), ws.journal.connect() as db:
                native = db.execute('SELECT 1 FROM operations WHERE id=?', (op['project_operation_id'],)).fetchone()
            if native or op.get('project_result'):
                op.update(state='blocked', error=str(exc))
                with self._db(write=True) as db:
                    self._window(db, handle); self._save_operation(db, body['operation_id'], op)
            else:
                self._reject(dict(handle, operation_id=body['operation_id']), str(exc))
            raise
