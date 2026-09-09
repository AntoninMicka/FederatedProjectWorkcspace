"""M0 experiment for controlled repositories; not a production Git sandbox."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess


class Git:
    def __init__(self, root):
        self.root = Path(root)

    def run(self, *args, check=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='M0 Test',
                   GIT_AUTHOR_EMAIL='m0@example.invalid', GIT_COMMITTER_NAME='M0 Test',
                   GIT_COMMITTER_EMAIL='m0@example.invalid', LC_ALL='C')
        return subprocess.run(
            ['git', '-c', f'core.hooksPath={os.devnull}', '-c', 'commit.gpgSign=false',
             '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false', *args],
            cwd=self.root, env=env, capture_output=True, text=True,
            check=check, timeout=30,
        )

    def head(self):
        return self.run('rev-parse', 'HEAD').stdout.strip()

    def commit(self, message):
        self.run('add', '--all')
        self.run('commit', '-m', message)
        return self.head()


class StaleIndex(RuntimeError):
    pass


class Index:
    def __init__(self, path):
        self.path = Path(path)
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, title TEXT NOT NULL);
            ''')

    def rebuild(self, git):
        """Read a fixed commit, validate all rows, then replace the projection atomically."""
        if git.run('ls-files', '-u').stdout:
            raise ValueError('Unresolved merge')
        commit = git.head()
        paths = git.run('ls-tree', '-r', '--name-only', '-z', commit, '--', 'registries/').stdout
        rows = []
        ids = set()
        for path in filter(None, paths.split('\0')):
            if not path.endswith('.json'):
                raise ValueError('Expected JSON registry entity')
            data = json.loads(git.run('show', f'{commit}:{path}').stdout)
            if not isinstance(data, dict):
                raise ValueError('Expected object')
            entity_id, title = data.get('id'), data.get('title')
            if not isinstance(entity_id, str) or not entity_id or entity_id in ids:
                raise ValueError('Missing or duplicate ID')
            if not isinstance(title, str) or not title.strip():
                raise ValueError('Invalid title')
            ids.add(entity_id)
            rows.append((entity_id, title))
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM entities')
            db.executemany('INSERT INTO entities VALUES (?, ?)', rows)
            db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (commit,))
        return commit

    def read(self, git):
        with sqlite3.connect(self.path) as db:
            state = db.execute('SELECT commit_id FROM state WHERE singleton=1').fetchone()
            if state is None or state[0] != git.head():
                raise StaleIndex('Index must be rebuilt from current HEAD')
            return db.execute('SELECT id, title FROM entities ORDER BY id').fetchall()
