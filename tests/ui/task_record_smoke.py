# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Review, defer, publish and amend a task record without losing the editor draft."""
import json
from uuid import uuid4
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.artifacts import Artifacts
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.chat_service import ChatService
from tests import test_task_queue as fixtures

app=QApplication([]);fixture=fixtures.TaskQueueTests();fixture.setUp()
try:
 doc=str(uuid4())
 Artifacts(fixture.node).save(dict(project_id=fixture.pid,artifact_id=doc,base_head=fixture.head,title='Inventory',body='# Original\n',new=True),str(uuid4()))
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.node)) as server:
  server.chat_service=ChatService(fixture.node,server.projects)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1400,900);view.show()
  phase=0;busy=False
  commands={
   1:'window.originalFetch=fetch;window.fetch=(url,opts={})=>originalFetch(url,{...opts,headers:{...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'}});openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>{showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A'));document.querySelector('[data-task-work-start=\"TASK-A\"]').click()})",
   3:'openArtifactEditor({id:'+json.dumps(doc)+',kind:"document"}).then(()=>{artifactEditorForm.elements.body.value="# Saved inventory";artifactEditorForm.dispatchEvent(new Event("input",{bubbles:true}));window.draftPrepared=true;})',
   4:'saveArtifactEditor({navigate:false}).then(value=>window.saved=value)',
   5:'window.beforeRecordHead=activeProject.head;openArtifactEditor({id:'+json.dumps(doc)+',kind:"document"}).then(()=>{artifactEditorForm.elements.body.value="UNSAVED EDITOR";artifactEditorForm.dispatchEvent(new Event("input",{bubbles:true}));document.querySelector("[data-record-event]").click();document.querySelector("#task-record-comment").value="Inventory verified";document.querySelector("#task-record-comment").dispatchEvent(new Event("input",{bubbles:true}));window.draftMade=true;refreshTaskWork().then(()=>window.draftRefreshed=true);})',
   6:"submitTaskRecord('deferred').then(()=>window.deferred=true)",
   7:"[...document.querySelectorAll('#task-record-editor button')].find(b=>b.textContent==='Otevřít nabídku').click()",
   8:"submitTaskRecord('publish').then(()=>window.published=true)",
   9:"[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Původní verze').click()",
   10:"window.prompt=()=> 'Corrected inventory note';[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Upravit komentář').click()",
   11:"openPlanItemEditor(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')).then(()=>window.taskTextOpened=true)",
   12:"document.querySelector('#editor-leave-dialog [data-leave-choice=discard]').click()",
  }
  checks={
   0:"typeof taskWorkActivityHeaders==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.opened&&activeProject',
   2:"!taskWorkBusy&&taskWorkView?.active_session_id",
   3:"window.draftPrepared&&artifactEditorDirty&&document.querySelector('#task-work-related-list').children.length===0",
   4:"window.saved&&!taskWorkBusy&&document.querySelector('#task-work-related-list').textContent.includes('Uložení dokumentu')&&document.querySelector('#task-work-related-list').textContent.includes('Commit')&&!document.querySelector('#task-work-related-list').textContent.includes('Saved inventory')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).activities.length===1",
   5:"window.draftRefreshed&&!taskWorkBusy&&document.querySelector('#task-record-comment').value==='Inventory verified'&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='UNSAVED EDITOR'",
   6:"window.deferred&&!taskWorkBusy&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).activities[0].offer.state==='deferred'&&activeProject.head===beforeRecordHead&&!document.querySelector('#task-record-form')",
   7:"document.querySelector('#task-record-comment')?.value==='Inventory verified'",
   8:"window.published&&!taskWorkBusy&&document.querySelector('#task-record-list').textContent.includes('Inventory verified')&&document.querySelector('#task-record-list').textContent.includes('Inventory')&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='UNSAVED EDITOR'&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===1",
   9:"document.querySelector('#task-record-preview').textContent.includes('Saved inventory')&&artifactEditorDirty",
   10:"!taskWorkBusy&&document.querySelector('#task-record-list').textContent.includes('Corrected inventory note')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records[0].revisions.length===2&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='UNSAVED EDITOR'",
   11:"document.querySelector('#editor-leave-dialog').open",
   12:"window.taskTextOpened&&!artifactEditorView.hidden&&artifactEditorForm.elements.body.value.includes('Corrected inventory note')&&artifactEditorForm.elements.body.value.includes('Inventory')&&!artifactEditorForm.elements.body.value.includes('# Saved inventory')&&(artifactEditorForm.elements.body.value.match(/fpw-task-record:/g)||[]).length===1",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==13:print('task record browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,editor:document.querySelector('#artifact-editor-status')?.textContent,view:taskWorkView})",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(65000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
