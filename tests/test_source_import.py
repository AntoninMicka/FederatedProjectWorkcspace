# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Regression coverage for immutable source imports and preview boundaries."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata import MAX_FILE
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


if __name__ == '__main__':
    unittest.main()
