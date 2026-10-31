// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const bridge = require('./bridge');
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const idPattern = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$/;
const kinds={message:'Zpráva',clarification:'Dotaz',progress:'Částečné splnění',completed:'Návrh dokončení'};

function validateSnapshot(snapshot) {
  if (!snapshot || typeof snapshot.project_id !== 'string' || typeof snapshot.revision !== 'string'
      || !/^[a-f0-9]{40,64}$/.test(snapshot.commit_id) || !Array.isArray(snapshot.tasks) || snapshot.tasks.length > 1000)
    throw Error('Neplatný projektový snapshot.');
  const tasks = new Map();
  for (const task of snapshot.tasks) {
    if (!idPattern.test(task.id) || tasks.has(task.id) || typeof task.title !== 'string'
        || typeof task.checked !== 'boolean' || !Array.isArray(task.checklist)) throw Error('Neplatná identita úkolu.');
    tasks.set(task.id, task);
  }
  for (const task of tasks.values()) {
    const seen = new Set([task.id]); let parent = task.parent_id;
    while (parent) {
      if (!tasks.has(parent) || seen.has(parent)) throw Error('Neplatná hierarchie úkolů.');
      seen.add(parent); parent = tasks.get(parent).parent_id;
    }
  }
  return snapshot;
}
function references(task) {
  const result = new Set(task?.source?.artifact_id ? [task.source.artifact_id] : []);
  for (const match of (task?.description || '').matchAll(/artifacts\/([a-f0-9-]{36})\//g)) result.add(match[1]);
  return result;
}
function detailHTML(project, task) {
  return `<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';"><style>
body{font-family:var(--vscode-font-family);color:var(--vscode-editor-foreground);padding:20px;max-width:900px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit}small{opacity:.8}.warning{color:var(--vscode-editorWarning-foreground)}</style></head><body>
<p class="warning">${escape(project.error || (project.state?.stale || project.panel?.stale ? 'Zastaralý export; obnovte synchronizaci.' : 'Stav úkolu mění až posouzení ve Workspace.'))}</p>
<small>${escape(project.snapshot.project_title)} · ${escape(task.id)}</small><h1>${escape(task.title)}</h1>
<p>${task.checked ? '✓ Dokončeno' : '○ Otevřeno'} · ${escape(task.type || 'úkol')}</p><pre>${escape(task.description)}</pre>
<h2>Podmínky splnění</h2><ul>${task.checklist.map(item => `<li>${item.checked?'☑':'☐'} ${escape(item.text)}</li>`).join('')}</ul>
<p>Závisí na: ${escape((task.depends_on || []).join(', ') || 'bez závislostí')}</p>
<small>Projektový commit: ${escape(project.snapshot.commit_id)}<br>Revize exportu: ${escape(project.snapshot.revision)}</small></body></html>`;
}
async function localFile(project, relative) {
  if (typeof relative !== 'string' || path.isAbsolute(relative) || relative.split(/[\\/]/).some(p => !p || p==='.' || p==='..'))
    throw Error('Neplatná cesta v repozitáři.');
  const repo = await bridge.repository(project.repository, project.identity);
  const file = path.resolve(repo.root, relative), real = await fs.realpath(file);
  if (real !== file || !real.startsWith(repo.root + path.sep)) throw Error('Soubor nebo symlink je mimo přiřazený repozitář.');
  const raw = await bridge.read(real);
  return {path: real, raw, sha256: hash(Buffer.from(raw))};
}
async function localRules(project) {
  await bridge.repository(project.repository, project.identity);
  const names = new Set(['AGENTS.md']);
  for (const name of await bridge.ruleFiles(project.repository)) names.add(name);
  if (names.size > 100) throw Error('Příliš mnoho lokálních pravidel.');
  const result = [];
  for (const name of names) {
    try {
      const item = await localFile(project, name);
      result.push({title: name, relative: name, sha256: item.sha256,
        scope: path.dirname(name)==='.' ? {kind:'project'} : {kind:'directory',path:path.dirname(name)}, local: true});
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return result;
}

function createSidebar(vscode, context, hooks) {
  // Keep the transport usable in hosts that only expose the command surface.
  if (!vscode.window.createTreeView) return {refresh: async () => {}};
  let projects = [], selected = null, openOnly = false, loading = null, detail = null, generation = 0, loadingGeneration = 0;
  const views = [], events = [];
  const find = item => projects.find(p => p.snapshot.project_id === item?.projectId);
  const taskOf = item => find(item)?.snapshot.tasks.find(t => t.id === item?.taskId);
  function row(project, kind, value = {}) {return {kind, projectId: project.snapshot.project_id, ...value};}
  const available = project => !project.error && !project.state?.stale && project.panel
    && project.panel.revision === project.snapshot.revision && !project.panel.stale;
  function assertCurrent(project) {if (!project || !available(project)) throw Error('Nejprve obnovte spojení a aktuální projektové zadání.');}
  function refreshEvents() {for (const event of events) event.fire();}
  function clear(keepSelection=false) {
    generation++;projects=[];if(!keepSelection)selected=null;refreshEvents();
    if(detail)detail.webview.html=keepSelection?'<p>Načítám aktuální přiřazení…</p>':'<p>Workspace je odpojený.</p>';
  }
  async function refresh(remote = true) {
    if (!vscode.workspace.isTrusted) {projects=[];refreshEvents();return;}
    if (loading) return loadingGeneration===generation ? loading : loading.then(()=>refresh(remote));
    const version=generation;loadingGeneration=version;
    loading = (async () => {
      try {
        const next=await hooks.projects();if(version!==generation)return;projects=next;
        for (const project of projects) {
          validateSnapshot(project.snapshot);
          try {project.localRules = await localRules(project);} catch (error) {project.error = error.message;}
          try {
            project.panel = JSON.parse(await bridge.read(path.join(project.root, 'panel.json')));
            if (project.panel.session_id !== project.session || project.panel.revision !== project.snapshot.revision) project.panel = null;
          } catch (_) {project.panel = null;}
          if (remote && !project.error && views.some(view => view.visible) && !project.legacy) {
            try {
              const value = await hooks.request(project, 'panel', {});
              if(version!==generation)return;
              if (value.session_id !== project.session || value.project_id !== project.snapshot.project_id
                  || value.revision !== project.snapshot.revision || !Array.isArray(value.documents) || !Array.isArray(value.messages))
                throw Error('Neshoda projektového panelu.');
              project.panel = value;
              await bridge.atomic(path.join(project.root, 'panel.json'), JSON.stringify(value));
            } catch (error) {project.error = error.message;}
          }
        }
      } catch (error) {
        projects = []; hooks.error?.(error.message);
      }
      refreshEvents();
      if (detail && selected) {
        const project = find(selected), task = taskOf(selected);
        detail.webview.html = project && task ? detailHTML(project, task) : '<p>Úkol již není v aktuálním přiřazení.</p>';
      }
    })().finally(() => {loading = null;});
    return loading;
  }
  function children(kind, item) {
    if (!item) return projects.map(project => row(project, 'project', {view: kind}));
    const project = find(item); if (!project) return [];
    if (kind === 'tasks') {
      const tasks = project.snapshot.tasks;
      function show(task) {return !openOnly || !task.checked || tasks.some(t => t.parent_id===task.id && show(t));}
      return tasks.filter(t => (t.parent_id || null) === (item.taskId || null) && show(t))
        .map(task => row(project, 'task', {taskId: task.id}));
    }
    if (item.kind !== 'project') return [];
    if (kind === 'messages') {
      const entries = new Map((project.panel?.messages || []).map(entry => [entry.message.message_id, entry]));
      for (const entry of project.pending || []) if (!entries.has(entry.message.message_id)) entries.set(entry.message.message_id, entry);
      return [...entries.values()].map(entry => row(project, 'message', {entry}));
    }
    if (kind === 'rules') return [row(project, 'instructions'), ...(project.localRules || []).map(rule => row(project, 'localRule', {rule})),
      ...(project.panel?.documents || []).filter(doc => doc.agent_rules).map(doc => row(project, 'document', {doc}))];
    const task = selected?.projectId === project.snapshot.project_id ? taskOf(selected) : null;
    const ids = task ? references(task) : null;
    return (project.panel?.documents || []).filter(doc => !ids || ids.has(doc.artifact_id))
      .map(doc => row(project, 'document', {doc}));
  }
  function treeItem(item) {
    const project = find(item); let label, description = '', icon = 'file-text', collapsed = vscode.TreeItemCollapsibleState.None, command;
    if (item.kind === 'project') {
      label = project.snapshot.project_title; description = project.error ? 'Nedostupné · uložený export' : project.state?.stale || project.panel?.stale ? 'Zastaralé' : project.snapshot.commit_id.slice(0,8);
      if(item.view==='messages'&&project.panel?.history_truncated)description+=' · poslední zprávy';
      icon = project.error || project.state?.stale || project.panel?.stale ? 'warning' : 'project'; collapsed = vscode.TreeItemCollapsibleState.Expanded;
    } else if (item.kind === 'task') {
      const task = taskOf(item); label = task.title; description = task.id; icon = task.checked ? 'pass' : 'circle-outline';
      if (project.snapshot.tasks.some(t => t.parent_id===task.id)) collapsed = vscode.TreeItemCollapsibleState.Collapsed;
      command = 'workspaceBridge.showTask';
    } else if (item.kind === 'document') {
      label = item.doc.title; description = item.doc.agent_rules ? JSON.stringify(item.doc.scope || {}) : item.doc.available ? 'Připnutý podklad' : 'Nedostupný text'; icon = item.doc.agent_rules ? 'law' : 'file-text'; command = 'workspaceBridge.showDocument';
    } else if (item.kind === 'message') {
      const entry = item.entry, review = entry.review;
      label = (entry.message.task_id || 'Projekt') + ' · ' + entry.message.body.slice(0,80);
      description = entry.draft ? 'Návrh · nebyl odeslán' : entry.old_session && !entry.receipt ? 'Stará relace · vyžaduje nové posouzení'
        : review?.state==='completed' ? (review.outcome==='stale'?'Zastaralé · neaplikováno':review.request.decision==='accepted'?'Přijato':'Odmítnuto')
        : review ? 'Review připraveno' : !entry.receipt ? 'Čeká na odeslání' : entry.receipt.status==='stale' ? 'Doručeno ze staré revize' : 'Doručeno · čeká na posouzení';
      icon = 'mail'; command = 'workspaceBridge.showMessage';
    } else if (item.kind === 'localRule') {label = item.rule.title; description = 'Lokální · '+JSON.stringify(item.rule.scope); icon = 'law'; command = 'workspaceBridge.showLocalRule';}
    else {label = 'INSTRUCTIONS.md'; description = 'Pokyny připojení'; icon = 'law'; command = 'workspaceBridge.showInstructions';}
    const result = new vscode.TreeItem(label, collapsed); result.id = `${item.projectId}:${item.kind}:${item.taskId || item.doc?.artifact_id || item.rule?.relative || item.entry?.message.message_id || ''}:${item.view || ''}`;
    result.description = description; result.tooltip = label+'\n'+description; result.iconPath = new vscode.ThemeIcon(icon); result.contextValue = item.kind;
    if (command) result.command = {command, title: label, arguments: [item]};
    return result;
  }
  for (const kind of ['tasks','messages','documents','rules']) {
    const event = new vscode.EventEmitter(); events.push(event); context.subscriptions.push(event);
    const view = vscode.window.createTreeView('workspaceBridge.'+kind, {treeDataProvider: {
      onDidChangeTreeData: event.event, getTreeItem: treeItem, getChildren: item => children(kind,item)}});
    views.push(view); context.subscriptions.push(view, view.onDidChangeVisibility(() => refresh()));
  }
  function register(name, action) {
    context.subscriptions.push(vscode.commands.registerCommand('workspaceBridge.'+name, async item => {
      try {if (!vscode.workspace.isTrusted) throw Error('Vyžadován důvěryhodný workspace.'); return await action(item);}
      catch (error) {await vscode.window.showErrorMessage(error.message);}
    }));
  }
  async function selectedItem(item, requireTask = true) {
    if (find(item) && (!requireTask || taskOf(item))) return item;
    const options = projects.flatMap(project => requireTask ? project.snapshot.tasks.map(task => ({label: task.title,
      description: project.snapshot.project_title+' · '+task.id, item: row(project,'task',{taskId:task.id})}))
      : [{label:project.snapshot.project_title,item:row(project,'project')}]);
    return (await vscode.window.showQuickPick(options,{placeHolder:requireTask?'Úkol Workspace':'Projekt Workspace'}))?.item;
  }
  async function saveBlob(project, raw) {
    const sha256 = hash(raw), file = path.join(project.root,'documents',sha256+'.txt');
    await bridge.atomic(file,raw); return {path:file,sha256,bytes:raw.length};
  }
  async function fetchDocument(project, doc) {
    assertCurrent(project);
    if (!doc.available) throw Error(doc.reason || 'Dokument není dostupný.');
    const result = await hooks.request(project,'document',{artifact_id:doc.artifact_id});
    if (result.project_id!==project.snapshot.project_id || result.session_id!==project.session
        || result.revision!==project.snapshot.revision || result.artifact_id!==doc.artifact_id
        || result.sha256!==doc.sha256 || result.stale || typeof result.content_base64!=='string') throw Error('Dokument neodpovídá připnuté revizi.');
    const raw=Buffer.from(result.content_base64,'base64');
    if (raw.length!==doc.bytes || raw.length>1024*1024 || hash(raw)!==doc.sha256) throw Error('Neshodují se bajty dokumentu.');
    return {...doc,...await saveBlob(project,raw),revision:project.snapshot.revision};
  }
  register('showTask',async item => {
    item=await selectedItem(item); if(!item)return; selected=item;
    if(!detail){detail=vscode.window.createWebviewPanel('workspaceTask','Úkol Workspace',vscode.ViewColumn.Active,{enableScripts:false,localResourceRoots:[]});
      context.subscriptions.push(detail,detail.onDidDispose(()=>{detail=null;}));}
    detail.title=taskOf(item).id; detail.webview.html=detailHTML(find(item),taskOf(item)); refreshEvents();
  });
  register('showDocument',async item => {const project=find(item); const file=await fetchDocument(project,item.doc);await vscode.window.showTextDocument(vscode.Uri.file(file.path));});
  register('showLocalRule',async item => {const project=find(item);const file=await localFile(project,item.rule.relative);await vscode.window.showTextDocument(vscode.Uri.file(file.path));});
  register('showInstructions',async item => {const project=find(item);await vscode.window.showTextDocument(vscode.Uri.file(path.join(project.root,'INSTRUCTIONS.md')));});
  register('showMessage',async item => {
    const e=item.entry;const text=`${kinds[e.message.kind]||e.message.kind} · ${e.message.task_id||'Projekt'}\n${e.message.body}\n\nRevize: ${e.message.revision}\n${e.draft||e.old_session&&!e.receipt?'Návrh není doručený; obsah předejte znovu až po posouzení aktuálního zadání.':e.review?.state==='completed'?(e.review.outcome||e.review.request.decision)+': '+e.review.request.note:'Čeká na posouzení ve Workspace.'}`;
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({content:text,language:'plaintext'}));
  });
  register('filterOpen',async()=>{openOnly=!openOnly;refreshEvents();});
  register('allDocuments',async()=>{selected=null;refreshEvents();});
  register('refreshPanel',async()=>{await hooks.synchronize();await refresh();});
  register('compose',async item => {
    item=await selectedItem(item,false);if(!item)return;const project=find(item);assertCurrent(project);
    const task=taskOf(item);
    const options=!task?['message']:task.type&&task.type!=='task'?['message','clarification']:['message','clarification','progress','completed'];
    const choiceKind=await vscode.window.showQuickPick(options.map(kind=>({label:kinds[kind],kind})),{placeHolder:'Typ zprávy'});
    const kind=choiceKind?.kind;if(!kind)return;
    let checklist;
    if(['completed','progress'].includes(kind)&&task.checklist.length){
      const choice=await vscode.window.showQuickPick(task.checklist.map((entry,index)=>({label:entry.text,picked:kind==='completed'||entry.checked,index})),{canPickMany:true,placeHolder:'Navrhované splněné podmínky (ostatní budou nesplněné)'});
      if(!choice)return; const chosen=new Set(choice.map(entry=>entry.index));checklist=task.checklist.map((_entry,index)=>({index,checked:chosen.has(index)}));
      if(kind==='completed'&&chosen.size!==task.checklist.length)throw Error('Pro část checklistu zvolte Částečné splnění.');
    }
    if(kind==='progress'&&!checklist?.length)throw Error('Úkol nemá checklist pro částečné splnění.');
    const body=await vscode.window.showInputBox({prompt:'Zpráva a skutečné důkazy k posouzení',ignoreFocusOut:true});if(!body)return;
    if(Buffer.byteLength(body)>16384)throw Error('Zpráva přesahuje 16 KiB.');
    if(await vscode.window.showWarningMessage(`${kinds[kind]} · ${task?.id||'Projekt'}\n${body}`,{modal:true},'Odeslat')!=='Odeslat')return;
    await bridge.repository(project.repository,project.identity);
    const message={message_id:crypto.randomUUID(),task_id:task?.id||null,kind,body,revision:project.snapshot.revision,
      repository_commit:await bridge.git(project.repository,'rev-parse','HEAD'),...(checklist?{checklist}:{})};
    const draft=path.join(project.root,'drafts',message.message_id+'.json');
    await bridge.atomic(draft,JSON.stringify(message,null,2));
    try {
      const current=await hooks.request(project,'panel',{});
      if(current.stale||current.revision!==message.revision||current.current_head!==project.snapshot.commit_id)
        throw Error('Zadání se během psaní změnilo.');
    } catch(error) {
      await vscode.window.showWarningMessage(`Zpráva nebyla odeslána a zůstala uložená jako návrh: ${draft}\n${error.message}`);
      await refresh(); return;
    }
    await bridge.atomic(path.join(project.root,'inbox',message.message_id+'.json'),JSON.stringify(message,null,2));
    await hooks.synchronize();await refresh();
  });
  register('handoff',async item => {
    item=await selectedItem(item);if(!item)return;const project=find(item);assertCurrent(project);const task=taskOf(item);
    const fresh=await hooks.request(project,'panel',{});
    if(fresh.stale||fresh.project_id!==project.snapshot.project_id||fresh.session_id!==project.session
        ||fresh.revision!==project.snapshot.revision||fresh.current_head!==project.snapshot.commit_id)throw Error('Neaktuální zadání nebo změněné oprávnění.');
    project.panel=fresh;
    await bridge.repository(project.repository,project.identity);
    const repositoryCommit=await bridge.git(project.repository,'rev-parse','HEAD'),ids=references(task),documents=[];
    if(project.panel.export_documents)for(const id of ids)
      if(!project.panel.documents.some(doc=>doc.artifact_id===id))throw Error('Odkazovaný podklad není v exportovaném katalogu: '+id);
    for(const doc of project.panel.documents){
      if(!doc.available){
        if(doc.agent_rules||ids.has(doc.artifact_id))throw Error('Nelze předat nedostupná pravidla nebo podklad: '+doc.title);
        continue;
      }
      if(doc.agent_rules&&doc.scope?.kind==='task'&&doc.scope.task_id!==task.id)continue;
      if(doc.agent_rules||ids.has(doc.artifact_id))documents.push(await fetchDocument(project,doc));
    }
    for(const rule of await localRules(project)){
      const file=await localFile(project,rule.relative);
      documents.push({...rule,...await saveBlob(project,Buffer.from(file.raw)),source:'local-working-tree',privacy:'local-only',repository_commit:repositoryCommit});
    }
    const instructions=await bridge.read(path.join(project.root,'INSTRUCTIONS.md'));
    const manifest={schema:'fpw-ide-context-v1',project_id:project.snapshot.project_id,task_id:task.id,
      documents_scope:project.panel.export_documents?'project':'disabled',
      context_status:project.panel.export_documents?'pinned':'task-only',privacy:'local-only',
      revision:project.snapshot.revision,project_commit:project.snapshot.commit_id,repository_commit:repositoryCommit,
      repository_dirty:Boolean(await bridge.git(project.repository,'status','--porcelain')),task,documents,
      transport:await saveBlob(project,Buffer.from(instructions)),rules_precedence:'not-resolved',
      notice:'Pravidla mají vlastní rozsah. Lokální a exportovaná pravidla se automaticky nepřekrývají; rozpory vyžadují posouzení. Předání nepřidává oprávnění ani nespouští agenta. Lokální manifest sám neautorizuje externí LLM požadavek.'
        +(project.panel.export_documents?'':' Export podkladů Workspace je vypnutý; předává se jen zadání a místní instrukce/pravidla.')};
    const current=JSON.parse(await bridge.read(path.join(project.root,'snapshot.json')));
    const verified=await hooks.request(project,'panel',{});
    if(verified.stale||verified.revision!==project.snapshot.revision||verified.current_head!==project.snapshot.commit_id)throw Error('Projekt nebo oprávnění se během předání změnily.');
    if(current.revision!==manifest.revision||await bridge.git(project.repository,'rev-parse','HEAD')!==repositoryCommit)throw Error('Kontext se během přípravy změnil. Opakujte předání.');
    const raw=JSON.stringify(manifest,null,2),file=path.join(project.root,'contexts',hash(Buffer.from(raw))+'.json');
    await bridge.atomic(file,raw);await bridge.atomic(path.join(project.root,'agent-context.json'),raw);
    await vscode.env.clipboard.writeText(`Úkol ${task.id}: ${task.title}\nPřipnutý Context Manifest: ${file}\n${manifest.notice}`);
    await vscode.window.showInformationMessage((project.panel.export_documents?'Připnuté zadání, podklady a pravidla jsou připravené.':'Export podkladů je vypnutý; připravené je pouze zadání a místní instrukce/pravidla.')+' Předání zkopírováno; běžící agent jej musí výslovně načíst.');
  });
  return {refresh,clear,children,treeItem,projects:()=>projects};
}
module.exports={createSidebar,validateSnapshot,detailHTML,references,localFile,localRules};
