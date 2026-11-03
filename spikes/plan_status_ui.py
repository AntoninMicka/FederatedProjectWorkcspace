# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared plan and queue status presentation; editing stages the existing item draft."""
PLAN_STATUS_JS = r'''
const planStatusLabels={'planned':'Plánováno','in progress':'Probíhá','resolved':'Vyřešeno','failed':'Selhalo','completed':'Dokončeno','deferred':'Odloženo'};
const planStatusColors={'planned':'#fff','in progress':'#fff2c7','resolved':'#e7effb','failed':'#f8dddd','completed':'#e2f3eb','deferred':'#eef1f3'};
function planStatus(item){return Object.hasOwn(item,'status')?(item.status||'unknown'):(item.checked?'completed':'planned');}
function planStatusBadge(item){
 const badge=document.createElement('span');badge.className='plan-status-badge';badge.dataset.status=planStatus(item);
 badge.textContent=(item.status_mode==='sum'?'SUM · ':'')+(planStatusLabels[planStatus(item)]||'Stav neznámý');
 if(item.status_mode==='sum')badge.title='Odvozeno ze všech přímých položek; skupiny se vyhodnocují rekurzivně. '+Object.entries(item.status_counts||{}).map(([status,count])=>(planStatusLabels[status]||status)+': '+count).join(', ');
 return badge;
}
function planStatusDraft(body,status){
 const newline=body.includes('\r\n')?'\r\n':'\n',lines=body.split(/\r?\n/);
 // This is only the scoped item fragment: never rewrite child nodes or neighbours.
 const indent=lines[0].match(/^\s*/)[0]+'  ';
 let fence=null,found=false;
 for(let index=1;index<lines.length;index++){
  const marker=lines[index].match(/^\s*(`{3,}|~{3,})(.*)$/);
  if(marker){if(!fence)fence=marker[1];else if(marker[1][0]===fence[0]&&marker[1].length>=fence.length&&!marker[2].trim())fence=null;continue;}
  if(!fence&&/^\s*[-+*]\s+status:/i.test(lines[index])){
   lines[index]=lines[index].replace(/(:\s*).*$/,(_,prefix)=>prefix+status);found=true;
  }
 }
 if(!found)lines.splice(1,0,indent+'- status: '+status);
 if(status!=='sum')lines[0]=lines[0].replace(/\[([ xX])\]/,status==='completed'?'[x]':'[ ]');
 return lines.join(newline);
}
function configurePlanStatusEditor(task){
 document.querySelector('#plan-item-status-control')?.remove();
 const label=document.createElement('label'),select=document.createElement('select');label.id='plan-item-status-control';label.textContent='Stav položky ';
 for(const [value,text] of Object.entries(planStatusLabels))select.append(new Option(text,value));
 if(['milestone','batch'].includes(task.type)||taskPlanProjection?.nodes.some(n=>n.parent_id===task.id))select.append(new Option('SUM — odvodit z položek','sum'));
 select.value=task.status_mode||planStatus(task);select.setAttribute('aria-label','Stav položky');
 select.addEventListener('change',()=>{
  if(artifactEditorForm.querySelector('button[type="submit"]').disabled)return;
  const body=artifactEditorForm.elements.body;body.value=planStatusDraft(body.value,select.value);body.dispatchEvent(new Event('input',{bubbles:true}));
 });
 label.append(select);document.querySelector('#artifact-raw-widget').before(label);
}
'''
PLAN_STATUS_CSS = '''
.plan-status-badge{display:inline-block;align-self:flex-start;font-size:12px;font-weight:500;line-height:1.4;padding:3px 8px;border:2px solid #557384;border-radius:20px;color:#174056;background:#fff;white-space:nowrap}
.plan-status-badge[data-status="completed"]{background:#e2f3eb;border-color:#26735e}.plan-status-badge[data-status="in progress"]{background:#fff2c7;border-color:#9a6900}.plan-status-badge[data-status="resolved"]{background:#e7effb;border-color:#4a6c9c}.plan-status-badge[data-status="failed"]{background:#f8dddd;border-color:#aa4242}.plan-status-badge[data-status="deferred"]{background:#eef1f3;border-color:#87939a}
.plan-batch-card .plan-status-badge{display:table;font-size:10px;padding:1px 5px;margin-top:5px;max-width:100%;box-sizing:border-box;overflow:hidden;text-overflow:ellipsis}
.plan-batch-card[data-status="completed"]{background:#e2f3eb}.plan-batch-card[data-status="in progress"]{background:#fff2c7}.plan-batch-card[data-status="resolved"]{background:#e7effb}.plan-batch-card[data-status="failed"]{background:#f8dddd}.plan-batch-card[data-status="deferred"]{background:#eef1f3}
#plan-item-status-control{display:grid;gap:4px;max-width:360px;margin:12px 0}.plan-milestone-label .plan-status-badge{display:table;color:#174056;white-space:nowrap}.plan-status-legend{flex:none;display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
'''
