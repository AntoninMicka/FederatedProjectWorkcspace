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

from scripts.package_desktop import ROOT, PREFIX, build


class PackageTests(unittest.TestCase):
    def test_reproducible_manifest_and_no_local_state(self):
        first = build(ROOT)
        self.assertEqual(first, build(ROOT))
        with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as archive:
            names = archive.getnames()
            self.assertIn(PREFIX + '/docs/project-opening.md', names)
            self.assertTrue(all(m.isfile() and m.name.startswith(PREFIX + '/') for m in archive))
            self.assertFalse(any('/.git/' in n or '/.venv/' in n or '.private.' in n or '/dist/' in n for n in names))
            manifest = json.load(archive.extractfile(PREFIX + '/MANIFEST.sha256.json'))
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.extractfile(PREFIX + '/' + name).read()).hexdigest(), digest)
            self.assertEqual(archive.getmember(PREFIX + '/run.sh').mode, 0o755)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'release.tar.gz'
            path.write_bytes(b'old release')
            result = subprocess.run([str(ROOT / 'run.sh'), 'package-desktop', '--output', str(path)],
                                    capture_output=True, cwd='/tmp')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), b'old release')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Real packaged WebEngine test requires M0_DESKTOP_TEST=1')
    def test_extracted_package_runs_without_checkout(self):
        with tempfile.TemporaryDirectory(prefix='desktop package ') as tmp:
            with tarfile.open(fileobj=io.BytesIO(build(ROOT)), mode='r:gz') as archive:
                # The builder's allowlisted archive contains regular files only.
                archive.extractall(tmp, filter='data')
            root = Path(tmp) / PREFIX
            result = subprocess.run([str(root / 'run.sh'), 'help'], cwd='/tmp', capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke'],
                                    cwd=root, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('authenticated fetch, value=1', result.stdout)
