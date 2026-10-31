// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const queue=require('../extensions/workspace-bridge/queue');
(async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'queue-cache-'));
 try{
  const bridge=require('../extensions/workspace-bridge/bridge');
  const repo=path.join(root,'repo');await fs.mkdir(repo);await bridge.git(repo,'init');
  await bridge.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','base');
  const base=await bridge.git(repo,'rev-parse','HEAD');
  const project={root:path.join(root,'storage'),repository:repo,identity:repo};
  const value={packet_id:'a'.repeat(64),manifest:{repository_commit:null}};
  assert.equal((await queue.sourceBaseline(project,value)).commit,base);
  await bridge.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','advance');
  assert.equal((await queue.sourceBaseline(project,value)).commit,base);
  await bridge.git(repo,'checkout','-b','feature');
  await bridge.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','feature');
  await bridge.git(repo,'checkout','-b','target',base);
  await bridge.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','merge','--no-ff','feature','-m','merge');
  assert.equal((await queue.sourceBaseline(project,value)).commit,base);
  const legacy={packet_id:'b'.repeat(64),manifest:{repository_commit:base}};
  assert.equal((await queue.sourceBaseline(project,legacy)).commit,base);
  await assert.rejects(queue.sourceBaseline({...project,identity:'wrong'},value));
  await bridge.git(repo,'checkout','--orphan','unrelated');
  await bridge.git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','other');
  await assert.rejects(queue.sourceBaseline(project,value),/historie/);
  const baseline=path.join(project.root,'packets',value.packet_id,'source-baseline.json');
  await fs.writeFile(baseline,'{"commit":"HEAD"}');
  await assert.rejects(queue.sourceBaseline(project,value),/výchozí/);
  const raw=Buffer.from('Immutable exported evidence.'),sha=crypto.createHash('sha256').update(raw).digest('hex'),cache=path.join(root,'cache');
  const source=await queue.blob(cache,raw,sha),hard=path.join(root,'hard','doc.txt');
  assert.equal(await queue.link(source,hard,sha,cache),'hardlink');assert.equal((await fs.stat(source)).ino,(await fs.stat(hard)).ino);
  const exdev=()=>{const e=Error('other filesystem');e.code='EXDEV';throw e;};
  const sym=path.join(root,'sym','doc.txt');assert.equal(await queue.link(source,sym,sha,cache,{...fs,link:exdev}),'symlink');await queue.verified(sym,sha,cache);
  const copy=path.join(root,'copy','doc.txt');assert.equal(await queue.link(source,copy,sha,cache,{...fs,link:exdev,symlink:exdev}),'copy');assert.notEqual((await fs.stat(source)).ino,(await fs.stat(copy)).ino);
  const evil=path.join(root,'evil','doc.txt');await fs.mkdir(path.dirname(evil),{mode:0o700});await fs.symlink(copy,evil);await assert.rejects(queue.verified(evil,sha,cache));
  await fs.chmod(source,0o600);await assert.rejects(queue.verified(hard,sha,cache));await fs.writeFile(source,'Tampered');await fs.chmod(source,0o400);await assert.rejects(queue.verified(hard,sha,cache));
  assert.equal((await fs.readFile(copy)).toString(),raw.toString());
  console.log('queue cache: hardlink/symlink/copy, immutable modes, tamper and outside-cache rejection OK');
 }finally{await fs.rm(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
