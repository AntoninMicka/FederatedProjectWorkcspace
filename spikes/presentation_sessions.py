# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Crash-safe public presentation histories materialized as project documents."""
from contextlib import closing
from datetime import datetime, timezone
import copy
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.journal import sync_dir
from spikes.markdown_documents import MAX_EDITOR
from spikes.metadata import require, timestamp, uuid


PREFIX = '```fpw-presentation-session-v1\n'
MAX_PAGES = 1000
PUBLIC_FIELDS = frozenset({'title', 'body', 'bullets', 'background', 'foreground', 'wallpaper',
                           'layout', 'column_break', 'closing', 'contacts', 'qr'})
GENERATED_SLIDE_IDS = frozenset({'presentation-closing'})


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def validate_slide_id(value):
    """Accept persisted deck UUIDs and the one bounded locally generated slide ID."""
    if value not in GENERATED_SLIDE_IDS:
        uuid(value)
    return value


def validate_snapshot(value):
    require(isinstance(value, dict) and value.keys() == {'shown_at', 'slide_id', 'ratio', 'content'},
            'Neplatný veřejný snapshot relace.')
    timestamp(value['shown_at'], 'shown_at')
    validate_slide_id(value['slide_id'])
    require(value['ratio'] in {'16:9', '4:3'}, 'Neplatný poměr stran snapshotu.')
    content = value['content']
    require(isinstance(content, dict) and set(content) <= PUBLIC_FIELDS
            and {'title', 'bullets', 'background', 'foreground', 'wallpaper'} <= set(content),
            'Snapshot obsahuje nepovolená nebo chybějící veřejná pole.')
    require(isinstance(content['title'], str) and isinstance(content['bullets'], list)
            and all(isinstance(item, str) for item in content['bullets']),
            'Neplatný veřejný obsah snapshotu.')
    require('body' not in content or isinstance(content['body'], str),
            'Neplatný veřejný text snapshotu.')
    for key in ('background', 'foreground', 'wallpaper'):
        require(isinstance(content[key], str), 'Neplatný vzhled snapshotu.')
    return value


def validate_session(value):
    required = {'version', 'session_id', 'source_project_id', 'source_artifact_id',
                'source_revision', 'title', 'started_at', 'ended_at', 'outcome', 'pages'}
    require(isinstance(value, dict) and value.keys() == required and value['version'] == 1,
            'Neplatný formát záznamu relace.')
    for key in ('session_id', 'source_project_id', 'source_artifact_id'):
        uuid(value[key])
    require(isinstance(value['source_revision'], str)
            and re.fullmatch(r'[0-9a-f]{40,64}:[0-9a-f-]{36}', value['source_revision']),
            'Neplatná zdrojová revize relace.')
    require(value['source_revision'].endswith(':' + value['source_artifact_id']),
            'Revize relace neodpovídá zdrojovému decku.')
    require(isinstance(value['title'], str) and 0 < len(value['title'].strip()) <= 200,
            'Neplatný název relace.')
    timestamp(value['started_at'], 'started_at')
    timestamp(value['ended_at'], 'ended_at')
    require(value['outcome'] in {'completed', 'interrupted'}, 'Neplatný stav relace.')
    require(isinstance(value['pages'], list) and len(value['pages']) <= MAX_PAGES,
            'Relace má příliš mnoho snapshotů.')
    for page in value['pages']:
        validate_snapshot(page)
    return value


def encode_session(value):
    value = validate_session(copy.deepcopy(value))
    result = PREFIX + json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n```\n'
    require(len(result.encode()) < MAX_EDITOR, 'Záznam relace překračuje limit 1 MiB.')
    return result


def is_session_document(body):
    return isinstance(body, str) and body.startswith(PREFIX)


def decode_session(body):
    require(isinstance(body, str) and body.startswith(PREFIX) and body.endswith('\n```\n')
            and len(body.encode()) < MAX_EDITOR, 'Neplatný dokument relace.')
    try:
        value = json.loads(body[len(PREFIX):-5])
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Neplatný JSON záznamu relace.') from exc
    return validate_session(value)


class PresentationSessions:
    """SQLite is authoritative only until the exact public history reaches Git."""

    def __init__(self, node_path):
        self.node_path = node_path
        self.artifacts = Artifacts(node_path)
        self.path = Path(node_path).resolve().with_suffix('.presentation-sessions.sqlite3')

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            require(not self.path.is_symlink(), 'Journal relací nesmí být symbolický odkaz.')
        else:
            os.close(fd)
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('CREATE TABLE IF NOT EXISTS sessions ('
                   'session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, '
                   'source_artifact_id TEXT NOT NULL, source_revision TEXT NOT NULL, title TEXT NOT NULL, '
                   'started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT, pages TEXT NOT NULL, '
                   'operation_id TEXT NOT NULL, base_head TEXT, materialized INTEGER NOT NULL DEFAULT 0)')
        return db

    def start(self, project_id, source_artifact_id, source_revision, title):
        for value in (project_id, source_artifact_id):
            uuid(value)
        require(source_revision.endswith(':' + source_artifact_id), 'Neplatná revize spuštěného decku.')
        require(isinstance(title, str) and title.strip(), 'Prezentace nemá název.')
        self.recover(project_id)
        row = dict(session_id=str(uuid4()), project_id=project_id, artifact_id=str(uuid4()),
                   source_artifact_id=source_artifact_id, source_revision=source_revision,
                   title=title.strip(), started_at=utc_now(), operation_id=str(uuid4()))
        with closing(self._connect()) as db, db:
            db.execute('INSERT INTO sessions '
                       '(session_id,project_id,artifact_id,source_artifact_id,source_revision,title,'
                       'started_at,pages,operation_id) VALUES (?,?,?,?,?,?,?,?,?)',
                       (row['session_id'], row['project_id'], row['artifact_id'],
                        row['source_artifact_id'], row['source_revision'], row['title'],
                        row['started_at'], '[]', row['operation_id']))
        sync_dir(self.path.parent)
        return row['session_id']

    def record(self, session_id, slide_id, ratio, content, *, shown_at=None):
        uuid(session_id); validate_slide_id(slide_id)
        page = validate_snapshot(dict(shown_at=shown_at or utc_now(), slide_id=slide_id,
                                      ratio=ratio, content=copy.deepcopy(content)))
        with closing(self._connect()) as db, db:
            row = db.execute('SELECT pages,ended_at FROM sessions WHERE session_id=?',
                             (session_id,)).fetchone()
            require(row is not None and row[1] is None, 'Relace již není aktivní.')
            pages = json.loads(row[0])
            require(len(pages) < MAX_PAGES, 'Relace dosáhla limitu 1000 snapshotů.')
            pages.append(page)
            encoded = json.dumps(pages, ensure_ascii=False, separators=(',', ':'))
            require(len(encoded.encode()) < MAX_EDITOR // 2, 'Historie relace je příliš velká.')
            db.execute('UPDATE sessions SET pages=? WHERE session_id=?', (encoded, session_id))
        return page

    def _row(self, row):
        keys = ('session_id', 'project_id', 'artifact_id', 'source_artifact_id',
                'source_revision', 'title', 'started_at', 'ended_at', 'outcome', 'pages',
                'operation_id', 'base_head', 'materialized')
        return dict(zip(keys, row))

    def _materialize(self, session_id, outcome):
        require(outcome in {'completed', 'interrupted'}, 'Neplatný stav ukončení relace.')
        with closing(self._connect()) as db, db:
            raw = db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            require(raw is not None, 'Relace neexistuje.')
            row = self._row(raw)
            if row['materialized']:
                return row['artifact_id']
            ended_at = row['ended_at'] or utc_now()
            actual_outcome = row['outcome'] or outcome
            base_head = row['base_head']
            if base_head is None:
                base_head = self.artifacts.open(row['project_id'])['commit_id']
            db.execute('UPDATE sessions SET ended_at=?,outcome=?,base_head=? WHERE session_id=?',
                       (ended_at, actual_outcome, base_head, session_id))
            row.update(ended_at=ended_at, outcome=actual_outcome, base_head=base_head)
        session = dict(version=1, session_id=row['session_id'],
                       source_project_id=row['project_id'],
                       source_artifact_id=row['source_artifact_id'],
                       source_revision=row['source_revision'], title=row['title'],
                       started_at=row['started_at'], ended_at=row['ended_at'],
                       outcome=row['outcome'], pages=json.loads(row['pages']))
        request = dict(project_id=row['project_id'], artifact_id=row['artifact_id'],
                       base_head=row['base_head'], title='Relace – ' + row['title'],
                       body=encode_session(session), new=True)
        self.artifacts.save(request, row['operation_id'])
        with closing(self._connect()) as db, db:
            db.execute('UPDATE sessions SET materialized=1 WHERE session_id=?', (session_id,))
        return row['artifact_id']

    def finish(self, session_id):
        return self._materialize(session_id, 'completed')

    def recover(self, project_id=None):
        if not self.path.exists():
            return []
        require(not self.path.is_symlink(), 'Journal relací nesmí být symbolický odkaz.')
        with closing(self._connect()) as db:
            if project_id is None:
                rows = db.execute('SELECT session_id FROM sessions WHERE materialized=0').fetchall()
            else:
                uuid(project_id)
                rows = db.execute('SELECT session_id FROM sessions '
                                  'WHERE materialized=0 AND project_id=?', (project_id,)).fetchall()
        completed = []
        for (session_id,) in rows:
            completed.append(self._materialize(session_id, 'interrupted'))
        return completed
