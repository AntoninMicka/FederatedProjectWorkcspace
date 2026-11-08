# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class MigrationBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_review_convert_and_reopen_archived_definition_in_real_browser(self):
        script=r'''
import json
from uuid import uuid4
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from tests import test_reporting
from tests.test_monitoring_workflow import workflow
from tests.test_monitoring_blocks import response
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.monitoring import Monitoring
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.chat_service import ChatService
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.monitoring=Monitoring(f.node,server.projects);server.chat_service=ChatService(f.node,server.projects)
  request=workflow(f.project,f.git.head());remote=str(uuid4());request['processing']['definition']['placement']=dict(mode='node',node_id=remote,capabilities=[])
  saved=MonitoringDefinitions(f.node).save_workflow(request,str(uuid4()))
  collection=saved['stages']['collection'];pin=collection['definition_ref'];v=json.loads(f.git.snapshot(pin['commit_id'])[pin['path']])['value']
  server.monitoring.rss_runtime.fetcher=lambda *a,**kw:response('first archived evidence')
  server.monitoring.rss_runtime.configure(dict(project_id=f.project,watch_id=collection['watch_id'],definition_ref=pin,input_id=v['inputs'][0]['id'],enabled=True,mode='pipeline'),confirm=True)
  server.monitoring.rss_runtime.tick(f.project)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);phase=0;busy=False
  commands={
   1:'window.migrationOriginalNode='+json.dumps(remote)+';window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(f.project)+').then(()=>window.migrationOpened=true)',
   2:"monitoringOpen();document.querySelector('#monitoring-migration-open').click()",
   3:"monitoringMigrationForm.requestSubmit()",
   4:"monitoringMigrationForm.elements.retention_days.value='31';monitoringMigrationForm.elements.retention_days.dispatchEvent(new Event('input',{bubbles:true}))",
   5:"monitoringMigrationForm.elements.retention_days.value='30';monitoringMigrationForm.requestSubmit()",
   6:"[...document.querySelectorAll('#monitoring-migration-preview button')].find(b=>b.textContent==='Převést podle tohoto náhledu').click()",
   7:"showMonitoringDefinition(monitoringView.definitions[0])",
   8:"document.querySelector('#monitoring-migration-open').click()",
   9:"editMonitoringBlock('processing',blockCatalog.blocks.find(b=>b.value.kind==='processing'))",
  }
  checks={
   0:"typeof openMonitoringMigration==='function'",
   1:"window.migrationOpened&&monitoringView?.definitions.length===2&&blockCatalog?.blocks.length===0",
   2:"!monitoringMigrationForm.hidden&&monitoringMigrationForm.querySelectorAll('input[name=watch_ids]:checked').length===2",
   3:"monitoringMigrationPlan?.blocks.length===5&&monitoringMigrationPlan.findings.length===1&&!document.querySelector('#monitoring-migration-preview').hidden",
   4:"monitoringMigrationPlan===null&&document.querySelector('#monitoring-migration-preview').hidden",
   5:"monitoringMigrationPlan?.retention_days===30&&monitoringMigrationPlan.issues.length===0",
   6:"monitoringMigrationForm.hidden&&blockCatalog?.blocks.length===5&&blockCatalog.blocks.some(b=>b.message_count===1)&&monitoringView.definitions.every(b=>b.converted)&&monitoringView.rss.bindings.every(b=>!b.enabled)",
   7:"document.querySelector('#monitoring-detail').textContent.includes('bylo převedeno')&&![...document.querySelector('#monitoring-detail').querySelectorAll('button')].some(b=>/Zapnout|Zpracovat uložené|Upravit zadání/.test(b.textContent))",
   8:"!monitoringMigrationForm.hidden&&monitoringMigrationForm.querySelectorAll('input[name=watch_ids]:disabled').length===2&&blockCatalog.blocks.length===5",
   9:"!blockEditor.hidden&&blockEditor.elements.node_id.value===window.migrationOriginalNode",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==10:print('migration browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#monitoring-block-state')?.textContent,detail:document.querySelector('#monitoring-detail')?.textContent})",lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(55000,timeout);result=app.exec()
  page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=70)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('migration browser OK',result.stdout)
