# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Independent collection/processing editor in the shared monitoring panel."""
JS=r'''
const monitoringWorkflowForm=document.querySelector('#monitoring-workflow-form');
let monitoringWorkflowEdit=null;
function monitoringNodeName(placement){
 if(placement.mode==='local')return 'Tento uzel';
 const node=monitoringView.execution_nodes?.nodes.find(n=>n.id===placement.node_id);
 return node?.name||('Nedostupný uzel · '+(placement.node_id||placement.capabilities.join(', ')));
}
function renderMonitoringDefinitions(readonly){
 const list=document.querySelector('#monitoring-definitions');list.replaceChildren();
 for(const row of monitoringView.definitions||[]){
  const li=document.createElement('li'),value=row.definition,collection=value.report.mode==='collect-only';
  li.append(monitoringButton(value.title,()=>showMonitoringDefinition(row)));
  const note=document.createElement('span');
  note.textContent=' — '+(collection?'Těžba':'Zpracování')+' · '+monitoringNodeName(value.placement)+' · '+
   (value.placement.mode!=='local'?'Čeká na vzdálené spouštění':collection?(row.runtime_state==='collection-configured'?'Těžba zapnutá':'Těžba nezapnutá'):
    value.schedule.trigger==='scheduled'?'Plán uložen, automatické spuštění čeká na zapojení':'Na vyžádání');
  li.append(note);list.append(li);
 }
}
function monitoringWorkflowPair(row){
 const rows=monitoringView.definitions||[];
 const collection=row.definition.report.mode==='collect-only'?row:
  rows.find(r=>r.watch_id===row.definition.inputs[0]?.watch_id);
 if(!collection)return null;
 const processing=row.definition.report.mode!=='collect-only'?row:
  rows.find(r=>r.definition.report.mode!=='collect-only'&&r.definition.inputs.length===1&&r.definition.inputs[0].watch_id===collection.watch_id);
 if(!processing)return null;
 // Only this editor's bounded two-stage shape can be round-tripped here.
 const c=collection.definition,p=processing.definition,steps=c.selection.pipeline?.steps;
 if(c.inputs.length!==1||c.inputs[0].kind!=='external'||c.inputs[0].connector!=='rss-atom'||
    p.inputs.length!==1||p.inputs[0].take!=='findings'||p.inputs[0].policy?.approval!=='selected'||
    !['manual','scheduled'].includes(p.schedule.trigger)||!steps||
    steps.some(s=>!['keywords','regex','dedup'].includes(s.kind))||
    steps.filter(s=>s.kind==='keywords').length>1||steps.filter(s=>s.kind==='regex').length>1||
    steps.filter(s=>s.kind==='dedup').length!==1||steps.at(-1).kind!=='dedup'||
    steps.some(s=>s.kind==='dedup'?s.field!=='content_sha256':JSON.stringify(s.fields)!==JSON.stringify(['title','content']))||
    steps.some(s=>s.kind==='keywords'?s.all.length||s.none.length||s.case_sensitive:
      s.kind==='regex'&&(s.match!=='search'||s.negate||JSON.stringify(s.flags)!==JSON.stringify(['IGNORECASE'])))||
    [c,p].some(v=>!['local','node'].includes(v.placement.mode)))return null;
 return {collection,processing};
}
function showMonitoringDefinition(row){
 monitoringOpen();const target=document.querySelector('#monitoring-detail');target.replaceChildren();
 const value=row.definition,collection=value.report.mode==='collect-only',h=document.createElement('h3');h.textContent=value.title;target.append(h);
 const p=document.createElement('p');p.textContent=value.goal;target.append(p);
 const node=document.createElement('p');node.textContent=(collection?'Těžební uzel: ':'Uzel pro zpracování: ')+monitoringNodeName(value.placement);target.append(node);
 const note=document.createElement('p');note.textContent=collection?'Prvotní filtr → uložené nálezy → následné zpracování. Synchronizace výsledků mezi uzly čeká na zapojení.':
  'Podklady: vybrané uložené nálezy. Spouštění: '+(value.schedule.trigger==='scheduled'?'podle plánu (automatické spouštění čeká na zapojení)':'na vyžádání')+'.';target.append(note);
 for(const input of value.inputs){const p=document.createElement('p');
  if(input.kind==='external')p.textContent='Zdroj: '+input.locator+' · kontrola každých '+input.poll.seconds/60+' min';
  else{p.textContent='Vstupní sledování: ';const source=monitoringView.definitions.find(r=>r.watch_id===input.watch_id);
   if(source)p.append(monitoringButton(source.definition.title,()=>showMonitoringDefinition(source)));else p.append(document.createTextNode('Nedostupné sledování'));}
  target.append(p);
 }
 if(collection){for(const step of value.selection.pipeline?.steps||[]){const p=document.createElement('p');
  p.textContent=step.kind==='keywords'?'Výběr výrazů: '+step.any.join(', '):step.kind==='regex'?'Regulární výraz: '+step.pattern:
   step.kind==='dedup'?'Vyřazení opakovaného obsahu.':'Filtr: '+step.kind;target.append(p);}
 }else{const p=document.createElement('p');p.textContent='Období: '+(monitoringLabels[value.schedule.kind]||'Den')+' · '+value.report.instructions;target.append(p);}
 if(!value.active){const p=document.createElement('p');p.textContent='Sledování je pozastavené.';target.append(p);}
 const readonly=activeProject.readOnly||!monitoringView.can_manage,pair=monitoringWorkflowPair(row);
 if(pair)target.append(monitoringButton('Upravit zadání',()=>editMonitoringWorkflow(pair),readonly));
 const projectId=activeProject.id,ref=structuredClone(row.definition_ref);
 if(collection&&value.placement.mode==='local'&&value.inputs.length===1&&value.inputs[0].connector==='rss-atom'){
  const configured=row.runtime_state==='collection-configured';
  target.append(monitoringButton(configured?'Pozastavit těžbu':'Zapnout místní těžbu',async()=>{
   if(activeProject?.id!==projectId)return;
   await monitoringRequest('rss-configure',{watch_id:row.watch_id,input_id:value.inputs[0].id,definition_ref:ref,enabled:!configured,
    mode:value.selection.pipeline?'pipeline':'queue-all',confirm:true});
   if(activeProject?.id===projectId)await loadMonitoring();
  },readonly||!value.active));
 }else if(!collection&&value.placement.mode==='local'){
  const label=document.createElement('label'),date=document.createElement('input');date.type='date';date.value=value.schedule.start;
  label.textContent='Začátek uzavřeného období';label.append(date);target.append(label);
  target.append(monitoringButton('Zpracovat uložené nálezy',async()=>{
   if(activeProject?.id!==projectId)return;
   const result=await monitoringRequest('workflow-run',{definition_ref:ref,period_start:date.value});
   if(activeProject?.id!==projectId)return;await loadMonitoring();
   monitoringStatus.textContent=result.state==='waiting-inputs'?'Čeká na vybrané podklady.':
    result.run?.state==='review'?'Návrh zprávy je připravený k posouzení.':'Stav zpracování: '+result.state;
  },readonly||!value.active));
 }else if(value.placement.mode!=='local'){
  const pending=document.createElement('p');pending.textContent='Zadání je uložené. Vzdálené spuštění zatím není dostupné; jiný uzel jej automaticky nepřebírá.';target.append(pending);
 }
}
function fillMonitoringNodes(select,placement){
 select.replaceChildren();const nodes=monitoringView.execution_nodes?.nodes||[];
 for(const node of nodes){const option=document.createElement('option');option.value=node.local?'local':node.id;option.textContent=node.name+(node.local?' · tento uzel':' · vzdálené spuštění čeká');select.append(option);}
 const selected=placement?.mode==='node'?placement.node_id:'local';
 if(![...select.options].some(o=>o.value===selected)){
  const missing=document.createElement('option');missing.value=selected;missing.textContent='Nedostupný uzel · '+selected;select.append(missing);
 }
 select.value=selected;
}
async function editMonitoringWorkflow(pair=null){
 if(!monitoringView)await loadMonitoring();if(!monitoringView||!await canLeaveMonitoring())return;
 monitoringOpen();monitoringForm.hidden=true;monitoringAttempt=null;monitoringDirty=false;
 monitoringWorkflowForm.reset();for(const el of monitoringWorkflowForm.querySelectorAll('input,select,textarea'))el.disabled=false;
 monitoringWorkflowEdit={project_id:activeProject.id,base_head:monitoringView.commit_id,pair:pair?structuredClone(pair):null,
  collection_id:pair?.collection.watch_id||crypto.randomUUID(),processing_id:pair?.processing.watch_id||crypto.randomUUID(),
  input_id:pair?.collection.definition.inputs[0].id||crypto.randomUUID(),link_id:pair?.processing.definition.inputs[0].id||crypto.randomUUID()};
 const f=monitoringWorkflowForm.elements,c=pair?.collection.definition,p=pair?.processing.definition;
 f.title.value=c?.title||'';f.goal.value=c?.goal||'';f.start.value=c?.schedule.start||new Date().toISOString().slice(0,10);
 f.timezone.value=c?.schedule.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||'Europe/Prague';
 f.privacy.value=pair?.collection.privacy||'project';f.privacy.disabled=Boolean(pair);
 f.url.value=c?.inputs[0].locator||'https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313';
 f.poll_minutes.value=c?c.inputs[0].poll.seconds/60:15;f.terms.value=c?.inputs[0].access.terms||'';f.retention.value=c?.inputs[0].access.retention||'';
 const steps=c?.selection.pipeline?.steps||[];f.keywords.value=steps.find(s=>s.kind==='keywords')?.any.join('\n')||'';
 f.regex.value=steps.find(s=>s.kind==='regex')?.pattern||'';
 f.instructions.value=p?.report.instructions||'Shrňte vybrané nálezy, změny a omezení podkladů.';
 f.kind.value=p?.schedule.kind||'weekly';f.trigger.value=p?.schedule.trigger||'manual';f.mode.value=p?.report.mode||'deterministic';
 fillMonitoringNodes(f.collection_node,c?.placement);fillMonitoringNodes(f.processing_node,p?.placement);
 document.querySelector('#monitoring-workflow-availability').textContent=(monitoringView.execution_nodes?.error||'')+
  ' Uložení zadání nespouští těžbu. Vzdálené spouštění, synchronizace výsledků a automatické zpracování podle plánu zatím nejsou dostupné.';
 monitoringWorkflowForm.hidden=false;f.title.focus();
}
function monitoringWorkflowPayload(){
 const f=monitoringWorkflowForm.elements,e=monitoringWorkflowEdit;
 const placement=select=>({mode:select.value==='local'?'local':'node',node_id:select.value==='local'?null:select.value,capabilities:[]});
 const base=(title,kind)=>({schema:'fpw-reporting-watch-v1',title,goal:f.goal.value,scope:{entities:[],categories:[],geographies:[],tags:[]},active:true,
  schedule:{kind,timezone:f.timezone.value,start:f.start.value},selection:{revision:'1',instructions:'Prvotní výběr nálezů'},evaluation:{revision:'1',instructions:'Zdroje nejsou potvrzená tvrzení.'}});
 const collection=e.pair?structuredClone(e.pair.collection.definition):base(f.title.value,'daily');
 const processing=e.pair?structuredClone(e.pair.processing.definition):base(('Zpracování · '+f.title.value).slice(0,150),f.kind.value);
 collection.title=f.title.value;collection.goal=f.goal.value;collection.schedule={...collection.schedule,timezone:f.timezone.value,start:f.start.value};
 collection.placement=placement(f.collection_node);
 collection.inputs=[{id:e.input_id,kind:'external',connector:'rss-atom',locator:f.url.value,poll:{seconds:Number(f.poll_minutes.value)*60},
  access:{reviewed:true,capture_allowed:true,terms:f.terms.value,retention:f.retention.value}}];
 const steps=[],words=f.keywords.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
 if(words.length)steps.push({id:'keywords',kind:'keywords',fields:['title','content'],all:[],any:words,none:[],case_sensitive:false});
 if(f.regex.value)steps.push({id:'regex',kind:'regex',fields:['title','content'],pattern:f.regex.value,flags:['IGNORECASE'],match:'search',negate:false});
 steps.push({id:'dedup',kind:'dedup',field:'content_sha256'});
 collection.selection={...collection.selection,pipeline:{schema:'fpw-monitoring-pipeline-v1',revision:crypto.randomUUID(),steps}};
 collection.report=collection.report||{mode:'collect-only',instructions:'Uložit vybrané nálezy pro další zpracování.',formats:['findings'],language:'cs',required_sections:[]};
 processing.goal=f.goal.value;processing.schedule={kind:f.kind.value,timezone:f.timezone.value,start:f.start.value,trigger:f.trigger.value};processing.placement=placement(f.processing_node);
 processing.inputs=[{id:e.link_id,kind:'watch',watch_id:e.collection_id,take:'findings',include_drafts:false,policy:{window:'ending-in-period',approval:'selected',missing:'wait'}}];
 processing.report={formats:['markdown'],language:'cs',required_sections:['# Přehled','## Omezení'],...processing.report,mode:f.mode.value,instructions:f.instructions.value};
 if(f.mode.value==='llm'){
  if(!monitoringView.binding)throw Error('Nejprve nastavte model pro zpracování.');
  processing.report.analysis={revision:'1',input_level:'mixed',case_studies:[],target:monitoringView.binding};
 }else delete processing.report.analysis;
 return {operation_id:crypto.randomUUID(),base_head:e.base_head,privacy:f.privacy.value,
  collection:{watch_id:e.collection_id,previous:e.pair?[e.pair.collection.definition_ref]:[],definition:collection},
  processing:{watch_id:e.processing_id,previous:e.pair?[e.pair.processing.definition_ref]:[],definition:processing}};
}
async function saveMonitoringWorkflow(){
 try{
  if(!monitoringWorkflowEdit||activeProject?.id!==monitoringWorkflowEdit.project_id)throw Error('Projekt se změnil. Otevřete zadání znovu.');
  if(!monitoringAttempt){if(!monitoringWorkflowForm.reportValidity())return false;monitoringAttempt=monitoringWorkflowPayload();}
  for(const el of monitoringWorkflowForm.querySelectorAll('input,select,textarea'))el.disabled=true;
  const projectId=monitoringWorkflowEdit.project_id;
  await monitoringRequest('workflow-save',monitoringAttempt);
  if(activeProject?.id!==projectId)return false;
  monitoringAttempt=null;monitoringDirty=false;monitoringWorkflowForm.hidden=true;await loadMonitoring();
  monitoringStatus.textContent='Zadání těžby a zpracování je uložené. Těžbu zapnete samostatně v detailu.';return true;
 }catch(error){monitoringStatus.textContent=error.message;return false;}
}
monitoringWorkflowForm.addEventListener('input',()=>{monitoringDirty=true;});
monitoringWorkflowForm.addEventListener('submit',event=>{event.preventDefault();saveMonitoringWorkflow();});
document.querySelector('#monitoring-workflow-new').addEventListener('click',()=>editMonitoringWorkflow());
document.querySelector('#monitoring-workflow-cancel').addEventListener('click',async()=>{if(await canLeaveMonitoring())monitoringWorkflowForm.hidden=true;});
'''
