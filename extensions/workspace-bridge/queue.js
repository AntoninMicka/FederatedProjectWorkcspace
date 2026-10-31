// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const bridge=require('./bridge');
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const stable=value=>JSON.stringify(value&&typeof value==='object'?Array.isArray(value)?value.map(v=>JSON.parse(stable(v))):Object.fromEntries(Object.keys(value).sort().map(k=>[k,JSON.parse(stable(value[k]))])):value);
function validate(value,project){
 if(value===null)return null;
 if(!value||!/^[a-f0-9]{64}$/.test(value.packet_id)||!value.manifest||hash(Buffer.from(stable(value.manifest)))!==value.packet_id
  ||value.manifest.schema!=='fpw-queue-packet-v1'||value.manifest.project_id!==project.snapshot.project_id
  ||value.manifest.session_id!==project.session||value.manifest.revision!==project.snapshot.revision
  ||value.manifest.project_head!==project.snapshot.commit_id||value.manifest.repository!==project.identity
  ||!Array.isArray(value.items)||!Array.isArray(value.blockers)||!Array.isArray(value.manifest.documents)
  ||value.manifest.documents.length>128||value.items.length!==value.manifest.tasks.length)throw Error('Neplatný balíček fronty.');
 for(let i=0;i<value.items.length;i++)if(value.items[i].id!==value.manifest.tasks[i].id||typeof value.items[i].eligible!=='boolean')throw Error('Nesouhlasí položky fronty.');
 return value;
}
async function verified(file,sha,cache){
 const real=await fs.realpath(file),stat=await fs.stat(file);
 if(!stat.isFile()||(stat.mode&0o222)||stat.size>1024*1024||(process.getuid&&stat.uid!==process.getuid()))throw Error('Neplatný blob fronty.');
 const own=await fs.lstat(file);
 if(own.isSymbolicLink()&&real!==path.join(cache,sha+'.txt'))throw Error('Odkaz míří mimo pinned cache.');
 if(!own.isSymbolicLink()&&real!==path.resolve(file))throw Error('Neplatná cesta blobu.');
 const raw=await fs.readFile(file);if(hash(raw)!==sha)throw Error('Obsah pinned blobu byl změněn.');return raw;
}
async function blob(cache,raw,sha){
 await bridge.safeDirectory(cache);const file=path.join(cache,sha+'.txt');
 try{await verified(file,sha,cache);return file;}catch(error){if(error.code!=='ENOENT')throw error;}
 const temporary=path.join(cache,'.'+crypto.randomUUID()+'.tmp');
 try{
  const handle=await fs.open(temporary,'wx',0o400);
  try{await handle.writeFile(raw);await handle.sync();}finally{await handle.close();}
  await fs.rename(temporary,file);
  if(process.platform!=='win32'){const dir=await fs.open(cache,'r');try{await dir.sync();}finally{await dir.close();}}
 }finally{await fs.rm(temporary,{force:true});}
 return file;
}
async function link(source,target,sha,cache,io=fs){
 await bridge.safeDirectory(path.dirname(target));
 try{await verified(target,sha,cache);return 'existing';}catch(error){if(error.code!=='ENOENT')throw error;}
 // Only verified content-addressed cache is a source; never a Workspace working file.
 await verified(source,sha,cache);
 const fallback=e=>['EXDEV','EPERM','EACCES','ENOSYS','ENOTSUP','EOPNOTSUPP'].includes(e.code);
 let method='hardlink';const temporary=path.join(path.dirname(target),'.'+crypto.randomUUID()+'.tmp');
 try{
  try{await io.link(source,temporary);}catch(error){
   if(!fallback(error))throw error;
   try{await io.symlink(path.relative(path.dirname(temporary),source),temporary);method='symlink';}
   catch(error){if(!fallback(error))throw error;await io.copyFile(source,temporary,require('node:fs').constants.COPYFILE_EXCL);await fs.chmod(temporary,0o400);method='copy';}
  }
  await verified(temporary,sha,cache);
  if(process.platform!=='win32'){const h=await fs.open(temporary,'r');try{await h.sync();}finally{await h.close();}}
  await fs.rename(temporary,target);
  if(process.platform!=='win32'){const dir=await fs.open(path.dirname(target),'r');try{await dir.sync();}finally{await dir.close();}}
 }finally{await fs.rm(temporary,{force:true});}
 return method;
}
async function sourceBaseline(project,value){
 const repo=await bridge.repository(project.repository,project.identity);
 const file=path.join(project.root,'packets',value.packet_id,'source-baseline.json');
 let baseline;
 try{baseline=JSON.parse(await bridge.read(file));}
 catch(error){if(error.code!=='ENOENT')throw error;}
 if(baseline!==undefined&&(!baseline||baseline.packet_id!==value.packet_id||baseline.repository!==project.identity
  ||typeof baseline.commit!=='string'||!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(baseline.commit)))throw Error('Neplatný výchozí commit předání.');
 const commit=baseline?.commit??value.manifest.repository_commit??repo.commit;
 if(typeof commit!=='string'||!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(commit))throw Error('Neplatný zdrojový commit.');
 try{await bridge.git(repo.root,'merge-base','--is-ancestor',commit,repo.commit);}
 catch(error){throw Error('Zdrojová historie nenavazuje na předání nebo není dostupná. Obnovte historii nebo předejte nový balíček.');}
 if(!baseline)await bridge.atomic(file,JSON.stringify({packet_id:value.packet_id,repository:project.identity,commit}));
 return {commit,current_commit:repo.commit};
}
async function synchronize(project,request){
 const response=await request(project,'queue',{}),value=validate(response.queue,project);
 project.queue=value;
 if(value&&!value.blockers.length){
  const root=path.join(project.root,'packets',value.packet_id),cache=path.join(project.root,'queue-cache');
  try{const old=JSON.parse(await bridge.read(path.join(root,'manifest.json')));if(hash(Buffer.from(stable(old)))!==value.packet_id)throw Error('Manifest byl změněn.');}catch(error){if(error.code!=='ENOENT')throw error;}
  await sourceBaseline(project,value);
  for(const doc of value.manifest.documents){
   if(!/^[a-f0-9]{64}$/.test(doc.sha256))throw Error('Neplatný digest podkladu.');
   const target=path.join(root,'documents',doc.sha256+'.txt');
   try{await verified(target,doc.sha256,cache);continue;}catch(error){if(error.code!=='ENOENT')throw error;}
   let source=path.join(cache,doc.sha256+'.txt');
   try{await verified(source,doc.sha256,cache);}catch(error){if(error.code!=='ENOENT')throw error;
    const result=await request(project,'queue-document',{packet_id:value.packet_id,artifact_id:doc.artifact_id});
    const raw=Buffer.from(result.content_base64,'base64');if(result.packet_id!==value.packet_id||result.artifact_id!==doc.artifact_id||hash(raw)!==doc.sha256||raw.length!==doc.bytes)throw Error('Neshoda exportovaného podkladu.');
    source=await blob(cache,raw,doc.sha256);
   }
   await link(source,target,doc.sha256,cache);
  }
  // Recheck live eligibility before publishing any pointer to a prepared generation.
  const current=validate((await request(project,'queue',{})).queue,project);
  if(!current||current.packet_id!==value.packet_id||current.blockers.length)throw Error('Balíček se během exportu změnil.');
  await bridge.atomic(path.join(root,'manifest.json'),stable(value.manifest));
  await bridge.atomic(path.join(root,'AGENT.md'),'# Předání fronty\n\n'+value.manifest.instructions+'\n\nManifest: manifest.json\nAktuální stav: ../../queue.json (pouze poslední známý stav; před odesláním synchronizujte).\n'
   +'Completion: ../../inbox/<UUID>.json; fields: message_id, task_id, kind="completed", body, revision=manifest.revision, repository_commit=actual HEAD, queue_packet_id, reported_by="agent", evidence={tests,diff}.\n'
   +'Přiložte i přesné checklist změny, pokud úkol má checklist. Zprávu publikujte přes dočasný soubor a rename; stejné UUID nikdy nepoužijte s jinými bajty.\n'
   +'Pravidla z manifestu a místní AGENTS.md načtěte explicitně; rozpory sami nepřekrývejte. Hlášení není lidská akceptace.\n');
  project.queue=current;
 }
 await bridge.atomic(path.join(project.root,'queue.json'),JSON.stringify(project.queue));
 return project.queue;
}
async function handoff(project,taskId,request){
 const value=await synchronize(project,request);
 if(!value||value.blockers.length||!value.items.find(i=>i.id===taskId)?.eligible)throw Error('Navazující, stale nebo nepřijatá položka je pouze k prohlížení.');
 const root=path.join(project.root,'packets',value.packet_id);
 for(const doc of value.manifest.documents)await verified(path.join(root,'documents',doc.sha256+'.txt'),doc.sha256,path.join(project.root,'queue-cache'));
 return {manifest:path.join(root,'manifest.json'),instructions:path.join(root,'AGENT.md'),inbox:path.join(project.root,'inbox'),packet_id:value.packet_id};
}
module.exports={sourceBaseline,stable,validate,verified,blob,link,synchronize,handoff};
