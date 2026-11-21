# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native-operation activity receipts, pinned before dispatch (ADR 0088)."""
import json
import sqlite3
import subprocess
import time
from uuid import UUID, uuid5

from spikes.metadata import require, uuid, validate_snapshot
from spikes.task_work import canonical, digest

# Only actual saves/imports/turns/runs, never drafts, previews or keystrokes.
ROUTES = {
    '/v1/artifacts/editor/save': 'artifact-save',
    '/v1/artifacts/delete/confirm': 'artifact-delete',
    '/v1/sources/import': 'source-import',
    '/v1/google-drive/confirm': 'source-import',
    '/v1/julia/editor/save': 'file-save',
    '/v1/julia/editor/delete/confirm': 'file-delete',
    '/v1/presentations/save': 'artifact-save',
    '/v1/tasks/presentation/confirm': 'artifact-publish',
    '/v1/summary/publish': 'artifact-publish',
    '/v1/extraction/publish': 'artifact-publish',
    '/v1/tasks/route': 'llm-task',
    '/v1/tasks/route-stream': 'llm-task',
    '/v1/artifacts/editor/plan-item/save': 'plan-save',
    '/v1/artifacts/editor/plan-item/create': 'plan-create',
    '/v1/artifacts/editor/plan-item/dependencies': 'plan-relations',
    '/v1/artifacts/editor/plan-item/delete': 'plan-delete',
    '/v1/chat/send': 'conversation-turn',
    '/v1/chat/send-stream': 'conversation-turn',
    '/v1/chat/snapshot': 'conversation-snapshot',
    '/v1/chat/output': 'conversation-output',
    '/v1/tasks/artifact': 'artifact-publish',
    '/v1/tasks/file-edit/confirm': 'file-edit',
    '/v1/tasks/search/confirm': 'search-run',
    '/v1/tasks/external/confirm': 'llm-run',
    '/v1/external/send': 'llm-run',
    '/v1/external/send-stream': 'llm-run',
    '/v1/external/confirm': 'llm-run',
    '/v1/media/confirm': 'media-run',
    '/v1/media/publish': 'artifact-publish',
    '/v1/artifacts/git/stage': 'file-stage',
    '/v1/artifacts/git/commit': 'file-commit',
}
NAMESPACE = UUID('b977b3ea-958e-4d4a-a661-a23ede4ea6ce')
# No text, filenames, URLs, prompt, manifest content or credential copies.
REF_FIELDS = {'definition_path', 'script_path', 'sha256', 'staged_sha256', 'expected_head', 'base_head', 'project_commit', 'project_id', 'artifact_id', 'commit_id', 'revision', 'thread_id',
              'turn_id', 'run_id', 'search_id', 'approval_id', 'message_id', 'assistant_message_id', 'manifest_id'}


def references(value):
    """Bounded server receipt identifiers, including nested native result envelopes."""
    found = []
    def visit(item, depth):
        if depth > 6 or len(found) >= 100:
            return
        if isinstance(item, dict):
            ref = {k: v for k, v in item.items() if k in REF_FIELDS
                   and isinstance(v, (str, int)) and not isinstance(v, bool) and len(str(v)) <= 200}
            if ref and ref not in found:
                found.append(ref)
            for key, child in item.items():
                if key not in {'content', 'body', 'messages', 'prompt', 'text', 'manifest',
                               'outcome', 'proposal', 'response', 'runtime_evidence', 'search_results'}:
                    visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item[:100]:
                visit(child, depth + 1)
    visit(value, 0)
    return found


def privacy_of(value):
    levels={'public':0,'project':1,'confidential':2,'local-only':3}
    found=['project']
    def visit(item,depth):
        if depth>6:return
        if isinstance(item,dict):
            if isinstance(item.get('privacy'),str) and item['privacy'] in levels:found.append(item['privacy'])
            for key,child in item.items():
                if key not in {'body','content','prompt','text','response','outcome'}:visit(child,depth+1)
        elif isinstance(item,list):
            for child in item[:100]:visit(child,depth+1)
    visit(value,0)
    return max(found,key=levels.get)


class TaskActivities:
    def __init__(self, work):
        self.work = work

    def begin(self, handle, context_revision, route, request):
        require(type(context_revision) is int, 'Invalid context revision')
        require(route in ROUTES and isinstance(request, dict), 'Unsupported task activity')
        # Group streaming/nonstreaming delivery of the same native turn.
        route = route.removesuffix('-stream')
        native = request.get('operation_id') or request.get('search_id') or request.get('approval_id') or request.get('run_id') or request.get('turn_id') or request.get('task_id')
        uuid(native)
        identifier = str(uuid5(NAMESPACE, canonical([self.work.user_id, route, native])))
        fingerprint = digest(request)
        with self.work._db() as db:
            self.work._window(db, handle)
            existing = self.work._operation(db, identifier, handle['window_id'])
        if existing:
            doc = json.loads(existing['doc'])
            require(doc.get('record_type') == 'task-activity' and existing['request'] == fingerprint,
                    'Activity operation ID reused with different request')
            self.work._authorize(doc['context']['project_id'])
            return identifier
        context = self.work.capture(handle, context_revision=context_revision)
        target = request.get('document', request.get('source', request.get('item', request.get('preview', request.get('plan', request)))))
        pid = target.get('project_id') if isinstance(target, dict) else None
        for ref in references(request):
            if 'project_id' in ref:
                uuid(ref['project_id'])
                require(self.work.can_read(ref['project_id']), 'Activity reference is not readable')
        if pid is not None:
            uuid(pid)
            require(self.work.can_read(pid), 'Activity target is not readable')
        doc = dict(record_type='task-activity', event_id=identifier, operation_id=native,
                   context=context, request_sha256=fingerprint, target_project_id=pid, kind=ROUTES[route], route=route,
                   author_id=self.work.user_id, created_at=time.time(), updated_at=time.time(),
                   outcome='unknown', privacy=privacy_of(request), local_capture=not self.work.network, request_references=references(request), result_references=[])
        # Recheck CAS under the writer: a simultaneous task switch cannot redirect dispatch.
        with self.work._db(write=True) as db:
            window = self.work._window(db, handle)
            require(window['revision'] == context_revision and window['active'] == context['work_session_id']
                    and window['pending'] is None, 'Task context changed before activity dispatch')
            row = self.work._operation(db, identifier, handle['window_id'])
            if row:
                require(row['request'] == fingerprint, 'Activity operation ID reused')
            else:
                db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',
                           (identifier, self.work.user_id, handle['window_id'], fingerprint, canonical(doc)))
        return identifier

    def finish(self, identifier, code, payload):
        require(type(code) is int, 'Invalid activity response')
        payload = payload if isinstance(payload, dict) else {}
        outcome = payload.get('outcome')
        states = [item.get('state') for item in (payload, payload.get('turn'), payload.get('projection'))
                  if isinstance(item, dict)]
        if 'unknown' in states: outcome = 'unknown'
        elif 'failed' in states: outcome = 'failed'
        if not isinstance(outcome, str) or outcome not in {'failed', 'unknown'}:
            outcome = 'succeeded' if 200 <= code < 300 else 'unknown' if code == 409 else 'failed'
        # A transport/provider ambiguity is never evidence of failure or success.
        if payload.get('retry') == 'same-operation' and code >= 400:
            outcome = 'unknown' if outcome != 'failed' else outcome
        with self.work._db(write=True) as db:
            row = db.execute('SELECT * FROM operations WHERE id=? AND user_id=?',
                             (identifier, self.work.user_id)).fetchone()
            require(row is not None, 'Unknown activity')
            doc = json.loads(row['doc'])
            require(doc.get('record_type') == 'task-activity', 'Not an activity')
            # A rejected concurrent/replayed attempt cannot erase a confirmed native receipt.
            if doc['outcome'] == 'succeeded':
                return
            if doc['outcome']!=outcome or doc['result_references']!=references(payload):
                from spikes.task_records import offer
                state=offer(doc);doc['offer']=dict(state,revision=state['revision']+1)
            doc['privacy']=privacy_of([{'privacy':doc.get('privacy','local-only')},payload])
            doc.update(outcome=outcome, response_code=code, updated_at=time.time(),
                       result_references=references(payload))
            self.work._save_operation(db, identifier, doc)

    def _readable(self, pid):
        if not self.work.can_read(pid):
            return False
        if self.work.network:
            try:
                git = self.work.projects.repository(pid)
                return all(meta['privacy'] != 'local-only' for meta in
                           validate_snapshot(git.snapshot(git.head())).values())
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return False
        return True

    def for_session(self, handle, session_id):
        with self.work._db() as db:
            self.work._window(db, handle)
            session = self.work._session(db, session_id, handle['window_id'])
            rows = db.execute('SELECT doc FROM operations WHERE user_id=? AND window_id=? ORDER BY rowid',
                              (self.work.user_id, handle['window_id'])).fetchall()
        # Read permission and trust boundary now, not merely when the event was captured.
        self.work._authorize(session['project_id'])
        result = []
        readable_cache = {}
        def readable(pid):
            if pid not in readable_cache: readable_cache[pid] = self._readable(pid)
            return readable_cache[pid]
        for row in rows:
            doc = json.loads(row[0])
            if doc.get('record_type') != 'task-activity' or doc['context']['work_session_id'] != session_id:
                continue
            target = doc['target_project_id']
            if (target and not readable(target)) or any(
                    not readable(ref['project_id']) for ref in
                    doc['request_references'] + doc['result_references'] if 'project_id' in ref):
                continue
            # Local captures may refer to local-only artifacts. Until artifact-level
            # disclosure is available, web never projects desktop-captured receipts.
            if self.work.network and doc.get('local_capture', True):
                continue
            from spikes.task_records import offer
            doc['offer']=offer(doc)
            result.append(doc)
        return result


    def for_task(self,pid,task_id):
        require(self.work.can_read(pid),'Právo číst úkol bylo odebráno.')
        with self.work._db() as db:
            if db is None:return []
            rows=db.execute('SELECT doc FROM operations WHERE user_id=? ORDER BY rowid DESC',(self.work.user_id,)).fetchall()
        result=[]
        for row in rows:
            event=json.loads(row[0])
            if event.get('record_type')!='task-activity' or event['context']['project_id']!=pid or event['context']['task_id']!=task_id:continue
            if self.work.network and (event.get('local_capture',True) or event.get('privacy','local-only')=='local-only'):continue
            projects={r['project_id'] for r in event['request_references']+event['result_references'] if 'project_id' in r}
            if event.get('target_project_id'):projects.add(event['target_project_id'])
            if not all(self._readable(project) for project in projects):continue
            result.append(event)
        return result
