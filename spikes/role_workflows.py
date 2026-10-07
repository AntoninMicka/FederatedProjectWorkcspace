# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict node-local authority for a two-step creator/opponent workflow."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.metadata import require, timestamp, uuid


STEP_STATES = {'unused', 'prepared', 'run-bound', 'succeeded', 'failed',
               'cancelled', 'unknown'}
TERMINAL = {'failed', 'cancelled', 'unknown'}
MAX_OUTPUT = 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class RoleWorkflows:
    """Durable workflow evidence; backend dispatch journals remain separate."""

    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Workflow state directory requires owned mode 0700')
        self.path = self.root / 'role-workflows.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe workflow journal')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                db.executescript('''
                    CREATE TABLE schema_info(version INTEGER NOT NULL);
                    INSERT INTO schema_info VALUES(2);
                    CREATE TABLE workflows(
                        workflow_id TEXT PRIMARY KEY,
                        node_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        expected_head TEXT NOT NULL,
                        request_digest TEXT NOT NULL,
                        request_json BLOB NOT NULL,
                        publish_state TEXT NOT NULL CHECK(publish_state IN
                            ('unpublished','publishing','published')),
                        publish_digest TEXT,
                        publish_json BLOB,
                        receipt_json BLOB);
                    CREATE TABLE steps(
                        workflow_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL CHECK(ordinal IN (1,2)),
                        step_id TEXT NOT NULL UNIQUE,
                        run_id TEXT NOT NULL UNIQUE,
                        manifest_id TEXT NOT NULL UNIQUE,
                        role_id TEXT NOT NULL,
                        role_revision TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN
                            ('unused','prepared','run-bound','succeeded','failed',
                             'cancelled','unknown')),
                        approval_digest TEXT,
                        preview_json BLOB,
                        manifest BLOB,
                        payload BLOB,
                        privacy TEXT,
                        provider_request BLOB,
                        response BLOB,
                        response_sha256 TEXT,
                        completed_at TEXT,
                        error TEXT,
                        PRIMARY KEY(workflow_id,ordinal),
                        FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id));
                ''')
            else:
                require(tables == {'schema_info', 'workflows', 'steps'},
                        'Unknown or incomplete workflow schema')
                version = db.execute('SELECT version FROM schema_info').fetchall()
                require(version in ([(1,)], [(2,)]),
                        'Unsupported workflow schema version')
                if version == [(1,)]:
                    db.execute("ALTER TABLE workflows ADD COLUMN publish_state TEXT NOT NULL "
                               "DEFAULT 'unpublished' CHECK(publish_state IN "
                               "('unpublished','publishing','published'))")
                    db.execute('ALTER TABLE workflows ADD COLUMN publish_digest TEXT')
                    db.execute('ALTER TABLE workflows ADD COLUMN publish_json BLOB')
                    db.execute('ALTER TABLE workflows ADD COLUMN receipt_json BLOB')
                    db.execute('UPDATE schema_info SET version=2')
                workflow_columns = [row[1] for row in
                    db.execute('PRAGMA table_info(workflows)')]
                step_columns = [row[1] for row in db.execute('PRAGMA table_info(steps)')]
                require(workflow_columns == ['workflow_id', 'node_id', 'user_id',
                    'project_id', 'expected_head', 'request_digest', 'request_json',
                    'publish_state', 'publish_digest', 'publish_json', 'receipt_json']
                    and step_columns == ['workflow_id', 'ordinal', 'step_id', 'run_id',
                    'manifest_id', 'role_id', 'role_revision', 'state',
                    'approval_digest', 'preview_json', 'manifest', 'payload', 'privacy',
                    'provider_request', 'response', 'response_sha256', 'completed_at',
                    'error'],
                    'Unknown or incomplete workflow schema')
            db.commit()
            return closing(db)
        except Exception:
            db.close(); raise

    @staticmethod
    def _owned(row, node_id, user_id):
        require(row is not None and row[0] == node_id and row[1] == user_id,
                'Workflow is unavailable to this owner')

    def prepare(self, *, request, node_id, user_id, creator):
        workflow_id = request['workflow_id']
        for value in (workflow_id, node_id, user_id, request['project_id']):
            uuid(value)
        request_raw = canonical(request); request_digest = digest(request_raw)
        creator_step = request['creator']; opponent_step = request['opponent']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,request_digest,request_json '
                             'FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone()
            if row:
                self._owned(row, node_id, user_id)
                require(row[2:] == (request_digest, request_raw),
                        'Workflow ID belongs to a different request')
            else:
                db.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,'
                           'NULL,NULL,NULL)',
                    (workflow_id, node_id, user_id, request['project_id'],
                     request['expected_head'], request_digest, request_raw,
                     'unpublished'))
                db.execute('INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (workflow_id, 1, creator_step['step_id'], creator_step['run_id'],
                     creator_step['manifest_id'], creator_step['role_id'],
                     creator_step['role_revision'], 'prepared', creator['approval_digest'],
                     canonical(creator['preview']), creator['manifest'], creator['payload'],
                     creator['privacy'], creator['provider_request'], None, None, None, None))
                db.execute('INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,'
                           'NULL,NULL,NULL,NULL,NULL)',
                    (workflow_id, 2, opponent_step['step_id'], opponent_step['run_id'],
                     opponent_step['manifest_id'], opponent_step['role_id'],
                     opponent_step['role_revision'], 'unused'))
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def prepare_opponent(self, workflow_id, node_id, user_id, opponent):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute('SELECT node_id,user_id FROM workflows WHERE workflow_id=?',
                               (workflow_id,)).fetchone()
            self._owned(owner, node_id, user_id)
            row = db.execute('SELECT state FROM steps WHERE workflow_id=? AND ordinal=2',
                             (workflow_id,)).fetchone()
            require(row is not None, 'Workflow opponent slot is missing')
            if row[0] == 'unused':
                db.execute("UPDATE steps SET state='prepared',approval_digest=?,preview_json=?,"
                           'manifest=?,payload=?,privacy=?,provider_request=? '
                           'WHERE workflow_id=? AND ordinal=2',
                    (opponent['approval_digest'], canonical(opponent['preview']),
                     opponent['manifest'], opponent['payload'], opponent['privacy'],
                     opponent['provider_request'], workflow_id))
            else:
                require(row[0] in STEP_STATES - {'unused'},
                        'Invalid opponent step state')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def bind(self, workflow_id, ordinal, node_id, user_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT w.node_id,w.user_id,s.state FROM workflows w '
                'JOIN steps s ON s.workflow_id=w.workflow_id '
                'WHERE w.workflow_id=? AND s.ordinal=?',
                (workflow_id, ordinal)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'prepared':
                db.execute("UPDATE steps SET state='run-bound' "
                           'WHERE workflow_id=? AND ordinal=?', (workflow_id, ordinal))
            else:
                require(row[2] in STEP_STATES - {'unused', 'prepared'},
                        'Invalid workflow step state')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def succeed(self, workflow_id, ordinal, node_id, user_id, response):
        require(isinstance(response, str) and bool(response.strip()) and '\0' not in response,
                'Workflow output must be non-empty UTF-8 Markdown')
        raw = response.encode('utf-8')
        require(len(raw) <= MAX_OUTPUT, 'Workflow output exceeds 1 MiB')
        response_digest = digest(raw)
        completed_at = datetime.now(timezone.utc).isoformat(
            timespec='microseconds').replace('+00:00', 'Z')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT w.node_id,w.user_id,s.state,s.response,'
                's.response_sha256,s.completed_at FROM workflows w JOIN steps s '
                'ON s.workflow_id=w.workflow_id WHERE w.workflow_id=? AND s.ordinal=?',
                (workflow_id, ordinal)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'run-bound':
                db.execute("UPDATE steps SET state='succeeded',response=?,response_sha256=?,"
                           'completed_at=? '
                           'WHERE workflow_id=? AND ordinal=?',
                           (raw, response_digest, completed_at, workflow_id, ordinal))
            else:
                require(row[2] == 'succeeded' and row[3] == raw
                        and row[4] == response_digest,
                        'Workflow step differs from durable result')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def finish(self, workflow_id, ordinal, node_id, user_id, state, error):
        require(state in TERMINAL and isinstance(error, str)
                and 0 < len(error.encode()) <= 4096, 'Invalid workflow failure')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT w.node_id,w.user_id,s.state,s.error FROM workflows w '
                'JOIN steps s ON s.workflow_id=w.workflow_id '
                'WHERE w.workflow_id=? AND s.ordinal=?',
                (workflow_id, ordinal)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'run-bound':
                db.execute('UPDATE steps SET state=?,error=? '
                           'WHERE workflow_id=? AND ordinal=?',
                           (state, error, workflow_id, ordinal))
            else:
                require(row[2:] == (state, error),
                        'Terminal workflow step differs from durable result')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def begin_publish(self, workflow_id, node_id, user_id, request):
        raw = canonical(request); request_digest = digest(raw)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,publish_state,publish_digest,'
                'publish_json FROM workflows WHERE workflow_id=?',
                (workflow_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'unpublished':
                require(row[3:] == (None, None),
                        'Workflow has inconsistent publication data')
                db.execute("UPDATE workflows SET publish_state='publishing',"
                           'publish_digest=?,publish_json=? WHERE workflow_id=?',
                           (request_digest, raw, workflow_id))
            else:
                require(row[2] in {'publishing', 'published'}
                        and row[3:] == (request_digest, raw),
                        'Workflow has a different publication request')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def complete_publish(self, workflow_id, node_id, user_id, receipt):
        raw = canonical(receipt)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,publish_state,receipt_json '
                'FROM workflows WHERE workflow_id=?', (workflow_id,)).fetchone()
            self._owned(row, node_id, user_id)
            if row[2] == 'publishing':
                db.execute("UPDATE workflows SET publish_state='published',receipt_json=? "
                           'WHERE workflow_id=?', (raw, workflow_id))
            else:
                require(row[2] == 'published' and row[3] == raw,
                        'Published workflow differs from durable receipt')
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def get(self, workflow_id, node_id, user_id):
        uuid(workflow_id); uuid(node_id); uuid(user_id)
        with self.connect() as db:
            workflow = db.execute('SELECT node_id,user_id,project_id,expected_head,'
                'request_digest,request_json,publish_state,publish_digest,publish_json,'
                'receipt_json FROM workflows WHERE workflow_id=?',
                (workflow_id,)).fetchone()
            self._owned(workflow, node_id, user_id)
            rows = db.execute('SELECT ordinal,step_id,run_id,manifest_id,role_id,'
                'role_revision,state,approval_digest,preview_json,manifest,payload,privacy,'
                'provider_request,response,response_sha256,completed_at,error FROM steps '
                'WHERE workflow_id=? ORDER BY ordinal', (workflow_id,)).fetchall()
        require(len(rows) == 2 and [row[0] for row in rows] == [1, 2],
                'Workflow requires exactly two ordered step slots')
        request = json.loads(workflow[5]); request_raw = canonical(request)
        require(request_raw == workflow[5] and digest(request_raw) == workflow[4],
                'Stored workflow request changed')
        require(workflow[6] in {'unpublished', 'publishing', 'published'},
                'Invalid workflow publication state')
        publish = json.loads(workflow[8]) if workflow[8] is not None else None
        receipt = json.loads(workflow[9]) if workflow[9] is not None else None
        if publish is None:
            require(workflow[6] == 'unpublished' and workflow[7] is None
                    and receipt is None, 'Unpublished workflow has publication data')
        else:
            publish_raw = canonical(publish)
            require(publish_raw == workflow[8] and digest(publish_raw) == workflow[7],
                    'Stored workflow publication changed')
            require(workflow[6] in {'publishing', 'published'},
                    'Workflow publication state is inconsistent')
        if receipt is not None:
            require(workflow[6] == 'published' and canonical(receipt) == workflow[9],
                    'Stored workflow publication receipt changed')
        steps = []
        for row in rows:
            require(row[6] in STEP_STATES, 'Invalid stored workflow step state')
            preview = json.loads(row[8]) if row[8] is not None else None
            manifest = json.loads(row[9]) if row[9] is not None else None
            response = row[13].decode('utf-8') if row[13] is not None else None
            if preview is not None:
                require(canonical(preview) == row[8]
                        and digest(row[8] + b'\0' + row[12]) == row[7],
                        'Stored workflow preview changed')
                require(canonical(manifest) == row[9]
                        and manifest['manifest_id'] == row[3]
                        and manifest['run_id'] == row[2]
                        and manifest['payload_size'] == len(row[10])
                        and manifest['payload_sha256'] == digest(row[10]),
                        'Stored workflow manifest or payload changed')
            else:
                require(row[6] == 'unused' and all(value is None for value in row[7:]),
                        'Unused workflow step contains prepared data')
            if response is not None:
                require(digest(row[13]) == row[14], 'Stored workflow response changed')
                timestamp(row[15], 'completed_at')
            else:
                require(row[15] is None, 'Workflow step without response has completion time')
            keys = ('ordinal', 'step_id', 'run_id', 'manifest_id', 'role_id',
                    'role_revision', 'state', 'approval_digest', 'preview', 'manifest',
                    'payload', 'privacy', 'provider_request', 'response',
                    'response_sha256', 'completed_at', 'error')
            steps.append(dict(zip(keys, row[:8] + (preview, manifest) + row[10:13]
                                   + (response,) + row[14:])))
        return {'workflow_id': workflow_id, 'node_id': workflow[0],
                'user_id': workflow[1], 'project_id': workflow[2],
                'expected_head': workflow[3], 'request_digest': workflow[4],
                'request': request, 'publish_state': workflow[6],
                'publish_digest': workflow[7], 'publish': publish,
                'receipt': receipt, 'steps': steps}

    def list(self, node_id, user_id):
        uuid(node_id); uuid(user_id)
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                'SELECT workflow_id FROM workflows WHERE node_id=? AND user_id=? '
                'ORDER BY rowid', (node_id, user_id))]
        return [self.get(value, node_id, user_id) for value in ids]
