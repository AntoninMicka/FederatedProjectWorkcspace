# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from spikes.target_probe import filesystem, run


class TargetProbeTests(unittest.TestCase):
    def test_real_crashes_recovery_measurements_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sentinel = base / 'unrelated'
            sentinel.write_bytes(b'keep')
            output = io.StringIO()
            with redirect_stdout(output):
                run(base, filesystem(base))
            self.assertEqual(output.getvalue().count('"verified": true'), 15)
            self.assertIn('target probe: PASS', output.getvalue())
            self.assertEqual(list(base.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_wrong_filesystem_refuses_before_creating_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'no probe created'):
                run(Path(tmp), 'not-a-filesystem')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_worker_failure_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('spikes.target_probe.subprocess.run', return_value=subprocess.CompletedProcess([], 2, '', 'failed')):
                # check_output also uses subprocess.run; avoid that unrelated mocked call.
                with patch('spikes.target_probe.subprocess.check_output', return_value='git test'), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeError, 'Worker normal'):
                        run(Path(tmp), filesystem(Path(tmp)))
            self.assertEqual(len(list(Path(tmp).glob('workspace-probe-*'))), 1)
