# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest

class MonitoringBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_independent_workflow_nodes_save_and_edit_in_real_browser(self):
        script=r'''
import json
from uuid import uuid4
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from tests import test_reporting
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.monitoring import Monitoring
from spikes.administration import Administration
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 admin=Administration(f.node,deployment='desktop');actor=dict(id=None,node_role='federation-admin',memberships={})
 state=admin.request(actor,dict(action='list'));peer=str(uuid4())
 state=admin.request(actor,dict(action='add-peer',expected_commit=state['commit_id'],node_id=peer,name='Omnia test',endpoint='https://192.168.100.2:8443',fingerprint='a'*64))
 admin.request(actor,dict(action='set-trust',expected_commit=state['commit_id'],node_id=peer,trust='approved'))
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.monitoring=Monitoring(f.node,server.projects);server.administration=admin
  from spikes.chat_service import ChatService
  server.chat_service=ChatService(f.node,server.projects)
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(f.project)+').then(()=>window.workflowProjectOpened=true)',
   2:"document.querySelector('#monitoring-workflow-new').click()",
   3:"(()=>{const f=monitoringWorkflowForm.elements;f.title.value='Browser těžba';f.goal.value='Sledovat změny';f.start.value='2026-10-05';f.collection_node.value="+json.dumps(peer)+";f.processing_node.value='local';f.terms.value='Synthetic capture permission';f.retention.value='Synthetic test retention';f.keywords.value='first';f.regex.value='first';f.access_confirm.checked=true;f.trigger.value='scheduled';monitoringWorkflowForm.dispatchEvent(new Event('input',{bubbles:true}));monitoringWorkflowForm.requestSubmit()})()",
   4:"[...document.querySelectorAll('#monitoring-definitions button')].find(b=>b.textContent==='Browser těžba').click()",
   5:"[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Upravit zadání').click()",
   6:"monitoringWorkflowForm.elements.trigger.value='manual';monitoringWorkflowForm.elements.access_confirm.checked=true;monitoringWorkflowForm.dispatchEvent(new Event('input',{bubbles:true}));monitoringWorkflowForm.requestSubmit()"}
  checks={
   0:"typeof editMonitoringWorkflow==='function'",
   1:"window.workflowProjectOpened&&monitoringView?.project_id===activeProject?.id&&monitoringView?.execution_nodes?.nodes.length===2",
   2:"!projectView.hidden&&!document.querySelector('#monitoring-panel').hidden&&!monitoringWorkflowForm.hidden&&monitoringWorkflowForm.elements.collection_node.options.length===2&&monitoringWorkflowForm.elements.processing_node.options.length===2",
   3:"monitoringView?.definitions.length===2&&monitoringWorkflowForm.hidden&&!monitoringDirty&&monitoringView.definitions.some(r=>r.definition.placement.node_id==="+json.dumps(peer)+")&&monitoringView.definitions.some(r=>r.definition.schedule.trigger==='scheduled')",
   4:"document.querySelector('#monitoring-detail').textContent.includes('Vzdálené spuštění')",
   5:"!monitoringWorkflowForm.hidden&&monitoringWorkflowForm.elements.collection_node.value==="+json.dumps(peer)+"&&monitoringWorkflowForm.elements.trigger.value==='scheduled'&&monitoringWorkflowForm.elements.keywords.value==='first'",
   6:"monitoringWorkflowForm.hidden&&!monitoringDirty&&monitoringView.definitions.length===2&&monitoringView.definitions.some(r=>r.definition.schedule.trigger==='manual')"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==7:print('workflow browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:monitoringStatus?.textContent,detail:document.querySelector('#monitoring-detail')?.textContent})",lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(45000,timeout);result=app.exec()
  page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('workflow browser OK',result.stdout)

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
  from tests.test_monitoring_filters import pipeline
  cfg=definition();cfg['selection']['pipeline']=pipeline();watch_id=str(uuid4())
  saved=MonitoringDefinitions(f.node).save(dict(project_id=f.project,base_head=f.git.head(),watch_id=watch_id,
    previous=[],privacy='project',definition=cfg),str(uuid4()))
  server.monitoring.rss_runtime.fetcher=lambda *a,**kw:dict(status=200,raw=rss(),validators={'if-none-match':'"browser"'})
  server.monitoring.rss_runtime.configure(dict(project_id=f.project,watch_id=watch_id,input_id=cfg['inputs'][0]['id'],
    definition_ref=saved['definition_ref'],enabled=True,mode='pipeline'),confirm=True)
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
   2:"document.querySelector('#monitoring-findings-list button').click()",
   3:"document.querySelector('#monitoring-detail input').value='Other';[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Vyhodnotit ukázku').click()",
   4:"document.querySelector('#monitoring-new').click()",
   5:"monitoringForm.elements.name.value='Browser test';monitoringForm.elements.goal.value='Sledovat ověřené změny';monitoringForm.elements.start.value='2026-03-23';monitoringForm.elements.presentation.checked=true;monitoringForm.dispatchEvent(new Event('input',{bubbles:true}));monitoringForm.requestSubmit()",
   6:"document.querySelector('#sidebar-monitoring-list button').click()",
   7:"[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Spustit nyní').click()",
   8:"document.querySelector('#sidebar-report-list button').click()",
   9:"document.querySelector('#monitoring-detail input[type=checkbox]').click();[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Vydat zprávu').click()",
   10:"[...document.querySelectorAll('#monitoring-detail button')].find(b=>b.textContent==='Otevřít navázanou prezentaci').click()"}
  checks={
   0:"typeof loadMonitoring==='function'",
   1:"activeProject&&monitoringView&&monitoringView.project_id===activeProject.id&&document.querySelector('#monitoring-rss-list').textContent.includes('kontrola každých 15 min')",
   2:"document.querySelector('#monitoring-detail h3')?.textContent.includes('Náhled pravidel')",
   3:"document.querySelector('#monitoring-detail pre')?.textContent.includes('discarded')&&document.querySelector('#monitoring-detail pre')?.textContent.includes('topic')",
   4:"!monitoringForm.hidden",
   5:"monitoringView?.watches.length===1&&!monitoringDirty&&monitoringForm.hidden",
   6:"[...document.querySelectorAll('#monitoring-detail button')].some(b=>b.textContent==='Spustit nyní')",
   7:"monitoringView?.reports.some(r=>r.state==='review')",
   8:"document.querySelector('#presentations-tab').getAttribute('aria-selected')==='true'&&document.querySelector('#monitoring-detail pre')?.textContent.includes('Nebyla doložena významná změna.')&&document.querySelector('#monitoring-detail input[type=checkbox]')",
   9:"monitoringView?.reports.some(r=>r.state==='completed'&&r.presentation_id)&&[...document.querySelectorAll('#monitoring-detail button')].some(b=>b.textContent==='Otevřít navázanou prezentaci')",
   10:"presentationEditorDeck&&presentationEditorArtifact===monitoringView.reports[0].presentation_id&&document.querySelector('#presentation-report-link')&&!document.querySelector('#presentation-panel').hidden"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==11:print('monitoring browser OK',flush=True);app.exit(0);return
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
