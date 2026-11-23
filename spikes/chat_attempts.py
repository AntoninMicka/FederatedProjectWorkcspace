# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Owner-local submitted prompts, before validation/provider effects (not a task plan)."""
import hashlib
import json
import sqlite3
import subprocess
import time
import traceback

from spikes.metadata import require, uuid, validate_snapshot
from spikes.sqlite_ownership import store_connection
from spikes.task_activities import TaskActivities, privacy_of
from spikes.task_outcomes import TaskOutcomes
from spikes.task_work import canonical
from spikes.task_file_edit import FileEditPrivacyConflict


ROUTES = {'/v1/tasks/route', '/v1/chat/send', '/v1/external/send'}
REASONS = {
    FileEditPrivacyConflict.reason: (FileEditPrivacyConflict.code, FileEditPrivacyConflict.public_message),
    'Project changed before routed task': ('project-changed', 'Projekt se změnil; obnovte jej a zkontrolujte výběr vstupů.'),
    'External task execution cannot include project artifacts': ('external-project-input', 'Zvolený režim externí úlohy nepodporuje přímo vybrané projektové podklady.'),
    'Search on demand requires a conversation task': ('search-output-conflict', 'Akce Promyslet s případným hledáním vyžaduje výsledek Konverzace. Pro soubor zvolte jinou akci.'),
    'Composing a search query requires a conversation task': ('search-output-conflict', 'Webové hledání nejprve připravuje konverzační výsledek; dokument uložte z hotového výsledku.'),
    'Chat mode cannot change inside an existing thread': ('thread-mode-changed', 'Režim uvnitř existujícího vlákna nelze změnit; založte nové vlákno.'),
    'Invalid AI task outcome': ('invalid-model-result', 'Model nevrátil výsledek v požadovaném formátu.'),
    'Model returned invalid explicit task JSON': ('invalid-model-result', 'Model nevrátil platný strukturovaný výsledek úlohy.'),
    'Model returned a different output kind than the explicit task plan': ('invalid-model-result', 'Model nevrátil požadovaný druh výsledku úlohy.'),
    'Unsupported AI task outcome kind': ('invalid-model-result', 'Model vrátil nepodporovaný druh výsledku.'),
}


class ChatAttempts:
    def __init__(self, work):
        self.work = work
        self.store = TaskOutcomes(work.chat_state_dir)

    def begin(self, route, request):
        route = route.removesuffix('-stream')
        if route not in ROUTES or not isinstance(request, dict):
            return None
        identifier = request.get('task_id') or request.get('turn_id') or request.get('run_id')
        pid = request.get('project_id'); content = request.get('content'); privacy = request.get('privacy')
        try:
            uuid(identifier); uuid(pid)
        except ValueError:
            return None
        if (not isinstance(content, str) or not content.strip() or '\0' in content
                or len(content.encode()) > 1024 * 1024
                or not isinstance(privacy, str) or privacy not in {'public', 'project', 'confidential', 'local-only'}):
            return None
        if not self.readable(pid, privacy):
            return None
        git = self.work.projects.repository(pid)  # No project writer/recovery.
        metadata = validate_snapshot(git.snapshot(git.head()))
        privacy = privacy_of([{'privacy': privacy}] + list(metadata.values()))
        fingerprint = hashlib.sha256(canonical(request).encode()).hexdigest()
        doc = dict(id=identifier, project_id=pid, route=route, content=content, privacy=privacy,
                   created_at=time.time(), state='unknown', request_sha256=fingerprint)
        for key in ('thread_id', 'run_id', 'manifest_id'):
            if isinstance(request.get(key), str):
                uuid(request[key]); doc[key] = request[key]
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS chat_attempts('
                       'id TEXT NOT NULL,user_id TEXT NOT NULL,project_id TEXT NOT NULL,doc TEXT NOT NULL,'
                       'PRIMARY KEY(id,user_id))')
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT doc FROM chat_attempts WHERE id=? AND user_id=?',
                             (identifier, self.work.user_id)).fetchone()
            if old:
                prior = json.loads(old[0])
                require(prior['request_sha256'] == fingerprint and prior['route'] == route,
                        'Submitted prompt identity belongs to another request')
            else:
                db.execute('INSERT INTO chat_attempts VALUES(?,?,?,?)',
                           (identifier, self.work.user_id, pid, canonical(doc)))
            db.commit()
        return identifier

    def readable(self, pid, privacy):
        if self.work.network and privacy == 'local-only': return False
        try:
            self.work.projects.repository(pid)
            return TaskActivities(self.work)._readable(pid)
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            return False

    def _read(self, db, identifier):
        row = db.execute('SELECT doc FROM chat_attempts WHERE id=? AND user_id=?',
                         (identifier, self.work.user_id)).fetchone()
        return json.loads(row[0]) if row else None

    def error(self, identifier, exc):
        # No exception text, prompt, filesystem path or credential in diagnostics.
        code, message = REASONS.get(str(exc), ('request-rejected', 'Požadavek byl odmítnut; jeho text je uložený v neúspěšných zadáních.'))
        frames = [frame for frame in traceback.extract_tb(exc.__traceback__)
                  if '/spikes/' in frame.filename and frame.name != 'require']
        diagnostic = dict(code=code, message=message, exception_type=type(exc).__name__,
                          reason_sha256=hashlib.sha256(str(exc).encode()).hexdigest())
        if isinstance(exc, FileEditPrivacyConflict):
            diagnostic['privacy_conflict'] = exc.details
        if frames:
            diagnostic.update(module=frames[-1].filename.rsplit('/', 1)[-1], line=frames[-1].lineno)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            doc = self._read(db, identifier)
            if doc is not None and doc['state'] not in {'completed', 'discarded'}:
                doc['diagnostic'] = diagnostic
                db.execute('UPDATE chat_attempts SET doc=? WHERE id=? AND user_id=?',
                           (canonical(doc), identifier, self.work.user_id)); db.commit()

    def finish(self, identifier, code, payload):
        payload = payload if isinstance(payload, dict) else {}
        states = {item.get('state') for item in (payload, payload.get('turn'), payload.get('projection')) if isinstance(item, dict)}
        state = ('unknown' if code in {408, 409} or payload.get('outcome') == 'unknown' or 'unknown' in states
                 else 'failed' if code >= 400 or payload.get('outcome') == 'failed' or 'failed' in states
                 else 'completed')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            doc = self._read(db, identifier)
            if doc is None or doc['state'] in {'completed', 'discarded'}: return
            doc.update(state=state, response_code=code)
            # A small receipt prevents a later failed replay from reviving a successful prompt.
            if state == 'completed':
                doc.pop('content', None); doc.pop('diagnostic', None)
            db.execute('UPDATE chat_attempts SET doc=? WHERE id=? AND user_id=?',
                       (canonical(doc), identifier, self.work.user_id)); db.commit()

    def list(self, pid, identifier=None):
        uuid(pid)
        if identifier is not None: uuid(identifier)
        if not self.readable(pid, 'project'): return []
        db = store_connection(self.store.path, 'Unsafe task outcome store', readonly=True)
        if db is None: return []
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_attempts'").fetchone(): return []
            query = 'SELECT doc FROM chat_attempts WHERE user_id=? AND project_id=?'
            params = [self.work.user_id, pid]
            if identifier is not None:
                query += ' AND id=?'; params.append(identifier)
            rows = db.execute(query + ' ORDER BY rowid DESC', params)
            result = []
            for row in rows:
                doc = json.loads(row[0])
                diagnostic = doc.get('diagnostic', {})
                if (diagnostic.get('code') == 'request-rejected'
                        and diagnostic.get('reason_sha256') == hashlib.sha256(FileEditPrivacyConflict.reason.encode()).hexdigest()):
                    doc['diagnostic'] = dict(diagnostic, code=FileEditPrivacyConflict.code,
                                             message=FileEditPrivacyConflict.public_message)
                if doc['state'] not in {'completed', 'discarded'} and (not self.work.network or doc['privacy'] != 'local-only'):
                    doc['content_bytes'] = len(doc['content'].encode())
                    if identifier is None:
                        doc['preview'] = doc.pop('content')[:160]
                    result.append(doc)
                if len(result) == 50: break
            return result
        finally:
            db.close()

    def discard(self, pid, identifier):
        uuid(pid); uuid(identifier)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            doc = self._read(db, identifier)
            require(doc is not None and doc['project_id'] == pid and self.readable(pid, doc['privacy']),
                    'Saved prompt is unavailable')
            doc.pop('content', None); doc.pop('diagnostic', None)
            doc['state'] = 'discarded'
            db.execute('UPDATE chat_attempts SET doc=? WHERE id=? AND user_id=?',
                       (canonical(doc), identifier, self.work.user_id)); db.commit()
        return dict(attempt_id=identifier, state='discarded')
