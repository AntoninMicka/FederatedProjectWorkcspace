# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Current block tools and concrete report editions; no legacy watch editors."""
from spikes.monitoring_blocks_ui import HTML as BLOCKS_HTML, CSS as BLOCKS_CSS, JS as BLOCKS_JS

HTML = ('<div id="monitoring-panel" role="tabpanel" aria-labelledby="monitoring-tab" hidden>'
        '<header><h2 id="monitoring-page-title">Nástroje</h2><p id="monitoring-page-description">Zdroje → filtry → pooly → zpracování → komplexní úlohy.</p></header>'
        '<p id="monitoring-status" role="status" aria-live="polite"></p>' + BLOCKS_HTML + '</div>')
CSS='''
.monitoring-grid{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,2fr);gap:1rem}
#monitoring-panel{max-width:1200px;margin:auto;padding:1rem}#monitoring-panel label{display:block;margin:.7rem 0}
#monitoring-panel input:not([type=checkbox]),#monitoring-panel textarea,#monitoring-panel select{box-sizing:border-box;width:100%;max-width:100%}
#monitoring-panel textarea{min-height:5rem}#monitoring-panel li{margin:.5rem 0}#monitoring-panel button{margin:.2rem}
#monitoring-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:70vh;overflow:auto;background:var(--panel,#f4f6f7);padding:1rem}
@media(max-width:760px){.monitoring-grid{grid-template-columns:1fr}}
'''

CSS += BLOCKS_CSS
JS = r'''
let monitoringView=null,monitoringDirty=false,monitoringAttempt=null;
const monitoringStatus=document.querySelector('#monitoring-status');
let monitoringLoadSequence=0,monitoringLoads=0;
function monitoringOpen(section='tools'){showWorkspacePage(projectView);selectSidebarTab(document.querySelector(section==='outputs'?'#presentations-tab':'#tools-tab'));selectMainTab(document.querySelector('#monitoring-tab'));}
function monitoringButton(label,action,disabled=false){const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=disabled;b.addEventListener('click',async()=>{try{await action();}catch(error){monitoringStatus.textContent=error.message;}});return b;}
async function monitoringRequest(action,payload={}){if(!activeProject)throw Error('Otevřete projekt.');return projectRequest('/v1/monitoring/'+action,{project_id:activeProject.id,...payload},120000);}
function clearMonitoring(){
 monitoringLoadSequence++;blockLoadSequence++;blockCatalog=null;blockSelectedId=null;blockEdit=null;blockProposal=null;blockParent=null;blockSaving=null;blockComposeRun=null;monitoringView=null;
 hideMonitoringEntityEditors();document.querySelector('#monitoring-block-content').replaceChildren();document.querySelector('#monitoring-compose').hidden=true;document.querySelector('#monitoring-composition-review').hidden=true;
 renderMonitoringToolTree();document.querySelector('#sidebar-report-list')?.replaceChildren();
}
async function canLeaveMonitoring(){return canLeaveMonitoringBlocks();}
async function loadMonitoring(){
 if(!activeProject)return;const projectId=activeProject.id,sequence=++monitoringLoadSequence;monitoringLoads++;
 try{const result=await monitoringRequest('view',{mode:'blocks'});if(activeProject?.id!==projectId||sequence!==monitoringLoadSequence)return;
  monitoringView=result;activeProject.head=result.commit_id;blockCatalog=result.block_catalog;renderMonitoring();
 }catch(error){if(activeProject?.id===projectId&&sequence===monitoringLoadSequence)monitoringStatus.textContent=error.message;}
 finally{monitoringLoads--;}
}
function renderMonitoring(){if(!monitoringView)return;renderMonitoringBlocks();}
function refreshVisibleMonitoring(){
 if(activeProject&&!document.hidden&&document.querySelector('#monitoring-panel')?.getClientRects().length&&!blockEdit&&!blockProposal&&!blockComposeRun&&!blockSaving&&!monitoringLoads)return loadMonitoring();
}
function refreshMonitoringAfterSync(event){if(activeProject?.id===event.detail?.projectId&&event.detail?.status?.state==='idle')return refreshVisibleMonitoring();}
async function renderPresentationReportLink(){
 document.querySelector('#presentation-report-link')?.remove();
 const pid=activeProject?.id,aid=presentationEditorArtifact;
 const source=presentationEditorView?.documents?.find(d=>d.id===aid)?.report_source;
 if(!pid||!source)return;
 if(monitoringView?.project_id!==pid||monitoringView.commit_id!==activeProject.head)await loadMonitoring();
 if(activeProject?.id!==pid||presentationEditorArtifact!==aid)return;
 document.querySelector('#presentation-report-link')?.remove();
 const panel=document.createElement('aside');panel.id='presentation-report-link';
 const output=monitoringView?.project_id===pid?monitoringView.outputs?.find(r=>r.id===source.artifact_id):null;
 const link=output?.presentations?.find(p=>p.artifact_id===aid);
 panel.append(blockText('p',link?.potentially_stale?'Zdrojová zpráva má novější nebo změněnou revizi. Tato prezentace zůstává původní.':output?'Prezentace odvozená z vydané zprávy.':'Zdrojové vydání není v aktuálním přehledu dostupné.'));
 panel.append(blockText('p','Zdrojová revize: '+source.commit_id.slice(0,12)+' · '+source.sha256.slice(0,12)));
 if(output)panel.append(monitoringButton(link?.potentially_stale?'Otevřít aktuální zdrojovou zprávu':'Otevřít zdrojovou zprávu',()=>activeProject?.id===pid&&presentationEditorArtifact===aid?openReportOutput({...output,source:'git'}):undefined));
 document.querySelector('#presentation-panel').prepend(panel);
}
function showMonitoringReport(report,target=document.querySelector('#report-output-content')){
 if(!report)return;target.replaceChildren();const body=document.createElement('pre');body.textContent=report.markdown||'Obsah zprávy není dostupný.';target.append(body);
}
setInterval(refreshVisibleMonitoring,15000);
document.addEventListener('visibilitychange',refreshVisibleMonitoring);
'''
JS += BLOCKS_JS
