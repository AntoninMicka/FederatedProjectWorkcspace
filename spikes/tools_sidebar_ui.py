# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One categorized tool list and entry point to existing editors."""
CATEGORIES = [('julia','Modely a výpočty','sidebar-tool-list'),
              ('source','Zdroje pro těžbu','sidebar-monitoring-source-list'),
              ('filter','Filtry','sidebar-monitoring-filter-list'),
              ('pool','Pooly zpráv','sidebar-monitoring-pool-list'),
              ('processing','Zpracování zpráv','sidebar-monitoring-processing-list'),
              ('task','Komplexní úlohy','sidebar-monitoring-list'),
              ('legacy','Starší sledování','sidebar-legacy-monitoring-list')]
TREE = '<ul id="sidebar-tools-tree" aria-label="Nástroje podle kategorií">'+''.join(
    '<li><details open data-tool-category="'+kind+'"><summary>'+label+'</summary><ul id="'+id_+'" aria-label="'+label+'"></ul></details></li>'
    for kind,label,id_ in CATEGORIES)+'</ul>'
NEW_ACTIONS = ''.join('<button type="button" role="menuitem" data-new-monitoring-block="'+kind+'"'+(' id="sidebar-monitoring-new"' if kind=='task' else '')+' disabled>'+label+'</button>'
    for kind,label in [('source','Nový zdroj pro těžbu'),('filter','Nový filtr'),('pool','Nový pool zpráv'),('processing','Nové zpracování zpráv'),('task','Nová komplexní úloha')])
NEW_ACTIONS += '<button type="button" role="menuitem" data-new-monitoring-block="compose" disabled>Sestavit úlohu pomocí LLM</button><button id="monitoring-workflow-new" type="button" role="menuitem" disabled>Nové starší zadání těžby a zpracování</button><button id="monitoring-new" type="button" role="menuitem" disabled>Nové původní sledování</button>'
CSS='''
#sidebar-tools{position:relative;overflow:visible}
#sidebar-tools>.sidebar-tool-options{position:absolute;top:70px;left:0;right:0;width:auto;max-height:min(60vh,420px);overflow-y:auto;z-index:60}
#sidebar-tools-tree,#sidebar-tools-tree ul{list-style:none;padding:0;margin:0}
#sidebar-tools-tree{flex:1;min-height:0;overflow-y:auto;scrollbar-width:thin;margin-top:14px}
#sidebar-tools-tree>li>details>summary{cursor:pointer;color:#a9bdca;font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding:10px 4px}
#sidebar-tools-tree ul{overflow:visible;flex:none}
#sidebar-tools-tree .sidebar-list-main{display:block;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px;text-align:left;overflow-wrap:anywhere}
#sidebar-tools-tree .sidebar-list-main:hover{background:#274154}
#sidebar-tools-tree .sidebar-item-id{font-size:10px}
'''
JS=r'''
let selectedToolKey=null;
function updateToolSelection(){
 for(const button of document.querySelectorAll('#sidebar-tools-tree [data-tool-key]'))button.setAttribute('aria-current',String(button.dataset.toolKey===selectedToolKey));
}
function toolSidebarRow(key,title,open,actions=[]){
 const row=document.createElement('li'),button=document.createElement('button');row.className='sidebar-list-row';
 button.type='button';button.className='sidebar-list-main';button.textContent=title;button.dataset.toolKey=key;
 button.setAttribute('aria-current',String(key===selectedToolKey));
 const show=async()=>{if(!await canLeaveWorkspaceEditors())return;await open();selectedToolKey=key;updateToolSelection();};
 button.addEventListener('click',show);row.append(button,sidebarItemMenu(title,[{label:'Zobrazit',run:show},...actions]));return row;
}
function updateToolsCount(){
 const count=document.querySelectorAll('#sidebar-tools-tree .sidebar-list-row').length;
 document.querySelector('#sidebar-tools-status').textContent='Počet nástrojů: '+count;
}
async function openMonitoringTool(row,edit=false){
 if(!await canLeaveWorkspaceEditors())return;
 monitoringOpen();blockTab=row.value.kind;blockSelectedId=row.id;renderMonitoringBlocks();
 if(edit&&!blockReadOnly())await editMonitoringBlock(row.value.kind,row);
}
function renderMonitoringToolTree(){
 for(const kind of ['source','filter','pool','processing','task']){
  const list=document.querySelector(kind==='task'?'#sidebar-monitoring-list':'#sidebar-monitoring-'+kind+'-list');list.replaceChildren();
  for(const row of blockCatalog?.blocks.filter(b=>b.value.kind===kind)||[]){
   const item=toolSidebarRow('block:'+row.id,row.value.title,()=>openMonitoringTool(row),[
    {label:'Upravit',disabled:blockReadOnly(),run:()=>openMonitoringTool(row,true)},
    {label:row.migration_pending?'Smazat · dokončete převod':row.used_by?.length?'Smazat · nejprve odpojte využití':'Smazat',disabled:blockReadOnly()||Boolean(row.used_by?.length)||Boolean(row.migration_pending),run:()=>deleteMonitoringTool(row)}]);
   if(kind==='task')item.dataset.composableTask=row.id;
   list.append(item);
  }
 }
 const legacy=document.querySelector('#sidebar-legacy-monitoring-list');legacy.replaceChildren();
 for(const watch of monitoringView?.watches||[])legacy.append(toolSidebarRow('watch:'+watch.id,watch.name,()=>{monitoringOpen();showMonitoringWatch(watch);},[
  {label:'Upravit',disabled:!monitoringView.can_manage||activeProject?.readOnly,run:async()=>{if(!await canLeaveWorkspaceEditors())return;monitoringOpen();editMonitoring(watch);}},
  {label:'Smazat',disabled:!monitoringView.can_manage||activeProject?.readOnly,run:()=>deleteLegacyTool('watch',watch.id,watch.name)}]));
 for(const row of monitoringView?.definitions||[])legacy.append(toolSidebarRow('definition:'+row.watch_id,row.definition.title,()=>{monitoringOpen();showMonitoringDefinition(row);},[{label:'Smazat',disabled:!monitoringView.can_manage||activeProject?.readOnly,run:()=>deleteLegacyTool('definition',row.watch_id,row.definition.title)}]));
 document.querySelector('#julia-editor-new').disabled=!activeProject||Boolean(activeProject.readOnly);
 const readonly=!activeProject||activeProject.readOnly||!monitoringView?.can_manage||!blockCatalog;
 for(const button of document.querySelectorAll('[data-new-monitoring-block]'))button.disabled=Boolean(readonly);
 updateToolsCount();
}
async function createMonitoringTool(kind){
 if(!activeProject||activeProject.readOnly||!await canLeaveWorkspaceEditors())return;
 const project=activeProject;
 if(!blockCatalog)await loadMonitoring();
 if(activeProject!==project||!blockCatalog||blockReadOnly())return;
 sidebarToolNewOptions.hidden=true;sidebarNewTool.setAttribute('aria-expanded','false');
 monitoringOpen();blockSelectedId=null;
 if(kind==='compose'){
  blockTab='task';renderMonitoringBlocks();document.querySelector('#monitoring-compose').hidden=false;document.querySelector('#monitoring-compose textarea').focus();
 }else{blockTab=kind;renderMonitoringBlocks();await editMonitoringBlock(kind);}
 closeMobileSidebar();closeCompactSidebarMenu();
}
let toolDeleteAttempt=null;
async function deleteMonitoringTool(row){
 if(blockReadOnly()||!await canLeaveWorkspaceEditors())return;
 if(row.used_by?.length){blockStatus('Nejdříve odpojte blok od jeho uživatelů.');return;}
 if(!window.confirm('Smazat „'+row.value.title+'“ z aktuálního katalogu? Historie, dřívější běhy a obsah poolů podle retence zůstanou zachované.'))return;
 const pid=activeProject.id;
 const block={id:row.id,previous:[row.ref],privacy:row.privacy,value:{...row.value,deleted:true}};
 const signature=JSON.stringify({pid,block});
 if(toolDeleteAttempt?.signature!==signature)toolDeleteAttempt={signature,payload:{base_head:blockCatalog.commit_id,block,operation_id:crypto.randomUUID(),confirm:true}};
 try{
  await monitoringRequest('block-delete',toolDeleteAttempt.payload);toolDeleteAttempt=null;
  if(activeProject?.id!==pid)return;
  blockSelectedId=null;selectedToolKey=null;await loadMonitoring();
  blockStatus('Položka byla odstraněna z aktuálního katalogu. Historie zůstala zachována.');
 }catch(error){if(activeProject?.id===pid)blockStatus(error.message);}
}
let legacyDeleteAttempt=null;
async function deleteLegacyTool(kind,id,title){
 if(!activeProject||activeProject.readOnly||!monitoringView?.can_manage||!await canLeaveWorkspaceEditors())return;
 const pid=activeProject.id,key=pid+':'+kind+':'+id;monitoringOpen();
 try{
  if(legacyDeleteAttempt?.key!==key){
   const preview=await monitoringRequest('legacy-delete-preview',{kind,id});
   if(activeProject?.id!==pid)return;
   if(preview.blockers.length){monitoringStatus.textContent='Nelze smazat: '+preview.blockers.join('; ');return;}
   legacyDeleteAttempt={key,payload:{base_head:preview.base_head,sources:preview.sources,operation_id:crypto.randomUUID(),confirm:true}};
  }
  if(!window.confirm('Smazat starší úlohu „'+title+'“ z katalogu a dalšího plánování? Původní definice, historie běhů a vydané zprávy zůstanou zachované.'))return;
  await monitoringRequest('legacy-delete',legacyDeleteAttempt.payload);legacyDeleteAttempt=null;
  if(activeProject?.id===pid){selectedToolKey=null;document.querySelector('#monitoring-detail').replaceChildren();await loadMonitoring();monitoringStatus.textContent='Úloha byla vyřazena; historie zůstala zachována.';}
 }catch(error){if(activeProject?.id===pid)monitoringStatus.textContent=error.message;}
}
'''
