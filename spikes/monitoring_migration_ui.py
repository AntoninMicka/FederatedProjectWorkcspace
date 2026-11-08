# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit one-time preview/apply and durable migration recovery."""
HTML='''<section id="monitoring-migration">
<h3>Jednorázový převod starších sledování</h3>
<p>Starší zadání převedete na samostatné bloky. Historické běhy a zprávy zůstanou zachované.</p>
<button id="monitoring-migration-open" type="button">Vybrat sledování k převodu</button>
<div id="monitoring-migration-pending"></div>
<form id="monitoring-migration-form" hidden>
<fieldset id="monitoring-migration-choices"><legend>Sledování k převodu</legend></fieldset>
<label>Uchování převzatých zpráv ve dnech <input name="retention_days" type="number" min="1" max="3650" value="30" required></label>
<label>Uzel pro zpracování bez původního konkrétního přiřazení <select name="processing_node_id" required></select></label>
<button type="submit">Zobrazit náhled převodu</button>
<button id="monitoring-migration-close" type="button">Zavřít</button>
</form>
<section id="monitoring-migration-preview" hidden aria-live="polite"></section>
</section>'''
JS=r'''
let monitoringMigrationSequence=0,monitoringMigrationProject=null,monitoringMigrationPlan=null,monitoringMigrationAttempt=null;
const monitoringMigrationForm=document.querySelector('#monitoring-migration-form');
function clearMonitoringMigration(){
 monitoringMigrationSequence++;monitoringMigrationProject=null;monitoringMigrationPlan=null;monitoringMigrationAttempt=null;
 monitoringMigrationForm.hidden=true;document.querySelector('#monitoring-migration-preview').replaceChildren();
 document.querySelector('#monitoring-migration-preview').hidden=true;
 document.querySelector('#monitoring-migration-pending').replaceChildren();
}
async function openMonitoringMigration(){
 if(!await canLeaveMonitoring())return;
 const pid=activeProject.id;const result=await monitoringRequest('migration-inventory');if(activeProject?.id!==pid)return;
 clearMonitoringMigration();monitoringMigrationProject=pid;
 const choices=document.querySelector('#monitoring-migration-choices');choices.replaceChildren(blockText('legend','Sledování k převodu'));
 for(const row of result.items){
  const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=row.id;input.name='watch_ids';
  input.disabled=row.converted;input.checked=!row.converted;label.append(input,document.createTextNode(' '+row.title+(row.converted?' — již převedeno':'')));choices.append(label);
  if(!row.converted){const mapping=document.createElement('label'),select=document.createElement('select');select.multiple=true;select.dataset.migrationPoolOwner=row.id;
   mapping.append(document.createTextNode(row.kind==='watch'?'Nové vstupní pooly (vyžadováno pro původní víceperiodové zadání)':'Výslovné nahrazení původních vstupů pooly (volitelné)'),select);
   for(const pool of blockCatalog.blocks.filter(b=>b.value.kind==='pool')){const opt=document.createElement('option');opt.value=pool.id;opt.textContent=pool.value.title;select.append(opt);}choices.append(mapping);}
 }
 const nodes=monitoringView?.execution_nodes?.nodes||[{id:blockCatalog.node_id,name:'Tento uzel'}];
 const select=monitoringMigrationForm.elements.processing_node_id;select.replaceChildren();
 for(const node of nodes){const opt=document.createElement('option');opt.value=node.id;opt.textContent=node.name;opt.selected=node.id===blockCatalog.node_id;select.append(opt);}
 for(const e of monitoringMigrationForm.querySelectorAll('input,select,button'))if(e.name!=='watch_ids')e.disabled=false;
 const pending=document.querySelector('#monitoring-migration-pending');
 for(const row of result.pending){pending.append(monitoringButton('Dokončit přerušený převod',async()=>{
  if(activeProject?.id!==pid)return;
  await monitoringRequest('migration-resume',{operation_id:row.operation_id});if(activeProject?.id!==pid)return;await loadMonitoring();await openMonitoringMigration();
  blockStatus('Přerušený převod byl dokončen. Nové bloky můžete zkontrolovat a aktivovat.');
 },blockReadOnly()));
  pending.append(monitoringButton('Zrušit dosud neuložený převod',async()=>{if(activeProject?.id!==pid)return;await monitoringRequest('migration-cancel',{operation_id:row.operation_id,confirm:true});if(activeProject?.id===pid)await openMonitoringMigration();},blockReadOnly()));
 }
 monitoringMigrationForm.hidden=false;
}
function renderMonitoringMigrationPreview(plan){
 const root=document.querySelector('#monitoring-migration-preview');root.replaceChildren();root.hidden=false;
 root.append(blockText('h3','Náhled jednorázového převodu'));
 root.append(blockText('p','Nových bloků: '+plan.blocks.length+' · zpráv do poolů: '+plan.findings.length+' · starších mimo retenci: '+plan.expired_findings));
 root.append(blockText('p','Před převodem aktualizujte všechny vykonávající uzly. Nové bloky zůstanou vypnuté; staré zadání se zachová jako historie.'));
 const names=new Map([...blockCatalog.blocks,...plan.blocks].map(b=>[b.id,b.value.title]));
 const list=document.createElement('ul');
 for(const b of plan.blocks){const li=document.createElement('li');li.append(blockText('strong',blockLabels[b.value.kind]+' · '+b.value.title));
  const c=b.value.config;if(b.value.kind==='filter')li.append(blockText('p',c.source_ids.map(i=>names.get(i)).join(', ')+' → '+names.get(c.pool_id)));
  if(b.value.kind==='processing')li.append(blockText('p','Vstupní pooly: '+c.pool_ids.map(i=>names.get(i)).join(', ')));
  if(b.value.kind==='source')li.append(blockText('p',c.locator+' · interval '+c.poll_seconds/60+' min'));
  if(b.value.kind==='processing')li.append(blockText('p','Ruční zpracování · posledních '+c.lookback_days+' dní · uzel '+c.node_id));
  if(b.value.kind==='pool')li.append(blockText('p','Uchování '+c.retention_days+' dní'));
  list.append(li);
 }root.append(list);
 for(const text of plan.notices)root.append(blockText('p',text));
 for(const issue of plan.issues)root.append(blockText('p','Nelze převést: '+issue.reason));
 if(!plan.issues.length&&plan.blocks.length)root.append(monitoringButton('Převést podle tohoto náhledu',applyMonitoringMigration,blockReadOnly()));
}
monitoringMigrationForm.addEventListener('input',()=>{
 if(monitoringMigrationAttempt)return;
 monitoringMigrationSequence++;monitoringMigrationPlan=null;document.querySelector('#monitoring-migration-preview').hidden=true;
 document.querySelector('#monitoring-migration-preview').replaceChildren();
});
monitoringMigrationForm.addEventListener('submit',async event=>{
 event.preventDefault();if(activeProject?.id!==monitoringMigrationProject)return;
 try{
  if(monitoringMigrationAttempt)throw Error('Nejdříve dokončete původní pokus o převod.');
  const watch_ids=[...monitoringMigrationForm.querySelectorAll('input[name=watch_ids]:checked:not(:disabled)')].map(i=>i.value);
  const pool_bindings={};for(const select of monitoringMigrationForm.querySelectorAll('[data-migration-pool-owner]')){const ids=[...select.selectedOptions].map(o=>o.value);if(ids.length&&watch_ids.includes(select.dataset.migrationPoolOwner))pool_bindings[select.dataset.migrationPoolOwner]=ids;}
  const sequence=++monitoringMigrationSequence;const plan=await monitoringRequest('migration-preview',{watch_ids,pool_bindings,retention_days:Number(monitoringMigrationForm.elements.retention_days.value),processing_node_id:monitoringMigrationForm.elements.processing_node_id.value});
  if(activeProject?.id!==monitoringMigrationProject||sequence!==monitoringMigrationSequence)return;
  monitoringMigrationPlan=plan;renderMonitoringMigrationPreview(plan);
 }catch(error){blockStatus(error.message);}
});
async function applyMonitoringMigration(){
 const pid=monitoringMigrationProject;if(activeProject?.id!==pid)return;
 if(!await canLeaveMonitoring())return;
 try{
  if(!monitoringMigrationAttempt){const p=monitoringMigrationPlan;monitoringMigrationAttempt={watch_ids:p.sources.map(s=>s.id),retention_days:p.retention_days,processing_node_id:p.processing_node_id,preview_sha256:p.preview_sha256,pool_bindings:p.pool_bindings,operation_id:crypto.randomUUID(),confirm:true};}
  for(const el of monitoringMigrationForm.querySelectorAll('input,select,button'))el.disabled=true;
  const result=await monitoringRequest('migration-apply',monitoringMigrationAttempt);if(activeProject?.id!==pid)return;
  clearMonitoringMigration();await loadMonitoring();blockTab='task';renderMonitoringBlocks();
  blockStatus('Převedeno sledování: '+result.converted.length+' · převzato zpráv: '+result.imported_findings+'. Nové bloky čekají na vaši aktivaci.');
 }catch(error){blockStatus(error.message+' Původní pokus lze zopakovat nebo obnovit v seznamu převodů.');}
}
document.querySelector('#monitoring-migration-open').addEventListener('click',async()=>{try{await openMonitoringMigration();}catch(e){blockStatus(e.message);}});
document.querySelector('#monitoring-migration-close').addEventListener('click',()=>clearMonitoringMigration());
'''
