# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Regression coverage for immutable source imports and preview boundaries."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata import MAX_FILE, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.source_import import Sources, request_from_file
from spikes.storage import Git


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.project_root = self.base / 'project'
        created = ProjectCreation(self.node).create('Import', str(self.project_root), str(uuid4()))
        self.project_id = created['id']
        self.sources = Sources(self.node)
        self.projects = Projects(self.node)
        self.git = Git(self.project_root)

    def _write(self, name, raw):
        path = self.base / name
        path.write_bytes(raw)
        return path

    def _request_for(self, path, title):
        return request_from_file(
            self.project_id,
            self.git.head(),
            str(path),
            title,
            '',
            [],
            'project'
        )

    def _legacy_import(self, name='legacy.pdf', raw=b'%PDF-1.7\nlegacy\n'):
        artifact_id = str(uuid4())
        author = ProjectCreation(self.node).author_id()
        created = '2026-09-17T08:00:00Z'
        meta = dict(schema_version=1, id=artifact_id, title='Legacy source', kind='source',
                    created_at=created, author_id=author, privacy='project', provenance='external',
                    file=name, description='', tags=[])
        prefix = f'artifacts/{artifact_id}/'
        changes = {prefix + name: raw,
                   prefix + 'metadata.json': (json.dumps(meta, sort_keys=True, indent=2) + '\n').encode()}
        base = self.git.head()
        operation = str(uuid4())
        def prepare(workspace):
            candidate = workspace.git.snapshot(base); candidate.update(changes)
            validate_snapshot(candidate)
            return changes, 'Local workspace author', author + '@local.invalid', 'Import original source'
        receipt = self.sources.workspace(self.project_id).transact(
            operation, {'action': 'legacy-import', 'artifact_id': artifact_id}, prepare, expected_head=base)
        return artifact_id, receipt['commit_id'], raw

    def test_import_accepts_supported_source_formats_and_lists_as_artifact(self):
        cases = [
            ('note.md', b'---\ntitle: Source\n---\nAhoj\n',),
            ('figure.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 16),
            ('scan.jpg', b'\xff\xd8\xff' + b'\x00' * 16),
            ('manual.pdf', b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF'),
        ]
        for filename, raw in cases:
            path = self._write('tmp-' + filename, raw)
            request = self._request_for(path, filename.rsplit('.', 1)[0])
            operation = str(uuid4())
            receipt = self.sources.import_source(request, operation)

            view = self.projects.open(self.project_id)
            self.assertEqual(receipt['commit_id'], view['commit_id'])
            self.assertIn(request['artifact_id'], [item['id'] for item in view['artifacts']])
            self.assertIn(request['title'], [item['title'] for item in view['artifacts']])

            source_path = self.project_root / 'artifacts' / request['artifact_id'] / request['filename']
            self.assertTrue(source_path.exists())
            self.assertEqual(source_path.read_bytes(), raw)
            meta = json.loads((source_path.parent / 'metadata.json').read_bytes())
            self.assertEqual(meta['schema_version'], 2)
            self.assertEqual(meta['import']['content_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(meta['import']['imported_at'], meta['created_at'])
            self.assertEqual(meta['import']['imported_by'], meta['author_id'])

            open_view = self.sources.open(self.project_id)
            self.assertEqual(open_view['documents'], [])

    def test_request_rejects_invalid_extension_or_too_large_file(self):
        unsupported = self._write('source.unsupported', b'abc')
        with self.assertRaises(ValueError):
            request_from_file(self.project_id, self.git.head(), str(unsupported), 'source', '', [], 'project')

        too_large = b'%PDF-1.7\n' + b'a' * (MAX_FILE + 1)
        large = self._write('too-large.pdf', too_large)
        with self.assertRaises(ValueError):
            request_from_file(self.project_id, self.git.head(), str(large), 'too-large', '', [], 'project')

    def test_preview_limit_is_independent_of_import_limit(self):
        # 5 MiB is inside import limit (16 MiB), but above preview limit (4 MiB).
        huge = b'\xff\xd8\xff' + b'a' * (5 * 1024 * 1024) + b'\xff'
        self.assertTrue(len(huge) > 4 * 1024 * 1024)
        self.assertTrue(len(huge) <= MAX_FILE)

        path = self._write('preview-boundary.jpg', huge)
        request = self._request_for(path, 'large-image')
        request['filename'] = 'preview-boundary.jpg'
        receipt = self.sources.import_source(request, str(uuid4()))

        view = self.projects.open(self.project_id)
        self.assertEqual(view['commit_id'], receipt['commit_id'])
        result = self.projects.preview(self.project_id, request['artifact_id'], view['commit_id'], 1)
        self.assertEqual(result['format'], 'unsupported')
        self.assertIn('4 MiB', result['message'])

        self.assertEqual(Artifacts(self.node).open(self.project_id)['documents'], [])

    def test_optional_provenance_is_validated_projected_and_previewed(self):
        raw = b'%PDF-1.7\nprovenance\n'
        path = self._write('evidence.pdf', raw)
        request = request_from_file(
            self.project_id, self.git.head(), str(path), 'Evidence', 'Description', ['tag'], 'confidential',
            source_url='https://example.invalid/evidence/7', source_author='External author',
            source_created_at='2026-09-16T09:30:00Z', source_revision='7')
        receipt = self.sources.import_source(request, str(uuid4()))
        projection = self.sources.workspace(self.project_id).read_projection()
        meta = projection['entities'][request['artifact_id']]['metadata']
        self.assertEqual(meta['source_url'], request['source_url'])
        self.assertEqual(meta['import']['source_author'], 'External author')
        self.assertEqual(meta['import']['source_created_at'], '2026-09-16T09:30:00Z')
        self.assertLess(meta['import']['source_created_at'], meta['import']['imported_at'])
        self.assertEqual(meta['import']['source_revision'], '7')
        self.assertEqual(self.projects.preview(self.project_id, request['artifact_id'], receipt['commit_id'])['metadata'], meta)

        invalid = dict(request, source_created_at='not-a-time', artifact_id=str(uuid4()), base_head=self.git.head())
        with self.assertRaises(ValueError):
            self.sources.import_source(invalid, str(uuid4()))
        self.assertIsNone(self.sources.workspace(self.project_id).recover())

    def test_metadata_edit_and_successor_preserve_original_source(self):
        original_path = self._write('edition-1.pdf', b'%PDF-1.7\nedition one\n')
        original = self._request_for(original_path, 'Edition 1')
        first = self.sources.import_source(original, str(uuid4()))

        edit = dict(project_id=self.project_id, artifact_id=original['artifact_id'],
                    base_head=first['commit_id'],
                    patch={'title': 'First edition', 'privacy': 'confidential'},
                    authorize_privacy_relaxation=False)
        edited = self.sources.edit_metadata(edit, str(uuid4()))
        old_meta = validate_snapshot(self.git.snapshot(edited['commit_id']))[original['artifact_id']]
        self.assertEqual(old_meta['title'], 'First edition')
        self.assertEqual(old_meta['privacy'], 'confidential')
        self.assertEqual((self.project_root / 'artifacts' / original['artifact_id'] / 'edition-1.pdf').read_bytes(),
                         b'%PDF-1.7\nedition one\n')

        relaxation = dict(edit, base_head=edited['commit_id'], patch={'privacy': 'public'})
        with self.assertRaisesRegex(ValueError, 'privacy relaxation'):
            self.sources.edit_metadata(relaxation, str(uuid4()))
        relaxation['authorize_privacy_relaxation'] = True
        relaxed = self.sources.edit_metadata(relaxation, str(uuid4()))

        successor_path = self._write('edition-2.pdf', b'%PDF-1.7\nedition two\n')
        successor = request_from_file(self.project_id, relaxed['commit_id'], str(successor_path),
                                      'Edition 2', '', [], 'project',
                                      supersedes=original['artifact_id'])
        final = self.sources.import_source(successor, str(uuid4()))
        entities = validate_snapshot(self.git.snapshot(final['commit_id']))
        self.assertEqual(entities[successor['artifact_id']]['relations'],
                         [{'type': 'supersedes', 'target_id': original['artifact_id']}])
        self.assertIn(original['artifact_id'],
                      [item['id'] for item in self.sources.open(self.project_id)['sources']])

    def test_duplicate_detection_is_same_project_and_does_not_merge_sources(self):
        raw = b'%PDF-1.7\nduplicate\n'
        path = self._write('duplicate.pdf', raw)
        request = self._request_for(path, 'First')
        receipt = self.sources.import_source(request, str(uuid4()))
        self.assertEqual(self.sources.duplicate_ids(self.project_id, receipt['commit_id'], request['sha256']),
                         [request['artifact_id']])
        duplicate = request_from_file(self.project_id, receipt['commit_id'], str(path), 'Second', '', [], 'project')
        second = self.sources.import_source(duplicate, str(uuid4()))
        self.assertNotEqual(request['artifact_id'], duplicate['artifact_id'])
        self.assertEqual(len(self.sources.duplicate_ids(self.project_id, second['commit_id'], request['sha256'])), 2)

    def test_explicit_v1_migration_requires_native_import_commit_and_is_idempotent(self):
        artifact_id, import_commit, raw = self._legacy_import()
        request = dict(project_id=self.project_id, artifact_id=artifact_id,
                       base_head=self.git.head(), import_commit=import_commit)
        operation = str(uuid4())
        receipt = self.sources.migrate_source(request, operation)
        meta = validate_snapshot(self.git.snapshot(receipt['commit_id']))[artifact_id]
        self.assertEqual(meta['schema_version'], 2)
        self.assertEqual(meta['import'], {
            'imported_at': meta['created_at'], 'imported_by': meta['author_id'],
            'content_sha256': hashlib.sha256(raw).hexdigest(),
            'importer': {'name': 'workspace-native-import', 'version': '1'}})
        self.assertEqual(self.sources.migrate_source(request, operation), receipt)
        self.assertEqual(self.git.run('rev-list', '--count', import_commit + '..HEAD').stdout.strip(), '1')

        other_id, _, _ = self._legacy_import('other.pdf')
        invalid = dict(project_id=self.project_id, artifact_id=other_id,
                       base_head=self.git.head(), import_commit=import_commit)
        with self.assertRaises(ValueError):
            self.sources.migrate_source(invalid, str(uuid4()))
        self.assertIsNone(self.sources.workspace(self.project_id).recover())

    def test_v1_migration_recovers_once_across_publish_and_index_boundaries(self):
        script = '''
import json,os,sys
from spikes.source_import import Sources
def checkpoint(stage):
    if stage == sys.argv[4]: os._exit(73)
Sources(sys.argv[1]).migrate_source(json.loads(sys.argv[2]),sys.argv[3],checkpoint=checkpoint)
'''
        for stage in ('prepared', 'commit-ready', 'ref-updated', 'index-entities', 'completed'):
            with self.subTest(stage=stage):
                artifact_id, import_commit, _ = self._legacy_import('legacy-' + stage + '.pdf')
                request = dict(project_id=self.project_id, artifact_id=artifact_id,
                               base_head=self.git.head(), import_commit=import_commit)
                operation = str(uuid4())
                result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(request),
                                         operation, stage], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 73, result.stderr)
                view = self.sources.open(self.project_id)
                receipt = self.sources.migrate_source(request, operation)
                self.assertEqual(receipt['commit_id'], view['commit_id'])
                self.assertEqual(validate_snapshot(self.git.snapshot(self.git.head()))[artifact_id]['schema_version'], 2)
                self.assertEqual(self.git.run('rev-list', '--count', import_commit + '..HEAD').stdout.strip(), '1')
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt widgets')
    def test_native_dialog_keeps_source_creation_separate_from_import_time(self):
        path = self._write('dated.pdf', b'%PDF-1.7\ndated\n')
        script = r'''
import os,sys
from PySide6.QtWidgets import QApplication,QLabel,QMessageBox
import spikes.desktop_import as module
from spikes.source_import import request_from_file
module.ImportDialog.load=lambda self: None
app=QApplication([])
dialog=module.ImportDialog(sys.argv[1],sys.argv[2])
dialog.view={'commit_id':sys.argv[4]}
dialog.path.setText(sys.argv[3]);dialog.title.setText('Dated source')
dialog.source_created_at.setText('2020-01-02T03:04:05Z')
captured={}
def make_request(*args,**kwargs):
    captured.update(kwargs);return request_from_file(*args,**kwargs)
module.request_from_file=make_request
QMessageBox.exec=lambda self: QMessageBox.StandardButton.Cancel
dialog.import_file()
assert captured['source_created_at']=='2020-01-02T03:04:05Z',captured
assert 'může být starší než import' in ' '.join(x.text() for x in dialog.findChildren(QLabel))
assert dialog.pending is None
sys.stdout.write('source/import times separated\n');sys.stdout.flush();os._exit(0)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.node), self.project_id,
                                 str(path), self.git.head()], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('source/import times separated', result.stdout)


if __name__ == '__main__':
    unittest.main()
