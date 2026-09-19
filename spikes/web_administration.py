# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Administration panel for the existing HTTPS UI."""

ADMIN_HTML = '''<section id="administration" class="settings-card" hidden aria-label="Správa uzlu">
<p id="admin-status" role="status"></p><p id="admin-node"></p>
<section id="admin-users-panel" role="tabpanel" aria-labelledby="settings-users-tab" hidden><h2>Lokální účty</h2><p>Přihlašujete se jen ke svému účtu na tomto uzlu. Hesla a přístupové klíče se mezi uzly nepřenášejí.</p><form id="admin-user-create"><label>Jméno <input name="name" required maxlength="200"></label>
<label>Role na tomto uzlu <select name="role"><option value="member">Člen</option><option value="node-admin">Správce uzlu</option><option value="federation-admin">Správce federace</option></select></label>
<button>Vytvořit uživatele</button></form><div class="admin-table-wrap"><table class="admin-table"><caption>Účty tohoto uzlu</caption><thead><tr><th scope="col">Uživatel a oprávnění</th></tr></thead><tbody id="admin-users"></tbody></table></div>
<div id="admin-key-box" hidden><p>Nový přístupový klíč se zobrazí pouze teď. Předejte jej uživateli bezpečnou cestou.</p><input id="admin-issued-key" readonly aria-label="Nový přístupový klíč"><button id="admin-key-hide" type="button">Skrýt klíč</button></div></section>
<section id="admin-federation" role="tabpanel" aria-labelledby="settings-federation-tab" hidden><h2>Federace</h2><p>Schválení eviduje důvěru v uzel. Mapování účtů vyžaduje podepsané potvrzení obou uzlů a neumožňuje přihlášení cizím klíčem.</p><p id="admin-signing-identity"></p>
<form id="admin-peer-create"><label>Jméno uzlu <input name="name" required maxlength="200"></label>
<label>Node UUID <input name="node_id" required></label><label>HTTPS adresa <input name="endpoint" type="url" required></label>
<label>SHA-256 otisk veřejného klíče, ověřený mimo toto spojení <input name="fingerprint" required pattern="[a-fA-F0-9]{64}"></label><button>Přidat uzel ke schválení</button></form><div class="admin-table-wrap"><table class="admin-table"><caption>Federované uzly</caption><thead><tr><th scope="col">Uzel a důvěra</th></tr></thead><tbody id="admin-peers"></tbody></table></div>
<h3>Mapování vlastních účtů</h3><form id="admin-mapping-create"><label>Místní účet <select name="local_user_id" required></select></label><label>Schválený uzel <select name="peer_node_id" required></select></label><label>UUID vlastního účtu na druhém uzlu <input name="peer_user_id" required></label><fieldset id="admin-mapping-projects"><legend>Rozsah projektů</legend></fieldset><button>Navrhnout mapování</button></form>
<div class="admin-table-wrap"><table class="admin-table"><caption>Oboustranné mapování</caption><thead><tr><th scope="col">Účty, rozsah a potvrzení</th></tr></thead><tbody id="admin-mappings"></tbody></table></div>
<label>Podepsané potvrzení nebo odvolání pro druhý uzel <textarea id="admin-mapping-export" readonly></textarea></label>
<form id="admin-mapping-import"><label>Podepsané potvrzení nebo odvolání z druhého uzlu <textarea name="envelope" required maxlength="4096"></textarea></label><button>Ověřit a přijmout</button></form></section></section>'''

ADMIN_CSS = '''
#administration{color:#213632}
#administration label{display:block;margin:12px 0}#administration input,#administration select{box-sizing:border-box;max-width:100%;padding:8px}
.admin-entry{border-top:1px solid #c9d5d2;padding:16px 0}.admin-entry button{margin:6px}
.admin-table-wrap{overflow-x:auto}.admin-table{border-collapse:collapse;width:100%;text-align:left}.admin-table caption{text-align:left;font-weight:bold;margin:14px 0}.admin-table th,.admin-table td{padding:12px;border-bottom:1px solid #c9d5d2}
#administration textarea{display:block;box-sizing:border-box;width:100%;min-height:90px;padding:8px}
#admin-issued-key{width:100%;font-family:monospace}#admin-status{white-space:pre-wrap;position:sticky;top:0;z-index:8;padding:12px;background:#e7f0ec;color:#213632;border:1px solid #a9bfb5;border-radius:6px}#admin-status:empty{display:none}#admin-status[role=alert]{background:#fff0e9;color:#7a281a;border-color:#c98470}
@media(max-width:600px){#administration{padding:14px}}
'''

ADMIN_JS = '''
let administrationState=null;
const adminPanel=document.querySelector('#administration');
const adminStatus=document.querySelector('#admin-status');
function showAdminStatus(message,error=false){adminStatus.textContent=message;adminStatus.setAttribute('role',error?'alert':'status');}
adminPanel.addEventListener('invalid',event=>{event.preventDefault();showAdminStatus('Opravte pole: '+(event.target.closest('label')?.textContent.trim() || event.target.name)+'. '+event.target.validationMessage,true);event.target.setAttribute('aria-invalid','true');event.target.focus();},true);
adminPanel.addEventListener('input',event=>event.target.removeAttribute('aria-invalid'));
let adminTab='users';
function selectAdminTab(tab){if(tab==='federation'&&!administrationState?.federation_admin)return;adminTab=tab;adminPanel.hidden=false;selectSettingsTab(document.querySelector('#settings-'+tab+'-tab'));}
async function openAdministration(tab){
 hideIssuedKey();showAdminStatus('Načítám…');adminPanel.hidden=false;
 try{administrationState=await adminRequest({action:'list'});renderAdministration();selectAdminTab(tab);showAdminStatus('');}
 catch(error){selectSettingsTab(document.querySelector('#settings-'+tab+'-tab'));showAdminStatus(error.message || 'Správu se nepodařilo načíst.',true);}
}
for(const name of ['users','federation'])document.querySelector('#settings-'+name+'-tab').onclick=()=>openAdministration(name);
function hideIssuedKey(){document.querySelector('#admin-issued-key').value='';document.querySelector('#admin-key-box').hidden=true;}
function adminElement(tag,text){const element=document.createElement(tag);element.textContent=text;return element;}
async function adminRequest(request){
 const response=await fetch('/v1/administration',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 const result=await response.json();if(!response.ok)throw new Error(result.error || 'Správa není dostupná.');return result;
}
async function adminChange(request){
 hideIssuedKey();showAdminStatus('Ukládám...');
 if(!administrationState){showAdminStatus('Správa není načtená. Zavřete ji a otevřete znovu.',true);return;}
 try{administrationState=await adminRequest({...request,expected_commit:administrationState.commit_id});renderAdministration();
  if(administrationState.access_key){document.querySelector('#admin-issued-key').value=administrationState.access_key;document.querySelector('#admin-key-box').hidden=false;delete administrationState.access_key;}
  if(administrationState.mapping_envelope){document.querySelector('#admin-mapping-export').value=JSON.stringify(administrationState.mapping_envelope);delete administrationState.mapping_envelope;}
  showAdminStatus('Uloženo.');
 }catch(error){showAdminStatus((error.message || 'Požadavek selhal.')+' Zavřete a znovu otevřete správu pro načtení aktuálního stavu.',true);}
}
function renderAdministration(){
 const state=administrationState;document.querySelector('#admin-node').textContent='Identita tohoto uzlu: '+state.node_id;
 document.querySelector('#settings-federation-tab').hidden=!state.federation_admin;
 document.querySelector('#admin-user-create').hidden=state.deployment==='desktop';
 selectAdminTab(state.federation_admin?adminTab:'users');
 document.querySelector('#admin-signing-identity').textContent=state.mapping_identity?'Otisk klíče tohoto uzlu: '+state.mapping_identity.fingerprint:'';
 document.querySelector('#admin-user-create option[value="federation-admin"]').disabled=!state.federation_admin;
 const users=document.querySelector('#admin-users');users.replaceChildren();
 for(const user of state.users){
  const tableRow=document.createElement('tr');const row=adminElement('td','');tableRow.append(row);row.className='admin-entry';row.append(adminElement('strong',user.name),adminElement('p',user.id+' · domovský uzel '+user.home_node_id));
  if(state.deployment==='desktop'){row.append(adminElement('p','Jediná lokální identita uživatele, pod kterým běží aplikace.'));users.append(tableRow);continue;}
  const role=document.createElement('select');for(const [value,title] of [['member','Člen'],['node-admin','Správce uzlu'],['federation-admin','Správce federace']]){const option=adminElement('option',title);option.value=value;option.disabled=value==='federation-admin'&&!state.federation_admin;role.append(option);}role.value=user.node_role;role.setAttribute('aria-label','Role '+user.name);row.append(role);
  const memberships=new Map();row.append(adminElement('p','Přístup k projektům'));
  for(const project of state.projects || []){const projectLabel=adminElement('label',project.title+' ');const select=document.createElement('select');for(const [value,title] of [['','Bez přístupu'],['reader','Čtenář'],['reviewer','Recenzent'],['editor','Editor'],['project-admin','Správce projektu']]){const option=adminElement('option',title);option.value=value;select.append(option);}select.value=user.memberships[project.id] || '';memberships.set(project.id,select);projectLabel.append(select);row.append(projectLabel);}
  const active=document.createElement('input');active.type='checkbox';active.checked=user.active;const activeLabel=adminElement('label','Aktivní účet ');activeLabel.append(active);row.append(activeLabel);
  const save=adminElement('button','Uložit oprávnění');save.type='button';save.onclick=()=>{const entries=Object.entries(user.memberships).filter(([id])=>!memberships.has(id));for(const [id,select] of memberships)if(select.value)entries.push([id,select.value]);adminChange({action:'update-user',user_id:user.id,node_role:role.value,active:active.checked,memberships:Object.fromEntries(entries)});};
  const rotate=adminElement('button','Nový klíč');rotate.type='button';rotate.onclick=()=>adminChange({action:'rotate-key',user_id:user.id});row.append(save,rotate);users.append(tableRow);
 }
 const peers=document.querySelector('#admin-peers');peers.replaceChildren();for(const peer of state.peers){const tableRow=document.createElement('tr');const row=adminElement('td','');tableRow.append(row);row.className='admin-entry';row.append(adminElement('strong',peer.name),adminElement('p',peer.id+' · '+peer.endpoint),adminElement('p','Otisk: '+peer.fingerprint),adminElement('p','Důvěra: '+({pending:'čeká na schválení',approved:'schválená',revoked:'odvolaná'}[peer.trust])));for(const [trust,title] of [['approved','Schválit důvěru'],['revoked','Odvolat důvěru']]){const button=adminElement('button',title);button.type='button';button.onclick=()=>{if(trust==='approved'&&!confirm('Ověřili jste UUID a otisk veřejného klíče tohoto uzlu nezávislou cestou?'))return;adminChange({action:'set-trust',node_id:peer.id,trust});};row.append(button);}peers.append(tableRow);}
 const form=document.querySelector('#admin-mapping-create');for(const [name,items] of [['local_user_id',state.users.filter(u=>u.active)],['peer_node_id',state.peers.filter(p=>p.trust==='approved')]]){const select=form.elements[name];select.replaceChildren();for(const item of items){const option=adminElement('option',item.name);option.value=item.id;select.append(option);}}
 const projects=document.querySelector('#admin-mapping-projects');projects.replaceChildren(adminElement('legend','Rozsah projektů'));for(const project of state.projects || []){const label=adminElement('label',project.title+' ');const input=document.createElement('input');input.type='checkbox';input.value=project.id;label.append(input);projects.append(label);}
 const mappings=document.querySelector('#admin-mappings');mappings.replaceChildren();for(const mapping of state.mappings || []){const tableRow=document.createElement('tr');const cell=document.createElement('td');tableRow.append(cell);cell.append(adminElement('p',mapping.spec.accounts.map(a=>a.node_id+' / '+a.user_id).join(' ↔ ')),adminElement('p','Projekty: '+mapping.spec.project_ids.map(id=>(state.projects || []).find(p=>p.id===id)?.title || id).join(', ')),adminElement('p',mapping.revocation?'Odvoláno':mapping.active?'Potvrzeno oběma stranami':'Čeká na oboustranné potvrzení ('+Object.keys(mapping.confirmations).length+'/2)'));if(!mapping.revocation){for(const [action,title] of [['confirm-mapping','Potvrdit za tento uzel a vydat soubor'],['revoke-mapping','Odvolat a vydat soubor']]){const button=adminElement('button',title);button.type='button';button.onclick=()=>adminChange({action,mapping_id:mapping.spec.id});cell.append(button);}}mappings.append(tableRow);}
 for(const [index,mapping] of (state.mappings || []).entries()){const saved=mapping.revocation || mapping.confirmations[state.node_id];if(saved){const button=adminElement('button','Zobrazit uložený podepsaný soubor');button.type='button';button.onclick=()=>{document.querySelector('#admin-mapping-export').value=JSON.stringify(saved);};mappings.children[index].firstChild.append(button);}}
}
document.addEventListener('settingsclosed',()=>{hideIssuedKey();administrationState=null;adminPanel.hidden=true;document.querySelector('#admin-users').replaceChildren();document.querySelector('#admin-peers').replaceChildren();document.querySelector('#admin-mappings').replaceChildren();document.querySelector('#admin-mapping-export').value='';});
document.querySelector('#admin-key-hide').onclick=hideIssuedKey;
document.querySelector('#admin-user-create').onsubmit=event=>{event.preventDefault();const fields=new FormData(event.target);adminChange({action:'create-user',name:fields.get('name'),node_role:fields.get('role')});};
document.querySelector('#admin-peer-create').onsubmit=event=>{event.preventDefault();const fields=new FormData(event.target);adminChange({action:'add-peer',name:fields.get('name'),node_id:fields.get('node_id'),endpoint:fields.get('endpoint'),fingerprint:fields.get('fingerprint')});};
document.querySelector('#admin-mapping-create').onsubmit=event=>{event.preventDefault();const fields=new FormData(event.target);const project_ids=Array.from(document.querySelectorAll('#admin-mapping-projects input:checked'),i=>i.value).sort();if(!project_ids.length){showAdminStatus('Vyberte alespoň jeden projekt pro mapování.',true);return;}adminChange({action:'propose-mapping',local_user_id:fields.get('local_user_id'),peer_node_id:fields.get('peer_node_id'),peer_user_id:fields.get('peer_user_id'),project_ids});};
document.querySelector('#admin-mapping-import').onsubmit=event=>{event.preventDefault();try{const envelope=JSON.parse(new FormData(event.target).get('envelope'));adminChange({action:'import-mapping',envelope});}catch(error){showAdminStatus('Potvrzení musí být platný JSON.',true);}};
'''
