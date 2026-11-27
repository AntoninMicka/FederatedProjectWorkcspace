# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared desktop/web relationship editor and explicit source selection."""
HTML = '''<dialog id="relations-dialog" aria-labelledby="relations-heading">
<header class="relations-heading"><h2 id="relations-heading">Vztahy a propojené podklady</h2><button id="relations-close" type="button" class="secondary-button">Zavřít</button></header>
<p id="relations-status" role="status"></p>
<div id="relations-overview"><section><h3>Vztahy projektu</h3><p>Vazba začne sdílet data až po potvrzení obou konců. Podprojekt poskytuje data rodiči; ostatní vazby poskytují publikované výstupy.</p><button id="relations-create" type="button">Přidat vztah</button><button id="relations-refresh" type="button" class="secondary-button">Obnovit přehled</button><div id="relations-list"></div></section>
<section><h3>Dostupné podklady</h3><label>Najít podle názvu nebo projektu <input id="relations-query" type="search" maxlength="200"></label><p class="relations-note">Vlastní a zděděná data jsou rozlišená. AI dostane jen výslovně vybrané textové podklady, ne celý propojený projekt.</p><div id="relations-sources"></div></section></div>
<form id="relations-editor" hidden><h3 id="relations-editor-title">Nový vztah</h3><label>Druh vztahu <select id="relations-type"><option value="parent_of">Rodič / podprojekt</option><option value="depends_on">Závislost na výstupech</option><option value="relates_to">Související projekty</option></select></label>
<label>Další projekt <select id="relations-other"></select></label><label id="relations-direction-label">Směr <select id="relations-direction"><option value="outgoing">Tento projekt poskytuje vztah</option><option value="incoming">Opačný směr</option></select></label>
<p id="relations-direction-help" class="relations-note"></p><label>Důvod <textarea id="relations-reason" rows="3" maxlength="1000" required></textarea></label><button type="submit">Připravit náhled</button><button class="relations-back secondary-button" type="button">Zpět na přehled</button></form>
<section id="relations-review" hidden><h3>Kontrola před uložením</h3><div id="relations-review-content"></div><label><input id="relations-approved" type="checkbox"> Potvrzuji uvedený směr, rozsah a zahrnutí budoucích dat/výstupů přes schválené cesty.</label><p><button id="relations-confirm" type="button" disabled>Potvrdit</button><button class="relations-back secondary-button" type="button">Zpět na přehled</button></p></section>
<section id="relations-preview" hidden><h3 id="relations-preview-title"></h3><p id="relations-preview-origin"></p><div id="relations-preview-content"></div><details><summary>Zdroj a přesná revize</summary><pre id="relations-preview-proof"></pre></details><button class="relations-back secondary-button" type="button">Zpět na přehled</button></section></dialog>'''

CSS = '''
#relations-dialog{width:min(1100px,94vw);max-height:90vh;overflow:auto;border:1px solid #baccc9;border-radius:14px;padding:22px;color:#213746}
.relations-heading{display:flex;align-items:center;justify-content:space-between;gap:15px}.relations-heading h2{margin:0}
#relations-overview{display:grid;grid-template-columns:minmax(260px,1fr) minmax(300px,1.4fr);gap:24px}
#relations-dialog section{min-width:0}#relations-dialog label{display:block;margin:10px 0}#relations-dialog input[type=search],#relations-dialog textarea,#relations-dialog select{box-sizing:border-box;width:100%;padding:8px}
.relations-card{border:1px solid #d3dfdc;border-radius:9px;padding:12px;margin:10px 0}.relations-card h4{margin:0 0 6px}.relations-card button{margin:5px 5px 0 0}.relations-note{color:#526675;font-size:13px}
#relations-status{white-space:pre-wrap}#relations-preview-content{max-height:55vh;overflow:auto}#relations-preview-content img{max-width:100%}#relations-preview-proof{white-space:pre-wrap;overflow-wrap:anywhere}
#relation-input-selection label{display:block;font-size:13px}#relation-input-selection{max-height:170px;overflow:auto;border:0;margin:8px 0;padding:0}
@media(max-width:720px){#relations-overview{grid-template-columns:1fr}}
'''

JS = r'''
var relationSelections=new Map(),relationSelectionProject=null;
const relationDialog=document.querySelector('#relations-dialog'),relationStatus=document.querySelector('#relations-status');
const RELATION_TYPES={parent_of:'Rodič / podprojekt',depends_on:'Závislost na výstupech',relates_to:'Souvislost'};
const RELATION_STATES={pending:'Čeká na souhlasy',active:'Aktivní',revoked:'Ukončená',conflict:'Konflikt',unavailable:'Nedostupná'};
let relationOverview=null,relationCatalog=null,relationEditing=null,relationAttempt=null,relationEpoch=0;
function relNode(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function relButton(text,run,disabled=false){const n=relNode('button',text);n.type='button';n.disabled=disabled;n.addEventListener('click',()=>Promise.resolve().then(run).catch(error=>relationStatus.textContent=error.message));return n;}
function relationProjectChanged(){if(!relationSelections)return;if(relationSelectionProject!==activeProject?.id){relationSelections.clear();relationSelectionProject=activeProject?.id;renderRelationSelections();}}
function selectedRelationInputs(){if(!relationSelections||relationSelectionProject!==activeProject?.id)return [];return [...relationSelections.values()].filter(v=>v.selected).map(v=>({input_id:v.input_id,pin:v.pin}));}
function renderRelationSelections(){
 const box=document.querySelector('#relation-input-selection');if(!box)return;box.replaceChildren();
 if(relationSelections&&relationSelectionProject===activeProject?.id)for(const value of relationSelections.values()){
  const label=relNode('label'),check=document.createElement('input');check.type='checkbox';check.checked=value.selected;
  check.addEventListener('change',()=>{value.selected=check.checked;pendingChatRequest=null;updatePromptInputSummary();});
  label.append(check,document.createTextNode(' '+value.title+' · propojený zdroj'));box.append(label);
 }
 updatePromptInputSummary();
}
function relationPage(id){for(const name of ['relations-overview','relations-editor','relations-review','relations-preview'])document.getElementById(name).hidden=name!==id;}
async function relRequest(action,body){return projectRequest('/v1/project-relations/'+action,{project_id:activeProject.id,...body},120000);}
async function openProjectRelations(){
 if(!activeProject)return;relationProjectChanged();relationPage('relations-overview');relationStatus.textContent='Načítám vztahy a dostupné podklady…';
 if(!relationDialog.open)relationDialog.showModal();await refreshProjectRelations();
}
async function refreshProjectRelations(){
 const root=activeProject?.id,epoch=++relationEpoch;if(!root)return;
 relationOverview=null;relationCatalog=null;
 document.querySelector('#relations-list').replaceChildren();document.querySelector('#relations-sources').replaceChildren();
 document.querySelector('#relations-create').disabled=true;
 try{
  // The two requests are sequential: the backend owns the shared application lane.
  const overview=await relRequest('overview',{}),catalog=await relRequest('sources',{query:''});
  if(root!==activeProject?.id||epoch!==relationEpoch)return;
  relationOverview=overview;relationCatalog=catalog;renderRelationOverview();renderRelationSources();
  relationStatus.textContent='Přehled je aktuální. Potvrzení vazby a výběr podkladů jsou samostatné kroky.';
 }catch(error){if(root===activeProject?.id&&epoch===relationEpoch)relationStatus.textContent=error.message;}
}
function renderRelationOverview(){
 const list=document.querySelector('#relations-list');list.replaceChildren();document.querySelector('#relations-create').disabled=!relationOverview.can_create;
 for(const row of relationOverview.relations){
  const card=relNode('article',undefined,'relations-card');card.dataset.relationId=row.relation_id;
  const orientation=row.type==='relates_to'?'obousměrně':row.orientation==='outgoing'?'tento projekt → další projekt':'další projekt → tento projekt';
  card.append(relNode('h4',row.other_title),relNode('p',`${RELATION_TYPES[row.type]} · ${orientation} · ${RELATION_STATES[row.state]||row.state}`));
  if(row.reason)card.append(relNode('p',row.reason,'relations-note'));
  if(row.can_approve)card.append(relButton('Potvrdit za tento projekt',()=>reviewRelationEvidence(row,false)));
  if(row.can_edit)card.append(relButton(row.state==='revoked'?'Navrhnout novou revizi':'Upravit typ / směr',()=>editProjectRelation(row)));
  if(row.can_revoke)card.append(relButton('Ukončit vazbu za tento projekt',()=>reviewRelationEvidence(row,true)));
  if(row.navigable)card.append(relButton('Otevřít projekt',async()=>{if(!await canLeaveWorkspaceEditors())return;relationDialog.close();await openRegisteredProject(row.other_project_id);}));
  list.append(card);
 }
 if(!relationOverview.relations.length)list.append(relNode('p','Projekt zatím nemá žádné vztahy.','relations-note'));
}
function renderRelationSources(){
 const list=document.querySelector('#relations-sources');list.replaceChildren();if(!relationCatalog)return;
 const query=document.querySelector('#relations-query').value.toLocaleLowerCase();
 const matched=relationCatalog.items.filter(r=>(r.title+' '+r.source_title).toLocaleLowerCase().includes(query));
 for(const row of matched){
  const card=relNode('article',undefined,'relations-card');card.dataset.sourceProjectId=row.source_project_id;card.dataset.artifactId=row.artifact_id;
  card.append(relNode('h4',row.title),relNode('p',`${row.source_title} · ${row.reason} · ${row.inherited?'Zděděné, jen ke čtení':'Vlastní'}`,'relations-note'));
  const source=relationCatalog.sources.find(s=>s.project_id===row.source_project_id);
  if(row.inherited){const why=relNode('details'),summary=relNode('summary','Proč je podklad dostupný');why.append(summary);
   for(const path of source.paths){const scope=path.some(e=>e.type!=='parent_of')?'Pouze publikované výstupy':'Projektová data';
    if(!row.scopes.includes(scope==='Projektová data'?'data':'outputs'))continue;
    why.append(relNode('p',scope+' · '+path.map(e=>RELATION_TYPES[e.type]).join(' → '),'relations-note'));}card.append(why);}
  card.append(relButton('Otevřít jen ke čtení',()=>viewRelationSource(row),!row.available));
  const select=relButton('Použít v zadání',()=>selectRelationSource(row),!row.can_select);select.title=row.can_select?'Výslovně připnout tento text jako vstup AI':'Pro AI jsou nyní dostupné textové podklady s oprávněním zadávat úkoly.';card.append(select);
  if(!row.available)card.append(relNode('p','Cizí reference vyžaduje samostatné ověření původního zdroje.','relations-note'));
  list.append(card);
 }
 if(!matched.length)list.append(relNode('p','V dostupných názvech ani projektech není shoda.','relations-note'));
}
function updateRelationDirection(){const type=document.querySelector('#relations-type').value;
 document.querySelector('#relations-direction-label').hidden=type==='relates_to';
 const options=document.querySelector('#relations-direction').options;
 options[0].textContent=type==='parent_of'?'Tento projekt je rodič':'Tento projekt využívá výstupy dalšího';
 options[1].textContent=type==='parent_of'?'Tento projekt je podprojekt':'Další projekt využívá výstupy tohoto';
 document.querySelector('#relations-direction-help').textContent=type==='parent_of'?'Rodič čte data podprojektu. Data rodiče se směrem dolů nezpřístupní.':type==='depends_on'?'Příjemce využívá jen publikované výstupy poskytovatele, ne jeho interní podklady.':'Oba projekty využívají publikované výstupy druhé strany.';
}
function editProjectRelation(row=null){
 relationEditing=row;relationAttempt=null;relationPage('relations-editor');relationStatus.textContent='';
 document.querySelector('#relations-editor-title').textContent=row?'Změna vztahu':'Nový vztah';
 const other=document.querySelector('#relations-other');other.replaceChildren();
 for(const project of relationOverview.candidates)other.append(new Option(project.title,project.id));
 if(row){if(![...other.options].some(o=>o.value===row.other_project_id))other.append(new Option(row.other_title,row.other_project_id));other.value=row.other_project_id;}
 other.disabled=Boolean(row);document.querySelector('#relations-type').value=row?.type||'parent_of';
 document.querySelector('#relations-direction').value=row?.orientation==='incoming'?'incoming':'outgoing';
 document.querySelector('#relations-reason').value=row?.reason||'';updateRelationDirection();
}
function reviewRelation(result,operationId=null){
 relationPage('relations-review');relationAttempt={result,operationId:operationId||crypto.randomUUID(),projectId:activeProject.id};
 const body=document.querySelector('#relations-review-content');body.replaceChildren();
 const p=result.preview,record=p.record,titles=result.display?.titles||{},name=id=>titles[id]||'Další oprávněný projekt';
 if(record.type)body.append(relNode('p',`${name(record.source_project_id)} → ${name(record.target_project_id)} · ${RELATION_TYPES[record.type]}`),relNode('p',record.reason));
 else body.append(relNode('p',p.mode==='revoke'?'Ukončení vazby za tento projekt':'Souhlas tohoto projektu s přesnou revizí vztahu'));
 body.append(relNode('p','Souhlas zahrnuje i budoucí podklady/výstupy a oprávněné příjemce přes další schválené cesty. Při změně typu nebo směru se stará revize vyřadí a jsou nutné nové souhlasy.'));
 const impact=relNode('details'),summary=relNode('summary','Dopad na dostupnost');impact.append(summary);
 for(const [key,label] of [['activation_adds','Po aktivaci zpřístupní'],['removes','Odebere']])for(const row of p.impact[key])impact.append(relNode('p',`${label}: ${name(row.recipient)} → ${name(row.provider)} · ${row.scope==='data'?'data':'výstupy'}`));
 body.append(impact);document.querySelector('#relations-approved').checked=false;document.querySelector('#relations-confirm').disabled=true;
}
async function reviewRelationEvidence(row,revoke){
 const reason=revoke?prompt('Důvod ukončení vazby:'):null;if(revoke&&!reason?.trim())return;
 const op=crypto.randomUUID();relationStatus.textContent='Připravuji náhled…';
 const result=await relRequest('evidence/preview',{owner_project_id:row.owner_project_id,relation_id:row.relation_id,operation_id:op,revoke,reason});
 reviewRelation(result,op);relationStatus.textContent='Zkontrolujte rozsah před potvrzením.';
}
async function viewRelationSource(row){
 relationStatus.textContent='Načítám připnutý podklad…';const root=activeProject.id,epoch=relationEpoch;
 const view=await relRequest('source/view',{source_project_id:row.source_project_id,artifact_id:row.artifact_id});
 if(root!==activeProject?.id||epoch!==relationEpoch||!relationDialog.open)return;
 relationPage('relations-preview');document.querySelector('#relations-preview-title').textContent=view.title;
 document.querySelector('#relations-preview-origin').textContent=`${row.source_title} · ${row.reason} · jen ke čtení`;
 document.querySelector('#relations-preview-proof').textContent=JSON.stringify(view.pin.source,null,2);
 const box=document.querySelector('#relations-preview-content');box.replaceChildren();const p=view.preview;
 if(p.format==='markdown')renderMarkdown(p.text,box,null,true,row.source_project_id,(pid,id)=>viewRelationSource({...row,source_project_id:pid,artifact_id:id}).catch(e=>relationStatus.textContent=e.message));
 else if(p.format==='image'||p.format==='pdf'){const img=document.createElement('img');img.alt=view.title;img.src=p.image;box.append(img);}
 else box.append(relNode('pre',p.text||p.message||'Náhled tohoto formátu není dostupný.'));
 relationStatus.textContent='Zobrazuje se konkrétní uložená revize; původní podklad se zde neupravuje.';
}
async function selectRelationSource(row){
 if(!await canLeaveWorkspaceEditors())return;
 const root=activeProject.id,epoch=relationEpoch;
 const value=await relRequest('source/pin',{source_project_id:row.source_project_id,artifact_id:row.artifact_id});
 if(root!==activeProject?.id||epoch!==relationEpoch)return;
 relationProjectChanged();relationSelections.set(value.input_id,{...value,selected:true});pendingChatRequest=null;renderRelationSelections();
 relationDialog.close();await navigateMainTab(document.querySelector('#chat-tab'));
 chatOperationStatus.textContent='Podklad je vybraný pro zadání. Odeslání modelu potvrďte zadáním úkolu; před odesláním se znovu ověří jeho dostupnost.';
}
document.querySelector('#relations-close').addEventListener('click',()=>relationDialog.close());
relationDialog.addEventListener('close',()=>{++relationEpoch;relationAttempt=null;});
for(const node of document.querySelectorAll('.relations-back'))node.addEventListener('click',()=>{relationAttempt=null;relationPage('relations-overview');});
document.querySelector('#relations-create').addEventListener('click',()=>editProjectRelation());
document.querySelector('#relations-type').addEventListener('change',updateRelationDirection);
document.querySelector('#relations-query').addEventListener('input',renderRelationSources);
document.querySelector('#relations-refresh').addEventListener('click',refreshProjectRelations);
document.querySelector('#open-project-relations').addEventListener('click',()=>openProjectRelations().catch(e=>relationStatus.textContent=e.message));
document.querySelector('#pick-relation-inputs').addEventListener('click',()=>openProjectRelations().catch(e=>relationStatus.textContent=e.message));
document.querySelector('#relations-editor').addEventListener('submit',async event=>{
 event.preventDefault();const other=document.querySelector('#relations-other').value;if(!other){relationStatus.textContent='Vyberte další projekt, který smíte spravovat.';return;}
 const outgoing=document.querySelector('#relations-direction').value==='outgoing';
 try{const result=await relRequest('proposal/preview',{source_project_id:outgoing?activeProject.id:other,target_project_id:outgoing?other:activeProject.id,
  relation_type:document.querySelector('#relations-type').value,reason:document.querySelector('#relations-reason').value,relation_id:relationEditing?.relation_id||null});reviewRelation(result);relationStatus.textContent='Zkontrolujte rozsah před potvrzením.';}
 catch(error){relationStatus.textContent=error.message;}
});
document.querySelector('#relations-approved').addEventListener('change',event=>document.querySelector('#relations-confirm').disabled=!event.target.checked);
document.querySelector('#relations-confirm').addEventListener('click',async()=>{
 const attempt=relationAttempt;if(!attempt||attempt.projectId!==activeProject?.id)return;
 const button=document.querySelector('#relations-confirm');button.disabled=true;relationStatus.textContent='Ukládám potvrzený krok…';
 try{const p=attempt.result.preview,receipt=await relRequest('confirm',{preview:p,sha256:attempt.result.sha256,operation_id:attempt.operationId});
  if(activeProject?.id!==attempt.projectId)return;
  if(p.project_id===activeProject.id&&activeProject.head===p.heads[activeProject.id]){activeProject.head=receipt.commit_id;document.querySelector('#project-commit').textContent=receipt.commit_id;}
  relationAttempt=null;relationPage('relations-overview');await refreshProjectRelations();
  relationStatus.textContent=p.mode==='propose'?'Návrh byl uložen. Vazba čeká na potvrzení obou projektů.':'Krok byl uložen. Skutečný stav vazby je uveden v přehledu.';
 }catch(error){relationStatus.textContent=error.message+' Při nejistém výsledku ověřte stav; další pokus zachová stejnou operaci.';button.disabled=!document.querySelector('#relations-approved').checked;}
});
renderRelationSelections();
'''
