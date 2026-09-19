# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable chat projections for long unified AI task outcomes."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.ai_outcome import AITaskOutcome
from spikes.metadata import require, timestamp, uuid


STATES = {'prepared', 'cancelled', 'completed'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


class TaskOutcomes:
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Task outcome state requires owned mode 0700')
        self.path = self.root / 'task-outcomes.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe task outcome store')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS outcomes('
                   'task_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,user_id TEXT NOT NULL,'
                   'project_id TEXT NOT NULL,thread_id TEXT NOT NULL,request TEXT NOT NULL,'
                   'outcome TEXT NOT NULL,privacy TEXT NOT NULL,project_commit TEXT NOT NULL,'
                   'run_id TEXT NOT NULL,manifest_id TEXT NOT NULL,created_at TEXT NOT NULL,'
                   'state TEXT NOT NULL,result TEXT)')
        db.commit()
        return closing(db)

    def prepare(self, *, node_id, user_id, request, routed):
        for value in (node_id, user_id, request.get('task_id'), request.get('project_id'),
                      request.get('thread_id'), routed.get('run_id'), routed.get('manifest_id')):
            uuid(value)
        timestamp(request.get('created_at'))
        outcome = AITaskOutcome.parse(routed.get('outcome')).serialize()
        require(routed.get('task_id') == request['task_id']
                and routed.get('privacy') in {'public', 'project', 'confidential', 'local-only'}
                and isinstance(routed.get('project_commit'), str),
                'Invalid routed task result')
        values = (node_id, user_id, request['project_id'], request['thread_id'],
                  _canonical(request), _canonical(outcome), routed['privacy'],
                  routed['project_commit'], routed['run_id'], routed['manifest_id'],
                  request['created_at'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,project_id,thread_id,request,outcome,'
                             'privacy,project_commit,run_id,manifest_id,created_at,state '
                             'FROM outcomes WHERE task_id=?', (request['task_id'],)).fetchone()
            if row:
                require(row[:11] == values, 'Task ID belongs to a different outcome')
            else:
                db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                           (request['task_id'],) + values + ('prepared',))
            db.commit()
        return self.get(request['task_id'], node_id, user_id)

    @staticmethod
    def _projection(task_id, row):
        request, outcome = json.loads(row[4]), json.loads(row[5])
        result = None if row[12] is None else json.loads(row[12])
        projection = {'task_id': task_id, 'project_id': row[2], 'thread_id': row[3],
                      'privacy': row[6], 'created_at': row[10], 'state': row[11],
                      'prompt': {'message_id': request['message_id'],
                                 'content': request['content'],
                                 'privacy': request['privacy']}}
        if row[11] == 'prepared':
            projection.update(temporary=True, outcome=outcome)
            if result is not None:
                projection['external_preview'] = result
        elif row[11] == 'completed':
            projection.update(temporary=False, outcome=result)
        else:
            projection.update(temporary=False, outcome=None)
        return {'task_id': task_id, 'node_id': row[0], 'user_id': row[1],
                'project_id': row[2], 'thread_id': row[3], 'request': request,
                'outcome': outcome, 'privacy': row[6], 'project_commit': row[7],
                'run_id': row[8], 'manifest_id': row[9], 'created_at': row[10],
                'state': row[11], 'result': result, 'projection': projection}

    def get(self, task_id, node_id, user_id):
        for value in (task_id, node_id, user_id): uuid(value)
        with self.connect() as db:
            row = db.execute('SELECT node_id,user_id,project_id,thread_id,request,outcome,'
                             'privacy,project_commit,run_id,manifest_id,created_at,state,result '
                             'FROM outcomes WHERE task_id=?', (task_id,)).fetchone()
        require(row is not None and row[:2] == (node_id, user_id),
                'Task outcome is unavailable to this user')
        require(row[11] in STATES, 'Invalid task outcome state')
        return self._projection(task_id, row)

    def list(self, node_id, user_id, project_id, thread_id=None):
        for value in (node_id, user_id, project_id): uuid(value)
        if thread_id is not None:
            uuid(thread_id)
        with self.connect() as db:
            query = ('SELECT task_id,node_id,user_id,project_id,thread_id,request,'
                     'outcome,privacy,project_commit,run_id,manifest_id,created_at,state,'
                     'result FROM outcomes WHERE node_id=? AND user_id=? AND project_id=?')
            values = [node_id, user_id, project_id]
            if thread_id is not None:
                query += ' AND thread_id=?'; values.append(thread_id)
            rows = db.execute(query + ' ORDER BY created_at,task_id', values).fetchall()
        return [self._projection(row[0], row[1:])['projection'] for row in rows]

    def finish(self, task_id, node_id, user_id, state, *, result=None):
        require(state in {'cancelled', 'completed'}, 'Invalid terminal task outcome state')
        current = self.get(task_id, node_id, user_id)
        if current['state'] != 'prepared':
            require(current['state'] == state
                    and current['result'] == result,
                    'Task outcome is already closed')
            return current
        if state == 'completed':
            require(isinstance(result, dict), 'Completed task outcome requires a result')
        else:
            require(result is None, 'Cancelled task outcome cannot have a result')
        encoded = None if result is None else _canonical(result)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE outcomes SET state=?,result=? '
                                 "WHERE task_id=? AND state='prepared'",
                                 (state, encoded, task_id))
            require(changed.rowcount == 1, 'Task outcome changed while completing')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def bind_external_preview(self, task_id, node_id, user_id, preview):
        current = self.get(task_id, node_id, user_id)
        require(current['state'] == 'prepared'
                and current['outcome']['kind'] == 'external-request'
                and isinstance(preview, dict)
                and preview.get('task_id') == task_id
                and isinstance(preview.get('preview_sha256'), str),
                'Invalid task external preview')
        if current['result'] is not None:
            require(current['result'] == preview,
                    'Task already belongs to a different external preview')
            return current
        encoded = _canonical(preview)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE outcomes SET result=? '
                                 "WHERE task_id=? AND state='prepared' AND result IS NULL",
                                 (encoded, task_id))
            require(changed.rowcount == 1,
                    'Task external preview changed while binding')
            db.commit()
        return self.get(task_id, node_id, user_id)
