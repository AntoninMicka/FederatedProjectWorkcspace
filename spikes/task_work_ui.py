# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Persistent task panel and lifecycle controls for PLAN-TASK-WORK-01-A/B."""
TASK_WORK_HTML = '''<button id="task-work-panel-toggle" type="button" aria-controls="task-work-controls" aria-expanded="false" hidden>Pracovní úkol</button>
<button id="task-work-panel-backdrop" type="button" aria-label="Zavřít panel úkolu" tabindex="-1" hidden></button>
<section id="task-work-controls" role="complementary" aria-labelledby="task-work-panel-title" tabindex="-1" hidden>
<header class="task-work-panel-head"><h2 id="task-work-panel-title">Práce na úkolu</h2><button id="task-work-panel-collapse" type="button" aria-label="Sbalit panel úkolu">Sbalit</button></header>
<p id="task-work-status" role="status" aria-live="polite"></p>
<label for="task-work-session">Zobrazená pracovní relace</label><select id="task-work-session" aria-label="Vybraná pracovní relace"></select>
<div class="task-work-actions">
<button id="task-work-pause" type="button">Pozastavit</button>
<button id="task-work-resume" type="button">Pokračovat</button>
<button id="task-work-switch" type="button">Vybrat jiný úkol</button>
<button id="task-work-close" type="button">Ukončit relaci</button>
<button id="task-work-propose" type="button">Navrhnout dokončení</button>
<button id="task-work-refresh" type="button">Obnovit kontext</button>
<button id="task-work-recover" type="button">Dokončit obnovu</button>
<button id="task-work-cancel" type="button">Zrušit zahájení</button>
<button id="task-work-restore" type="button">Obnovit pracovní okno</button>
</div>
<div id="task-work-details" aria-label="Zadání a průběh zobrazené relace"></div>
<section class="task-work-related" aria-labelledby="task-work-related-title"><h3 id="task-work-related-title">Činnosti a výstupy</h3><p id="task-work-related-empty">K této relaci zatím nejsou připojené činnosti ani výstupy.</p><ul id="task-work-related-list"></ul></section>
<section id="task-work-proposals" aria-labelledby="task-work-proposals-title" hidden><h3 id="task-work-proposals-title">Návrhy dokončení</h3><ul id="task-work-proposal-list"></ul></section>
</section>'''

TASK_WORK_CSS = '''
#task-work-controls{box-sizing:border-box;flex:none;width:330px;min-width:0;height:100%;max-height:100dvh;overflow:auto;overscroll-behavior:contain;padding:16px;border-left:1px solid #b7d5c8;background:#f8fcfa;color:#162638;z-index:75}
#task-work-controls .task-work-panel-head{display:flex;align-items:center;gap:8px;margin-bottom:10px;color:#162638}
#task-work-panel-title{flex:1;margin:0;font-size:18px}#task-work-panel-collapse{padding:7px 10px;min-height:36px}
#task-work-controls p{margin:0 0 8px;overflow-wrap:anywhere}#task-work-controls h3{font-size:15px;margin:16px 0 8px}
#task-work-controls label{display:block;margin:8px 0 4px}#task-work-controls select{width:100%;min-width:0;max-width:100%}
.task-work-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:10px}.task-work-actions button{margin:0;padding:7px 9px;font-size:12px;overflow-wrap:anywhere}
#task-work-panel-toggle{position:fixed;z-index:65;right:12px;top:12px;max-width:calc(100vw - 160px);min-height:40px;padding:8px 12px;box-shadow:0 3px 14px #14263835}
#task-work-panel-backdrop{position:fixed;z-index:70;inset:0;width:100%;height:100%;margin:0;padding:0;border:0;border-radius:0;background:#07131f88}
.task-work-description{white-space:normal;overflow-wrap:anywhere}.task-work-description pre{max-width:100%;overflow:auto;white-space:pre-wrap}.task-work-description p{white-space:pre-wrap}
.task-work-pin,.task-work-project{display:block;font-size:12px;color:#627183;overflow-wrap:anywhere;margin:7px 0}
#task-work-checklist{min-width:0;margin:14px 0 0;padding:10px;border:1px solid #c8d5dc;border-radius:8px}
#task-work-checklist label{display:flex;align-items:flex-start;gap:7px;padding:5px 0;margin:0;overflow-wrap:anywhere}#task-work-checklist input{flex:none;margin:3px 0 0}
#task-work-checklist small{display:block;font-size:12px;margin:4px 0 7px;color:#627183}.task-work-progress{width:100%;height:10px;accent-color:#176b60}
.task-work-related ul,#task-work-proposals ul{padding-left:18px}#task-work-proposal-list li{padding:5px 0;white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:1050px){#task-work-controls{position:fixed;inset:0 0 0 auto;width:min(88vw,360px);max-width:100vw;height:100vh;height:100dvh;box-shadow:-8px 0 30px #07131f44;padding:14px}#task-work-controls:focus{outline:none}}
@media print{#task-work-controls,#task-work-panel-toggle,#task-work-panel-backdrop{display:none!important}}
'''

import json

from spikes.task_activities import ROUTES

TASK_WORK_JS = 'const taskActivityRoutes=new Set('+json.dumps(list(ROUTES))+');\n' + r'''
function taskWorkActivityFinished(path){
 if(taskActivityRoutes.has(path)&&taskWorkHandle)setTimeout(()=>{if(!taskWorkBusy)refreshTaskWork();},0);
}
function taskWorkActivityHeaders(path,request){
 if(!taskActivityRoutes.has(path)||!taskWorkHandle||!taskWorkView?.active_session_id)return {};
 if(taskWorkBusy||taskWorkView.pending)throw new Error('Nejprve obnovte pracovní kontext úkolu.');
 return {'X-FPW-Task-Work':JSON.stringify({...taskWorkHandle,context_revision:taskWorkView.context_revision})};
}
let taskWorkHandle=null,taskWorkView=null,taskWorkBusy=false,taskWorkMessage='',taskWorkSelection=null,taskWorkAttempt=null,taskWorkProposalDraft='';
const taskWorkStorageKey='fpw-task-work-window-v1',taskWorkRestoreKey='fpw-task-work-restore-v1';
function readTaskWorkStorage(key){try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}}
let taskWorkPrevious=readTaskWorkStorage(taskWorkStorageKey),taskWorkRestoreAttempt=readTaskWorkStorage(taskWorkRestoreKey);
let taskWorkPanelOpen=true,taskWorkPanelReturnFocus=null,taskWorkChecklistFocus=null;
const taskWorkPanelNarrow=window.matchMedia('(max-width:1050px)');
let taskWorkInertRestore=null,taskWorkPanelExternalState='';
function storeTaskWorkHandle(handle){taskWorkHandle={window_id:handle.window_id,window_token:handle.window_token};try{sessionStorage.setItem(taskWorkStorageKey,JSON.stringify(taskWorkHandle));}catch{taskWorkMessage='Pracovní okno nelze uložit pro obnovení po reloadu.';}}
function selectedTaskWorkSession(){return taskWorkView?.sessions.find(s=>s.work_session_id===taskWorkSelection);}
function renderTaskWork(){
 const root=document.querySelector('#task-work-controls'),select=document.querySelector('#task-work-session');
 root.hidden=!taskWorkHandle&&!taskWorkPrevious;
 const sessions=taskWorkView?.sessions||[],active=sessions.find(s=>s.work_session_id===taskWorkView?.active_session_id);
 if(!sessions.some(s=>s.work_session_id===taskWorkSelection))taskWorkSelection=active?.work_session_id||sessions[0]?.work_session_id||null;
 select.replaceChildren();
 const states={active:'Aktivní',paused:'Pozastaveno',closed:'Ukončeno'};
 for(const session of sessions){const option=document.createElement('option');option.value=session.work_session_id;option.textContent=`${session.task_id} · ${session.title||'Nedostupné zadání'} · ${states[session.state]||session.state}`;select.append(option);}
 select.value=taskWorkSelection||'';select.disabled=taskWorkBusy||!sessions.length;
 const selected=selectedTaskWorkSession(),pending=taskWorkView?.pending;
 document.querySelector('#task-work-status').textContent=taskWorkMessage||(pending?'Zahájení čeká na obnovu.':active?`Pracuji na ${active.task_id} · ${active.title||'Nedostupné zadání'}${active.blocked?' · '+active.blocked:''}`:taskWorkHandle?'Žádný aktivní úkol.':'Je dostupné předchozí pracovní okno. Obnovení je pozastaví a vyžádá nové pokračování.');
 document.querySelector('#task-work-pause').disabled=taskWorkBusy||!!pending||!selected||selected.state!=='active';
 document.querySelector('#task-work-resume').disabled=taskWorkBusy||!!pending||!selected||selected.state!=='paused'||!!active||!!selected.blocked;
 document.querySelector('#task-work-close').disabled=taskWorkBusy||!!pending||!selected||selected.state==='closed';
 document.querySelector('#task-work-propose').disabled=taskWorkBusy||!!pending||!selected||!!selected.blocked;
 document.querySelector('#task-work-refresh').disabled=taskWorkBusy||!taskWorkHandle;
 document.querySelector('#task-work-restore').hidden=!!taskWorkHandle||!taskWorkPrevious;
 document.querySelector('#task-work-restore').disabled=taskWorkBusy;
 for(const id of ['task-work-recover','task-work-cancel']){document.getElementById(id).hidden=!pending;document.getElementById(id).disabled=taskWorkBusy;}
 for(const button of document.querySelectorAll('[data-task-work-start]'))button.disabled=taskWorkBusy||!!pending||!!activeProject?.readOnly||button.dataset.blocked==='true';
 document.querySelector('#task-work-switch').disabled=taskWorkBusy||!!pending||!selected;
 renderTaskWorkDetails();syncTaskWorkPanel();
}
async function taskWorkRefreshPlan(){
 const project=activeProject;if(!project)return;
 const session=taskWorkView?.sessions.find(s=>s.project_id===project.id&&s.validated_head&&s.validated_head!==project.head);
 if(!session)return;
 const view=await projectRequest('/v1/projects/open',{project_id:project.id,scope:'plan'});
 if(activeProject!==project)return;
 project.head=view.commit_id;document.querySelector('#project-commit').textContent=view.commit_id;
 installTaskPlanViews(view,{loadQueue:false});
}
async function refreshTaskWork(){
 if(!taskWorkHandle||taskWorkBusy)return;
 taskWorkBusy=true;taskWorkMessage='Načítám pracovní kontext…';renderTaskWork();
 try{taskWorkView=await projectRequest('/v1/task-work',{action:'status',...taskWorkHandle});taskWorkMessage='';await taskWorkRefreshPlan();}
 catch(error){taskWorkView=null;taskWorkMessage=error.message;}
 finally{taskWorkBusy=false;renderTaskWork();}
}
async function restoreTaskWorkWindow(){
 if(taskWorkBusy||taskWorkHandle||!taskWorkPrevious)return false;
 if(!window.confirm('Obnovit předchozí pracovní okno? Jeho aktivní relace se pozastaví. Původní okno ztratí oprávnění tento kontext ovládat.'))return false;
 taskWorkBusy=true;taskWorkMessage='Obnovuji pracovní okno…';renderTaskWork();
 try{
  if(!taskWorkRestoreAttempt){const view=await projectRequest('/v1/task-work',{action:'status',...taskWorkPrevious});
   taskWorkRestoreAttempt={action:'restore',...taskWorkPrevious,context_revision:view.context_revision,operation_id:crypto.randomUUID()};
   // Preserve the original operation for a lost restore reply. Never invent another claim.
   sessionStorage.setItem(taskWorkRestoreKey,JSON.stringify(taskWorkRestoreAttempt));
  }
  const result=await projectRequest('/v1/task-work',taskWorkRestoreAttempt);
  storeTaskWorkHandle(result.window);taskWorkView=result;taskWorkPrevious=null;taskWorkRestoreAttempt=null;
  try{sessionStorage.removeItem(taskWorkRestoreKey);}catch{}
  taskWorkMessage='Pracovní okno obnoveno. Vyberte relaci a použijte Pokračovat.';return true;
 }catch(error){taskWorkMessage=error.message+' Opakování obnovy použije původní operaci.';return false;}
 finally{taskWorkBusy=false;renderTaskWork();}
}
async function ensureTaskWorkWindow(){
 if(taskWorkHandle)return true;
 if(taskWorkPrevious)return await restoreTaskWorkWindow();
 const handle=await projectRequest('/v1/task-work',{action:'window'});storeTaskWorkHandle(handle);
 taskWorkView=await projectRequest('/v1/task-work',{action:'status',...taskWorkHandle});return true;
}
async function sendTaskWork(request){
 if(taskWorkBusy)return;
 taskWorkBusy=true;taskWorkAttempt=request;taskWorkMessage='Ukládám pracovní kontext…';renderTaskWork();
 try{
  const result=await projectRequest('/v1/task-work',request,120000);taskWorkView=result;
  if(result.operation?.state!=='completed')throw Error(result.operation?.error||'Operace vyžaduje obnovu.');
  if(result.active_session_id&&['start','switch','resume','recover'].includes(request.action))taskWorkSelection=result.active_session_id;
  taskWorkMessage=request.action==='propose-completion'?'Návrh uložen k pracovní relaci. Dokončení úkolu se nezměnilo.':'';
  taskWorkAttempt=null;await taskWorkRefreshPlan();
 }catch(error){
  taskWorkMessage=error.message+' Obnovte kontext před další změnou.';
  // Read actual state, without retrying the mutation or starting another task.
  try{taskWorkView=await projectRequest('/v1/task-work',{action:'status',...taskWorkHandle});}catch{taskWorkView=null;}
 }finally{taskWorkBusy=false;renderTaskWork();
  if(taskWorkChecklistFocus!==null){const radio=[...document.querySelectorAll('[data-task-work-checklist]')].find(el=>el.value===taskWorkChecklistFocus);if(radio&&!radio.disabled)radio.focus();taskWorkChecklistFocus=null;}
 }
}
async function startTaskWork(item){
 if(taskWorkBusy||!activeProject||activeProject.readOnly)return;
 const project=activeProject;taskWorkPanelOpen=true;
 try{
  if(!await ensureTaskWorkWindow()||activeProject!==project)return;
  const active=taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id);
  if(active&&active.project_id===project.id&&active.task_id===item.id&&!active.blocked){taskWorkMessage='Tento úkol už je aktivní.';renderTaskWork();return;}
  if(active&&!window.confirm(active.project_id===project.id&&active.task_id===item.id?`Uzavřít původní pracovní úsek a přijmout aktuální zadání ${item.id}?`:`Pozastavit ${active.task_id} a přepnout na ${item.id}?`))return;
  const target=await projectRequest('/v1/task-work',{action:'inspect',...taskWorkHandle,project_id:project.id,task_id:item.id,expected_head:project.head});
  if(activeProject!==project)return;
  const request={action:active?'switch':'start',...taskWorkHandle,operation_id:crypto.randomUUID(),context_revision:taskWorkView.context_revision,project_id:project.id,task_id:item.id,selected_checklist:null,...target};
  if(active)Object.assign(request,{work_session_id:active.work_session_id,session_revision:active.revision});
  await sendTaskWork(request);
 }catch(error){taskWorkMessage=error.message;renderTaskWork();}
}
function appendTaskWorkStart(detail,item){
 if(item.checked||!([null,undefined,'task'].includes(item.type))||taskPlanProjection?.nodes.some(n=>n.parent_id===item.id))return;
 const button=document.createElement('button');button.type='button';button.textContent='Zahájit úkol';button.dataset.taskWorkStart=item.id;button.dataset.blocked=String(!item.ready);
 button.disabled=taskWorkBusy||!!activeProject?.readOnly||!item.ready||!!taskWorkView?.pending;
 if(!item.ready)button.title='Zahájení blokují předpoklady úkolu.';
 button.addEventListener('click',()=>startTaskWork(item));detail.append(button);
}
async function changeTaskWork(action){
 const session=selectedTaskWorkSession();if(taskWorkBusy||!taskWorkView||!session)return;
 const request={action,...taskWorkHandle,operation_id:crypto.randomUUID(),context_revision:taskWorkView.context_revision,work_session_id:session.work_session_id,session_revision:session.revision};
 if(action==='close'&&!window.confirm('Ukončit pracovní relaci? Dokončení úkolu se tím nepotvrzuje.'))return;
 if(action==='propose-completion'){
  const comment=window.prompt('Komentář k návrhu dokončení (úkol se nezaškrtne):',taskWorkProposalDraft);if(comment===null)return;
  taskWorkProposalDraft=comment;request.comment=comment;
 }
 await sendTaskWork(request);
}
function taskWorkPanelAvailable(){return Boolean(taskWorkHandle||taskWorkPrevious)&&(document.body.dataset.runtime==='desktop'||document.body.classList.contains('authenticated'))&&!document.body.classList.contains('presenter-active');}
function syncTaskWorkPanel(){
 const root=document.querySelector('#task-work-controls'),toggle=document.querySelector('#task-work-panel-toggle'),backdrop=document.querySelector('#task-work-panel-backdrop');
 const available=taskWorkPanelAvailable(),open=available&&taskWorkPanelOpen,modal=open&&taskWorkPanelNarrow.matches;
 const active=taskWorkView?.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id);toggle.textContent=active?'Úkol '+active.task_id:'Pracovní relace';
 root.hidden=!open;toggle.hidden=!available||open;toggle.setAttribute('aria-expanded',String(open));
 backdrop.hidden=!modal;root.setAttribute('role',modal?'dialog':'complementary');
 if(modal)root.setAttribute('aria-modal','true');else root.removeAttribute('aria-modal');
 document.body.classList.toggle('task-work-panel-shown',open&&!modal);
 if(modal&&!taskWorkInertRestore){
  taskWorkInertRestore=[document.querySelector('main'),document.querySelector('#workspace-sidebar'),document.querySelector('#mobile-sidebar-toggle')].filter(Boolean).map(el=>[el,el.inert]);
  for(const [el] of taskWorkInertRestore)el.inert=true;
  if(!root.contains(document.activeElement))queueMicrotask(()=>{if(!root.hidden&&taskWorkPanelNarrow.matches)document.querySelector('#task-work-panel-collapse').focus();});
 }else if(!modal&&taskWorkInertRestore){for(const [el,prior] of taskWorkInertRestore)el.inert=prior;taskWorkInertRestore=null;}
}
function setTaskWorkPanel(open){
 const root=document.querySelector('#task-work-controls');
 if(open&&!taskWorkPanelOpen)taskWorkPanelReturnFocus=document.activeElement;
 taskWorkPanelOpen=open;syncTaskWorkPanel();
 if(open&&!root.hidden){document.querySelector('#task-work-panel-collapse').focus();}
 else if(!open){const previous=taskWorkPanelReturnFocus;if(previous?.isConnected&&previous.getClientRects().length&&!previous.closest('[inert]'))previous.focus();else document.querySelector('#task-work-panel-toggle').focus();}
}
function scheduleTaskWorkRefresh(){
 if(!taskWorkHandle||taskWorkBusy||!activeProject)return;
 const project=activeProject;
 if(!taskWorkView?.sessions.some(s=>s.project_id===project.id&&s.validated_head&&s.validated_head!==project.head))return;
 queueMicrotask(()=>{if(!taskWorkBusy&&activeProject===project)refreshTaskWork();});
}
function renderTaskWorkDetails(){
 const target=document.querySelector('#task-work-details'),proposals=document.querySelector('#task-work-proposals'),list=document.querySelector('#task-work-proposal-list');
 const session=selectedTaskWorkSession(),task=session?.current_task;
 target.replaceChildren();list.replaceChildren();
 const related=document.querySelector('#task-work-related-list');related.replaceChildren();proposals.hidden=!session?.completion_proposals?.length;
 const empty=document.querySelector('#task-work-related-empty');empty.textContent=session?'K této relaci zatím nejsou připojené činnosti ani výstupy.':'Vyberte pracovní relaci.';
 empty.hidden=!!session?.activities?.length;
 for(const activity of session?.activities||[]){
  const row=document.createElement('li');
  const outcomes={succeeded:'Uloženo / dokončeno',failed:'Neúspěšné',unknown:'Výsledek není potvrzen'};
  const kinds={'artifact-save':'Uložení dokumentu','artifact-delete':'Odstranění dokumentu','source-import':'Import podkladu','artifact-publish':'Uložení výstupu','conversation-turn':'Konverzace','conversation-snapshot':'Uložení konverzace','conversation-output':'Uložení odpovědi','llm-run':'Modelový běh','llm-task':'Modelová úloha','search-run':'Vyhledávání','file-edit':'Úprava souboru','file-save':'Uložení souboru','file-delete':'Odstranění souboru','file-stage':'Rozpracovaná změna souboru','file-commit':'Commit souboru','plan-save':'Úprava plánu','plan-create':'Vytvoření položky plánu','plan-relations':'Úprava vazeb plánu','plan-delete':'Odstranění položky plánu','media-run':'Tvorba média'};
  row.textContent=`${kinds[activity.kind]||activity.kind} · ${outcomes[activity.outcome]||activity.outcome} · ${new Date(activity.created_at*1000).toLocaleString()}`;
  for(const ref of activity.result_references||[]){if(ref.commit_id){const pin=document.createElement('small');pin.className='task-work-pin';pin.textContent='Commit '+ref.commit_id;row.append(pin);}}
  related.append(row);
 }
 if(!session)return;
 const heading=document.createElement('h3');heading.textContent=`${session.task_id} · ${session.title||'Nedostupné zadání'}`;target.append(heading);
 if(!task){const reason=document.createElement('p');reason.textContent=session.blocked||'Zadání nelze načíst.';target.append(reason);return;}
 const project=document.createElement('span');project.className='task-work-project';project.textContent=`Projekt: ${session.project_title||session.project_id}`;
 target.append(project,planStatusBadge(task));
 if(session.blocked){const warning=document.createElement('p');warning.textContent=session.blocked;target.append(warning);}
 const label=document.createElement('h3');label.textContent='Aktuální zadání';target.append(label);
 const description=document.createElement('div');description.className='task-work-description';
 if(task.description_markdown)renderMarkdown(task.description_markdown,description,null,activeProject?.id===session.project_id);
 else description.textContent=task.description||'Úkol nemá doplňující popis.';
 target.append(description);
 const pin=document.createElement('small');pin.className='task-work-pin';pin.textContent='Pracovní úsek je připnutý k revizi '+session.definition_pin.project_commit.slice(0,12)+'.';target.append(pin);
 const checklist=task.checklist||[],checked=checklist.filter(item=>item.checked).length;
 const progress=document.createElement('p');progress.textContent=checklist.length?`Checklist: ${checked} z ${checklist.length} bodů splněno.`:'Úkol nemá samostatný checklist.';target.append(progress);
 if(checklist.length){
  const bar=document.createElement('progress');bar.className='task-work-progress';bar.max=checklist.length;bar.value=checked;bar.ariaLabel='Splnění checklistu';target.append(bar);
  const field=document.createElement('fieldset');field.id='task-work-checklist';const legend=document.createElement('legend');legend.textContent='Kontext další činnosti';field.append(legend);
  const help=document.createElement('small');help.textContent='Volba bodu neoznačuje jeho splnění.';field.append(help);
  for(const [index,text,done] of [[null,'Celý úkol',false],...checklist.map((item,index)=>[index,item.text,item.checked])]){
   const row=document.createElement('label'),radio=document.createElement('input'),caption=document.createElement('span');radio.type='radio';radio.name='task-work-checklist-context';radio.value=index===null?'':String(index);radio.dataset.taskWorkChecklist=radio.value;
   radio.checked=!session.blocked&&(session.selected_checklist??null)===index;radio.disabled=taskWorkBusy||!!taskWorkView.pending||!!session.blocked||session.state==='closed';
   caption.textContent=(index===null?'':done?'☑ ':'☐ ')+text;
   radio.addEventListener('change',()=>{if(radio.checked){taskWorkChecklistFocus=radio.value;selectTaskWorkChecklist(index);}});row.append(radio,caption);field.append(row);
  }
  target.append(field);
 }
 for(const proposal of session.completion_proposals||[]){const row=document.createElement('li');row.textContent=`${proposal.state==='pending'?'Čeká na posouzení':proposal.state} · ${proposal.comment||'Bez komentáře'}`;list.append(row);}
}
async function selectTaskWorkChecklist(index){
 const session=selectedTaskWorkSession();if(taskWorkBusy||!session||!taskWorkView||session.blocked)return;
 await sendTaskWork({action:'select-checklist',...taskWorkHandle,operation_id:crypto.randomUUID(),context_revision:taskWorkView.context_revision,work_session_id:session.work_session_id,session_revision:session.revision,selected_checklist:index});
}
async function navigateTaskWorkPlan(){
 const session=selectedTaskWorkSession();if(taskWorkBusy||!session||!await canLeaveWorkspaceEditors())return;
 if(activeProject?.id!==session.project_id)await openRegisteredProject(session.project_id);
 if(activeProject?.id!==session.project_id)return;
 if(await openTaskPlan()){setTaskWorkPanel(false);document.querySelector('#plan-graph').focus();}
}
document.querySelector('#task-work-panel-toggle').addEventListener('click',()=>setTaskWorkPanel(true));
document.querySelector('#task-work-panel-collapse').addEventListener('click',()=>setTaskWorkPanel(false));
document.querySelector('#task-work-panel-backdrop').addEventListener('click',()=>setTaskWorkPanel(false));
document.querySelector('#task-work-switch').addEventListener('click',navigateTaskWorkPlan);
document.querySelector('#task-work-controls').addEventListener('keydown',event=>{
 if(!taskWorkPanelNarrow.matches||!taskWorkPanelOpen||event.key!=='Tab')return;
 const focusable=[...event.currentTarget.querySelectorAll('button:not([disabled]),select:not([disabled]),input:not([disabled]),[href]')].filter(el=>el.getClientRects().length&&!el.closest('[hidden]'));
 const first=focusable[0],last=focusable.at(-1);if(!first){event.preventDefault();return;}
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&taskWorkPanelNarrow.matches&&taskWorkPanelOpen&&!document.querySelector('#task-work-controls').hidden&&!document.querySelector('dialog[open]')){event.preventDefault();event.stopPropagation();setTaskWorkPanel(false);}},true);
taskWorkPanelNarrow.addEventListener('change',syncTaskWorkPanel);
new MutationObserver(()=>{const key=[document.body.dataset.runtime,document.body.classList.contains('authenticated'),document.body.classList.contains('presenter-active')].join('|');if(key!==taskWorkPanelExternalState){taskWorkPanelExternalState=key;syncTaskWorkPanel();}}).observe(document.body,{attributes:true,attributeFilter:['class','data-runtime']});

document.querySelector('#task-work-session').addEventListener('change',event=>{taskWorkSelection=event.target.value;renderTaskWork();});
for(const [id,action] of [['pause','pause'],['resume','resume'],['close','close'],['propose','propose-completion']])document.querySelector('#task-work-'+id).addEventListener('click',()=>changeTaskWork(action));
document.querySelector('#task-work-refresh').addEventListener('click',refreshTaskWork);
document.querySelector('#task-work-restore').addEventListener('click',restoreTaskWorkWindow);
for(const [id,action] of [['recover','recover'],['cancel','cancel']])document.querySelector('#task-work-'+id).addEventListener('click',()=>{if(taskWorkView?.pending)sendTaskWork({action,...taskWorkHandle,operation_id:taskWorkView.pending.operation_id});});
window.addEventListener('focus',()=>{if(taskWorkHandle&&!taskWorkBusy)refreshTaskWork();});
renderTaskWork();
'''
