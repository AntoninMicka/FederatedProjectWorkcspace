# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReprocessBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_manual_reprocessing_after_protection_preserves_published_edition(self):
        script=r'''
import json,time
from unittest.mock import patch
from uuid import uuid4
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from tests import test_reporting
from tests.test_monitoring_blocks import blocks,response
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.monitoring import Monitoring
from spikes.composable_monitoring import ComposableMonitoring
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  instant=[time.time()]
  server.monitoring=Monitoring(f.node,server.projects,clock=lambda:instant[0])
  runtime=ComposableMonitoring(server.monitoring,fetcher=lambda *a,**kw:response())
  server.monitoring._composable_runtime=runtime
  specs=blocks(f.node);runtime.blocks.save(f.project,f.git.head(),specs,str(uuid4()))
  runtime.configure(f.project,specs[0]['id'],True,confirm=True);runtime.tick(f.project,lane='intake')
  first=runtime.process(f.project,specs[3]['id'],str(uuid4()))
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConfirm(self,url,text):return True
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print(message,line,flush=True)
  page=Page(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1200,900);view.show()
  phase=0;busy=False;original=None;original_path=None;error_run=None
  commands={
   0:'window.sourceRun='+json.dumps(first['id'])+';window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};(async()=>{await openRegisteredProject('+json.dumps(f.project)+');await loadMonitoring();await openReportOutput(reportOutputRows().find(r=>r.job?.id===sourceRun));window.originalOpened=true;})()',
   1:'Date.now=()=>'+str(int(instant[0]+4501)*1000)+';(async()=>{await loadMonitoring();await openReportOutput(reportOutputRows().find(r=>r.run_id===sourceRun&&r.source==="git"));window.publishedOpened=true;})()',
   2:"(()=>{const b=[...document.querySelectorAll('#report-output-actions button')].find(b=>b.textContent==='Zpracovat znovu');b.click();b.click();})()",
   4:"(async()=>{await loadMonitoring();await openReportOutput(reportOutputRows().find(r=>r.job?.id===window.errorRun));window.errorOpened=true;})()",
   5:"[...document.querySelectorAll('#report-output-actions button')].find(b=>b.textContent==='Zpracovat znovu').click()",
   3:"[...document.querySelectorAll('#report-output-actions button')].find(b=>b.textContent==='Vydat posouzenou zprávu').click()",
  }
  checks={
   0:"window.originalOpened&&[...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent==='Zpracovat znovu'&&b.disabled)",
   1:"window.publishedOpened&&[...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent==='Zpracovat znovu'&&!b.disabled)",
   2:"reportOutputRows().some(r=>r.id===selectedReportOutput&&r.job?.intent.reprocess_of===sourceRun&&r.job.result.protection.finalized)&&document.querySelector('#report-output-content').textContent.includes('Dodatečný vstup')&&[...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent==='Vydat posouzenou zprávu'&&!b.disabled)",
   4:"window.errorOpened&&document.querySelector('#report-output-content').textContent.includes('Ověřovací chyba vstupů')&&[...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent==='Zpracovat znovu'&&!b.disabled)&&![...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent==='Vydat posouzenou zprávu')",
   5:"reportOutputRows().some(r=>r.id===selectedReportOutput&&r.job?.intent.reprocess_of===window.errorRun&&r.state==='review')",
   3:"monitoringView.outputs.length===2&&reportOutputRows().some(r=>r.id===selectedReportOutput&&r.source==='git')",
  }
  def received(value):
   global phase,busy,original,original_path,error_run
   busy=False
   if value!='ready':return
   phase+=1
   if phase==1:
    instant[0]=first['result']['protection']['until'];runtime.tick(f.project,lane='processing')
    published=runtime.publish(f.project,first['id'],first['result']['approval_digest'],confirm=True)
    original_path=published['report_ref']['path'];original=f.git.snapshot(f.git.head())[original_path]
    instant[0]+=901;runtime.fetcher=lambda *a,**kw:response('Dodatečný vstup');runtime.tick(f.project,lane='intake')
   if phase==4:
    assert f.git.snapshot(f.git.head())[original_path]==original
    with runtime.pools.read_db() as db:
     rows=db.execute("SELECT document FROM block_jobs WHERE project=?",(f.project,)).fetchall()
    assert sum(json.loads(r[0]).get('reprocess_of')==first['id'] for r in rows)==1
    error_run=str(uuid4())
    with patch.object(runtime,'_period_inputs',side_effect=ValueError('Ověřovací chyba vstupů')):
     try:runtime.process(f.project,specs[3]['id'],error_run)
     except ValueError:pass
    page.runJavaScript('window.errorRun='+json.dumps(error_run))
   if phase==6:
    assert next(j for j in runtime.catalog(f.project)['jobs'] if j['id']==error_run)['state']=='failed'
    print('manual report reprocessing browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  def loaded(ok):
   if ok:page.runJavaScript(commands[0])
  page.loadFinished.connect(loaded)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  QTimer.singleShot(45000,lambda:(print('timeout phase',phase,flush=True),app.exit(2)))
  page.setUrl(QUrl(server.origin+'/'));result=app.exec()
  from shiboken6 import delete
  view.close();delete(view);delete(page);delete(profile);raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('manual report reprocessing browser OK',result.stdout)
