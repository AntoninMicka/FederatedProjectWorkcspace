# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Roadmap evidence and pinned previews work without claiming a task window."""
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.chat_service import ChatService
from spikes.projects import Projects
from tests.test_task_records import TaskRecordTests

app=QApplication([]);fixture=TaskRecordTests();fixture.setUp()
try:
 fixture.service.execute(fixture.request());fixture.saved('# New inventory content\n')
 head=fixture.work.projects.repository(fixture.f.f.pid).head()
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.f.f.node)) as server:
  server.chat_service=ChatService(fixture.f.f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Auth(QWebEngineUrlRequestInterceptor):
   def interceptRequest(self,info):
    if info.requestUrl().toString().startswith(server.origin+'/'):info.setHttpHeader(b'Authorization',('Bearer '+server.token).encode())
  auth=Auth(profile);profile.setUrlRequestInterceptor(auth)
  page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1440,900);view.show();phase=0;busy=False
  commands={
   1:'openRegisteredProject('+json.dumps(fixture.f.f.pid)+').then(()=>window.projectOpened=true)',
   2:"openTaskPlan().then(()=>showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')))",
   3:"[...document.querySelectorAll('#plan-detail [data-task-record] button')].find(b=>b.textContent==='Původní verze').click()",
   4:"[...document.querySelectorAll('#plan-detail [data-task-record] button')].find(b=>b.textContent==='Aktuální artefakt').click()",
   5:"window.evidenceFetch=fetch;window.fetch=async(...args)=>{const response=await evidenceFetch(...args);if(args[1]?.body&&JSON.parse(args[1].body).action==='record-preview')return new Promise(resolve=>window.releaseEvidence=()=>resolve(response));return response;};[...document.querySelectorAll('#plan-detail [data-task-record] button')].find(b=>b.textContent==='Původní verze').click()",
   6:"showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-X'));releaseEvidence();",
  }
  checks={
   0:"typeof appendTaskPlanRecords==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.projectOpened&&activeProject',
   2:"document.querySelectorAll('#plan-detail [data-task-record]').length===1&&document.querySelectorAll('#plan-detail [data-task-activity]').length===2&&document.querySelector('#plan-detail').textContent.includes('Inventář je připraven ke kontrole')&&taskWorkHandle===null&&!document.querySelector('#plan-detail').textContent.includes('Načítám záznamy')",
   3:"document.querySelector('#plan-detail [aria-label=\"Náhled výsledku úkolu\"]').textContent.includes('Original inventory')&&taskWorkHandle===null",
   4:"document.querySelector('#plan-detail [aria-label=\"Náhled výsledku úkolu\"]').textContent.includes('New inventory content')",
   5:"typeof window.releaseEvidence==='function'",
   6:"planDetailId==='TASK-X'&&document.querySelector('#plan-detail').textContent.includes('nemá potvrzené projektové záznamy')&&!document.querySelector('#plan-detail').textContent.includes('Original inventory')&&taskWorkHandle===null",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==7:print('roadmap task records browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("document.querySelector('#plan-detail').textContent",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(60000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater()
  assert fixture.work.projects.repository(fixture.f.f.pid).head()==head
  assert fixture.f.status()['active_session_id']==fixture.sid
  raise SystemExit(result)
finally:fixture.doCleanups()
