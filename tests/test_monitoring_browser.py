# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Current monitoring UI integration; legacy editors are intentionally absent."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class MonitoringBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_current_tools_pool_and_documents_in_real_browser(self):
        try:
            result=subprocess.run([sys.executable,'-u','-m','tests.ui.current_monitoring_smoke'],
                cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=60)
        except subprocess.TimeoutExpired as exc:
            self.fail('Browser timeout: '+str(exc.stdout)+' '+str(exc.stderr))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('current monitoring browser OK',result.stdout)
