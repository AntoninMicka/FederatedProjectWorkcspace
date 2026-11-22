# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Open a cross-project link already stored in task text, without attaching anything."""
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
 service,source,artifact,reference,share=fixture.shared_reference();fixture.aid=reference
 fixture.service.execute(fixture.attachment_request())
 pid=fixture.f.f.pid;head=fixture.work.projects.repository(pid).head();source_head=service.artifacts.workspace(source).git.head()
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.f.f.node)) as server:
  server.chat_service=ChatService(fixture.f.f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Auth(QWebEngineUrlRequestInterceptor):
   def interceptRequest(self,info):
    if info.requestUrl().toString().startswith(server.origin+'/'):info.setHttpHeader(b'Authorization',('Bearer '+server.token).encode())
  auth=Auth(profile);profile.setUrlRequestInterceptor(auth)
  page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1400,900);view.show();phase=0;busy=False
  click="[...document.querySelectorAll('#plan-detail .artifact-link')].find(button=>button.textContent==='Foreign link').click()"
  commands={
   1:'openRegisteredProject('+json.dumps(pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>showTaskPlanDetail(taskPlanProjection.nodes.find(node=>node.id==='TASK-A')))",
   3:click,
   4:"for(const item of currentArtifacts)delete item.sharing;openTaskPlan().then(()=>showTaskPlanDetail(taskPlanProjection.nodes.find(node=>node.id==='TASK-A')))",
   5:click,
  }
  shown="!!document.querySelector('.shared-reference-banner')&&previewContent.textContent.includes('Original foreign bytes')&&!previewContent.textContent.includes('fpw-artifact-reference-v2')&&selectedArtifact==="+json.dumps(reference)+"&&activeProject.id==="+json.dumps(pid)+"&&taskWorkHandle===null"
  checks={0:"typeof openPreview==='function'&&document.body.dataset.runtime==='desktop'",1:'window.opened&&activeProject',
   2:"[...document.querySelectorAll('#plan-detail .artifact-link')].some(button=>button.textContent==='Foreign link')",3:shown,
   4:"!document.querySelector('#plan-panel').hidden&&[...document.querySelectorAll('#plan-detail .artifact-link')].some(button=>button.textContent==='Foreign link')",5:shown}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==6:print('stored reference text link browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({preview:previewContent.textContent,status:previewStatus.textContent})",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(45000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater()
  assert fixture.work.projects.repository(pid).head()==head
  assert service.artifacts.workspace(source).git.head()==source_head
  raise SystemExit(result)
finally:fixture.doCleanups()
