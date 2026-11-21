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

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_persistent_panel_checklist_dirty_editor_navigation_focus_and_privacy(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_work_panel_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=80)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('task panel browser OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_native_editor_save_automatically_appears_as_task_activity(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_activity_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('task activity browser OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_record_draft_defer_publish_preview_and_amend_preserve_dirty_editor(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_record_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=80)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('task record browser OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_backend_restart_fresh_profile_recovers_saved_task_and_human_completes_it(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_work_restart_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=80)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('task work restart and completion browser OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_roadmap_records_and_exact_current_outputs_without_claiming_work_context(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_record_roadmap_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=80)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('roadmap task records browser OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_existing_artifact_attachment_requires_confirmation_and_reaches_task_text(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/task_attachment_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=65)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('existing task attachment browser OK',result.stdout)
