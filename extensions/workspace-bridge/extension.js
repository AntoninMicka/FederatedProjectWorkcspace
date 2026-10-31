// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const bridge = require('./bridge');
const {createSidebar} = require('./sidebar');
const {createUpdater} = require('./updater');

async function activate(context) {
  if (vscode.env.remoteName) { vscode.window.showWarningMessage('Workspace bridge zatím vyžaduje lokální IDE bez Remote SSH/WSL.'); return; }
  let busy = false;
  const output = vscode.window.createOutputChannel('Workspace bridge');
  context.subscriptions.push(output);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
  status.text = 'Workspace: odpojeno'; status.command = 'workspaceBridge.configure'; status.show();
  context.subscriptions.push(status);
  const privateRoot = path.join(context.globalStorageUri.fsPath, 'bridge-private');
  const mailbox = session => path.join(privateRoot, 'sessions', session);
  const sidebar = createSidebar(vscode, context, {projects: panelProjects, request: panelRequest,
    synchronize: () => synchronize(true), error: text => output.appendLine(text)});
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
        result.push({session,root,repository:local.repository,identity:identity.repository,snapshot,state,pending,
          legacy:config.legacy,error:state.error || (config.legacy?'Původní spojení: pro plný panel připojte Workspace schema-v2.':null)});
      } catch (error) {output.appendLine('Panel '+session+': '+error.message);}
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
      failed_at:new Date().toISOString()}));} catch (_) { /* original error is reported */ }
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
  async function synchronize(quiet = false) {
    if (busy || !vscode.workspace.isTrusted || !(context.globalState.get('connection') || context.globalState.get('session'))) return;
    busy = true;
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
        let count = 0, stale = 0, failed = 0;
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
            count++; if (result.stale) stale++;
          } catch (error) { failed++; await unavailable(mapping?.session_id || session,error); output.appendLine((mapping?.title || local.refresh?.title || session) + ': ' + error.message); }
        }
        status.text = `${current.name}: ${count} projektů` + (stale ? ` · ${stale} zastaralých` : '') + (failed ? ` · ${failed} chyb` : '');
        warning = Boolean(stale || failed || !count);
        summary = `Synchronizace Workspace: ${count} projektů, ${stale} zastaralých, ${failed} chyb.`;
        if (stale || !count) summary += ' Použijte Workspace: Nastavení projektů.';
        if (failed) summary += ' Podrobnosti najdete ve výstupu Workspace bridge.';
      }
      if (!quiet) {
        if (warning) vscode.window.showWarningMessage(summary);
        else vscode.window.showInformationMessage(summary);
      }
    } catch (error) {
      try {const config=await configuration();for(const session of config.legacy?[config.pairing.session_id]:Object.keys(config.mappings||{}))await unavailable(session,error);}catch(_){}
      status.text = error.code === 'ECONNREFUSED' ? 'Workspace: čeká na spuštění' : 'Workspace: chyba spojení';
      output.appendLine(error.message);
      if (!quiet) vscode.window.showErrorMessage(error.message);
    } finally { await sidebar.refresh(); busy = false; }
  }
  async function hasPendingMessages(session) {
    const root = mailbox(session);
    for (const name of await fs.readdir(path.join(root, 'inbox'))) {
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
    const target = await chooseLocalProject(); if (!target) return;
    let identity = target.repository;
    try { identity = await bridge.git(target.repository, 'remote', 'get-url', 'origin'); } catch (_) { /* local repository */ }
    const existing = current.mappings.find(item => item.project_id === project.project_id);
    if (existing?.repository) {
      try { await bridge.repository(target.repository, existing.repository); identity = existing.repository; } catch (_) { /* explicit reassignment below */ }
    }
    await bridge.repository(target.repository, identity);
    if (await vscode.window.showWarningMessage(`Přiřadit ${project.title} k ${target.editor_workspace}?\nRepozitář: ${identity}`, {modal: true}, 'Přiřadit') !== 'Přiřadit') return;
    await mapProject(config, current, project, true, {...target, identity});
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
    const kind = await vscode.window.showQuickPick(['completed', 'clarification', 'message'], {placeHolder: 'Typ zprávy'}); if (!kind) return;
    let queue;try{queue=JSON.parse(await bridge.read(path.join(config.root,'queue.json')));}catch(error){if(error.code!=='ENOENT')throw error;}
    if(kind==='completed'&&queue?.items.some(i=>i.id===selected.label))throw Error('Položka fronty vyžaduje hlášení agenta podle packets/<id>/AGENT.md a lidské přijetí ve Workspace.');
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
    sidebar.clear?.();
    vscode.window.showInformationMessage('Lokální synchronizace zastavena. Přístup odvolejte také ve Workspace. Soubory zůstaly zachovány.');
  });
  command('checkUpdates', () => checkUpdates(true));
  const updateTimer = setInterval(() => { void checkUpdates(); }, 60000);
  context.subscriptions.push({dispose: () => clearInterval(updateTimer)});
  void checkUpdates();
  const timer = setInterval(() => {
    if (vscode.workspace.getConfiguration('workspaceBridge').get('autoSync', true)) synchronize(true);
  }, 10000);
  context.subscriptions.push({dispose: () => clearInterval(timer)});
  if (context.globalState.get('connection') || context.globalState.get('session')) await synchronize(true);
  else {
    try {
      await fs.access(path.join(context.extensionPath, 'pairing.json'));
      // Startup activation must finish even while the invitation remains open.
      vscode.window.showInformationMessage('Workspace bridge je připraven k připojení.', 'Připojit')
        .then(choice => choice === 'Připojit' ? vscode.commands.executeCommand('workspaceBridge.connect') : undefined)
        .catch(error => output.appendLine(error.message));
    } catch (_) { /* generic package without pairing */ }
  }
  await sidebar.refresh();
  return {sidebar};
}
module.exports = {activate};
