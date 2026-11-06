# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest

class ArtifactGitUITests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_stage_review_commit_preserves_newer_working_edit(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineScript
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.chat_service import ChatService
from tests.test_plan_draft import PlanDraftTests,BODY
app=QApplication([]);fixture=PlanDraftTests();fixture.setUp()
first=BODY+'      - First staged snapshot.\n';later=first+'      - Later working text.\n'
try:
 with running_api('http',handler=DesktopHandler,projects=fixture.projects) as server:
  server.chat_service=ChatService(fixture.node,fixture.projects)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app)
  bootstrap=QWebEngineScript();bootstrap.setInjectionPoint(QWebEngineScript.DocumentCreation);bootstrap.setWorldId(QWebEngineScript.MainWorld);bootstrap.setSourceCode('window.workspaceAutoStart=false;');page.scripts().insert(bootstrap)
  phase=0;busy=False
  commands={1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.openDone=true)',2:'openPreview('+json.dumps(fixture.aid)+')',3:"document.querySelector('#preview-git-stage').click()",4:"document.querySelector('#preview-git-commit').click()",5:"document.querySelector('#artifact-git-message').value='Reviewed selected snapshot';document.querySelector('#artifact-git-confirm').click()"}
  checks={0:"typeof artifactGitButtons==='function'",1:"window.openDone===true",2:"artifactGitState?.can_stage&&!artifactGitState.can_commit&&!document.querySelector('#preview-git-stage').parentElement.hidden&&document.querySelector('#preview-content').textContent.includes('First staged snapshot')&&document.querySelector('#preview-panel .workspace-page-header').contains(document.querySelector('#preview-git-stage'))",3:"artifactGitState?.can_commit&&!artifactGitState.can_stage",4:"document.querySelector('#artifact-git-dialog').open&&document.querySelector('#artifact-git-diff').textContent.includes('+      - First staged snapshot')&&!document.querySelector('#artifact-git-diff').textContent.includes('Later working text')",5:"!document.querySelector('#artifact-git-dialog').open&&activeProject.head!==BASE&&artifactGitState?.can_stage&&!artifactGitState.can_commit&&document.querySelector('#preview-content').textContent.includes('Later working text')&&!document.querySelector('#plan-source-controls')&&taskPlanProjection?.status==='ready'"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==2:fixture.path.write_text(first)
   if phase==4:
    assert fixture.git.head()==fixture.head
    fixture.path.write_text(later)
   if phase==6:
    committed=fixture.git.snapshot(fixture.git.head())[str(fixture.path.relative_to(fixture.project_root))]
    assert committed==first.encode() and fixture.path.read_text()==later
    print('file Stage/Commit browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase].replace('BASE',json.dumps(fixture.head))+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(180);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   page.runJavaScript("JSON.stringify({feedback:document.querySelector('#artifact-git-feedback')?.textContent,preview:previewStatus?.textContent,state:artifactGitState,dialog:document.querySelector('#artifact-git-dialog')?.open})",lambda s:(print('timeout phase',phase,s,flush=True),app.exit(2)))
  QTimer.singleShot(25000,timeout)
  result=app.exec();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=35)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('file Stage/Commit browser OK',result.stdout)
