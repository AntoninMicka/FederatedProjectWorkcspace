# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only task evidence in the roadmap, independent of working-window ownership."""
JS = r'''
async function appendTaskPlanRecords(detail,item){
 const project=activeProject;if(!project)return;
 const head=project.head,section=document.createElement('section');section.dataset.taskEvidence=item.id;
 const heading=document.createElement('h3');heading.textContent='Plnění úkolu a výsledky';const status=document.createElement('p');status.setAttribute('role','status');status.textContent='Načítám záznamy…';
 section.append(heading,status);detail.append(section);
 section.append(taskRecordButton('Obnovit záznamy',()=>{if(activeProject===project&&planDetailId===item.id&&section.isConnected){section.remove();appendTaskPlanRecords(detail,item);}}));
 const current=()=>activeProject===project&&project.head===head&&planDetailId===item.id&&section.isConnected&&!detail.hidden&&detail.contains(section);
 const previewHost=document.createElement('section');previewHost.setAttribute('aria-label','Náhled výsledku úkolu');let previewGeneration=0;
 async function openOutput(id,index,version,page=1,activity=false){
  const generation=++previewGeneration;previewHost.replaceChildren();const message=document.createElement('p');message.textContent='Načítám výsledek…';previewHost.append(message);
  try{const result=await projectRequest('/v1/task-work',{action:activity?'record-activity-preview':'record-preview',project_id:project.id,task_id:item.id,expected_head:head,[activity?'event_id':'record_id']:id,output_index:index,version,page});
   if(!current()||generation!==previewGeneration)return;
   previewHost.replaceChildren();previewHost.append(taskRecordButton('Zavřít náhled',()=>{previewGeneration++;previewHost.replaceChildren();}));
   const title=document.createElement('h4');title.textContent=result.metadata.title+' · '+(version==='original'?'původní verze':'aktuální verze')+' · '+result.commit_id.slice(0,12);previewHost.append(title);
   const content=document.createElement('div');previewHost.append(content);
   if(result.format==='markdown')renderMarkdown(result.text,content,null,false);
   else if(['image','pdf'].includes(result.format)){const image=document.createElement('img');image.alt=result.metadata.title;image.src=result.image;image.style.maxWidth='100%';content.append(image);}
   else{const pre=document.createElement('pre');pre.textContent=result.text||result.message||'Náhled není dostupný.';content.append(pre);}
   if(page>1)previewHost.append(taskRecordButton('Předchozí strana',()=>openOutput(id,index,version,page-1,activity)));
   if(page<(result.pages||1))previewHost.append(taskRecordButton('Další strana',()=>openOutput(id,index,version,page+1,activity)));
  }catch(error){if(current()&&generation===previewGeneration){previewHost.replaceChildren();message.textContent=error.message;previewHost.append(message);}}
 }
 try{const data=await projectRequest('/v1/task-work',{action:'record-list',project_id:project.id,task_id:item.id,expected_head:head});
  if(!current())return;
  status.textContent=`Potvrzené záznamy: ${data.records.length}. `+(data.activities_unavailable?'Lokální evidenci nyní nelze načíst.':`Evidované činnosti na tomto uzlu: ${data.activities.length}${data.activities_truncated?' (posledních 50)':''}.`);
  const confirmed=document.createElement('div');section.append(confirmed);
  for(const record of data.records)appendConfirmedTaskRecord(confirmed,record,(record,index,version)=>openOutput(record.id,index,version));
  if(!data.records.length){const empty=document.createElement('p');empty.textContent='Úkol zatím nemá potvrzené projektové záznamy.';confirmed.append(empty);}
  const local=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Automatická evidence na tomto uzlu';local.append(summary);section.append(local);
  const states={pending:'Nepřipojeno',draft:'Rozepsaný záznam',deferred:'Odloženo',dismissed:'Odmítnuto',confirmed:'Připojeno'};
  const outcomes={succeeded:'Dokončeno',failed:'Neúspěšné',unknown:'Výsledek není potvrzen'};
  for(const event of data.activities){
   const row=document.createElement('article');row.dataset.taskActivity=event.event_id;const text=document.createElement('p');text.textContent=`${event.offer.comment||'Činnost'} · ${outcomes[event.outcome]} · ${event.offer.pending_operation_id?'Čeká na obnovu zápisu':states[event.offer.state]||event.offer.state} · ${new Date(event.created_at*1000).toLocaleString()}`;row.append(text);
   if(event.outputs_unavailable){const warning=document.createElement('p');warning.textContent='Připnuté výsledky nyní nelze ověřit.';row.append(warning);}
   for(const [index,output] of event.outputs.entries()){const result=document.createElement('p');result.textContent=output.title+' · '+output.commit_id.slice(0,12);result.append(taskRecordButton('Původní verze',()=>openOutput(event.event_id,index,'original',1,true)),taskRecordButton('Aktuální artefakt',()=>openOutput(event.event_id,index,'current',1,true)));row.append(result);}
   local.append(row);
  }
  if(!data.activities.length&&!data.activities_unavailable){const empty=document.createElement('p');empty.textContent='Na tomto uzlu nejsou další evidované činnosti.';local.append(empty);}
  section.append(previewHost);
 }catch(error){if(current())status.textContent=error.message;}
}
'''
