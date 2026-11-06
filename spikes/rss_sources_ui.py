# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared Sources page with channel tabs and aggregated entries."""
HTML = '''<div id="sources-view" hidden>
<header class="sources-header"><div><h1>Zdroje</h1><p>Nové články z odebíraných kanálů.</p></div>
<button id="sources-refresh" type="button">Načíst kanály</button></header>
<div id="sources-channel-tabs" role="tablist" aria-label="Kanály zdrojů"></div>
<p id="sources-status" role="status" aria-live="polite">Kanály zatím nebyly načteny.</p>
<div id="sources-feed" role="tabpanel" aria-label="Články z vybraných kanálů" tabindex="0"></div>
</div>'''
CSS = '''
#sources-view{max-width:1100px;margin:0 auto;padding:clamp(12px,3vw,32px);width:100%;box-sizing:border-box;overflow:auto}
.sources-header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.sources-header h1{margin:0}.sources-header p{color:#526678}
#sources-channel-tabs{display:flex;gap:8px;overflow:auto;padding:8px 0}
#sources-channel-tabs button{white-space:nowrap;background:#eaf0f4;color:#23394b;border:1px solid #c7d4dc}
#sources-channel-tabs button[aria-selected=true]{background:#176b60;color:white;border-color:#176b60}
.source-entry{padding:18px 0;border-bottom:1px solid #dce5ea}.source-entry h2{font-size:19px;line-height:1.4;margin:6px 0}
.source-entry a{color:#176b60;text-decoration:none}.source-entry a:hover{text-decoration:underline}
.source-entry-meta{font-size:13px;color:#526678}.source-entry-meta time{margin-left:12px}
#sources-status{white-space:pre-line;color:#526678;line-height:1.6}
'''
JS = r'''
let sourcesView=null,sourcesChannel='all',sourcesBusy=false,sourcesSequence=0;
const sourcesTabs=document.getElementById('sources-channel-tabs'),sourcesFeed=document.getElementById('sources-feed');
const sourcesStatus=document.getElementById('sources-status'),sourcesRefresh=document.getElementById('sources-refresh');
function renderSources(){
 if(!sourcesView)return;
 const tabs=[{id:'all',name:'Všechny'},...sourcesView.channels];sourcesTabs.replaceChildren();
 for(const channel of tabs){
  const b=document.createElement('button');b.type='button';b.setAttribute('role','tab');b.id='source-channel-'+channel.id;
  b.textContent=channel.name;b.setAttribute('aria-controls','sources-feed');b.setAttribute('aria-selected',String(channel.id===sourcesChannel));b.tabIndex=channel.id===sourcesChannel?0:-1;
  b.addEventListener('click',()=>{sourcesChannel=channel.id;renderSources();document.getElementById(b.id).focus();});sourcesTabs.append(b);
 }
 sourcesFeed.setAttribute('aria-labelledby','source-channel-'+sourcesChannel);sourcesFeed.replaceChildren();
 const entries=sourcesView.entries.filter(e=>sourcesChannel==='all'||e.channel_id===sourcesChannel);
 const channels=sourcesView.channels.filter(c=>sourcesChannel==='all'||c.id===sourcesChannel);
 sourcesStatus.textContent=entries.length+' článků\n'+channels.map(c=>{
  const checked=c.checked_at?new Date(c.checked_at).toLocaleString('cs-CZ'):'dosud nenačteno';
  if(c.error)return c.name+': '+(c.state==='unknown'?'Neznámý výsledek':'Chyba načítání')+' — '+c.error+'. Poslední úspěšné načtení: '+checked+'.';
  return c.name+': '+(c.state==='loading'?'Načítá se…':checked);
 }).join('\n');
 if(!entries.length){const p=document.createElement('p');p.textContent=channels.some(c=>c.state==='unloaded')?'Pro načtení článků použijte tlačítko Načíst kanály.':'Žádné načtené články.';sourcesFeed.append(p);}
 for(const e of entries){
  const article=document.createElement('article');article.className='source-entry';
  const meta=document.createElement('div');meta.className='source-entry-meta';meta.textContent=e.channel_name;
  const date=document.createElement('time');if(e.published_at){date.dateTime=e.published_at;date.textContent=new Date(e.published_at).toLocaleString('cs-CZ');}else date.textContent='Datum publikace neuvedeno';meta.append(date);
  const heading=document.createElement('h2');let url=null;try{url=new URL(e.url);}catch(error){}
  if(url&&['http:','https:'].includes(url.protocol)&&!url.username&&!url.password){const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=e.title||'Článek bez titulku';heading.append(a);}else heading.textContent=e.title||'Článek bez titulku';
  article.append(meta,heading);if(e.author){const p=document.createElement('p');p.textContent=e.author;article.append(p);}
  if(e.revisions>1){const small=document.createElement('small');small.textContent='Aktualizovaná položka';article.append(small);}sourcesFeed.append(article);
 }
 sourcesRefresh.disabled=sourcesBusy||!sourcesView.can_refresh;
 sourcesRefresh.textContent=sourcesBusy?'Načítám…':sourcesChannel==='all'?'Načíst kanály':'Načíst kanál';
}
async function loadSources(refresh=false){
 const sequence=++sourcesSequence;
 if(refresh){sourcesBusy=true;sourcesRefresh.disabled=true;sourcesRefresh.textContent='Načítám…';}
 try{const result=await projectRequest('/v1/rss-sources/'+(refresh?'refresh':'view'),refresh?{channel_id:sourcesChannel}:{},60000);
  if(sequence!==sourcesSequence)return;sourcesView=result;renderSources();
 }catch(error){if(sequence===sourcesSequence)sourcesStatus.textContent=error.message;}
 finally{if(sequence===sourcesSequence){sourcesBusy=false;sourcesRefresh.disabled=!sourcesView?.can_refresh;sourcesRefresh.textContent=sourcesChannel==='all'?'Načíst kanály':'Načíst kanál';}}
}
sourcesRefresh.addEventListener('click',()=>loadSources(true));
sourcesTabs.addEventListener('keydown',event=>{
 if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 const tabs=[...sourcesTabs.querySelectorAll('[role=tab]')],i=tabs.indexOf(document.activeElement);if(i<0)return;
 event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].click();
});
'''
