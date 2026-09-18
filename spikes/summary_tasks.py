# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local authority for durable summary requests and previews."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.metadata import require, uuid


STATES = {'prepared', 'run-bound', 'succeeded', 'failed', 'cancelled', 'unknown',
          'publishing', 'published'}
TERMINAL = {'failed', 'cancelled', 'unknown'}
MAX_OUTPUT = 1024 * 1024


class SummaryTasks:
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Summary state directory requires owned mode 0700')
        self.path = self.root / 'summary-tasks.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe summary task store')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                db.executescript('''
                    CREATE TABLE schema_info(version INTEGER NOT NULL);
                    INSERT INTO schema_info VALUES(2);
                    CREATE TABLE tasks(
                        task_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, user_id TEXT NOT NULL,
                        request_digest TEXT NOT NULL, request_json BLOB NOT NULL,
                        run_id TEXT NOT NULL UNIQUE, manifest_id TEXT NOT NULL UNIQUE,
                        manifest BLOB NOT NULL, payload BLOB NOT NULL,
                        privacy TEXT NOT NULL CHECK(privacy IN
                            ('public','project','confidential','local-only')),
                        state TEXT NOT NULL CHECK(state IN
                            ('prepared','run-bound','succeeded','failed','cancelled','unknown',
                             'publishing','published')),
                        response BLOB, response_sha256 TEXT, error TEXT,
                        publish_digest TEXT, publish_json BLOB, receipt_json BLOB);
                ''')
            else:
                require(tables == {'schema_info', 'tasks'}, 'Unknown or incomplete summary schema')
                version = db.execute('SELECT version FROM schema_info').fetchall()
                require(version in ([(1,)], [(2,)]),
                        'Unsupported summary schema version')
                if version == [(1,)]:
                    db.execute('ALTER TABLE tasks ADD COLUMN publish_digest TEXT')
                    db.execute('ALTER TABLE tasks ADD COLUMN publish_json BLOB')
                    db.execute('ALTER TABLE tasks ADD COLUMN receipt_json BLOB')
                    db.execute('UPDATE schema_info SET version=2')
                columns = [row[1] for row in db.execute('PRAGMA table_info(tasks)')]
                require(columns == ['task_id', 'node_id', 'user_id', 'request_digest',
                    'request_json', 'run_id', 'manifest_id', 'manifest', 'payload', 'privacy',
                    'state', 'response', 'response_sha256', 'error', 'publish_digest',
                    'publish_json', 'receipt_json'],
                    'Unknown or incomplete summary schema')
            db.commit()
            return closing(db)
        except Exception:
            db.close(); raise

    @staticmethod
    def _owned(row, node_id, user_id):
        require(row is not None and row[0] == node_id and row[1] == user_id,
                'Summary task is unavailable to this owner')

    def prepare(self, *, task_id, node_id, user_id, request, manifest, payload, privacy):
        for value in (task_id, node_id, user_id, manifest['run_id'], manifest['manifest_id']):
            uuid(value)
        require(privacy in {'public', 'project', 'confidential', 'local-only'},
                'Invalid summary privacy')
        request_raw = json.dumps(request, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode()
        digest = hashlib.sha256(request_raw).hexdigest()
        manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')).encode()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,request_digest,run_id,manifest_id,'
                             'manifest,payload,privacy FROM tasks WHERE task_id=?',
                             (task_id,)).fetchone()
            expected = (node_id, user_id, digest, manifest['run_id'], manifest['manifest_id'],
                        manifest_raw, payload, privacy)
            if row:
                require(row == expected, 'Task ID belongs to a different summary request')
            else:
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,'
                           'NULL,NULL,NULL)',
                           (task_id, node_id, user_id, digest, request_raw, manifest['run_id'],
                            manifest['manifest_id'], manifest_raw, payload, privacy, 'prepared'))
            db.commit()
        return self.get(task_id, node_id, user_id)

    def bind(self, task_id, node_id, user_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state FROM tasks WHERE task_id=?',
                             (task_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'prepared':
                db.execute("UPDATE tasks SET state='run-bound' WHERE task_id=?", (task_id,))
            else:
                require(row[2] in STATES - {'prepared'}, 'Invalid summary task state')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def succeed(self, task_id, node_id, user_id, response):
        require(isinstance(response, str) and bool(response.strip()) and '\0' not in response,
                'Summary output must be non-empty UTF-8 Markdown')
        raw = response.encode('utf-8')
        require(len(raw) <= MAX_OUTPUT, 'Summary output exceeds 1 MiB')
        digest = hashlib.sha256(raw).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,response,response_sha256 FROM tasks '
                             'WHERE task_id=?', (task_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'run-bound':
                db.execute("UPDATE tasks SET state='succeeded',response=?,response_sha256=? "
                           'WHERE task_id=?', (raw, digest, task_id))
            else:
                require(row[2] == 'succeeded' and row[3:] == (raw, digest),
                        'Summary task differs from durable result')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def finish(self, task_id, node_id, user_id, state, error):
        require(state in TERMINAL and isinstance(error, str)
                and 0 < len(error.encode()) <= 4096, 'Invalid summary failure')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,error FROM tasks WHERE task_id=?',
                             (task_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'run-bound':
                db.execute('UPDATE tasks SET state=?,error=? WHERE task_id=?',
                           (state, error, task_id))
            else:
                require(row[2:] == (state, error), 'Terminal summary differs from durable result')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def begin_publish(self, task_id, node_id, user_id, request):
        raw = json.dumps(request, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
        digest = hashlib.sha256(raw).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,publish_digest,publish_json '
                             'FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'succeeded':
                require(row[3:] == (None, None), 'Summary already has publication data')
                db.execute("UPDATE tasks SET state='publishing',publish_digest=?,publish_json=? "
                           'WHERE task_id=?', (digest, raw, task_id))
            else:
                require(row[2] in {'publishing', 'published'}
                        and row[3:] == (digest, raw),
                        'Summary has a different publication request')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def complete_publish(self, task_id, node_id, user_id, receipt):
        raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,receipt_json FROM tasks '
                             'WHERE task_id=?', (task_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'publishing':
                db.execute("UPDATE tasks SET state='published',receipt_json=? WHERE task_id=?",
                           (raw, task_id))
            else:
                require(row[2] == 'published' and row[3] == raw,
                        'Published summary differs from durable receipt')
            db.commit()
        return self.get(task_id, node_id, user_id)

    def get(self, task_id, node_id, user_id):
        uuid(task_id); uuid(node_id); uuid(user_id)
        with self.connect() as db:
            row = db.execute('SELECT node_id,user_id,request_digest,request_json,run_id,'
                'manifest_id,manifest,payload,privacy,state,response,response_sha256,error,'
                'publish_digest,publish_json,receipt_json '
                'FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        self._owned(row, node_id, user_id)
        require(row[9] in STATES, 'Invalid stored summary state')
        request = json.loads(row[3]); manifest = json.loads(row[6])
        canonical_request = json.dumps(request, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode()
        canonical_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode()
        require(row[3] == canonical_request
                and hashlib.sha256(row[3]).hexdigest() == row[2],
                'Stored summary request changed')
        require(row[6] == canonical_manifest and manifest['run_id'] == row[4]
                and manifest['manifest_id'] == row[5]
                and manifest['payload_size'] == len(row[7])
                and manifest['payload_sha256'] == hashlib.sha256(row[7]).hexdigest(),
                'Stored summary manifest or payload changed')
        response = None
        if row[10] is not None:
            response = row[10].decode('utf-8')
            require(hashlib.sha256(row[10]).hexdigest() == row[11],
                    'Stored summary response changed')
        publish = json.loads(row[14]) if row[14] is not None else None
        receipt = json.loads(row[15]) if row[15] is not None else None
        if publish is not None:
            canonical = json.dumps(publish, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')).encode()
            require(canonical == row[14] and hashlib.sha256(canonical).hexdigest() == row[13],
                    'Stored summary publication changed')
        if receipt is not None:
            require(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode() == row[15],
                    'Stored summary receipt changed')
        keys = ('node_id', 'user_id', 'request_digest', 'request', 'run_id', 'manifest_id',
                'manifest', 'payload', 'privacy', 'state', 'response', 'response_sha256', 'error',
                'publish_digest', 'publish', 'receipt')
        return dict(zip(keys, row[:3] + (request,) + row[4:6] + (manifest,) + row[7:10]
                             + (response,) + row[11:14] + (publish, receipt)))

    def list(self, node_id, user_id):
        uuid(node_id); uuid(user_id)
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                'SELECT task_id FROM tasks WHERE node_id=? AND user_id=? ORDER BY rowid',
                (node_id, user_id))]
        return [dict(task_id=value, **self.get(value, node_id, user_id)) for value in ids]
