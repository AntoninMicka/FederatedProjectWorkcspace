# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real shared UI with local HTTP, RSS capture, a pool and current block tools."""
import json
from uuid import uuid4
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from tests import test_rss_monitoring as rss_fixture
from tests.test_monitoring_blocks import blocks, response
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.chat_service import ChatService
from spikes.administration import Administration

app=QApplication([])
f=rss_fixture.RSSMonitoringTests('test_15_minute_collection_is_independent_of_daily_output_and_never_calls_llm')
f.setUp()
try:
 f.runtime.tick(f.f.project)
 excluded=[r['revision_id'] for r in f.findings()]+[r['value']['raw_ref']['artifact_id'] for r in f.findings()]
 monitoring=Monitoring(f.f.node,Projects(f.f.node),clock=lambda:f.now[0])
 specs=blocks(f.f.node)
 monitoring.composable.blocks.save(f.f.project,f.f.git.head(),specs,str(uuid4()))
 monitoring.composable.fetcher=lambda *a,**kw:response()
 monitoring.composable.configure(f.f.project,specs[0]['id'],True,confirm=True)
 monitoring.composable.tick(f.f.project)
 with running_api('http',handler=DesktopHandler,projects=Projects(f.f.node)) as server:
  server.monitoring=monitoring
  server.administration=Administration(f.f.node,deployment='desktop')
  server.administration.request(dict(id=None,node_role='federation-admin',memberships={}),dict(action='list'))
  server.chat_service=ChatService(f.f.node,server.projects)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  profile=QWebEngineProfile(app)
  page=Page(profile,app);started=[False];checking=[False]
  script=r'''
window.currentToolsSmoke={done:false};
(async()=>{
 const check=(ok,message)=>{if(!ok)throw Error(message);};
 const native=window.fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'Bearer '+TOKEN};return native(url,opts);};
 await openRegisteredProject(PID);
 check(activeProject?.id===PID,'project did not open');
 for(const id of EXCLUDED)check(!currentArtifacts.some(a=>a.id===id),'RSS appears in documents');
 for(const id of ['monitoring-new','monitoring-workflow-new','monitoring-form','monitoring-workflow-form','sidebar-legacy-monitoring-list','monitoring-migration-open'])check(!document.getElementById(id),'legacy UI remains: '+id);
 await navigateSidebarTab(document.getElementById('tools-tab'));
 await loadMonitoring();
 check(blockCatalog?.blocks.length===5,'current block catalog missing: '+monitoringStatus.textContent);
 check(monitoringView.block_catalog.commit_id===monitoringView.commit_id,'mixed snapshots');
 check(document.querySelectorAll('#sidebar-tools-tree [data-tool-key^="block:"]').length===5,'block list missing');
 check(document.querySelectorAll('[data-new-monitoring-block]').length===6,'new actions missing');
 document.querySelector('[data-tool-key="block:'+POOL+'"]').click();
 await new Promise(resolve=>setTimeout(resolve,80));
 const open=[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Otevřít zprávy a původ');check(open,'pool action missing');open.click();
 for(let n=0;n<100&&!document.querySelector('#monitoring-block-content').textContent.includes('Energie dnes');n++)await new Promise(resolve=>setTimeout(resolve,30));
 check(document.querySelector('#monitoring-block-content').textContent.includes('Energie dnes'),'pool content not visible');
 document.getElementById('sidebar-new-tool').click();
 check(!document.querySelector('#sidebar-tool-new-options').textContent.includes('původní'),'legacy creation remains');
 window.currentToolsSmoke={done:true,ok:true};
})().catch(error=>{window.currentToolsSmoke={done:true,error:error.stack||String(error)};});
'''
  for key,value in [('TOKEN',server.token),('PID',f.f.project),('EXCLUDED',excluded),('POOL',specs[1]['id'])]:
   script=script.replace(key,json.dumps(value))
  def poll():
   if checking[0]:return
   checking[0]=True
   def received(value):
    checking[0]=False
    if not started[0]:
     if not value:return
     started[0]=True;page.runJavaScript(script);return
    value=json.loads(value) if isinstance(value,str) else None
    if value and value.get('done'):
     if value.get('ok'):print('current monitoring browser OK',flush=True);app.exit(0)
     else:print(value,flush=True);app.exit(1)
   page.runJavaScript('typeof openRegisteredProject==="function"' if not started[0] else 'JSON.stringify(window.currentToolsSmoke)',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(50)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   page.runJavaScript('JSON.stringify({state:window.currentToolsSmoke,status:document.querySelector("#monitoring-status")?.textContent})',lambda value:(print('timeout',started[0],value,flush=True),app.exit(2)))
  QTimer.singleShot(40000,timeout)
  result=app.exec();page.deleteLater();profile.deleteLater()
  if result:raise SystemExit(result)
finally:f.doCleanups()
