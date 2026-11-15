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
function monitoringCatalogColumns(kind){
 if(kind==='source')return [['Kanál / hledání',r=>r.value.config.locator],['Kontrola zdroje',r=>r.value.config.connector==='rss-atom'?r.value.config.poll_seconds/60+' min':'Na vyžádání'],['Sdílená aktivace',r=>r.runtime?.error|| (r.runtime?.enabled?'Zapnutý':'Vypnutý')],['Poslední výsledek',r=>r.value.config.connector==='rss-atom'?monitoringIntakeOutcome(r.latest_intake):'Hledání pouze při zpracování']];
 if(kind==='filter')return [['Vstupní zdroje',r=>r.value.config.source_ids.map(blockName).join(', ')],['Pravidla',r=>r.value.config.pipeline.steps.map(s=>s.kind).join(' → ')],['Cílový pool',r=>blockName(r.value.config.pool_id)]];
 if(kind==='pool')return [['Zprávy',r=>String(r.message_count??0)],['Uchování',r=>r.value.config.retention_days+' dní'],['Příjem synchronizace',r=>r.last_received_sync||'Zatím nepotvrzen']];
 return [['Vstupní pooly',r=>r.value.config.pool_ids.map(blockName).join(', ')],['Rozvrh',r=>({manual:'Na vyžádání',daily:'Denně',weekly:'Týdně',monthly:'Měsíčně',quarterly:'Čtvrtletně',annual:'Ročně'})[r.value.config.schedule.kind]],['Vykonavatel',r=>r.value.config.node_id===blockCatalog.node_id?'Tento uzel':(monitoringView?.execution_nodes?.nodes.find(n=>n.id===r.value.config.node_id)?.name||'Jiný uzel')],['Stav',r=>r.runtime?.error|| (r.runtime?.enabled?'Pravidelný běh zapnutý':'Ruční / vypnutý')]];
}
function monitoringCatalogTable(kind,rows,{selected=null,toggle=null}={}){
 const section=document.createElement('section');section.dataset.monitoringCatalog=kind;
 section.append(blockText('h3',blockLabels[kind]));
 const scroll=document.createElement('div');scroll.className='monitoring-table-scroll';
 const table=document.createElement('table');table.className='monitoring-catalog-table';table.setAttribute('aria-label',blockLabels[kind]);
 const caption=blockText('caption',rows.length?'Počet položek: '+rows.length:'Zatím žádné položky.');table.append(caption);
 const head=document.createElement('thead'),header=document.createElement('tr'),columns=monitoringCatalogColumns(kind);
 for(const label of [...(selected?['Zařazení']:[]),'Název',...columns.map(c=>c[0]),'Využití','Akce']){const th=blockText('th',label);th.scope='col';header.append(th);}head.append(header);table.append(head);
 const body=document.createElement('tbody');
 for(const row of rows){
  const tr=document.createElement('tr');tr.dataset.monitoringRow=row.id;
  const cell=node=>{const td=document.createElement('td');typeof node==='string'?td.append(document.createTextNode(node)):td.append(node);tr.append(td);};
  if(selected){const input=document.createElement('input');input.type='checkbox';input.checked=selected.has(row.id);input.setAttribute('aria-label','Zařadit: '+row.value.title);input.dataset.aggregateMember=row.id;input.disabled=blockReadOnly()||Boolean(blockSaving)||row.migration_pending;input.addEventListener('change',()=>toggle(row,input.checked));cell(input);}
  cell(row.value.title);for(const [,value] of columns)cell(value(row));cell(String((row.used_by||[]).length));
  const actions=document.createElement('div');
  actions.append(monitoringButton('Zobrazit',()=>openMonitoringTool(row)));
  actions.append(monitoringButton('Upravit '+({source:'zdroj',filter:'filtr',pool:'pool',processing:'úlohu'})[kind],async()=>{
   if(blockEdit?.value.kind==='task'){blockParent=readMonitoringBlock();blockEdit=null;}
   monitoringOpen();blockTab=kind;blockSelectedId=row.id;renderMonitoringBlocks();await editMonitoringBlock(kind,row);
  },blockReadOnly()||row.migration_pending));cell(actions);body.append(tr);
 }
 table.append(body);scroll.append(table);section.append(scroll);return section;
}
function renderMonitoringTaskAggregate(container,row,editing=false){
 const draft=editing?blockEdit:row,c=draft.value.config,section=document.createElement('section');
 section.className='monitoring-task-aggregate';section.dataset.monitoringTask=draft.id;
 section.append(blockText('h3',editing&&!draft.previous.length?'Nová sestava nástrojů':draft.value.title));
 section.append(blockText('p','Položky jsou sdílené. Jejich úprava se projeví ve všech sestavách, které je používají.'));
 if(editing){
  const metadata=document.createElement('table');metadata.className='monitoring-catalog-table';
  const body=document.createElement('tbody'),tr=document.createElement('tr');
  const title=document.createElement('input');title.value=draft.value.title;title.required=true;title.maxLength=200;title.setAttribute('aria-label','Název sestavy');title.dataset.aggregateTitle='';title.addEventListener('input',()=>{draft.value.title=title.value;});
  const privacy=document.createElement('select');privacy.setAttribute('aria-label','Soukromí sestavy');
  for(const [id,label] of [['public','Veřejné'],['project','Projekt'],['confidential','Důvěrné'],['local-only','Pouze lokálně']]){const o=blockText('option',label);o.value=id;o.selected=id===draft.privacy;privacy.append(o);}
  title.disabled=Boolean(blockSaving);privacy.disabled=draft.previous.length>0||Boolean(blockSaving);privacy.addEventListener('change',()=>{draft.privacy=privacy.value;});
  for(const [label,input] of [['Název sestavy',title],['Soukromí',privacy]]){const th=blockText('th',label);th.scope='row';const td=document.createElement('td');td.append(input);tr.append(th,td);}body.append(tr);metadata.append(body);section.append(metadata);
  const actions=document.createElement('div');actions.className='form-actions';
  actions.append(monitoringButton('Uložit složení',async()=>{if(!title.reportValidity())return;await saveMonitoringBlock(readMonitoringBlock());},blockReadOnly()));
  actions.append(monitoringButton('Zrušit změny složení',async()=>{if(await canLeaveMonitoringBlocks())renderMonitoringBlocks();}));section.append(actions);
 }else{
  section.append(blockText('p',c.instructions));
  section.append(monitoringButton('Upravit složení',()=>editMonitoringBlock('task',row),blockReadOnly()||row.migration_pending));
  section.append(monitoringButton('Sestavit zprávy úlohy',async()=>{if(!window.confirm('Spustit zpracování této úlohy včetně jejích modelů a hledání?'))return;await monitoringRequest('block-task-run',{block_id:row.id,run_id:crypto.randomUUID()});blockTab='runs';await loadMonitoringBlocks();},blockReadOnly()||row.migration_pending));
 }
 const selected=new Set(['source','filter','pool','processing'].flatMap(k=>c[k+'_ids']||[]));
 const rows=blockRows();const resolved=new Set(row.resolved_ids||selected);
 for(const kind of ['source','filter','pool','processing']){
  const candidates=rows.filter(b=>b.value.kind===kind&&(editing||resolved.has(b.id)));
  const table=monitoringCatalogTable(kind,candidates,editing?{selected,toggle:(member,enabled)=>{
   const key=kind+'_ids';c[key]=enabled?[...new Set([...c[key],member.id])]:c[key].filter(id=>id!==member.id);
   draft.value.config=closeMonitoringTaskDependencies(structuredClone(draft)).value.config;renderMonitoringBlocks();
   if(!enabled&&draft.value.config[key].includes(member.id))blockStatus('Položku vyžaduje jiné zvolené propojení; nejprve odpojte jeho uživatele.');
  }}:{});
  if(editing)table.append(monitoringButton('Vytvořit nové: '+blockLabels[kind],async()=>{blockParent=readMonitoringBlock();blockEdit=null;await editMonitoringBlock(kind);},blockReadOnly()||Boolean(blockSaving)));
  section.append(table);
 }
 container.append(section);
}
'''
