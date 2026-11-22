# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""New backend origin + off-the-record Qt profile recovers work and completes it."""
import json
from uuid import uuid4
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.artifacts import Artifacts
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.chat_service import ChatService
from spikes.task_work import TaskWork
from spikes.task_activities import TaskActivities
from spikes.task_records import TaskRecords
from tests import test_task_queue as fixtures

app=QApplication([]);fixture=fixtures.TaskQueueTests();fixture.setUp()
try:
 fixture.head=fixture.save('- [ ] [TASK-A] Inventory\n  - type: task\n  - [x] Reviewed inventory\n- [ ] [TASK-X] Other task\n')
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.node)) as first:
  old_origin=first.origin;work=TaskWork(fixture.node)
  handle={k:v for k,v in work.create_window().items() if k.startswith('window_')}
  pin=work.inspect(handle,fixture.pid,'TASK-A',fixture.head)
  view=work.execute(dict(handle,action='start',operation_id=str(uuid4()),context_revision=0,project_id=fixture.pid,task_id='TASK-A',selected_checklist=0,**pin));sid=view['active_session_id']
  aid=str(uuid4());request=dict(operation_id=str(uuid4()),document=dict(project_id=fixture.pid,artifact_id=aid,base_head=view['sessions'][0]['validated_head'],title='Inventory',body='# Saved inventory\n',new=True))
  event=TaskActivities(work).begin(handle,view['context_revision'],'/v1/artifacts/editor/save',request)
  receipt=Artifacts(fixture.node).save(request['document'],request['operation_id']);TaskActivities(work).finish(event,200,receipt)
  state=TaskActivities(work).for_session(handle,sid)[0]
  TaskRecords(work).execute(dict(handle,action='record-offer',operation_id=str(uuid4()),work_session_id=sid,event_ids=[event],offer_revisions=[state['offer']['revision']],comment='Saved draft before restart',selected_checklist=0,state='deferred'))
  # Native save completed, but the process lost its activity finalization.
  second=dict(operation_id=str(uuid4()),document=dict(request['document'],new=False,
      base_head=work.projects.repository(fixture.pid).head(),body='# Revised inventory after lost response\n'))
  lost=TaskActivities(work).begin(handle,work.status(handle)['context_revision'],'/v1/artifacts/editor/save',second)
  with TaskActivities(work).observe(lost):Artifacts(fixture.node).save(second['document'],second['operation_id'])
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.node)) as server:
  assert old_origin!=server.origin
  server.chat_service=ChatService(fixture.node,server.projects)
  profile=QWebEngineProfile(app)
  class Auth(QWebEngineUrlRequestInterceptor):
   def interceptRequest(self,info):
    if info.requestUrl().toString().startswith(server.origin+'/'):info.setHttpHeader(b'Authorization',('Bearer '+server.token).encode())
  auth=Auth(profile);profile.setUrlRequestInterceptor(auth)
  page=QWebEnginePage(profile,app);browser=QWebEngineView();browser.setPage(page);browser.resize(1400,900);browser.show();phase=0;busy=False
  commands={
   1:"window.confirm=()=>true;document.querySelector('#task-work-saved-resume').click()",
   2:'openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>openArtifactEditor({id:'+json.dumps(aid)+',kind:"document"})).then(()=>{artifactEditorForm.elements.body.value="UNSAVED EDITOR";artifactEditorForm.dispatchEvent(new Event("input",{bubbles:true}));window.editorReady=true;})',
   3:"document.querySelector('#task-work-complete').click()",
  }
  current="taskWorkView?.sessions.find(s=>s.work_session_id==="+json.dumps(sid)+")"
  checks={
   0:"typeof taskWorkSavedSessions!=='undefined'&&taskWorkSavedSessions.some(s=>s.work_session_id==="+json.dumps(sid)+")&&!document.querySelector('#task-work-controls').hidden&&sessionStorage.getItem(taskWorkStorageKey)===null",
   1:"!taskWorkBusy&&taskWorkView?.active_session_id==="+json.dumps(sid)+"&&("+current+")?.selected_checklist===0&&("+current+")?.activities[0].offer.comment==='Saved draft before restart'&&("+current+")?.activities.length===2&&("+current+")?.activities[1].outcome==='succeeded'&&("+current+")?.activities[1].offer.state==='pending'&&("+current+")?.task_records.length===0",
   2:"window.editorReady&&artifactEditorDirty&&!document.querySelector('#task-work-complete').disabled",
   3:"!taskWorkBusy&&taskWorkView?.active_session_id===null&&("+current+")?.current_task.checked&&("+current+")?.state==='closed'&&artifactEditorDirty&&artifactEditorForm.elements.body.value==='UNSAVED EDITOR'&&document.querySelector('#task-work-status').textContent.includes('Úkol byl dokončen')",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==4:print('task work restart and completion browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,history:taskWorkSavedSessions,view:taskWorkView})",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(65000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();browser.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
