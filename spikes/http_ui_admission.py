# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Browser-side admission matching the server's serialized request lanes."""

import json

from spikes.http_admission_policy import ROUTE_LANES


HTTP_UI_ADMISSION_JS = r'''
(()=>{
 const send=window.fetch.bind(window),lanes=new Map();
 const now=()=>globalThis.performance?.now?.()??Date.now();
 const routeLanes=Object.freeze(__FPW_ROUTE_LANES__);
 function lane(path){
  return Object.hasOwn(routeLanes,path)?routeLanes[path]:'application';
 }
 window.fetch=(input,options={})=>{
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
  const method=(options.method||input?.method||'GET').toUpperCase();
  if(url.origin!==location.origin||method!=='POST'||!url.pathname.startsWith('/v1/'))return send(input,options);
  const timing=url.pathname==='/v1/projects/open'?{queued_at:now(),queue_ms:null,headers_ms:null,drain_ms:null}:null;
  const signal=options.signal||input?.signal;
  const aborted=()=>signal?.reason||new DOMException('Požadavek byl zrušen.','AbortError');
  if(signal?.aborted)return Promise.reject(aborted());
  const key=lane(url.pathname+url.search),state=lanes.get(key)||{tail:Promise.resolve(),pending:0};
  if(state.pending>=64)return Promise.reject(new DOMException('Příliš mnoho čekajících požadavků.','QuotaExceededError'));
  lanes.set(key,state);state.pending++;
  const previous=state.tail;let finish,released=false;
  const done=new Promise(resolve=>{finish=resolve;});
  state.tail=previous.then(()=>done);
  const release=()=>{if(!released){released=true;if(timing&&timing.headers_at!==undefined)timing.drain_ms=Math.round(now()-timing.headers_at);state.pending--;finish();}};
  const dispatch=async()=>{
   try{
    if(signal?.aborted)throw aborted();
    const dispatched=now();if(timing)timing.queue_ms=Math.round(dispatched-timing.queued_at);
    const response=await send(input,options);
    if(timing){timing.headers_at=now();timing.headers_ms=Math.round(timing.headers_at-dispatched);try{Object.defineProperty(response,'fpwAdmissionTiming',{value:timing});}catch(error){}}
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
'''.replace('__FPW_ROUTE_LANES__', json.dumps(ROUTE_LANES, sort_keys=True))
