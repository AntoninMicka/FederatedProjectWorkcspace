# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable human approvals for exact external-provider chat dispatches."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.metadata import require, timestamp, uuid


STATES = {'prepared', 'cancelled', 'succeeded', 'failed', 'unknown'}


class ExternalDispatches:
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'External dispatch state requires owned mode 0700')
        self.path = self.root / 'external-dispatches.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe external dispatch store')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS approvals('
                   'approval_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,user_id TEXT NOT NULL,'
                   'request TEXT NOT NULL,manifest BLOB NOT NULL,payload BLOB NOT NULL,'
                   'provider_request BLOB NOT NULL,preview_sha256 TEXT NOT NULL,'
                   'binding_sha256 TEXT NOT NULL,privacy TEXT NOT NULL,'
                   'created_at TEXT NOT NULL,state TEXT NOT NULL,'
                   'result TEXT,error TEXT)')
        db.commit()
        return closing(db)

    def prepare(self, *, approval_id, node_id, user_id, request, manifest, payload,
                provider_request, preview_sha256, binding_sha256, privacy, created_at):
        for value in (approval_id, node_id, user_id):
            uuid(value)
        timestamp(created_at)
        require(privacy in {'public', 'project', 'confidential'},
                'External privacy policy forbids this request')
        require(isinstance(request, dict) and type(manifest) is bytes
                and type(payload) is bytes and type(provider_request) is bytes
                and len(preview_sha256) == 64 and len(binding_sha256) == 64,
                'Invalid external dispatch preview')
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'))
        values = (node_id, user_id, encoded, manifest, payload, provider_request,
                  preview_sha256, binding_sha256, privacy, created_at)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,request,manifest,payload,provider_request,'
                             'preview_sha256,binding_sha256,privacy,created_at,state FROM approvals '
                             'WHERE approval_id=?', (approval_id,)).fetchone()
            if row:
                require(row[:10] == values and row[10] == 'prepared',
                        'Approval ID belongs to a different or closed preview')
            else:
                db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)',
                           (approval_id,) + values + ('prepared',))
            db.commit()
        return self.get(approval_id, node_id, user_id)

    def get(self, approval_id, node_id, user_id):
        for value in (approval_id, node_id, user_id):
            uuid(value)
        with self.connect() as db:
            row = db.execute('SELECT request,manifest,payload,provider_request,preview_sha256,'
                             'binding_sha256,privacy,created_at,state,result,error,node_id,user_id '
                             'FROM approvals WHERE approval_id=?', (approval_id,)).fetchone()
        require(row is not None and row[11:] == (node_id, user_id),
                'External preview is unavailable to this user')
        require(row[8] in STATES, 'Invalid external preview state')
        return {'approval_id': approval_id, 'request': json.loads(row[0]),
                'manifest': row[1], 'payload': row[2], 'provider_request': row[3],
                'preview_sha256': row[4], 'binding_sha256': row[5],
                'privacy': row[6], 'created_at': row[7], 'state': row[8],
                'result': None if row[9] is None else json.loads(row[9]),
                'error': row[10]}

    def finish(self, approval_id, node_id, user_id, state, *, result=None, error=None):
        require(state in {'cancelled', 'succeeded', 'failed', 'unknown'},
                'Invalid terminal external dispatch state')
        current = self.get(approval_id, node_id, user_id)
        if current['state'] != 'prepared':
            require(current['state'] == state, 'External preview is already closed')
            return current
        encoded = (json.dumps(result, ensure_ascii=False, sort_keys=True,
                              separators=(',', ':')) if result is not None else None)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE approvals SET state=?,result=?,error=? '
                                 "WHERE approval_id=? AND state='prepared'",
                                 (state, encoded, error, approval_id))
            require(changed.rowcount == 1, 'External preview changed while completing')
            db.commit()
        return self.get(approval_id, node_id, user_id)
