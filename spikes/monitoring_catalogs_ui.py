# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Purpose-specific tables reused, without copying tools, in complex tasks."""
JS=r'''
function monitoringIntakeOutcome(job){
 if(!job)return 'Výsledek příjmu není v přehledu k dispozici';
 if(job.state==='unknown')return 'Neznámý výsledek — vyžaduje posouzení';
 if(job.state==='failed')return 'Chyba: '+(job.result?.error||'Příjem selhal');
 if(job.state!=='completed')return ({prepared:'Připraveno ke sběru',dispatching:'Probíhá příjem',abandoned:'Příjem uzavřen bez ověřeného výsledku',cancelled:'Příjem zrušen'})[job.state]||'Stav příjmu není známý';
 const result=job.result||{};
 if(result.status===304)return 'Zdroj se nezměnil';
 if(!Number.isInteger(result.input_items))return 'Úspěšný příjem — starší záznam bez počtů';
 if(result.input_items===0)return 'Kanál neobsahoval položky';
 if(result.filter_count===0)return 'Zdroj nemá připojený filtr';
 if(result.selected_items===0)return 'Žádná shoda filtru · položek: '+result.input_items;
 if(result.new_items===0)return 'Bez nových revizí · vybráno: '+result.selected_items;
 return 'Nové revize: '+result.new_items+' · vybráno: '+result.selected_items+' z '+result.input_items;
}
function monitoringLatestProcessing(row){
 return (blockCatalog?.jobs||[]).find(j=>j.intent.kind==='processing'&&j.intent.block?.id===row.id&&!j.intent.regeneration_of&&!j.result?.replacement)||null;
}
function monitoringProcessingFailure(error){
 return ['Neúplný přenos vstupních dat:','Neúplné období zdrojové úlohy ','Chybí vydané vstupní zprávy zdrojové úlohy '].some(prefix=>String(error||'').startsWith(prefix))?'Neúplné vstupy: '+error:'Chyba: '+(error||'Zpracování selhalo');
}
function monitoringProcessingOutcome(row){
 return monitoringProcessingJobOutcome(monitoringLatestProcessing(row));
}
function monitoringProcessingJobOutcome(job){
 return monitoringProcessingBaseOutcome(job)+(job?.input_evidence?.potentially_stale?' · možné zastarání vstupů':'');
}
function monitoringProcessingBaseOutcome(job){
 if(!job)return 'Výsledek není v přehledu k dispozici';
 if(job.state==='unknown')return 'Unknown · výsledek není známý: '+(job.result?.error||'vyžaduje posouzení');
 if(job.state==='failed')return monitoringProcessingFailure(job.result?.error);
 if(job.state==='published')return 'Zpráva vydána';
 if(job.state==='review'){
  const guard=job.result?.protection;
  if(guard?.error)return monitoringProcessingFailure(guard.error);
  if(guard&&!guard.finalized)return 'Ochranné období do '+new Date(guard.until*1000).toLocaleString()+(guard.changed?' · přibyly nezahrnuté vstupy':'');
  return 'Návrh čeká na posouzení a vydání';
 }
 return ({prepared:'Čeká na zpracování',dispatching:'Probíhá zpracování',cancelled:'Zpracování zrušeno'})[job.state]||'Stav výsledku není známý';
}
function monitoringProcessingPlan(row){
 if(row.migration_pending)return 'Čeká na dokončení převodu';
 if(row.runtime?.error)return row.runtime.error;
 if(row.value.config.schedule.kind==='manual')return 'Pouze ruční spuštění';
 return row.runtime?.enabled?'Pravidelný běh zapnutý':'Pravidelný běh není aktivovaný';
}
function monitoringProcessingTime(row){
 const job=monitoringLatestProcessing(row);if(!job)return 'V přehledu není uložen';
 const at=job.result?.output?.built_at||(Number.isFinite(job.intent.started_at)?job.intent.started_at*1000:null);
 return at?new Date(at).toLocaleString():'Čas není uložen';
}
function monitoringProcessingExecutor(row){
 const job=monitoringLatestProcessing(row),id=job?.intent.executor_node_id;
 if(!id)return 'Nezjištěn';
 return id===blockCatalog.node_id?'Tento uzel':(monitoringView?.execution_nodes?.nodes?.find(n=>n.id===id)?.name||'Jiný uzel');
}
function monitoringCatalogColumns(kind){
 if(kind==='source')return [['Kanál / hledání',r=>r.value.config.locator],['Kontrola zdroje',r=>r.value.config.connector==='rss-atom'?r.value.config.poll_seconds/60+' min':'Na vyžádání'],['Sdílená aktivace',r=>r.runtime?.error|| (r.runtime?.enabled?'Zapnutý':'Vypnutý')],['Poslední sběr',r=>r.runtime?.last_success||'Není uložen'],['Příští sběr',r=>r.value.config.connector==='rss-atom'&&r.runtime?.enabled?new Date(r.runtime.next_due*1000).toLocaleString():'Neaktivní / na vyžádání'],['Poslední výsledek',r=>r.value.config.connector==='rss-atom'?monitoringIntakeOutcome(r.latest_intake):'Hledání pouze při zpracování']];
 if(kind==='filter')return [['Vstupní zdroje',r=>r.value.config.source_ids.map(blockName).join(', ')],['Pravidla',r=>r.value.config.pipeline.steps.map(s=>s.kind).join(' → ')],['Cílový pool',r=>blockName(r.value.config.pool_id)]];
 if(kind==='pool')return [['Zprávy',r=>String(r.message_count??0)],['Čekající verze',r=>r.processing_status?.consumer_ids.length?String(r.processing_status.pending_count):'Bez připojeného zpracování'],['Uchování',r=>r.value.config.retention_days+' dní'],['Příjem synchronizace',r=>r.last_received_sync||'Zatím nepotvrzen']];
 return [['Vstupy (pooly / zprávy)',r=>[...r.value.config.pool_ids,...(r.value.config.report_task_ids||[])].map(blockName).join(', ')],['Rozvrh',r=>{
  const c=r.value.config.schedule,label=({manual:'Na vyžádání',daily:'Denně',weekly:'Týdně',monthly:'Měsíčně',quarterly:'Čtvrtletně',annual:'Ročně'})[c.kind];
  return c.kind==='manual'?label:label+' v '+c.time+' ('+c.timezone+')';
 }],['Plánovaný uzel',r=>r.value.config.node_id===blockCatalog.node_id?'Tento uzel':(monitoringView?.execution_nodes?.nodes?.find(n=>n.id===r.value.config.node_id)?.name||'Jiný uzel')],['Aktivace rozvrhu',monitoringProcessingPlan],['Poslední zpracování',monitoringProcessingTime],['Příští zpracování',r=>r.next_processing_at?new Date(r.next_processing_at*1000).toLocaleString():'Ruční / neaktivní'],['Poslední vydání',r=>r.last_issued_at?new Date(r.last_issued_at).toLocaleString():'Žádné uložené vydání'],['Skutečný vykonavatel',monitoringProcessingExecutor],['Výsledek',monitoringProcessingOutcome]];
}

function monitoringCatalogTable(kind,rows,{task=null}={}){
 const section=document.createElement('section');section.dataset.monitoringCatalog=kind;
 section.append(blockText('h3',blockLabels[kind]));
 const actions=document.createElement('div');actions.className='monitoring-catalog-actions';
 actions.setAttribute('aria-label','Akce: '+blockLabels[kind]);
 const disabled=blockReadOnly()||Boolean(blockSaving)||Boolean(task?.migration_pending);
 actions.append(monitoringButton('Vytvořit nové',async()=>{
  if(!await canLeaveMonitoringBlocks())return;
  blockParent=task;await editMonitoringBlock(kind);
 },disabled));
 actions.append(monitoringButton('Přidat existující',()=>monitoringExistingPicker(section,kind,task),disabled));
 section.append(actions);
 const scroll=document.createElement('div');scroll.className='monitoring-table-scroll';
 const table=document.createElement('table');table.className='monitoring-catalog-table';table.setAttribute('aria-label',blockLabels[kind]);
 table.append(blockText('caption',rows.length?'Počet položek: '+rows.length:'Zatím žádné položky.'));
 const head=document.createElement('thead'),header=document.createElement('tr'),columns=monitoringCatalogColumns(kind);
 for(const label of ['Název',...columns.map(c=>c[0]),'Využití','Akce']){const th=blockText('th',label);th.scope='col';header.append(th);}head.append(header);table.append(head);
 const body=document.createElement('tbody');
 for(const row of rows){
  const tr=document.createElement('tr');tr.dataset.monitoringRow=row.id;
  const cell=node=>{const td=document.createElement('td');typeof node==='string'?td.append(document.createTextNode(node)):td.append(node);tr.append(td);};
  cell(row.value.title);for(const [,value] of columns)cell(value(row));cell(String((row.used_by||[]).length));
  const rowActions=document.createElement('div');
  rowActions.append(monitoringButton('Zobrazit',()=>openMonitoringTool(row)));
  rowActions.append(monitoringButton('Upravit '+({source:'zdroj',filter:'filtr',pool:'pool',processing:'úlohu'})[kind],()=>openMonitoringTool(row,true),disabled||row.migration_pending));
  if(task)rowActions.append(monitoringButton('Odebrat ze sestavy',async()=>{
   const updated=structuredClone(task),key=kind+'_ids';updated.value.config[key]=updated.value.config[key].filter(id=>id!==row.id);
   closeMonitoringTaskDependencies(updated);
   if(updated.value.config[key].includes(row.id)){blockStatus('Položku vyžaduje jiné propojení; nejprve odpojte jeho uživatele.');return;}
   await saveMonitoringAggregate(updated);
  },disabled));
  cell(rowActions);body.append(tr);
 }
 table.append(body);scroll.append(table);section.append(scroll);return section;
}
function monitoringExistingPicker(section,kind,task){
 if(section.querySelector('[data-monitoring-existing]'))return;
 const picker=document.createElement('div');picker.dataset.monitoringExisting=kind;picker.className='monitoring-existing-picker';
 const resolved=new Set(task?.resolved_ids||Object.values(task?.value.config||{}).filter(Array.isArray).flat());
 const candidates=blockRows().filter(b=>b.value.kind===kind&&!b.migration_pending&&(!task||!resolved.has(b.id)));
 const label=blockText('label',task?'Připojit sdílenou položku do sestavy':'Otevřít existující položku z katalogu');
 const select=document.createElement('select');select.setAttribute('aria-label','Existující: '+blockLabels[kind]);
 for(const row of candidates){const option=blockText('option',row.value.title);option.value=row.id;select.append(option);}
 label.append(select);picker.append(label);
 if(!candidates.length)picker.append(blockText('p','Žádné další dostupné položky.'));
 picker.append(monitoringButton(task?'Přidat do sestavy':'Otevřít položku',async()=>{
  const member=candidates.find(b=>b.id===select.value);if(!member)return;
  if(task){const updated=structuredClone(task),key=kind+'_ids';updated.value.config[key]=[...new Set([...updated.value.config[key],member.id])];await saveMonitoringAggregate(closeMonitoringTaskDependencies(updated));}
  else await openMonitoringTool(member);
 },!candidates.length||blockReadOnly()));
 picker.append(monitoringButton('Zrušit výběr',()=>picker.remove()));
 section.querySelector('.monitoring-catalog-actions').after(picker);select.focus();
}
let monitoringAggregateAttempt=null;
async function saveMonitoringAggregate(row){
 if(blockReadOnly()||blockSaving)return;
 const pid=activeProject.id;
 const block={id:row.id,previous:row.previous||[row.ref],privacy:row.privacy,value:row.value};
 if(blockProposal){
  const index=blockProposal.proposal.blocks.findIndex(b=>b.id===row.id);
  if(index<0){blockStatus('Upravovat lze pouze sestavu v aktuálním návrhu.');return;}
  blockProposal.proposal.blocks[index]=block;renderMonitoringBlocks();renderBlockProposal();return;
 }
 const signature=JSON.stringify({pid,block});
 if(monitoringAggregateAttempt&&monitoringAggregateAttempt.signature!==signature){blockStatus('Nejprve opakujte původní změnu sestavy.');return;}
 monitoringAggregateAttempt??={signature,payload:{base_head:blockCatalog.commit_id,blocks:[block],operation_id:crypto.randomUUID()}};
 await retryMonitoringAggregate();
}
async function retryMonitoringAggregate(){
 const attempt=monitoringAggregateAttempt;if(!attempt||blockReadOnly()||blockSaving)return;
 const pid=activeProject.id;if(JSON.parse(attempt.signature).pid!==pid)return;
 const row=attempt.payload.blocks[0];
 try{
  blockSaving=attempt.payload;renderMonitoringBlocks();
  await monitoringRequest('blocks-save',blockSaving);monitoringAggregateAttempt=null;blockSaving=null;
  if(activeProject?.id!==pid)return;
  blockTab='task';blockSelectedId=row.id;await loadMonitoringBlocks();blockStatus('Složení sestavy uloženo.');
 }catch(err){
  blockSaving=null;const rejected=err.status>=400&&err.status<500&&err.status!==408&&err.outcome!=='unknown';
  if(rejected)monitoringAggregateAttempt=null;
  renderMonitoringBlocks();blockStatus(err.message+(rejected?' Obnovte přehled a zvolte změnu znovu.':' Opakujte uložení sestavy tlačítkem nad přehledem.'));
 }
}

function renderMonitoringFlow(container,task){
 const details=document.createElement('details');details.dataset.monitoringFlow='';details.append(blockText('summary','Tok dat a závislosti'));
 const rows=blockRows(),ids=new Set(task.resolved_ids||Object.values(task.value.config).filter(Array.isArray).flat());
 const table=document.createElement('table');table.className='monitoring-catalog-table';
 const head=document.createElement('tr');for(const text of ['Z části','Do části'])head.append(blockText('th',text));table.append(head);
 // Pool producers are visible even when shared outside the task membership.
 for(const filter of rows.filter(b=>b.value.kind==='filter'&&ids.has(b.value.config.pool_id))){ids.add(filter.id);for(const id of filter.value.config.source_ids)ids.add(id);}
 const edges=[];
 for(const row of rows.filter(b=>ids.has(b.id))){const c=row.value.config;
  if(row.value.kind==='filter'){for(const id of c.source_ids)edges.push([id,row.id]);edges.push([row.id,c.pool_id]);}
  if(row.value.kind==='processing')for(const id of [...c.pool_ids,...c.search_ids,...(c.report_task_ids||[])])edges.push([id,row.id]);
 }
 const visiting=new Set(),done=new Set();
 function cycle(id){if(visiting.has(id))return true;if(done.has(id))return false;visiting.add(id);for(const [,to] of edges.filter(e=>e[0]===id))if(cycle(to))return true;visiting.delete(id);done.add(id);return false;}
 if([...ids].some(cycle))details.append(blockText('p','Propojení obsahuje cyklus; sestavu před spuštěním opravte.'));
 for(const [from,to] of edges){const tr=document.createElement('tr');tr.append(blockText('td',blockName(from)),blockText('td',blockName(to)));table.append(tr);}
 if(!edges.length)details.append(blockText('p','Sestava zatím nemá propojené části.'));
 const scroll=document.createElement('div');scroll.className='monitoring-table-scroll';scroll.append(table);details.append(scroll);container.append(details);
}
function renderMonitoringTaskAggregate(container,row){
 const section=document.createElement('section');section.className='monitoring-task-aggregate';section.dataset.monitoringTask=row.id;
 section.append(blockText('h3',row.value.title));
 section.append(blockText('p','Agregovaný přehled sdílených částí. Jejich úprava se projeví ve všech sestavách, které je používají.'));
 section.append(monitoringButton('Sestavit zprávy úlohy',async()=>{
  if(!window.confirm('Spustit zpracování této úlohy včetně jejích modelů a hledání?'))return;
  await monitoringRequest('block-task-run',{block_id:row.id,run_id:crypto.randomUUID()});blockTab='runs';await loadMonitoringBlocks();
 },blockReadOnly()||row.migration_pending||Boolean(blockSaving)||!row.value.config.processing_ids.length));
 if(!row.value.config.processing_ids.length)section.append(blockText('p','Před spuštěním přidejte zpracování zpráv.'));
 const resolved=new Set(row.resolved_ids||Object.values(row.value.config).filter(Array.isArray).flat());
 for(const kind of ['source','filter','pool','processing'])section.append(monitoringCatalogTable(kind,blockRows().filter(b=>b.value.kind===kind&&resolved.has(b.id)),{task:row}));
 renderMonitoringFlow(section,row);
 container.append(section);
}
'''
