# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Browser-side admission matching the server's serialized request lanes."""

HTTP_UI_ADMISSION_JS = r'''
(()=>{
 const send=window.fetch.bind(window),lanes=new Map();
 const reviews=new Set(['/v1/roadmap-refinement/list','/v1/roadmap-refinement/detail','/v1/roadmap-refinement/reconcile/preview']);
 function lane(path){
  if(path==='/v1/diagnostics/status')return 'diagnostics';
  if(path==='/v1/node-telemetry/status')return 'telemetry';
  if(path==='/v1/chat/availability'||path==='/v1/tasks/run-control')return 'availability';
  return reviews.has(path)?'review':'application';
 }
 window.fetch=(input,options={})=>{
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
  const method=(options.method||input?.method||'GET').toUpperCase();
  if(url.origin!==location.origin||method!=='POST'||!url.pathname.startsWith('/v1/'))return send(input,options);
  const signal=options.signal||input?.signal;
  const aborted=()=>signal?.reason||new DOMException('Požadavek byl zrušen.','AbortError');
  if(signal?.aborted)return Promise.reject(aborted());
  const key=lane(url.pathname+url.search),state=lanes.get(key)||{tail:Promise.resolve(),pending:0};
  if(state.pending>=64)return Promise.reject(new DOMException('Příliš mnoho čekajících požadavků.','QuotaExceededError'));
  lanes.set(key,state);state.pending++;
  const previous=state.tail;let finish,released=false;
  const done=new Promise(resolve=>{finish=resolve;});
  state.tail=previous.then(()=>done);
  const release=()=>{if(!released){released=true;state.pending--;finish();}};
  const dispatch=async()=>{
   try{
    if(signal?.aborted)throw aborted();
    const response=await send(input,options);
    // Headers alone do not mean the server has released its lane. Drain a
    // clone without accumulating chunks, while returning the original stream
    // immediately to its consumer (including streaming chat).
    const reader=response.clone().body?.getReader();
    if(!reader){release();return response;}
    (async()=>{try{while(!(await reader.read()).done){}}catch(error){}finally{reader.releaseLock();release();}})();
    return response;
   }catch(error){release();throw error;}
  };
  const request=previous.then(()=>{
   const locks=window.navigator?.locks;
   if(!locks?.request)return dispatch();
   // One origin-wide lock joins independent pages (main UI and presenter).
   // Return headers immediately, but hold ownership until response EOF.
   return new Promise((resolve,reject)=>{
    locks.request('fpw-http-'+key,signal?{signal}:{},async()=>{
     try{resolve(await dispatch());await done;}
     catch(error){reject(error);}
    }).catch(error=>{release();reject(error);});
   });
  });
  if(!signal)return request;
  let onAbort;
  const cancelled=new Promise((resolve,reject)=>{onAbort=()=>reject(aborted());signal.addEventListener('abort',onAbort,{once:true});if(signal.aborted)onAbort();});
  return Promise.race([request,cancelled]).finally(()=>signal.removeEventListener('abort',onAbort));
 };
})();
'''
