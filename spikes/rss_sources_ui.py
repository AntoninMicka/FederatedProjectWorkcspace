# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared Sources page with channel tabs and aggregated entries."""
HTML = '''<div id="sources-view" hidden>
<header class="sources-header"><div><h1 id="sources-heading">Zdroje</h1><p>Nové články z odebíraných kanálů.</p></div>
<div><button id="sources-edit" type="button" hidden>Upravit kanál</button><button id="sources-refresh" type="button">Načíst kanály</button></div></header>
<form id="sources-editor" hidden><h2 id="sources-editor-title">Nový zdroj</h2>
<label>Název<input name="name" required maxlength="300"></label>
<label>URL kanálu<input name="url" type="url" required placeholder="https://…"></label>
<label>Perioda obnovy v minutách<input name="minutes" type="number" min="1" max="10080" value="15" required></label>
<p>Automatická obnova běží při otevřené čtečce. Odběr lze sdílet s vybranými uzly; projektovou těžbu neaktivuje.</p>
<button type="submit">Uložit zdroj</button><button id="sources-editor-cancel" type="button">Zrušit</button></form>
<section id="sources-import-review" hidden><h2>Import odběrů</h2>
<p>OPML (.opml/.xml) nebo JSON seznam odběrů. Import nestahuje články. Výchozí perioda je 15 minut.</p>
<input id="sources-import-file" type="file" accept=".opml,.xml,.json,application/xml,text/xml,application/json">
<div id="sources-import-items"></div><button id="sources-import-save" type="button" disabled>Importovat vybrané</button>
<button id="sources-import-cancel" type="button">Zrušit</button></section>
<p id="sources-status" role="status" aria-live="polite">Kanály zatím nebyly načteny.</p>
<details id="sources-reader-sync" hidden><summary>Synchronizace odběrů mezi uzly</summary>
<p>Na obou vybraných uzlech povolte sdílení. Přenášejí se názvy, URL a intervaly; cache článků a projektová aktivace sběru zůstávají místní. Automatická kontrola probíhá přibližně jednou za minutu.</p>
<div id="sources-reader-sync-peers"></div><div id="sources-reader-sync-conflicts"></div></details>
<div id="sources-feed" role="tabpanel" aria-label="Články z vybraných kanálů" tabindex="0"></div>
<details id="sources-connectors"><summary>Typy zdrojů a dostupnost</summary><ul id="sources-connector-list"></ul></details>
</div>'''
CSS = '''
#sources-view{max-width:1100px;margin:0 auto;padding:clamp(12px,3vw,32px);width:100%;box-sizing:border-box;overflow:auto}
.sources-header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.sources-header>div:last-child{display:flex;gap:8px;flex-wrap:wrap}
.sources-header h1{margin:0}.sources-header p{color:#526678}
#sources-channel-tabs{list-style:none;padding:0;margin:14px 0;overflow-y:auto;min-height:0;flex:1;scrollbar-width:thin}
#sources-channel-tabs .sidebar-list-main{display:block;text-align:left;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px;white-space:normal;overflow-wrap:anywhere}
#sources-channel-tabs .sidebar-list-main:hover{background:#274154}
#sidebar-sources{overflow:visible}
.sources-primary-actions{display:flex;gap:8px}
.sources-primary-actions button{position:relative;width:38px;height:38px;display:grid;place-items:center;padding:8px}
.sources-primary-actions svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sources-action-label{position:absolute;z-index:60;top:calc(100% + 8px);left:0;padding:7px 9px;border:1px solid #496072;border-radius:7px;background:#07131f;color:#f4f8fb;font-size:12px;white-space:nowrap;opacity:0;visibility:hidden;pointer-events:none;box-shadow:0 5px 16px #07131f66}
.sources-primary-actions button:hover .sources-action-label,.sources-primary-actions button:focus-visible .sources-action-label{opacity:1;visibility:visible}
#sources-editor label{display:flex;flex-direction:column;gap:6px;margin:12px 0}
#sources-editor input{width:100%;box-sizing:border-box}
#sources-import-items label{display:flex;gap:8px;margin:12px 0;overflow-wrap:anywhere}
.source-entry{padding:18px 0;border-bottom:1px solid #dce5ea}.source-entry h2{font-size:19px;line-height:1.4;margin:6px 0}
.source-entry a{color:#176b60;text-decoration:none}.source-entry a:hover{text-decoration:underline}
.source-entry-meta{font-size:13px;color:#526678}.source-entry-meta time{margin-left:12px}
#sources-status{white-space:pre-line;color:#526678;line-height:1.6}
#sources-reader-sync{overflow-wrap:anywhere}
#sources-reader-sync-peers p{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#sources-reader-sync-conflicts button{margin:4px 8px 4px 0;max-width:100%;white-space:normal;overflow-wrap:anywhere}
'''
JS = r'''
let sourcesView=null,sourcesChannel='all',sourcesBusy=false,sourcesSequence=0,sourcesEditing=null,sourcesSaving=false,sourcesDirty=false,sourcesPending=null,sourcesImport=null;
const sourcesEditor=document.getElementById('sources-editor'),sourcesImportReview=document.getElementById('sources-import-review');
const sourcesTabs=document.getElementById('sources-channel-tabs'),sourcesFeed=document.getElementById('sources-feed');
const sourcesStatus=document.getElementById('sources-status'),sourcesRefresh=document.getElementById('sources-refresh');
function renderSources(){
 if(!sourcesView)return;
 renderReaderSync();
 if(!['all',...sourcesView.channels.map(c=>c.id)].includes(sourcesChannel))sourcesChannel='all';
 document.getElementById('sources-heading').textContent=sourcesChannel==='all'?'Zdroje':sourcesView.channels.find(c=>c.id===sourcesChannel).name;
 document.getElementById('sources-count').textContent='Počet kanálů: '+sourcesView.channels.length;
 for(const id of ['sources-new','sources-import'])document.getElementById(id).disabled=!sourcesView.can_refresh;
 const edit=document.getElementById('sources-edit');edit.hidden=sourcesChannel==='all';edit.disabled=!sourcesView.can_refresh;
 const catalog=document.getElementById('sources-connector-list');catalog.replaceChildren();
 const availability={ready:'Dostupné',unavailable:'Nedostupné','not-configured':'Nepřipojeno'};
 for(const connector of sourcesView.connectors||[]){const li=document.createElement('li');li.textContent=connector.name+' — '+(availability[connector.availability.state]||'Neznámý stav')+'. '+connector.availability.reason;catalog.append(li);}
 const tabs=[{id:'all',name:'Všechny'},...sourcesView.channels];sourcesTabs.replaceChildren();
 for(const channel of tabs){
  const row=document.createElement('li');row.className='sidebar-list-row';row.setAttribute('role','presentation');
  const b=document.createElement('button');b.className='sidebar-list-main';b.type='button';b.setAttribute('role','tab');b.id='source-channel-'+channel.id;
  b.textContent=channel.name;b.setAttribute('aria-current',String(channel.id===sourcesChannel));b.setAttribute('aria-controls','sources-feed');b.setAttribute('aria-selected',String(channel.id===sourcesChannel));b.tabIndex=channel.id===sourcesChannel?0:-1;
  b.addEventListener('click',()=>{if(!canLeaveSources())return;sourcesChannel=channel.id;closeSourcesEditor();renderSources();document.getElementById(b.id).focus();});
  const open=()=>b.click();
  const actions=[{label:'Zobrazit obsah',run:open}];
  if(channel.id!=='all')actions.push({label:'Upravit kanál',disabled:!sourcesView.can_refresh,run:()=>{if(!canLeaveSources())return;sourcesChannel=channel.id;renderSources();editSource(channel);}});
  actions.push({label:'Načíst články',disabled:!sourcesView.can_refresh||sourcesBusy,run:()=>{if(!canLeaveSources())return;sourcesChannel=channel.id;closeSourcesEditor();renderSources();return loadSources(true);}});
  row.append(b,sidebarItemMenu(channel.name,actions,'sources-channel-menu'));sourcesTabs.append(row);
 }
 sourcesFeed.setAttribute('aria-labelledby','source-channel-'+sourcesChannel);sourcesFeed.replaceChildren();
 const entries=sourcesView.entries.filter(e=>sourcesChannel==='all'||e.channel_id===sourcesChannel);
 const channels=sourcesView.channels.filter(c=>sourcesChannel==='all'||c.id===sourcesChannel);
 sourcesStatus.textContent=entries.length+' článků\n'+channels.map(c=>{
  const checked=c.checked_at?new Date(c.checked_at).toLocaleString('cs-CZ'):'dosud nenačteno';
  if(c.error)return c.name+': '+(c.state==='unavailable'?'Nedostupné':c.state==='unknown'?'Neznámý výsledek':'Chyba načítání')+' — '+c.error+'. Poslední úspěšné načtení: '+checked+'.';
  return c.name+': '+(c.state==='loading'?'Načítá se…':checked);
 }).join('\n');
 if(!entries.length){const p=document.createElement('p');p.textContent=channels.some(c=>c.state==='unloaded')?'Pro načtení článků použijte tlačítko Načíst kanály.':'Žádné načtené články.';sourcesFeed.append(p);}
 for(const e of entries){
  const article=document.createElement('article');article.className='source-entry';
  const meta=document.createElement('div');meta.className='source-entry-meta';meta.textContent=e.channel_name;
  const date=document.createElement('time');if(e.published_at){date.dateTime=e.published_at;date.textContent=new Date(e.published_at).toLocaleString('cs-CZ');}else date.textContent='Datum publikace neuvedeno';meta.append(date);
  const heading=document.createElement('h2');let url=null;try{url=new URL(e.url);}catch(error){}
  if(url&&['http:','https:'].includes(url.protocol)&&!url.username&&!url.password){const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=e.title||'Článek bez titulku';heading.append(a);}else heading.textContent=e.title||'Článek bez titulku';
  article.append(meta,heading);if(e.content){const body=document.createElement('p');body.className='source-entry-content';body.textContent=e.content;article.append(body);}if(e.author){const p=document.createElement('p');p.textContent=e.author;article.append(p);}
  if(e.revisions>1){const small=document.createElement('small');small.textContent='Aktualizovaná položka';article.append(small);}sourcesFeed.append(article);
 }
 sourcesRefresh.disabled=sourcesBusy||!sourcesView.can_refresh;
 sourcesRefresh.textContent=sourcesBusy?'Načítám…':sourcesChannel==='all'?'Načíst kanály':'Načíst kanál';
}
async function readerSyncAction(path,request){
 if(!canLeaveSources()||!sourcesView?.can_refresh)return;
 sourcesSequence++;sourcesBusy=false;sourcesSaving=true;
 try{sourcesView=await projectRequest('/v1/rss-sources/'+path,request,60000);renderSources();sourcesStatus.textContent='Nastavení odběrů bylo aktualizováno.';}
 catch(error){try{sourcesView=await projectRequest('/v1/rss-sources/view',{});renderSources();}catch(reloadError){}sourcesStatus.textContent=error.message;}
 finally{sourcesSaving=false;}
}
function renderReaderSync(){
 const section=document.getElementById('sources-reader-sync'),sync=sourcesView?.reader_sync;
 section.hidden=!sourcesView?.can_refresh||!sync;if(section.hidden)return;
 const peers=document.getElementById('sources-reader-sync-peers');peers.replaceChildren();
 const known=new Map((sync.available_peers||[]).map(p=>[p.id,{...p,available:true}]));
 for(const p of sync.peers)if(!known.has(p.id))known.set(p.id,{id:p.id,name:'Uzel již není schválený',available:false});
 if(!known.size)peers.textContent='Nejsou dostupné schválené uzly pro sdílení.';
 for(const p of known.values()){
  const saved=sync.peers.find(s=>s.id===p.id),row=document.createElement('p'),label=document.createElement('label'),check=document.createElement('input');
  check.type='checkbox';check.checked=!!saved?.enabled;check.disabled=!p.available&&!saved?.enabled;
  check.addEventListener('change',()=>readerSyncAction('sync-settings',{peer_id:p.id,enabled:check.checked,expected_enabled:!!saved?.enabled}));
  label.append(check,document.createTextNode(' Sdílet odběry s '+p.name));row.append(label);
  const status=document.createElement('span');status.textContent=' · '+({idle:'Připraveno',pending:'Čeká na plný přenos',conflict:'Konflikt',error:'Chyba přenosu'})[saved?.state||'idle'];row.append(status);
  const button=document.createElement('button');button.type='button';button.textContent='Synchronizovat nyní';button.disabled=!p.available||!saved?.enabled;
  button.addEventListener('click',()=>readerSyncAction('sync',{peer_id:p.id}));row.append(button);peers.append(row);
 }
 const conflicts=document.getElementById('sources-reader-sync-conflicts');conflicts.replaceChildren();
 for(const conflict of sync.conflicts){
  const group=document.createElement('section'),title=document.createElement('h3');title.textContent='Rozdílné úpravy: '+conflict.url;group.append(title);
  for(const v of conflict.versions){
   const button=document.createElement('button');button.type='button';button.textContent=v.value?'Použít: '+v.value.name+' · '+v.value.poll_seconds/60+' min':'Potvrdit odstranění odběru';
   button.addEventListener('click',()=>readerSyncAction('sync-resolve',{url:conflict.url,chosen:v.id,revision:sourcesView.revision,tips:conflict.versions.map(v=>v.id)}));group.append(button);
  }
  conflicts.append(group);
 }
}
async function loadSources(refresh=false,dueOnly=false){
 const sequence=++sourcesSequence;
 if(refresh){sourcesBusy=true;sourcesRefresh.disabled=true;sourcesRefresh.textContent='Načítám…';}
 try{
  if(dueOnly){const latest=await projectRequest('/v1/rss-sources/view',{},60000);if(sequence!==sourcesSequence)return;sourcesView=latest;renderSources();}
  const channels=refresh?(sourcesChannel==='all'?(sourcesView?.channels||[]).filter(c=>!dueOnly||c.due).map(c=>c.id):[sourcesChannel]):[null];
  for(const id of dueOnly?channels.slice(0,1):channels){
   if(refresh&&(document.hidden||document.getElementById('sources-view').hidden))break;
   const result=await projectRequest('/v1/rss-sources/'+(refresh?'refresh':'view'),refresh?{channel_id:id,...(dueOnly?{due_only:true}:{})}:{},60000);
   if(sequence!==sourcesSequence)return;sourcesView=result;renderSources();
  }
 }catch(error){if(sequence===sourcesSequence)sourcesStatus.textContent=error.message;}
 finally{if(sequence===sourcesSequence){sourcesBusy=false;sourcesRefresh.disabled=!sourcesView?.can_refresh;sourcesRefresh.textContent=sourcesChannel==='all'?'Načíst kanály':'Načíst kanál';}}
}
sourcesRefresh.addEventListener('click',()=>loadSources(true));
sourcesTabs.addEventListener('keydown',event=>{
 if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
 const tabs=[...sourcesTabs.querySelectorAll('[role=tab]')],i=tabs.indexOf(document.activeElement);if(i<0)return;
 event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(['ArrowRight','ArrowDown'].includes(event.key)?1:-1)+tabs.length)%tabs.length;tabs[next].click();
});

function canLeaveSources(){
 if(sourcesSaving)return false;
 if(sourcesDirty||sourcesPending){if(!window.confirm('Zahodit rozpracované změny odběrů?'))return false;closeSourcesEditor();}
 return true;
}
function closeSourcesEditor(){
 sourcesImportSequence++;sourcesEditor.hidden=true;sourcesImportReview.hidden=true;sourcesEditing=null;sourcesDirty=false;sourcesPending=null;sourcesImport=null;
 sourcesFeed.hidden=false;sourcesRefresh.hidden=false;document.getElementById('sources-connectors').hidden=false;
}
function editSource(channel=null){
 if(!canLeaveSources())return;closeSourcesEditor();
 sourcesEditing=channel?{id:channel.id,name:channel.name,url:channel.url,poll_seconds:channel.poll_seconds}:{id:crypto.randomUUID(),name:'',url:'',poll_seconds:900};
 sourcesEditor.hidden=false;sourcesFeed.hidden=true;sourcesRefresh.hidden=true;document.getElementById('sources-edit').hidden=true;document.getElementById('sources-connectors').hidden=true;
 document.getElementById('sources-editor-title').textContent=channel?'Upravit kanál':'Nový zdroj';
 sourcesEditor.elements.name.value=sourcesEditing.name;sourcesEditor.elements.url.value=sourcesEditing.url;sourcesEditor.elements.minutes.value=sourcesEditing.poll_seconds/60;
 sourcesEditor.elements.name.focus();
}
async function saveSources(channels){
 if(sourcesBusy)return;sourcesBusy=true;sourcesSaving=true;sourcesEditor.inert=true;sourcesImportReview.inert=true;
 sourcesPending??={revision:sourcesView.revision,channels};
 try{sourcesView=await projectRequest('/v1/rss-sources/save',sourcesPending);sourcesChannel=channels[0].id;closeSourcesEditor();renderSources();sourcesStatus.textContent='Odběry byly uloženy.';}
 catch(e){sourcesStatus.textContent=e.message;}
 finally{sourcesBusy=false;sourcesSaving=false;sourcesEditor.inert=false;sourcesImportReview.inert=false;sourcesRefresh.disabled=!sourcesView?.can_refresh;sourcesRefresh.textContent=sourcesChannel==='all'?'Načíst kanály':'Načíst kanál';}
}
sourcesEditor.addEventListener('input',()=>{sourcesDirty=true;sourcesPending=null;});
sourcesEditor.addEventListener('submit',async event=>{
 event.preventDefault();if(!sourcesEditor.reportValidity())return;
 await saveSources([{...sourcesEditing,name:sourcesEditor.elements.name.value,url:sourcesEditor.elements.url.value,poll_seconds:Number(sourcesEditor.elements.minutes.value)*60}]);
});
document.getElementById('sources-new').addEventListener('click',()=>editSource());
document.getElementById('sources-edit').addEventListener('click',()=>editSource(sourcesView.channels.find(c=>c.id===sourcesChannel)));
for(const id of ['sources-editor-cancel','sources-import-cancel'])document.getElementById(id).addEventListener('click',()=>{if(canLeaveSources()){closeSourcesEditor();renderSources();}});
document.getElementById('sources-import').addEventListener('click',()=>{
 if(!canLeaveSources())return;closeSourcesEditor();sourcesImportReview.hidden=false;sourcesFeed.hidden=true;sourcesRefresh.hidden=true;document.getElementById('sources-edit').hidden=true;
 document.getElementById('sources-import-file').value='';document.getElementById('sources-import-items').replaceChildren();document.getElementById('sources-import-save').disabled=true;
});
let sourcesImportSequence=0;
document.getElementById('sources-import-file').addEventListener('change',async event=>{
 const file=event.target.files[0],sequence=++sourcesImportSequence;if(!file)return;
 try{
  if(file.size>512*1024)throw Error('Import je omezen na 512 KiB.');
  const result=await projectRequest('/v1/rss-sources/import-preview',{text:await file.text()});
  if(sequence!==sourcesImportSequence||sourcesImportReview.hidden)return;
  sourcesImport=result;sourcesDirty=true;sourcesPending=null;
  const list=document.getElementById('sources-import-items');list.replaceChildren();
  for(const channel of result.channels){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=true;check.value=channel.id;label.append(check,document.createTextNode(channel.name+' — '+channel.url));list.append(label);}
  sourcesStatus.textContent=result.channels.length+' nových odběrů · '+result.duplicates+' duplicit · '+result.errors.length+' neplatných řádků';
  for(const error of result.errors){const p=document.createElement('p');p.textContent='Řádek '+error.row+': '+error.error;list.append(p);}
  document.getElementById('sources-import-save').disabled=!result.channels.length;
 }catch(e){if(sequence===sourcesImportSequence){sourcesImport=null;document.getElementById('sources-import-save').disabled=true;sourcesStatus.textContent=e.message;}}
});
document.getElementById('sources-import-items').addEventListener('change',()=>{sourcesPending=null;});
document.getElementById('sources-import-save').addEventListener('click',async()=>{
 const selected=new Set([...document.querySelectorAll('#sources-import-items input:checked')].map(e=>e.value));
 const channels=sourcesImport?.channels.filter(c=>selected.has(c.id))||[];
 if(!channels.length){sourcesStatus.textContent='Vyberte alespoň jeden odběr.';return;}
 await saveSources(channels);
});
function refreshDueSources(){
 if(!document.hidden&&!document.getElementById('sources-view').hidden&&!sourcesBusy&&!sourcesSaving&&!sourcesDirty&&sourcesEditor.hidden&&sourcesImportReview.hidden&&sourcesView?.can_refresh)return loadSources(true,true);
}
setInterval(refreshDueSources,30000);
'''
