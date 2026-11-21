# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Inline, explicitly confirmed task records; editor drafts stay independent."""
JS = r'''
const taskRecordDrafts=new Map();
const taskAttachmentDrafts=new Map();
async function loadTaskAttachment(){
 const session=selectedTaskWorkSession();if(!session||taskWorkBusy||session.record_pending?.length)return;
 const previous=taskAttachmentDrafts.get(session.work_session_id);
 try{
  const options=await projectRequest('/v1/task-work',{action:'record-attachment-options',...taskWorkHandle,work_session_id:session.work_session_id});
  if(selectedTaskWorkSession()?.work_session_id!==session.work_session_id)return;
  taskAttachmentDrafts.set(session.work_session_id,{...options,selected:options.items.some(item=>item.id===previous?.selected)?previous.selected:options.items[0]?.id||'',comment:previous?.comment??'Připojen existující artefakt',attempt:null});
  renderTaskRecords();
 }catch(error){taskWorkMessage=error.message;renderTaskWork();}
}
function renderTaskAttachment(editor,session){
 editor.append(taskRecordButton('Připojit existující soubor / artefakt',loadTaskAttachment,taskWorkBusy||!!session.record_pending?.length));
 const draft=taskAttachmentDrafts.get(session.work_session_id);if(!draft)return;
 const form=document.createElement('form');form.id='task-attachment-form';
 const label=document.createElement('label');label.textContent='Existující soubor / artefakt v projektu';
 const select=document.createElement('select');select.id='task-attachment-artifact';
 for(const item of draft.items){const option=document.createElement('option');option.value=item.id;option.textContent=item.title;select.append(option);}
 select.value=draft.selected;select.disabled=taskWorkBusy||!!draft.attempt;
 select.addEventListener('change',()=>{draft.selected=select.value;});label.append(select);
 const commentLabel=document.createElement('label');commentLabel.textContent='Komentář k připojení';
 const comment=document.createElement('textarea');comment.id='task-attachment-comment';comment.maxLength=4000;comment.value=draft.comment;comment.disabled=taskWorkBusy||!!draft.attempt;
 comment.addEventListener('input',()=>{draft.comment=comment.value;});commentLabel.append(comment);
 const status=document.createElement('p');status.textContent=draft.items.length?'Připojí se odkaz na vybranou uloženou verzi. Obsah souboru se nekopíruje.':'V projektu není dostupný žádný soubor k připojení. Nejprve jej přidejte mezi podklady.';
 const submit=async()=>{
  if(taskWorkBusy||!draft.selected)return;
  if(!draft.attempt)draft.attempt={action:'record-attach',...taskWorkHandle,operation_id:crypto.randomUUID(),work_session_id:session.work_session_id,artifact_id:draft.selected,comment:draft.comment,selected_checklist:session.selected_checklist,expected_head:draft.expected_head,privacy:draft.privacy};
  await sendTaskWork(draft.attempt);
  if(!taskWorkAttempt){taskAttachmentDrafts.delete(session.work_session_id);renderTaskRecords();}
 };
 form.addEventListener('submit',event=>{event.preventDefault();submit();});
 form.append(label,commentLabel,status,taskRecordButton('Potvrdit a připojit',submit,taskWorkBusy||!draft.selected),taskRecordButton('Obnovit výběr',loadTaskAttachment,taskWorkBusy||!!session.record_pending?.length));editor.append(form);
}
let taskRecordPreviewId=null,taskRecordPreviewGeneration=0;
function clearTaskRecordPreview(){taskRecordPreviewId=null;taskRecordPreviewGeneration++;document.querySelector('#task-record-preview').replaceChildren();}
function taskRecordButton(label,action,disabled=false){const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=disabled;button.addEventListener('click',action);return button;}
function chooseTaskRecordEvents(ids){
 const session=selectedTaskWorkSession();if(!session?.activities)return;
 const events=ids.map(id=>session.activities.find(e=>e.event_id===id)).filter(Boolean);if(!events.length){taskRecordDrafts.delete(session.work_session_id);renderTaskRecords();return;}
 const previous=taskRecordDrafts.get(session.work_session_id),first=events[0].offer;
 const levels=['public','project','confidential','local-only'];
 const minimum=Math.max(levels.indexOf(session.record_minimum_privacy||'project'),...events.map(e=>levels.indexOf(e.privacy||'local-only')));
 taskRecordDrafts.set(session.work_session_id,{ids:events.map(e=>e.event_id),revisions:events.map(e=>e.offer.revision),comment:previous?.comment??first.comment,selected:previous?.selected??first.selected_checklist,privacy:levels[minimum],attempt:null});renderTaskRecords();
}
function renderTaskRecords(){
 const editor=document.querySelector('#task-record-editor'),list=document.querySelector('#task-record-list');editor.replaceChildren();list.replaceChildren();
 const session=selectedTaskWorkSession();if(!session?.current_task){clearTaskRecordPreview();return;}
 if(taskRecordPreviewId&&!session.task_records?.some(record=>record.id===taskRecordPreviewId))clearTaskRecordPreview();
 const draft=taskRecordDrafts.get(session.work_session_id),selected=new Set(draft?.ids||[]);
 const heading=document.createElement('h3');heading.textContent='Přidat záznam k úkolu';editor.append(heading);
 const info=document.createElement('p');info.textContent='Vyberte související činnosti. Záznam ani příloha nepotvrzují splnění úkolu.';editor.append(info);
 renderTaskAttachment(editor,session);
 const stateNames={pending:'K připojení',draft:'Rozepsané',deferred:'Odložené',dismissed:'Odmítnuté',confirmed:'Připojeno'};
 for(const event of session.activities||[]){
  const row=document.createElement('label'),check=document.createElement('input'),caption=document.createElement('span');check.type='checkbox';check.dataset.recordEvent=event.event_id;check.checked=selected.has(event.event_id);check.disabled=taskWorkBusy||event.offer.state==='confirmed'||!!event.offer.pending_operation_id;
  caption.textContent=`${stateNames[event.offer.state]||event.offer.state} · ${event.offer.comment.slice(0,100)||'Činnost'} · ${event.outcome==='succeeded'?'dokončeno':event.outcome==='failed'?'neúspěšné':'výsledek není potvrzen'}`;
  check.addEventListener('change',()=>{const ids=new Set(taskRecordDrafts.get(session.work_session_id)?.ids||[]);if(check.checked)ids.add(event.event_id);else ids.delete(event.event_id);chooseTaskRecordEvents([...ids]);});row.append(check,caption);editor.append(row);
  if(['draft','deferred','dismissed'].includes(event.offer.state))editor.append(taskRecordButton('Otevřít nabídku',()=>{taskRecordDrafts.delete(session.work_session_id);chooseTaskRecordEvents(event.offer.event_ids||[event.event_id]);},taskWorkBusy||!!event.offer.pending_operation_id));
 }
 for(const operation of session.record_pending||[]){
  const row=document.createElement('p');row.textContent='Zápis čeká na obnovu. Komentář a výsledky zůstávají připnuté.';
  for(const [label,action] of [['Obnovit zápis','record-recover'],['Zrušit před zápisem','record-cancel']])row.append(taskRecordButton(label,async()=>{await sendTaskWork({action,...taskWorkHandle,operation_id:operation.operation_id});renderTaskRecords();},taskWorkBusy));editor.append(row);
 }
 if(draft){
  const reserved=!!session.record_pending?.some(op=>op.operation_id===draft.attempt?.operation_id);
  const change=update=>{if(!reserved){draft.attempt=null;Object.assign(draft,update);}};
  const form=document.createElement('form');form.id='task-record-form';form.addEventListener('submit',event=>{event.preventDefault();submitTaskRecord('publish');});
  const label=document.createElement('label');label.textContent='Komentář k výsledku';label.htmlFor='task-record-comment';
  const comment=document.createElement('textarea');comment.id='task-record-comment';comment.maxLength=4000;comment.rows=5;comment.value=draft.comment;comment.disabled=taskWorkBusy||reserved;
  comment.addEventListener('input',()=>{change({comment:comment.value});});form.append(label,comment);
  const checklistLabel=document.createElement('label');checklistLabel.textContent='Bod původního checklistu';checklistLabel.htmlFor='task-record-point';
  const checklist=document.createElement('select');checklist.id='task-record-point';checklist.disabled=taskWorkBusy||reserved;
  for(const [value,text] of [['','Celý úkol'],...(session.record_checklist||[]).map((text,index)=>[String(index),text])]){const option=document.createElement('option');option.value=value;option.textContent=text;checklist.append(option);}
  checklist.value=draft.selected===null?'':String(draft.selected);checklist.addEventListener('change',()=>{change({selected:checklist.value===''?null:Number(checklist.value)});});form.append(checklistLabel,checklist);
  const privacyLabel=document.createElement('label');privacyLabel.textContent='Soukromí záznamu';privacyLabel.htmlFor='task-record-privacy';const privacy=document.createElement('select');privacy.id='task-record-privacy';privacy.disabled=taskWorkBusy||reserved;
  for(const value of ['public','project','confidential','local-only']){const option=document.createElement('option');option.value=value;option.textContent=value;option.disabled=value==='local-only'&&document.body.dataset.runtime!=='desktop';privacy.append(option);}privacy.value=draft.privacy;privacy.addEventListener('change',()=>{change({privacy:privacy.value});});form.append(privacyLabel,privacy);
  const pin=document.createElement('small');pin.className='task-work-pin';pin.textContent='Výsledky zůstanou u původních činností; vybraný bod nemění jejich splnění.';form.append(pin);
  for(const [text,state] of [['Uložit rozepsané','draft'],['Odložit','deferred'],['Odmítnout','dismissed'],['Potvrdit a připojit','publish']])form.append(taskRecordButton(text,()=>submitTaskRecord(state),taskWorkBusy||reserved));
  form.append(taskRecordButton('Obnovit nabídku',async()=>{await refreshTaskWork();const current=selectedTaskWorkSession();if(current?.current_task&&!current.record_pending?.length){draft.attempt=null;draft.revisions=draft.ids.map(id=>current.activities.find(e=>e.event_id===id)?.offer.revision);renderTaskRecords();}},taskWorkBusy));editor.append(form);
 }
 const title=document.createElement('h3');title.textContent='Potvrzené záznamy';list.append(title);
 if(!session.task_records?.length){const empty=document.createElement('p');empty.textContent='Žádné potvrzené záznamy.';list.append(empty);}
 for(const record of session.task_records||[])appendConfirmedTaskRecord(list,record,openTaskRecordOutput,async record=>{const last=record.revisions.at(-1),value=window.prompt('Oprava komentáře (původní text zůstane v historii):',last.comment);if(value===null)return;await sendTaskWork({action:'record-amend',...taskWorkHandle,operation_id:crypto.randomUUID(),work_session_id:session.work_session_id,record_id:record.id,record_revision:record.record_revision,comment:value,selected_checklist:last.selected_checklist,expected_head:record.validated_head});});
}
function appendConfirmedTaskRecord(list,record,openOutput,amend=null){
  const article=document.createElement('article');article.dataset.taskRecord=record.id;const last=record.revisions.at(-1);
  const when=document.createElement('small');when.textContent=`${record.context.task_id} · ${new Date(record.revisions[0].created_at).toLocaleString()} · ${record.events.length} činností`;const comment=document.createElement('p');comment.textContent=last.comment||'Bez komentáře';article.append(when,comment);
  if(last.selected_checklist!==null){const point=document.createElement('p');point.textContent='Bod původního checklistu: '+(last.selected_checklist+1);article.append(point);}
  for(const [index,output] of record.outputs.entries()){
   const row=document.createElement('p');row.textContent=output.title+' · '+output.artifact_id.slice(0,8)+' · '+output.commit_id.slice(0,12);row.append(taskRecordButton('Původní verze',()=>openOutput(record,index,'original')),taskRecordButton('Aktuální artefakt',()=>openOutput(record,index,'current')));article.append(row);
  }
  if(!record.outputs.length){const warning=document.createElement('p');warning.textContent='Záznam odkazuje na činnosti či běhy; neobsahuje potvrzený souborový výsledek.';article.append(warning);}
  if(amend)article.append(taskRecordButton('Upravit komentář',()=>amend(record),taskWorkBusy));
  const history=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Historie komentáře ('+record.revisions.length+')';history.append(summary);
  for(const revision of record.revisions){const row=document.createElement('p');row.textContent=`${new Date(revision.created_at).toLocaleString()} · ${revision.comment}`;history.append(row);}article.append(history);list.append(article);
}
async function submitTaskRecord(state){
 const session=selectedTaskWorkSession(),draft=taskRecordDrafts.get(session?.work_session_id);if(!draft||taskWorkBusy)return;
 if(!draft.attempt){draft.attempt={action:state==='publish'?'record-publish':'record-offer',...taskWorkHandle,operation_id:crypto.randomUUID(),work_session_id:session.work_session_id,event_ids:draft.ids,offer_revisions:draft.revisions,comment:draft.comment,selected_checklist:draft.selected};
  if(state==='publish')Object.assign(draft.attempt,{expected_head:session.validated_head,privacy:draft.privacy});else draft.attempt.state=state;
 }
 await sendTaskWork(draft.attempt);
 if(!taskWorkAttempt){taskRecordDrafts.delete(session.work_session_id);renderTaskRecords();}
}
async function openTaskRecordOutput(record,index,version,page=1){
 const generation=++taskRecordPreviewGeneration;taskRecordPreviewId=record.id;
 const target=document.querySelector('#task-record-preview');target.replaceChildren();const status=document.createElement('p');status.textContent='Načítám připnutý výsledek…';target.append(status);
 try{const result=await projectRequest('/v1/task-work',{action:'record-output',...taskWorkHandle,project_id:record.context.project_id,record_id:record.id,output_index:index,version,page});
  if(generation!==taskRecordPreviewGeneration)return;
  target.replaceChildren();target.append(taskRecordButton('Zavřít náhled',clearTaskRecordPreview));const heading=document.createElement('h3');heading.textContent=(version==='original'?'Původní verze':'Aktuální artefakt')+' · '+result.commit_id.slice(0,12);target.append(heading);
  if(result.format==='markdown'){const content=document.createElement('div');renderMarkdown(result.text,content,null,false);target.append(content);}
  else if(['image','pdf'].includes(result.format)){const image=document.createElement('img');image.alt=result.metadata.title;image.src=result.image;target.append(image);}
  else{const text=document.createElement('pre');text.textContent=result.text||result.message||'Náhled není dostupný.';target.append(text);}
  if(result.pages>1){if(page>1)target.append(taskRecordButton('Předchozí strana',()=>openTaskRecordOutput(record,index,version,page-1)));if(page<result.pages)target.append(taskRecordButton('Další strana',()=>openTaskRecordOutput(record,index,version,page+1)));}
 }catch(error){if(generation===taskRecordPreviewGeneration){target.replaceChildren();status.textContent=error.message;target.append(status);}}
}
'''
