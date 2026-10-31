// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto'),http=require('node:http');
const bridge=require('../extensions/workspace-bridge/bridge'),queue=require('../extensions/workspace-bridge/queue');
async function post(endpoint,route,body,token){return new Promise((resolve,reject)=>{
 const raw=JSON.stringify(body),url=new URL(route,endpoint),req=http.request(url,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(raw)}},r=>{let raw='';r.on('data',c=>raw+=c);r.on('end',()=>{try{const value=JSON.parse(raw);if(r.statusCode!==200)reject(Error(raw));else resolve(value);}catch(e){reject(e);}});});req.on('error',reject);req.end(raw);
});}
(async()=>{
 const f=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
 const project={root:f.storage,session:f.record.session_id,snapshot:f.record.snapshot,repository:f.record.repository,identity:f.record.repository};
 const pairing={...f.pairing,...f.record},request=async(p,action,data)=>bridge.connectionRequest(f.pairing,{action,request:{session_id:p.session,...data}});
 const published=await post(f.pairing.endpoint,'/v1/ide-queue/publish',f.publication,f.admin_token);
 await bridge.sync(project.root,pairing,project.repository);
 const broken=async(p,action,data)=>{if(action==='queue-document')throw Error('interrupted download');return request(p,action,data);};
 await assert.rejects(queue.synchronize(project,broken),/interrupted download/);
 await assert.rejects(fs.access(path.join(project.root,'packets',published.packet_id,'manifest.json')));
 const original=await queue.synchronize(project,request);assert.equal(original.blockers.length,0);
 const packetRoot=path.join(project.root,'packets',original.packet_id),cache=path.join(project.root,'queue-cache');
 for(const doc of original.manifest.documents){const target=path.join(packetRoot,'documents',doc.sha256+'.txt');assert.equal(await fs.realpath(target),target);assert.ok((await fs.stat(target)).nlink>=2);await queue.verified(target,doc.sha256,cache);}
 await assert.rejects(queue.handoff(project,'TASK-02',request));
 const context=await queue.handoff(project,'TASK-01',request);assert.equal(context.packet_id,original.packet_id);
 const manifestBefore=await fs.readFile(context.manifest,'utf8');
 let currentHead=original.current_head;
 for(const task of ['TASK-01','TASK-02']){
  const m={message_id:crypto.randomUUID(),task_id:task,kind:'completed',body:'Agent report with explicit evidence.',revision:original.manifest.revision,
   repository_commit:await bridge.git(project.repository,'rev-parse','HEAD'),queue_packet_id:original.packet_id,reported_by:'agent',evidence:{tests:'Integration checks passed',diff:'Reported source commit'}};
  await bridge.atomic(path.join(project.root,'inbox',m.message_id+'.json'),JSON.stringify(m));
  const result=await bridge.sync(project.root,pairing,project.repository);assert.equal(result.has_queue,true);assert.equal(result.receipts[0].status,'received');
  let state=await queue.synchronize(project,request);assert.equal(state.items.find(i=>i.id===task).agent_confirmed,true);assert.equal(state.items.find(i=>i.id===task).user_confirmed,false);
  const review={project_id:f.record.project_id,session_id:project.session,message_id:m.message_id,decision:'accepted',note:'User inspected tests and diff.',expected_head:currentHead,operation_id:crypto.randomUUID()};
  const accepted=await post(f.pairing.endpoint,'/v1/ide-bridge/review',review,f.admin_token);assert.equal(accepted.outcome,'accepted');
  assert.deepEqual(await post(f.pairing.endpoint,'/v1/ide-bridge/review',review,f.admin_token),accepted);
  state=await queue.synchronize(project,request);currentHead=state.current_head;assert.equal(state.items.find(i=>i.id===task).user_confirmed,true);
  const front=await post(f.pairing.endpoint,'/v1/task-queue',{project_id:f.record.project_id,action:'status'},f.admin_token);assert.equal(front.items.find(i=>i.id===task).user_confirmed,true);assert.equal(front.valid,true);
 }
 assert.equal((await queue.synchronize(project,request)).items[2].eligible,true);
 assert.equal(await fs.readFile(context.manifest,'utf8'),manifestBefore);
 console.log('queue HTTP/filesystem: pinned manifest, hardlinks, agent inbox, human review, replay and A/B/C progression OK');
})().catch(e=>{console.error(e);process.exit(1);});
