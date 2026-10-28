# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from scripts.package_desktop import ROOT, archive_prefix, build
from scripts.release_version import read_version


class PackageTests(unittest.TestCase):
    def test_reproducible_manifest_and_no_local_state(self):
        prefix = archive_prefix(read_version(ROOT))
        first = build(ROOT)
        self.assertEqual(first, build(ROOT))
        with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as archive:
            names = archive.getnames()
            for name in ('docs/project-opening.md', 'docs/ollama-lan.md',
                         'docs/release-0.1.0.md', 'CHANGELOG.md',
                         'docs/roadmap-graph.json', 'extensions/workspace-bridge/extension.js',
                         'extensions/workspace-bridge/bridge.js', 'docs/ide-file-bridge.md', 'TODO.md', 'BACKLOG.md', 'WORK_LOG.md'):
                self.assertIn(prefix + '/' + name, names)
            self.assertIn(prefix + '/VERSION', names)
            self.assertIn(prefix + '/modules/publication-experiment-registry.module.json', names)
            self.assertIn(prefix + '/modules/publication-experiment-registry.source.json', names)
            self.assertTrue(all(m.isfile() and m.name.startswith(prefix + '/') for m in archive))
            self.assertFalse(any('/.git/' in n or '/.venv/' in n or '.private.' in n or '/dist/' in n for n in names))
            manifest = json.load(archive.extractfile(prefix + '/MANIFEST.sha256.json'))
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.extractfile(prefix + '/' + name).read()).hexdigest(), digest)
            self.assertEqual(archive.getmember(prefix + '/run.sh').mode, 0o755)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'release.tar.gz'
            path.write_bytes(b'old release')
            result = subprocess.run([str(ROOT / 'run.sh'), 'package-desktop', '--output', str(path)],
                                    capture_output=True, cwd='/tmp')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), b'old release')

    def test_explicit_candidate_version_updates_root_and_embedded_version(self):
        payload = build(ROOT, '0.1.1~rc1')
        prefix = archive_prefix('0.1.1~rc1')
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            self.assertEqual(archive.extractfile(prefix + '/VERSION').read(), b'0.1.1~rc1\n')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Real packaged WebEngine test requires M0_DESKTOP_TEST=1')
    def test_extracted_package_runs_without_checkout(self):
        prefix = archive_prefix(read_version(ROOT))
        with tempfile.TemporaryDirectory(prefix='desktop package ') as tmp:
            with tarfile.open(fileobj=io.BytesIO(build(ROOT)), mode='r:gz') as archive:
                # The builder's allowlisted archive contains regular files only.
                archive.extractall(tmp, filter='data')
            root = Path(tmp) / prefix
            result = subprocess.run([str(root / 'run.sh'), 'help'], cwd='/tmp', capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke'],
                                    cwd=root, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('authenticated fetch, value=1', result.stdout)
