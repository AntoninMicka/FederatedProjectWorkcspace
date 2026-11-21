# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class TaskWorkBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_lifecycle_dirty_editor_lost_reply_and_explicit_window_restore(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_work_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=85)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('task work browser OK',result.stdout)
