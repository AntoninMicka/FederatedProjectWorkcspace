# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest

class MonitoringBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_create_review_publish_and_open_real_presentation_editor(self):
        script = r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from tests import test_reporting
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.monitoring import Monitoring
from spikes.presentation_documents import PresentationDocuments
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.monitoring=Monitoring(f.node,server.projects);server.presentation_documents=PresentationDocuments(f.node)
  from spikes.monitoring_definitions import MonitoringDefinitions
  from tests.test_monitoring_definitions import definition
  from tests.test_rss_pilot import rss
  from uuid import uuid4
  cfg=definition();watch_id=str(uuid4())
  saved=MonitoringDefinitions(f.node).save(dict(project_id=f.project,base_head=f.git.head(),watch_id=watch_id,
    previous=[],privacy='project',definition=cfg),str(uuid4()))
  server.monitoring.rss_runtime.fetcher=lambda *a,**kw:dict(status=200,raw=rss(),validators={'if-none-match':'"browser"'})
  server.monitoring.rss_runtime.configure(dict(project_id=f.project,watch_id=watch_id,input_id=cfg['inputs'][0]['id'],
    definition_ref=saved['definition_ref'],enabled=True,mode='queue-all'),confirm=True)
  server.monitoring.rss_runtime.tick(f.project)
  from spikes.chat_service import ChatService
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(f.project)+')',
   2:"document.querySelector('#sidebar-monitoring-new').click()",
   3:"monitoringForm.elements.name.value='Browser test';monitoringForm.elements.goal.value='Sledovat ověřené změny';monitoringForm.elements.start.value='2026-03-23';monitoringForm.elements.presentation.checked=true;monitoringForm.dispatchEvent(new Event('input',{bubbles:true}));monitoringForm.requestSubmit()",
   4:"document.querySelector('#sidebar-monitoring-list button').click()",
   5:"[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Spustit nyní').click()",
   6:"document.querySelector('#sidebar-report-list button').click()",
   7:"document.querySelector('#monitoring-detail input[type=checkbox]').click();[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Vydat zprávu').click()",
   8:"[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Otevřít navázanou prezentaci').click()"}
  checks={
   0:"typeof loadMonitoring==='function'",
   1:"activeProject&&monitoringView&&monitoringView.project_id===activeProject.id&&document.querySelector('#monitoring-rss-list').textContent.includes('kontrola každých 15 min')",
   2:"!monitoringForm.hidden",
   3:"monitoringView?.watches.length===1&&!monitoringDirty&&monitoringForm.hidden",
   4:"[...document.querySelectorAll('#monitoring-detail button')].some(b=>b.textContent==='Spustit nyní')",
   5:"monitoringView?.reports.some(r=>r.state==='review')",
   6:"document.querySelector('#presentations-tab').getAttribute('aria-selected')==='true'&&document.querySelector('#monitoring-detail pre')?.textContent.includes('Nebyla doložena významná změna.')&&document.querySelector('#monitoring-detail input[type=checkbox]')",
   7:"monitoringView?.reports.some(r=>r.state==='completed'&&r.presentation_id)&&[...document.querySelectorAll('#monitoring-detail button')].some(b=>b.textContent==='Otevřít navázanou prezentaci')",
   8:"presentationEditorDeck&&presentationEditorArtifact===monitoringView.reports[0].presentation_id&&document.querySelector('#presentation-report-link')&&!document.querySelector('#presentation-panel').hidden"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==9:print('monitoring browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(200)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:monitoringStatus?.textContent,project:document.querySelector('#project-status')?.textContent,form:monitoringForm?.outerHTML.slice(0,1000)})",lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(60000,timeout)
  result=app.exec()
  page.deleteLater();profile.deleteLater()
  raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=75)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('monitoring browser OK',result.stdout)
