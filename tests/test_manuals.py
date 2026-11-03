# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Catalog/package checks and a representative real WebEngine reading flow."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from spikes.manuals import manual_catalog, manual_paths
from scripts.package_desktop import ROOT, sources


class ManualTests(unittest.TestCase):
    def test_catalog_and_source_package_contain_all_readable_manuals(self):
        groups = manual_catalog()
        ids = [m['id'] for g in groups for m in g['manuals']]
        self.assertEqual(len(ids), len(set(ids)))
        for group in groups:
            for manual in group['manuals']:
                self.assertTrue(manual['text'], manual['id'])
        self.assertTrue(set(ROOT / p for p in manual_paths()) <= set(sources(ROOT)))

    def test_missing_installation_files_are_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs').mkdir()
            (root / 'docs/project-opening.md').write_text('# Ukázka', encoding='utf-8')
            manuals = manual_catalog(root)[0]['manuals']
            self.assertEqual(manuals[0]['text'], '# Ukázka')
            self.assertIsNone(manuals[1]['text'])

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires Qt/WebEngine')
    def test_browser_reads_manual_without_project_and_preserves_navigation_guard(self):
        script = r'''
import json
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
app=QApplication([])
with running_api('http',handler=DesktopHandler) as server:
 profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app)
 phase=0
 def received(value):
  global phase
  if value!='ready':return
  phase+=1
  commands={
   1:"navigateSidebarTab(document.querySelector('#manuals-tab'))",
   2:"document.querySelector('[data-manual-id=project-opening]').click()",
   3:"document.querySelector('[data-manual-id=task-queue]').click()",
   4:"window.savedGuard=canLeaveWorkspaceEditors;canLeaveWorkspaceEditors=async()=>false;navigateSidebarTab(document.querySelector('#projects-tab'))",
   5:"canLeaveWorkspaceEditors=window.savedGuard;navigateSidebarTab(document.querySelector('#projects-tab'))",
   6:"openManual({id:'missing',title:'Chybějící',text:null})",
   7:"openManual({id:'unsafe',title:'Unsafe',text:'# Test\\n<script>window.manualInjected=true</script>'})",
   8:"console.log('manual browser OK')"}
  if phase==8:
   print('manual browser OK',flush=True);app.exit(0);return
  page.runJavaScript(commands[phase])
 def poll():
  checks={
   0:"document.querySelector('#manuals-tab')&&typeof canLeaveWorkspaceEditors==='function'",
   1:"manualsCatalog&&document.querySelectorAll('#manuals-tree details').length===5&&!document.querySelector('#manuals-view').hidden",
   2:"document.querySelector('#manual-title').textContent==='Projekty a dokumenty'&&document.querySelector('#manual-content h1')&&activeProject===null&&!document.querySelector('#manual-content textarea,#manual-content input,#manual-content [contenteditable]')",
   3:"document.querySelector('#manual-title').textContent==='Fronta úloh'&&document.querySelector('[data-manual-id=task-queue]').getAttribute('aria-current')==='page'",
   4:"!document.querySelector('#manuals-view').hidden&&document.querySelector('#manuals-tab').getAttribute('aria-selected')==='true'",
   5:"document.querySelector('#manuals-view').hidden",
   6:"document.querySelector('#manual-content').textContent.includes('v instalaci chybí')",
   7:"document.querySelector('#manual-content').textContent.includes('<script>')&&!document.querySelector('#manual-content script')&&!window.manualInjected"}
  page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
 timer=QTimer();timer.timeout.connect(poll);timer.start(150)
 page.setUrl(QUrl(server.origin+'/'))
 QTimer.singleShot(15000,lambda:(print('timeout phase',phase,flush=True),app.exit(2)))
 raise SystemExit(app.exec())
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('manual browser OK', result.stdout)
