# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Authoritative node-local chat threads, separate from project Git and LLM runs."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

from spikes.metadata import require, timestamp, uuid


PRIVACY = {'public', 'project', 'confidential', 'local-only'}
MAX_MESSAGE = 1024 * 1024
TERMINAL = {'failed', 'cancelled', 'unknown'}


def _text(value, name, limit=200):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and len(value.encode('utf-8')) <= limit
            and not any(char in value for char in '\0\r\n'), f'Invalid {name}')


def _content(value):
    require(isinstance(value, str) and bool(value.strip()), 'Message content is required')
    raw = value.encode('utf-8')
    require(len(raw) <= MAX_MESSAGE, 'Message exceeds 1 MiB')
    return raw, hashlib.sha256(raw).hexdigest()


class ChatThreads:
    """SQLite authority for immutable messages and turn/run reconciliation."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Chat state directory requires owned mode 0700')
        self.path = self.root / 'chat-threads.sqlite'

    def connect(self):
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe chat thread store')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                self._create(db)
            else:
                require(tables == {'schema_info', 'threads', 'messages', 'turns'},
                        'Unknown or incomplete chat schema')
                row = db.execute('SELECT version FROM schema_info').fetchall()
                require(row == [(1,)], 'Unsupported chat schema version')
                self._validate_columns(db)
            db.commit()
            return closing(db)
        except Exception:
            db.close()
            raise

    @staticmethod
    def _create(db):
        db.executescript('''
            CREATE TABLE schema_info(version INTEGER NOT NULL);
            INSERT INTO schema_info VALUES(1);
            CREATE TABLE threads(
                thread_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, user_id TEXT NOT NULL,
                classification TEXT NOT NULL CHECK(classification='brainstorming'),
                status TEXT NOT NULL CHECK(status IN ('active','archived')),
                created_at TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=0),
                next_sequence INTEGER NOT NULL CHECK(next_sequence>=0));
            CREATE TABLE messages(
                message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(thread_id),
                sequence INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content BLOB NOT NULL, content_sha256 TEXT NOT NULL,
                privacy TEXT NOT NULL CHECK(privacy IN ('public','project','confidential','local-only')),
                author_id TEXT NOT NULL, created_at TEXT NOT NULL, supersedes_id TEXT,
                UNIQUE(thread_id,sequence),
                FOREIGN KEY(supersedes_id) REFERENCES messages(message_id));
            CREATE TABLE turns(
                turn_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(thread_id),
                user_message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
                run_id TEXT UNIQUE, assistant_message_id TEXT UNIQUE REFERENCES messages(message_id),
                state TEXT NOT NULL CHECK(state IN
                    ('prepared','run-bound','completed','failed','cancelled','unknown')),
                error TEXT);
        ''')

    @staticmethod
    def _validate_columns(db):
        expected = {
            'schema_info': ['version'],
            'threads': ['thread_id', 'node_id', 'user_id', 'classification', 'status',
                        'created_at', 'revision', 'next_sequence'],
            'messages': ['message_id', 'thread_id', 'sequence', 'role', 'content',
                         'content_sha256', 'privacy', 'author_id', 'created_at', 'supersedes_id'],
            'turns': ['turn_id', 'thread_id', 'user_message_id', 'run_id',
                      'assistant_message_id', 'state', 'error'],
        }
        for table, columns in expected.items():
            actual = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
            require(actual == columns, 'Unknown or incomplete chat schema')

    @staticmethod
    def _owner(db, thread_id, node_id, user_id, *, active=False):
        for value in (thread_id, node_id, user_id):
            uuid(value)
        row = db.execute('SELECT node_id,user_id,status,classification,created_at,revision,'
                         'next_sequence FROM threads WHERE thread_id=?', (thread_id,)).fetchone()
        require(row is not None and row[0] == node_id and row[1] == user_id,
                'Chat thread is unavailable to this owner')
        require(row[2] in {'active', 'archived'} and row[3] == 'brainstorming',
                'Invalid stored chat thread')
        timestamp(row[4])
        require(type(row[5]) is int and row[5] >= 0 and type(row[6]) is int and row[6] >= 0,
                'Invalid stored chat thread counters')
        require(not active or row[2] == 'active', 'Chat thread is archived')
        return row

    def create(self, *, thread_id, node_id, user_id, created_at,
               classification='brainstorming'):
        for value in (thread_id, node_id, user_id):
            uuid(value)
        timestamp(created_at)
        require(classification == 'brainstorming', 'Unsupported chat classification')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,classification,created_at FROM threads '
                             'WHERE thread_id=?', (thread_id,)).fetchone()
            request = (node_id, user_id, classification, created_at)
            if row:
                require(row == request, 'Thread ID belongs to a different request')
            else:
                db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?)',
                           (thread_id, node_id, user_id, classification, 'active',
                            created_at, 0, 0))
            db.commit()
        return self.get(thread_id, node_id, user_id)

    def prepare_turn(self, *, thread_id, node_id, user_id, turn_id, message_id,
                     content, privacy, created_at, checkpoint=lambda stage: None):
        uuid(turn_id); uuid(message_id); timestamp(created_at)
        require(privacy in PRIVACY, 'Unknown message privacy')
        raw, digest = _content(content)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            thread = self._owner(db, thread_id, node_id, user_id, active=True)
            existing = db.execute('SELECT thread_id,user_message_id,state FROM turns '
                                  'WHERE turn_id=?', (turn_id,)).fetchone()
            if existing:
                message = db.execute('SELECT content,privacy,author_id,created_at FROM messages '
                                     'WHERE message_id=?', (message_id,)).fetchone()
                require(existing[:2] == (thread_id, message_id)
                        and message == (raw, privacy, user_id, created_at),
                        'Turn ID belongs to a different request')
            else:
                require(db.execute('SELECT 1 FROM messages WHERE message_id=?',
                                   (message_id,)).fetchone() is None,
                        'Message ID already exists')
                sequence = thread[6] + 1
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                           (message_id, thread_id, sequence, 'user', raw, digest,
                            privacy, user_id, created_at))
                db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?)',
                           (turn_id, thread_id, message_id, None, None, 'prepared', None))
                db.execute('UPDATE threads SET revision=revision+1,next_sequence=? '
                           'WHERE thread_id=?', (sequence, thread_id))
            checkpoint('prepared')
            db.commit()
        return self.get_turn(turn_id, node_id, user_id)

    def bind_run(self, *, turn_id, node_id, user_id, run_id,
                 checkpoint=lambda stage: None):
        uuid(turn_id); uuid(run_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT thread_id,run_id,state FROM turns WHERE turn_id=?',
                             (turn_id,)).fetchone()
            require(row is not None, 'Unknown chat turn')
            self._owner(db, row[0], node_id, user_id, active=True)
            if row[2] == 'prepared':
                require(row[1] is None, 'Prepared turn already has a run')
                db.execute("UPDATE turns SET run_id=?,state='run-bound' WHERE turn_id=?",
                           (run_id, turn_id))
            else:
                require(row[2] in {'run-bound', 'completed'} | TERMINAL and row[1] == run_id,
                        'Turn cannot bind this run')
            checkpoint('run-bound')
            db.commit()
        return self.get_turn(turn_id, node_id, user_id)

    def complete(self, *, turn_id, node_id, user_id, run_id, message_id,
                 content, privacy, created_at, checkpoint=lambda stage: None):
        uuid(turn_id); uuid(run_id); uuid(message_id); timestamp(created_at)
        require(privacy in PRIVACY, 'Unknown message privacy')
        raw, digest = _content(content)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT thread_id,run_id,assistant_message_id,state FROM turns '
                             'WHERE turn_id=?', (turn_id,)).fetchone()
            require(row is not None, 'Unknown chat turn')
            thread = self._owner(db, row[0], node_id, user_id)
            if row[3] == 'completed':
                message = db.execute('SELECT content,privacy,author_id,created_at FROM messages '
                                     'WHERE message_id=?', (message_id,)).fetchone()
                require(row[1] == run_id and row[2] == message_id
                        and message == (raw, privacy, 'backend:' + run_id, created_at),
                        'Completed turn differs from durable result')
            else:
                require(row[3] == 'run-bound' and row[1] == run_id,
                        'Turn is not bound to this run')
                require(db.execute('SELECT 1 FROM messages WHERE message_id=?',
                                   (message_id,)).fetchone() is None,
                        'Message ID already exists')
                sequence = thread[6] + 1
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                           (message_id, row[0], sequence, 'assistant', raw, digest,
                            privacy, 'backend:' + run_id, created_at))
                db.execute("UPDATE turns SET assistant_message_id=?,state='completed' "
                           'WHERE turn_id=?', (message_id, turn_id))
                db.execute('UPDATE threads SET revision=revision+1,next_sequence=? '
                           'WHERE thread_id=?', (sequence, row[0]))
            checkpoint('completed')
            db.commit()
        return self.get_turn(turn_id, node_id, user_id)

    def finish(self, *, turn_id, node_id, user_id, run_id, state, error=None):
        uuid(turn_id); uuid(run_id)
        require(state in TERMINAL, 'Invalid terminal turn state')
        if error is not None:
            _text(error, 'turn error', 4096)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT thread_id,run_id,state,error FROM turns WHERE turn_id=?',
                             (turn_id,)).fetchone()
            require(row is not None, 'Unknown chat turn')
            self._owner(db, row[0], node_id, user_id)
            if row[2] == 'run-bound':
                require(row[1] == run_id, 'Turn is not bound to this run')
                db.execute('UPDATE turns SET state=?,error=? WHERE turn_id=?',
                           (state, error, turn_id))
            else:
                require(row[1:] == (run_id, state, error),
                        'Terminal turn differs from durable result')
            db.commit()
        return self.get_turn(turn_id, node_id, user_id)

    def archive(self, thread_id, node_id, user_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._owner(db, thread_id, node_id, user_id)
            if row[2] == 'active':
                require(db.execute("SELECT 1 FROM turns WHERE thread_id=? AND state IN "
                                   "('prepared','run-bound')", (thread_id,)).fetchone() is None,
                        'Cannot archive a thread with an active turn')
                db.execute("UPDATE threads SET status='archived',revision=revision+1 "
                           'WHERE thread_id=?', (thread_id,))
            db.commit()
        return self.get(thread_id, node_id, user_id)

    def get_turn(self, turn_id, node_id, user_id):
        uuid(turn_id)
        with self.connect() as db:
            row = db.execute('SELECT turn_id,thread_id,user_message_id,run_id,'
                             'assistant_message_id,state,error FROM turns WHERE turn_id=?',
                             (turn_id,)).fetchone()
            require(row is not None, 'Unknown chat turn')
            self._owner(db, row[1], node_id, user_id)
            for value in row[:3]:
                uuid(value)
            if row[3] is not None:
                uuid(row[3])
            if row[4] is not None:
                uuid(row[4])
            require(row[5] in {'prepared', 'run-bound', 'completed'} | TERMINAL,
                    'Invalid stored chat turn')
            return dict(zip(('turn_id', 'thread_id', 'user_message_id', 'run_id',
                             'assistant_message_id', 'state', 'error'), row))

    def get(self, thread_id, node_id, user_id):
        with self.connect() as db:
            row = self._owner(db, thread_id, node_id, user_id)
            messages = []
            for item in db.execute('SELECT message_id,sequence,role,content,content_sha256,'
                                   'privacy,author_id,created_at,supersedes_id FROM messages '
                                   'WHERE thread_id=? ORDER BY sequence', (thread_id,)):
                uuid(item[0])
                require(type(item[1]) is int and item[1] == len(messages) + 1,
                        'Invalid stored chat message sequence')
                require(item[2] in {'user', 'assistant'} and item[5] in PRIVACY,
                        'Invalid stored chat message')
                if item[2] == 'user':
                    uuid(item[6])
                else:
                    require(isinstance(item[6], str) and item[6].startswith('backend:'),
                            'Invalid stored chat message author')
                    uuid(item[6].removeprefix('backend:'))
                timestamp(item[7])
                if item[8] is not None:
                    uuid(item[8])
                try:
                    text = item[3].decode('utf-8')
                except UnicodeError as exc:
                    raise ValueError('Stored chat message is not UTF-8') from exc
                require(hashlib.sha256(item[3]).hexdigest() == item[4],
                        'Stored chat message digest mismatch')
                messages.append(dict(zip(('message_id', 'sequence', 'role', 'content',
                                          'content_sha256', 'privacy', 'author_id',
                                          'created_at', 'supersedes_id'),
                                         item[:3] + (text,) + item[4:])))
            require(row[6] == len(messages), 'Invalid stored chat sequence counter')
            turns = []
            for item in db.execute('SELECT turn_id,user_message_id,run_id,assistant_message_id,'
                                   'state,error FROM turns WHERE thread_id=? ORDER BY rowid',
                                   (thread_id,)):
                for value in item[:2]:
                    uuid(value)
                if item[2] is not None:
                    uuid(item[2])
                if item[3] is not None:
                    uuid(item[3])
                require(item[4] in {'prepared', 'run-bound', 'completed'} | TERMINAL,
                        'Invalid stored chat turn')
                turns.append(dict(zip(('turn_id', 'user_message_id', 'run_id',
                                       'assistant_message_id', 'state', 'error'), item)))
            return dict(thread_id=thread_id, node_id=row[0], user_id=row[1], status=row[2],
                        classification=row[3], created_at=row[4], revision=row[5],
                        messages=messages, turns=turns)

    def list(self, node_id, user_id):
        uuid(node_id); uuid(user_id)
        with self.connect() as db:
            rows = db.execute('SELECT thread_id,created_at,revision,status FROM threads '
                              'WHERE node_id=? AND user_id=? ORDER BY created_at,thread_id',
                              (node_id, user_id)).fetchall()
        result = []
        for thread_id, created_at, revision, status in rows:
            thread = self.get(thread_id, node_id, user_id)
            require(thread['created_at'] == created_at and thread['revision'] == revision
                    and thread['status'] == status, 'Chat thread changed during listing')
            result.append(thread)
        return result
