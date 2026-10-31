// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const ID = 'federated-workspace.workspace-file-bridge';
const MAX_PACKAGE = 2 * 1024 * 1024;

function newer(candidate, installed) {
  const parse = value => {
    if (typeof value !== 'string' || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value))
      throw Error('Neplatná verze rozšíření.');
    const parts = value.split('.').map(Number);
    if (!parts.every(Number.isSafeInteger)) throw Error('Neplatná verze rozšíření.');
    return parts;
  };
  const a = parse(candidate), b = parse(installed);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}

function createUpdater(vscode, context, request, report) {
  let busy = false, lastCheck = 0, installed = null;
  async function reload() {
    const choice = await vscode.window.showInformationMessage(
      'Aktualizace Workspace ' + installed + ' je nainstalována. Pro načtení obnovte okno IDE.', 'Obnovit okno');
    if (choice === 'Obnovit okno') await vscode.commands.executeCommand('workbench.action.reloadWindow');
  }
  return async function check(manual = false) {
    if (busy || !vscode.workspace.isTrusted) return;
    if (!manual && Date.now() - lastCheck < 60 * 60 * 1000) return;
    busy = true;
    lastCheck = Date.now();
    let temporary;
    try {
      if (installed) { if (manual) await reload(); return; }
      const available = await request(false);
      if (!available) {
        lastCheck = 0;
        if (manual) throw Error('Aktualizace vyžaduje připojení Workspace schema-v2.');
        return;
      }
      if (available.extension_id !== ID) throw Error('Neshoda identity aktualizace Workspace.');
      if (!newer(available.version, context.extension?.packageJSON?.version || require('./package.json').version)) {
        if (manual) vscode.window.showInformationMessage('Workspace je aktuální.');
        return;
      }
      if (!vscode.workspace.getConfiguration('workspaceBridge').get('autoUpdate', false)) {
        const choice = await vscode.window.showInformationMessage(
          'Je dostupná aktualizace Workspace ' + available.version + '.', 'Aktualizovat');
        if (choice !== 'Aktualizovat') return;
      }
      const download = await request(true);
      if (!download || download.extension_id !== ID || download.version !== available.version)
        throw Error('Verze aktualizace se během stahování změnila. Zkuste kontrolu znovu.');
      if (typeof download.package_base64 !== 'string' || !download.package_base64.length ||
          download.package_base64.length > Math.ceil(MAX_PACKAGE / 3) * 4 ||
          !/^[A-Za-z0-9+/]*={0,2}$/.test(download.package_base64) ||
          !/^[a-f0-9]{64}$/.test(download.sha256 || '')) throw Error('Neplatný aktualizační balíček.');
      const bytes = Buffer.from(download.package_base64, 'base64');
      if (bytes.length > MAX_PACKAGE || bytes.toString('base64') !== download.package_base64 ||
          crypto.createHash('sha256').update(bytes).digest('hex') !== download.sha256)
        throw Error('Neshoda kontrolního součtu aktualizace.');
      temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'workspace-update-'));
      const file = path.join(temporary, 'workspace.vsix');
      await fs.writeFile(file, bytes, {mode: 0o600, flag: 'wx'});
      await vscode.commands.executeCommand('workbench.extensions.installExtension', vscode.Uri.file(file));
      installed = download.version;
      await fs.rm(temporary, {recursive: true, force: true});
      temporary = undefined;
      await reload();
    } catch (error) {
      report('Aktualizace Workspace: ' + error.message);
      if (manual) await vscode.window.showErrorMessage('Aktualizace Workspace: ' + error.message);
    } finally {
      if (temporary) await fs.rm(temporary, {recursive: true, force: true}).catch(error => report(error.message));
      busy = false;
    }
  };
}
module.exports = {createUpdater, newer};
