# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Minimal lifecycle controls for PLAN-TASK-WORK-01-A; the right panel is slice B."""
TASK_WORK_HTML = '''<section id="task-work-controls" aria-label="Pracovní kontext úkolu" hidden>
<p id="task-work-status" role="status" aria-live="polite"></p>
<label>Pracovní relace <select id="task-work-session" aria-label="Vybraná pracovní relace"></select></label>
<div class="task-work-actions">
<button id="task-work-pause" type="button">Pozastavit</button>
<button id="task-work-resume" type="button">Pokračovat</button>
<button id="task-work-close" type="button">Ukončit relaci</button>
<button id="task-work-propose" type="button">Navrhnout dokončení</button>
<button id="task-work-refresh" type="button">Obnovit kontext</button>
<button id="task-work-recover" type="button">Dokončit obnovu</button>
<button id="task-work-cancel" type="button">Zrušit zahájení</button>
<button id="task-work-restore" type="button">Obnovit pracovní okno</button>
</div></section>'''

TASK_WORK_CSS = '''
#task-work-controls{flex:none;max-height:35vh;overflow:auto;padding:10px 16px;margin-bottom:10px;border:1px solid #b7d5c8;border-radius:9px;background:#f3f9f6}
#task-work-controls p{margin:0 0 6px;overflow-wrap:anywhere}#task-work-controls label{display:flex;align-items:center;gap:8px;margin:0}
#task-work-controls select{min-width:0;max-width:100%}.task-work-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.task-work-actions button{margin:0;padding:6px 10px;font-size:12px}
@media(max-width:640px){#task-work-controls{padding:8px;max-height:42vh}.task-work-actions button{min-height:36px}}
'''

TASK_WORK_JS = r'''
let taskWorkHandle=null,taskWorkView=null,taskWorkBusy=false,taskWorkMessage='',taskWorkSelection=null,taskWorkAttempt=null,taskWorkProposalDraft='';
const taskWorkStorageKey='fpw-task-work-window-v1',taskWorkRestoreKey='fpw-task-work-restore-v1';
function readTaskWorkStorage(key){try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}}
let taskWorkPrevious=readTaskWorkStorage(taskWorkStorageKey),taskWorkRestoreAttempt=readTaskWorkStorage(taskWorkRestoreKey);
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
  if(result.active_session_id)taskWorkSelection=result.active_session_id;
  taskWorkMessage=request.action==='propose-completion'?'Návrh uložen k pracovní relaci. Dokončení úkolu se nezměnilo.':'';
  taskWorkAttempt=null;await taskWorkRefreshPlan();
 }catch(error){
  taskWorkMessage=error.message+' Obnovte kontext před další změnou.';
  // Read actual state, without retrying the mutation or starting another task.
  try{taskWorkView=await projectRequest('/v1/task-work',{action:'status',...taskWorkHandle});}catch{taskWorkView=null;}
 }finally{taskWorkBusy=false;renderTaskWork();}
}
async function startTaskWork(item){
 if(taskWorkBusy||!activeProject||activeProject.readOnly)return;
 const project=activeProject;
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
document.querySelector('#task-work-session').addEventListener('change',event=>{taskWorkSelection=event.target.value;renderTaskWork();});
for(const [id,action] of [['pause','pause'],['resume','resume'],['close','close'],['propose','propose-completion']])document.querySelector('#task-work-'+id).addEventListener('click',()=>changeTaskWork(action));
document.querySelector('#task-work-refresh').addEventListener('click',refreshTaskWork);
document.querySelector('#task-work-restore').addEventListener('click',restoreTaskWorkWindow);
for(const [id,action] of [['recover','recover'],['cancel','cancel']])document.querySelector('#task-work-'+id).addEventListener('click',()=>{if(taskWorkView?.pending)sendTaskWork({action,...taskWorkHandle,operation_id:taskWorkView.pending.operation_id});});
window.addEventListener('focus',()=>{if(taskWorkHandle&&!taskWorkBusy)refreshTaskWork();});
renderTaskWork();
'''
