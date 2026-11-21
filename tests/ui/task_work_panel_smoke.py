# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Task panel across viewers/editor/chat, checklist context, responsive focus and revocation."""
import json
from uuid import uuid4
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.administration import AccessDenied
from spikes.artifacts import Artifacts
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.chat_service import ChatService
from spikes.task_work import TaskWork
from tests import test_task_queue as fixtures

app=QApplication([]);f=fixtures.TaskQueueTests();f.setUp();original=TaskWork._authorize;revoked=False
try:
 f.head=f.save('- [ ] [TASK-A] Inventarizace\n  - type: task\n  - Sepsat inventář techniky. <img src=x onerror=bad()>\n  - [ ] Seznam zařízení\n  - [x] Ověřené umístění\n- [ ] [TASK-X] Bez checklistu\n  - type: task\n  - Další samostatné zadání.\n')
 doc=str(uuid4());Artifacts(f.node).save(dict(project_id=f.pid,artifact_id=doc,base_head=f.head,title='Seznam techniky',body='# Seznam techniky\n\nPůvodní obsah.\n',new=True),str(uuid4()))
 def authorize(service,pid):
  if revoked:raise AccessDenied('Právo bylo odebráno.')
  return original(service,pid)
 TaskWork._authorize=authorize
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);browser=QWebEngineView();browser.setPage(page);browser.resize(1440,900);browser.show();phase=0;busy=False
  inject='window.nativeFetch=fetch;window.workCalls=[];window.allCalls=[];window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};if(opts.body)allCalls.push({url,body:JSON.parse(opts.body)});if(url==="/v1/task-work")workCalls.push(JSON.parse(opts.body));return nativeFetch(url,opts)};window.confirm=()=>true;'
  commands={
   1:inject+'openRegisteredProject('+json.dumps(f.pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>{showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A'));document.querySelector('[data-task-work-start=\"TASK-A\"]').click()})",
   3:"window.pointHead=activeProject.head;projectRequest('/v1/task-work',{action:'capture',...taskWorkHandle,context_revision:taskWorkView.context_revision}).then(v=>{window.originalCapture=v;document.querySelector('[data-task-work-checklist=\"0\"]').click()})",
   4:'openPreview('+json.dumps(doc)+')',
   5:'openArtifactEditor({id:'+json.dumps(doc)+',kind:"document"}).then(()=>{artifactEditorForm.elements.body.value="NEULOŽENÝ TEXT";artifactEditorForm.dispatchEvent(new Event("input",{bubbles:true}));document.querySelector(\'[data-task-work-checklist="1"]\').click()})',
   6:"document.querySelector('#task-work-panel-collapse').click()",
   7:"document.querySelector('#task-work-panel-toggle').click()",
   8:'syncTaskWorkPanel()',
   9:"(()=>{const root=document.querySelector('#task-work-controls'),items=[...root.querySelectorAll('button:not([disabled]),select:not([disabled]),input:not([disabled]),[href]')].filter(el=>el.getClientRects().length&&!el.closest('[hidden]'));items.at(-1).focus();items.at(-1).dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));window.tabWrapped=document.activeElement===items[0];document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));})()",
   10:"(()=>{const pending=navigateMainTab(document.querySelector('#chat-tab'));setTimeout(()=>document.querySelector('[data-leave-choice=cancel]').click(),30);pending.then(value=>window.cancelledNavigation=value===false);})()",
   11:"(()=>{const closing=closeArtifactEditor();setTimeout(()=>document.querySelector('[data-leave-choice=discard]').click(),30);closing.then(()=>navigateMainTab(document.querySelector('#chat-tab'))).then(()=>window.chatOpened=true);})()",
   12:"document.querySelector('#task-work-panel-toggle').click()",
   13:"document.querySelector('#task-work-switch').click()",
   14:"showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-X'));document.querySelector('[data-task-work-start=\"TASK-X\"]').click()",
   15:'refreshTaskWork()',
  }
  active="taskWorkView?.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id)"
  panel="!document.querySelector('#task-work-controls').hidden"
  checks={
   0:"typeof startTaskWork==='function'&&document.body.dataset.runtime==='desktop'",
   1:"window.opened&&activeProject",
   2:"!taskWorkBusy&&("+active+")?.task_id==='TASK-A'&&"+panel+"&&document.querySelector('#task-work-controls').getBoundingClientRect().left>=document.querySelector('main').getBoundingClientRect().right-1&&document.querySelector('#task-work-controls').getAttribute('role')==='complementary'&&document.querySelector('#task-work-details').textContent.includes('Sepsat inventář')&&!document.querySelector('#task-work-details img')&&document.querySelector('.task-work-progress').value===1&&document.querySelector('.task-work-progress').max===2",
   3:"!taskWorkBusy&&("+active+")?.selected_checklist===0&&originalCapture.selected_checklist===null&&activeProject.head===pointHead&&!("+active+").current_task.checklist[0].checked&&document.activeElement.dataset.taskWorkChecklist==='0'",
   4:"!document.querySelector('#preview-panel').hidden&&document.querySelector('#preview-title').textContent==='Seznam techniky'&&"+panel,
   5:"!taskWorkBusy&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='NEULOŽENÝ TEXT'&&("+active+")?.selected_checklist===1&&"+panel,
   6:"document.querySelector('#task-work-controls').hidden&&!document.querySelector('#task-work-panel-toggle').hidden&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='NEULOŽENÝ TEXT'",
   7:panel+"&&artifactEditorDirty&&document.activeElement.id==='task-work-panel-collapse'",
   8:panel+"&&innerWidth<500&&document.querySelector('#task-work-controls').getAttribute('role')==='dialog'&&document.querySelector('#task-work-controls').getAttribute('aria-modal')==='true'&&document.querySelector('main').inert&&document.documentElement.scrollWidth<=innerWidth+2",
   9:"window.tabWrapped&&document.querySelector('#task-work-controls').hidden&&!document.querySelector('main').inert&&document.activeElement.id==='task-work-panel-toggle'&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='NEULOŽENÝ TEXT'",
   10:"window.cancelledNavigation&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='NEULOŽENÝ TEXT'&&!artifactEditorView.hidden",
   11:"window.chatOpened&&!document.querySelector('#chat-panel').hidden&&!artifactEditorDirty&&allCalls.filter(c=>c.url==='/v1/artifacts/editor/save'||c.url==='/v1/chat/send').length===0",
   12:panel+"&&document.querySelector('#task-work-details').textContent.includes('Sepsat inventář')",
   13:"!document.querySelector('#plan-panel').hidden&&document.querySelector('#task-work-controls').hidden&&("+active+")?.task_id==='TASK-A'",
   14:"!taskWorkBusy&&("+active+")?.task_id==='TASK-X'&&"+panel+"&&!document.querySelector('#task-work-checklist')&&document.querySelector('#task-work-details').textContent.includes('Úkol nemá samostatný checklist')&&document.querySelector('#task-work-related-empty').textContent.includes('zatím nejsou')",
   15:"!taskWorkBusy&&("+active+")?.title===null&&document.querySelector('#task-work-details').textContent.includes('Právo bylo odebráno')&&!document.querySelector('#task-work-details').textContent.includes('Další samostatné zadání')&&!document.querySelector('#task-work-details').textContent.includes('Queue')&&!document.querySelector('#task-work-checklist')",
  }
  def received(value):
   global phase,busy,revoked
   busy=False
   if value!='ready':return
   phase+=1
   if phase==16:
    print('task panel browser OK',flush=True);app.exit(0);return
   if phase==8:browser.resize(390,850)
   if phase==15:revoked=True
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,details:document.querySelector('#task-work-details').textContent,focus:document.activeElement?.id,inert:document.querySelector('main').inert,dirty:artifactEditorDirty,view:taskWorkView})",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(65000,timeout);result=app.exec();browser.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:TaskWork._authorize=original;f.doCleanups()
