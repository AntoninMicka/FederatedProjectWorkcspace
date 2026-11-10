# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Browser-side admission matching the server's serialized request lanes."""

import json

from spikes.http_admission_policy import ROUTE_LANES, PROJECT_ROUTES, ACTION_LANES


HTTP_UI_ADMISSION_JS = r'''
(()=>{
 const send=window.fetch.bind(window),lanes=new Map();let totalPending=0;
 const queueWaitMs=5000;
 const now=()=>globalThis.performance?.now?.()??Date.now();
 const routeLanes=Object.freeze(__FPW_ROUTE_LANES__);
 const projectFields=Object.freeze(__FPW_PROJECT_FIELDS__);
 const actionLanes=Object.freeze(__FPW_ACTION_LANES__);
 function lane(path,body){
  const actions=Object.hasOwn(actionLanes,path)?actionLanes[path]:null;
  if(actions&&typeof body?.action==='string'&&Object.hasOwn(actions,body.action))return actions[body.action];
  return Object.hasOwn(routeLanes,path)?routeLanes[path]:'application';
 }
 const failure=(name,message,outcome,cause)=>Object.assign(new Error(message),{
  name,status:outcome==='not-started'?503:408,phase:outcome==='not-started'?'admission':'transport',
  outcome,retry:'same-operation',dispatched:outcome!=='not-started',cause});
 window.fetch=(input,options={})=>{
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
  const method=(options.method||input?.method||'GET').toUpperCase();
  if(url.origin!==location.origin||method!=='POST'||!url.pathname.startsWith('/v1/'))return send(input,options);
  const queuedAt=now();
  const timing=url.pathname==='/v1/projects/open'?{queued_at:queuedAt,queue_ms:null,headers_ms:null,drain_ms:null}:null;
  const signal=options.signal||input?.signal;
  const aborted=()=>signal?.reason||new DOMException('Požadavek byl zrušen.','AbortError');
  if(signal?.aborted)return Promise.reject(failure(signal.reason?.name==='TimeoutError'?'TimeoutError':'AbortError','Požadavek byl zrušen před odesláním.','not-started',aborted()));
  if(totalPending>=64)return Promise.reject(failure('QuotaExceededError','Fronta je plná. Požadavek nebyl odeslán.','not-started'));
  const path=url.pathname+url.search;
  let body;if(Object.hasOwn(actionLanes,path)||Object.hasOwn(projectFields,path))try{body=JSON.parse(options.body);}catch(error){}
  let key=lane(path,body);
  if(key==='project'){
   try{const field=projectFields[url.pathname],scope=field?body[field]:body;
    if(typeof scope?.project_id==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(scope.project_id))key+=':'+scope.project_id;
   }catch(error){}
  }

  const state=lanes.get(key)||{active:null,queue:[]};
  const entry={start:null};let released=false,dispatched=false,waitingError=null,timer;
  const acquiring=new AbortController();let resolve,reject,finish;
  const result=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const done=new Promise(yes=>{finish=yes;});
  const pump=()=>{
   if(state.active||!state.queue.length)return;
   const next=state.queue.shift();state.active=next;
   Promise.resolve().then(()=>next.start());
  };
  const release=()=>{
   if(released)return;released=true;
   if(state.active===entry)state.active=null;
   else{const index=state.queue.indexOf(entry);if(index>=0)state.queue.splice(index,1);}
   totalPending--;finish();
   if(!state.active&&!state.queue.length){if(lanes.get(key)===state)lanes.delete(key);}
   else pump();
  };
  const stopWaiting=error=>{
   if(dispatched||waitingError)return;
   waitingError=error;clearTimeout(timer);acquiring.abort(error);release();reject(error);
  };
  const expired=()=>failure('TimeoutError','Čekání ve frontě vypršelo. Požadavek nebyl odeslán.','not-started');
  const onAbort=()=>{
   const name=signal?.reason?.name==='TimeoutError'?'TimeoutError':'AbortError';
   if(!dispatched)stopWaiting(failure(name,'Požadavek byl zrušen před odesláním.','not-started',aborted()));
   else reject(failure(name,'Požadavek byl odeslán; výsledek není známý. Obnovte stav původní operace.','unknown',aborted()));
  };
  const failed=error=>{
   release();reject(waitingError||(error?.phase?error:failure(error?.name||'Error',
    dispatched?'Požadavek byl odeslán; výsledek není známý. Obnovte stav původní operace.':'Požadavek nebyl odeslán; nelze získat linku.',
    dispatched?'unknown':'not-started',error)));
  };
  const dispatch=async()=>{
   if(waitingError)throw waitingError;
   if(signal?.aborted){onAbort();throw waitingError;}
   if(now()-queuedAt>=queueWaitMs){stopWaiting(expired());throw waitingError;}
   const sentAt=now();dispatched=true;clearTimeout(timer);
   if(timing)timing.queue_ms=Math.round(sentAt-queuedAt);
   const response=await send(input,options);
   if(timing){timing.headers_at=now();timing.headers_ms=Math.round(timing.headers_at-sentAt);try{Object.defineProperty(response,'fpwAdmissionTiming',{value:timing});}catch(error){}}
   // Headers and caller cancellation are not completion. Keep ownership until
   // the original response transport reaches EOF or fails, including streams.
   const reader=response.clone().body?.getReader();
   resolve(response);
   if(!reader){release();return;}
   (async()=>{try{while(!(await reader.read()).done){}}catch(error){}finally{
    reader.releaseLock();if(timing)timing.drain_ms=Math.round(now()-timing.headers_at);release();
   }})();
  };
  entry.start=()=>{
   if(waitingError)return;
   try{
    const locks=window.navigator?.locks;
    const task=locks?.request?locks.request('fpw-http-'+key,{signal:acquiring.signal},async()=>{
     await dispatch();await done;
    }):dispatch();
    Promise.resolve(task).catch(failed);
   }catch(error){failed(error);}
  };
  lanes.set(key,state);totalPending++;state.queue.push(entry);
  timer=setTimeout(()=>stopWaiting(expired()),queueWaitMs);
  signal?.addEventListener('abort',onAbort,{once:true});
  if(signal?.aborted)onAbort();else pump();
  return result.finally(()=>{clearTimeout(timer);signal?.removeEventListener('abort',onAbort);});
 };
})();
'''.replace('__FPW_ROUTE_LANES__', json.dumps(ROUTE_LANES, sort_keys=True)).replace(
    '__FPW_PROJECT_FIELDS__', json.dumps(PROJECT_ROUTES, sort_keys=True)).replace(
    '__FPW_ACTION_LANES__', json.dumps(ACTION_LANES, sort_keys=True))
