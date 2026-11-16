# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class MigrationBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_service_conversion_preserves_current_catalog_without_legacy_panel(self):
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
  page=Page(profile,app);started=False;busy=False
  script=r"""
window.migrationSmoke={done:false};
(async()=>{
 const check=(ok,message)=>{if(!ok)throw Error(message);};
 const native=window.fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'Bearer '+__TOKEN__};return native(url,opts);};
 await openRegisteredProject(__PID__);
 await navigateSidebarTab(document.getElementById('tools-tab'));await loadMonitoring();
 check(!document.getElementById('monitoring-migration-open'),'retired panel restored');
 check(blockCatalog.blocks.length===0,'unexpected initial blocks');
 const post=async(action,body)=>{const response=await fetch('/v1/monitoring/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:__PID__,...body})});const value=await response.json();return {response,value};};
 const options={watch_ids:__IDS__,retention_days:30,processing_node_id:__NODE__};
 let result=await post('migration-preview',options);check(result.response.ok,JSON.stringify(result.value));
 const preview=result.value;check(preview.blocks.length===5&&preview.findings.length===1&&preview.issues.length===0,'incomplete preview');
 const apply={...options,preview_sha256:preview.preview_sha256,operation_id:__OP__,confirm:true};
 result=await post('migration-apply',{...apply,retention_days:31});check(result.response.status===422,'changed preview accepted: '+result.response.status+' '+JSON.stringify(result.value));
 await loadMonitoring();check(blockCatalog.blocks.length===0,'rejected preview wrote blocks');
 result=await post('migration-apply',apply);check(result.response.ok,JSON.stringify(result.value));
 await loadMonitoring();const committed=monitoringView.commit_id;
 check(blockCatalog.blocks.length===5&&blockCatalog.blocks.some(b=>b.message_count===1),'conversion catalog incomplete');
 check(blockCatalog.blocks.every(b=>b.runtime===null),'conversion activated a source');
 result=await post('migration-apply',apply);check(result.response.ok,'same operation did not replay');
 await loadMonitoring();check(monitoringView.commit_id===committed&&blockCatalog.blocks.length===5,'conversion duplicated');
 result=await post('migration-inventory',{});check(result.response.ok&&result.value.items.length===2&&result.value.items.every(b=>b.converted),'legacy retirement missing');
 editMonitoringBlock('processing',blockCatalog.blocks.find(b=>b.value.kind==='processing'));
 check(!blockEditor.hidden&&blockEditor.elements.node_id.value===__NODE__,'executor assignment lost');
 window.migrationSmoke={done:true,ok:true};
})().catch(error=>{window.migrationSmoke={done:true,error:error.stack||String(error)};});
"""
  for key,value in [('__TOKEN__',server.token),('__PID__',f.project),('__NODE__',remote),('__IDS__',sorted(s['watch_id'] for s in saved['stages'].values())),('__OP__',str(uuid4()))]:
   script=script.replace(key,json.dumps(value))
  def received(value):
   global started,busy
   busy=False
   if not started:
    if value:started=True;page.runJavaScript(script)
    return
   value=json.loads(value) if isinstance(value,str) else None
   if value and value.get('done'):
    if value.get('ok'):print('migration browser OK',flush=True);app.exit(0)
    else:print(value,flush=True);app.exit(1)
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('typeof openRegisteredProject==="function"' if not started else 'JSON.stringify(window.migrationSmoke)',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  QTimer.singleShot(55000,lambda:(print('migration timeout',flush=True),app.exit(2)));result=app.exec()
  page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
'''
        try:
            result=subprocess.run([sys.executable,'-u','-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=70)
        except subprocess.TimeoutExpired as exc:
            self.fail('Browser timeout: '+str(exc.stdout)+' '+str(exc.stderr))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('migration browser OK',result.stdout)
