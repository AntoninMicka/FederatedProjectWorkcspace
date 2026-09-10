"""Preview reads are HEAD-bound and never execute document content."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.artifact_preview import preview
from spikes.artifacts import Artifacts
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git, StaleIndex
from spikes.workspace import PendingOperation
from tests.fixtures import metadata
from tests import test_local_api


def pdf_bytes():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 120 120] /Contents 4 0 R >>',
               b'<< /Length 23 >>\nstream\n0 0 1 rg 5 5 50 50 re f\nendstream']
    data = b'%PDF-1.4\n'; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 5\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6XcAAAAASUVORK5CYII=')


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'; self.root = self.base / 'project'
        self.id = ProjectCreation(self.node).create('Preview', str(self.root), str(uuid4()))['id']
        self.projects = Projects(self.node); self.git = Git(self.root)

    def add(self, name, raw):
        id_ = str(uuid4()); folder = self.root / 'artifacts' / id_; folder.mkdir(parents=True)
        meta = dict(metadata('<img src=x onerror=alert(1)>', id_), kind='source', file=name,
                    description='Existing summary', privacy='local-only', provenance='external')
        (folder / name).write_bytes(raw); (folder / 'metadata.json').write_text(json.dumps(meta))
        self.git.commit('Fixture'); return id_

    def test_committed_markdown_metadata_stale_pending_and_registration(self):
        id_ = self.add('note.md', b'# Heading\n<script>alert(1)</script>')
        head = self.git.head()
        (self.root / 'artifacts' / id_ / 'note.md').write_text('foreign draft')
        result = self.projects.preview(self.id, id_, head)
        self.assertIn('# Heading', result['text']); self.assertNotIn('raw', result)
        self.assertEqual(result['metadata']['privacy'], 'local-only')
        with self.assertRaises(ValueError): self.projects.preview(self.id, str(uuid4()), head)
        with self.assertRaises(ValueError): self.projects.preview(str(uuid4()), id_, head)
        with self.assertRaises(ValueError): self.projects.preview(self.id, '../file', head)
        with self.assertRaises(ValueError): self.projects.preview(self.id, id_, head, True)
        self.git.commit('Later')
        with self.assertRaises(StaleIndex): self.projects.preview(self.id, id_, head)
        service = Artifacts(self.node)
        request = dict(project_id=self.id, artifact_id=str(uuid4()), base_head=self.git.head(),
                       title='Pending', body='text', new=True)
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('stop')
        with self.assertRaises(RuntimeError): service.save(request, str(uuid4()), checkpoint=crash)
        with self.assertRaises(PendingOperation): self.projects.preview(self.id, id_, self.git.head())

    def test_images_pdf_and_unsupported_limits(self):
        for name, raw, format_ in [('image.png', PNG, 'image'), ('source.pdf', pdf_bytes(), 'pdf'),
                                   ('unsafe.svg', b'<svg onload="evil()"/>', 'unsupported'),
                                   ('bad.md', b'\xff', 'unsupported'), ('lines.md', b'line\n' * 2001, 'unsupported'), ('bad.pdf', b'bad', 'unsupported'),
                                   ('large.md', b'x' * (4 * 1024 * 1024 + 1), 'unsupported')]:
            with self.subTest(name=name):
                id_ = self.add(name, raw); head = self.git.head()
                result = self.projects.preview(self.id, id_, head)
                self.assertEqual(result['format'], format_)
                self.assertEqual(self.git.head(), head)
                if format_ in ('pdf', 'image'): self.assertTrue(result['image'].startswith('data:image/png;base64,'))
                if format_ == 'pdf': self.assertEqual(self.projects.preview(self.id, id_, head, 2)['format'], 'unsupported')
        with patch('spikes.artifact_preview.subprocess.run', side_effect=FileNotFoundError):
            result = preview(dict(raw=pdf_bytes(), path='x.pdf', sidecar=True, metadata={}))
            self.assertEqual(result['format'], 'unsupported')

    def test_authenticated_api_and_no_filesystem_parameters(self):
        id_ = self.add('note.md', b'# Test')
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler, projects=self.projects) as server:
            body = json.dumps(dict(project_id=self.id, artifact_id=id_, expected_head=self.git.head(), page=1)).encode()
            response = driver.request(server, path='/v1/artifacts/preview', body=body)
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response)
            driver.rejected(server, path='/v1/artifacts/preview', body=body, headers={'Authorization': None})
            driver.rejected(server, path='/v1/artifacts/preview', body=body, headers={'Origin': 'https://evil.invalid'})
            driver.rejected(server, path='/v1/artifacts/preview', body=b'{"path":"/etc/passwd"}')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real WebEngine')
    def test_real_main_panel_markdown_image_pdf(self):
        for name, raw in [('note.md', b'# Heading\n<script>evil()</script>'), ('image.png', PNG), ('source.pdf', pdf_bytes())]:
            id_ = self.add(name, raw)
            # One displayed artifact per smoke; preserve the same project identity.
            for folder in (self.root / 'artifacts').iterdir():
                if folder.name != id_:
                    import shutil
                    shutil.rmtree(folder)
            if self.git.run('status', '--porcelain').stdout:
                self.git.commit('Select fixture')
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node),
                                     '--smoke', '--smoke-project', self.id], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('rendered rows verified', result.stdout)
