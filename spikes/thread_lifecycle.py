# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Crash-recoverable removal of supported node-local chat thread state."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.chat_records import MARKER, OUTPUT_MARKER
from spikes.chat_threads import ChatThreads
from spikes.metadata import require, uuid


BLOCKED_TURNS = {'prepared', 'run-bound', 'unknown'}
BLOCKED_OUTCOMES = {'prepared'}
BLOCKED_APPROVALS = {'prepared', 'unknown'}
BLOCKED_RUNS = {'prepared', 'dispatching', 'unknown'}
BLOCKED_SEARCHES = {'prepared', 'dispatching', 'unknown'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


class ThreadLifecycle:
    def __init__(self, state_dir, projects):
        self.root = Path(state_dir).absolute(); self.projects = projects
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Thread lifecycle state requires owned mode 0700')
        self.path = self.root / 'thread-lifecycle.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe thread lifecycle journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('''CREATE TABLE IF NOT EXISTS operations(
            operation_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL UNIQUE,
            node_id TEXT NOT NULL, user_id TEXT NOT NULL,
            preview_sha256 TEXT NOT NULL, plan_json BLOB NOT NULL,
            stage TEXT NOT NULL, receipt_json BLOB)''')
        columns = [row[1] for row in db.execute('PRAGMA table_info(operations)')]
        require(columns == ['operation_id', 'thread_id', 'node_id', 'user_id',
            'preview_sha256', 'plan_json', 'stage', 'receipt_json'],
            'Unknown thread lifecycle schema')
        db.commit(); return closing(db)

    def _existing_db(self, name):
        path = self.root / name
        if not os.path.lexists(path): return None
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe linked thread store')
        return path

    def _rows(self, name, query, values=()):
        path = self._existing_db(name)
        if path is None: return []
        with closing(sqlite3.connect(path, timeout=30)) as db:
            return db.execute(query, values).fetchall()

    def _published(self, project_id, thread_id):
        if project_id is None: return []
        workspace = self.projects.workspace(project_id, blocking=False)
        head = workspace.git.head(); files = workspace.git.snapshot(head)
        compact = ('"thread_id":"' + thread_id + '"').encode()
        spaced = ('"thread_id": "' + thread_id + '"').encode()
        rows = []
        for path, raw in files.items():
            if not path.startswith('artifacts/') or not (compact in raw or spaced in raw):
                continue
            kind = ('snapshot' if MARKER.encode() in raw else
                    'output' if OUTPUT_MARKER.encode() in raw else None)
            parts = path.split('/')
            if kind is not None and len(parts) >= 3:
                rows.append({'artifact_id': parts[1], 'kind': kind})
        require(workspace.git.head() == head, 'Project changed during thread deletion preview')
        return sorted(rows, key=lambda row: (row['artifact_id'], row['kind']))

    @staticmethod
    def _json(value):
        try: return json.loads(value)
        except (TypeError, ValueError): return None

    def preview(self, *, thread_id, node_id, user_id):
        thread = ChatThreads(self.root).get(thread_id, node_id, user_id)
        outcomes = self._rows('task-outcomes.sqlite',
            'SELECT task_id,state,run_id,result FROM outcomes '
            'WHERE thread_id=? AND node_id=? AND user_id=? ORDER BY task_id',
            (thread_id, node_id, user_id))
        searches = []
        for task_id, *_ in outcomes:
            searches += self._rows('search-runs.sqlite',
                'SELECT search_id,task_id,state,request_json FROM searches WHERE task_id=?',
                (task_id,))
        approvals = []
        for approval_id, state, run_id, request in self._rows(
                'external-dispatches.sqlite',
                'SELECT approval_id,state,run_id,request FROM approvals '
                'WHERE node_id=? AND user_id=? ORDER BY approval_id', (node_id, user_id)):
            value = self._json(request)
            if isinstance(value, dict) and value.get('thread_id') == thread_id:
                approvals.append((approval_id, state, run_id))
        run_ids = {turn['run_id'] for turn in thread['turns'] if turn['run_id']}
        run_ids.update(row[2] for row in outcomes if row[2])
        run_ids.update(row[2] for row in approvals if row[2])
        for _, _, _, raw in searches:
            value = self._json(raw)
            if isinstance(value, dict) and isinstance(value.get('synthesis_run_id'), str):
                run_ids.add(value['synthesis_run_id'])
        approval_ids = {row[0] for row in approvals}
        for _, _, _, result in outcomes:
            value = self._json(result)
            if isinstance(value, dict):
                if isinstance(value.get('approval_id'), str): approval_ids.add(value['approval_id'])
                if isinstance(value.get('run_id'), str): run_ids.add(value['run_id'])
                external = value.get('external_preview')
                if isinstance(external, dict):
                    if isinstance(external.get('approval_id'), str): approval_ids.add(external['approval_id'])
                    if isinstance(external.get('run_id'), str): run_ids.add(external['run_id'])
        backend_runs = []
        for filename, adapter in (('ollama-runs.sqlite', 'ollama'),
                                  ('openai-runs.sqlite', 'openai-responses')):
            for run_id in sorted(run_ids):
                rows = self._rows(filename, 'SELECT state FROM runs WHERE run_id=?', (run_id,))
                if rows: backend_runs.append({'run_id': run_id, 'adapter': adapter,
                                              'state': rows[0][0]})
        blockers = []
        blockers += [{'kind': 'turn', 'id': row['turn_id'], 'state': row['state']}
                     for row in thread['turns'] if row['state'] in BLOCKED_TURNS]
        blockers += [{'kind': 'task-outcome', 'id': row[0], 'state': row[1]}
                     for row in outcomes if row[1] in BLOCKED_OUTCOMES]
        blockers += [{'kind': 'approval', 'id': row[0], 'state': row[1]}
                     for row in approvals if row[1] in BLOCKED_APPROVALS]
        blockers += [{'kind': 'backend-run', 'id': row['run_id'], 'state': row['state']}
                     for row in backend_runs if row['state'] in BLOCKED_RUNS]
        blockers += [{'kind': 'web-search', 'id': row[0], 'state': row[2]}
                     for row in searches if row[2] in BLOCKED_SEARCHES]
        plan = {'schema': 'fpw-thread-deletion-preview-v1', 'thread_id': thread_id,
            'node_id': node_id, 'user_id': user_id, 'expected_revision': thread['revision'],
            'project_id': thread['project_id'], 'status': thread['status'],
            'counts': {'messages': len(thread['messages']), 'turns': len(thread['turns']),
                       'task_outcomes': len(outcomes), 'approvals': len(approval_ids),
                       'backend_runs': len(backend_runs), 'web_searches': len(searches)},
            'task_ids': sorted(row[0] for row in outcomes),
            'search_ids': sorted(row[0] for row in searches),
            'approval_ids': sorted(approval_ids), 'run_ids': sorted(run_ids),
            'published_artifacts': self._published(thread['project_id'], thread_id),
            'published_git_history_preserved': True,
            'blockers': sorted(blockers, key=lambda row: (row['kind'], row['id']))}
        plan['preview_sha256'] = hashlib.sha256(_canonical(plan)).hexdigest()
        return plan

    def _operation(self, operation_id):
        with self.connect() as db:
            row = db.execute('SELECT thread_id,node_id,user_id,preview_sha256,plan_json,'
                             'stage,receipt_json FROM operations WHERE operation_id=?',
                             (operation_id,)).fetchone()
        if row is None: return None
        return {'thread_id': row[0], 'node_id': row[1], 'user_id': row[2],
                'preview_sha256': row[3], 'plan': json.loads(row[4]), 'stage': row[5],
                'receipt': None if row[6] is None else json.loads(row[6])}

    def _advance(self, operation_id, current, following, receipt=None):
        raw = None if receipt is None else _canonical(receipt)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE operations SET stage=?,receipt_json=? '
                'WHERE operation_id=? AND stage=?', (following, raw, operation_id, current))
            require(changed.rowcount == 1, 'Thread deletion stage changed concurrently')
            db.commit()

    def _delete_ids(self, filename, table, column, values):
        path = self._existing_db(filename)
        if path is None or not values: return
        with closing(sqlite3.connect(path, timeout=30)) as db:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            db.executemany(f'DELETE FROM {table} WHERE {column}=?', [(v,) for v in values])
            db.commit()

    def recover_pending(self, *, node_id, user_id):
        uuid(node_id); uuid(user_id)
        with self.connect() as db:
            rows = db.execute('SELECT operation_id,thread_id,preview_sha256,plan_json,stage '
                'FROM operations WHERE node_id=? AND user_id=? AND stage<>? ORDER BY rowid',
                (node_id, user_id, 'completed')).fetchall()
        result = []
        for operation_id, thread_id, digest, raw, stage in rows:
            plan = json.loads(raw)
            try:
                receipt = self.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
                    operation_id=operation_id, expected_revision=plan['expected_revision'],
                    preview_sha256=digest)
            except (ValueError, OSError, sqlite3.Error) as exc:
                result.append({'operation_id': operation_id, 'thread_id': thread_id,
                               'state': 'blocked', 'stage': stage, 'error': str(exc)})
            else:
                result.append(receipt)
        return result

    def confirm(self, *, thread_id, node_id, user_id, operation_id,
                expected_revision, preview_sha256, checkpoint=lambda stage: None):
        for value in (thread_id, node_id, user_id, operation_id): uuid(value)
        require(type(expected_revision) is int and expected_revision >= 0,
                'Invalid expected thread revision')
        current = self._operation(operation_id)
        if current is None:
            plan = self.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
            require(plan['expected_revision'] == expected_revision,
                    'Chat thread changed after deletion preview')
            require(plan['preview_sha256'] == preview_sha256,
                    'Chat thread deletion preview changed')
            require(not plan['blockers'], 'Chat thread has active or unknown local effects')
            raw = _canonical(plan)
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                require(db.execute('SELECT 1 FROM operations WHERE thread_id=?',
                                   (thread_id,)).fetchone() is None,
                        'Chat thread already has a deletion operation')
                db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,NULL)',
                    (operation_id, thread_id, node_id, user_id, preview_sha256, raw, 'planned'))
                db.commit()
            current = self._operation(operation_id)
            checkpoint('planned')
        require((current['thread_id'], current['node_id'], current['user_id'],
                 current['preview_sha256']) ==
                (thread_id, node_id, user_id, preview_sha256),
                'Deletion operation belongs to a different request')
        if current['stage'] == 'completed': return current['receipt']
        plan = current['plan']; stage = current['stage']
        if stage == 'planned':
            markers = self._rows('chat-threads.sqlite',
                'SELECT operation_id,node_id,user_id,preview_sha256 FROM deletions '
                'WHERE thread_id=?', (thread_id,))
            if markers:
                require(markers == [(operation_id, node_id, user_id, preview_sha256)],
                        'Chat thread has a different deletion lock')
            else:
                refreshed = self.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
                require(refreshed['preview_sha256'] == preview_sha256
                        and not refreshed['blockers'],
                        'Chat thread changed before deletion lock')
            ChatThreads(self.root).mark_deleting(thread_id=thread_id, node_id=node_id,
                user_id=user_id, operation_id=operation_id, preview_sha256=preview_sha256,
                expected_revision=plan['expected_revision'])
            checkpoint('marked'); self._advance(operation_id, 'planned', 'marked'); stage = 'marked'
        if stage == 'marked':
            self._delete_ids('external-dispatches.sqlite', 'approvals', 'approval_id',
                             plan['approval_ids'])
            checkpoint('approvals'); self._advance(operation_id, 'marked', 'approvals'); stage = 'approvals'
        if stage == 'approvals':
            self._delete_ids('search-runs.sqlite', 'searches', 'search_id',
                             plan.get('search_ids', []))
            self._delete_ids('task-outcomes.sqlite', 'outcomes', 'task_id', plan['task_ids'])
            checkpoint('outcomes'); self._advance(operation_id, 'approvals', 'outcomes'); stage = 'outcomes'
        if stage == 'outcomes':
            for filename in ('ollama-runs.sqlite', 'openai-runs.sqlite'):
                self._delete_ids(filename, 'runs', 'run_id', plan['run_ids'])
            checkpoint('runs'); self._advance(operation_id, 'outcomes', 'runs'); stage = 'runs'
        if stage == 'runs':
            ChatThreads(self.root).delete_marked(thread_id=thread_id, node_id=node_id,
                user_id=user_id, operation_id=operation_id, preview_sha256=preview_sha256)
            checkpoint('thread'); self._advance(operation_id, 'runs', 'thread'); stage = 'thread'
        if stage == 'thread':
            receipt = {'operation_id': operation_id, 'thread_id': thread_id,
                       'preview_sha256': preview_sha256, 'state': 'completed',
                       'deleted': plan['counts'],
                       'published_artifacts_preserved': plan['published_artifacts']}
            checkpoint('completed'); self._advance(operation_id, 'thread', 'completed', receipt)
            return receipt
        raise ValueError('Unsupported thread deletion recovery stage')
