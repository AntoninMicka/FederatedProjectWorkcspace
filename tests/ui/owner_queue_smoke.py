# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exercise owner queue navigation and real HTML drag/drop against an isolated API."""
import json
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation
from spikes.chat_service import ChatService
from tests.test_owner_task_queue import OwnerQueueTests

app=QApplication([]);f=OwnerQueueTests();f.setUp()
try:
 f.owner=ProjectCreation(f.node).author_id()
 f.add(f.pid,'TASK-A');f.add(f.pid,'TASK-X');f.add(f.other,'TASK-A')
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);browser=QWebEngineView();browser.setPage(page);browser.resize(1100,780);browser.show();phase=0;busy=False
  inject='window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};'
  drag="""(()=>{const rows=[...document.querySelector('#owner-queue-list').children],data=new DataTransfer();rows[2].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:data}));const target=rows[0],y=target.getBoundingClientRect().top+1;target.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:data,clientY:y}));target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data,clientY:y}));})()"""
  commands={
   1:inject+'openTaskQueue()',
   2:drag,
   3:"document.querySelector('#owner-queue-list').children[2].querySelector('.task-queue-order-controls button').click()",
   4:"[...document.querySelectorAll('#owner-queue-list>li')].find(row=>row.querySelector('.owner-queue-task').textContent.startsWith('TASK-X')).querySelector('button[aria-label=\"Pozastavit: TASK-X\"]').click()",
   5:"[...document.querySelectorAll('#owner-queue-list>li')].find(row=>row.querySelector('.owner-queue-task').textContent.startsWith('TASK-X')).querySelector('button[aria-label=\"Uvolnit: TASK-X\"]').click()",
   6:"window.nativeRequest=projectRequest;window.failedMoves=0;projectRequest=async(path,body,...rest)=>{if(body.action==='owner-move'){failedMoves++;throw Error('Simulated unknown result')}return nativeRequest(path,body,...rest)};document.querySelector('#owner-queue-list').children[2].querySelector('.task-queue-order-controls button').click()",
   7:"projectRequest=nativeRequest;document.querySelector('#owner-queue-refresh').click()",
   8:'location.reload()',
   9:inject+'openTaskQueue()',
  }
  visible="!document.querySelector('#assigned-queue-view').hidden&&!ownerQueueBusy&&ownerQueueView?.items.length===3"
  checks={
   0:"typeof openTaskQueue==='function'",
   1:visible+"&&!activeProject&&!document.querySelector('#assigned-queue-tab').disabled&&document.querySelector('#owner-queue-list').children.length===3",
   2:visible+'&&ownerQueueView.items[0].project_id==='+json.dumps(f.other),
   3:visible+"&&ownerQueueView.items[1].id==='TASK-X'&&document.activeElement.classList.contains('owner-queue-task')",
   # One queue: management happens in the row, without opening a project or a second panel.
   4:visible+"&&!activeProject&&ownerQueueView.items.find(i=>i.id==='TASK-X').held&&!document.querySelector('#owner-queue-project-tools')&&!document.querySelector('#task-queue-list')&&!document.querySelector('#assigned-queue-view').textContent.includes('Správa a zprávy')&&[...document.querySelectorAll('#owner-queue-list>li')].every(row=>row.querySelector('button[aria-label^=\"Odebrat:\"]'))",
   5:visible+"&&!activeProject&&!ownerQueueView.items.find(i=>i.id==='TASK-X').held&&ownerQueueView.items[1].id==='TASK-X'",
   6:"!ownerQueueBusy&&!ownerQueueView&&failedMoves===1&&document.querySelector('#owner-queue-status').textContent.includes('Obnovte frontu')",
   7:visible+"&&ownerQueueView.items[1].id==='TASK-X'",
   8:"typeof openTaskQueue==='function'&&!ownerQueueView",
   9:visible+"&&!activeProject&&ownerQueueView.items[1].id==='TASK-X'&&innerWidth<500&&document.documentElement.scrollWidth<=innerWidth+2",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==10:
    print('owner queue browser OK',flush=True);app.exit(0);return
   if phase==8:browser.resize(390,780)
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#owner-queue-status')?.textContent,view:ownerQueueView,active:activeProject?.id,hidden:document.querySelector('#assigned-queue-view')?.hidden})",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(60000,timeout);result=app.exec();browser.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
