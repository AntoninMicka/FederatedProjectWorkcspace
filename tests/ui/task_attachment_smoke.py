# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Attach an existing output with explicit confirmation and inspect the task text."""
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
   3:"[...document.querySelectorAll('#task-record-editor button')].find(b=>b.textContent==='Připojit existující soubor / artefakt').click()",
   4:'document.querySelector("#task-attachment-artifact").value='+json.dumps(doc)+';document.querySelector("#task-attachment-artifact").dispatchEvent(new Event("change"));document.querySelector("#task-attachment-comment").value="Existing inventory attached";document.querySelector("#task-attachment-comment").dispatchEvent(new Event("input"));window.attachmentChosen=true;',
   5:"[...document.querySelectorAll('#task-attachment-form button')].find(b=>b.textContent==='Potvrdit a připojit').click()",
   6:"[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Původní verze').click()",
   7:"openPlanItemEditor(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')).then(()=>window.taskOpened=true)",
  }
  checks={
   0:"typeof loadTaskAttachment==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.opened&&activeProject',
   2:"!taskWorkBusy&&taskWorkView?.active_session_id",
   3:"document.querySelector('#task-attachment-artifact')?.options.length>0",
   4:"window.attachmentChosen&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===0",
   5:"!taskWorkBusy&&document.querySelector('#task-record-list').textContent.includes('Existing inventory attached')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===1&&!taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).current_task.checked",
   6:"document.querySelector('#task-record-preview').textContent.includes('Original')",
   7:"window.taskOpened&&!artifactEditorView.hidden&&artifactEditorForm.elements.body.value.includes('Existing inventory attached')&&artifactEditorForm.elements.body.value.includes('Inventory')&&!artifactEditorForm.elements.body.value.includes('# Original')",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==8:print('existing task attachment browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,editor:document.querySelector('#artifact-editor-status')?.textContent,view:taskWorkView})",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(45000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
