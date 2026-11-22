# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit task input, fake model, saved file, confirmed note and original conversation."""
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
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.node)) as server:
  from tests.test_chat_service import FakeAdapter
  from unittest.mock import patch
  from spikes.ollama_backend import OllamaAdapter
  calls=[];server.chat_service=ChatService(fixture.node,server.projects,adapter_factory=lambda runs:FakeAdapter(runs,calls))
  binding=dict(schema_version=1,binding_id=str(uuid4()),revision='one',adapter='ollama',boundary='same-node',endpoint='http://127.0.0.1:11434',model='fake-test',target_id='local-process')
  server.chat_service.configure(binding)
  discovery=patch.object(OllamaAdapter,'discover_models',return_value=['fake-test']);discovery.start();fixture.addCleanup(discovery.stop)
  server.chat_service.refresh_ollama_models(binding)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1400,900);view.show()
  phase=0;busy=False
  commands={
   1:'window.originalFetch=fetch;window.fetch=(url,opts={})=>originalFetch(url,{...opts,headers:{...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'}});openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>{showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A'));document.querySelector('[data-task-work-start=\"TASK-A\"]').click()})",
   3:"document.querySelector('#chat-draft').value='User draft';document.querySelector('#task-work-analyze').click()",
   4:"document.querySelector('#chat-mode').value='brainstorming';refreshChatModeControls();document.querySelector('#chat-run-adapter').value='ollama';document.querySelector('#chat-run-adapter').dispatchEvent(new Event('change'));document.querySelector('#chat-run-model').value=[...document.querySelector('#chat-run-model').options].find(o=>o.value).value;document.querySelector('#chat-run-model').dispatchEvent(new Event('change'));",
   5:"document.querySelector('#chat-submit').click()",
   6:"[...document.querySelectorAll('#sidebar-chat-tree button')].find(b=>b.textContent==='Uložit poslední odpověď').click()",
   7:"chooseTaskRecordEvents(selectedTaskWorkSession().activities.filter(e=>e.kind==='conversation-output').map(e=>e.event_id));document.querySelector('#task-record-comment').value='Analysis reviewed';document.querySelector('#task-record-comment').dispatchEvent(new Event('input'))",
   8:"submitTaskRecord('publish')",
   9:"[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Otevřít konverzaci a běh').click()",
  }
  checks={
   0:"typeof prepareTaskWorkAnalysis==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.opened&&activeProject',
   2:"!taskWorkBusy&&taskWorkView?.active_session_id",
   3:"taskWorkPreparedInput&&document.querySelector('#chat-draft').value.includes('fpw-task-work-input-v1')&&document.querySelector('#chat-draft').value.endsWith('User draft')&&!document.querySelector('#chat-draft').value.includes('TASK-X')&&selectedTaskWorkSession().activities.length===0&&!document.querySelector('#chat-panel').hidden",
   4:"!!selectedRunOffer()&&!document.querySelector('#chat-submit').disabled",
   5:"!taskWorkBusy&&document.querySelector('#chat-messages').textContent.includes('Assistant answer')&&selectedTaskWorkSession().activities.length===1",
   6:"!taskWorkBusy&&selectedTaskWorkSession().activities.length===2&&selectedTaskWorkSession().activities.some(e=>e.kind==='conversation-output')",
   7:"document.querySelector('#task-record-comment')?.value==='Analysis reviewed'",
   8:"!taskWorkBusy&&selectedTaskWorkSession().task_records.length===1&&document.querySelector('#task-record-list').textContent.includes('Analysis reviewed')&&!selectedTaskWorkSession().current_task.checked",
   9:"activeThread?.turns.length===1&&document.querySelector('#chat-messages').textContent.includes('Assistant answer')&&!document.querySelector('#chat-panel').hidden",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==4:assert calls==[]
   if phase==10:assert len(calls)==2;print('task analysis browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,editor:document.querySelector('#artifact-editor-status')?.textContent,view:taskWorkView})",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(60000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
