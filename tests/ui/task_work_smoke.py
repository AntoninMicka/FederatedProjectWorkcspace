# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real page/API lifecycle with a lost native-write reply and a dirty editor."""
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.chat_service import ChatService
from spikes.task_work import TaskWork
from tests import test_task_queue as fixtures

app=QApplication([]);f=fixtures.TaskQueueTests();f.setUp();original=TaskWork.execute;interrupted=False
try:
 def faulty(service,request,**kwargs):
  global interrupted
  if request.get('action')=='switch' and not interrupted:
   interrupted=True
   def stop(stage):
    if stage=='task-work-after-project':raise OSError('Simulated interrupted switch')
   return original(service,request,checkpoint=stop)
  return original(service,request,**kwargs)
 TaskWork.execute=faulty
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);browser=QWebEngineView();browser.setPage(page);browser.resize(1100,850);browser.show();phase=0;busy=False
  inject='window.nativeFetch=fetch;window.workCalls=[];window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};if(url==="/v1/task-work")workCalls.push(JSON.parse(opts.body));return nativeFetch(url,opts)};window.confirm=()=>true;window.prompt=()=>"Worked proof";'
  commands={
   1:inject+'openRegisteredProject('+json.dumps(f.pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')))",
   3:"document.querySelector('[data-task-work-start=\"TASK-A\"]').click()",
   4:"document.querySelector('#task-work-pause').click()",
   5:"document.querySelector('#task-work-resume').click()",
   6:"projectRequest('/v1/task-work',{action:'capture',...taskWorkHandle,context_revision:taskWorkView.context_revision}).then(value=>{window.originalContext=value;showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-X'));document.querySelector('[data-task-work-start=\"TASK-X\"]').click()})",
   7:"document.querySelector('#task-work-recover').click()",
   8:"document.querySelector('#task-work-propose').click()",
   9:"openNewArtifactEditor().then(()=>{artifactEditorForm.elements.body.value='Unsaved work';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#task-work-pause').click()})",
   10:"(()=>{const closing=closeArtifactEditor();setTimeout(()=>document.querySelector('[data-leave-choice=discard]').click(),50);closing.then(()=>window.discarded=true)})()",
   11:'location.reload()',
   12:inject,
   13:"document.querySelector('#task-work-restore').click()",
   14:"document.querySelector('#task-work-resume').click()",
   15:"document.querySelector('#task-work-close').click()",
  }
  active="taskWorkView?.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id)"
  checks={
   0:"typeof startTaskWork==='function'",
   1:"window.opened&&activeProject&&workCalls.length===0",
   2:"!!document.querySelector('[data-task-work-start=\"TASK-A\"]')&&!document.querySelector('[data-task-work-start=\"TASK-A\"]').disabled",
   3:"!taskWorkBusy&&("+active+")?.task_id==='TASK-A'&&("+active+")?.current_task.status==='in progress'&&!("+active+")?.blocked",
   4:"!taskWorkBusy&&taskWorkView&&!taskWorkView.active_session_id&&taskWorkView.sessions[0].state==='paused'",
   5:"!taskWorkBusy&&("+active+")?.task_id==='TASK-A'",
   6:"!taskWorkBusy&&taskWorkView?.pending&&originalContext.task_id==='TASK-A'&&document.querySelector('#task-work-status').textContent.includes('Simulated interrupted switch')",
   7:"!taskWorkBusy&&!taskWorkView?.pending&&("+active+")?.task_id==='TASK-X'&&workCalls.filter(r=>r.action==='switch').length===1&&workCalls.filter(r=>r.action==='recover').length===1&&originalContext.task_id==='TASK-A'",
   8:"!taskWorkBusy&&("+active+")?.completion_proposals?.length===1&&!("+active+")?.current_task.checked",
   9:"!taskWorkBusy&&!taskWorkView?.active_session_id&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='Unsaved work'&&!artifactEditorView.hidden",
   10:"window.discarded&&artifactEditorView.hidden",
   11:"typeof startTaskWork==='function'&&!taskWorkHandle",
   12:"!taskWorkHandle&&!document.querySelector('#task-work-restore').hidden&&workCalls.length===0",
   13:"!taskWorkBusy&&taskWorkView&&!taskWorkView.active_session_id&&taskWorkHandle&&!document.querySelector('#task-work-resume').disabled&&!activeProject",
   14:"!taskWorkBusy&&("+active+")?.task_id==='TASK-X'&&!activeProject",
   15:"!taskWorkBusy&&taskWorkView&&!taskWorkView.active_session_id&&taskWorkView.sessions.some(s=>s.task_id==='TASK-X'&&s.state==='closed'&&!s.current_task.checked)&&document.documentElement.scrollWidth<=innerWidth+2",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==16:
    print('task work browser OK',flush=True);app.exit(0);return
   if phase==11:browser.resize(390,850)
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({message:taskWorkMessage,status:document.querySelector('#task-work-status')?.textContent,view:taskWorkView,editorDirty:artifactEditorDirty})",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(70000,timeout);result=app.exec();browser.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:TaskWork.execute=original;f.doCleanups()
