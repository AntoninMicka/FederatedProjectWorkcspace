// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFile} = require('node:child_process');
const bridge = require('./bridge');
const queueBridge = require('./queue');
const {createSidebar} = require('./sidebar');
const {createUpdater} = require('./updater');
const coordination = require('./coordination');
const unified = require('./unified');

async function activate(context) {
  if (vscode.env.remoteName) { vscode.window.showWarningMessage('Workspace bridge zatím vyžaduje lokální IDE bez Remote SSH/WSL.'); return; }
  let running = null, queued = null, ownerUnsupportedUntil = 0;
  const output = vscode.window.createOutputChannel('Workspace bridge');
  context.subscriptions.push(output);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
  status.text = 'Workspace: odpojeno';
  status.command = context.globalState.get('connection') || context.globalState.get('session')
    ? 'workspaceBridge.sync' : 'workspaceBridge.connect';
  status.show();
  context.subscriptions.push(status);
  const privateRoot = path.join(context.globalStorageUri.fsPath, 'bridge-private');
  const mailbox = session => path.join(privateRoot, 'sessions', session);
  // One background poller per profile; other windows render its files (ADR 0090).
  const lease = coordination.createLease(privateRoot), backoff = coordination.createBackoff();
  context.subscriptions.push({dispose: () => { void lease.release().catch(() => {}); }});
  const reported = new Set();
  function reportOnce(key, text) { if (!reported.has(key)) { reported.add(key); output.appendLine(text); } }
  const sidebar = createSidebar(vscode, context, {projects: panelProjects, request: panelRequest,
    synchronize: () => synchronize(true), error: text => output.appendLine(text), ownerQueue: readOwnerQueue,
    open: (target, title) => offerOpen(target, title)});
  // Opening another project is always the user's choice, never automatic.
  async function offerOpen(target, title) {
    if (!target) return;
    const here = (vscode.workspace.workspaceFolders || []).some(folder => folder.uri.fsPath === target)
      || (vscode.workspace.workspaceFile?.scheme === 'file' && vscode.workspace.workspaceFile.fsPath === target);
    if (here) return;
    const choice = await vscode.window.showInformationMessage(`Projekt ${title} je v IDE přiřazený k ${target}.`, 'Otevřít v novém okně', 'Otevřít zde');
    if (choice) await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(target), {forceNewWindow: choice === 'Otevřít v novém okně'});
  }
  async function readOwnerQueue() {
    const parent = context.globalState.get('connection');
    if (!parent) return null;
    try { return unified.validateOwner(JSON.parse(await bridge.read(path.join(privateRoot, 'owner-queue.json'))), parent); }
    catch (error) { if (error.code !== 'ENOENT') reportOnce('owner:' + error.message, 'Společné pořadí fronty: ' + error.message); return null; }
  }
  async function refreshOwnerQueue(config) {
    if (Date.now() < ownerUnsupportedUntil) return;
    const file = path.join(privateRoot, 'owner-queue.json'), connection_id = config.pairing.connection_id;
    try {
      const value = await bridge.connectionRequest(config.pairing, {action: 'owner-queue'}, config.ca);
      const owner = {revision: value.revision, order: value.order, sessions: value.sessions,
        connection_id, fetched_at: new Date().toISOString()};
      unified.validateOwner(owner, connection_id);
      await bridge.atomic(file, JSON.stringify(owner));
    } catch (error) {
      if (error.status === 422 && /Unsupported connection action/.test(error.message)) {
        // Older Workspace: rows keep the order of each project (ADR 0090).
        ownerUnsupportedUntil = Date.now() + 600000;
        await bridge.atomic(file, JSON.stringify({unsupported: true, connection_id}));
        return;
      }
      // The last known order stays and is labelled with its time in the panel.
      output.appendLine('Společné pořadí fronty: ' + error.message);
    }
  }
  async function panelProjects() {
    if (!(context.globalState.get('connection') || context.globalState.get('session'))) return [];
    const config = await configuration(), result = [];
    const mappings = config.legacy ? {[config.pairing.session_id]: {repository: config.repository}} : config.mappings || {};
    for (const [session, local] of Object.entries(mappings)) {
      const root = mailbox(session);
      try {
        const snapshot = JSON.parse(await bridge.read(path.join(root, 'snapshot.json')));
        const state = JSON.parse(await bridge.read(path.join(root, 'STATUS.json')));
        const identity = JSON.parse(await bridge.read(path.join(root, 'SESSION.json')));
        if (identity.session_id !== session || identity.project_id !== snapshot.project_id || identity.revision !== snapshot.revision)
          throw Error('Neshoda identity lokálního exportu.');
        const pending = [];
        const histories=(await fs.readdir(path.join(privateRoot,'sessions'))).filter(n=>/^[a-f0-9-]{36}$/.test(n)).slice(-200);
        for(const prior of histories){
          const priorRoot=mailbox(prior);let info;
          try{info=JSON.parse(await bridge.read(path.join(priorRoot,'SESSION.json')));}catch(error){if(error.code==='ENOENT')continue;throw error;}
          if(info.project_id!==snapshot.project_id||info.connection_id!==(config.pairing.connection_id||null)||info.repository!==identity.repository)continue;
          for(const directory of ['inbox','drafts']){
            let names;try{names=await fs.readdir(path.join(priorRoot,directory));}catch(error){if(error.code==='ENOENT')continue;throw error;}
            for(const name of names.filter(n=>/^[a-f0-9-]{36}\.json$/.test(n)).slice(-100)){
              const message=JSON.parse(await bridge.read(path.join(priorRoot,directory,name)));
              if(message.message_id+'.json'!==name)throw Error('Neshoda identity lokální zprávy.');
              let receipt;try{receipt=JSON.parse(await bridge.read(path.join(priorRoot,'receipts',name)));}catch(error){if(error.code!=='ENOENT')throw error;}
              pending.push({message,receipt,session_id:prior,draft:directory==='drafts',old_session:prior!==session});
            }
          }
        }
        result.push({session,root,repository:local.repository,editor_workspace:local.editor_workspace,identity:identity.repository,snapshot,state,pending,
          legacy:config.legacy,error:state.error || (config.legacy?'Původní spojení: pro plný panel připojte Workspace schema-v2.':null)});
      } catch (error) {
        // A mapping without its first local export (or an inactive one) is
        // reported once per window, not on every refresh.
        if (error.code === 'ENOENT') reportOnce('panel:' + session, 'Panel ' + session + ': projekt zatím nemá lokální export (čeká na první synchronizaci nebo přiřazení již není aktivní).');
        else output.appendLine('Panel '+session+': '+error.message);
      }
    }
    return result;
  }
  async function panelRequest(project, action, payload) {
    const config = await configuration();
    if (config.legacy || !config.mappings?.[project.session]) throw Error('Projekt již není přiřazený.');
    await bridge.repository(project.repository,project.identity);
    return bridge.connectionRequest(config.pairing,{action,request:{session_id:project.session,...payload}},config.ca);
  }
  async function unavailable(session, error) {
    try {await bridge.atomic(path.join(mailbox(session),'STATUS.json'),JSON.stringify({stale:true,error:error.message,
      ...(error.busy?{busy:true}:{}),failed_at:new Date().toISOString()}));} catch (_) { /* original error is reported */ }
  }
  async function configuration() {
    const parent = context.globalState.get('connection');
    const key = parent || context.globalState.get('session');
    if (!key) throw new Error('Nejprve připojte Workspace.');
    const value = await context.secrets.get((parent ? 'connection:' : 'session:') + key);
    if (!value) throw new Error('Chybí přihlašovací údaje. Připojte Workspace znovu.');
    return {...JSON.parse(value), key, legacy: !parent};
  }
  async function persist(config) {
    await context.secrets.store('connection:' + config.pairing.connection_id,
      JSON.stringify({pairing: config.pairing, ca: config.ca, mappings: config.mappings || {}}));
    const previous = context.globalState.get('connection');
    await context.globalState.update('connection', config.pairing.connection_id);
    if (previous && previous !== config.pairing.connection_id) {sidebar.clear?.();await context.secrets.delete('connection:' + previous);}
  }
  async function catalog(config) {
    return bridge.connectionRequest(config.pairing, {action: 'status'}, config.ca);
  }
  const checkUpdates = createUpdater(vscode, context, async download => {
    if (!context.globalState.get('connection')) return null;
    const config = await configuration();
    return bridge.connectionRequest(config.pairing, {action: 'extension-update', download}, config.ca);
  }, text => output.appendLine(text));
  async function projectConnection() {
    const config = await configuration();
    if (config.legacy) return {...config, root: mailbox(config.pairing.session_id)};
    const current = await catalog(config);
    const items = current.mappings.filter(item => config.mappings?.[item.session_id] && item.bound);
    if (!items.length) throw new Error('Nejprve nastavte přiřazení projektů.');
    const selected = items.length === 1 ? items[0] : await vscode.window.showQuickPick(
      items.map(item => ({label: item.title, description: item.editor_workspace, mapping: item})), {placeHolder: 'Projekt Workspace'});
    if (!selected) return null;
    const item = selected.mapping || selected;
    return {...config, repository: config.mappings[item.session_id].repository,
      root: mailbox(item.session_id), pairing: {...config.pairing, ...item}};
  }
  // A run in flight may have read the inbox before this request: callers wait
  // for exactly one follow-up run instead of returning silently (ADR 0090).
  function synchronize(quiet = false) {
    if (!vscode.workspace.isTrusted || !(context.globalState.get('connection') || context.globalState.get('session'))) return Promise.resolve();
    if (!running) { running = runSynchronize(quiet).finally(() => { running = null; }); return running; }
    queued ||= running.catch(() => {}).then(() => { queued = null; return synchronize(quiet); });
    return queued;
  }
  async function runSynchronize(quiet) {
    status.command = 'workspaceBridge.sync';
    status.text = '$(sync~spin) ' + status.text.replace(/^\$\([^)]*\) /, '');
    let contention = false;
    try {
      const config = await configuration();
      let summary, warning = false;
      if (config.legacy) {
        const result = await bridge.sync(mailbox(config.pairing.session_id), config.pairing, config.repository, config.ca);
        status.text = result.stale ? 'Workspace: zastaralé zadání' : 'Workspace: propojeno';
        warning = result.stale;
        summary = result.stale ? 'Zadání je zastaralé. Pro aktuální revizi použijte Workspace: Nastavení projektů.' : 'Workspace synchronizován: 1 projekt.';
      } else {
        const current = await catalog(config);
        let count = 0, stale = 0, failed = 0, waitingReview = 0, busyProjects = 0;
        for (const [session, local] of Object.entries(config.mappings || {})) {
          let mapping = current.mappings.find(item => item.session_id === session);
          if (!mapping && !local.refresh) {
            try {
              const prior=JSON.parse(await bridge.read(path.join(mailbox(session),'SESSION.json')));
              const updated=current.mappings.find(item=>item.project_id===prior.project_id);
              if(updated&&updated.repository===prior.repository&&updated.editor_workspace===local.editor_workspace){
                local.refresh={...updated};await persist(config);
              }
            }catch(error){if(error.code!=='ENOENT')output.appendLine(error.message);}
          }
          if (!local.refresh && (!mapping || !mapping.bound)) continue;
          try {
            if (local.refresh) mapping = await refreshProject(config, current, session, local);
            let result = await bridge.sync(mailbox(mapping.session_id), {...config.pairing, ...mapping}, local.repository, config.ca);
            for (const rejected of result.rejected_messages || [])
              output.appendLine(`${rejected.task_id} / ${rejected.message_id}: ${rejected.reason}; zpráva zachována v rejections/.`);
            const project = current.projects.find(item => item.project_id === mapping.project_id);
            if (!local.refresh && !result.has_queue && result.stale && project && project.expected_head !== mapping.expected_head
                && !await hasPendingMessages(mapping.session_id)) {
              // Persist intent before map can revoke the previous session.
              local.refresh = {...mapping, expected_head: project.expected_head};
              await persist(config);
              mapping = await refreshProject(config, current, mapping.session_id, local);
              result = await bridge.sync(mailbox(mapping.session_id), {...config.pairing, ...mapping}, local.repository, config.ca);
            }
            if (mapping.session_id !== session || local.previous_session) {
              for (const editor of vscode.window.visibleTextEditors || []) {
                if ([session, local.previous_session].filter(id => id && id !== mapping.session_id)
                    .some(id => editor.document.uri.fsPath === path.join(mailbox(id), 'TODO.md')))
                  await vscode.window.showTextDocument(vscode.Uri.file(path.join(mailbox(mapping.session_id), 'TODO.md')),
                    {viewColumn: editor.viewColumn, preserveFocus: true, preview: false});
              }
            }
            // Typed state first (K6); the text prefix covers backends older than the state.
            if (result.queue_refresh_state === 'waiting_review' || (result.queue_refresh_state === undefined
                && result.queue_refresh_error?.startsWith('Queue refresh waits for human review'))) {
              // An intentional review boundary is not a broken connection.
              await bridge.atomic(path.join(mailbox(mapping.session_id), 'STATUS.json'), JSON.stringify({
                stale: true, waiting_review: true, queue_refresh_error: result.queue_refresh_error,
                synchronized_at: new Date().toISOString()}));
              count++; stale++; waitingReview++;
              output.appendLine((mapping.title || session) + ': ' + result.queue_refresh_error);
              continue;
            }
            if (result.queue_refresh_error) throw Error(result.queue_refresh_error);
            // No packet: clear the last pointer here instead of a second request.
            if (result.has_queue === false)
              await bridge.atomic(path.join(mailbox(mapping.session_id), 'queue.json'), 'null');
            // Export queue/context even when the sidebar views are closed.
            if (result.has_queue) {
              const project = {root: mailbox(mapping.session_id), session: mapping.session_id,
                snapshot: result.snapshot, repository: local.repository, identity: mapping.repository};
              const queue = await queueBridge.synchronize(project, (p, action, data) =>
                bridge.connectionRequest(config.pairing, {action, request: {session_id: p.session, ...data}}, config.ca));
              if (queue?.blockers.length) throw Error(queue.blockers.join('; '));
            }
            count++; if (result.stale) stale++;
          } catch (error) {
            if (error.busy) busyProjects++; else failed++;
            await unavailable(mapping?.session_id || session,error); output.appendLine((mapping?.title || local.refresh?.title || session) + ': ' + error.message);
          }
        }
        if (Object.keys(config.mappings || {}).length) await refreshOwnerQueue(config);
        contention = busyProjects > 0;
        status.text = `${current.name}: ${count} projektů` + (stale ? ` · ${stale} zastaralých` : '') + (waitingReview ? ` · ${waitingReview} čeká na posouzení` : '') + (busyProjects ? ` · ${busyProjects} zaneprázdněných` : '') + (failed ? ` · ${failed} chyb` : '');
        warning = Boolean(stale || failed || busyProjects || !count);
        summary = `Synchronizace Workspace: ${count} projektů, ${stale} zastaralých, ${failed} chyb.`;
        if (busyProjects) summary += ` ${busyProjects} projektů je ve Workspace právě zaneprázdněných; zobrazuje se poslední známý stav a pokus se zopakuje automaticky.`;
        if (waitingReview) summary += ` ${waitingReview} projektů čeká na posouzení výsledků ve Workspace.`;
        if (stale) summary += ' Obnova zadání se zopakuje automaticky; nevyřízené zprávy zůstávají zachované.';
        if (!count && !failed) summary += ' Použijte Workspace: Nastavení projektů.';
        if (failed) summary += ' Podrobnosti najdete ve výstupu Workspace bridge.';
      }
      if (!quiet) {
        if (warning) vscode.window.showWarningMessage(summary);
        else vscode.window.showInformationMessage(summary);
      }
    } catch (error) {
      contention = Boolean(error.busy);
      try {const config=await configuration();for(const session of config.legacy?[config.pairing.session_id]:Object.keys(config.mappings||{}))await unavailable(session,error);}catch(reportError){output.appendLine(`Hlášení nedostupnosti do Workspace selhalo: ${reportError.message}`);}
      status.text = error.code === 'ECONNREFUSED' ? 'Workspace: čeká na spuštění' : error.busy ? 'Workspace: zaneprázdněný · poslední známý stav' : 'Workspace: chyba spojení';
      output.appendLine(error.message);
      if (!quiet) vscode.window.showErrorMessage(error.message);
    } finally {
      if (contention) backoff.failure(); else backoff.success();
      status.text = status.text.replace(/^\$\(sync~spin\) /, '');
      // The queue was exported above; the panel only adds its own reads.
      try { await sidebar.refresh(true, {queue: false, throttle: quiet}); }
      catch (error) { output.appendLine('Panel: ' + error.message); }
      try { await lease.publish({status: status.text}); }
      catch (error) { reportOnce('lease:' + error.message, 'Koordinace oken: ' + error.message); }
    }
  }
  // Background tick: the lease holder polls Workspace; other windows only
  // re-render when the holder has published a new local generation.
  async function tick() {
    if (!vscode.workspace.isTrusted || !(context.globalState.get('connection') || context.globalState.get('session'))) return;
    let leader;
    try { leader = await lease.acquire(); }
    catch (error) { reportOnce('lease:' + error.message, 'Koordinace oken: ' + error.message); leader = true; }
    if (leader) { if (backoff.due()) await synchronize(true); return; }
    const marker = await lease.changed().catch(() => null);
    if (!marker) return;
    if (typeof marker.status === 'string') status.text = marker.status;
    await sidebar.refresh(true, {queue: false, throttle: true});
  }
  async function hasPendingMessages(session) {
    const root = mailbox(session);
    let names;
    try { names = await fs.readdir(path.join(root, 'inbox')); }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
    for (const name of names) {
      if (!/^[0-9a-f-]{36}\.json$/.test(name)) continue;
      try {
        const receipt = JSON.parse(await bridge.read(path.join(root, 'receipts', name)));
        if (receipt.message_id + '.json' !== name || !['received', 'stale'].includes(receipt.status)) return true;
      }
      catch (error) { if (error.code === 'ENOENT') return true; throw error; }
    }
    return false;
  }
  async function refreshProject(config, current, session, local) {
    const intent = local.refresh;
    await bridge.repository(local.repository, intent.repository);
    const active = current.mappings.find(item => item.project_id === intent.project_id);
    let next;
    if (active?.session_id === session) {
      const project = current.projects.find(item => item.project_id === intent.project_id);
      if (!project) throw new Error('Projekt již není dostupný.');
      // No server write has happened yet; follow a newer HEAD after a restart.
      intent.expected_head = project.expected_head;
      await persist(config);
      next = await bridge.connectionRequest(config.pairing, {action: 'map', mapping: {
        connection_id: config.pairing.connection_id, project_id: intent.project_id, enabled: true,
        expected_head: intent.expected_head, expected_mapping: session, repository: intent.repository,
        editor_workspace: intent.editor_workspace, instructions: intent.instructions,
        export_documents: Boolean(intent.export_documents)}}, config.ca);
    } else {
      // Recover only the exact result of our persisted intent, never a changed target.
      if (!active || !['project_id', 'expected_head', 'repository', 'editor_workspace', 'instructions']
          .every(key => active[key] === intent[key]) || Boolean(active.export_documents)!==Boolean(intent.export_documents)) throw new Error('Přiřazení se změnilo během obnovy zadání.');
      next = active;
    }
    const bound = await bridge.connectionRequest(config.pairing, {action: 'bind', session_id: next.session_id,
      repository: intent.repository, editor_workspace: intent.editor_workspace}, config.ca);
    const mapping = {...intent, ...bound, bound: true};
    const restored = {repository: local.repository, editor_workspace: local.editor_workspace, previous_session: session};
    // Publish the new local mapping only after bind; a failed store retains intent.
    const updated = {...config, mappings: {...config.mappings, [bound.session_id]: restored}};
    delete updated.mappings[session];
    await persist(updated);
    config.mappings = updated.mappings;
    sidebar.clear?.(true);
    return mapping;
  }
  function command(name, action) {
    context.subscriptions.push(vscode.commands.registerCommand('workspaceBridge.' + name,
      async () => {try { if (!vscode.workspace.isTrusted) throw new Error('Vyžadován důvěryhodný workspace.'); await action(); }
      catch (error) { vscode.window.showErrorMessage(error.message); }}));
  }
  async function chooseLocalProject() {
    const items = (vscode.workspace.workspaceFolders || []).map(folder => ({label: folder.name,
      description: folder.uri.fsPath, folder: folder.uri.fsPath,
      workspace: vscode.workspace.workspaceFile?.scheme === 'file' ? vscode.workspace.workspaceFile.fsPath : folder.uri.fsPath}));
    items.push({label: 'Vybrat složku…', browse: 'folder'}, {label: 'Vybrat soubor .code-workspace…', browse: 'workspace'});
    const selected = await vscode.window.showQuickPick(items, {placeHolder: 'Přiřadit konkrétní projekt v IDE'});
    if (!selected) return null;
    if (selected.folder) return {repository: await fs.realpath(selected.folder), editor_workspace: await fs.realpath(selected.workspace)};
    const chosen = await vscode.window.showOpenDialog({canSelectMany: false,
      canSelectFiles: selected.browse === 'workspace', canSelectFolders: selected.browse === 'folder',
      ...(selected.browse === 'workspace' ? {filters: {'Code workspace': ['code-workspace']}} : {})});
    if (!chosen?.length) return null;
    const editor_workspace = await fs.realpath(chosen[0].fsPath);
    if (selected.browse === 'folder') return {repository: editor_workspace, editor_workspace};
    const folders = await vscode.window.showOpenDialog({canSelectMany: false, canSelectFiles: false, canSelectFolders: true, openLabel: 'Git repozitář tohoto workspace'});
    if (!folders?.length) return null;
    return {repository: await fs.realpath(folders[0].fsPath), editor_workspace};
  }
  async function mapProject(config, current, project, enabled, target = null) {
    const existing = current.mappings.find(item => item.project_id === project.project_id);
    const mapping = {connection_id: config.pairing.connection_id, project_id: project.project_id, enabled,
      expected_head: project.expected_head, expected_mapping: existing?.session_id || null,
      repository: target?.identity || existing?.repository || '',
      editor_workspace: target?.editor_workspace || existing?.editor_workspace || '', instructions: existing?.instructions || ''};
    const result = await bridge.connectionRequest(config.pairing, {action: 'map', mapping}, config.ca);
    if (!enabled) {
      if (existing) delete config.mappings[existing.session_id];
      await persist(config); return;
    }
    if (target) {
      const bound = await bridge.connectionRequest(config.pairing, {action: 'bind', session_id: result.session_id,
        repository: target.identity, editor_workspace: target.editor_workspace}, config.ca);
      if (existing && existing.session_id !== bound.session_id) delete config.mappings[existing.session_id];
      config.mappings[bound.session_id] = {repository: target.repository, editor_workspace: target.editor_workspace};
      await persist(config);
    }
  }
  async function assignProject(config, current, project) {
    const target = await chooseLocalProject(); if (!target) return false;
    return assignTarget(config, current, project, target);
  }
  async function assignTarget(config, current, project, target) {
    let identity = target.repository;
    try { identity = await bridge.git(target.repository, 'remote', 'get-url', 'origin'); } catch (_) { /* local repository */ }
    const existing = current.mappings.find(item => item.project_id === project.project_id);
    if (existing?.repository) {
      try { await bridge.repository(target.repository, existing.repository); identity = existing.repository; } catch (_) { /* explicit reassignment below */ }
    }
    await bridge.repository(target.repository, identity);
    const previous = existing?.editor_workspace && existing.editor_workspace !== target.editor_workspace ? `\nDosavadní projekt v IDE: ${existing.editor_workspace}` : '';
    if (await vscode.window.showWarningMessage(`Přiřadit ${project.title} k ${target.editor_workspace}?\nRepozitář: ${identity}${previous}`, {modal: true}, 'Přiřadit') !== 'Přiřadit') return false;
    await mapProject(config, current, project, true, {...target, identity});
    return true;
  }
  // Long Git operations never wait for an interactive credential prompt.
  function gitLong(args, cwd) {
    const env = {...process.env, GIT_TERMINAL_PROMPT: '0'};
    env.GIT_SSH_COMMAND ||= 'ssh -o BatchMode=yes';
    return new Promise((resolve, reject) => execFile('git', args, {cwd, env, timeout: 600000, maxBuffer: 1 << 20},
      (error, stdout, stderr) => error ? reject(new Error('Git: ' + (String(stderr || '').trim().split('\n').slice(-3).join(' ') || error.message))) : resolve(stdout)));
  }
  function folderName(text) {
    return String(text || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^A-Za-z0-9._-]+/g, '-')
      .replace(/^[-._]+|[-._]+$/g, '').slice(0, 80) || 'workspace-project';
  }
  async function newFolder(suggestion) {
    const parent = await vscode.window.showOpenDialog({canSelectMany: false, canSelectFiles: false, canSelectFolders: true, openLabel: 'Nadřazená složka projektu'});
    if (!parent?.length) return null;
    const name = await vscode.window.showInputBox({prompt: 'Název nové složky projektu v IDE', value: folderName(suggestion), ignoreFocusOut: true,
      validateInput: value => /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value) ? null : 'Použijte písmena bez diakritiky, číslice, tečku, pomlčku nebo podtržítko.'});
    if (!name) return null;
    const root = path.join(await fs.realpath(parent[0].fsPath), name);
    try { await fs.lstat(root); } catch (error) { if (error.code === 'ENOENT') return root; throw error; }
    throw new Error('Složka již existuje: ' + root + '. Pro existující repozitář zvolte Použít existující složku.');
  }
  // Creates (or reuses) the local folder of an existing Workspace project and
  // binds it through the ordinary map/bind lifecycle (ADR 0090).
  async function createProject() {
    const config = await configuration();
    if (config.legacy) throw new Error('Nejprve připojte Workspace z nové stránky nastavení.');
    config.mappings ||= {};
    const current = await catalog(config);
    if (!current.projects.length) throw new Error('Workspace nenabízí žádný projekt, který můžete upravovat.');
    const picked = await vscode.window.showQuickPick(current.projects.map(project => {
      const existing = current.mappings.find(item => item.project_id === project.project_id);
      return {label: project.title, description: existing?.editor_workspace ? 'v IDE: ' + existing.editor_workspace : 'bez projektu v IDE', project, existing};
    }), {placeHolder: 'Projekt Workspace, ke kterému vytvořit projekt v IDE'});
    if (!picked) return;
    const method = await vscode.window.showQuickPick([
      {label: '$(repo-clone) Naklonovat Git repozitář do nové složky', method: 'clone'},
      {label: '$(folder-opened) Použít existující složku nebo .code-workspace', method: 'existing'},
      {label: '$(new-folder) Vytvořit nový prázdný Git repozitář', method: 'init'}], {placeHolder: 'Projekt v IDE pro ' + picked.project.title});
    if (!method) return;
    let target;
    if (method.method === 'existing') {
      target = await chooseLocalProject(); if (!target) return;
    } else {
      let url = null;
      if (method.method === 'clone') {
        url = await vscode.window.showInputBox({prompt: 'Adresa Git repozitáře (HTTPS, SSH nebo lokální cesta)',
          value: picked.existing?.repository || '', ignoreFocusOut: true,
          validateInput: value => !value || value.startsWith('-') || /[\u0000-\u001f\u007f]/.test(value) ? 'Zadejte platnou adresu repozitáře.' : null});
        if (!url) return;
      }
      const root = await newFolder(url ? path.basename(url.replace(/[\\/]+$/, '')).replace(/\.git$/, '') : picked.project.title);
      if (!root) return;
      const work = async () => {
        // git clone removes its own incomplete target; init leaves an empty repository.
        if (url) await gitLong(['clone', '--', url, root], path.dirname(root));
        else { await fs.mkdir(root); await gitLong(['init', '--quiet', '--', root], path.dirname(root)); }
      };
      if (vscode.window.withProgress) await vscode.window.withProgress({location: vscode.ProgressLocation?.Notification ?? 15,
        title: url ? 'Workspace: klonuji ' + url : 'Workspace: vytvářím repozitář'}, work);
      else await work();
      const real = await fs.realpath(root);
      target = {repository: real, editor_workspace: real};
    }
    if (!await assignTarget(config, current, picked.project, target)) return;
    await synchronize();
    await offerOpen(target.editor_workspace, picked.project.title);
  }
  command('configure', async () => {
    const config = await configuration();
    if (config.legacy) { vscode.window.showInformationMessage('Toto je původní projektové propojení. Nové připojení Workspace připravte v Nastavení → IDE a editory.'); return; }
    config.mappings ||= {};
    const current = await catalog(config);
    const selected = await vscode.window.showQuickPick(current.projects.map(project => ({label: project.title,
      description: current.mappings.find(item => item.project_id === project.project_id)?.editor_workspace || 'Bez přiřazení',
      picked: current.mappings.some(item => item.project_id === project.project_id), project})),
      {canPickMany: true, placeHolder: 'Projekty, které chcete propagovat z Workspace do IDE'});
    if (!selected) return;
    const selectedIds = new Set(selected.map(item => item.project.project_id));
    for (const project of current.projects) {
      const existing = current.mappings.find(item => item.project_id === project.project_id);
      if (existing && !selectedIds.has(project.project_id)) await mapProject(config, current, project, false);
    }
    for (const item of selected) {
      const existing = current.mappings.find(mapping => mapping.project_id === item.project.project_id);
      if (!existing || !config.mappings[existing.session_id] || existing.expected_head !== item.project.expected_head)
        await assignProject(config, current, item.project);
    }
    await synchronize();
  });
  command('assign', async () => {
    const config = await configuration();
    if (config.legacy) throw new Error('Nejprve připojte Workspace z nové stránky nastavení.');
    config.mappings ||= {};
    const current = await catalog(config);
    const selected = await vscode.window.showQuickPick(current.projects.map(project => ({label: project.title, project})), {placeHolder: 'Projekt pro přiřazení nebo změnu cíle'});
    if (selected) { await assignProject(config, current, selected.project); await synchronize(); }
  });
  command('createProject', createProject);
  command('connect', async () => {
    let pairing;
    try { pairing = JSON.parse(await fs.readFile(path.join(context.extensionPath, 'pairing.json'), 'utf8')); }
    catch (_) {
      const selected = await vscode.window.showOpenDialog({canSelectMany: false, filters: {'Workspace pairing': ['json']}});
      if (!selected?.length) return;
      pairing = JSON.parse(await bridge.read(selected[0].fsPath));
    }
    bridge.validatePairing(pairing);
    if (await vscode.window.showWarningMessage(`Připojit ${pairing.name || pairing.project_id} na ${pairing.endpoint}?\nPřipojení umožní výběr a přiřazení vašich oprávněných projektů. Soubory zůstanou mimo Git.`, {modal: true}, 'Připojit') !== 'Připojit') return;
    let ca;
    if (pairing.endpoint.startsWith('https:') && await vscode.window.showQuickPick(['Systémová důvěra TLS', 'Vybrat vlastní CA certifikát'], {placeHolder: 'Ověření serveru'}) === 'Vybrat vlastní CA certifikát') {
      const certificates = await vscode.window.showOpenDialog({canSelectMany: false, filters: {'CA certificate': ['pem', 'crt']}});
      if (!certificates?.length) return;
      ca = await bridge.read(certificates[0].fsPath);
    }
    await bridge.safeDirectory(privateRoot);
    if (pairing.schema_version === 2) {
      // Validate the server before replacing a working local connection.
      await bridge.connectionRequest(pairing, {action: 'status'}, ca);
      await persist({pairing, ca, mappings: {}});
      await synchronize();
      if (await vscode.window.showInformationMessage('Workspace připojen. Projekty můžete nastavit nyní nebo později.', 'Nastavit projekty') === 'Nastavit projekty')
        await vscode.commands.executeCommand('workspaceBridge.configure');
    } else {
      const selected = await vscode.window.showOpenDialog({canSelectFiles: false, canSelectFolders: true, canSelectMany: false});
      if (!selected?.length) return;
      const repo = await bridge.repository(selected[0].fsPath, pairing.repository);
      await context.secrets.store('session:' + pairing.session_id, JSON.stringify({pairing, repository: repo.root, ca}));
      await context.globalState.update('connection', undefined);
      await context.globalState.update('session', pairing.session_id);
      await synchronize();
    }
  });
  command('sync', () => synchronize());
  command('open', async () => {
    const config = await projectConnection(); if (!config) return;
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(config.root, 'TODO.md'))));
    await vscode.env.clipboard.writeText(config.root);
    vscode.window.showInformationMessage('Cesta ke komunikační složce zkopírována: ' + config.root);
  });
  command('message', async () => {
    const config = await projectConnection(); if (!config) return;
    const snapshot = JSON.parse(await bridge.read(path.join(config.root, 'snapshot.json')));
    const selected = await vscode.window.showQuickPick(snapshot.tasks.map(task => ({label: task.id, description: task.title})), {placeHolder: 'Úkol'});
    if (!selected) return;
    const kind = await vscode.window.showQuickPick(['progress', 'completed', 'clarification', 'message'], {placeHolder: 'Typ zprávy'}); if (!kind) return;
    let queue;try{queue=JSON.parse(await bridge.read(path.join(config.root,'queue.json')));}catch(error){if(error.code!=='ENOENT')throw error;}
    if(kind==='completed'&&queue?.items.some(i=>i.id===selected.label))throw Error('Položka fronty vyžaduje hlášení agenta podle packets/<id>/AGENT.md, nebo ruční žádost z pohledu Fronta úkolů; přijímá ji člověk ve Workspace.');
    if(kind==='progress'&&queue&&[...queue.items,...(queue.linked_items||[])].some(i=>i.id===selected.label))return vscode.commands.executeCommand('workspaceBridge.compose',{projectId:snapshot.project_id,taskId:selected.label});
    const body = await vscode.window.showInputBox({prompt: 'Výsledek a důkazy, dotaz nebo zpráva', ignoreFocusOut: true}); if (!body) return;
    if (await vscode.window.showWarningMessage(`${kind} · ${selected.label}\n${body}`, {modal: true}, 'Odeslat') !== 'Odeslat') return;
    const message = {message_id: crypto.randomUUID(), task_id: selected.label, kind, body,
      revision: snapshot.revision, repository_commit: await bridge.git(config.repository, 'rev-parse', 'HEAD')};
    await bridge.atomic(path.join(config.root, 'inbox', message.message_id + '.json'), JSON.stringify(message, null, 2));
    await synchronize();
  });
  command('disconnect', async () => {
    for (const type of ['connection', 'session']) {
      const key = context.globalState.get(type);
      if (key) await context.secrets.delete(type + ':' + key);
      await context.globalState.update(type, undefined);
    }
    status.text = 'Workspace: odpojeno';
    status.command = 'workspaceBridge.connect';
    sidebar.clear?.();
    vscode.window.showInformationMessage('Lokální synchronizace zastavena. Přístup odvolejte také ve Workspace. Soubory zůstaly zachovány.');
  });
  command('checkUpdates', () => checkUpdates(true));
  const updateTimer = setInterval(() => { void checkUpdates(); }, 60000);
  context.subscriptions.push({dispose: () => clearInterval(updateTimer)});
  void checkUpdates();
  const timer = setInterval(() => {
    if (vscode.workspace.getConfiguration('workspaceBridge').get('autoSync', true))
      tick().catch(error => output.appendLine(error.message));
  }, 10000);
  context.subscriptions.push({dispose: () => clearInterval(timer)});
  if (context.globalState.get('connection') || context.globalState.get('session')) {
    // A newly opened window does not start a second poll of the same profile.
    let leader = true;
    try { leader = await lease.acquire(); } catch (error) { reportOnce('lease:' + error.message, 'Koordinace oken: ' + error.message); }
    if (leader) await synchronize(true);
    else { const marker = await lease.changed().catch(() => null); if (typeof marker?.status === 'string') status.text = marker.status; }
  } else {
    try {
      await fs.access(path.join(context.extensionPath, 'pairing.json'));
      // Startup activation must finish even while the invitation remains open.
      vscode.window.showInformationMessage('Workspace bridge je připraven k připojení.', 'Připojit')
        .then(choice => choice === 'Připojit' ? vscode.commands.executeCommand('workspaceBridge.connect') : undefined)
        .catch(error => output.appendLine(error.message));
    } catch (_) { /* generic package without pairing */ }
  }
  // The startup run (or the lease holder) already exported the queue.
  await sidebar.refresh(true, {queue: false, throttle: true});
  return {sidebar};
}
module.exports = {activate};
