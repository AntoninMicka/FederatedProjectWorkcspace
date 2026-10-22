# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Authoritative local SQLite journal containing exact outbound Git bundles."""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from spikes.administration import identifier
from spikes.metadata import require
from spikes.network_backend import private_root


@contextmanager
def database(node, *, create=False):
    root = Path(node).absolute().parent / ('.' + Path(node).name + '.network')
    path = root / 'git-transfer-journal.sqlite'
    if not create and not os.path.lexists(path):
        yield None
        return
    root = private_root(node)
    flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd); os.close(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and not info.st_mode & 0o077, 'Unsafe transfer journal')
    with closing(sqlite3.connect(path, timeout=60)) as db:
        db.execute('PRAGMA synchronous=FULL')
        if create:
            db.execute('CREATE TABLE IF NOT EXISTS transfers '
                       '(operation_id TEXT PRIMARY KEY, context TEXT NOT NULL, head TEXT NOT NULL, '
                       'commit_count INTEGER NOT NULL, digest TEXT NOT NULL, bundle BLOB NOT NULL, '
                       'done INTEGER NOT NULL DEFAULT 0, receipt TEXT)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(transfers)')}
            if 'receipt' not in columns:
                db.execute('ALTER TABLE transfers ADD COLUMN receipt TEXT')
            db.commit()
        yield db


def pending_operation(node, project_id, recipient_id):
    with database(node) as db:
        if db is None:
            return None
        for operation, raw in db.execute('SELECT operation_id, context FROM transfers WHERE done=0 ORDER BY rowid'):
            context = json.loads(raw)
            if context['project_id'] == project_id and context['recipient_node_id'] == recipient_id:
                identifier(operation)
                return operation
    return None


def pending_transfer(node, project_id, recipient_id):
    with database(node) as db:
        if db is None:
            return None
        for row in db.execute(
                'SELECT operation_id,context,head FROM transfers '
                'WHERE done=0 ORDER BY rowid'):
            context = json.loads(row[1])
            if (context['project_id'] == project_id
                    and context['recipient_node_id'] == recipient_id):
                identifier(row[0])
                return {'operation_id': row[0], 'context': context,
                        'candidate_head': row[2]}
    return None


def replication_runtime(node, replication_id=None):
    with database(node) as db:
        if db is None:
            return {} if replication_id is None else None
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='replication_runtime'").fetchone() is None:
            return {} if replication_id is None else None
        rows = db.execute(
            'SELECT replication_id,state,operation_id,last_head,detail,updated_at '
            'FROM replication_runtime').fetchall()
        values = {row[0]: dict(state=row[1], operation_id=row[2],
                               last_head=row[3], detail=row[4], updated_at=row[5])
                  for row in rows}
        return values.get(replication_id) if replication_id else values


def set_replication_runtime(node, replication_id, state, *, operation_id=None,
                            last_head=None, detail=None):
    from datetime import datetime, timezone
    identifier(replication_id)
    require(state in {'idle', 'pending', 'offline', 'rejected', 'conflict', 'error'},
            'Invalid replication runtime state')
    require(operation_id is None or identifier(operation_id),
            'Invalid replication runtime operation')
    require(last_head is None or isinstance(last_head, str)
            and len(last_head) in {40, 64}
            and all(char in '0123456789abcdef' for char in last_head),
            'Invalid replication runtime HEAD')
    require(detail is None or isinstance(detail, str) and len(detail) <= 500,
            'Invalid replication runtime detail')
    updated = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    with database(node, create=True) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS replication_runtime (
            replication_id TEXT PRIMARY KEY, state TEXT NOT NULL,
            operation_id TEXT, last_head TEXT, detail TEXT,
            updated_at TEXT NOT NULL)''')
        db.execute('INSERT OR REPLACE INTO replication_runtime VALUES (?,?,?,?,?,?)',
                   (replication_id, state, operation_id, last_head, detail, updated))
    return dict(state=state, operation_id=operation_id, last_head=last_head,
                detail=detail, updated_at=updated)


def prepare_bundle(node, context, operation_id):
    from spikes.git_transfer import export_bundle, MAX_BUNDLE
    identifier(operation_id)
    canonical = json.dumps(context, sort_keys=True, separators=(',', ':'))
    with database(node, create=True) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT context, head, commit_count, digest, bundle FROM transfers WHERE operation_id=?',
                         (operation_id,)).fetchone()
        if row:
            require(row[0] == canonical, 'Transfer operation belongs to another source or recipient identity')
            payload, head, count = bytes(row[4]), row[1], row[2]
            require(len(payload) <= MAX_BUNDLE and hashlib.sha256(payload).hexdigest() == row[3],
                    'Stored transfer bundle changed; preserve journal for recovery')
        else:
            privacy = context.get('privacy', ['public'])
            require(isinstance(privacy, list), 'Invalid transfer privacy context')
            payload, head, count = export_bundle(
                node, context['project_id'], frozenset(privacy))
            db.execute('INSERT INTO transfers(operation_id,context,head,commit_count,digest,bundle) VALUES (?,?,?,?,?,?)',
                       (operation_id, canonical, head, count, hashlib.sha256(payload).hexdigest(), payload))
        db.commit()
        return payload, head, count


def complete(node, operation_id, digest, receipt=None):
    require(receipt is None or isinstance(receipt, str) and len(receipt) <= 16384,
            'Invalid transfer receipt')
    with database(node) as db:
        require(db is not None, 'Transfer journal missing after remote success')
        with db:
            if receipt is None:
                result = db.execute(
                    'UPDATE transfers SET done=1 WHERE operation_id=? AND digest=?',
                    (operation_id, digest))
            else:
                row = db.execute(
                    'SELECT receipt FROM transfers WHERE operation_id=? AND digest=?',
                    (operation_id, digest)).fetchone()
                require(row is not None and row[0] in {None, receipt},
                        'Transfer receipt changed')
                result = db.execute(
                    'UPDATE transfers SET done=1,receipt=? '
                    'WHERE operation_id=? AND digest=?',
                    (receipt, operation_id, digest))
            require(result.rowcount == 1, 'Transfer completion does not match journal')
