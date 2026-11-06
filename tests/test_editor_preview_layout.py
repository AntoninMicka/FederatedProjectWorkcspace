# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest

class EditorPreviewLayoutTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_editor_modes_preserve_draft_and_use_viewport_at_desktop_and_mobile_sizes(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.chat_service import ChatService
from tests.test_plan_draft import PlanDraftTests,BODY
app=QApplication([]);fixture=PlanDraftTests();fixture.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=fixture.projects) as server:
  server.chat_service=ChatService(fixture.node,fixture.projects)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1440,1000);view.show()
  bootstrap=QWebEngineScript();bootstrap.setInjectionPoint(QWebEngineScript.DocumentCreation);bootstrap.setWorldId(QWebEngineScript.MainWorld);bootstrap.setSourceCode('window.workspaceAutoStart=false;');page.scripts().insert(bootstrap)
  draft=BODY+''.join('      - Dlouhý popis řádek '+str(i)+'\n' for i in range(180))+'      - <script>window.editorPreviewInjected=true</script>\n'
  phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.openDone=true)',
   2:'openArtifactEditor({id:'+json.dumps(fixture.aid)+',kind:"document"})',
   3:'document.querySelector("#task-plan-mode-raw").click();artifactEditorForm.elements.body.value='+json.dumps(draft)+';artifactEditorForm.elements.body.dispatchEvent(new Event("input",{bubbles:true}));artifactEditorForm.elements.body.setSelectionRange(27,35);artifactEditorForm.elements.body.scrollTop=160;',
   4:"document.querySelector('#task-plan-mode-preview').click()",
   5:"document.querySelector('#task-plan-mode-raw').click()",
   6:"document.querySelector('#artifact-editor-tools').open=true",
   7:"document.querySelector('#artifact-editor-tools').open=false",
   8:"document.querySelector('#task-plan-mode-preview').click()",
   9:"document.querySelector('#task-plan-mode-structured').click()",
   10:"document.querySelector('#task-plan-mode-raw').click()"}
  checks={
   0:"typeof openArtifactEditor==='function'",
   1:"window.openDone===true",
   2:"!artifactEditorView.hidden&&artifactEditorForm.elements.body.value===BODY&&document.querySelector('#task-plan-mode-preview')",
   3:"artifactEditorDirty&&artifactEditorForm.elements.body.value===DRAFT&&rawFits()",
   4:"taskPlanMode==='preview'&&!document.querySelector('#task-plan-preview').hidden&&document.querySelector('#task-plan-preview').textContent.includes('Dlouhý popis řádek 179')&&artifactEditorForm.elements.body.value===DRAFT&&artifactEditorDirty&&previewFits()&&!document.querySelector('#task-plan-preview script')&&!window.editorPreviewInjected",
   5:"taskPlanMode==='raw'&&artifactEditorForm.elements.body.value===DRAFT&&artifactEditorForm.elements.body.selectionStart===27&&artifactEditorForm.elements.body.selectionEnd===35&&artifactEditorForm.elements.body.scrollTop===160&&rawFits()",
   6:"document.querySelector('#artifact-editor-tools').open&&artifactEditorForm.elements.body.getBoundingClientRect().height>120&&pageFits()",
   7:"innerWidth<500&&rawFits()",
   8:"taskPlanMode==='preview'&&previewFits()&&pageFits()",
   9:"taskPlanMode==='structured'&&!document.querySelector('#task-plan-blocks').hidden&&artifactRawRoot.hidden&&document.querySelector('#task-plan-preview').hidden&&artifactEditorForm.elements.body.value===DRAFT&&pageFits()",
   10:"taskPlanMode==='raw'&&rawFits()&&artifactEditorForm.elements.body.value===DRAFT"}
  helpers="""window.pageFits=()=>{const body=workspacePageLayouts.get(artifactEditorForm).body;return body.scrollHeight<=body.clientHeight+2&&body.scrollWidth<=body.clientWidth+2};window.rawFits=()=>{const body=workspacePageLayouts.get(artifactEditorForm).body,r=artifactEditorForm.elements.body.getBoundingClientRect(),b=body.getBoundingClientRect();return r.width>b.width*.9&&r.height>b.height*.65&&r.bottom<=b.bottom+1&&pageFits()};window.previewFits=()=>{const body=workspacePageLayouts.get(artifactEditorForm).body,r=document.querySelector('#task-plan-preview').getBoundingClientRect(),b=body.getBoundingClientRect();return r.width>b.width*.9&&r.height>b.height*.65&&r.bottom<=b.bottom+1};"""
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==3:page.runJavaScript(helpers)
   if phase==7:view.resize(390,844)
   if phase==11:
    assert fixture.git.head()==fixture.head and fixture.path.read_text()==BODY
    print('editor preview and geometry OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase].replace('DRAFT',json.dumps(draft)).replace('BODY',json.dumps(BODY))+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(180);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   page.runJavaScript("JSON.stringify({mode:taskPlanMode,body:workspacePageLayouts.get(artifactEditorForm)?.body.getBoundingClientRect().toJSON(),raw:artifactEditorForm.elements.body.getBoundingClientRect().toJSON(),preview:document.querySelector('#task-plan-preview').getBoundingClientRect().toJSON(),nodes:[...document.querySelectorAll('#artifact-raw-widget,#artifact-raw-widget .raw-editor-layout,#artifact-raw-widget .raw-editor-main,#artifact-raw-widget .raw-editor-main>label,#artifact-editor-tools')].map(e=>({tag:e.tagName,id:e.id,rect:e.getBoundingClientRect().toJSON(),display:getComputedStyle(e).display,flex:getComputedStyle(e).flex,height:getComputedStyle(e).height,alignItems:getComputedStyle(e).alignItems})),scrollHeight:workspacePageLayouts.get(artifactEditorForm)?.body.scrollHeight,clientHeight:workspacePageLayouts.get(artifactEditorForm)?.body.clientHeight,status:artifactEditorStatus.textContent})",lambda s:(print('timeout phase',phase,s,flush=True),app.exit(2)))
  QTimer.singleShot(25000,timeout)
  result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=35)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('editor preview and geometry OK',result.stdout)
