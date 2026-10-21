# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path

from scripts.release_version import read_version, validate_version


class ReleaseVersionTests(unittest.TestCase):
    def test_current_version_and_supported_candidate_suffix(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(read_version(root), '0.1.0')
        self.assertEqual(validate_version('0.1.0~rc1'), '0.1.0~rc1')

    def test_invalid_or_unsafe_values_are_rejected(self):
        for value in ('', 'v0.1.0', '01.0.0', '0.1', '0.1.0-rc1',
                      '0.1.0\nInjected: yes', '../0.1.0', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_version(value)

    def test_version_file_is_single_ascii_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for raw in (b'0.1.0', b'0.1.0\r\n', b'0.1.0\nextra\n', b'\xff\n'):
                (root / 'VERSION').write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    read_version(root)
            (root / 'VERSION').unlink()
            (root / 'target').write_text('0.1.0\n')
            (root / 'VERSION').symlink_to(root / 'target')
            with self.assertRaises(ValueError):
                read_version(root)


if __name__ == '__main__':
    unittest.main()
