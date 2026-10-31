// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
// Real HTTP/filesystem/backend; only the editor surface is replaced.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const crypto=require('node:crypto'),http=require('node:http'),Module=require('node:module');
const ui=require('../extensions/workspace-bridge/sidebar');
(async()=>{
 const fixture=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
 const commands=new Map(),views=new Map(),subscriptions=[],errors=[],panels=[],opened=[];let clipboard='',kind='completed';
 let saved=JSON.stringify({pairing:fixture.pairing,mappings:fixture.mappings}),duringInput=null;
 const bridge=require('../extensions/workspace-bridge/bridge');
 class Emitter{event=()=>({dispose(){}});fire(){}dispose(){}}
 const vscode={env:{clipboard:{writeText:async value=>{clipboard=value;}}},StatusBarAlignment:{Left:1},ViewColumn:{Active:1},
  EventEmitter:Emitter,ThemeIcon:class{constructor(id){this.id=id;}},TreeItem:class{constructor(label,state){this.label=label;this.collapsibleState=state;}},
  TreeItemCollapsibleState:{None:0,Collapsed:1,Expanded:2},Uri:{file:fsPath=>({fsPath})},
  commands:{registerCommand:(id,fn)=>{commands.set(id,fn);return{dispose(){}};}},
  workspace:{isTrusted:true,getConfiguration:()=>({get:()=>false}),openTextDocument:async doc=>doc},
  window:{visibleTextEditors:[],createOutputChannel:()=>({appendLine:message=>errors.push(message),dispose(){}}),createStatusBarItem:()=>({show(){},dispose(){}}),
   createTreeView:(id,options)=>{const view={visible:true,provider:options.treeDataProvider,onDidChangeVisibility:()=>({dispose(){}}),dispose(){}};views.set(id,view);return view;},
   createWebviewPanel:(_id,title,_column,options)=>{const panel={title,options,webview:{html:''},onDidDispose:()=>({dispose(){}}),dispose(){}};panels.push(panel);return panel;},
   showTextDocument:async doc=>{opened.push(doc);if(doc.fsPath)await fs.access(doc.fsPath);},
   showQuickPick:async items=>items[0]?.kind?items.find(item=>item.kind===kind):typeof items[0]==='string'?kind:items[0],showInputBox:async()=>{if(duringInput)await duringInput();return '<script>verified evidence</script>';},
   showWarningMessage:async()=>'Odeslat',showInformationMessage:async()=>{},showErrorMessage:async message=>{errors.push(message);}}};
 const load=Module._load;Module._load=function(name,...args){return name==='vscode'?vscode:load.call(this,name,...args);};
 const extension=require('../extensions/workspace-bridge/extension');Module._load=load;
 const context={subscriptions,extensionPath:path.resolve('extensions/workspace-bridge'),globalStorageUri:{fsPath:fixture.storage},
  globalState:{get:name=>name==='connection'?fixture.pairing.connection_id:undefined,update:async()=>{}},
  secrets:{get:async()=>saved,store:async(_key,value)=>{saved=value;}}};
 function request(route,body,token){return new Promise((resolve,reject)=>{
  const raw=JSON.stringify(body),req=http.request(new URL(route,fixture.pairing.endpoint),{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(raw)}},response=>{let text='';response.on('data',chunk=>text+=chunk);response.on('end',()=>{let value;try{value=JSON.parse(text);}catch(_){value=text;}resolve({status:response.statusCode,value});});});req.on('error',reject);req.end(raw);
 });}
 try{
  const api=await extension.activate(context),sidebar=api.sidebar;
  assert.equal(views.size,5);assert.equal(sidebar.projects().length,2);assert.deepEqual(errors,[]);
  let project=sidebar.projects().find(p=>p.snapshot.project_id===fixture.project_id);
  assert.equal(project.panel.export_documents,false);
  const catalog=await bridge.connectionRequest(fixture.pairing,{action:'status'}),mapping=catalog.mappings.find(m=>m.project_id===fixture.project_id);
  const grant=await request('/v1/ide-bridge/connection/map',{connection_id:fixture.pairing.connection_id,project_id:fixture.project_id,
   enabled:true,expected_head:fixture.head,expected_mapping:mapping.session_id,repository:mapping.repository,
   editor_workspace:mapping.editor_workspace,instructions:mapping.instructions,export_documents:true},fixture.admin_token);
  assert.equal(grant.status,200,JSON.stringify(grant.value));
  await commands.get('workspaceBridge.sync')();project=sidebar.projects().find(p=>p.snapshot.project_id===fixture.project_id);
  assert.equal(project.panel.export_documents,true);assert.notEqual(project.session,mapping.session_id);
  const root={kind:'project',projectId:fixture.project_id};
  let task=sidebar.children('tasks',root).find(row=>row.taskId==='TASK-01');assert.ok(task);
  assert.ok(sidebar.treeItem(task).command.command==='workspaceBridge.showTask');
  await commands.get('workspaceBridge.showTask')(task);
  assert.equal(panels[0].options.enableScripts,false);
  assert.match(panels[0].webview.html,/&lt;script&gt;/);assert.ok(!panels[0].webview.html.includes('<script>'));
  assert.match(panels[0].webview.html,/default-src 'none'/);
  const docs=sidebar.children('documents',root);assert.ok(docs.some(item=>item.doc.artifact_id===fixture.document_id));
  await commands.get('workspaceBridge.showDocument')(docs.find(item=>item.doc.artifact_id===fixture.document_id));
  const exported=opened.at(-1).fsPath;assert.ok(exported.endsWith('.txt'));
  assert.equal(await fs.readFile(exported,'utf8'),fixture.document_body);
  const rules=sidebar.children('rules',root);assert.ok(rules.some(item=>item.kind==='localRule'&&item.rule.relative==='AGENTS.md'));
  assert.ok(rules.some(item=>item.kind==='localRule'&&item.rule.relative===' space/AGENTS.md'));
  assert.ok(rules.some(item=>item.doc?.agent_rules));
  await commands.get('workspaceBridge.handoff')(task);
  const manifest=JSON.parse(await fs.readFile(path.join(project.root,'agent-context.json'),'utf8'));
  assert.equal(manifest.project_id,fixture.project_id);assert.equal(manifest.task_id,'TASK-01');
  assert.equal(manifest.project_commit,fixture.head);assert.equal(manifest.rules_precedence,'not-resolved');
  assert.ok(manifest.documents.some(doc=>doc.local));assert.ok(manifest.documents.some(doc=>doc.agent_rules));
  const originalRequest=bridge.connectionRequest;
  bridge.connectionRequest=async(...args)=>{const value=await originalRequest(...args);if(args[1].action==='panel')value.documents.find(doc=>doc.agent_rules).available=false;return value;};
  const previousClipboard=clipboard;await commands.get('workspaceBridge.handoff')(task);
  assert.equal(clipboard,previousClipboard);assert.ok(errors.some(error=>error.includes('nedostupná pravidla')));bridge.connectionRequest=originalRequest;await sidebar.refresh();errors.length=0;
  assert.match(clipboard,/Context Manifest/);
  const agentBytes=await fs.readFile(path.join(fixture.repository,'AGENTS.md'),'utf8');assert.equal(agentBytes,'Local agent instructions.\n');
  await assert.rejects(ui.localFile(project,'../escape'),/cesta/);
  await assert.rejects(ui.localFile(project,'linked.txt'),/symlink/);
  await commands.get('workspaceBridge.compose')(task);
  project=sidebar.projects().find(p=>p.snapshot.project_id===fixture.project_id);
  let messages=sidebar.children('messages',root);assert.equal(messages.length,1);
  assert.match(sidebar.treeItem(messages[0]).description,/čeká na posouzení/);
  const proposal=messages[0].entry;
  const forbidden=await request('/v1/ide-bridge/review',{},fixture.pairing.token);assert.notEqual(forbidden.status,200);
  const review=await request('/v1/ide-bridge/review',{project_id:fixture.project_id,session_id:proposal.session_id,
   message_id:proposal.message.message_id,decision:'accepted',note:'Reviewed by user.',expected_head:fixture.head,operation_id:crypto.randomUUID()},fixture.admin_token);
  assert.equal(review.status,200,JSON.stringify(review.value));assert.equal(review.value.state,'completed');
  await commands.get('workspaceBridge.sync')();
  project=sidebar.projects().find(p=>p.snapshot.project_id===fixture.project_id);
  assert.notEqual(project.session,proposal.session_id);
  assert.equal(project.snapshot.tasks.find(t=>t.id==='TASK-01').checked,true);
  messages=sidebar.children('messages',root);assert.equal(messages.length,1);assert.equal(sidebar.treeItem(messages[0]).description,'Přijato');
  kind='message';await commands.get('workspaceBridge.compose')(root);
  messages=sidebar.children('messages',root);assert.ok(messages.some(row=>row.entry.message.task_id===null));
  assert.equal(sidebar.children('messages',{kind:'project',projectId:fixture.other_project}).length,0);
  await commands.get('workspaceBridge.filterOpen')();assert.ok(!sidebar.children('tasks',root).some(row=>row.taskId==='TASK-01'));
  duringInput=()=>bridge.git(fixture.repository,'-c','user.name=Test','-c','user.email=test@example.invalid','-c','commit.gpgSign=false','commit','--allow-empty','-m','Assignment changed while typing');
  await commands.get('workspaceBridge.compose')(root);duringInput=null;
  assert.ok(sidebar.children('messages',root).some(row=>row.entry.draft),'changed assignment must retain a visible unsent draft');
  await commands.get('workspaceBridge.sync')();
  assert.ok(sidebar.children('messages',root).some(row=>row.entry.draft),'draft must survive mapping refresh');
  assert.throws(()=>ui.validateSnapshot({...project.snapshot,tasks:[{...project.snapshot.tasks[0],parent_id:'FOREIGN'}]}),/hierarchie/);
  await request('/v1/ide-bridge/connection/revoke',{connection_id:fixture.pairing.connection_id},fixture.admin_token);
  await commands.get('workspaceBridge.sync')();
  project=sidebar.projects().find(p=>p.snapshot.project_id===fixture.project_id);assert.ok(project.error);
  const before=opened.length;await commands.get('workspaceBridge.showDocument')(docs[0]);assert.equal(opened.length,before);
  assert.ok(errors.some(error=>error.includes('aktuální projektové zadání')));
  console.log(JSON.stringify({views:views.size,review:'accepted',project_message:true,handoff:true,revocation:true}));
 }finally{for(const disposable of subscriptions)disposable.dispose();}
})().catch(error=>{console.error(error);process.exitCode=1;});
