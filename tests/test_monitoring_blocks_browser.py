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
from spikes.presentation_documents import PresentationDocuments
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.monitoring=Monitoring(f.node,server.projects,clock=lambda:1794160000)
  server.monitoring._composable_runtime=ComposableMonitoring(server.monitoring,fetcher=lambda *a,**kw:response())
  server.chat_service=ChatService(f.node,server.projects)
  server.presentation_documents=PresentationDocuments(f.node)
  specs=blocks(f.node);second=deepcopy(specs[0]);second['id']=str(uuid4());second['value']['title']='Druhý kanál';second['value']['config']['locator']='https://example.org/second'
  server.monitoring.composable.blocks.save(f.project,f.git.head(),specs+[second],str(uuid4()))
  from spikes import monitoring_design_samples
  monitoring_design_samples.read_article=lambda url:dict(text='Ukázkový plný text',raw_sha256='a'*64)
  designed=deepcopy(specs[2]);designed['id']=str(uuid4());designed['value']['title']='Filtr podle ukázek'
  server.monitoring.composable._model=lambda *a,**kw:json.dumps(dict(blocks=[designed],explanation='Návrh ověřeného kanálu.'))
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConfirm(self,url,text):return True
   def javaScriptPrompt(self,url,text,default):return (True,'Nová komplexní úloha')
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
   6:"document.querySelector('[data-monitoring-catalog=pool] .monitoring-catalog-actions button').click()",
   7:"blockEditor.elements.title.value='Nový společný pool';blockEditor.requestSubmit()",
   8:'renderMonitoringBlocks()',
   9:'window.extraPoolId=blockCatalog.blocks.find(b=>b.value.title===\'Nový společný pool\').id;[...document.querySelectorAll(\'[data-monitoring-row=\\"\'+blockTestIds[1]+\'\\"] button\')].find(b=>b.textContent===\'Odebrat ze sestavy\').click()',
   10:'[...document.querySelectorAll(\'[data-monitoring-row=\\"\'+window.extraPoolId+\'\\"] button\')].find(b=>b.textContent===\'Odebrat ze sestavy\').click()',
   11:"[...document.querySelectorAll('[data-monitoring-catalog=pool] .monitoring-catalog-actions button')].find(b=>b.textContent==='Přidat existující').click()",
   12:"[...document.querySelectorAll('[data-monitoring-existing=pool] button')].find(b=>b.textContent==='Přidat do sestavy').click()",
   13:"blockTab='source';blockSelectedId=blockTestIds[0];renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Zapnout sběr').click()",
   14:"[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Zkontrolovat splatné kanály').click()",
   15:"blockTab='processing';blockSelectedId=blockTestIds[3];renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Sestavit návrh zprávy').click()",
   16:"(async()=>{await loadMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Vydat posouzenou zprávu').click();})()",
   17:"document.querySelector('#sidebar-monitoring-filter-list .sidebar-list-main').click()",
   18:"document.querySelector('#sidebar-monitoring-filter-list summary').click();[...document.querySelectorAll('#sidebar-monitoring-filter-list [role=menuitem]')].find(b=>b.textContent==='Upravit').click()",
   19:"document.querySelector('#sidebar-new-tool').click()",
   20:"document.querySelector('[data-new-monitoring-block=filter]').click()",
   21:"(async()=>{window.createdToolKinds=[];for(const kind of ['source','pool','processing','task','compose']){await createMonitoringTool(kind);createdToolKinds.push(kind==='compose'?!document.querySelector('#monitoring-compose').hidden:kind==='task'?!blockEdit&&blockTab==='task':blockEdit?.value.kind===kind);}window.toolsCreationDone=true;})()",
   22:"(async()=>{await canLeaveWorkspaceEditors();activeProject.readOnly=true;renderMonitoringToolTree();window.readOnlyToolsChecked=true;})()",
   23:'activeProject.readOnly=false;renderMonitoringToolTree();const taskMenu=document.querySelector(\'[data-composable-task="\'+blockTestIds[4]+\'"]\');taskMenu.querySelector("summary").click();[...taskMenu.querySelectorAll("[role=menuitem]")].find(b=>b.textContent==="Smazat").click()',
   24:"document.querySelector('#sidebar-monitoring-filter-list summary').click();[...document.querySelectorAll('#sidebar-monitoring-filter-list [role=menuitem]')].find(b=>b.textContent==='Smazat').click()",
   25:"(async()=>{await navigateSidebarTab(document.querySelector('#presentations-tab'));document.querySelector('#sidebar-report-list .sidebar-list-main').click()})()",
   26:"[...document.querySelectorAll('#report-output-actions button')].find(b=>b.textContent==='Vytvořit prezentaci ze zprávy').click()",
   27:"window.reportPresentationId=presentationEditorArtifact;[...document.querySelectorAll('#presentation-report-link button')].find(b=>b.textContent==='Otevřít zdrojovou zprávu').click()",
   28:"[...document.querySelectorAll('#report-output-actions button')].find(b=>b.textContent.startsWith('Otevřít prezentaci:')).click()",
   29:"monitoringOpen();editMonitoringBlock('processing',blockCatalog.blocks.find(b=>b.id===blockTestIds[3]))",
   30:"blockEditor.elements.schedule_kind.value='weekly';blockEditor.requestSubmit()",
   31:"blockTab='filter';renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-toolbar button')].find(b=>b.textContent==='Navrhnout filtr pomocí LLM').click()",
   32:"(()=>{const f=document.querySelector('#monitoring-compose');f.elements.goal.value='Vybrat zprávy o energetice';for(const o of f.elements.sample_sources.options)o.selected=o.value===blockTestIds[0];f.requestSubmit()})()",
   33:"document.querySelector('#monitoring-composition-save').click()",
    34:"monitoringOpen();editMonitoringBlock('processing',blockCatalog.blocks.find(b=>b.id===blockTestIds[3]))",
   35:"blockEditor.elements.schedule_kind.value='manual';blockEditor.requestSubmit()",
   36:"editMonitoringBlock('processing')",
   37:"(()=>{blockEditor.elements.title.value='Měsíční z vydaných zpráv';for(const o of blockEditor.elements.pool_ids.options)o.selected=false;for(const o of blockEditor.elements.report_task_ids.options)o.selected=o.value===blockTestIds[3];blockEditor.elements.lookback_days.value=31;blockEditor.requestSubmit()})()",
   38:"window.chainTaskId=blockCatalog.blocks.find(b=>b.value.title==='Měsíční z vydaných zpráv').id;blockTab='processing';blockSelectedId=chainTaskId;renderMonitoringBlocks();[...document.querySelectorAll('#monitoring-block-content button')].find(b=>b.textContent==='Sestavit návrh zprávy').click()",
   39:"openReportOutput(reportOutputRows().find(o=>o.job?.intent.block.id===chainTaskId))",
  }

  checks={
   0:"typeof editMonitoringBlock==='function'",
   1:"window.blocksOpened&&blockCatalog?.blocks.length===6",
   2:"document.querySelectorAll('#sidebar-monitoring-list [data-composable-task]').length===1&&document.querySelectorAll('#sidebar-tools-tree [data-tool-key^=\"block:\"]').length===6&&!document.querySelector('#monitoring-block-tabs')&&document.querySelector('#monitoring-page-title').textContent==='Zdroje'&&document.querySelectorAll('[data-monitoring-catalog=source] tbody tr').length===2&&document.querySelectorAll('[data-monitoring-entity-editor]').length===4&&!document.querySelector('#monitoring-task-editor')",
   3:"blockEditor.id==='monitoring-filter-editor'&&!blockEditor.hidden&&blockEditor.elements.source_ids.options.length===2",
   4:"blockEditor.hidden&&blockCatalog.blocks.find(b=>b.id===blockTestIds[2]).value.config.source_ids.length===2",
   5:"blockEditor.hidden&&!blockEdit&&document.querySelectorAll('.monitoring-task-aggregate [data-monitoring-catalog]').length===4&&![...document.querySelectorAll('.monitoring-task-aggregate button')].some(b=>b.textContent==='Upravit složení')&&document.querySelectorAll('.monitoring-task-aggregate input').length===0&&[...document.querySelectorAll('.monitoring-task-aggregate [data-monitoring-catalog]')].every(s=>s.querySelectorAll('.monitoring-catalog-actions button').length===2&&s.querySelector('.monitoring-catalog-actions').compareDocumentPosition(s.querySelector('table'))&Node.DOCUMENT_POSITION_FOLLOWING)&&!!document.querySelector('[data-monitoring-flow]')",
   6:"blockEditor.id==='monitoring-pool-editor'&&!blockEditor.hidden&&!!blockEditor.elements.retention_days",
   7:"blockEditor.hidden&&!blockEdit&&blockCatalog.blocks.find(b=>b.id===blockTestIds[4]).value.config.pool_ids.length===2&&document.querySelectorAll('[data-monitoring-catalog=pool] tbody tr').length===2",
   8:"!blockEdit&&document.querySelectorAll('.monitoring-task-aggregate [data-monitoring-catalog]').length===4",
   9:"!!window.extraPoolId&&document.querySelector('#monitoring-block-state').textContent.includes('vyžaduje')",
   10:'!blockSaving&&blockCatalog.blocks.find(b=>b.id===blockTestIds[4]).value.config.pool_ids.length===1',
   11:"!!document.querySelector('[data-monitoring-existing=pool] select')&&document.querySelector('[data-monitoring-existing=pool] select').value===window.extraPoolId",
   12:"!blockSaving&&blockCatalog.blocks.find(b=>b.id===blockTestIds[4]).value.config.pool_ids.length===2&&blockCatalog.blocks.filter(b=>b.value.title==='Nový společný pool').length===1",
   13:"blockCatalog.blocks.find(b=>b.id===blockTestIds[0]).runtime?.enabled===true",
   14:"blockCatalog.blocks.find(b=>b.id===blockTestIds[1]).message_count===1&&document.querySelector('[data-monitoring-catalog=source]').textContent.includes('Nové revize: 1')",
   15:"[...document.querySelectorAll('#monitoring-block-content button')].some(b=>b.textContent==='Vydat posouzenou zprávu'&&b.disabled)&&document.querySelector('#monitoring-block-content').textContent.includes('Ochranné období')&&blockTab==='runs'&&document.querySelector('#monitoring-block-content').textContent.includes('Energie dnes')&&blockCatalog.jobs.some(j=>j.state==='review')",
   16:"blockCatalog.jobs.some(j=>j.state==='published')",
   17:"blockTab==='filter'&&document.querySelectorAll('#monitoring-block-content article').length===1&&document.querySelector('#sidebar-monitoring-filter-list .sidebar-list-main').getAttribute('aria-current')==='true'",
   18:"!blockEditor.hidden&&blockEdit.id===blockTestIds[2]",
   19:"!document.querySelector('#sidebar-tool-new-options').hidden&&document.querySelectorAll('#sidebar-tool-new-options [data-new-monitoring-block]').length===6",
   20:"!blockEditor.hidden&&blockEdit.value.kind==='filter'&&!blockEdit.previous.length&&document.querySelector('#sidebar-tool-new-options').hidden",
   21:"window.toolsCreationDone&&createdToolKinds.length===5&&createdToolKinds.every(Boolean)&&blockCatalog.blocks.filter(b=>b.value.kind==='task').length===2",
   22:"window.readOnlyToolsChecked&&[...document.querySelectorAll('[data-new-monitoring-block]')].every(b=>b.disabled)",
   23:"!blockCatalog.blocks.some(b=>b.id===blockTestIds[4])&&document.querySelectorAll('#sidebar-monitoring-list .sidebar-list-row').length===1",
   24:"!blockCatalog.blocks.some(b=>b.id===blockTestIds[2])&&[...document.querySelectorAll('#sidebar-monitoring-pool-list [role=menuitem]')].some(b=>b.textContent.includes('Smazat · nejprve')&&b.disabled)",
   25:"!document.querySelector('#report-output-view').hidden&&projectView.hidden&&document.querySelector('#report-output-content pre')?.textContent.includes('Energie dnes')&&document.querySelector('#report-output-title').textContent===blockCatalog.jobs.find(j=>j.state==='published'&&j.intent.kind==='processing').result.output.title&&document.querySelector('#report-output-inputs').textContent.includes('Přesné použité vstupy')&&document.querySelectorAll('#report-output-inputs tbody tr').length===1",
   26:"!document.querySelector('#presentation-panel').hidden&&presentationEditorDeck?.slides.some(s=>s.notes.includes('Zdrojová zpráva:'))&&!!document.querySelector('#presentation-report-link button')",
   27:"!document.querySelector('#report-output-view').hidden&&[...document.querySelectorAll('#report-output-actions button')].some(b=>b.textContent.startsWith('Otevřít prezentaci:'))",
   28:"!document.querySelector('#presentation-panel').hidden&&presentationEditorArtifact===window.reportPresentationId",
   29:"!blockEditor.hidden&&['manual','daily','weekly','monthly','quarterly','annual'].every(kind=>[...blockEditor.elements.schedule_kind.options].some(o=>o.value===kind))&&document.querySelector('[data-monitoring-catalog=processing]').textContent.includes('Zpráva vydána')&&document.querySelector('[data-monitoring-catalog=processing]').textContent.includes('Skutečný vykonavatel')",
   30:"blockEditor.hidden&&blockCatalog.blocks.find(b=>b.id===blockTestIds[3]).value.config.schedule.kind==='weekly'",
   31:"!document.querySelector('#monitoring-compose').hidden&&blockDesignKind==='filter'&&document.querySelector('#monitoring-compose').elements.sample_sources.options.length===2",
   32:"!!blockProposal&&blockProposal.calibration[0].results[0].decision==='selected'&&document.querySelector('#monitoring-composition-blocks').textContent.includes('Vybráno')&&document.querySelector('#monitoring-composition-blocks').textContent.includes('Ověřený kanál:')&&document.querySelector('#monitoring-composition-blocks').textContent.includes('Použít existující: Energetika')&&document.querySelector('#monitoring-block-state').textContent.includes('Návrh je připravený')",
   33:"!blockProposal&&blockCatalog.blocks.some(b=>b.value.title==='Filtr podle ukázek')",
    34:"!blockEditor.hidden&&blockEditor.id==='monitoring-processing-editor'",
   35:"blockEditor.hidden&&blockCatalog.blocks.find(b=>b.id===blockTestIds[3]).value.config.schedule.kind==='manual'",
   36:"!blockEditor.hidden&&blockEditor.elements.report_task_ids.options.length===1&&blockEditor.elements.report_task_ids.options[0].textContent==='Ranní zpráva'",
   37:"blockEditor.hidden&&blockCatalog.blocks.some(b=>b.value.title==='Měsíční z vydaných zpráv'&&b.value.config.report_task_ids[0]===blockTestIds[3])",
   38:"blockTab==='runs'&&blockCatalog.jobs.some(j=>j.intent.block?.id===chainTaskId&&j.state==='review'&&j.intent.report_inputs?.length===1)",
   39:"!document.querySelector('#report-output-view').hidden&&document.querySelectorAll('[data-report-input]').length===1&&document.querySelector('#report-output-inputs').textContent.includes(blockTestIds[3])&&document.querySelector('#report-output-content').textContent.includes('Energie dnes')",
  }

  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==16:
    runtime=server.monitoring.composable;instant=runtime.clock()+3600
    runtime.clock=runtime.pools.clock=lambda:instant
    runtime.tick(f.project,lane='processing')
   if phase==6:view.grab().save('/tmp/fpw-task-aggregate.png')
   if phase==18:view.grab().save('/tmp/fpw-tools-tree.png')
   if phase==20:view.grab().save('/tmp/fpw-tools-new-menu.png')
   if phase==27:view.grab().save('/tmp/fpw-report-presentation.png')
   if phase==29:view.grab().save('/tmp/fpw-report-output.png')
   if phase==33:view.grab().save('/tmp/fpw-monitoring-design-review.png')
   if phase==40:view.grab().save('/tmp/fpw-report-chain.png');print('blocks browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#monitoring-block-state')?.textContent,monitoring:monitoringStatus?.textContent,presentation:document.querySelector('#presentation-editor-status')?.textContent,report:document.querySelector('#report-output-status')?.textContent,link:document.querySelector('#presentation-report-link')?.textContent,edit:blockEdit,content:document.querySelector('#monitoring-block-content')?.textContent})",lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(55000,timeout);result=app.exec()
  from shiboken6 import delete
  view.close();delete(view);delete(page);delete(profile);raise SystemExit(result)
finally:f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=70)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('blocks browser OK',result.stdout)
