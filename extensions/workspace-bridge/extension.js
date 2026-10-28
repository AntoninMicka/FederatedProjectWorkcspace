// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const bridge = require('./bridge');

async function activate(context) {
  if (vscode.env.remoteName) { vscode.window.showWarningMessage('Workspace bridge zatím vyžaduje lokální IDE bez Remote SSH/WSL.'); return; }
  let busy = false;
  const output = vscode.window.createOutputChannel('Workspace bridge');
  context.subscriptions.push(output);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
  status.text = 'Workspace: odpojeno'; status.command = 'workspaceBridge.open'; status.show();
  context.subscriptions.push(status);
  async function connection() {
    const key = context.globalState.get('session');
    if (!key) throw new Error('Nejprve propojte projekt.');
    const value = await context.secrets.get('session:' + key);
    if (!value) throw new Error('Chybí přihlašovací údaje. Propojte projekt znovu.');
    const config = JSON.parse(value);
    return {...config, root: path.join(context.globalStorageUri.fsPath, 'bridge-private', 'sessions', key)};
  }
  async function synchronize(quiet = false) {
    if (busy || !vscode.workspace.isTrusted || !context.globalState.get('session')) return;
    busy = true;
    try {
      const config = await connection();
      const result = await bridge.sync(config.root, config.pairing, config.repository, config.ca);
      status.text = result.stale ? 'Workspace: zastaralé zadání' : 'Workspace: propojeno';
      if (!quiet) vscode.window.showInformationMessage(result.stale ? 'Zadání se změnilo. V aplikaci vytvořte nové propojení.' : 'Workspace synchronizován.');
    } catch (error) {
      status.text = 'Workspace: chyba spojení';
      output.appendLine(error.message);
      if (!quiet) vscode.window.showErrorMessage(error.message);
    } finally { busy = false; }
  }
  function command(name, action) {
    context.subscriptions.push(vscode.commands.registerCommand('workspaceBridge.' + name,
      async () => {try { if (!vscode.workspace.isTrusted) throw new Error('Vyžadován důvěryhodný workspace.'); await action(); }
      catch (error) { vscode.window.showErrorMessage(error.message); }}));
  }
  command('connect', async () => {
    let pairing;
    try { pairing = JSON.parse(await fs.readFile(path.join(context.extensionPath, 'pairing.json'), 'utf8')); }
    catch (_) {
      const selected = await vscode.window.showOpenDialog({canSelectMany: false, filters: {'Workspace pairing': ['json']}});
      if (!selected?.length) return;
      pairing = JSON.parse(await bridge.read(selected[0].fsPath));
    }
    bridge.validatePairing(pairing);
    if (await vscode.window.showWarningMessage(`Propojit ${pairing.endpoint} s projektem ${pairing.project_id} a repozitářem ${pairing.repository}? TODO a instrukce se uloží lokálně mimo Git.`, {modal: true}, 'Propojit') !== 'Propojit') return;
    const selected = await vscode.window.showOpenDialog({canSelectFiles: false, canSelectFolders: true, canSelectMany: false, openLabel: 'Vybrat zdrojový Git repozitář'});
    if (!selected?.length) return;
    const repo = await bridge.repository(selected[0].fsPath, pairing.repository);
    let ca;
    if (pairing.endpoint.startsWith('https:') && await vscode.window.showQuickPick(['Systémová důvěra TLS', 'Vybrat vlastní CA certifikát'], {placeHolder: 'Ověření serveru'}) === 'Vybrat vlastní CA certifikát') {
      const certificates = await vscode.window.showOpenDialog({canSelectMany: false, filters: {'CA certificate': ['pem', 'crt']}});
      if (!certificates?.length) return;
      ca = await bridge.read(certificates[0].fsPath);
    }
    await bridge.safeDirectory(path.join(context.globalStorageUri.fsPath, 'bridge-private'));
    await context.secrets.store('session:' + pairing.session_id, JSON.stringify({pairing, repository: repo.root, ca}));
    await context.globalState.update('session', pairing.session_id);
    await synchronize();
    await vscode.commands.executeCommand('workspaceBridge.open');
  });
  command('sync', () => synchronize());
  command('open', async () => {
    const {root} = await connection();
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(root, 'TODO.md')));
    await vscode.window.showTextDocument(document);
    await vscode.env.clipboard.writeText(root);
    vscode.window.showInformationMessage('Cesta ke komunikační složce zkopírována: ' + root);
  });
  command('message', async () => {
    const config = await connection();
    const snapshot = JSON.parse(await bridge.read(path.join(config.root, 'snapshot.json')));
    const selected = await vscode.window.showQuickPick(snapshot.tasks.map(task => ({label: task.id, description: task.title})), {placeHolder: 'Úkol'});
    if (!selected) return;
    const kind = await vscode.window.showQuickPick(['completed', 'clarification', 'message'], {placeHolder: 'Typ zprávy'});
    if (!kind) return;
    const body = await vscode.window.showInputBox({prompt: 'Výsledek a důkazy, dotaz nebo zpráva', ignoreFocusOut: true});
    if (!body) return;
    if (await vscode.window.showWarningMessage(`${kind} · ${selected.label}\n${body}`, {modal: true}, 'Odeslat') !== 'Odeslat') return;
    const message = {message_id: crypto.randomUUID(), task_id: selected.label, kind, body,
      revision: snapshot.revision, repository_commit: await bridge.git(config.repository, 'rev-parse', 'HEAD')};
    await bridge.atomic(path.join(config.root, 'inbox', message.message_id + '.json'), JSON.stringify(message, null, 2));
    await synchronize();
  });
  command('disconnect', async () => {
    const session = context.globalState.get('session');
    if (session) await context.secrets.delete('session:' + session);
    await context.globalState.update('session', undefined);
    status.text = 'Workspace: odpojeno';
    vscode.window.showInformationMessage('Lokální synchronizace zastavena. Přístup odvolejte také ve Workspace. Soubory zůstaly zachovány.');
  });
  const timer = setInterval(() => synchronize(true), 10000);
  context.subscriptions.push({dispose: () => clearInterval(timer)});
  if (context.globalState.get('session')) await synchronize(true);
  else {
    try {
      await fs.access(path.join(context.extensionPath, 'pairing.json'));
      if (await vscode.window.showInformationMessage('Workspace bridge je připraven k propojení.', 'Propojit') === 'Propojit')
        await vscode.commands.executeCommand('workspaceBridge.connect');
    } catch (_) { /* generic package without pairing */ }
  }
}
module.exports = {activate};
