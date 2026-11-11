# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class BlocksBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_separate_catalogs_inline_creation_shared_filter_and_report_in_real_browser(self):
        script=r'''
import json
from copy import deepcopy
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
from spikes.chat_service import ChatService
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.monitoring=Monitoring(f.node,server.projects,clock=lambda:1794160000)
  server.monitoring._composable_runtime=ComposableMonitoring(server.monitoring,fetcher=lambda *a,**kw:response())
  server.chat_service=ChatService(f.node,server.projects)
  specs=blocks(f.node);second=deepcopy(specs[0]);second['id']=str(uuid4());second['value']['title']='Druhý kanál';second['value']['config']['locator']='https://example.org/second'
  server.monitoring.composable.blocks.save(f.project,f.git.head(),specs+[second],str(uuid4()))
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConfirm(self,url,text):return True
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1280,900);view.show();phase=0;busy=False
  ids=json.dumps([b['id'] for b in specs])
  commands={
   1:'window.blockTestIds='+ids+';window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(f.project)+').then(async()=>{await navigateMainTab(document.getElementById("monitoring-tab"));window.blocksOpened=true})',
   2:"monitoringOpen();blockTab='source';renderMonitoringBlocks()",
   3:"editMonitoringBlock('filter',blockCatalog.blocks.find(b=>b.id===blockTestIds[2]))",
   4:"(()=>{for(const o of blockEditor.elements.source_ids.options)o.selected=true;blockEditor.requestSubmit()})()",
   5:"editMonitoringBlock('task',blockCatalog.blocks.find(b=>b.id===blockTestIds[4]))",
   6:"[...blockFields.querySelectorAll('button')].find(b=>b.textContent==='Vytvořit nové: Pooly zpráv').click()",
   7:"blockEditor.elements.title.value='Nový společný pool';blockEditor.requestSubmit()",
   8:"blockEditor.elements.title.value='Upravená komplexní úloha';blockEditor.requestSubmit()",
   9:"blockTab='source';renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content article')].find(a=>a.querySelector('h3').textContent==='ČT24').querySelectorAll('button')[2].click()",
   10:"[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Zkontrolovat splatné kanály').click()",
   11:"blockTab='processing';renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Sestavit návrh zprávy').click()",
   12:"[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Vydat posouzenou zprávu').click()",
   13:"document.querySelector('#sidebar-monitoring-filter-list .sidebar-list-main').click()",
   14:"document.querySelector('#sidebar-monitoring-filter-list summary').click();[...document.querySelectorAll('#sidebar-monitoring-filter-list [role=menuitem]')].find(b=>b.textContent==='Upravit').click()",
   15:"document.querySelector('#sidebar-new-tool').click()",
   16:"document.querySelector('[data-new-monitoring-block=filter]').click()",
   17:"(async()=>{window.createdToolKinds=[];for(const kind of ['source','pool','processing','task','compose']){await createMonitoringTool(kind);createdToolKinds.push(kind==='compose'?!document.querySelector('#monitoring-compose').hidden:blockEdit?.value.kind===kind);}window.toolsCreationDone=true;})()",
   18:"(async()=>{await canLeaveWorkspaceEditors();activeProject.readOnly=true;renderMonitoringToolTree();window.readOnlyToolsChecked=true;})()",
   19:"activeProject.readOnly=false;renderMonitoringToolTree();document.querySelector('#sidebar-monitoring-list summary').click();[...document.querySelectorAll('#sidebar-monitoring-list [role=menuitem]')].find(b=>b.textContent==='Smazat').click()",
   20:"document.querySelector('#sidebar-monitoring-filter-list summary').click();[...document.querySelectorAll('#sidebar-monitoring-filter-list [role=menuitem]')].find(b=>b.textContent==='Smazat').click()",
  }
  checks={
   0:"typeof editMonitoringBlock==='function'",
   1:"window.blocksOpened&&blockCatalog?.blocks.length===6",
   2:"document.querySelectorAll('#sidebar-monitoring-list [data-composable-task]').length===1&&document.querySelectorAll('#sidebar-tools-tree [data-tool-key^=\"block:\"]').length===6&&document.querySelectorAll('#monitoring-block-tabs button').length===6&&document.querySelectorAll('#monitoring-block-content article').length===2",
   3:"!blockEditor.hidden&&blockEditor.elements.source_ids.options.length===2",
   4:"blockEditor.hidden&&blockCatalog.blocks.find(b=>b.id===blockTestIds[2]).value.config.source_ids.length===2",
   5:"!blockEditor.hidden&&blockEditor.elements.processing_ids.selectedOptions.length===1",
   6:"!blockEditor.hidden&&!!blockEditor.elements.retention_days",
   7:"!blockEditor.hidden&&blockEdit.value.kind==='task'&&[...blockEditor.elements.pool_ids.selectedOptions].some(o=>o.textContent==='Nový společný pool')",
   8:"blockEditor.hidden&&blockCatalog.blocks.some(b=>b.value.title==='Upravená komplexní úloha')",
   9:"blockCatalog.blocks.find(b=>b.id===blockTestIds[0]).runtime?.enabled===true",
   10:"blockCatalog.blocks.find(b=>b.id===blockTestIds[1]).message_count===1",
   11:"blockTab==='runs'&&document.querySelector('#monitoring-block-content').textContent.includes('Energie dnes')&&blockCatalog.jobs.some(j=>j.state==='review')",
   12:"blockCatalog.jobs.some(j=>j.state==='published')",
   13:"blockTab==='filter'&&document.querySelectorAll('#monitoring-block-content article').length===1&&document.querySelector('#sidebar-monitoring-filter-list .sidebar-list-main').getAttribute('aria-current')==='true'",
   14:"!blockEditor.hidden&&blockEdit.id===blockTestIds[2]",
   15:"!document.querySelector('#sidebar-tool-new-options').hidden&&document.querySelectorAll('#sidebar-tool-new-options [data-new-monitoring-block]').length===6",
   16:"!blockEditor.hidden&&blockEdit.value.kind==='filter'&&!blockEdit.previous.length&&document.querySelector('#sidebar-tool-new-options').hidden",
   17:"window.toolsCreationDone&&createdToolKinds.length===5&&createdToolKinds.every(Boolean)",
   18:"window.readOnlyToolsChecked&&[...document.querySelectorAll('[data-new-monitoring-block]')].every(b=>b.disabled)",
   19:"!blockCatalog.blocks.some(b=>b.id===blockTestIds[4])&&document.querySelectorAll('#sidebar-monitoring-list .sidebar-list-row').length===0",
   20:"!blockCatalog.blocks.some(b=>b.id===blockTestIds[2])&&[...document.querySelectorAll('#sidebar-monitoring-pool-list [role=menuitem]')].some(b=>b.textContent.includes('Smazat · nejprve')&&b.disabled)",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==14:view.grab().save('/tmp/fpw-tools-tree.png')
   if phase==16:view.grab().save('/tmp/fpw-tools-new-menu.png')
   if phase==21:print('blocks browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#monitoring-block-state')?.textContent,monitoring:monitoringStatus?.textContent,edit:blockEdit,content:document.querySelector('#monitoring-block-content')?.textContent})",lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(55000,timeout);result=app.exec()
  from shiboken6 import delete
  view.close();delete(view);delete(page);delete(profile);raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=70)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('blocks browser OK',result.stdout)
