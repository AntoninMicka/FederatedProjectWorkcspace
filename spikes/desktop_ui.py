# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Static same-origin UI; project data arrives through authenticated reads."""
import sqlite3
import subprocess

from spikes.local_api import Handler
from spikes.ollama_backend import OllamaResponseError, UnknownRun
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
<button id="open-settings" class="global-nav" type="button">Nastavení</button>
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
<div id="settings-view" hidden>
<header><span class="badge">Nastavení uzlu</span><span>Platí pro tento počítač</span></header>
<div class="settings-heading"><div class="eyebrow">LOKÁLNÍ KONFIGURACE</div>
<h1>Nastavení</h1><p>Tato nastavení se neukládají do projektu ani nesynchronizují.</p></div>
<div id="settings-tabs" role="tablist" aria-label="Sekce nastavení">
<button id="settings-backend-tab" type="button" role="tab" aria-selected="true" aria-controls="settings-backend-panel">AI backend</button>
<button id="settings-users-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-users-panel" tabindex="-1" hidden>Uživatelé</button>
<button id="settings-federation-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-federation" tabindex="-1" hidden>Federace</button></div>
<section id="settings-backend-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-backend-tab">
<h2 id="settings-backend-title">Lokální AI backend</h2>
<p id="settings-backend-status" role="status" aria-live="polite">Načítám stav lokálního backendu…</p>
<form id="chat-backend-form"><label>Hranice <select name="boundary"><option value="same-node">Stejný počítač</option><option value="private-network">Privátní síť</option></select></label>
<label>Endpoint <input name="endpoint" value="http://127.0.0.1:11434" required></label>
<label>Model <input name="model" placeholder="gemma3" required></label>
<label>ID cíle <input name="target_id" value="local-process" required></label>
<label>SHA-256 certifikátu pro LAN <input name="tls_cert_sha256" pattern="[0-9a-f]{64}"></label>
<button type="submit">Uložit backend</button></form>
<small>Privátní síť vyžaduje číselnou HTTPS adresu a připnutý certifikát. Tajné klíče se zde nezobrazují.</small>
<hr><h2>Externí textový backend</h2>
<p id="settings-external-status" role="status" aria-live="polite">Načítám stav externího backendu…</p>
<form id="external-backend-form">
<label>Provider <input value="OpenAI Responses API" disabled></label>
<label>Endpoint <input name="endpoint" value="https://api.openai.com/v1/responses" readonly></label>
<label>Modelový snapshot <input name="model" placeholder="gpt-5-YYYY-MM-DD" required></label>
<label>Maximum výstupních tokenů <input name="max_output_tokens" type="number" min="1" max="128000" value="4096" required></label>
<label>Timeout v sekundách <input name="timeout_seconds" type="number" min="1" max="180" value="180" required></label>
<label>API klíč <input name="secret" type="password" minlength="20" maxlength="4096" autocomplete="new-password" required></label>
<p><a class="provider-link" href="https://platform.openai.com/api-keys">Vytvořit nebo spravovat klíč u OpenAI ↗</a></p>
<button type="submit">Uložit externí backend</button></form>
<small>Správa klíče se otevře v systémovém prohlížeči; workspace nevidí přihlášení ani vytvořený klíč. Klíč sem potom vložíte jednou, po odeslání se vymaže z formuláře a server jej nikdy nevrací. Externí volání bude dostupné až po samostatném náhledu a potvrzení.</small>
</section>
<div id="administration-host"></div>
<button id="settings-back" class="back-button" type="button">← Zpět</button>
</div>
<div id="project-view" hidden>
<header class="project-header"><div><span class="eyebrow">OTEVŘENÝ PROJEKT</span><h1 id="project-title"></h1></div>
<details><summary>Uložená verze</summary><code id="project-commit"></code></details></header>
<section id="workspace-panel" aria-label="Pracovní prostor">
<div id="main-tabs" role="tablist" aria-label="Hlavní panel">
<button id="preview-tab" role="tab" aria-controls="preview-panel" aria-selected="true">Náhled</button>
<button id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" tabindex="-1">Chat</button>
<button id="summary-tab" role="tab" aria-controls="summary-panel" aria-selected="false" tabindex="-1">Souhrn</button>
<button id="extraction-tab" role="tab" aria-controls="extraction-panel" aria-selected="false" tabindex="-1">Extrakce</button>
<button id="metadata-tab" role="tab" aria-controls="metadata-panel" aria-selected="false" tabindex="-1">Metadata</button></div>
<div id="main-panel-content">
<div id="preview-panel" role="tabpanel" aria-labelledby="preview-tab">
<p id="preview-status" role="status">Vyberte podklad ze seznamu vlevo.</p>
<h2 id="preview-title"></h2><div id="preview-content"></div>
<div id="pdf-controls" hidden><label for="pdf-page">Stránka PDF (1–100)</label>
<input id="pdf-page" type="number" min="1" max="100" value="1"><button id="pdf-show">Zobrazit stránku</button></div>
<details id="preview-details" hidden><summary>Podrobnosti</summary><dl id="preview-metadata"></dl></details></div>
<div id="chat-panel" role="tabpanel" aria-labelledby="chat-tab" hidden><h2>Chat</h2>
<p id="chat-backend-status" role="status">Načítám stav lokálního backendu…</p>
<button id="chat-open-settings" class="secondary-button" type="button">Otevřít nastavení backendu</button>
<button id="chat-new-thread" type="button">Nové vlákno</button>
<span id="chat-record-actions" hidden><button id="chat-save-snapshot" type="button">Uložit otisk</button>
<button id="chat-save-output" type="button">Uložit poslední odpověď</button></span>
<div id="chat-messages" role="log" aria-label="Vaše zadání"></div></div>
<div id="summary-panel" role="tabpanel" aria-labelledby="summary-tab" hidden><h2>Lokální souhrn</h2>
<p>Vyberte projektové podklady, nebo zprávy aktuálního chatu. Náhled se do projektu uloží až po potvrzení.</p>
<label>Zdroj <select id="summary-kind"><option value="artifacts">Vybrané podklady</option>
<option value="messages">Aktuální chat</option></select></label>
<fieldset id="summary-artifacts"><legend>Podklady</legend><div id="summary-artifact-list"></div></fieldset>
<label for="summary-focus">Zaměření (volitelné)</label>
<textarea id="summary-focus" rows="2" maxlength="16384"></textarea>
<label for="summary-focus-privacy">Soukromí zaměření</label><select id="summary-focus-privacy">
<option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option>
<option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<button id="summary-generate" type="button">Vytvořit náhled</button>
<p id="summary-status" role="status" aria-live="polite"></p>
<div id="summary-preview" aria-label="Náhled souhrnu"></div>
<div id="summary-publish-controls" hidden><label for="summary-title">Název dokumentu</label>
<input id="summary-title" maxlength="200" value="Souhrn projektu">
<button id="summary-publish" type="button">Uložit do projektu</button></div></div>
<div id="extraction-panel" role="tabpanel" aria-labelledby="extraction-tab" hidden><h2>Strukturovaná extrakce</h2>
<p>Vyberte podklady a uzavřené schéma. Náhled se uloží až po potvrzení.</p>
<label>Schéma <select id="extraction-schema"><option value="facts|facts-v1">Fakta</option>
<option value="action-items|action-items-v1">Akční položky</option></select></label>
<label>Zdroj <select id="extraction-kind"><option value="artifacts">Vybrané podklady</option>
<option value="messages">Aktuální chat</option></select></label>
<fieldset id="extraction-artifacts"><legend>Podklady</legend><div id="extraction-artifact-list"></div></fieldset>
<label for="extraction-focus">Zaměření (volitelné)</label><textarea id="extraction-focus" rows="2" maxlength="16384"></textarea>
<label for="extraction-focus-privacy">Soukromí zaměření</label><select id="extraction-focus-privacy">
<option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option>
<option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<button id="extraction-generate" type="button">Vytvořit náhled</button>
<p id="extraction-status" role="status" aria-live="polite"></p>
<pre id="extraction-preview" aria-label="Náhled extrakce"></pre>
<div id="extraction-publish-controls" hidden><label for="extraction-title">Název zdroje</label>
<input id="extraction-title" maxlength="200" value="Strukturovaná extrakce">
<button id="extraction-publish" type="button">Uložit do projektu</button></div></div>
<div id="metadata-panel" role="tabpanel" aria-labelledby="metadata-tab" hidden><h2>Návrh popisu a štítků</h2>
<p>Vyberte jeden artefakt. Návrh projekt nezmění, dokud nepotvrdíte konkrétní pole.</p>
<label for="metadata-artifact">Artefakt</label><select id="metadata-artifact"></select>
<button id="metadata-generate" type="button">Navrhnout metadata</button>
<p id="metadata-status" role="status" aria-live="polite"></p>
<div id="metadata-diff" hidden><section><h3>Popis</h3><p id="metadata-description-before"></p>
<label><input id="metadata-apply-description" type="checkbox"><span id="metadata-description-after"></span></label></section>
<fieldset><legend>Navržené nové štítky</legend><div id="metadata-tag-list"></div></fieldset>
<button id="metadata-publish" type="button">Použít vybrané změny</button></div></div></div>
<form id="chat-composer"><label for="chat-draft">Zadání úkolu</label>
<label for="chat-privacy">Soukromí</label><select id="chat-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<div class="prompt-row"><textarea id="chat-draft" rows="2" maxlength="16000" placeholder="Co chcete v projektu zpracovat?"></textarea>
<button id="chat-submit" type="submit" disabled>Odeslat</button></div>
<p id="chat-operation-status" role="status" aria-live="polite"></p>
<small>Enter odešle, Shift+Enter vloží nový řádek · historie zůstává lokálně na tomto uzlu</small></form>
</section>
<button id="back-projects" class="back-button">← Zpět na seznam projektů</button>
</div></main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#f4f7fa;color:#162638;font:15px system-ui;display:flex;height:100vh;overflow:hidden}
aside{width:238px;flex-shrink:0;background:#142638;color:#c8d4df;padding:28px 20px;display:flex;flex-direction:column;overflow:auto}
.brand{font-weight:750;letter-spacing:2px;color:white;margin-bottom:32px}.global-nav{margin-top:auto;background:#176b60;text-align:left}.node-note{font-size:11px;line-height:1.8;padding-top:18px;color:#9eb5c7}
main{flex:1;min-width:0;padding:26px 32px;overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:center;color:#627183;font-size:12px}
.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}
h1{font-size:32px;margin:12px 0}h2{font-size:21px}p{line-height:1.6;color:#627183}button,textarea,input{font:inherit}
button{border:0;border-radius:8px;background:#176b60;color:white;font-weight:600;padding:12px 18px;cursor:pointer}
button:hover{background:#12564d}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}
summary{cursor:pointer}code,li,dd,h1,h2,button{overflow-wrap:anywhere}small{font-size:11px;color:#627183}
.home-heading,.settings-heading{margin-top:44px}.home-heading h1{font-size:38px}.home-help{font-size:13px;margin-top:24px}
.settings-card{max-width:720px;background:white;border:1px solid #dce3e9;border-radius:16px;padding:22px 26px;margin:24px 0}.settings-card label{display:block;margin:12px 0}.settings-card input,.settings-card select{padding:9px;max-width:100%}.settings-card input{width:100%}.settings-card small{display:block;margin-top:16px}
.provider-link{color:#176b60;font-weight:600}
#settings-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 8px}#settings-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
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
.chat-message.assistant{background:#eef1fa}.chat-message small{display:block;margin-top:6px}.secondary-button{background:#e8eef2;color:#304657;margin:0 8px 12px 0}.secondary-button:hover{background:#dce6eb}#chat-privacy{padding:7px;max-width:100%}#chat-operation-status{font-size:12px;min-height:20px;margin:2px 0;color:#315f58}#chat-record-actions button{padding:8px 12px;margin-left:6px;font-size:12px}
#summary-panel label,#extraction-panel label{display:block;margin:10px 0 5px}#summary-panel textarea,#summary-panel input,#summary-panel select,#extraction-panel textarea,#extraction-panel input,#extraction-panel select{padding:9px;max-width:100%}#summary-focus,#extraction-focus{width:100%;resize:vertical}#summary-artifacts,#extraction-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#summary-artifact-list label,#extraction-artifact-list label{font-weight:400}#summary-status,#extraction-status{font-size:12px;min-height:20px;color:#315f58}#summary-preview,#extraction-preview{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#summary-preview:empty,#extraction-preview:empty{display:none}#summary-preview p{white-space:pre-wrap;margin:6px 0}#extraction-preview{white-space:pre-wrap;overflow:auto}#summary-publish-controls,#extraction-publish-controls{border-top:1px solid #dce3e9;padding-top:12px}
#metadata-panel label{display:block;margin:10px 0 5px}#metadata-panel select{padding:9px;max-width:100%;margin-bottom:10px}#metadata-status{font-size:12px;min-height:20px;color:#315f58}#metadata-diff{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#metadata-diff p,#metadata-diff span{white-space:pre-wrap}#metadata-diff fieldset{margin:14px 0;border:1px solid #dce3e9}#metadata-tag-list label{font-weight:400}
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
const settingsView=document.querySelector('#settings-view');
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
let currentArtifacts=[];
function renderSidebarArtifacts(items){
 currentArtifacts=items;
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
 renderSummarySources();
 renderExtractionSources();
 renderMetadataSources();
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
 currentArtifacts=[];clearSummary();clearExtraction();clearMetadata();
 activeThread=null;pendingChatRequest=null;
 document.querySelector('#chat-submit').disabled=true;document.querySelector('#chat-messages').replaceChildren();
 document.querySelector('#chat-backend-status').textContent='Otevřete projekt.';
 document.querySelector('#chat-operation-status').textContent='';document.querySelector('#chat-record-actions').hidden=true;
 document.querySelector('#project-home').hidden=false;
 settingsView.hidden=true;
 document.querySelector('#sidebar-projects').hidden=false;document.querySelector('#sidebar-project-tools').hidden=true;
 selectMainTab(mainTabs[0]);
 sidebarArtifacts.replaceChildren();sidebarArtifactStatus.textContent='Otevřete projekt.';
 todoTree.replaceChildren();document.querySelector('#todo-title').textContent='';
 todoStatus.textContent='Otevřete projekt.';createTodo.hidden=true;document.querySelector('#todo-help').hidden=true;
 projectView.hidden=true;
 document.querySelector('#project-title').textContent='';
 document.querySelector('#project-commit').textContent='';
}
async function projectRequest(path,body,timeout=60000){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});
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
  await loadChat();
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
  const next={ArrowRight:(index+1)%mainTabs.length,
   ArrowLeft:(index+mainTabs.length-1)%mainTabs.length,Home:0,End:mainTabs.length-1}[event.key];
  if(next===undefined)return;
  event.preventDefault();selectMainTab(mainTabs[next]);mainTabs[next].focus();
 });
}
let settingsReturn=null;
const settingsTabs=[...document.querySelectorAll('#settings-tabs [role="tab"]')];
function selectSettingsTab(selected){
 for(const tab of settingsTabs){
  const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
  const panel=document.getElementById(tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;
 }
 const administration=document.getElementById('administration');if(administration)administration.hidden=selected.id==='settings-backend-tab';
}
for(const [index,tab] of settingsTabs.entries()){
 tab.addEventListener('click',()=>selectSettingsTab(tab));
 tab.addEventListener('keydown',event=>{
  const visible=settingsTabs.filter(item=>!item.hidden);const current=visible.indexOf(tab);
  const next={ArrowRight:(current+1)%visible.length,ArrowLeft:(current+visible.length-1)%visible.length,Home:0,End:visible.length-1}[event.key];
  if(next===undefined)return;event.preventDefault();visible[next].click();visible[next].focus();
 });
}
async function openSettings(){
 const activeTab=mainTabs.find(tab=>tab.getAttribute('aria-selected')==='true');
 settingsReturn={project:!!activeProject,tabId:activeTab?.id || 'preview-tab'};
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=true;
 selectSettingsTab(document.querySelector('#settings-backend-tab'));
 document.querySelector('#settings-backend-status').textContent='Načítám stav lokálního backendu…';
 await loadBackendBinding();
}
async function closeSettings(){
 const destination=settingsReturn;settingsReturn=null;settingsView.hidden=true;
 document.dispatchEvent(new Event('settingsclosed'));
 if(destination?.project && activeProject){
  projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;
  const tab=document.getElementById(destination.tabId);if(tab)selectMainTab(tab);
  await loadBackendBinding();
 }else{
  document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;
 }
}
document.querySelector('#open-settings').addEventListener('click',openSettings);
document.querySelector('#chat-open-settings').addEventListener('click',openSettings);
document.querySelector('#settings-back').addEventListener('click',closeSettings);
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
   const entries=key==='import' ? [
    ['imported_at',value.imported_at],['imported_by',value.imported_by],['content_sha256',value.content_sha256],
    ['source_author',value.source_author],['source_created_at',value.source_created_at],
    ['source_revision',value.source_revision],['importer_name',value.importer?.name],
    ['importer_version',value.importer?.version]
   ].filter(([,item])=>item!==undefined) : [[key,value]];
   for(const [entryKey,entryValue] of entries){
    const term=document.createElement('dt');term.textContent=({title:'Název',description:'Popis',tags:'Štítky',id:'Identifikátor',kind:'Typ',file:'Soubor',created_at:'Vytvořeno v projektu',author_id:'Autor',privacy:'Soukromí',provenance:'Původ',schema_version:'Verze formátu',relations:'Vztahy',source_url:'Odkaz na zdroj',imported_at:'Importováno do projektu',imported_by:'Importoval',content_sha256:'SHA-256 původních bajtů',source_author:'Autor zdroje',source_created_at:'Doložený čas vzniku zdroje',source_revision:'Revize zdroje',importer_name:'Importér',importer_version:'Verze importéru'})[entryKey] || entryKey;
    const detail=document.createElement('dd');detail.textContent=Array.isArray(entryValue) && entryValue.every(item=>typeof item==='string') ? entryValue.join(', ') : typeof entryValue==='string'?entryValue:JSON.stringify(entryValue);
    const labels={privacy:{public:'Veřejné',project:'V rámci projektu',confidential:'Důvěrné','local-only':'Jen na tomto počítači'},
     provenance:{user:'Vytvořeno uživatelem',external:'Převzato ze zdroje','llm-generated':'Vytvořeno AI','llm-transformed':'Upraveno AI',snapshot:'Snímek stavu'},
     kind:{document:'Dokument',source:'Zdroj'}};
    if(labels[entryKey] && Object.hasOwn(labels[entryKey],entryValue))detail.textContent=labels[entryKey][entryValue];
    metadata.append(term,detail);
   }
  }
  document.querySelector('#preview-details').hidden=false;
  if(result.format==='markdown')renderMarkdown(result.text);
  else if(result.format==='json'){
   const pre=document.createElement('pre');pre.textContent=result.text;previewContent.append(pre);
  }
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
const chatStatus=document.querySelector('#chat-backend-status');
const settingsBackendStatus=document.querySelector('#settings-backend-status');
const settingsExternalStatus=document.querySelector('#settings-external-status');
const chatMessages=document.querySelector('#chat-messages');
const chatForm=document.querySelector('#chat-backend-form');
const chatOperationStatus=document.querySelector('#chat-operation-status');
let activeThread=null,chatBinding=null,pendingChatRequest=null;
function renderChat(thread){
 activeThread=thread || null;chatMessages.replaceChildren();
 for(const item of thread?.messages || []){
  const message=document.createElement('div');message.className='chat-message '+item.role;
  message.textContent=item.content;
  const detail=document.createElement('small');detail.textContent=`${item.role==='user'?'Vy':'Asistent'} · ${item.privacy}`;
  message.append(detail);chatMessages.append(message);
 }
 document.querySelector('#chat-record-actions').hidden=!(thread?.messages?.length);
}
document.querySelector('#chat-new-thread').addEventListener('click',()=>{
 pendingChatRequest=null;renderChat(null);draft.value='';
 chatOperationStatus.textContent='';
 document.querySelector('#chat-submit').disabled=true;
 chatStatus.textContent=chatBinding ? `Nové vlákno · backend: ${chatBinding.model}` :
  'Nové vlákno · nejprve nastavte backend.';
 draft.focus();
});
function fillBinding(binding){
 chatBinding=binding;const fields=chatForm.elements;
 if(binding){fields.boundary.value=binding.boundary;fields.endpoint.value=binding.endpoint;
  fields.model.value=binding.model;fields.target_id.value=binding.target_id;
  fields.tls_cert_sha256.value=binding.tls_cert_sha256 || '';
  chatStatus.textContent=`Backend: ${binding.model} · ${binding.boundary}`;
  settingsBackendStatus.textContent=`Nastaven backend ${binding.model} · ${binding.boundary}.`;
 }else{
  chatStatus.textContent='Backend zatím není nastaven.';
  settingsBackendStatus.textContent='Backend zatím není nastaven.';
 }
}
async function loadBackendBinding(){
 try{const result=await projectRequest('/v1/chat/status',{});fillBinding(result.binding);
  const external=await projectRequest('/v1/external/status',{});
  settingsExternalStatus.textContent=external.binding ?
   `Nastaven externí backend ${external.binding.model}; klíč ${external.credential?.available?'je uložen':'chybí'}.` :
   'Externí backend zatím není nastaven.';return true;}
 catch(error){settingsBackendStatus.textContent=error.message;return false;}
}
async function loadChat(){
 try{
  const result=await projectRequest('/v1/chat/status',{});fillBinding(result.binding);
  const active=[...result.threads].reverse().filter(item=>item.status==='active');
  renderChat(active.find(item=>item.project_id===activeProject?.id) ||
             active.find(item=>item.project_id===null) || null);
 }catch(error){chatStatus.textContent=error.message;renderChat(null);}
}
chatForm.addEventListener('submit',async event=>{
 event.preventDefault();const fields=chatForm.elements;
 const boundary=fields.boundary.value;
 const binding={schema_version:1,binding_id:chatBinding?.binding_id || crypto.randomUUID(),
  revision:crypto.randomUUID(),adapter:'ollama',boundary,endpoint:fields.endpoint.value.trim(),
  model:fields.model.value.trim(),target_id:boundary==='same-node'?'local-process':fields.target_id.value.trim()};
 if(boundary==='private-network')binding.tls_cert_sha256=fields.tls_cert_sha256.value.trim();
 settingsBackendStatus.textContent='Ukládám backend…';
 try{const result=await projectRequest('/v1/chat/configure',binding);fillBinding(result.binding);
  settingsBackendStatus.textContent=`Backend ${result.binding.model} byl uložen.`;}
 catch(error){
  const message=error.message;const reloaded=await loadBackendBinding();
  settingsBackendStatus.textContent=reloaded ? message+' Poslední potvrzené nastavení bylo znovu načteno.' :
   message+' Aktuální stav nelze potvrdit; zkuste nastavení znovu otevřít.';
 }
});
document.querySelector('#external-backend-form').addEventListener('submit',async event=>{
 event.preventDefault();const form=event.currentTarget,fields=form.elements;
 const binding={schema_version:1,binding_id:crypto.randomUUID(),revision:crypto.randomUUID(),
  adapter:'openai-responses',boundary:'external-provider',endpoint:fields.endpoint.value,
  model:fields.model.value.trim(),target_id:'api.openai.com',
  max_output_tokens:Number(fields.max_output_tokens.value),
  timeout_seconds:Number(fields.timeout_seconds.value),secret:fields.secret.value};
 settingsExternalStatus.textContent='Ukládám externí backend…';
 try{const result=await projectRequest('/v1/external/configure',binding);
  fields.secret.value='';settingsExternalStatus.textContent=
   `Externí backend ${result.binding.model} byl uložen; klíč server nevrátil.`;}
 catch(error){fields.secret.value='';settingsExternalStatus.textContent=error.message;}
});
draft.addEventListener('input',()=>{
 document.querySelector('#chat-submit').disabled=!activeProject || !draft.value.trim();
});
document.querySelector('#chat-composer').addEventListener('submit',async event=>{
 event.preventDefault();if(!activeProject || !draft.value.trim())return;
 selectMainTab(mainTabs[1]);
 if(!chatBinding){chatOperationStatus.textContent='Nejprve uložte nastavení backendu.';return;}
 if(!pendingChatRequest){pendingChatRequest={project_id:activeProject.id,expected_head:activeProject.head,
  thread_id:activeThread?.thread_id || crypto.randomUUID(),turn_id:crypto.randomUUID(),
  message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
  assistant_message_id:crypto.randomUUID(),
  selected_message_ids:(activeThread?.messages || []).map(item=>item.message_id),
  content:draft.value.trim(),privacy:document.querySelector('#chat-privacy').value,
  created_at:new Date().toISOString()};}
 const submit=document.querySelector('#chat-submit');submit.disabled=true;chatOperationStatus.textContent='Odesílám…';
 const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';},250);
 try{
  const result=await projectRequest('/v1/chat/send',pendingChatRequest,210000);
  renderChat(result.thread);fillBinding(result.target);pendingChatRequest=null;draft.value='';draft.focus();
  chatOperationStatus.textContent='Odpověď je připravena.';
 }catch(error){await loadChat();chatOperationStatus.textContent=error.message;}
 finally{clearTimeout(thinking);submit.disabled=!activeProject || !draft.value.trim();
  document.querySelector('#main-panel-content').scrollTop=document.querySelector('#main-panel-content').scrollHeight;}
});
async function assignActiveThread(){
 if(!activeProject || !activeThread)throw new Error('Nejprve vytvořte chatové vlákno.');
 if(activeThread.project_id===activeProject.id)return activeThread;
 const assigned=await projectRequest('/v1/chat/assign',{project_id:activeProject.id,
  thread_id:activeThread.thread_id,expected_revision:activeThread.revision});
 renderChat(assigned);return assigned;
}
async function runChatRecord(button,action){
 button.disabled=true;chatOperationStatus.textContent='Připravuji projektový záznam…';
 try{
  const thread=await assignActiveThread();
  if(action==='snapshot'){
   await projectRequest('/v1/chat/snapshot',{operation_id:crypto.randomUUID(),project_id:activeProject.id,
    thread_id:thread.thread_id,expected_thread_revision:thread.revision,expected_head:activeProject.head,
    snapshot_id:crypto.randomUUID(),mode:'full',title:'Záznam brainstormingu',created_at:new Date().toISOString(),
    base_snapshot_id:null,base_snapshot_sha256:null});
  }else{
   const answer=[...thread.messages].reverse().find(item=>item.role==='assistant');
   if(!answer)throw new Error('Vlákno zatím nemá odpověď asistenta.');
   await projectRequest('/v1/chat/output',{operation_id:crypto.randomUUID(),project_id:activeProject.id,
    thread_id:thread.thread_id,expected_thread_revision:thread.revision,expected_head:activeProject.head,
    artifact_id:crypto.randomUUID(),title:'Výstup z brainstormingu',body:answer.content,
    created_at:new Date().toISOString(),message_ids:[answer.message_id],snapshot_id:null,snapshot_sha256:null});
  }
  chatOperationStatus.textContent=action==='snapshot'?'Otisk byl uložen do projektu.':'Výstup byl uložen jako editovatelný dokument.';
  await openRegisteredProject(activeProject.id);selectMainTab(mainTabs[1]);
 }catch(error){chatOperationStatus.textContent=error.message;}
 finally{button.disabled=false;}
}
document.querySelector('#chat-save-snapshot').addEventListener('click',event=>runChatRecord(event.currentTarget,'snapshot'));
document.querySelector('#chat-save-output').addEventListener('click',event=>runChatRecord(event.currentTarget,'output'));
draft.addEventListener('keydown',event=>{
 if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();document.querySelector('#chat-composer').requestSubmit();}
});
let summaryPreview=null,pendingSummaryRequest=null,pendingSummaryPublish=null;
const summaryStatus=document.querySelector('#summary-status');
const summaryPreviewElement=document.querySelector('#summary-preview');
function clearSummary(){
 summaryPreview=null;pendingSummaryRequest=null;pendingSummaryPublish=null;
 if(summaryPreviewElement)summaryPreviewElement.replaceChildren();
 const controls=document.querySelector('#summary-publish-controls');if(controls)controls.hidden=true;
 if(summaryStatus)summaryStatus.textContent='';
}
function renderSummarySources(){
 const list=document.querySelector('#summary-artifact-list');if(!list)return;list.replaceChildren();
 for(const item of currentArtifacts){
  const label=document.createElement('label');const input=document.createElement('input');
  input.type='checkbox';input.value=item.id;label.append(input,document.createTextNode(' '+item.title));list.append(label);
 }
}
function renderSummary(text){
 summaryPreviewElement.replaceChildren();
 for(const line of text.split('\\n')){
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const item=document.createElement(heading?'h'+heading[1].length:'p');
  item.textContent=heading?heading[2]:line;summaryPreviewElement.append(item);
 }
}
document.querySelector('#summary-kind').addEventListener('change',event=>{
 document.querySelector('#summary-artifacts').hidden=event.target.value!=='artifacts';
 pendingSummaryRequest=null;summaryPreview=null;summaryPreviewElement.replaceChildren();
 document.querySelector('#summary-publish-controls').hidden=true;
});
document.querySelector('#summary-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){summaryStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 const kind=document.querySelector('#summary-kind').value;
 try{
  let selection;
  if(kind==='artifacts'){
   const ids=[...document.querySelectorAll('#summary-artifact-list input:checked')].map(item=>item.value);
   if(!ids.length)throw new Error('Vyberte alespoň jeden podklad.');
   selection={kind:'artifacts',artifact_ids:ids};
  }else{
   const thread=await assignActiveThread();
   if(!thread.messages.length)throw new Error('Aktuální chat nemá zprávy.');
   selection={kind:'messages',thread_id:thread.thread_id,thread_revision:thread.revision,
    message_ids:thread.messages.map(item=>item.message_id)};
  }
  if(!pendingSummaryRequest){
   const focusText=document.querySelector('#summary-focus').value.trim();
   pendingSummaryRequest={schema:'fpw-summary-request-v1',task_id:crypto.randomUUID(),
    run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),project_id:activeProject.id,
    expected_head:activeProject.head,role_id:'summarizer',role_revision:'summarizer-v1',
    target:chatBinding,selection,focus:focusText?{input_id:crypto.randomUUID(),content:focusText,
     privacy:document.querySelector('#summary-focus-privacy').value}:null};
  }
  event.currentTarget.disabled=true;summaryStatus.textContent='Připravuji souhrn…';
  const result=await projectRequest('/v1/summary/preview',pendingSummaryRequest,210000);
  summaryPreview=result;pendingSummaryRequest=null;pendingSummaryPublish=null;renderSummary(result.response);
  document.querySelector('#summary-publish-controls').hidden=false;
  summaryStatus.textContent=`Náhled je připraven · soukromí: ${result.privacy}.`;
 }catch(error){summaryStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
document.querySelector('#summary-publish').addEventListener('click',async event=>{
 if(!summaryPreview || !activeProject)return;
 try{
  const title=document.querySelector('#summary-title').value.trim();
  if(!title)throw new Error('Zadejte název souhrnu.');
  if(!pendingSummaryPublish)pendingSummaryPublish={task_id:summaryPreview.task_id,
   preview_sha256:summaryPreview.response_sha256,project_id:activeProject.id,
   expected_head:activeProject.head,artifact_id:crypto.randomUUID(),title,
   created_at:new Date().toISOString(),operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;summaryStatus.textContent='Ukládám souhrn do projektu…';
  await projectRequest('/v1/summary/publish',pendingSummaryPublish);
  const projectId=activeProject.id;summaryStatus.textContent='Souhrn byl uložen do projektu.';
  await openRegisteredProject(projectId);
 }catch(error){summaryStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
let extractionPreview=null,pendingExtractionRequest=null,pendingExtractionPublish=null;
const extractionStatus=document.querySelector('#extraction-status');
const extractionPreviewElement=document.querySelector('#extraction-preview');
function clearExtraction(){
 extractionPreview=null;pendingExtractionRequest=null;pendingExtractionPublish=null;
 if(extractionPreviewElement)extractionPreviewElement.textContent='';
 const controls=document.querySelector('#extraction-publish-controls');if(controls)controls.hidden=true;
 if(extractionStatus)extractionStatus.textContent='';
}
function renderExtractionSources(){
 const list=document.querySelector('#extraction-artifact-list');if(!list)return;list.replaceChildren();
 for(const item of currentArtifacts){const label=document.createElement('label');const input=document.createElement('input');
  input.type='checkbox';input.value=item.id;label.append(input,document.createTextNode(' '+item.title));list.append(label);}
}
document.querySelector('#extraction-kind').addEventListener('change',event=>{
 document.querySelector('#extraction-artifacts').hidden=event.target.value!=='artifacts';clearExtraction();
});
document.querySelector('#extraction-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){extractionStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 try{
  const kind=document.querySelector('#extraction-kind').value;let selection;
  if(kind==='artifacts'){
   const ids=[...document.querySelectorAll('#extraction-artifact-list input:checked')].map(item=>item.value);
   if(!ids.length)throw new Error('Vyberte alespoň jeden podklad.');
   selection={kind:'artifacts',artifact_ids:ids};
  }else{const thread=await assignActiveThread();if(!thread.messages.length)throw new Error('Aktuální chat nemá zprávy.');
   selection={kind:'messages',thread_id:thread.thread_id,thread_revision:thread.revision,
    message_ids:thread.messages.map(item=>item.message_id)};}
  const [schemaId,schemaRevision]=document.querySelector('#extraction-schema').value.split('|');
  const focusText=document.querySelector('#extraction-focus').value.trim();
  if(!pendingExtractionRequest)pendingExtractionRequest={schema:'fpw-extraction-request-v1',task_id:crypto.randomUUID(),
   run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),project_id:activeProject.id,expected_head:activeProject.head,
   role_id:'extractor',role_revision:'extractor-v1',target:chatBinding,schema_id:schemaId,
   schema_revision:schemaRevision,selection,focus:focusText?
   {input_id:crypto.randomUUID(),content:focusText,privacy:document.querySelector('#extraction-focus-privacy').value}:null};
  event.currentTarget.disabled=true;extractionStatus.textContent='Připravuji extrakci…';
  const result=await projectRequest('/v1/extraction/preview',pendingExtractionRequest,210000);
  extractionPreview=result;pendingExtractionRequest=null;pendingExtractionPublish=null;
  extractionPreviewElement.textContent=JSON.stringify(JSON.parse(result.response),null,2);
  document.querySelector('#extraction-publish-controls').hidden=false;
  extractionStatus.textContent=`Náhled je připraven · soukromí: ${result.privacy}.`;
 }catch(error){extractionStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#extraction-publish').addEventListener('click',async event=>{
 if(!extractionPreview || !activeProject)return;
 try{const title=document.querySelector('#extraction-title').value.trim();if(!title)throw new Error('Zadejte název extrakce.');
  if(!pendingExtractionPublish)pendingExtractionPublish={task_id:extractionPreview.task_id,
   preview_sha256:extractionPreview.response_sha256,project_id:activeProject.id,expected_head:activeProject.head,
   artifact_id:crypto.randomUUID(),title,created_at:new Date().toISOString(),operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;extractionStatus.textContent='Ukládám extrakci do projektu…';
  await projectRequest('/v1/extraction/publish',pendingExtractionPublish);const projectId=activeProject.id;
  extractionStatus.textContent='Extrakce byla uložena do projektu.';await openRegisteredProject(projectId);
 }catch(error){extractionStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
let metadataPreview=null,pendingMetadataRequest=null,pendingMetadataPublish=null;
const metadataStatus=document.querySelector('#metadata-status');
function clearMetadata(){
 metadataPreview=null;pendingMetadataRequest=null;pendingMetadataPublish=null;
 const diff=document.querySelector('#metadata-diff');if(diff)diff.hidden=true;
 if(metadataStatus)metadataStatus.textContent='';
}
function renderMetadataSources(){
 const select=document.querySelector('#metadata-artifact');if(!select)return;select.replaceChildren();
 const empty=document.createElement('option');empty.value='';empty.textContent='Vyberte artefakt';select.append(empty);
 for(const item of currentArtifacts){const option=document.createElement('option');option.value=item.id;
  option.textContent=item.title;select.append(option);}
}
document.querySelector('#metadata-artifact').addEventListener('change',clearMetadata);
document.querySelector('#metadata-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){metadataStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 const artifactId=document.querySelector('#metadata-artifact').value;
 if(!artifactId){metadataStatus.textContent='Vyberte jeden artefakt.';return;}
 try{
  if(!pendingMetadataRequest)pendingMetadataRequest={schema:'fpw-metadata-suggestion-request-v1',
   task_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
   project_id:activeProject.id,expected_head:activeProject.head,role_id:'metadata-advisor',
   role_revision:'metadata-advisor-v1',target:chatBinding,
   selection:{kind:'artifacts',artifact_ids:[artifactId]},focus:null,metadata_input_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;metadataStatus.textContent='Připravuji návrh metadat…';
  const result=await projectRequest('/v1/metadata-suggestions/preview',pendingMetadataRequest,210000);
  metadataPreview=result;pendingMetadataRequest=null;pendingMetadataPublish=null;
  document.querySelector('#metadata-description-before').textContent='Původní: '+(result.diff.description.before || 'bez popisu');
  const description=document.querySelector('#metadata-apply-description');
  description.checked=false;description.disabled=!result.diff.description.changed;
  document.querySelector('#metadata-description-after').textContent=result.diff.description.after===null?
   'Model nenavrhl nový popis.':'Navržený: '+result.diff.description.after;
  const tags=document.querySelector('#metadata-tag-list');tags.replaceChildren();
  for(const tag of result.diff.tags.suggested_additions){const label=document.createElement('label');
   const input=document.createElement('input');input.type='checkbox';input.value=tag;
   label.append(input,document.createTextNode(' '+tag));tags.append(label);}
  if(!result.diff.tags.suggested_additions.length)tags.textContent='Model nenavrhl žádný nový štítek.';
  document.querySelector('#metadata-diff').hidden=false;
  metadataStatus.textContent=`Návrh je připraven · soukromí: ${result.privacy}.`;
 }catch(error){metadataStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#metadata-publish').addEventListener('click',async event=>{
 if(!metadataPreview || !activeProject)return;
 try{const applyDescription=document.querySelector('#metadata-apply-description').checked;
  const tags=[...document.querySelectorAll('#metadata-tag-list input:checked')].map(item=>item.value);
  if(!applyDescription && !tags.length)throw new Error('Vyberte alespoň jednu změnu.');
  if(!pendingMetadataPublish)pendingMetadataPublish={task_id:metadataPreview.task_id,
   preview_sha256:metadataPreview.response_sha256,project_id:activeProject.id,
   expected_head:activeProject.head,artifact_id:document.querySelector('#metadata-artifact').value,
   apply_description:applyDescription,tags,operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;metadataStatus.textContent='Ukládám potvrzená metadata…';
  await projectRequest('/v1/metadata-suggestions/publish',pendingMetadataPublish);
  const projectId=activeProject.id;metadataStatus.textContent='Vybraná metadata byla uložena.';
  await openRegisteredProject(projectId);
 }catch(error){metadataStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
loadProjects();
"""
ASSETS = {'/': ('text/html; charset=utf-8', HTML), '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS)}


class DesktopHandler(Handler):
    assets = ASSETS
    max_body = 64 * 1024
    post_paths = Handler.post_paths | {'/v1/projects', '/v1/projects/open',
        '/v1/artifacts/preview', '/v1/chat/status', '/v1/chat/configure', '/v1/chat/send',
        '/v1/external/status', '/v1/external/configure',
        '/v1/chat/assign', '/v1/chat/snapshot', '/v1/chat/output',
        '/v1/summary/status', '/v1/summary/preview', '/v1/summary/publish',
        '/v1/extraction/status', '/v1/extraction/preview', '/v1/extraction/publish',
        '/v1/metadata-suggestions/status', '/v1/metadata-suggestions/preview',
        '/v1/metadata-suggestions/publish'}

    def dispatch(self, request):
        if self.path == '/v1/counter':
            return super().dispatch(request)
        projects = self.server.projects or Projects()
        try:
            if self.path == '/v1/metadata-suggestions/status' and request == {}:
                return self.reply(200, self.server.metadata_suggestion_service.status())
            if self.path == '/v1/metadata-suggestions/preview' and isinstance(request, dict):
                return self.reply(200, self.server.metadata_suggestion_service.preview(request))
            if self.path == '/v1/metadata-suggestions/publish' and isinstance(request, dict):
                return self.reply(200, self.server.metadata_suggestion_service.publish(request))
            if self.path == '/v1/extraction/status' and request == {}:
                return self.reply(200, self.server.extraction_service.status())
            if self.path == '/v1/extraction/preview' and isinstance(request, dict):
                return self.reply(200, self.server.extraction_service.preview(request))
            if self.path == '/v1/extraction/publish' and isinstance(request, dict):
                return self.reply(200, self.server.extraction_service.publish(request))
            if self.path == '/v1/summary/status' and request == {}:
                return self.reply(200, self.server.summary_service.status())
            if self.path == '/v1/summary/preview' and isinstance(request, dict):
                return self.reply(200, self.server.summary_service.preview(request))
            if self.path == '/v1/summary/publish' and isinstance(request, dict):
                return self.reply(200, self.server.summary_service.publish(request))
            if self.path == '/v1/chat/status' and request == {}:
                return self.reply(200, self.server.chat_service.status())
            if self.path == '/v1/external/status' and request == {}:
                return self.reply(200, self.server.chat_service.external_status())
            if self.path == '/v1/external/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure_external(request))
            if self.path == '/v1/chat/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure(request))
            if self.path == '/v1/chat/send' and isinstance(request, dict) and set(request) == {
                    'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                    'content', 'privacy', 'created_at'}:
                return self.reply(200, self.server.chat_service.send(**request))
            if self.path == '/v1/chat/assign' and isinstance(request, dict) and set(request) == {
                    'project_id', 'thread_id', 'expected_revision'}:
                return self.reply(200, self.server.chat_service.assign(**request))
            if self.path in {'/v1/chat/snapshot', '/v1/chat/output'} and isinstance(request, dict):
                payload = dict(request); operation_id = payload.pop('operation_id', None)
                if self.path == '/v1/chat/snapshot':
                    return self.reply(200, self.server.chat_service.publish_snapshot(payload, operation_id))
                return self.reply(200, self.server.chat_service.publish_output(payload, operation_id))
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
        except UnknownRun:
            return self.reply(409, {'error': 'Výsledek běhu není známý. Vlákno bylo zachováno; '
                                   'zkontrolujte stav před novým odesláním.'})
        except OllamaResponseError:
            return self.reply(502, {'error': 'Lokální LLM požadavek selhal. Vlákno a stav běhu byly zachovány.'})
        except PendingOperation:
            return self.reply(409, {'error': 'Projekt má nedokončenou operaci. Nejprve proveďte obnovu.'})
        except StaleIndex:
            return self.reply(409, {'error': 'Projekt se během čtení změnil. Zkuste jej znovu otevřít.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            if self.path.startswith(('/v1/chat/', '/v1/external/', '/v1/summary/', '/v1/extraction/',
                                     '/v1/metadata-suggestions/')):
                return self.reply(422, {'error': 'Chat požadavek nelze provést. Ověřte backend, '
                                       'projekt, výběr kontextu a lokální stav.'})
            # Do not forward paths, Git stderr or configuration payloads to the renderer.
            return self.reply(422, {'error': 'Projekt nelze otevřít: ověřte konfiguraci, registraci, '
                                   'práva lokálního stavu a platnost Git dat/indexu.'})

    def do_GET(self):
        if self.single('Host') != self.server.authority:
            return self.send_error(403)
        if self.path not in self.assets:
            return self.send_error(404)
        kind, content = self.assets[self.path]
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
