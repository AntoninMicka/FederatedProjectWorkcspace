# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""XREF-02-B/C: share, attach, open, repin, fork, detach and revoke cross-project references.

The browser never builds a share or reference itself. It shows the exact
server preview and confirms its digest. All text uses textContent.
"""

SHARING_HTML = '''<dialog id="sharing-dialog" aria-labelledby="sharing-heading">
<h2 id="sharing-heading">Sdílení podkladu</h2>
<div id="sharing-body"></div>
<p id="sharing-status" role="status"></p>
<div class="form-actions"><button id="sharing-primary" type="button">Připravit náhled</button><button id="sharing-confirm" type="button" hidden disabled>Potvrdit</button><button id="sharing-close" type="button" class="secondary-button">Zavřít</button></div>
</dialog>'''

SHARING_ATTACH_BUTTON = '<button id="open-sharing-attach" type="button">Připojit z jiného projektu</button>'

SHARING_CSS = '''
#sharing-dialog{width:min(760px,92vw);max-height:88vh;box-sizing:border-box;border:1px solid #bfcdc9;border-radius:14px;padding:20px;color:#213746;overflow:auto}
#sharing-dialog fieldset{border:1px solid #d5e0dd;border-radius:10px;margin:10px 0;padding:10px 12px}
#sharing-dialog label{display:block;margin:6px 0}
#sharing-dialog textarea,#sharing-dialog input[type=text]{width:100%;box-sizing:border-box}
#sharing-dialog .sharing-option{display:flex;gap:8px;align-items:flex-start}
#sharing-dialog .sharing-note{color:#53656f;font-size:13px;margin:2px 0 0}
#sharing-dialog dl,.shared-reference-provenance{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:8px 0}
#sharing-dialog dd,.shared-reference-provenance dd{margin:0;overflow-wrap:anywhere}
.sharing-diff{max-height:320px;overflow:auto;background:#f4f7f6;border-radius:8px;padding:8px;font-size:12px;white-space:pre-wrap}
.shared-reference-actions{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px}
.sidebar-shared-badge{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;background:#27455a;color:#cfe3f1;font-size:11px}
.shared-reference-banner{border:1px solid #9fb9c9;background:#eef5f9;color:#213746;border-radius:10px;padding:10px 12px;margin:0 0 10px}
.shared-reference-banner[data-state="deleted"],.shared-reference-banner[data-state="share-revoked"],.shared-reference-banner[data-state="not-shared"],.shared-reference-banner[data-state="invalid-pin"]{border-color:#c98f8f;background:#fbf0f0}
.shared-reference-banner[data-state="offline-stale"],.shared-reference-banner[data-state="newer-available"]{border-color:#d6b56b;background:#fdf7e8}
'''

SHARING_JS = r'''
const sharingDialog=document.querySelector('#sharing-dialog');
const sharingBody=document.querySelector('#sharing-body'),sharingStatus=document.querySelector('#sharing-status');
const sharingPrimary=document.querySelector('#sharing-primary'),sharingConfirm=document.querySelector('#sharing-confirm');
const SHARING_PURPOSE={share:'Sdílení podkladu',output:'Výstup projektu'};
const SHARING_PRIVACY={public:'Veřejné',project:'V rámci projektu',confidential:'Důvěrné','local-only':'Jen na tomto počítači'};
const SHARED_STATE={current:'Aktuální připnutá revize.',
 'newer-available':'Ve zdroji je novější revize. Zobrazuje se původní připnutá verze; aktualizace vyžaduje výslovné potvrzení.',
 'offline-stale':'Zdroj je nedostupný. Zobrazuje se uložená kopie, kterou nelze ověřit; nelze ji použít pro AI kontext ani kopii.',
 deleted:'Zdrojový podklad byl odstraněn. Původní obsah už nelze načíst.',
 'share-revoked':'Sdílení bylo ve zdrojovém projektu ukončeno. Obsah už nelze načíst; dříve vytvořené vlastní kopie zůstávají.',
 'not-shared':'Podklad už není do tohoto projektu sdílený.',
 'invalid-pin':'Připnutá revize zdroje není dostupná.'};
let sharingFlow=null;
function sharingNode(tag,text,cls){const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=text;if(cls)node.className=cls;return node;}
function sharingList(pairs){const dl=document.createElement('dl');for(const [k,v] of pairs){if(v===undefined||v===null||v==='')continue;dl.append(sharingNode('dt',k),sharingNode('dd',v));}return dl;}
function sharingReset(heading){
 sharingFlow={heading,attempt:null};document.querySelector('#sharing-heading').textContent=heading;
 sharingBody.replaceChildren();sharingStatus.textContent='';sharingPrimary.hidden=false;sharingPrimary.disabled=false;
 sharingPrimary.textContent='Připravit náhled';sharingConfirm.hidden=true;sharingConfirm.disabled=true;
}
document.querySelector('#sharing-close').addEventListener('click',()=>{sharingFlow=null;sharingDialog.close();});
sharingDialog.addEventListener('close',()=>{sharingFlow=null;});
async function sharingOverview(){return projectRequest('/v1/sharing/overview',{project_id:activeProject.id});}
function sharingConfirmStep(display,pairs,run,extra=[]){
 const flow=sharingFlow;sharingBody.replaceChildren(sharingNode('h3','Kontrola před uložením'),sharingList(pairs),...extra);
 const confirm=document.createElement('label');confirm.className='sharing-option';
 const box=document.createElement('input');box.type='checkbox';box.id='sharing-approved';
 confirm.append(box,sharingNode('span','Potvrzuji přesný rozsah, revizi a soukromí uvedené výše.'));sharingBody.append(confirm);
 sharingPrimary.hidden=true;sharingConfirm.hidden=false;sharingConfirm.disabled=true;sharingConfirm.textContent='Potvrdit';
 box.addEventListener('change',()=>{sharingConfirm.disabled=!box.checked;});
 sharingConfirm.onclick=async()=>{
  if(sharingFlow!==flow)return;sharingConfirm.disabled=true;sharingStatus.textContent='Ukládám…';
  // A retried confirmation keeps its operation ID so a lost response cannot duplicate the write.
  flow.attempt=flow.attempt||crypto.randomUUID();
  try{await run(flow.attempt);if(sharingFlow!==flow)return;sharingStatus.textContent='Uloženo.';sharingConfirm.hidden=true;
   const projectId=activeProject.id;await openRegisteredProject(projectId);}
  catch(error){if(sharingFlow===flow){sharingStatus.textContent=error.message;sharingConfirm.disabled=!box.checked;}}
 };
}
async function openShareDialog(item){
 if(!activeProject||activeProject.readOnly)return;
 sharingReset(`Sdílet do projektu · ${item.title}`);const flow=sharingFlow;sharingStatus.textContent='Načítám projekty…';sharingDialog.showModal();
 let overview;try{overview=await sharingOverview();}catch(error){if(sharingFlow===flow)sharingStatus.textContent=error.message;return;}
 if(sharingFlow!==flow)return;sharingStatus.textContent='';
 const existing=overview.shares.filter(row=>row.artifact_id===item.id);
 if(existing.length){
  const box=sharingNode('fieldset');box.append(sharingNode('legend','Dosavadní sdílení'));
  for(const row of existing){
   const targets=row.targets.map(t=>t.title).join(', ')||'žádný dostupný cíl';
   const used=row.usage.map(u=>`${u.project_title}: ${u.title||u.reference_id}`).join('; ')||'zatím nepoužito';
   box.append(sharingList([['Účel',SHARING_PURPOSE[row.purpose]],['Cíle',targets],['Důvod',row.reason],['Použití',used],['Stav',row.revoked?'ukončeno':'aktivní']]));
   if(!row.revoked){const end=sharingNode('button','Ukončit sdílení','secondary-button sharing-revoke');end.type='button';
    end.dataset.shareId=row.share_id;end.addEventListener('click',()=>openRevokeDialog(item,row));box.append(end);}
  }
  sharingBody.append(box);
 }
 const targets=sharingNode('fieldset');targets.append(sharingNode('legend','Cílové projekty'));
 if(!overview.candidates.length)targets.append(sharingNode('p','Nemáte přístup k žádnému dalšímu projektu.','sharing-note'));
 for(const project of overview.candidates){
  const label=document.createElement('label');label.className='sharing-option';
  const box=document.createElement('input');box.type='checkbox';box.value=project.id;box.name='sharing-target';
  label.append(box,sharingNode('span',project.title));targets.append(label);
 }
 targets.append(sharingNode('p','Sdílení se týká jen tohoto podkladu. Přístup k celému projektu se nemění.','sharing-note'));
 const purpose=document.createElement('select');purpose.id='sharing-purpose';
 for(const [value,label] of Object.entries(SHARING_PURPOSE))purpose.append(new Option(label,value));
 const purposeLabel=sharingNode('label','Účel ');purposeLabel.append(purpose);
 const reason=document.createElement('textarea');reason.id='sharing-reason';reason.rows=3;reason.maxLength=1000;
 const reasonLabel=sharingNode('label','Důvod sdílení ');reasonLabel.append(reason);
 sharingBody.append(targets,purposeLabel,reasonLabel);
 sharingPrimary.disabled=!overview.candidates.length;
 sharingPrimary.onclick=async()=>{
  const chosen=[...targets.querySelectorAll('input[name=sharing-target]:checked')].map(box=>box.value);
  if(!chosen.length){sharingStatus.textContent='Vyberte alespoň jeden cílový projekt.';return;}
  if(!reason.value.trim()){sharingStatus.textContent='Uveďte důvod sdílení.';return;}
  sharingPrimary.disabled=true;sharingStatus.textContent='Připravuji náhled…';
  try{
   const offer=await projectRequest('/v1/sharing/share/preview',{project_id:activeProject.id,artifact_id:item.id,targets:chosen,purpose:purpose.value,reason:reason.value});
   if(sharingFlow!==flow)return;sharingStatus.textContent='';const d=offer.display;
   sharingConfirmStep(d,[['Podklad',d.artifact_title],['Zdrojový projekt',d.source_title],['Účel',SHARING_PURPOSE[d.purpose]],
    ['Cíle',d.targets.map(t=>t.title||t.id).join(', ')],['Soukromí',SHARING_PRIVACY[d.privacy]||d.privacy],['Důvod',d.reason],['Náhled SHA-256',offer.sha256]],
    operation=>projectRequest('/v1/sharing/share/confirm',{preview:offer.preview,sha256:offer.sha256,operation_id:operation},120000));
  }catch(error){if(sharingFlow===flow){sharingStatus.textContent=error.message;sharingPrimary.disabled=false;}}
 };
}
async function openAttachDialog(){
 if(!activeProject||activeProject.readOnly)return;
 sharingReset('Připojit podklad z jiného projektu');const flow=sharingFlow;sharingStatus.textContent='Načítám nabídky…';sharingDialog.showModal();
 let overview;try{overview=await sharingOverview();}catch(error){if(sharingFlow===flow)sharingStatus.textContent=error.message;return;}
 if(sharingFlow!==flow)return;sharingStatus.textContent='';
 const offers=sharingNode('fieldset');offers.append(sharingNode('legend','Podklady sdílené do tohoto projektu'));
 if(!overview.offers.length)offers.append(sharingNode('p','Do tohoto projektu zatím nikdo nic nesdílí.','sharing-note'));
 const title=document.createElement('input');title.type='text';title.id='sharing-title';title.maxLength=200;
 for(const offer of overview.offers){
  const label=document.createElement('label');label.className='sharing-option';
  const radio=document.createElement('input');radio.type='radio';radio.name='sharing-offer';radio.value=offer.share_id;
  radio.addEventListener('change',()=>{if(!title.value.trim()||title.dataset.auto==='1'){title.value=offer.artifact_title||'';title.dataset.auto='1';}});
  const text=sharingNode('span');text.append(sharingNode('strong',offer.artifact_title||offer.artifact_id));
  text.append(sharingNode('span',` · ${SHARING_PURPOSE[offer.purpose]} z projektu ${offer.source_title}`));
  text.append(sharingNode('p',`Důvod: ${offer.reason} · Soukromí: ${SHARING_PRIVACY[offer.privacy]||offer.privacy}`+(offer.attached_reference_ids.length?' · již připojeno':''),'sharing-note'));
  label.append(radio,text);offers.append(label);
 }
 title.addEventListener('input',()=>{title.dataset.auto='0';});
 const titleLabel=sharingNode('label','Název v tomto projektu ');titleLabel.append(title);
 const reason=document.createElement('textarea');reason.id='sharing-reason';reason.rows=3;reason.maxLength=1000;
 const reasonLabel=sharingNode('label','Důvod použití ');reasonLabel.append(reason);
 sharingBody.append(offers,titleLabel,reasonLabel,sharingNode('p','Připojí se konkrétní aktuální revize jen ke čtení. Novější revize se pouze nabídne.','sharing-note'));
 sharingPrimary.disabled=!overview.offers.length;
 sharingPrimary.onclick=async()=>{
  const chosen=offers.querySelector('input[name=sharing-offer]:checked');const offer=overview.offers.find(o=>o.share_id===chosen?.value);
  if(!offer){sharingStatus.textContent='Vyberte sdílený podklad.';return;}
  if(!title.value.trim()||!reason.value.trim()){sharingStatus.textContent='Vyplňte název a důvod použití.';return;}
  sharingPrimary.disabled=true;sharingStatus.textContent='Připravuji náhled…';
  try{
   const attach=await projectRequest('/v1/sharing/attach/preview',{project_id:activeProject.id,source_project_id:offer.source_project_id,share_id:offer.share_id,title:title.value.trim(),reason:reason.value});
   if(sharingFlow!==flow)return;sharingStatus.textContent='';const d=attach.display;
   sharingConfirmStep(d,[['Podklad',d.artifact_title],['Zdrojový projekt',d.source_title],['Účel',SHARING_PURPOSE[d.purpose]],['Důvod sdílení',d.share_reason],
    ['Název zde',d.title],['Důvod použití',d.reason],['Připnutá revize',d.commit_id],['Soubor',d.path],['SHA-256 obsahu',d.sha256],
    ['Soukromí',SHARING_PRIVACY[d.privacy]||d.privacy],['Náhled SHA-256',attach.sha256]],
    operation=>projectRequest('/v1/sharing/attach/confirm',{preview:attach.preview,sha256:attach.sha256,operation_id:operation},120000));
  }catch(error){if(sharingFlow===flow){sharingStatus.textContent=error.message;sharingPrimary.disabled=false;}}
 };
}
document.querySelector('#open-sharing-attach').addEventListener('click',()=>openAttachDialog());
async function sharingReviewFlow(heading,path,request,describe){
 if(!activeProject||activeProject.readOnly)return;
 sharingReset(heading);const flow=sharingFlow;sharingPrimary.hidden=true;sharingStatus.textContent='Připravuji náhled…';
 if(!sharingDialog.open)sharingDialog.showModal();
 try{
  const result=await projectRequest(path+'/preview',request);if(sharingFlow!==flow)return;sharingStatus.textContent='';
  const [pairs,extra]=describe(result.display,result);
  sharingConfirmStep(result.display,[...pairs,['Náhled SHA-256',result.sha256]],
   operation=>projectRequest(path+'/confirm',{preview:result.preview,sha256:result.sha256,operation_id:operation},120000),extra);
 }catch(error){if(sharingFlow===flow)sharingStatus.textContent=error.message;}
}
function openRepinDialog(id,title){
 return sharingReviewFlow(`Aktualizovat · ${title}`,'/v1/sharing/repin',{project_id:activeProject.id,reference_id:id},d=>{
  const diff=d.diff?sharingNode('pre',d.diff.lines.join('\n')+(d.diff.truncated?'\n…':''),'sharing-diff')
   :sharingNode('p','Obsah není text; porovnejte velikost a SHA-256.','sharing-note');
  return [[['Připnutá revize',d.before.commit_id],['Aktuální revize',d.after.commit_id],
   ['Název ve zdroji',d.before.title===d.after.title?d.after.title:`${d.before.title} → ${d.after.title}`],
   ['Velikost',`${d.before.size} → ${d.after.size} B`],['SHA-256 nyní',d.before.sha256],['SHA-256 po aktualizaci',d.after.sha256],
   ['Soukromí po aktualizaci',SHARING_PRIVACY[d.privacy]||d.privacy]],
   [sharingNode('h3','Porovnání'),diff,sharingNode('p','Dříve připnuté vstupy hotových úkolů, zpráv a manifestů se nemění; aktualizace platí jen pro tuto referenci.','sharing-note')]];
 });
}
function openForkDialog(id,title){
 return sharingReviewFlow(`Vlastní kopie · ${title}`,'/v1/sharing/fork',{project_id:activeProject.id,reference_id:id},d=>
  [[['Podklad',d.title],['Kopírovaná revize',d.commit_id],['Soubor',d.path],['Soukromí kopie',SHARING_PRIVACY[d.privacy]||d.privacy]],
   [sharingNode('p','Vznikne nový upravitelný podklad tohoto projektu s trvalým záznamem původu. Ukončení sdílení ve zdroji jej zpětně neodstraní.','sharing-note')]]);
}
function openDetachDialog(id,title){
 return sharingReviewFlow(`Odebrat z projektu · ${title}`,'/v1/sharing/detach',{project_id:activeProject.id,reference_id:id},d=>
  [[['Reference',d.title],['Připnutá revize',d.commit_id],['Soubor',d.path]],
   [sharingNode('p','Odebere se jen odkaz v tomto projektu. Zdrojový podklad, jeho sdílení i historie reference zůstávají.','sharing-note')]]);
}
function openRevokeDialog(item,row){
 return sharingReviewFlow(`Ukončit sdílení · ${item.title}`,'/v1/sharing/revoke',{project_id:activeProject.id,share_id:row.share_id},d=>
  [[['Podklad',d.artifact_title],['Účel',SHARING_PURPOSE[d.purpose]],['Důvod sdílení',d.reason],['Dostupné cíle',d.targets.map(t=>t.title).join(', ')||'—']],
   [sharingNode('p','Ukončení platí pro všechny cílové projekty tohoto sdílení a je konečné: podklad už nepůjde připojit, zobrazit ani zkopírovat. Kopie, které si cílové projekty již legitimně vytvořily, tím zpětně odstranit nelze. Záznam sdílení zůstává v historii.','sharing-note')]]);
}
async function openSharedReference(id){
 if(!activeProject||!await canLeaveWorkspaceEditors())return;
 showWorkspacePage(projectView);const project=activeProject;
 clearPreview();selectedArtifact=id;
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current',String(button.dataset.id===id));
 const request=previewRequest;selectMainTab(document.querySelector('#preview-tab'));previewStatus.textContent='Načítám sdílený podklad…';
 try{
  const view=await projectRequest('/v1/sharing/reference/view',{project_id:project.id,reference_id:id});
  if(request!==previewRequest||activeProject!==project)return;
  document.querySelector('#preview-title').textContent=view.title;
  const banner=sharingNode('div',null,'shared-reference-banner');banner.dataset.state=view.state;banner.setAttribute('role','note');
  banner.append(sharingNode('strong','Sdílený podklad · jen ke čtení. '),sharingNode('span',SHARED_STATE[view.state]||view.state));
  const share=view.share||{};
  const provenance=sharingList([['Zdrojový projekt',view.source_title||'nedostupný'],['Podklad ve zdroji',view.source.artifact_id],
   ['Připnutá revize',view.source.commit_id],['Soubor',view.source.path],['SHA-256 obsahu',view.source.sha256],
   ['Soukromí',SHARING_PRIVACY[view.privacy]||view.privacy],['Důvod použití',share.reason],['Připojil',share.attached_by],['Sdílel',share.originator_id],
   ['Formát reference',view.share?null:'starší reference bez záznamu sdílení']]);
  provenance.className='shared-reference-provenance';previewContent.append(banner,provenance);
  if(!project.readOnly){
   const actions=sharingNode('div',null,'shared-reference-actions');
   const action=(label,run)=>{const button=sharingNode('button',label,'secondary-button');button.type='button';button.addEventListener('click',run);actions.append(button);};
   if(view.state==='newer-available')action('Porovnat a aktualizovat',()=>openRepinDialog(id,view.title));
   if(view.state==='current'||view.state==='newer-available')action('Vytvořit vlastní kopii',()=>openForkDialog(id,view.title));
   action('Odebrat z projektu',()=>openDetachDialog(id,view.title));
   previewContent.append(actions);
  }
  const preview=view.preview;
  if(preview?.format==='markdown')renderMarkdown(preview.text);
  else if(preview?.format==='json'){previewContent.append(sharingNode('pre',preview.text));}
  else if(preview&&(preview.format==='image'||preview.format==='pdf')){const image=document.createElement('img');image.alt=view.title;image.src=preview.image;previewContent.append(image);}
  previewStatus.textContent=preview?.message||'';
  if(typeof syncPageLayout==='function')syncPageLayout();
 }catch(error){if(request===previewRequest)previewStatus.textContent=error.message;}
}
'''
