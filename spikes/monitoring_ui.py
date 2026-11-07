# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared, inert monitoring UI. All mutations go through authenticated services."""
HTML='''<div id="monitoring-panel" role="tabpanel" aria-labelledby="monitoring-tab" hidden>
<header><h2>Sledování a zprávy</h2><p>Společný cíl a historie, samostatné zadání pro každé období.</p></header>
<p id="monitoring-status" role="status" aria-live="polite"></p>
<section id="monitoring-rss-section" hidden><h3>Průběžný sběr RSS</h3><ul id="monitoring-rss-list"></ul><h4>Výběr položek</h4><ul id="monitoring-findings-list"></ul></section>
<div class="monitoring-grid"><section><h3>Sledování</h3><button id="monitoring-new" type="button">Nové sledování</button>
<ul id="monitoring-watches"></ul></section><section id="monitoring-detail"><p>Vyberte sledování nebo zprávu.</p></section></div>
<form id="monitoring-form" hidden>
<h3 id="monitoring-form-title">Nové sledování</h3>
<label>Název <input name="name" required maxlength="150"></label>
<label>Cíl / téma <textarea name="goal" required maxlength="2000"></textarea></label>
<label>Rozsah (témata oddělená čárkou) <input name="tags"></label>
<div class="monitoring-grid"><label>Začátek sledování <input name="start" type="date" required></label>
<label>Časová zóna <input name="timezone" value="Europe/Prague" required></label></div>
<label>Projektové podklady <select name="inputs" multiple size="6" aria-describedby="monitoring-input-help"></select></label>
<p id="monitoring-input-help">Podklady zůstanou připnuté k přesnému běhu. Jejich obsah není automaticky potvrzená událost.</p>
<label>Veřejné webové zdroje (HTTPS URL, každý na řádku) <textarea name="urls" rows="3"></textarea></label>
<label>Podmínky přístupu / licence a povolené uchování <textarea name="access_note" rows="2"></textarea></label>
<label><input name="access_confirm" type="checkbox"> Zkontroloval jsem podmínky, licenci a povoluji sběr a uchování uvedených veřejných zdrojů.</label>
<fieldset id="monitoring-periods"><legend>Období a zadání reportů</legend></fieldset>
<label>Zpracování <select name="mode"><option value="deterministic">Pravidlový přehled bez LLM</option><option value="llm">Návrh pomocí nastaveného modelu</option></select></label>
<p id="monitoring-model"></p>
<label>Soukromí <select name="privacy"><option value="project">Projekt</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto uzlu</option></select></label>
<label><input name="presentation" type="checkbox"> Zpráva + navázaný návrh prezentace</label>
<label><input name="active" type="checkbox" checked> Aktivní sledování</label>
<p>Uložením schvalujete konfiguraci a zvolené sběry/model. Každá zpráva čeká na samostatné posouzení a vydání.</p>
<button type="submit">Uložit sledování</button> <button id="monitoring-form-cancel" type="button">Zrušit</button>
</form>
<section><h3>Zprávy</h3><ul id="monitoring-reports"></ul></section>
</div>'''
CSS='''
.monitoring-grid{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,2fr);gap:1rem}
#monitoring-panel{max-width:1200px;margin:auto;padding:1rem}#monitoring-panel label{display:block;margin:.7rem 0}
#monitoring-panel input:not([type=checkbox]),#monitoring-panel textarea,#monitoring-panel select{box-sizing:border-box;width:100%;max-width:100%}
#monitoring-panel textarea{min-height:5rem}#monitoring-panel li{margin:.5rem 0}#monitoring-panel button{margin:.2rem}
#monitoring-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:70vh;overflow:auto;background:var(--panel,#f4f6f7);padding:1rem}
.monitoring-period{border-top:1px solid #bbc7cb;padding:.5rem}#monitoring-form{border:1px solid #bbc7cb;border-radius:.5rem;padding:1rem}
@media(max-width:760px){.monitoring-grid{grid-template-columns:1fr}}
'''
JS=r'''
let monitoringView=null,monitoringEdit=null,monitoringDirty=false,monitoringAttempt=null;
const monitoringForm=document.querySelector('#monitoring-form');
const monitoringStatus=document.querySelector('#monitoring-status');
const monitoringLabels={weekly:'Týden',monthly:'Měsíc',quarterly:'Čtvrtletí',annual:'Rok / výroční zpráva'};
const monitoringStates={succeeded:'Staženo',fetching:'Stahuje se',prepared:'Připraveno',collecting:'Zpracovává se',review:'K posouzení',approved:'Schváleno',issuing:'Vydává se',issued:'Vydáno, čeká na doručení',completed:'Vydáno',failed:'Chyba',cancelled:'Zrušeno',unknown:'Neznámý výsledek — vyžaduje dohledání'};
function clearMonitoring(){monitoringView=null;monitoringEdit=null;monitoringAttempt=null;monitoringDirty=false;monitoringForm.hidden=true;document.querySelector('#monitoring-rss-section').hidden=true;for(const id of ['monitoring-watches','monitoring-reports','sidebar-monitoring-list','sidebar-report-list','monitoring-rss-list','monitoring-findings-list'])document.getElementById(id)?.replaceChildren();}
async function canLeaveMonitoring(){if(!monitoringDirty&&!monitoringAttempt)return true;return resolveEditorLeave('Sledování',saveMonitoring,()=>{monitoringDirty=false;monitoringAttempt=null;monitoringForm.hidden=true;});}
function monitoringOpen(section='tools'){selectSidebarTab(document.querySelector(section==='outputs'?'#presentations-tab':'#tools-tab'));selectMainTab(document.querySelector('#monitoring-tab'));}
function monitoringButton(label,action,disabled=false){const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=disabled;b.addEventListener('click',async()=>{try{await action();}catch(error){monitoringStatus.textContent=error.message;}});return b;}
async function monitoringRequest(action,payload={}){if(!activeProject)throw Error('Otevřete projekt.');return projectRequest('/v1/monitoring/'+action,{project_id:activeProject.id,...payload},120000);}
let monitoringLoadSequence=0;
async function loadMonitoring(){
 if(!activeProject)return;const projectId=activeProject.id,sequence=++monitoringLoadSequence;
 try{const result=await monitoringRequest('view');if(activeProject?.id!==projectId||sequence!==monitoringLoadSequence)return;monitoringView=result;activeProject.head=result.commit_id;renderMonitoring();}
 catch(error){if(activeProject?.id===projectId)monitoringStatus.textContent=error.message;}
}
function renderMonitoring(){
 if(!monitoringView)return;const readonly=activeProject?.readOnly||!monitoringView.can_manage;
 document.querySelector('#monitoring-new').disabled=readonly;document.querySelector('#sidebar-monitoring-new').disabled=readonly;
 monitoringStatus.textContent=monitoringView.error||`${monitoringView.watches.length} sledování · ${monitoringView.reports.length} zpráv`;
 const rss=monitoringView.rss,rssList=document.querySelector('#monitoring-rss-list');rssList.replaceChildren();
 document.querySelector('#monitoring-rss-section').hidden=!rss?.bindings?.length&&!rss?.findings?.length;
 const findingsList=document.querySelector('#monitoring-findings-list');findingsList.replaceChildren();
 for(const finding of rss?.findings||[]){const value=finding.value,li=document.createElement('li'),summary=document.createElement('p');
  summary.textContent=value.item.title+' — '+value.stage+' · '+value.selection.reason;li.append(summary);
  const evaluation=rss.evaluations?.[finding.revision_id];if(evaluation){const p=document.createElement('p'),r=evaluation.result;
   p.textContent='Relevance: '+(r.relevance??'neznámá')+' · Potenciální význam: '+(r.significance??'neznámý')+' · Důvěryhodnost tvrzení: '+r.trustworthiness;li.append(p);
   for(const step of evaluation.steps){const p=document.createElement('p');p.textContent=step.id+' · '+step.outcome+' · '+step.reason;li.append(p);}}
  const audit=value.selection.audit;if(audit){const details=document.createElement('details'),caption=document.createElement('summary');caption.textContent='Pravidla a vysvětlení';details.append(caption);
   for(const step of audit.result.steps){const p=document.createElement('p');p.textContent=step.id+' · '+step.kind+' · '+step.outcome+' · '+step.reason;details.append(p);}
   details.append(monitoringButton('Náhled pravidel na ukázce',()=>showMonitoringFilterPreview(value.item,audit.pipeline)));li.append(details);}
  findingsList.append(li);
 }
 for(const binding of rss?.bindings||[]){const li=document.createElement('li');
  const at=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('cs-CZ'):'dosud neproběhla';
  const pending=rss.polls.filter(p=>p.binding===binding.key).at(-1);
  li.textContent=binding.url+' — '+(binding.enabled?'Zapnuto':'Pozastaveno')+' · kontrola každých '+Math.round(binding.interval/60)+' min · poslední úspěšná: '+at(binding.last_success)+' · příští: '+at(binding.next_due);
  if(pending?.state==='unknown')li.textContent+=' · Neznámý výsledek, čeká na dohledání.';
  if(binding.last_error)li.textContent+=' · '+binding.last_error;
  rssList.append(li);
 }
 for(const id of ['monitoring-watches','sidebar-monitoring-list']){
  const list=document.getElementById(id);list.replaceChildren();
  for(const watch of monitoringView.watches){const li=document.createElement('li');const valid=monitoringView.granted[watch.id];
   li.append(monitoringButton(watch.name,()=>{monitoringOpen();showMonitoringWatch(watch);}));const state=document.createElement('span');
   state.textContent=' — '+(!valid?'Změněná konfigurace čeká na souhlas':watch.active?'Aktivní':'Pozastaveno');li.append(state);list.append(li);}
 }
 for(const id of ['monitoring-reports','sidebar-report-list']){
  const list=document.getElementById(id);list.replaceChildren();
  for(const report of monitoringView.reports){const li=document.createElement('li');li.append(monitoringButton(`${report.name} · ${monitoringLabels[report.kind]||report.kind} · ${report.period.start_local.slice(0,10)} · ${monitoringStates[report.state]||report.state}`,()=>{monitoringOpen('outputs');showMonitoringReport(report);}));list.append(li);}
 }
}
function showMonitoringFilterPreview(item,pipeline){
 const target=document.querySelector('#monitoring-detail');target.replaceChildren();
 const heading=document.createElement('h3');heading.textContent='Náhled pravidel · '+pipeline.revision;target.append(heading);
 const note=document.createElement('p');note.textContent='Ukázka nic nepublikuje a nespouští LLM. Chybějící jazyk se neodhaduje.';target.append(note);
 const title=document.createElement('input'),content=document.createElement('textarea');title.value=item.title;content.value=item.content;
 for(const [label,control] of [['Název ukázky',title],['Text ukázky',content]]){const l=document.createElement('label');l.textContent=label;l.append(control);target.append(l);}
 const output=document.createElement('pre');output.setAttribute('aria-live','polite');
 const projectId=activeProject.id;
 target.append(monitoringButton('Vyhodnotit ukázku',async()=>{
  if(activeProject?.id!==projectId)return;
  const sample={...item,title:title.value,content:content.value};
  sample.content_sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(sample.content))),b=>b.toString(16).padStart(2,'0')).join('');
  if(activeProject?.id!==projectId||!output.isConnected)return;
  const preview=await monitoringRequest('filter-preview',{pipeline,items:[sample]});
  if(activeProject?.id!==projectId||!output.isConnected)return;
  const result=preview.results[0];output.textContent=result.decision+' · '+result.reason+'\n'+result.steps.map(s=>s.id+' · '+s.outcome+' · '+s.reason).join('\n');
 }));target.append(output);
}
function showMonitoringWatch(watch){
 const target=document.querySelector('#monitoring-detail');target.replaceChildren();const h=document.createElement('h3');h.textContent=watch.name;target.append(h);
 const p=document.createElement('p');p.textContent=watch.goal;target.append(p);
 if(monitoringView.watch_errors?.[watch.id]){const error=document.createElement('p');error.textContent=monitoringView.watch_errors[watch.id];target.append(error);}
 for(const capture of monitoringView.collections?.[watch.id]||[]){const item=document.createElement('p');item.textContent='Sběr: '+capture.url+' — '+(monitoringStates[capture.state]||capture.state)+(capture.error?' · '+capture.error:'');target.append(item);}
 const runs=monitoringView.reports.filter(r=>r.watch_id===watch.id);
 const last=document.createElement('p');last.textContent=runs.length?'Poslední běh: '+runs[0].period.end_local+' — '+(monitoringStates[runs[0].state]||runs[0].state):'Dosud žádný běh.';target.append(last);
 const next=document.createElement('p');next.textContent='Příští plánované periody: '+Object.entries(monitoringView.next_runs?.[watch.id]||{}).map(([k,v])=>`${monitoringLabels[k]}: ${v}`).join(' · ');target.append(next);
 const readOnly=activeProject.readOnly||!monitoringView.can_manage;
 target.append(monitoringButton('Upravit',()=>editMonitoring(watch),readOnly));
 target.append(monitoringButton(watch.active?'Pozastavit':'Obnovit',async()=>{const cfg=structuredClone(watch);cfg.active=!cfg.active;await monitoringRequest('save',{operation_id:crypto.randomUUID(),base_head:activeProject.head,watch:cfg,new:false});await loadMonitoring();},readOnly));
 const kind=document.createElement('select');for(const key of Object.keys(monitoringLabels).filter(k=>k in watch.periods)){const option=document.createElement('option');option.value=key;option.textContent=monitoringLabels[key];kind.append(option);}target.append(kind);
 target.append(monitoringButton('Spustit nyní',async()=>{monitoringStatus.textContent='Připravuji návrh za poslední uzavřené období…';await monitoringRequest('run',{watch_id:watch.id,kind:kind.value});await loadMonitoring();},readOnly||!watch.active||!monitoringView.granted[watch.id]));
}
function renderPresentationReportLink(){
 document.querySelector('#presentation-report-link')?.remove();
 const report=monitoringView?.reports.find(r=>r.presentation_id===presentationEditorArtifact);if(!report)return;
 const link=monitoringButton('Zdrojová zpráva'+(report.superseded?' — existuje vydaná oprava':''),()=>{monitoringOpen('outputs');showMonitoringReport(report);});link.id='presentation-report-link';document.querySelector('#presentation-panel').prepend(link);
}
function showMonitoringReport(report){
 const target=document.querySelector('#monitoring-detail');target.replaceChildren();const h=document.createElement('h3');h.textContent=report.name+' — '+(monitoringLabels[report.kind]||report.kind);target.append(h);
 const state=document.createElement('p');state.textContent=(monitoringStates[report.state]||report.state)+(report.error?' · '+report.error:'');target.append(state);
 if(report.superseded){const warning=document.createElement('p');warning.textContent='Existuje vydaná oprava. Tato zpráva i její prezentace zachovávají původní obsah.';target.append(warning);}
 if(report.corrects){const note=document.createElement('p');note.textContent='Oprava předchozího vydání: '+report.corrects.artifact_id;target.append(note);}
 const pre=document.createElement('pre');pre.textContent=report.markdown||'Úplný kandidát ještě není připravený. Neznámý běh se automaticky neopakuje.';target.append(pre);
 if(report.markdown)target.append(monitoringButton('Export Markdown',()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([report.markdown],{type:'text/markdown;charset=utf-8'}));a.href=url;a.download='zprava-'+report.period.kind+'-'+report.period.start_local.slice(0,10)+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
 const readOnly=activeProject.readOnly||!monitoringView.can_manage;
 if(report.state==='review'){
  const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';label.append(check,document.createTextNode(' Posoudil jsem přesný obsah, zdroje i omezení a schvaluji vydání.'));target.append(label);
  const publish=monitoringButton('Vydat zprávu',async()=>{await monitoringRequest('publish',{run_id:report.id,approval_digest:report.approval_digest,confirm:true});await loadMonitoring();showMonitoringReport(monitoringView.reports.find(r=>r.id===report.id));},true);
  check.addEventListener('change',()=>{publish.disabled=readOnly||!check.checked;});target.append(publish);
  target.append(monitoringButton('Odmítnout návrh',async()=>{await monitoringRequest('cancel',{run_id:report.id,confirm:true});await loadMonitoring();showMonitoringReport(monitoringView.reports.find(r=>r.id===report.id));},readOnly));
 }
 if(['failed','cancelled'].includes(report.state))target.append(monitoringButton('Nový pokus z původních vstupů',async()=>{await monitoringRequest('retry',{run_id:report.id,confirm:true});await loadMonitoring();showMonitoringReport(monitoringView.reports.find(r=>r.id===report.id));},readOnly));
 if(report.state==='completed'&&!report.superseded)target.append(monitoringButton('Připravit opravu z aktuálních podkladů',async()=>{await monitoringRequest('correct',{run_id:report.id});await loadMonitoring();},readOnly));
 if(report.state==='completed')target.append(monitoringButton('Vytvořit / otevřít prezentaci',async()=>{const result=await monitoringRequest('presentation',{run_id:report.id});if(document.body.dataset.runtime==='server'){monitoringStatus.textContent='Prezentace je uložená ve Výstupech; presenter otevřete v desktopu.';await loadMonitoring();}else await openPresentationEditor(result.artifact_id);},readOnly));
 if(report.presentation_id&&!readOnly&&document.body.dataset.runtime!=='server')target.append(monitoringButton('Otevřít navázanou prezentaci',()=>openPresentationEditor(report.presentation_id)));
}
async function editMonitoring(watch=null){
 if(!monitoringView)await loadMonitoring();if(!monitoringView)return;
 if(!await canLeaveMonitoring())return;monitoringOpen();monitoringEdit=watch?.id||crypto.randomUUID();monitoringAttempt=null;monitoringDirty=false;
 const cfg=watch||{name:'',goal:'',tags:[],start:new Date().toISOString().slice(0,10),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Europe/Prague',inputs:[],urls:[],access_note:'',periods:{weekly:monitoringView.profiles.weekly},mode:'deterministic',privacy:'project',active:true,presentation:false};
 for(const key of ['name','goal','start','timezone','access_note','mode','privacy'])monitoringForm.elements[key].value=cfg[key];
 monitoringForm.elements.tags.value=cfg.tags.join(', ');monitoringForm.elements.urls.value=cfg.urls.join('\n');
 for(const key of ['active','presentation'])monitoringForm.elements[key].checked=cfg[key];
 monitoringForm.elements.access_confirm.checked=Boolean(cfg.urls.length);monitoringForm.elements.privacy.disabled=Boolean(watch);
 const inputs=monitoringForm.elements.inputs;inputs.replaceChildren();for(const item of monitoringView.inputs){const option=document.createElement('option');option.value=item.id;option.textContent=item.title;option.selected=cfg.inputs.includes(item.id);inputs.append(option);}
 const field=document.querySelector('#monitoring-periods');field.querySelectorAll('.monitoring-period').forEach(e=>e.remove());
 for(const [key,profile] of Object.entries(monitoringView.profiles)){const row=document.createElement('div');row.className='monitoring-period';const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.period=key;check.checked=key in cfg.periods;label.append(check,document.createTextNode(' '+monitoringLabels[key]));const text=document.createElement('textarea');text.dataset.profile=key;text.value=cfg.periods[key]||profile;text.disabled=!check.checked;check.addEventListener('change',()=>{text.disabled=!check.checked;});row.append(label,text);field.append(row);}
 document.querySelector('#monitoring-model').textContent=monitoringView.binding?'Nastavený model: '+monitoringView.binding.model+' · '+monitoringView.binding.boundary:'Model není nastavený; modelový režim nebude dostupný.';
 for(const field of monitoringForm.querySelectorAll('input,select,textarea'))field.disabled=false;
 monitoringForm.elements.privacy.disabled=Boolean(watch);
 for(const check of monitoringForm.querySelectorAll('[data-period]'))monitoringForm.querySelector(`[data-profile="${check.dataset.period}"]`).disabled=!check.checked;
 monitoringForm.hidden=false;monitoringForm.elements.name.focus();
}
monitoringForm.addEventListener('input',()=>{monitoringDirty=true;});
async function saveMonitoring(){
 try{if(!monitoringForm.reportValidity())return false;
  if(!monitoringAttempt){const f=monitoringForm.elements;const urls=f.urls.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);if(urls.length&&!f.access_confirm.checked)throw Error('Potvrďte podmínky a uchování veřejných zdrojů.');
   const periods={};for(const check of monitoringForm.querySelectorAll('[data-period]'))if(check.checked)periods[check.dataset.period]=monitoringForm.querySelector(`[data-profile="${check.dataset.period}"]`).value;
   monitoringAttempt={operation_id:crypto.randomUUID(),base_head:activeProject.head,new:!monitoringView.watches.some(w=>w.id===monitoringEdit),watch:{id:monitoringEdit,name:f.name.value,goal:f.goal.value,tags:f.tags.value.split(',').map(s=>s.trim()).filter(Boolean),start:f.start.value,timezone:f.timezone.value,inputs:[...f.inputs.selectedOptions].map(o=>o.value),urls,access_note:f.access_note.value,periods,mode:f.mode.value,binding:f.mode.value==='llm'?monitoringView.binding:null,privacy:f.privacy.value,active:f.active.checked,presentation:f.presentation.checked}};}
  for(const field of monitoringForm.querySelectorAll('input,select,textarea'))field.disabled=true;
  monitoringStatus.textContent='Ukládám a připravuji sledování…';await monitoringRequest('save',monitoringAttempt);monitoringAttempt=null;monitoringDirty=false;monitoringForm.hidden=true;await loadMonitoring();return true;
 }catch(error){monitoringStatus.textContent=error.message;return false;}
}
monitoringForm.addEventListener('submit',event=>{event.preventDefault();saveMonitoring();});
document.querySelector('#monitoring-form-cancel').addEventListener('click',async()=>{if(await canLeaveMonitoring())monitoringForm.hidden=true;});
document.querySelector('#monitoring-new').addEventListener('click',()=>editMonitoring());
document.querySelector('#sidebar-monitoring-new').addEventListener('click',()=>editMonitoring());
setInterval(()=>{if(activeProject&&document.visibilityState!=='hidden'&&!monitoringDirty&&!monitoringAttempt)loadMonitoring();},15000);
'''
