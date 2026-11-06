# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest

class PlanNavigationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1', 'Requires real Qt/WebEngine')
    def test_editor_return_parent_navigation_child_cells_and_tasks_landing(self):
        result=subprocess.run([sys.executable,'-m','tests.plan_navigation_smoke'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=35)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
