import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from scripts.package_deb import build, NAME


@unittest.skipUnless(shutil.which('dpkg-deb'), 'Requires Debian packaging tools')
class DebianPackageTests(unittest.TestCase):
    def test_contents_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = build(root / 'app.deb')
            subprocess.run(['dpkg-deb', '-R', str(package), str(root / 'unpacked')], check=True, capture_output=True)
            tree = root / 'unpacked'
            self.assertEqual({p.name for p in (tree / 'DEBIAN').iterdir()}, {'control'})
            self.assertFalse((tree / 'home').exists())
            self.assertFalse((tree / 'var').exists())
            self.assertTrue((tree / f'usr/bin/{NAME}').stat().st_mode & 0o111)
            self.assertFalse(any('.private.' in str(p) for p in tree.rglob('*')))
            original = package.read_bytes()
            with self.assertRaises(FileExistsError): build(package)
            self.assertEqual(original, package.read_bytes())
            with self.assertRaises(ValueError): build(root / 'bad.deb', '1\nInjected: yes')

    @unittest.skipUnless(os.environ.get('M0_DEB_TEST') == '1', 'Requires installed Debian runtime dependencies')
    def test_isolated_dpkg_install_upgrade_remove_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'root'
            admin = root / 'var/lib/dpkg'
            admin.mkdir(parents=True)
            # Empty database proves missing dependencies are rejected first.
            command = ['dpkg', '--force-not-root', '--root=' + str(root)]
            package = build(base / 'v1.deb')
            result = subprocess.run(command + ['--install', str(package)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            # Model the host's installed runtime; no claim of a separate OS image.
            (admin / 'status').write_bytes(Path('/var/lib/dpkg/status').read_bytes())
            sentinel = root / 'home/user/projects/keep.txt'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b'user project')
            for version in ['0.1.0~m0', '0.1.1~m0']:
                package = build(base / (version + '.deb'), version)
                result = subprocess.run(command + ['--install', str(package)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sentinel.read_bytes(), b'user project')
            if os.environ.get('M0_DESKTOP_TEST') == '1':
                result = subprocess.run([str(root / f'usr/bin/{NAME}'), '--smoke'], cwd='/tmp',
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('backend stopped', result.stdout)
            result = subprocess.run(command + ['--purge', NAME], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / f'usr/bin/{NAME}').exists())
            self.assertEqual(sentinel.read_bytes(), b'user project')
