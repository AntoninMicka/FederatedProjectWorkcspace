// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const queue=require('../extensions/workspace-bridge/queue');
(async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'queue-cache-'));
 try{
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
