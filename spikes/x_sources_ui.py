# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local X subscriptions and budget; no API dispatch on opening the UI."""
HTML='''<details id="x-sources" hidden><summary>X / Twitter — neověřený PoC, placené API</summary>
<p>Odběry a token jsou pouze na tomto uzlu. Otevření ani uložení nastavení nevolá X API.
Načítání je ruční z detailu zdroje projektu. Příspěvky jsou nedůvěryhodné signály, nikoliv potvrzené události.</p>
<p><a href="https://docs.x.com/x-api/getting-started/pricing" target="_blank" rel="noopener noreferrer">Aktuální ceny X API</a> · správu seznamů na X, stream ani archiv tento PoC nepodporuje.</p>
<p id="x-sources-status" role="status"></p><button id="x-sources-reload" type="button">Obnovit místní nastavení</button>
<form id="x-settings-form">
<label>Bearer token (prázdné = zachovat uložený)<input name="token" type="password" autocomplete="new-password" maxlength="8192"></label>
<label>Měsíční místní limit rezervací v USD<input name="budget" type="number" min="0.01" step="0.01" value="10" required></label>
<label>Cena za přečtený příspěvek v USD<input name="price" type="number" min="0.000001" step="0.000001" value="0.005" required></label>
<label>Datum kontroly ceníku<input name="price_review" type="date" value="2026-11-16" required></label>
<label>Příspěvků na stránku<input name="max_results" type="number" min="10" max="100" value="10" required></label>
<label>Nejvýše stránek na jedno ruční načtení<input name="max_pages" type="number" min="1" max="5" value="1" required></label>
<label><input name="enabled" type="checkbox">Povolit ruční placená načtení na tomto uzlu</label>
<p>Rezervuje se cena za maximální počet příspěvků. Nejasný nebo neúplný požadavek rezervaci nevrací.
Jde o místní horní odhad podle zadané sazby, nikoliv vyúčtování X; nastavte také limit v konzoli poskytovatele.</p>
<button type="submit">Uložit nastavení X</button></form>
<h3>Místní odběry</h3><button id="x-subscription-new" type="button">Přidat odběr</button><div id="x-subscription-list"></div>
<form id="x-subscription-form" hidden><h4>Odběr X</h4>
<label>Název<input name="name" maxlength="200" required></label>
<label>Typ<select name="kind"><option value="account">Příspěvky účtu podle číselného ID</option><option value="recent-search">Hledání za posledních 7 dnů</option></select></label>
<label>Číselné ID účtu / hledaný dotaz<input name="value" maxlength="512" required></label>
<label>První okno načtení v hodinách<input name="lookback_hours" type="number" min="1" max="167" value="24" required></label>
<label>Uchování surového obsahu ve dnech<input name="retention_days" type="number" min="1" max="30" value="7" required></label>
<label>Posouzené podmínky přístupu, licence a odstranění<input name="terms" maxlength="4000" required></label>
<label><input name="enabled" type="checkbox">Odběr povolený pro ruční načtení</label>
<button type="submit">Uložit odběr</button><button id="x-subscription-cancel" type="button">Zrušit</button></form>
<h3>Poslední požadavky a rezervace</h3><div id="x-request-list"></div>
<form id="x-forget-form"><label>ID smazaného nebo omezeného příspěvku<input name="post_id" inputmode="numeric" pattern="[0-9]{1,19}" required></label>
<p>Odstraní surový text z tohoto uzlu a zablokuje známé místní verze. Odvozené zprávy, vzdálené uzly a zálohy vyžadují samostatné posouzení.</p>
<button type="submit">Odstranit příspěvek z místních dat</button></form></details>'''
CSS='''#x-sources{margin:1.5rem 0;padding:1rem;border:1px solid #c7d4dc;border-radius:.5rem}
#x-sources label{display:block;margin:.6rem 0}#x-sources input:not([type=checkbox]),#x-sources select{display:block;width:100%;box-sizing:border-box}
#x-sources button{margin:.3rem .5rem .3rem 0}#x-sources td{overflow-wrap:anywhere}'''
JS=r'''
let xSourcesState=null,xSourcesBusy=false,xSourcesDirty=false,xSubscriptionId=null;
const xSettings=document.querySelector('#x-settings-form'),xSubscription=document.querySelector('#x-subscription-form');
function xStatus(message){document.querySelector('#x-sources-status').textContent=message;}
function xText(tag,value){const node=document.createElement(tag);node.textContent=value;return node;}
function xButton(label,action){const button=xText('button',label);button.type='button';button.addEventListener('click',()=>Promise.resolve().then(action).catch(error=>xStatus(error.message)));return button;}
function xMoney(value){return (value/1000000).toLocaleString('cs-CZ',{style:'currency',currency:'USD',maximumFractionDigits:6});}
function xSubscriptions(){return (xSourcesState?.subscriptions||[]).map(({fingerprint,...subscription})=>subscription);}
function renderXSources(){
 const list=document.querySelector('#x-subscription-list');list.replaceChildren();
 const table=document.createElement('table');table.className='monitoring-catalog-table';
 const header=document.createElement('tr');for(const name of ['Název','Zdroj','Stav','Uchování','Akce'])header.append(xText('th',name));table.append(header);
 for(const sub of xSourcesState?.subscriptions||[]){const row=document.createElement('tr');
  for(const value of [sub.name,sub.kind+': '+sub.value,sub.enabled?'Ruční načtení povoleno':'Pozastaveno',sub.retention_days+' dní'])row.append(xText('td',value));
  const actions=document.createElement('td');actions.append(xButton('Upravit',()=>editXSubscription(sub)),xButton('Odebrat',async()=>{
   if(!window.confirm('Odebrat místní odběr? Historie placených požadavků a jejich rezervace zůstanou.'))return;
   await saveXSources(xSubscriptions().filter(s=>s.id!==sub.id));
  }));row.append(actions);table.append(row);
 }list.append(table);
 const requests=document.querySelector('#x-request-list');requests.replaceChildren();
 for(const run of xSourcesState?.requests||[]){const p=xText('p',(run.subscription||'Odběr')+' · '+run.id+' · '+run.state+' · '+xMoney(run.reserved_micro_usd)+(run.imported?' · import potvrzen':''));
  if(['prepared','dispatching'].includes(run.state)||run.state==='completed'&&!run.imported)p.append(xButton('Ponechat unknown a uvolnit další ruční požadavek',async()=>{
   if(!window.confirm('Ponechat výsledek neznámý, nevracet rezervovanou cenu a povolit nový ruční požadavek? Původní API volání se nebude opakovat.'))return;
   xSourcesState=await projectRequest('/v1/x-sources/close',{operation_id:run.id,confirm:true});renderXSources();
  }));requests.append(p);
 }
 xStatus('Neověřený PoC. Rezervace za '+(xSourcesState?.budget_month||'aktuální měsíc')+' UTC: '+xMoney(xSourcesState?.reserved_micro_usd||0)+'. Nastavení se nesynchronizuje.');
}
async function loadXSources(){
 if(xSourcesBusy)return;
 if(xSourcesDirty&&!window.confirm('Zahodit rozepsané nastavení X?'))return;
 xSourcesBusy=true;
 try{
  xSourcesState=await projectRequest('/v1/x-sources/view',{});
  const settings=xSourcesState.settings;
  if(settings){for(const key of ['max_results','max_pages','price_review'])xSettings.elements[key].value=settings[key];xSettings.elements.budget.value=settings.monthly_budget_micro_usd/1e6;xSettings.elements.price.value=settings.post_price_micro_usd/1e6;xSettings.elements.enabled.checked=settings.enabled;}
  xSettings.elements.token.value='';xSourcesDirty=false;xSubscription.hidden=true;renderXSources();
 }catch(error){xStatus(error.message);}finally{xSourcesBusy=false;}
}
async function saveXSources(subscriptions=xSubscriptions()){
 if(xSourcesBusy||!xSettings.reportValidity())return;
 const fields=xSettings.elements,token=fields.token.value||null;
 const settings={enabled:fields.enabled.checked,monthly_budget_micro_usd:Math.round(Number(fields.budget.value)*1e6),post_price_micro_usd:Math.round(Number(fields.price.value)*1e6),max_results:Number(fields.max_results.value),max_pages:Number(fields.max_pages.value),price_review:fields.price_review.value};
 if(settings.enabled&&!window.confirm('Povolit pouze ruční placené načítání X podle uvedeného rozpočtu? Uložením se X API nevolá.'))return;
 xSourcesBusy=true;
 try{xSourcesState=await projectRequest('/v1/x-sources/save',{revision:xSourcesState?.revision??null,settings,subscriptions,token});xSourcesDirty=false;xSubscription.hidden=true;renderXSources();}
 catch(error){xStatus(error.message+' Změna není potvrzena; při změně tokenu jej před opakováním zadejte znovu.');}
 finally{fields.token.value='';xSourcesBusy=false;}
}
function editXSubscription(sub=null){
 xSubscriptionId=sub?.id||crypto.randomUUID();xSubscription.reset();
 for(const key of ['name','kind','value','retention_days','terms','lookback_hours'])if(sub)xSubscription.elements[key].value=sub[key];
 xSubscription.elements.enabled.checked=sub?.enabled||false;xSubscription.hidden=false;xSubscription.elements.name.focus();
}
document.querySelector('#x-sources').addEventListener('toggle',()=>{if(document.querySelector('#x-sources').open&&!xSourcesState)loadXSources();});
document.querySelector('#x-sources-reload').addEventListener('click',()=>loadXSources());
xSettings.addEventListener('input',()=>xSourcesDirty=true);xSubscription.addEventListener('input',()=>xSourcesDirty=true);
xSettings.addEventListener('submit',e=>{e.preventDefault();saveXSources().catch(error=>xStatus(error.message));});
document.querySelector('#x-subscription-new').addEventListener('click',()=>editXSubscription());
document.querySelector('#x-subscription-cancel').addEventListener('click',()=>{xSubscription.hidden=true;});
xSubscription.addEventListener('submit',async e=>{
 e.preventDefault();if(!xSubscription.reportValidity())return;
 const f=xSubscription.elements,sub={id:xSubscriptionId,name:f.name.value,kind:f.kind.value,value:f.value.value,retention_days:Number(f.retention_days.value),lookback_hours:Number(f.lookback_hours.value),terms:f.terms.value,enabled:f.enabled.checked};
 await saveXSources([...xSubscriptions().filter(s=>s.id!==sub.id),sub]);
});
document.querySelector('#x-forget-form').addEventListener('submit',async e=>{
 e.preventDefault();if(!window.confirm('Odstranit tento příspěvek ze surových místních dat? Odvozené zprávy a další uzly musíte posoudit zvlášť.'))return;
 try{await projectRequest('/v1/x-sources/forget',{post_id:e.currentTarget.elements.post_id.value,confirm:true});xStatus('Surová místní data odstraněna. Posuďte odvozené zprávy, vzdálené uzly a zálohy.');}
 catch(error){xStatus(error.message);}
});
'''
