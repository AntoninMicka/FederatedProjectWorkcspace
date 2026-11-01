# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Deadline controls for the existing streamed task progress surface."""
TASK_STREAM_JS = r'''
let taskRunDeadlineBox=null,taskRunDeadlineIdentity=null,taskStreamDraft='';
function appendTaskStreamDelta(delta){
 taskStreamDraft+=delta;
 const match=taskStreamDraft.match(/(?:^|[{,])\s*"content"\s*:\s*("(?:[^"\\]|\\.)*(?:"|$))/s);
 if(!match){
  const parts=[];
  for(const token of taskStreamDraft.matchAll(/(?:^|[{,])\s*"(before|after)"\s*:\s*("(?:[^"\\]|\\.)*(?:"|$))/gs)){
   const text=taskStreamString(token[2]);if(text!==null)parts.push((token[1]==='before'?'− ':'+ ')+text);
  }
  if(parts.length){chatStream.textContent=parts.join('\n');chatStream.hidden=false;keepChatStreamVisible();}
  return;
 }
 const text=taskStreamString(match[1]);
 if(text!==null){chatStream.textContent=text;chatStream.hidden=false;keepChatStreamVisible();}
}
function taskStreamString(quoted){
 if(!quoted.endsWith('"')||quoted.length===1){
  quoted=quoted.replace(/\\u[0-9a-f]{0,3}$/i,'').replace(/\\$/,'')+'"';
 }
 try{return JSON.parse(quoted);}catch(_incompleteEscape){return null;}
}
function clearTaskRunDeadline(){
 if(taskRunDeadlineBox)taskRunDeadlineBox.remove();
 taskRunDeadlineBox=null;taskRunDeadlineIdentity=null;
}
function updateTaskRunDeadline(value,request){
 if(!request)return;
 const identity=request.run_id;
 if(taskRunDeadlineIdentity&&taskRunDeadlineIdentity!==identity)clearTaskRunDeadline();
 if(!taskRunDeadlineBox){
  taskRunDeadlineIdentity=identity;
  const box=document.createElement('div');box.id='task-run-deadline';box.className='task-actions';box.setAttribute('role','status');
  const message=document.createElement('span'),extend=document.createElement('button'),stop=document.createElement('button');
  extend.dataset.taskRunAction='extend';stop.dataset.taskRunAction='stop';
  extend.type=stop.type='button';extend.textContent='Prodloužit na 30 minut';stop.textContent='Ukončit běh';
  const decide=async action=>{
   extend.disabled=stop.disabled=true;
   try{
    const result=await projectRequest('/v1/tasks/run-control',{project_id:request.project_id,run_id:identity,action},10000);
    if(taskRunDeadlineIdentity===identity)updateTaskRunDeadline(result,request);
   }catch(error){if(taskRunDeadlineIdentity===identity){message.textContent=error.message;extend.disabled=stop.disabled=false;}}
  };
  extend.onclick=()=>decide('extend');stop.onclick=()=>decide('stop');
  box.append(message,extend,stop);chatStreamStatus.insertAdjacentElement('afterend',box);taskRunDeadlineBox=box;
 }
 const [message,extend,stop]=taskRunDeadlineBox.children;
 const remaining=Math.max(0,value.hard_seconds-value.elapsed_seconds);
 message.textContent=value.stopped?'Příjem odpovědi byl ukončen.':value.extended?
  `Prodloužený běh · nejvýše ještě ${Math.ceil(remaining/60)} min.`:
  value.elapsed_seconds>=value.soft_seconds?`Běh trvá déle než 3 minuty. Bez prodloužení skončí za ${remaining} s.`:'';
 extend.hidden=value.extended||value.elapsed_seconds<value.soft_seconds;
 extend.disabled=stop.disabled=Boolean(value.stopped);
 if(!value.extended)extend.textContent=`Prodloužit na ${Math.round(value.soft_seconds*10/60)} minut`;
}
'''
