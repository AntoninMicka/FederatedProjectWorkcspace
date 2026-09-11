# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Isolated licensing-asset tests; not a full runtime or legal-compliance audit."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from scripts import package_deb, package_desktop
from scripts.license_files import LICENSE_FILES, license_files

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def fixture(root):
    """Synthetic, trusted build tree with real legal assets, not a release build."""
    for name in (
        'run.sh', 'requirements.txt', 'README.md', 'docs/project-opening.md',
        'spikes/__init__.py', 'spikes/artifact_preview.py',
        'spikes/libgit2/probe.cpp', 'spikes/libgit2/README.md',
        'AGENTS.md', 'ARCHITECTURE.md', 'DATA_MODEL.md', 'FEDERATION.md',
        'SECURITY.md', 'TODO.md', 'BACKLOG.md', 'WORK_LOG.md',
        'REUSE_CATALOG.md', 'CONTRIBUTING.md',
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Synthetic packaging fixture\n', encoding='utf-8')
    for name in LICENSE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_ROOT / name, path)
    for name in ('package_deb.py', 'package_desktop.py', 'license_files.py'):
        path = root / 'scripts' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_ROOT / 'scripts' / name, path)
    (root / 'docs/legal/release.private.md').write_text('DO NOT SHIP\n')
    (root / 'docs/legal/private-evidence.json').write_text('{"private": true}\n')
    return root


class LicensePackagingTests(unittest.TestCase):
    def test_provenance_document_is_required(self):
        self.assertIn('docs/legal/PROVENANCE.md', LICENSE_FILES)

    def test_missing_provenance_stops_both_builders(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = fixture(base / 'root')
            (root / 'docs/legal/PROVENANCE.md').unlink(missing_ok=True)
            with self.assertRaises(ValueError):
                package_desktop.build(root)
            output = base / 'missing-provenance.deb'
            with patch.object(package_deb, 'ROOT', root):
                with self.assertRaises(ValueError):
                    package_deb.build(output)
            self.assertFalse(output.exists())

    def test_dependency_register_does_not_claim_release_approval(self):
        data = tomllib.loads((SOURCE_ROOT / 'docs/legal/DEPENDENCIES.toml').read_text())
        self.assertEqual(data['schema_version'], 1)
        self.assertFalse(data['is_complete_sbom'])
        self.assertFalse(data['is_release_approval'])
        ids = [item['id'] for item in data['components']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({'pyyaml', 'pyside6', 'shiboken6', 'webengine', 'poppler'} <= set(ids))
        for item in data['components']:
            self.assertTrue(item['license_evidence'])
            self.assertTrue(item['release_status'])

    def test_evidence_license_hashes_match_delivered_bytes(self):
        evidence = (SOURCE_ROOT / 'docs/legal/LICENSE_SOURCES.md').read_text()
        for path in (SOURCE_ROOT / 'docs/legal/licenses').iterdir():
            self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), evidence)
        raw = (SOURCE_ROOT / 'docs/legal/licenses/LICENSE.PyYAML-6.0.3').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.assertEqual(blob, '2f1b8e15e5627d92f0521605c9870bc8e5505cb4')

    def test_source_archive_contains_all_legal_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(Path(tmp))
            raw = package_desktop.build(root)
            self.assertEqual(raw, package_desktop.build(root))
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
                manifest = json.load(archive.extractfile(
                    package_desktop.PREFIX + '/MANIFEST.sha256.json'))
                for name in LICENSE_FILES:
                    data = archive.extractfile(package_desktop.PREFIX + '/' + name).read()
                    self.assertEqual(data, (root / name).read_bytes())
                    self.assertEqual(manifest[name], hashlib.sha256(data).hexdigest())
                self.assertNotIn('docs/legal/release.private.md', manifest)
                self.assertNotIn('docs/legal/private-evidence.json', manifest)
                self.assertEqual(len(archive.getnames()), len(set(archive.getnames())))

    def test_missing_license_stops_source_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(Path(tmp))
            (root / 'docs/legal/licenses/COPYING.LGPL-3.0').unlink()
            with self.assertRaises(ValueError):
                package_desktop.build(root)

    def test_empty_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(Path(tmp))
            (root / 'THIRD_PARTY_NOTICES.md').write_bytes(b'')
            with self.assertRaises(ValueError):
                license_files(root)

    def test_symlinked_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(Path(tmp))
            target = root / 'THIRD_PARTY_NOTICES.md'
            target.unlink()
            target.symlink_to(root / 'LICENSE')
            with self.assertRaises(ValueError):
                license_files(root)

    def test_symlinked_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = fixture(base / 'root')
            legal = root / 'docs/legal'
            legal.rename(base / 'elsewhere')
            legal.symlink_to(base / 'elsewhere', target_is_directory=True)
            with self.assertRaises(ValueError):
                license_files(root)

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Requires dpkg-deb')
    def test_deb_carries_notices_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = fixture(base / 'root')
            output = base / 'workspace.deb'
            with patch.object(package_deb, 'ROOT', root):
                package_deb.build(output)
                original = output.read_bytes()
                with self.assertRaises(FileExistsError):
                    package_deb.build(output)
                self.assertEqual(original, output.read_bytes())
            unpacked = base / 'unpacked'
            subprocess.run(['dpkg-deb', '--raw-extract', str(output), str(unpacked)],
                           check=True, capture_output=True, timeout=30)
            doc = unpacked / 'usr/share/doc' / package_deb.NAME
            for name in LICENSE_FILES:
                self.assertEqual((doc / name).read_bytes(), (root / name).read_bytes())
            self.assertFalse((doc / 'docs/legal/release.private.md').exists())
            self.assertFalse((doc / 'docs/legal/private-evidence.json').exists())
            self.assertFalse(any(p.suffix == '.so' for p in unpacked.rglob('*')))
            control = (unpacked / 'DEBIAN/control').read_text()
            self.assertIn('Homepage: https://github.com/AntoninMicka/', control)
            self.assertIn('poppler-utils', control)
            self.assertIn('THIRD_PARTY_NOTICES.md', (doc / 'README').read_text())
            launcher = (unpacked / 'usr/bin' / package_deb.NAME).read_text()
            self.assertTrue(launcher.startswith('#!/bin/sh\n'))
            self.assertIn('SPDX-License-Identifier: MPL-2.0', launcher)
            self.assertIn('exec /usr/bin/python3 -I', launcher)
            desktop = (unpacked / 'usr/share/applications' /
                       (package_deb.NAME + '.desktop')).read_text()
            self.assertIn('SPDX-License-Identifier: MPL-2.0', desktop)

    def test_missing_notice_stops_deb_before_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = fixture(base / 'root')
            (root / 'THIRD_PARTY_NOTICES.md').unlink()
            output = base / 'missing.deb'
            with patch.object(package_deb, 'ROOT', root):
                with self.assertRaises(ValueError):
                    package_deb.build(output)
            self.assertFalse(output.exists())

    def test_packaging_entrypoints_work_as_scripts_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixture(Path(tmp) / 'root')
            for name in ('package_deb.py', 'package_desktop.py'):
                result = subprocess.run([sys.executable, str(root / 'scripts' / name), '--help'],
                                        cwd='/tmp', capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--output', result.stdout)


if __name__ == '__main__':
    unittest.main()
