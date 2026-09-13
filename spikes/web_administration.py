# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Administration panel for the existing HTTPS UI."""

ADMIN_HTML = '''<button id="administration-open" type="button">Uživatelé a federace</button>
<dialog id="administration"><div class="admin-header"><h2>Správa uzlu</h2><button id="administration-close" type="button">Zavřít</button></div>
<p id="admin-status" role="status"></p><p id="admin-node"></p>
<section><h3>Uživatelé</h3><form id="admin-user-create"><label>Jméno <input name="name" required maxlength="200"></label>
<label>Role na tomto uzlu <select name="role"><option value="member">Člen</option><option value="node-admin">Správce uzlu</option><option value="federation-admin">Správce federace</option></select></label>
<button>Vytvořit uživatele</button></form><div id="admin-users"></div>
<div id="admin-key-box" hidden><p>Nový přístupový klíč se zobrazí pouze teď. Předejte jej uživateli bezpečnou cestou.</p><input id="admin-issued-key" readonly aria-label="Nový přístupový klíč"><button id="admin-key-hide" type="button">Skrýt klíč</button></div></section>
<section id="admin-federation"><h3>Federace</h3><p>Schválení eviduje důvěru v uzel. Síťové spojení a synchronizace zatím nejsou zapojené.</p>
<form id="admin-peer-create"><label>Jméno uzlu <input name="name" required maxlength="200"></label>
<label>Node UUID <input name="node_id" required></label><label>HTTPS adresa <input name="endpoint" type="url" required></label>
<label>SHA-256 otisk veřejného klíče, ověřený mimo toto spojení <input name="fingerprint" required pattern="[a-fA-F0-9]{64}"></label><button>Přidat uzel ke schválení</button></form><div id="admin-peers"></div></section></dialog>'''

ADMIN_CSS = '''
#administration-open{display:none;position:fixed;bottom:12px;left:12px;z-index:4}
body.authenticated #administration-open:not([hidden]){display:block}
#administration{width:min(900px,92vw);max-height:85vh;overflow:auto;border:1px solid #adc0bf;border-radius:14px;padding:24px;background:#f5f8f7;color:#213632}
#administration::backdrop{background:rgba(10,30,27,.55)}
.admin-header{display:flex;align-items:center;justify-content:space-between;gap:16px}
#administration label{display:block;margin:12px 0}#administration input,#administration select{box-sizing:border-box;max-width:100%;padding:8px}
.admin-entry{border-top:1px solid #c9d5d2;padding:16px 0}.admin-entry button{margin:6px}
#admin-issued-key{width:100%;font-family:monospace}#admin-status{white-space:pre-wrap}
@media(max-width:600px){#administration{padding:14px}#administration-open{font-size:11px;bottom:6px}.admin-header h2{font-size:20px}}
'''

ADMIN_JS = '''
let administrationState=null;
const adminDialog=document.querySelector('#administration');
const adminStatus=document.querySelector('#admin-status');
function hideIssuedKey(){document.querySelector('#admin-issued-key').value='';document.querySelector('#admin-key-box').hidden=true;}
function adminElement(tag,text){const element=document.createElement(tag);element.textContent=text;return element;}
async function adminRequest(request){
 const response=await fetch('/v1/administration',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 const result=await response.json();if(!response.ok)throw new Error(result.error || 'Správa není dostupná.');return result;
}
async function adminChange(request){
 hideIssuedKey();adminStatus.textContent='Ukládám...';
 try{administrationState=await adminRequest({...request,expected_commit:administrationState.commit_id});renderAdministration();
  if(administrationState.access_key){document.querySelector('#admin-issued-key').value=administrationState.access_key;document.querySelector('#admin-key-box').hidden=false;delete administrationState.access_key;}
  adminStatus.textContent='Uloženo.';
 }catch(error){adminStatus.textContent=error.message+' Zavřete a znovu otevřete správu pro načtení aktuálního stavu.';}
}
function renderAdministration(){
 const state=administrationState;document.querySelector('#admin-node').textContent='Identita tohoto uzlu: '+state.node_id;
 document.querySelector('#admin-federation').hidden=!state.federation_admin;
 document.querySelector('#admin-user-create option[value="federation-admin"]').disabled=!state.federation_admin;
 const users=document.querySelector('#admin-users');users.replaceChildren();
 for(const user of state.users){
  const row=adminElement('div','');row.className='admin-entry';row.append(adminElement('strong',user.name),adminElement('p',user.id+' · domovský uzel '+user.home_node_id));
  const role=document.createElement('select');for(const [value,title] of [['member','Člen'],['node-admin','Správce uzlu'],['federation-admin','Správce federace']]){const option=adminElement('option',title);option.value=value;option.disabled=value==='federation-admin'&&!state.federation_admin;role.append(option);}role.value=user.node_role;role.setAttribute('aria-label','Role '+user.name);row.append(role);
  const memberships=new Map();row.append(adminElement('p','Přístup k projektům'));
  for(const project of state.projects || []){const projectLabel=adminElement('label',project.title+' ');const select=document.createElement('select');for(const [value,title] of [['','Bez přístupu'],['reader','Čtenář'],['reviewer','Recenzent'],['editor','Editor'],['project-admin','Správce projektu']]){const option=adminElement('option',title);option.value=value;select.append(option);}select.value=user.memberships[project.id] || '';memberships.set(project.id,select);projectLabel.append(select);row.append(projectLabel);}
  const active=document.createElement('input');active.type='checkbox';active.checked=user.active;const activeLabel=adminElement('label','Aktivní účet ');activeLabel.append(active);row.append(activeLabel);
  const save=adminElement('button','Uložit oprávnění');save.type='button';save.onclick=()=>{const entries=Object.entries(user.memberships).filter(([id])=>!memberships.has(id));for(const [id,select] of memberships)if(select.value)entries.push([id,select.value]);adminChange({action:'update-user',user_id:user.id,node_role:role.value,active:active.checked,memberships:Object.fromEntries(entries)});};
  const rotate=adminElement('button','Nový klíč');rotate.type='button';rotate.onclick=()=>adminChange({action:'rotate-key',user_id:user.id});row.append(save,rotate);users.append(row);
 }
 const peers=document.querySelector('#admin-peers');peers.replaceChildren();for(const peer of state.peers){const row=adminElement('div','');row.className='admin-entry';row.append(adminElement('strong',peer.name),adminElement('p',peer.id+' · '+peer.endpoint),adminElement('p','Otisk: '+peer.fingerprint),adminElement('p','Důvěra: '+({pending:'čeká na schválení',approved:'schválená',revoked:'odvolaná'}[peer.trust])));for(const [trust,title] of [['approved','Schválit důvěru'],['revoked','Odvolat důvěru']]){const button=adminElement('button',title);button.type='button';button.onclick=()=>{if(trust==='approved'&&!confirm('Ověřili jste UUID a otisk veřejného klíče tohoto uzlu nezávislou cestou?'))return;adminChange({action:'set-trust',node_id:peer.id,trust});};row.append(button);}peers.append(row);}
}
document.querySelector('#administration-open').onclick=async()=>{hideIssuedKey();adminDialog.showModal();adminStatus.textContent='Načítám...';try{administrationState=await adminRequest({action:'list'});renderAdministration();adminStatus.textContent='';}catch(error){adminStatus.textContent=error.message;}};
document.querySelector('#administration-close').onclick=()=>adminDialog.close();
adminDialog.addEventListener('close',()=>{hideIssuedKey();administrationState=null;document.querySelector('#admin-users').replaceChildren();document.querySelector('#admin-peers').replaceChildren();});
document.querySelector('#admin-key-hide').onclick=hideIssuedKey;
document.querySelector('#admin-user-create').onsubmit=event=>{event.preventDefault();const fields=new FormData(event.target);adminChange({action:'create-user',name:fields.get('name'),node_role:fields.get('role')});};
document.querySelector('#admin-peer-create').onsubmit=event=>{event.preventDefault();const fields=new FormData(event.target);adminChange({action:'add-peer',name:fields.get('name'),node_id:fields.get('node_id'),endpoint:fields.get('endpoint'),fingerprint:fields.get('fingerprint')});};
'''
