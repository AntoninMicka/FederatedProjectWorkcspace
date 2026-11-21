# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real editor save automatically reaches the persistent task panel."""
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
   5:"openTaskPlan().then(()=>showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')))",
   6:"[...document.querySelectorAll('#plan-detail [data-task-record] button')].find(b=>b.textContent==='Původní verze').click()",

  }
  checks={
   0:"typeof taskWorkActivityHeaders==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.opened&&activeProject',
   2:"!taskWorkBusy&&taskWorkView?.active_session_id",
   3:"window.draftPrepared&&artifactEditorDirty&&document.querySelector('#task-work-related-list').children.length===0",
   4:"window.saved&&!taskWorkBusy&&document.querySelector('#task-work-related-list').textContent.includes('Uložení dokumentu')&&document.querySelector('#task-work-related-list').textContent.includes('Commit')&&!document.querySelector('#task-work-related-list').textContent.includes('Saved inventory')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).activities.length===1&&document.querySelector('#task-record-list').textContent.includes('Automaticky zaznamenáno')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===1",
   5:"document.querySelectorAll('#plan-detail [data-task-record]').length===1&&document.querySelector('#plan-detail').textContent.includes('Automaticky zaznamenáno')&&document.querySelector('#plan-detail [data-task-record]').textContent.includes('Inventory')&&!taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).current_task.checked",
   6:"document.querySelector('#plan-detail [aria-label=\"Náhled výsledku úkolu\"]').textContent.includes('Saved inventory')",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==7:print('task activity browser OK',flush=True);app.exit(0);return
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
