# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real Git/SQLite projection, transactional migration and application recovery."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.source_import import Sources, request_from_file
from spikes.storage import Git, Index, StaleIndex
from spikes.workspace import PendingOperation, Workspace
from tests.fixtures import ENTITY, OTHER, encoded, markdown, metadata


BOUNDARIES = ('index-cleared', 'index-entities', 'index-relations',
              'index-state', 'index-published')
IDENTITY = dict(author_name='Local author', author_email='author@local.invalid', message='Graph update')


def graph(title='Document'):
    doc = metadata(title, tags=['Žluťoučký', 'same', 'same'], description='',
                   source_url='https://example.invalid/source',
                   relations=[{'type': 'custom type', 'target_id': OTHER},
                              {'type': 'custom type', 'target_id': OTHER},
                              {'type': 'references', 'target_id': ENTITY}])
    decision = metadata('Decision', OTHER)
    decision.update(kind='decisions', status='accepted', body='Decision body',
                    privacy='confidential', relations=[{'type': 'depends_on', 'target_id': ENTITY}])
    return {f'artifacts/{ENTITY}/original.md': markdown(doc),
            f'registries/decisions/{OTHER}.json': encoded(decision)}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'project'
        self.root.mkdir()
        self.git = Git(self.root)
        self.git.run('init', '--initial-branch=main')
        self.write(graph())
        self.original = self.git.commit('Original graph')
        self.index = Index(self.base/'index.sqlite')
        self.index.rebuild(self.git)

    def write(self, files):
        for path, raw in files.items():
            dest = self.root/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)

    def expected(self):
        files = self.git.snapshot(self.git.head())
        metas = validate_snapshot(files)
        return dict(commit_id=self.git.head(), entities={
            ENTITY: dict(metadata=metas[ENTITY], path=f'artifacts/{ENTITY}/original.md'),
            OTHER: dict(metadata=metas[OTHER], path=f'registries/decisions/{OTHER}.json')},
            relations=[dict(source_id=ENTITY, ordinal=0, type='custom type', target_id=OTHER),
                       dict(source_id=ENTITY, ordinal=1, type='custom type', target_id=OTHER),
                       dict(source_id=ENTITY, ordinal=2, type='references', target_id=ENTITY),
                       dict(source_id=OTHER, ordinal=0, type='depends_on', target_id=ENTITY)])

    def dump(self):
        with closing(sqlite3.connect(self.index.path)) as db:
            return list(db.iterdump()), db.execute('PRAGMA user_version').fetchone()[0]

    def legacy(self):
        self.index.path.unlink()
        with closing(sqlite3.connect(self.index.path)) as db, db:
            db.execute('CREATE TABLE entities(id TEXT PRIMARY KEY, title TEXT NOT NULL)')
            db.execute('CREATE TABLE state(singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_id TEXT NOT NULL)')
            db.execute('INSERT INTO state VALUES (1, ?)', (self.original,))
            db.executemany('INSERT INTO entities VALUES (?, ?)', [(ENTITY, 'Document'), (OTHER, 'Decision')])

    def test_metadata_paths_relations_tags_and_legacy_api(self):
        view = self.index.read_projection(self.git)
        self.assertEqual(view, self.expected())
        self.assertEqual(self.index.read(self.git), [(ENTITY, 'Document'), (OTHER, 'Decision')])
        self.assertEqual(view['entities'][ENTITY]['path'], f'artifacts/{ENTITY}/original.md')
        self.assertEqual(view['entities'][OTHER]['path'], f'registries/decisions/{OTHER}.json')
        self.assertNotIn('tags', view['entities'][OTHER]['metadata'])
        outgoing = self.index.read_relations(self.git, ENTITY, relation_type='custom type')
        self.assertEqual(outgoing['commit_id'], self.original)
        self.assertEqual([edge['ordinal'] for edge in outgoing['relations']], [0, 1])
        incoming = self.index.read_relations(self.git, ENTITY, direction='incoming')
        self.assertEqual([edge['source_id'] for edge in incoming['relations']], [ENTITY, OTHER])
        self.assertEqual(self.index.read_relations(self.git, OTHER, relation_type="' OR 1=1 --")['relations'], [])
        with closing(sqlite3.connect(self.index.path)) as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT tag FROM tags WHERE entity_id=? ORDER BY ordinal', (ENTITY,)).fetchall(),
                             [('Žluťoučký',), ('same',), ('same',)])
            self.assertEqual(db.execute('SELECT kind, privacy, status, body FROM entities WHERE id=?', (OTHER,)).fetchone(),
                             ('decisions', 'confidential', 'accepted', 'Decision body'))
            db.execute('PRAGMA foreign_keys=ON')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO relations VALUES (?, ?, ?, ?)', (ENTITY, 3, 'references', str(uuid4())))
        with self.assertRaises(ValidationError):
            self.index.read_relations(self.git, ENTITY, direction='both')

    def test_invalid_snapshot_and_head_change_retain_entire_previous_projection(self):
        before = self.dump()
        files = graph('Invalid graph')
        decision = json.loads(files[f'registries/decisions/{OTHER}.json'])
        decision['relations'][0]['target_id'] = str(uuid4())
        files[f'registries/decisions/{OTHER}.json'] = encoded(decision)
        self.write(files)
        self.git.commit('Dangling relation')
        with self.assertRaisesRegex(ValidationError, 'Dangling'):
            self.index.rebuild(self.git)
        self.assertEqual(self.dump(), before)
        with self.assertRaises(StaleIndex):
            self.index.read_projection(self.git)
        with self.assertRaises(StaleIndex):
            self.index.read_relations(self.git, ENTITY)
        self.write(graph('Valid update'))
        updated = self.git.commit('Valid graph')
        with patch.object(self.git, 'head', side_effect=[updated, self.original]):
            with self.assertRaises(StaleIndex):
                self.index.rebuild(self.git)
        self.assertEqual(self.dump(), before)
        self.index.rebuild(self.git)
        for query in (self.index.read, self.index.read_projection,
                      lambda git: self.index.read_relations(git, ENTITY)):
            with patch.object(self.git, 'head', side_effect=[updated, self.original]):
                with self.assertRaises(StaleIndex):
                    query(self.git)

    def test_legacy_requires_rebuild_and_future_version_is_not_overwritten(self):
        self.legacy()
        reopened = Index(self.index.path)
        with self.assertRaises(StaleIndex):
            reopened.read(self.git)
        self.assertEqual(self.dump()[1], 0)
        reopened.rebuild(self.git)
        self.assertEqual(reopened.read_projection(self.git), self.expected())
        with closing(sqlite3.connect(self.index.path)) as db:
            db.execute('PRAGMA user_version=77')
        before = self.dump()
        with self.assertRaisesRegex(ValidationError, 'Unsupported index'):
            Index(self.index.path)
        with self.assertRaises(ValidationError):
            reopened.rebuild(self.git)
        self.assertEqual(self.dump(), before)

    def test_unrecognized_legacy_database_is_not_initialized_as_index(self):
        self.index.path.unlink()
        with closing(sqlite3.connect(self.index.path)) as db, db:
            db.execute('CREATE TABLE operations(record TEXT NOT NULL)')
            db.execute("INSERT INTO operations VALUES ('unfinished operation')")
        before = self.dump()
        with self.assertRaisesRegex(ValidationError, 'Unrecognized legacy'):
            Index(self.index.path)
        self.assertEqual(self.dump(), before)
        self.legacy()
        with closing(sqlite3.connect(self.index.path)) as db:
            db.execute('ALTER TABLE entities ADD COLUMN unexpected TEXT')
        before = self.dump()
        with self.assertRaises(ValidationError):
            Index(self.index.path)
        self.assertEqual(self.dump(), before)

    def test_process_crashes_rollback_migration_and_replacement(self):
        self.write(graph('Updated'))
        self.git.commit('Updated graph')
        child = '''
import os,sys
from spikes.storage import Git,Index
def checkpoint(stage):
    if stage == sys.argv[3]: os._exit(73)
Index(sys.argv[2]).rebuild(Git(sys.argv[1]), checkpoint=checkpoint)
'''
        for legacy in (True, False):
            for stage in BOUNDARIES:
                with self.subTest(legacy=legacy, stage=stage):
                    self.legacy()
                    if not legacy:
                        self.git.run('reset', '--hard', self.original)
                        self.index.rebuild(self.git)
                        self.write(graph('Updated'))
                        self.git.commit('Updated graph')
                    before = self.dump()
                    result = subprocess.run([sys.executable, '-c', child, str(self.root),
                                             str(self.index.path), stage], capture_output=True,
                                            text=True, timeout=15)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    if stage != 'index-published':
                        self.assertEqual(self.dump(), before)
                    else:
                        self.assertEqual(self.index.read_projection(self.git), self.expected())
                    reopened = Index(self.index.path)
                    reopened.rebuild(self.git)
                    self.assertEqual(reopened.read_projection(self.git), self.expected())
                    self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    def test_sql_readers_never_see_half_replaced_graph(self):
        before = self.dump()
        self.write(graph('New title'))
        self.git.commit('New title')
        seen = []
        def checkpoint(stage):
            if stage != 'index-published':
                self.assertEqual(self.dump(), before)
                seen.append(stage)
        self.index.rebuild(self.git, checkpoint=checkpoint)
        self.assertEqual(seen, list(BOUNDARIES[:-1]))
        self.assertEqual(self.index.read_projection(self.git), self.expected())


class WorkspaceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base/'node.json'
        self.root = self.base/'project'
        self.id = ProjectCreation(self.node).create('Graph', str(self.root), str(uuid4()))['id']
        self.service = Artifacts(self.node)
        self.git = Git(self.root)
        self.ws = self.service.workspace(self.id)

    def assert_current(self):
        files = self.git.snapshot(self.git.head())
        view = self.ws.read_projection()
        metas = validate_snapshot(files)
        self.assertEqual(view['commit_id'], self.git.head())
        self.assertEqual({id_: item['metadata'] for id_, item in view['entities'].items()}, metas)
        for id_, item in view['entities'].items():
            self.assertIn(item['path'], files)
            if item['path'].startswith('artifacts/'):
                self.assertEqual(item['path'].split('/')[1], id_)
            else:
                self.assertTrue(item['path'].endswith('/'+id_+'.json'))
        self.assertEqual(len(view['relations']), sum(len(meta.get('relations', [])) for meta in metas.values()))
        return view

    def test_native_import_metadata_rename_delete_and_missing_index(self):
        request = dict(project_id=self.id, artifact_id=ENTITY, base_head=self.git.head(),
                       title='Document', body='Original\n', new=True,
                       metadata={'description': 'Description', 'tags': ['one', 'two']})
        self.service.save(request, str(uuid4()))
        source = self.base/'external.md'
        raw = b'---\r\nexternal: yes\r\n---\r\nOriginal\r\n'
        source.write_bytes(raw)
        imported = request_from_file(self.id, self.git.head(), str(source), 'Source', '', [], 'local-only')
        Sources(self.node).import_source(imported, str(uuid4()))
        meta = metadata('Decision', OTHER)
        meta.update(kind='decisions', status='proposed', body='Body',
                    relations=[{'type': 'references', 'target_id': ENTITY},
                               {'type': 'cites', 'target_id': imported['artifact_id']}])
        path = self.root/f'registries/decisions/{OTHER}.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(encoded(meta))
        self.git.commit('Relations to document and imported source')
        original = self.assert_current()
        rename = dict(request, base_head=self.git.head(), new=False, filename='renamed.md',
                      metadata={'description': '', 'tags': []})
        self.service.save(rename, str(uuid4()))
        renamed = self.assert_current()
        self.assertEqual(renamed['entities'][ENTITY]['path'], f'artifacts/{ENTITY}/renamed.md')
        self.assertEqual(renamed['relations'], original['relations'])
        self.assertEqual(renamed['entities'][ENTITY]['metadata']['tags'], [])
        self.assertEqual(renamed['entities'][imported['artifact_id']]['metadata']['privacy'], 'local-only')
        with self.assertRaises(ValidationError):
            self.service.delete(dict(project_id=self.id, artifact_id=ENTITY, base_head=self.git.head()), str(uuid4()))
        meta['relations'] = meta['relations'][1:]
        path.write_bytes(encoded(meta))
        self.git.commit('Remove incoming document relation')
        self.service.delete(dict(project_id=self.id, artifact_id=ENTITY, base_head=self.git.head()), str(uuid4()))
        self.ws.index.path.unlink()
        self.ws = self.service.workspace(self.id)
        final = self.assert_current()
        self.assertNotIn(ENTITY, final['entities'])
        self.assertEqual(len(final['relations']), 1)
        self.assertEqual(self.ws.read_relations(imported['artifact_id'], direction='incoming')['relations'], final['relations'])
        self.assertEqual(self.git.snapshot(self.git.head())[final['entities'][imported['artifact_id']]['path']], raw)
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(Projects(self.node).open(self.id)['commit_id'], final['commit_id'])
        self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    def test_pending_blocks_graph_reads_and_process_recovery_rebuilds(self):
        child = '''
import os,sys
from spikes.workspace import Workspace
from tests.test_index_projection import graph,IDENTITY
def checkpoint(stage):
    if stage == sys.argv[3]: os._exit(73)
Workspace(sys.argv[1],sys.argv[2]).apply(graph(), checkpoint=checkpoint, **IDENTITY)
'''
        baseline = self.git.head()
        for stage in BOUNDARIES:
            with self.subTest(stage=stage):
                result = subprocess.run([sys.executable, '-c', child, str(self.root),
                                         str(self.ws.journal.state), stage], capture_output=True,
                                        text=True, timeout=15)
                self.assertEqual(result.returncode, 73, result.stderr)
                for query in (self.ws.read_projection, lambda: self.ws.read_relations(ENTITY),
                              lambda: Projects(self.node).open(self.id)):
                    with self.assertRaises(PendingOperation):
                        query()
                self.ws = self.service.workspace(self.id)
                receipt = self.ws.recover()
                self.assertEqual(receipt['commit_id'], self.assert_current()['commit_id'])
                self.assertEqual(self.git.run('rev-list', '--count', baseline+'..HEAD').stdout.strip(), '1')
                self.assertEqual(self.ws.receipt(receipt['operation_id']), receipt)
                self.assertIsNone(self.ws.recover())
                self.git.run('reset', '--hard', baseline)

    def test_project_read_checks_metadata_and_relations_not_only_title(self):
        self.ws.apply(graph(), **IDENTITY)
        for sql in ("UPDATE relations SET type='unexpected'",
                    "UPDATE entities SET title='unexpected'",
                    "UPDATE entities SET privacy='public'",
                    "UPDATE tags SET tag='unexpected'"):
            with self.subTest(sql=sql):
                with closing(sqlite3.connect(self.ws.index.path)) as db, db:
                    db.execute(sql)
                with self.assertRaisesRegex(ValidationError, 'Index differs'):
                    Projects(self.node).open(self.id)
                self.ws.index.rebuild(self.git)
        self.assertEqual(Projects(self.node).open(self.id)['commit_id'], self.git.head())


if __name__ == '__main__':
    unittest.main()
