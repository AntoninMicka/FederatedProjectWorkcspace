# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""M0 experiment for controlled repositories; not a production Git sandbox."""
from contextlib import closing
import json
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


def projection(files, entities, commit):
    """Describe validated metadata and its content location without parsing source bytes."""
    paths = {}
    for path in sorted(files):
        group, category, name = path.split('/')
        if group == 'registries':
            paths[name[:-5]] = path
        elif name != 'metadata.json':
            paths[category] = path
    return dict(commit_id=commit,
                entities={id_: dict(metadata=meta, path=paths[id_])
                          for id_, meta in sorted(entities.items())},
                relations=[dict(source_id=id_, ordinal=ordinal, **relation)
                           for id_, meta in sorted(entities.items())
                           for ordinal, relation in enumerate(meta.get('relations', []))])


class Index:
    VERSION = 2
    FIELDS = ('schema_version', 'id', 'title', 'kind', 'privacy', 'provenance', 'author_id', 'created_at',
              'description', 'source_url', 'status', 'body')
    IMPORT_FIELDS = ('imported_at', 'imported_by', 'content_sha256', 'source_author',
                     'source_created_at', 'source_revision')
    SCHEMA = (
        '''CREATE TABLE entities (
            schema_version INTEGER NOT NULL, id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
            privacy TEXT NOT NULL, provenance TEXT NOT NULL, author_id TEXT NOT NULL,
            created_at TEXT NOT NULL, description TEXT, source_url TEXT,
            status TEXT, body TEXT, path TEXT NOT NULL, metadata TEXT NOT NULL)''',
        '''CREATE TABLE imports (
            entity_id TEXT PRIMARY KEY REFERENCES entities(id), imported_at TEXT NOT NULL,
            imported_by TEXT NOT NULL, content_sha256 TEXT NOT NULL, source_author TEXT,
            source_created_at TEXT, source_revision TEXT, importer_name TEXT NOT NULL,
            importer_version TEXT)''',
        '''CREATE TABLE tags (entity_id TEXT NOT NULL REFERENCES entities(id),
            ordinal INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY(entity_id, ordinal))''',
        '''CREATE TABLE relations (
            source_id TEXT NOT NULL REFERENCES entities(id), ordinal INTEGER NOT NULL,
            type TEXT NOT NULL, target_id TEXT NOT NULL REFERENCES entities(id),
            PRIMARY KEY(source_id, ordinal))''',
        'CREATE INDEX relations_target ON relations(target_id, type)',
        'CREATE INDEX relations_source_type ON relations(source_id, type)',
        'CREATE INDEX tags_value ON tags(tag)',
    )

    def __init__(self, path):
        self.path = Path(path)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            version = self._version(db)
            if version == 0:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                require(tables <= {'state', 'entities'}, 'Unrecognized legacy index; index retained')
                for table, expected in (('entities', ['id', 'title']), ('state', ['singleton', 'commit_id'])):
                    if table in tables:
                        columns = [row[1] for row in db.execute('PRAGMA table_info(' + table + ')')]
                        require(columns == expected, 'Unrecognized legacy index; index retained')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, title TEXT NOT NULL);
                ''')
            elif version == 1:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                require(tables == {'state', 'entities', 'tags', 'relations'},
                        'Unrecognized v1 index; index retained')
                expected = {
                    'state': ['singleton', 'commit_id'],
                    'entities': ['id', 'title', 'kind', 'privacy', 'provenance', 'author_id', 'created_at',
                                 'description', 'source_url', 'status', 'body', 'path', 'metadata'],
                    'tags': ['entity_id', 'ordinal', 'tag'],
                    'relations': ['source_id', 'ordinal', 'type', 'target_id'],
                }
                for table, columns in expected.items():
                    require([row[1] for row in db.execute('PRAGMA table_info(' + table + ')')] == columns,
                            'Unrecognized v1 index; index retained')

    def _version(self, db):
        version = db.execute('PRAGMA user_version').fetchone()[0]
        require(version in {0, 1, self.VERSION}, 'Unsupported index schema version; index retained')
        return version

    def rebuild(self, git, *, checkpoint=lambda stage: None):
        """Read a fixed commit, validate all rows, then replace the projection atomically."""
        if git.run('ls-files', '-u').stdout:
            raise ValueError('Unresolved merge')
        commit = git.head()
        files = git.snapshot(commit)
        entities = validate_snapshot(files)
        view = projection(files, entities, commit)
        rows = [tuple(item['metadata'].get(key) for key in self.FIELDS) +
                (item['path'], json.dumps(item['metadata'], ensure_ascii=False, sort_keys=True))
                for item in view['entities'].values()]
        imports = []
        for id_, meta in entities.items():
            if 'import' not in meta:
                continue
            imported = meta['import']; importer = imported['importer']
            imports.append((id_, *(imported.get(key) for key in self.IMPORT_FIELDS),
                            importer['name'], importer.get('version')))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            if self._version(db) != self.VERSION:
                if self._version(db) == 0:
                    columns = [row[1] for row in db.execute('PRAGMA table_info(entities)')]
                    require(columns == ['id', 'title'], 'Unrecognized legacy index; index retained')
                db.execute('DROP TABLE IF EXISTS relations')
                db.execute('DROP TABLE IF EXISTS tags')
                db.execute('DROP TABLE entities')
                for statement in self.SCHEMA:
                    db.execute(statement)
                db.execute(f'PRAGMA user_version={self.VERSION}')
            db.execute('DELETE FROM imports')
            db.execute('DELETE FROM relations')
            db.execute('DELETE FROM tags')
            db.execute('DELETE FROM entities')
            checkpoint('index-cleared')
            db.executemany('INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
            db.executemany('INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', imports)
            checkpoint('index-entities')
            db.executemany('INSERT INTO tags VALUES (?, ?, ?)',
                           [(id_, n, tag) for id_, meta in entities.items()
                            for n, tag in enumerate(meta.get('tags', []))])
            db.executemany('INSERT INTO relations VALUES (?, ?, ?, ?)',
                           [(edge['source_id'], edge['ordinal'], edge['type'], edge['target_id'])
                            for edge in view['relations']])
            checkpoint('index-relations')
            db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (commit,))
            checkpoint('index-state')
            if git.head() != commit:
                raise StaleIndex('HEAD changed during index rebuild')
        checkpoint('index-published')
        return commit

    def _read(self, git, query):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN')
            if self._version(db) == 0:
                raise StaleIndex('Legacy index must be rebuilt from current HEAD')
            if self._version(db) == 1:
                raise StaleIndex('V1 index must be rebuilt from current HEAD')
            state = db.execute('SELECT commit_id FROM state WHERE singleton=1').fetchone()
            if state is None or state[0] != git.head():
                raise StaleIndex('Index must be rebuilt from current HEAD')
            result = query(db, state[0])
            if state[0] != git.head():
                raise StaleIndex('HEAD changed while reading index')
            return result

    def read(self, git):
        """Retain the original id/title API for existing consumers."""
        return self._read(git, lambda db, commit: db.execute(
            'SELECT id, title FROM entities ORDER BY id').fetchall())

    @staticmethod
    def _relations(db, where='', params=()):
        rows = db.execute('SELECT source_id, ordinal, type, target_id FROM relations ' +
                          where + ' ORDER BY source_id, ordinal', params).fetchall()
        return [dict(source_id=source, ordinal=n, type=type_, target_id=target)
                for source, n, type_, target in rows]

    def read_projection(self, git):
        def query(db, commit):
            edges = self._relations(db)
            relations, tags = {}, {}
            for edge in edges:
                relations.setdefault(edge['source_id'], []).append(
                    dict(type=edge['type'], target_id=edge['target_id']))
            for id_, tag in db.execute('SELECT entity_id, tag FROM tags ORDER BY entity_id, ordinal'):
                tags.setdefault(id_, []).append(tag)
            entities = {}
            imported = {}
            for row in db.execute('SELECT entity_id, ' + ', '.join(self.IMPORT_FIELDS) +
                                  ', importer_name, importer_version FROM imports ORDER BY entity_id'):
                block = {key: value for key, value in zip(self.IMPORT_FIELDS, row[1:]) if value is not None}
                block['importer'] = {'name': row[-2]}
                if row[-1] is not None:
                    block['importer']['version'] = row[-1]
                imported[row[0]] = block
            for row in db.execute('SELECT ' + ', '.join(self.FIELDS) +
                                  ', path, metadata FROM entities ORDER BY id'):
                path, canonical = row[-2], json.loads(row[-1])
                meta = {key: value for key, value in zip(self.FIELDS, row)
                        if key in canonical}
                id_ = meta['id']
                if 'file' in canonical:
                    meta['file'] = path.rsplit('/', 1)[-1]
                if 'tags' in canonical:
                    meta['tags'] = tags.get(id_, [])
                if 'relations' in canonical:
                    meta['relations'] = relations.get(id_, [])
                if 'import' in canonical:
                    require(id_ in imported, 'Index differs from stored metadata')
                    meta['import'] = imported[id_]
                require(meta == canonical and
                        ('tags' in canonical or id_ not in tags) and
                        ('relations' in canonical or id_ not in relations) and
                        ('import' in canonical or id_ not in imported),
                        'Index differs from stored metadata')
                entities[id_] = dict(metadata=meta, path=path)
            return dict(commit_id=commit, entities=entities, relations=edges)
        return self._read(git, query)

    def read_relations(self, git, entity_id, *, direction='outgoing', relation_type=None):
        require(direction in {'outgoing', 'incoming'}, 'Invalid relation direction')
        column = 'source_id' if direction == 'outgoing' else 'target_id'
        where, params = 'WHERE ' + column + '=?', [entity_id]
        if relation_type is not None:
            require(isinstance(relation_type, str), 'Invalid relation type filter')
            where += ' AND type=?'
            params.append(relation_type)
        return self._read(git, lambda db, commit: dict(
            commit_id=commit, relations=self._relations(db, where, params)))
