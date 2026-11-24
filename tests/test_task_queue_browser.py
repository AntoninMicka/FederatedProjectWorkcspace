# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class QueueRepairBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_invalid_queue_preview_cancel_and_repair_without_emptying(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from tests.test_task_queue import TaskQueueTests,BODY
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation
from spikes.chat_service import ChatService
app=QApplication([]);f=TaskQueueTests('test_duplicate_completed_and_blocked_rejected');f.setUp()
try:
 f.owner=ProjectCreation(f.node).author_id()
 for identifier in ('TASK-A','TASK-B','TASK-C'):f.act('add',identifier)
 f.act('set-flag','TASK-B',flag='held',value=True)
 f.save(BODY.replace('depends_on: TASK-A','depends_on: TASK-A, TASK-X').replace('- [ ] [TASK-A]','- [x] [TASK-A]'))
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.queueCalls=[];window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};if(opts.body)queueCalls.push(JSON.parse(opts.body));return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(f.pid)+').then(()=>window.opened=true)',
   2:'openTaskQueue()',
   3:"window.previewText='';window.confirm=text=>{window.previewText=text;return false};document.querySelector('#owner-queue-projects button').click()",
   4:"window.confirm=text=>{window.previewText=text;return true};document.querySelector('#owner-queue-projects button').click()"}
  checks={
   0:"typeof openTaskQueue==='function'",
   1:"window.opened&&activeProject",
   # Repair is offered in the one queue, without a project panel.
   2:"!document.querySelector('#assigned-queue-view').hidden&&!document.querySelector('#task-queue-panel')&&ownerQueueView&&!ownerQueueBusy&&!ownerQueueView.projects[0].valid&&document.querySelector('#owner-queue-projects button')&&!document.querySelector('#owner-queue-projects button').disabled",
   3:"!ownerQueueBusy&&ownerQueueView&&window.previewText.includes('TASK-X')&&window.previewText.includes('TASK-A')&&window.previewText.includes('vyřazení')&&!ownerQueueView.projects[0].valid&&queueCalls.filter(c=>c.action==='repair').length===0&&ownerQueueView.projects[0].task_ids.length===3",
   4:"!ownerQueueBusy&&ownerQueueView?.projects[0].valid&&JSON.stringify(ownerQueueView.projects[0].task_ids)===JSON.stringify(['TASK-X','TASK-B','TASK-C'])&&ownerQueueView.items.find(i=>i.id==='TASK-B').held&&queueCalls.filter(c=>c.action==='repair').length===1&&!taskQueueBusy&&taskQueueView?.valid"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==5:print('queue repair browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#owner-queue-status')?.textContent,owner:ownerQueueView,view:taskQueueView})",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(45000,timeout);result=app.exec();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('queue repair browser OK',result.stdout)


class OwnerQueueBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_cross_project_queue_drag_drop_without_open_project(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tests/ui/owner_queue_smoke.py')],
            cwd=root,env={**os.environ,'PYTHONPATH':str(root)},text=True,capture_output=True,timeout=75)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('owner queue browser OK',result.stdout)
