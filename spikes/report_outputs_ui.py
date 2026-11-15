# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Concrete report editions in the shared output tree; never a task shortcut."""
HTML='''<div id="report-output-view" hidden>
<header><h1 id="report-output-title">Zpráva</h1></header>
<p id="report-output-status" role="status" aria-live="polite"></p>
<div id="report-output-actions" class="form-actions"></div>
<section id="report-output-content" aria-label="Obsah zprávy"></section>
</div>'''
CSS='''
#report-output-view{max-width:1100px;width:100%;box-sizing:border-box;margin:0 auto;padding:clamp(12px,3vw,32px);overflow:auto}
#report-output-content pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.6}
#sidebar-output-tree,#sidebar-output-tree ul{list-style:none;margin:0;padding:0}
#sidebar-output-tree{flex:1;min-height:0;overflow:auto;scrollbar-width:thin;margin-top:14px}
#sidebar-output-tree ul{overflow:visible;flex:none}
#sidebar-output-tree summary{color:#a9bdca;font-size:11px;padding:10px 4px;cursor:pointer;text-transform:uppercase}
#sidebar-output-tree .sidebar-item-menu>summary{font-size:16px;text-transform:none;padding:8px}
#sidebar-output-tree .sidebar-list-main{display:block;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px;text-align:left;overflow-wrap:anywhere}
#sidebar-output-tree .sidebar-list-main:hover{background:#274154}
'''
JS=r'''
let selectedReportOutput=null,reportOutputSequence=0;
const reportReprocessRequests=new Map(),reportReprocessBusy=new Set();
function reportReprocessDeadline(job){
 return job.result?.protection?.until??(job.result?.output?.built_at?Date.parse(job.result.output.built_at)/1000+3600:null);
}
function reportReprocessButton(sourceRunId,until,readonly){
 const pid=activeProject.id,key=pid+':'+sourceRunId;
 const button=monitoringButton('Zpracovat znovu',async()=>{
  if(activeProject?.id!==pid||reportReprocessBusy.has(key))return;
  if(!window.confirm('Zpracovat znovu původní období z aktuálně dostupných vstupů? Vznikne nový návrh; model a hledání se mohou spustit znovu.'))return;
  if(activeProject?.id!==pid)return;
  if(!reportReprocessRequests.has(key))reportReprocessRequests.set(key,{source_run_id:sourceRunId,run_id:crypto.randomUUID(),confirm:true});
  reportReprocessBusy.add(key);button.disabled=true;
  const status=document.querySelector('#report-output-view')?.hidden?monitoringStatus:document.querySelector('#report-output-status');
  status.textContent='Zpracovávám nový návrh zprávy…';
  try{
   const result=await monitoringRequest('block-reprocess',reportReprocessRequests.get(key));
   reportReprocessRequests.delete(key);
   if(activeProject?.id!==pid)return;
   await loadMonitoring();if(activeProject?.id!==pid)return;
   const output=reportOutputRows().find(r=>r.id==='block:'+result.id);
   if(output)await openReportOutput(output);else status.textContent='Stav nového zpracování: '+result.state;
  }catch(error){
   if(activeProject?.id===pid)status.textContent=error.message;
   throw error;
  }finally{
   reportReprocessBusy.delete(key);
   button.disabled=readonly||!Number.isFinite(until)||Date.now()/1000<until;
  }
 },readonly||!sourceRunId||!Number.isFinite(until)||Date.now()/1000<until||reportReprocessBusy.has(key));
 return button;
}
function exportReportMarkdown(title,markdown){
 const a=document.createElement('a'),url=URL.createObjectURL(new Blob([markdown],{type:'text/markdown;charset=utf-8'}));
 a.href=url;a.download=title.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,180)+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function reportOutputRows(){
 const rows=(monitoringView?.outputs||[]).map(output=>{const local=monitoringView?.reports?.find(r=>r.report_ref?.artifact_id===output.id);return {...output,title:local?.output?.title||output.title,built_at:local?.output?.built_at||output.built_at,source:'git'};});
 for(const report of monitoringView?.reports||[]){
  if(!report.markdown||report.report_ref||!['review','failed','cancelled'].includes(report.state))continue;
  rows.push({id:'legacy:'+report.id,title:report.output?.title||report.name+' · čas sestavení není uložen',built_at:report.output?.built_at,state:report.state,source:'legacy-draft',report,markdown:report.markdown});
 }
 for(const job of blockCatalog?.jobs||[]){
  if(job.result?.replacement||job.intent.kind!=='processing'||job.state!=='review'||!job.result?.markdown||rows.some(r=>r.run_id===job.id))continue;
  rows.push({id:'block:'+job.id,title:job.result.output?.title||job.intent.block.value.title+' · čas sestavení není uložen',built_at:job.result.output?.built_at,state:'review',source:'block-draft',job,markdown:job.result.markdown});
 }
 return rows.sort((a,b)=>String(b.built_at||b.issued_at||'').localeCompare(String(a.built_at||a.issued_at||''))||a.id.localeCompare(b.id));
}
function renderReportOutputs(){
 const list=document.querySelector('#sidebar-report-list');list.replaceChildren();
 const rows=reportOutputRows();document.querySelector('#sidebar-report-heading').textContent='Zprávy ('+rows.length+')';
 for(const output of rows){
  const row=document.createElement('li'),button=document.createElement('button'),title=document.createElement('span'),state=document.createElement('small');
  row.className='sidebar-list-row';row.dataset.reportOutput=output.id;
  if(output.source==='git'&&output.kind==='block-report')row.dataset.composableReport=output.id;
  button.type='button';button.className='sidebar-list-main';button.setAttribute('aria-current',String(output.id===selectedReportOutput));
  title.textContent=output.title;state.className='sidebar-item-id';state.textContent=output.state==='review'?'Návrh k posouzení':output.source==='git'?'Vydaná zpráva':'Nevydaný návrh';if(output.job?.result.protection&&!output.job.result.protection.finalized)state.textContent='Ochranné období';state.textContent+=' · '+output.id.replace(/^(legacy|block):/,'').slice(0,8);button.append(title,state);
  button.addEventListener('click',()=>openReportOutput(output));
  row.append(button,sidebarItemMenu(output.title,[{label:'Zobrazit zprávu',run:()=>openReportOutput(output)},
   {label:'Export Markdown',run:async()=>{const report=output.source==='git'?await monitoringRequest('output',{output_id:output.id,expected_head:monitoringView.commit_id}):output;exportReportMarkdown(output.title,report.markdown);}}]));
  list.append(row);
 }
}
async function openReportOutput(output){
 const project=activeProject;if(!project||!await canLeaveWorkspaceEditors()||activeProject!==project)return;
 const pid=project.id,sequence=++reportOutputSequence,view=document.querySelector('#report-output-view'),content=document.querySelector('#report-output-content'),actions=document.querySelector('#report-output-actions'),status=document.querySelector('#report-output-status');
 selectedReportOutput=output.id;renderReportOutputs();selectSidebarTab(document.querySelector('#presentations-tab'));showWorkspacePage(view);
 document.querySelector('#report-output-title').textContent=output.title;content.replaceChildren();actions.replaceChildren();status.textContent='Načítám konkrétní zprávu…';
 try{
  const report=output.source==='git'?await monitoringRequest('output',{output_id:output.id,expected_head:monitoringView.commit_id}):output;
  if(activeProject?.id!==pid||sequence!==reportOutputSequence||view.hidden)return;
  status.textContent=output.source==='git'?'Vydaná zpráva':report.state==='review'?'Návrh zprávy — čeká na posouzení.':'Nevydaný návrh';
  actions.append(monitoringButton('Export Markdown',()=>exportReportMarkdown(output.title,report.markdown)));
  if(output.source==='block-draft'||output.kind==='block-report')actions.append(reportReprocessButton(output.job?.id||report.run_id,output.job?reportReprocessDeadline(output.job):report.reprocess_until,activeProject.readOnly||!monitoringView.can_manage));
  if(output.source==='git'){
   const decks=report.presentations||[];
   for(const deck of decks){
    actions.append(monitoringButton((deck.potentially_stale?'Otevřít starší prezentaci: ':'Otevřít prezentaci: ')+deck.title,()=>activeProject?.id===pid?openPresentationEditor(deck.artifact_id):undefined));
    if(deck.potentially_stale)actions.append(blockText('p','Prezentace vychází z dřívější revize zprávy; její obsah nebyl přepsán.'));
   }
   if(!decks.some(d=>!d.potentially_stale))actions.append(monitoringButton('Vytvořit prezentaci ze zprávy',async()=>{
    if(activeProject?.id!==pid)return;
    if(!window.confirm('Vytvořit prezentaci z přesně tohoto vydání zprávy bez dalšího výzkumu?'))return;
    if(activeProject?.id!==pid)return;
    const result=await monitoringRequest('presentation',{output_id:output.id,expected_head:report.commit_id,confirm:true});
    if(activeProject?.id!==pid)return;await loadMonitoring();if(activeProject?.id!==pid)return;
    presentationEditorView=null;await openPresentationEditor(result.artifact_id);
   },activeProject.readOnly||!monitoringView.can_manage));
  }
  const local=output.source==='legacy-draft'?output.report:monitoringView?.reports?.find(r=>r.report_ref?.artifact_id===output.id);
  if(local){showMonitoringReport({...local,name:output.title,markdown:report.markdown},content);return;}
  const pre=document.createElement('pre');pre.textContent=report.markdown;content.append(pre);
  if(output.job?.result.protection&&!output.job.result.protection.finalized){
   const guard=output.job.result.protection;
   actions.append(blockText('p','Ochranné období do '+new Date(guard.until*1000).toLocaleString()+(guard.changed?' · Přibyly nezahrnuté vstupy.':'')));
   if(guard.error)actions.append(blockText('p','Dokončení ochrany selhalo: '+guard.error));
  }
  if(output.source==='block-draft')actions.append(monitoringButton('Vydat posouzenou zprávu',async()=>{
   if(!window.confirm('Vydat přesně tento návrh zprávy do projektu?'))return;
   const result=await monitoringRequest('block-publish',{run_id:output.job.id,approval_digest:output.job.result.approval_digest,confirm:true});
   if(activeProject?.id!==pid)return;await loadMonitoring();if(activeProject?.id!==pid)return;const issued=reportOutputRows().find(r=>r.id===result.report_ref.artifact_id);if(issued)await openReportOutput(issued);
  },activeProject.readOnly||!monitoringView.can_manage||!!(output.job?.result.protection&&!output.job.result.protection.finalized)));
 }catch(error){if(activeProject?.id===pid&&sequence===reportOutputSequence)status.textContent=error.message;}
}
'''
