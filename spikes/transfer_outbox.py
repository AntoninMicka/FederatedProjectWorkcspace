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
                       'done INTEGER NOT NULL DEFAULT 0)')
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


def prepare_bundle(node, context, operation_id):
    from spikes.git_transfer import export_bundle, git_run, MAX_BUNDLE
    from spikes.projects import Projects
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
            ws = Projects(node).workspace(context['project_id'], blocking=False)
            with ws.journal.lock(), ws.journal.connect() as state:
                ws._branch(); ws._read_locked(state)
                require(ws.git.head() == head and not git_run(ws.git, 'status', '--porcelain', '--untracked-files=all').stdout,
                        'Source changed since pending transfer; inspect source and recipient instead of replacing the saved bundle')
        else:
            payload, head, count = export_bundle(node, context['project_id'])
            db.execute('INSERT INTO transfers(operation_id,context,head,commit_count,digest,bundle) VALUES (?,?,?,?,?,?)',
                       (operation_id, canonical, head, count, hashlib.sha256(payload).hexdigest(), payload))
        db.commit()
        return payload, head, count


def complete(node, operation_id, digest):
    with database(node) as db:
        require(db is not None, 'Transfer journal missing after remote success')
        with db:
            result = db.execute('UPDATE transfers SET done=1 WHERE operation_id=? AND digest=?', (operation_id, digest))
            require(result.rowcount == 1, 'Transfer completion does not match journal')
