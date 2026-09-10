"""Static same-origin UI; project data arrives through authenticated reads."""
import sqlite3
import subprocess

from spikes.local_api import Handler
from spikes.projects import Projects
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation

HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projektový workspace</title><link rel="stylesheet" href="/app.css">
<body><aside><div class="brand">◈ &nbsp; WORKSPACE</div>
<div id="sidebar-projects"><h2>Projekty</h2><ul id="sidebar-project-list"></ul>
<p id="sidebar-project-status" role="status">Načítám projekty…</p></div>
<div id="sidebar-project-tools" hidden>
<div id="sidebar-tabs" role="tablist" aria-label="Obsah levého panelu">
<button id="todo-tab" role="tab" aria-controls="todo-widget" aria-selected="true">Úkoly</button>
<button id="artifacts-tab" role="tab" aria-controls="sidebar-artifacts" aria-selected="false" tabindex="-1">Podklady</button></div>
<div id="todo-widget" role="tabpanel" aria-labelledby="todo-tab" tabindex="0"><h2>Hlavní seznam úkolů</h2>
<p id="todo-status" role="status">Otevřete projekt.</p><div id="todo-title"></div>
<button id="create-main-todo" hidden>Vytvořit seznam úkolů</button>
<ul id="todo-tree" aria-label="Úkoly projektu"></ul><small id="todo-help" hidden>Úkoly upravíte v editoru.</small></div>
<div id="sidebar-artifacts" role="tabpanel" aria-labelledby="artifacts-tab" tabindex="0" hidden>
<h2>Podklady</h2><p id="sidebar-artifact-status" role="status"></p>
<ul id="sidebar-artifact-list" aria-label="Podklady projektu"></ul></div></div>
<div class="node-note">Na tomto počítači<br>Zkušební verze</div></aside>
<main><div id="project-home">
<header><span class="badge">Pracovní prostor</span><span>Vaše projekty, zdroje a rozhodnutí</span></header>
<div class="home-heading"><div class="eyebrow">VAŠE PRÁCE NA JEDNOM MÍSTĚ</div>
<h1>Projekty</h1><p>Vyberte projekt a pokračujte tam, kde jste skončili.</p></div>
<p id="project-status" role="status" aria-live="polite">Načítám projekty…</p>
<div id="project-cards" aria-label="Seznam projektů"></div>
<p class="home-help">Nový projekt vytvoříte tlačítkem v horní liště.</p>
<details class="diagnostics"><summary>Ověření spojení</summary>
<button id="increment">Ověřit spojení</button><output id="count">0</output><p id="status" role="status">Připraveno k ověření.</p></details>
</div>
<div id="project-view" hidden>
<header class="project-header"><div><span class="eyebrow">OTEVŘENÝ PROJEKT</span><h1 id="project-title"></h1></div>
<details><summary>Uložená verze</summary><code id="project-commit"></code></details></header>
<section id="workspace-panel" aria-label="Pracovní prostor">
<div id="main-tabs" role="tablist" aria-label="Hlavní panel">
<button id="preview-tab" role="tab" aria-controls="preview-panel" aria-selected="true">Náhled</button>
<button id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" tabindex="-1">Chat</button></div>
<div id="main-panel-content">
<div id="preview-panel" role="tabpanel" aria-labelledby="preview-tab">
<p id="preview-status" role="status">Vyberte podklad ze seznamu vlevo.</p>
<h2 id="preview-title"></h2><div id="preview-content"></div>
<div id="pdf-controls" hidden><label for="pdf-page">Stránka PDF (1–100)</label>
<input id="pdf-page" type="number" min="1" max="100" value="1"><button id="pdf-show">Zobrazit stránku</button></div>
<details id="preview-details" hidden><summary>Podrobnosti</summary><dl id="preview-metadata"></dl></details></div>
<div id="chat-panel" role="tabpanel" aria-labelledby="chat-tab" hidden><h2>Chat</h2>
<p>Asistent zatím není připojený a neodpovídá. Zadání zůstávají jen v tomto okně a po jeho zavření se ztratí.</p>
<div id="chat-messages" role="log" aria-label="Vaše zadání"></div></div></div>
<form id="chat-composer"><label for="chat-draft">Zadání úkolu</label>
<div class="prompt-row"><textarea id="chat-draft" rows="2" maxlength="16000" placeholder="Co chcete v projektu zpracovat?"></textarea>
<button id="chat-submit" type="submit" disabled>Přidat zadání</button></div>
<small>Jen v tomto okně · Enter přidá zadání, Shift+Enter nový řádek · Asistent zatím neodpovídá</small></form>
</section>
<button id="back-projects" class="back-button">← Zpět na seznam projektů</button>
</div></main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#f4f7fa;color:#162638;font:15px system-ui;display:flex;height:100vh;overflow:hidden}
aside{width:238px;flex-shrink:0;background:#142638;color:#c8d4df;padding:28px 20px;display:flex;flex-direction:column;overflow:auto}
.brand{font-weight:750;letter-spacing:2px;color:white;margin-bottom:32px}.node-note{font-size:11px;line-height:1.8;margin-top:auto;padding-top:28px;color:#9eb5c7}
main{flex:1;min-width:0;padding:26px 32px;overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:center;color:#627183;font-size:12px}
.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}
h1{font-size:32px;margin:12px 0}h2{font-size:21px}p{line-height:1.6;color:#627183}button,textarea,input{font:inherit}
button{border:0;border-radius:8px;background:#176b60;color:white;font-weight:600;padding:12px 18px;cursor:pointer}
button:hover{background:#12564d}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}
summary{cursor:pointer}code,li,dd,h1,h2,button{overflow-wrap:anywhere}small{font-size:11px;color:#627183}
.home-heading{margin-top:44px}.home-heading h1{font-size:38px}.home-help{font-size:13px;margin-top:24px}
#project-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;margin-top:24px}
.project-card{background:white;color:#162638;border:1px solid #dce5eb;border-radius:16px;padding:24px;text-align:left;min-height:190px;display:flex;flex-direction:column;gap:14px;box-shadow:0 5px 20px #18364808}
.project-card:hover{background:#fafffd;border-color:#4b9e8c;box-shadow:0 8px 24px #18364812}
.project-card .project-name{font-size:21px;line-height:1.4}.project-card .project-description{font-size:13px;color:#627183;font-weight:400;line-height:1.6}
.project-card .project-id{font-size:11px;color:#82909d;font-weight:400;margin-top:auto}.project-card .project-action{color:#176b60;font-size:13px}
.diagnostics{margin-top:32px;color:#627183;font-size:12px}.diagnostics button{margin:14px 12px 0 0}.diagnostics output{font-size:20px}
aside h2{font-size:16px;color:white}aside p{font-size:12px;color:#aabecf}aside small{color:#aabecf}
#sidebar-project-list,#sidebar-artifact-list,#todo-tree{list-style:none;padding:0;margin:14px 0}
#sidebar-project-list button,#sidebar-artifact-list button{display:block;text-align:left;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px}
#sidebar-project-list button:hover,#sidebar-artifact-list button:hover{background:#274154}
#sidebar-artifact-list button[aria-current="true"]{background:#274154;border-left:3px solid #79c9ac}
.sidebar-artifact-id{display:block;font-size:10px;color:#8faabc;margin:0 8px 10px}.sidebar-artifact-title{font-size:13px}
#sidebar-tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:18px}#sidebar-tabs button{font-size:12px;padding:8px 6px;border:1px solid #496072;background:transparent;color:#c8d4df}
#sidebar-tabs button[aria-selected="true"]{background:#274154;color:white;border-color:#79c9ac}
#todo-title{font-size:13px;font-weight:600;overflow-wrap:anywhere}#todo-tree ul{padding-left:14px;list-style:none;border-left:1px solid #496072;margin-left:4px}
#todo-tree li{font-size:13px;margin:8px 0}.todo-label{display:inline-flex;gap:7px;align-items:baseline;max-width:100%}.todo-label input{flex-shrink:0;accent-color:#79c9ac}.todo-text{overflow-wrap:anywhere;min-width:0}
.todo-done>.todo-label .todo-text,.todo-done>details>summary .todo-text{color:#a9c5b7;text-decoration:line-through}
#project-view{height:100%;display:flex;flex-direction:column;gap:16px}.project-header{flex-shrink:0}.project-header h1{font-size:25px;color:#162638;margin:6px 0}
.project-header details{max-width:280px}.project-header code{font-size:10px}
#workspace-panel{min-height:0;flex:1;display:flex;flex-direction:column;background:white;border:1px solid #dce3e9;border-radius:16px;overflow:hidden}
#main-tabs{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid #dce3e9;padding:16px;flex-shrink:0}
#main-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
#main-panel-content{overflow:auto;padding:0 22px 20px;flex:1;min-height:0}
#preview-status{font-size:12px}#preview-content img{max-width:100%;height:auto}#preview-content pre{white-space:pre-wrap;background:#eff3f6;padding:16px}
#preview-content p{white-space:pre-wrap;margin:6px 0}#preview-content h1{font-size:28px}#preview-title{font-size:20px}
#preview-metadata{overflow-wrap:anywhere}#preview-metadata dt{font-weight:600;margin-top:10px}#preview-metadata dd{margin:4px 0;white-space:pre-wrap}
#pdf-controls{margin:16px 0}#pdf-page{width:75px;margin:0 12px;padding:10px}
#chat-composer{flex-shrink:0;border-top:1px solid #dce3e9;background:#fafffd;padding:14px 20px}#chat-composer label{font-weight:600;font-size:12px}
.prompt-row{display:flex;gap:10px;margin:8px 0}.prompt-row textarea{resize:vertical;min-height:64px;max-height:150px;flex:1;min-width:0;border:1px solid #bfcdc9;border-radius:8px;padding:10px;background:white}
.prompt-row button{align-self:flex-end}.chat-message{padding:14px 18px;background:#edf5f2;border-radius:12px;margin:14px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.back-button{align-self:flex-start;background:transparent;color:#456276;padding:8px 0;font-size:13px;flex-shrink:0}.back-button:hover{background:transparent;color:#176b60}
@media(max-width:780px){aside{width:185px;padding:22px 12px}main{padding:18px}#project-cards{grid-template-columns:1fr}.prompt-row{flex-direction:column}.project-header details{max-width:140px}}
'''
JS = '''const button=document.querySelector('#increment');
button.addEventListener('click',async()=>{
 button.disabled=true;
 const status=document.querySelector('#status');
 status.textContent='Ověřuji spojení…';
 try {
  const response=await fetch('/v1/counter',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:'increment'}),signal:AbortSignal.timeout(4000)});
  if(!response.ok) throw new Error('request rejected');
  const result=await response.json();
  document.querySelector('#count').textContent=result.value;
  status.textContent='Spojení funguje.';
 }catch(error){status.textContent='Spojení se nezdařilo. Zavřete a znovu spusťte aplikaci.';}
 finally{button.disabled=false;}
});'''
JS += """
const projectCards=document.querySelector('#project-cards');
const sidebarProjects=document.querySelector('#sidebar-project-list');
const projectStatus=document.querySelector('#project-status');
const projectView=document.querySelector('#project-view');
const todoTree=document.querySelector('#todo-tree');
const todoStatus=document.querySelector('#todo-status');
const sidebarArtifacts=document.querySelector('#sidebar-artifact-list');
const sidebarArtifactStatus=document.querySelector('#sidebar-artifact-status');
const sidebarTabs=[...document.querySelectorAll('#sidebar-tabs [role="tab"]')];
function selectSidebarTab(selected){
 for(const tab of sidebarTabs){
  const active=tab===selected;
  tab.setAttribute('aria-selected',String(active));tab.tabIndex=active ? 0 : -1;
  document.getElementById(tab.getAttribute('aria-controls')).hidden=!active;
 }
}
for(const [index,tab] of sidebarTabs.entries()){
 tab.addEventListener('click',()=>selectSidebarTab(tab));
 tab.addEventListener('keydown',event=>{
  const next={ArrowRight:(index+1)%2,ArrowLeft:(index+1)%2,Home:0,End:1}[event.key];
  if(next===undefined) return;
  event.preventDefault();selectSidebarTab(sidebarTabs[next]);sidebarTabs[next].focus();
 });
}
function renderSidebarArtifacts(items){
 sidebarArtifacts.replaceChildren();
 sidebarArtifactStatus.textContent=items.length ? `Počet položek: ${items.length}` : 'Zatím tu nejsou žádné podklady.';
 for(const item of items){
  const row=document.createElement('li');
  const title=document.createElement('button');title.className='sidebar-artifact-title';title.textContent=item.title;
  title.dataset.id=item.id;title.setAttribute('aria-current','false');
  title.addEventListener('click',()=>openPreview(item.id));
  const id=document.createElement('small');id.className='sidebar-artifact-id';id.textContent=item.id;
  row.append(title,id);sidebarArtifacts.append(row);
 }
}
let viewRequest=0;
const createTodo=document.querySelector('#create-main-todo');
createTodo.addEventListener('click',()=>{
 if(activeProject && !createTodo.hidden)location.hash='create-main-todo';
});
function renderTodo(todo){
 createTodo.hidden=!!todo;
 document.querySelector('#todo-help').hidden=!todo;
 todoTree.replaceChildren();
 document.querySelector('#todo-title').textContent=todo?.title || '';
 if(!todo){todoStatus.textContent='Založte seznam a mějte úkoly projektu po ruce.';return;}
 if(todo.status!=='ready'){todoStatus.textContent='Hlavní seznam úkolů nelze zobrazit v tomto formátu nebo velikosti.';return;}
 todoStatus.textContent=todo.total ? `${todo.completed} z ${todo.total} hotovo` : 'Zatím bez úkolů.';
 if(todo.truncated) todoStatus.textContent+=' Zobrazeno prvních 1000 položek.';
 const lists=[todoTree];
 for(let i=0;i<todo.items.length;i++){
  const item=todo.items[i];lists.length=item.depth+1;
  const row=document.createElement('li');row.dataset.depth=item.depth;
  const label=document.createElement('span');label.className='todo-label';
  const check=document.createElement('input');check.type='checkbox';check.checked=item.checked;check.disabled=true;
  check.setAttribute('aria-label',item.checked ? 'Hotovo' : 'Nehotovo');
  const title=document.createElement('span');title.className='todo-text';title.textContent=item.title;
  label.append(check,title);
  if(item.checked) row.classList.add('todo-done');
  if(todo.items[i+1]?.depth>item.depth){
   const branch=document.createElement('details');branch.open=true;
   const summary=document.createElement('summary');summary.append(label);branch.append(summary);
   const children=document.createElement('ul');branch.append(children);row.append(branch);
   lists[item.depth+1]=children;
  }else{row.append(label);}
  lists[item.depth].append(row);
 }
}
function clearProject(){
 ++viewRequest;
 clearPreview();activeProject=null;document.querySelector('#chat-draft').value='';
 document.querySelector('#chat-submit').disabled=true;document.querySelector('#chat-messages').replaceChildren();
 document.querySelector('#project-home').hidden=false;
 document.querySelector('#sidebar-projects').hidden=false;document.querySelector('#sidebar-project-tools').hidden=true;
 selectMainTab(mainTabs[0]);
 sidebarArtifacts.replaceChildren();sidebarArtifactStatus.textContent='Otevřete projekt.';
 todoTree.replaceChildren();document.querySelector('#todo-title').textContent='';
 todoStatus.textContent='Otevřete projekt.';createTodo.hidden=true;document.querySelector('#todo-help').hidden=true;
 projectView.hidden=true;
 document.querySelector('#project-title').textContent='';
 document.querySelector('#project-commit').textContent='';
}
async function projectRequest(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});
 const result=await response.json();
 if(!response.ok) throw new Error(result.error || 'Požadavek byl odmítnut.');
 return result;
}
let catalogRequest=0;
async function openRegisteredProject(projectId){
 ++catalogRequest;
 clearProject();const request=viewRequest;
 projectStatus.textContent='Otevírám projekt…';
 try{
  const result=await projectRequest('/v1/projects/open',{project_id:projectId});
  if(request!==viewRequest)return;
  activeProject={id:projectId,head:result.commit_id};
  renderTodo(result.main_todo);renderSidebarArtifacts(result.artifacts);
  document.querySelector('#project-title').textContent=result.title;
  document.querySelector('#project-commit').textContent=result.commit_id;
  projectView.hidden=false;document.querySelector('#project-home').hidden=true;
  document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
  selectSidebarTab(sidebarTabs[1]);
  document.querySelector('#preview-status').textContent=result.artifacts.length ?
   'Vyberte podklad ze seznamu vlevo.' : 'Zatím tu nejsou žádné podklady. První dokument vytvoříte tlačítkem Dokumenty v horní liště.';
 }catch(error){if(request===viewRequest)projectStatus.textContent=error.message;}
}
function renderProjectCatalog(items){
 projectCards.replaceChildren();sidebarProjects.replaceChildren();
 for(const item of items){
  const card=document.createElement('button');card.type='button';card.className='project-card';card.dataset.id=item.id;
  const name=document.createElement('span');name.className='project-name';name.textContent=item.title;
  const description=document.createElement('span');description.className='project-description';
  description.textContent=item.available ? (item.description.slice(0,240) || 'Prostor pro zdroje, poznámky a rozhodnutí.') : 'Projekt nelze načíst. Ověřte jeho umístění a konfiguraci.';
  const id=document.createElement('span');id.className='project-id';id.textContent=item.id;
  const action=document.createElement('span');action.className='project-action';action.textContent=item.available?'Otevřít projekt →':'Zkusit otevřít →';
  card.append(name,description,id,action);card.addEventListener('click',()=>openRegisteredProject(item.id));projectCards.append(card);
  const row=document.createElement('li');const compact=document.createElement('button');compact.type='button';compact.dataset.id=item.id;
  compact.textContent=item.title;compact.title=item.id;compact.addEventListener('click',()=>openRegisteredProject(item.id));row.append(compact);sidebarProjects.append(row);
 }
 document.querySelector('#sidebar-project-status').textContent=items.length ? `Počet projektů: ${items.length}` : 'Zatím bez projektů.';
}
async function loadProjects(selectedId=null){
 const request=++catalogRequest;
 clearProject();projectCards.replaceChildren();sidebarProjects.replaceChildren();
 projectStatus.textContent='Načítám projekty…';document.querySelector('#sidebar-project-status').textContent='Načítám projekty…';
 try{
  const result=await projectRequest('/v1/projects',{details:true});
  if(request!==catalogRequest)return;
  renderProjectCatalog(result.projects);
  projectStatus.textContent=result.projects.length ? 'Vyberte projekt.' : 'Zatím nemáte žádný projekt.';
  if(selectedId && result.projects.some(p=>p.id===selectedId))await openRegisteredProject(selectedId);
 }catch(error){if(request===catalogRequest){projectStatus.textContent=error.message;document.querySelector('#sidebar-project-status').textContent='Seznam není dostupný.';}}
}
document.querySelector('#back-projects').addEventListener('click',()=>loadProjects());

"""

JS += """
let activeProject=null, selectedArtifact=null, previewRequest=0;
const previewStatus=document.querySelector('#preview-status');
const previewContent=document.querySelector('#preview-content');
const mainTabs=[...document.querySelectorAll('#main-tabs [role="tab"]')];
function selectMainTab(tab){
 for(const item of mainTabs){
  const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;
  document.getElementById(item.getAttribute('aria-controls')).hidden=!active;
 }
}
for(const [index,tab] of mainTabs.entries()){
 tab.addEventListener('click',()=>selectMainTab(tab));
 tab.addEventListener('keydown',event=>{
  const next={ArrowRight:1-index,ArrowLeft:1-index,Home:0,End:1}[event.key];
  if(next===undefined)return;
  event.preventDefault();selectMainTab(mainTabs[next]);mainTabs[next].focus();
 });
}
function clearPreview(){
 ++previewRequest;selectedArtifact=null;previewContent.replaceChildren();
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current','false');
 document.querySelector('#preview-title').textContent='';
 document.querySelector('#preview-metadata').replaceChildren();
 document.querySelector('#preview-details').hidden=true;
 document.querySelector('#pdf-controls').hidden=true;
 previewStatus.textContent='Vyberte podklad ze seznamu.';
}
function renderMarkdown(text){
 // Deliberately small Markdown subset; all source text uses textContent, never HTML.
 let fence=null,code=null;
 for(const line of text.split('\\n')){
  const marker=line.match(/^\\s*(`{3,}|~{3,})(.*)$/);
  if(marker && (!fence || (marker[1][0]===fence[0] && marker[1].length>=fence.length && !marker[2].trim()))){
   if(fence){fence=null;code=null;}else{fence=marker[1];code=document.createElement('pre');previewContent.append(code);}
   continue;
  }
  if(fence){code.textContent+=line+'\\n';continue;}
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const element=document.createElement(heading?'h'+heading[1].length:'p');
  element.textContent=heading?heading[2]:line;previewContent.append(element);
 }
}
async function openPreview(id,page=1){
 if(!activeProject)return;
 const project=activeProject;
 clearPreview();selectedArtifact=id;
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current',String(button.dataset.id===id));
 const request=previewRequest;
 selectMainTab(mainTabs[0]);previewStatus.textContent='Načítám náhled…';
 try{
  const result=await projectRequest('/v1/artifacts/preview',{
   project_id:project.id,artifact_id:id,expected_head:project.head,page});
  if(request!==previewRequest || activeProject!==project)return;
  document.querySelector('#preview-title').textContent=result.metadata.title;
  const metadata=document.querySelector('#preview-metadata');
  for(const [key,value] of Object.entries(result.metadata)){
   const term=document.createElement('dt');term.textContent=({title:'Název',description:'Popis',tags:'Štítky',id:'Identifikátor',kind:'Typ',file:'Soubor',created_at:'Vytvořeno',author_id:'Autor',privacy:'Soukromí',provenance:'Původ',schema_version:'Verze formátu',relations:'Vztahy',source_url:'Odkaz na zdroj'})[key] || key;
   const detail=document.createElement('dd');detail.textContent=Array.isArray(value) && value.every(item=>typeof item==='string') ? value.join(', ') : typeof value==='string'?value:JSON.stringify(value);
   const labels={privacy:{public:'Veřejné',project:'V rámci projektu',confidential:'Důvěrné','local-only':'Jen na tomto počítači'},
    provenance:{user:'Vytvořeno uživatelem',external:'Převzato ze zdroje','llm-generated':'Vytvořeno AI','llm-transformed':'Upraveno AI',snapshot:'Snímek stavu'},
    kind:{document:'Dokument',source:'Zdroj'}};
   if(labels[key] && Object.hasOwn(labels[key],value))detail.textContent=labels[key][value];
   metadata.append(term,detail);
  }
  document.querySelector('#preview-details').hidden=false;
  if(result.format==='markdown')renderMarkdown(result.text);
  else if(result.format==='image' || result.format==='pdf'){
   const image=document.createElement('img');image.alt=result.metadata.title;
   image.addEventListener('error',()=>{if(request===previewRequest)previewStatus.textContent='Obrázek se nepodařilo zobrazit.';});
   image.src=result.image;previewContent.append(image);
  }
  // Keep page selection available after an invalid/missing PDF page.
  const isPdf=result.format==='pdf' || result.metadata.file?.toLowerCase().endsWith('.pdf');
  document.querySelector('#pdf-controls').hidden=!isPdf;
  document.querySelector('#pdf-page').value=page;
  previewStatus.textContent=result.message || (result.format==='pdf'?'Stránka '+page+' · uložená verze':'Uložená verze · pouze pro čtení');
 }catch(error){if(request===previewRequest){previewStatus.textContent=error.message;}}
}
document.querySelector('#pdf-show').addEventListener('click',()=>{
 const input=document.querySelector('#pdf-page');
 if(input.reportValidity() && selectedArtifact)openPreview(selectedArtifact,Number(input.value));
});
const draft=document.querySelector('#chat-draft');
draft.addEventListener('input',()=>{
 document.querySelector('#chat-submit').disabled=!activeProject || !draft.value.trim();
 if(activeProject && draft.value.trim())selectMainTab(mainTabs[1]);
});
document.querySelector('#chat-composer').addEventListener('submit',event=>{
 event.preventDefault();if(!activeProject || !draft.value.trim())return;
 selectMainTab(mainTabs[1]);
 const message=document.createElement('div');message.className='chat-message';message.textContent=draft.value.trim();
 document.querySelector('#chat-messages').append(message);
 draft.value='';document.querySelector('#chat-submit').disabled=true;draft.focus();
 document.querySelector('#main-panel-content').scrollTop=document.querySelector('#main-panel-content').scrollHeight;
});
draft.addEventListener('keydown',event=>{
 if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();document.querySelector('#chat-composer').requestSubmit();}
});
loadProjects();
"""
ASSETS = {'/': ('text/html; charset=utf-8', HTML), '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS)}


class DesktopHandler(Handler):
    post_paths = Handler.post_paths | {'/v1/projects', '/v1/projects/open', '/v1/artifacts/preview'}

    def dispatch(self, request):
        if self.path == '/v1/counter':
            return super().dispatch(request)
        projects = self.server.projects or Projects()
        try:
            if self.path == '/v1/projects' and request == {}:
                return self.reply(200, {'projects': projects.list()})
            if self.path == '/v1/projects' and isinstance(request, dict) and set(request) == {'details'} and request['details'] is True:
                return self.reply(200, {'projects': projects.catalog()})
            if (self.path == '/v1/projects/open' and isinstance(request, dict)
                    and set(request) == {'project_id'} and isinstance(request['project_id'], str)):
                return self.reply(200, projects.open(request['project_id']))
            if (self.path == '/v1/artifacts/preview' and isinstance(request, dict)
                    and set(request) == {'project_id', 'artifact_id', 'expected_head', 'page'}):
                return self.reply(200, projects.preview(**request))
            return self.send_error(400)
        except PendingOperation:
            return self.reply(409, {'error': 'Projekt má nedokončenou operaci. Nejprve proveďte obnovu.'})
        except StaleIndex:
            return self.reply(409, {'error': 'Projekt se během čtení změnil. Zkuste jej znovu otevřít.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            # Do not forward paths, Git stderr or configuration payloads to the renderer.
            return self.reply(422, {'error': 'Projekt nelze otevřít: ověřte konfiguraci, registraci, '
                                   'práva lokálního stavu a platnost Git dat/indexu.'})

    def do_GET(self):
        if self.single('Host') != self.server.authority:
            return self.send_error(403)
        if self.path not in ASSETS:
            return self.send_error(404)
        kind, content = ASSETS[self.path]
        data = content.encode()
        self.close_connection = True
        self.send_response_only(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
