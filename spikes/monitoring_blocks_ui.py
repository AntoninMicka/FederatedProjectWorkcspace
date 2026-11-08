# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Separate reusable block catalogs and a form-based complex-task composer."""
HTML='''
<section id="monitoring-blocks" aria-label="Stavební bloky sledování">
<p>Zdroje → filtry → pooly → zpracování. Komplexní úlohy skládají společné bloky.</p>
<nav id="monitoring-block-tabs" aria-label="Části sledování"></nav>
<div id="monitoring-block-toolbar"></div><p id="monitoring-block-state" role="status"></p>
<div id="monitoring-block-content"></div>
<form id="monitoring-block-editor" hidden><h3 id="monitoring-block-editor-title"></h3>
<div id="monitoring-block-fields"></div>
<button type="submit">Uložit blok</button><button id="monitoring-block-cancel" type="button">Zrušit</button></form>
<form id="monitoring-compose" hidden><h3>Sestavit komplexní úlohu pomocí LLM</h3>
<label>Co má úloha sledovat a jaký výstup očekáváte?<textarea name="goal" required maxlength="8000" rows="5"></textarea></label>
<p>Model dostane popis a katalog bloků s kontrolou soukromí. Návrh před uložením můžete upravit.</p>
<button type="submit">Navrhnout sestavu</button></form>
<section id="monitoring-composition-review" hidden><h3>Návrh sestavy k posouzení</h3>
<p id="monitoring-composition-explanation"></p><ul id="monitoring-composition-blocks"></ul>
<button id="monitoring-composition-save" type="button">Uložit posouzenou sestavu</button>
<button id="monitoring-composition-cancel" type="button">Zahodit návrh</button></section>
</section>
'''
CSS='''
#monitoring-block-tabs{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem}
#monitoring-block-tabs button{background:#eaf0f4;color:#23394b;border:1px solid #c7d4dc}
#monitoring-block-tabs button[aria-pressed=true]{background:#176b60;color:white;box-shadow:inset 0 -3px 0 #0b403a}
#monitoring-block-toolbar{display:flex;gap:.5rem;flex-wrap:wrap}
#monitoring-block-content article{padding:1rem;border:1px solid #c7d4dc;border-radius:.5rem;margin:1rem 0}
#monitoring-block-fields fieldset{margin:1rem 0}#monitoring-block-fields select[multiple]{min-height:7rem}
#monitoring-block-content pre{white-space:pre-wrap;overflow-wrap:anywhere}
'''
JS=r'''
const blockLabels={source:'Zdroje',filter:'Filtry',pool:'Pooly zpráv',processing:'Zpracování zpráv',task:'Komplexní úlohy',runs:'Výsledky a běhy'};
let blockLoadSequence=0,blockEditHead=null,blockCatalog=null,blockTab='task',blockEdit=null,blockProposal=null,blockSaving=null,blockParent=null,blockComposeRun=null;
const blockEditor=document.querySelector('#monitoring-block-editor'),blockFields=document.querySelector('#monitoring-block-fields');
function blockText(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
function blockStatus(text){document.querySelector('#monitoring-block-state').textContent=text;}
function blockRows(){return [...(blockCatalog?.blocks||[]).filter(b=>!blockProposal?.proposal.blocks.some(p=>p.id===b.id)),...(blockProposal?.proposal.blocks||[]).map(b=>({...b,ref:b.previous[0]||null,used_by:[],tasks:[]}))];}
function blockName(id){return blockRows().find(b=>b.id===id)?.value.title||'Nedostupný blok';}
function blockReadOnly(){return activeProject?.readOnly||!blockCatalog?.can_manage;}
async function loadMonitoringBlocks(){
 if(!activeProject)return;const pid=activeProject.id,sequence=++blockLoadSequence;
 try{const result=await monitoringRequest('blocks');if(activeProject?.id!==pid||sequence!==blockLoadSequence)return;
  blockCatalog=result;if(!blockEdit&&!blockProposal)renderMonitoringBlocks();
 }catch(e){if(activeProject?.id===pid)blockStatus(e.message);}
}
function renderMonitoringBlocks(){
 if(!blockCatalog)return;
 if(!monitoringView?.error)monitoringStatus.textContent=blockCatalog.blocks.filter(b=>b.value.kind==='task').length+' komplexních úloh · '+blockCatalog.blocks.filter(b=>b.value.kind==='source').length+' zdrojů · '+blockCatalog.blocks.filter(b=>b.value.kind==='pool').length+' poolů';
 const taskList=document.querySelector('#sidebar-monitoring-list');
 taskList.querySelectorAll('[data-composable-task]').forEach(e=>e.remove());
 for(const row of blockCatalog.blocks.filter(b=>b.value.kind==='task')){
  const li=document.createElement('li');li.dataset.composableTask=row.id;
  li.append(monitoringButton(row.value.title,async()=>{if(!await canLeaveMonitoringBlocks())return;monitoringOpen();blockTab='task';renderMonitoringBlocks();const target=document.querySelector('[data-monitoring-block-id="'+row.id+'"]');if(target){target.tabIndex=-1;target.focus({preventScroll:true});}}));taskList.append(li);
 }
 const reportList=document.querySelector('#sidebar-report-list');reportList.querySelectorAll('[data-composable-report]').forEach(e=>e.remove());
 for(const job of blockCatalog.jobs.filter(j=>j.state==='published'&&j.intent.kind==='processing')){
  const li=document.createElement('li');li.dataset.composableReport=job.id;li.append(monitoringButton(job.intent.block.value.title,async()=>{if(!await canLeaveMonitoringBlocks())return;monitoringOpen('outputs');blockTab='runs';renderMonitoringBlocks();}));reportList.append(li);
 }
 const tabs=document.querySelector('#monitoring-block-tabs');tabs.replaceChildren();
 for(const [kind,label] of Object.entries(blockLabels)){
  const count=kind==='runs'?blockCatalog.jobs.filter(j=>j.intent.kind!=='intake').length:blockRows().filter(b=>b.value.kind===kind).length;
  const b=monitoringButton(label+' ('+count+')',async()=>{if(!await canLeaveMonitoringBlocks())return;blockTab=kind;renderMonitoringBlocks();});
  b.setAttribute('aria-pressed',String(kind===blockTab));tabs.append(b);
 }
 const toolbar=document.querySelector('#monitoring-block-toolbar');toolbar.replaceChildren();
 if(blockTab!=='runs')toolbar.append(monitoringButton('Vytvořit nový blok',()=>editMonitoringBlock(blockTab),blockReadOnly()));
 if(blockTab==='task')toolbar.append(monitoringButton('Sestavit pomocí LLM',()=>{
  document.querySelector('#monitoring-compose').hidden=false;document.querySelector('#monitoring-compose textarea').focus();
 },blockReadOnly()));
 toolbar.append(monitoringButton('Obnovit přehled',()=>loadMonitoringBlocks()));
 const content=document.querySelector('#monitoring-block-content');content.replaceChildren();
 if(blockTab==='runs'){
  for(const j of blockCatalog.jobs){
   const article=document.createElement('article');article.append(blockText('h3',j.intent.block?.value.title||j.intent.kind));
   article.append(blockText('p','Stav: '+j.state));if(j.result?.error)article.append(blockText('p',j.result.error));
   if(j.result?.children)for(const c of j.result.children)article.append(blockText('p',blockName(c.block_id)+' · '+c.state));
   if(j.result?.markdown)article.append(blockText('pre',j.result.markdown));
   if(j.state==='review'&&j.intent.kind==='processing')article.append(monitoringButton('Vydat posouzenou zprávu',async()=>{
    if(!window.confirm('Vydat přesně tento návrh zprávy do projektu?'))return;
    await monitoringRequest('block-publish',{run_id:j.id,approval_digest:j.result.approval_digest,confirm:true});await loadMonitoringBlocks();
   },blockReadOnly()));
   if(j.state==='unknown'&&j.intent.kind==='intake')article.append(monitoringButton('Uzavřít neznámý příjem a povolit další kontrolu',async()=>{
    if(!window.confirm('Původní výsledek zůstane neznámý. Povolit další kontrolu zdroje?'))return;
    await monitoringRequest('block-release',{job_id:j.id,confirm:true});await loadMonitoringBlocks();
   },blockReadOnly()));
   content.append(article);
  }
  return;
 }
 const rows=blockRows().filter(b=>b.value.kind===blockTab);
 if(!rows.length)content.append(blockText('p','Zatím žádné položky. Vytvořte blok nebo jej přidejte při sestavování úlohy.'));
 for(const row of rows){
  const article=document.createElement('article'),c=row.value.config;article.dataset.monitoringBlockId=row.id;article.append(blockText('h3',row.value.title));
  if(row.value.kind==='task')article.append(blockText('p','Spuštění úlohy: '+(row.run_count||0)));
  const usage=row.used_by||[];article.append(monitoringButton(usage.length?'Využití: '+usage.length+' bloků · '+(row.tasks||[]).length+' úloh':'Zatím nepoužito',()=>{
   const list=document.createElement('ul');for(const id of usage)list.append(blockText('li',blockName(id)));article.append(list);
  }));
  article.append(monitoringButton('Upravit',()=>editMonitoringBlock(blockTab,row),blockReadOnly()));
  if(blockTab==='source'){
   article.append(blockText('p',c.connector==='rss-atom'?c.locator+' · každých '+c.poll_seconds/60+' min · redundantní sběr na zapojených uzlech':'Webové hledání na vyžádání: '+c.locator));
   article.append(blockText('p','Podmínky: '+c.terms+' · uchování: '+c.retention));
   if(c.connector==='rss-atom'){
    article.append(blockText('p','Tento uzel: '+(row.runtime?.enabled?'sběr zapnutý':'sběr vypnutý')+' · poslední úspěch: '+(row.runtime?.last_success||'zatím žádný')+' · příští kontrola: '+(row.runtime?new Date(row.runtime.next_due*1000).toLocaleString():'nenastavena')));
    if(row.runtime?.error)article.append(blockText('p',row.runtime.error));
    article.append(monitoringButton(row.runtime?.enabled?'Pozastavit zdejší sběr':'Zapnout sběr na tomto uzlu',async()=>{
     await monitoringRequest('block-configure',{block_id:row.id,enabled:!row.runtime?.enabled,confirm:true});await loadMonitoringBlocks();
    },blockReadOnly()));
    if(row.runtime?.error)article.append(monitoringButton('Potvrdit aktuální konfiguraci sběru',async()=>{await monitoringRequest('block-configure',{block_id:row.id,enabled:true,confirm:true});await loadMonitoringBlocks();},blockReadOnly()));
    article.append(monitoringButton('Zkontrolovat splatné kanály',async()=>{await monitoringRequest('block-tick');await loadMonitoringBlocks();},blockReadOnly()));
   }
  }else if(blockTab==='filter')article.append(blockText('p',c.source_ids.map(blockName).join(', ')+' → '+blockName(c.pool_id)));
  else if(blockTab==='pool'){
   article.append(blockText('p',(row.message_count??0)+' uložených zpráv · uchování '+c.retention_days+' dní'));
   article.append(blockText('p',row.last_received_sync?'Poslední příjem synchronizace: '+new Date(row.last_received_sync).toLocaleString():'Synchronizace přes sdílení projektu · zatím žádný potvrzený příjem'));
   article.append(monitoringButton('Otevřít zprávy a původ',async()=>{
    const pid=activeProject.id,result=await monitoringRequest('pool-view',{pool_id:row.id});if(activeProject?.id!==pid)return;
    const list=document.createElement('div');
    for(const group of result.messages){
     const item=document.createElement('article');
     for(const rev of group.revisions){item.append(blockText('h4',rev.item.title||'Bez názvu'));item.append(blockText('p',rev.item.content||''));
      if(rev.item.url){const a=blockText('a',rev.item.url);a.href=rev.item.url;a.target='_blank';a.rel='noopener noreferrer';item.append(a);}}
     item.append(blockText('p','Vybraly filtry: '+[...new Set(group.contributions.map(c=>blockName(c.filter_id)))].join(', ')));
     item.append(blockText('p','Pozorovaly uzly: '+[...new Set(group.observations.map(o=>o.node_id))].join(', ')+(group.concurrent_versions?' · více obsahových verzí':'')));
     list.append(item);
    }article.append(list);
   }));
  }else if(blockTab==='processing'){
   article.append(blockText('p',c.pool_ids.map(blockName).join(', ')+(c.search_ids.length?' + hledání: '+c.search_ids.map(blockName).join(', '):'')+' → '+c.instructions));
   article.append(blockText('p',c.schedule.kind==='manual'?'Na vyžádání':'Denně v '+c.schedule.time+' ('+c.schedule.timezone+')'));
   article.append(monitoringButton('Sestavit návrh zprávy',async()=>{
    if((c.mode==='llm'||c.search_ids.length)&&!window.confirm('Spustit zpracování včetně nastaveného modelu nebo webového hledání?'))return;
    await monitoringRequest('block-process',{block_id:row.id,run_id:crypto.randomUUID()});blockTab='runs';await loadMonitoringBlocks();
   },blockReadOnly()||c.node_id!==blockCatalog.node_id));
   if(c.schedule.kind==='daily')article.append(monitoringButton(row.runtime?.enabled?'Pozastavit denní zpracování':'Zapnout denní zpracování',async()=>{
    await monitoringRequest('block-configure',{block_id:row.id,enabled:!row.runtime?.enabled,confirm:true});await loadMonitoringBlocks();
   },blockReadOnly()||c.node_id!==blockCatalog.node_id));
  }else{
   article.append(blockText('p',c.instructions));
   for(const kind of ['source','filter','pool','processing']){const ids=blockRows().filter(b=>b.value.kind===kind&&(row.resolved_ids||c[kind+'_ids']).includes(b.id)).map(b=>b.id);article.append(blockText('p',blockLabels[kind]+': '+ids.map(blockName).join(', ')));}
   article.append(monitoringButton('Sestavit zprávy úlohy',async()=>{
    if(!window.confirm('Spustit zpracování této úlohy včetně jejích modelů a hledání?'))return;
    await monitoringRequest('block-task-run',{block_id:row.id,run_id:crypto.randomUUID()});
    blockTab='runs';await loadMonitoringBlocks();
   },blockReadOnly()));
  }
  content.append(article);
 }
}
function blockField(name,label,type,value,options=[]){
 const wrap=document.createElement('label');wrap.append(document.createTextNode(label));
 const input=document.createElement(type==='textarea'?'textarea':type==='select'||type==='multi'?'select':'input');
 input.name=name;input.required=!['keywords','regex','search_ids','source_ids','filter_ids','pool_ids'].includes(name);
 if(type==='select'||type==='multi'){
  input.multiple=type==='multi';for(const o of options){const opt=document.createElement('option');opt.value=o.id;opt.textContent=o.title;opt.selected=type==='multi'?(value||[]).includes(o.id):value===o.id;input.append(opt);}
 }else{input.type=type==='textarea'?'text':type;input.value=value??'';if(type==='number'){input.min='1';input.max='3650';}}
 wrap.append(input);blockFields.append(wrap);return input;
}
function blockOptions(kind,predicate=()=>true){return blockRows().filter(b=>b.value.kind===kind&&predicate(b.value.config)).map(b=>({id:b.id,title:b.value.title}));}
function blockDefaults(kind){
 if(kind==='source')return {connector:'rss-atom',locator:'',poll_seconds:900,terms:'',retention:'30 dní'};
 if(kind==='filter')return {source_ids:[],pool_id:'',pipeline:{schema:'fpw-monitoring-pipeline-v1',revision:'1',steps:[{id:'dedup',kind:'dedup',field:'content_sha256'}]}};
 if(kind==='pool')return {retention_days:30};
 if(kind==='processing')return {pool_ids:[],search_ids:[],instructions:'Shrnout zprávy a uvést zdroje a omezení.',mode:'deterministic',schedule:{kind:'manual',time:'07:00',timezone:'Europe/Prague'},lookback_days:7,node_id:blockCatalog.node_id};
 return {source_ids:[],filter_ids:[],pool_ids:[],processing_ids:[],instructions:''};
}
async function editMonitoringBlock(kind,row=null,restore=null){
 if(blockSaving){blockStatus('Nejdříve dokončete původní pokus o uložení nebo zrušte editor.');return;}
 if(blockEdit&&!restore&&!await canLeaveMonitoringBlocks())return;
 blockEdit=restore||{id:row?.id||crypto.randomUUID(),previous:row?.ref?[row.ref]:[],privacy:row?.privacy||'project',value:structuredClone(row?.value||{schema:'fpw-reporting-block-v1',kind,title:'',config:blockDefaults(kind)})};
 blockEditHead=blockCatalog.commit_id;blockFields.replaceChildren();document.querySelector('#monitoring-block-editor-title').textContent=blockLabels[kind]+' — '+(row?'úprava':'nový blok');
 const v=blockEdit.value,c=v.config;
 blockField('title','Název','text',v.title);const privacy=blockField('privacy','Soukromí','select',blockEdit.privacy,[{id:'public',title:'Veřejné'},{id:'project',title:'Projekt'},{id:'confidential',title:'Důvěrné'},{id:'local-only',title:'Pouze lokálně'}]);privacy.disabled=blockEdit.previous.length>0;
 if(kind==='source'){
  blockField('connector','Typ zdroje','select',c.connector,[{id:'rss-atom',title:'RSS / Atom'},{id:'web-search',title:'Webové hledání na vyžádání'}]);
  blockField('locator','Adresa kanálu / dotaz hledání','text',c.locator);const poll=blockField('poll_minutes','Interval RSS v minutách','number',(c.poll_seconds||900)/60);poll.max='10080';
  blockField('terms','Podmínky přístupu a licence','textarea',c.terms);blockField('retention','Podmínky uchování zdroje','textarea',c.retention);
 }else if(kind==='pool')blockField('retention_days','Uchování zpráv ve dnech','number',c.retention_days);
 else if(kind==='filter'){
  blockField('source_ids','Vstupní kanály (lze vybrat více)','multi',c.source_ids,blockOptions('source',c=>c.connector==='rss-atom'));
  blockField('pool_id','Cílový pool','select',c.pool_id,blockOptions('pool'));
  const steps=c.pipeline.steps,simple=steps.every(s=>s.kind==='dedup'?s.field==='content_sha256':
   s.kind==='keywords'?s.all.length===0&&s.none.length===0&&!s.case_sensitive&&JSON.stringify(s.fields)===JSON.stringify(['title','content']):
   s.kind==='regex'?s.match==='search'&&!s.negate&&JSON.stringify(s.flags)===JSON.stringify(['IGNORECASE'])&&JSON.stringify(s.fields)===JSON.stringify(['title','content']):false)&&
   steps.filter(s=>s.kind==='keywords').length<=1&&steps.filter(s=>s.kind==='regex').length<=1&&steps.at(-1).kind==='dedup';
  if(simple){
   blockField('keywords','Vybrat některý výraz (jeden na řádku)','textarea',steps.find(s=>s.kind==='keywords')?.any.join('\n')||'');
   blockField('regex','Regulární výraz (volitelný)','text',steps.find(s=>s.kind==='regex')?.pattern||'');
  }else blockFields.append(blockText('p','Filtr používá pokročilá pravidla. Tento formulář zachová jejich přesné znění; upravit lze název a propojení.'));

 }else if(kind==='processing'){
  blockField('pool_ids','Vstupní pooly','multi',c.pool_ids,blockOptions('pool'));blockField('search_ids','Hledání při sestavení zprávy','multi',c.search_ids,blockOptions('source',c=>c.connector==='web-search'));
  blockField('instructions','Zadání zprávy','textarea',c.instructions);blockField('mode','Zpracování','select',c.mode,[{id:'deterministic',title:'Přehled bez LLM'},{id:'llm',title:'Pomocí nastaveného LLM'}]);
  blockField('lookback_days','Zprávy za posledních dní','number',c.lookback_days);blockField('schedule_kind','Spouštění','select',c.schedule.kind,[{id:'manual',title:'Na vyžádání'},{id:'daily',title:'Denně'}]);
  blockField('time','Čas denního zpracování','time',c.schedule.time);blockField('timezone','Časová zóna','text',c.schedule.timezone);
  const nodes=monitoringView?.execution_nodes?.nodes||[{id:blockCatalog.node_id,name:'Tento uzel'}];
  blockField('node_id','Uzel pro zpracování','select',c.node_id,nodes.map(n=>({id:n.id,title:n.name})));
 }else{
  blockField('instructions','Záměr komplexní úlohy','textarea',c.instructions);
  for(const k of ['source','filter','pool','processing']){
   blockField(k+'_ids',blockLabels[k]+' — použít existující','multi',c[k+'_ids'],blockOptions(k));
   blockFields.append(monitoringButton('Vytvořit nové: '+blockLabels[k],async()=>{
    blockParent=readMonitoringBlock();blockEdit=null;await editMonitoringBlock(k);
   }));
  }
 }
 blockEditor.hidden=false;blockEditor.elements.title.focus();blockStatus('');
}
function readMonitoringBlock(){
 const b=structuredClone(blockEdit),f=blockEditor.elements,c=b.value.config,get=n=>f[n].value,sel=n=>[...f[n].selectedOptions].map(o=>o.value);
 b.value.title=get('title');b.privacy=get('privacy');const kind=b.value.kind;
 if(kind==='source')Object.assign(c,{connector:get('connector'),locator:get('locator'),poll_seconds:get('connector')==='web-search'?null:Number(get('poll_minutes'))*60,terms:get('terms'),retention:get('retention')});
 else if(kind==='pool')c.retention_days=Number(get('retention_days'));
 else if(kind==='filter'){
  c.source_ids=sel('source_ids');c.pool_id=get('pool_id');if(!f.keywords)return b;const steps=[],words=get('keywords').split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
  if(words.length)steps.push({id:'keywords',kind:'keywords',fields:['title','content'],all:[],any:words,none:[],case_sensitive:false});
  if(get('regex'))steps.push({id:'regex',kind:'regex',fields:['title','content'],pattern:get('regex'),flags:['IGNORECASE'],match:'search',negate:false});
  steps.push({id:'dedup',kind:'dedup',field:'content_sha256'});c.pipeline={schema:'fpw-monitoring-pipeline-v1',revision:crypto.randomUUID(),steps};
 }else if(kind==='processing')Object.assign(c,{pool_ids:sel('pool_ids'),search_ids:sel('search_ids'),instructions:get('instructions'),mode:get('mode'),lookback_days:Number(get('lookback_days')),node_id:get('node_id'),schedule:{kind:get('schedule_kind'),time:get('time'),timezone:get('timezone')}});
 else{
  c.instructions=get('instructions');for(const k of ['source','filter','pool','processing'])c[k+'_ids']=sel(k+'_ids');
  // Include dependencies of selected shared blocks without copying their definitions.
  const rows=blockRows(),chosen=new Set(Object.values(c).filter(Array.isArray).flat());
  for(let repeat=0;repeat<4;repeat++)for(const r of rows.filter(r=>chosen.has(r.id))){const x=r.value.config;
   for(const d of [...(x.source_ids||[]),...(x.pool_ids||[]),...(x.search_ids||[]),...(x.pool_id?[x.pool_id]:[])])chosen.add(d);}
  for(const k of ['source','filter','pool','processing'])c[k+'_ids']=rows.filter(r=>r.value.kind===k&&chosen.has(r.id)).map(r=>r.id);
 }
 return b;
}
async function canLeaveMonitoringBlocks(){
 if(!blockEdit&&!blockProposal&&!blockComposeRun)return true;
 if(!window.confirm('Zahodit rozpracovanou úpravu bloku nebo návrh sestavy?'))return false;
 blockEdit=null;blockProposal=null;blockComposeRun=null;blockParent=null;blockSaving=null;blockEditor.hidden=true;
 document.querySelector('#monitoring-composition-review').hidden=true;return true;
}
blockEditor.addEventListener('submit',async e=>{
 e.preventDefault();if(!blockEditor.reportValidity())return;const pid=activeProject.id;
 try{
  const b=readMonitoringBlock();
  if(blockProposal){const index=blockProposal.proposal.blocks.findIndex(p=>p.id===b.id);if(index>=0)blockProposal.proposal.blocks[index]=b;else blockProposal.proposal.blocks.push(b);}
  else{
   if(!blockSaving)blockSaving={base_head:blockEditHead,blocks:[b],operation_id:crypto.randomUUID()};
   for(const field of blockEditor.querySelectorAll('input,select,textarea'))field.disabled=true;
   await monitoringRequest('blocks-save',blockSaving);if(activeProject?.id!==pid)return;blockSaving=null;
  }
  blockEdit=null;blockEditor.hidden=true;await loadMonitoringBlocks();
  if(blockParent){const parent=blockParent;blockParent=null;parent.value.config[b.value.kind+'_ids'].push(b.id);await editMonitoringBlock('task',null,parent);}
  else if(blockProposal)renderBlockProposal();else renderMonitoringBlocks();
 }catch(err){blockStatus(err.message);}
});
document.querySelector('#monitoring-block-cancel').addEventListener('click',async()=>{if(await canLeaveMonitoringBlocks())renderMonitoringBlocks();});
document.querySelector('#monitoring-compose').addEventListener('submit',async e=>{
 e.preventDefault();const pid=activeProject.id,form=e.currentTarget;
 try{if(!blockComposeRun)blockComposeRun={run_id:crypto.randomUUID(),goal:form.elements.goal.value,confirm:true};
  form.querySelector('button').disabled=true;blockStatus('Model navrhuje sestavu…');
  const result=await monitoringRequest('block-compose',blockComposeRun);if(activeProject?.id!==pid)return;
  if(result.state!=='review')throw Error('Stav návrhu: '+result.state+' · '+(result.result?.error||''));
  blockProposal=result.result;blockComposeRun=null;form.hidden=true;renderBlockProposal();
 }catch(err){blockStatus(err.message);}finally{form.querySelector('button').disabled=false;}
});
function renderBlockProposal(){
 document.querySelector('#monitoring-composition-review').hidden=false;
 document.querySelector('#monitoring-composition-explanation').textContent=blockProposal.proposal.explanation;
 const list=document.querySelector('#monitoring-composition-blocks');list.replaceChildren();
 for(const b of blockProposal.proposal.blocks){const li=document.createElement('li');li.append(blockText('span',(b.previous.length?'Upravit: ':'Nový blok: ')+b.value.title+' · '+blockLabels[b.value.kind]));li.append(monitoringButton('Upravit návrh',()=>editMonitoringBlock(b.value.kind,{...b,ref:b.previous[0]||null})));list.append(li);}
 const reused=new Set();for(const b of blockProposal.proposal.blocks){const c=b.value.config;for(const key of ['source_ids','pool_ids','search_ids','filter_ids','processing_ids'])for(const id of c[key]||[])if(!blockProposal.proposal.blocks.some(p=>p.id===id))reused.add(id);}
 for(const id of reused)list.append(blockText('li','Použít existující: '+blockName(id)));
}
document.querySelector('#monitoring-composition-save').addEventListener('click',async()=>{
 try{if(!blockSaving)blockSaving={base_head:blockProposal.base_head,blocks:blockProposal.proposal.blocks,operation_id:crypto.randomUUID()};
  await monitoringRequest('blocks-save',blockSaving);blockSaving=null;blockProposal=null;blockEdit=null;blockEditor.hidden=true;
  document.querySelector('#monitoring-composition-review').hidden=true;await loadMonitoringBlocks();blockStatus('Sestava uložená. Sběr a plánované zpracování aktivujte samostatně.');
 }catch(e){blockStatus(e.message);}
});
document.querySelector('#monitoring-composition-cancel').addEventListener('click',async()=>{if(await canLeaveMonitoringBlocks())renderMonitoringBlocks();});
'''
