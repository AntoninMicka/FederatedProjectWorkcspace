# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""M0 experiment for controlled repositories; not a production Git sandbox."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from spikes.metadata import MAX_FILE, MAX_SNAPSHOT, require, validate_snapshot


class Git:
    def __init__(self, root, *, deadline=None):
        self.root = Path(root)
        self.deadline = deadline

    def run(self, *args, check=True, binary=False, env_extra=None, input=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='M0 Test',
                   GIT_AUTHOR_EMAIL='m0@example.invalid', GIT_COMMITTER_NAME='M0 Test',
                   GIT_COMMITTER_EMAIL='m0@example.invalid', LC_ALL='C')
        env.update(env_extra or {})
        timeout = 30 if self.deadline is None else min(30, self.deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('Operation deadline exceeded')
        return subprocess.run(
            ['git', '-c', f'core.hooksPath={os.devnull}', '-c', 'commit.gpgSign=false',
             '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false', *args],
            cwd=self.root, env=env, capture_output=True, text=not binary,
            check=check, timeout=timeout, input=input,
        )

    def head(self):
        return self.run('rev-parse', 'HEAD').stdout.strip()

    def commit(self, message):
        self.run('add', '--all')
        self.run('commit', '-m', message)
        return self.head()

    def snapshot(self, commit):
        """Read artifact/registry bytes from a fixed commit or tree under PoC limits."""
        entries = self.run('ls-tree', '-r', '-z', commit, '--', 'artifacts/', 'registries/').stdout
        files = {}
        total = 0
        for entry in filter(None, entries.split('\0')):
            info, path = entry.split('\t', 1)
            mode, kind, oid = info.split()
            require(mode in {'100644', '100755'} and kind == 'blob', 'Non-regular Git entry')
            size = int(self.run('cat-file', '-s', oid).stdout)
            total += size
            require(size <= MAX_FILE and total <= MAX_SNAPSHOT and len(files) < 10000, 'Snapshot exceeds limits')
            files[path] = self.run('cat-file', 'blob', oid, binary=True).stdout
        return files


class StaleIndex(RuntimeError):
    pass


class Index:
    def __init__(self, path):
        self.path = Path(path)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, title TEXT NOT NULL);
            ''')

    def rebuild(self, git):
        """Read a fixed commit, validate all rows, then replace the projection atomically."""
        if git.run('ls-files', '-u').stdout:
            raise ValueError('Unresolved merge')
        commit = git.head()
        files = git.snapshot(commit)
        entities = validate_snapshot(files)
        rows = [(meta['id'], meta['title']) for meta in entities.values()]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM entities')
            db.executemany('INSERT INTO entities VALUES (?, ?)', rows)
            db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (commit,))
        return commit

    def read(self, git):
        with closing(sqlite3.connect(self.path)) as db, db:
            state = db.execute('SELECT commit_id FROM state WHERE singleton=1').fetchone()
            if state is None or state[0] != git.head():
                raise StaleIndex('Index must be rebuilt from current HEAD')
            return db.execute('SELECT id, title FROM entities ORDER BY id').fetchall()
