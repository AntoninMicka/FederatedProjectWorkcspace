// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const {createUpdater, newer} = require('../extensions/workspace-bridge/updater');

function fixture({auto = true, version = '0.4.2', fail = false, confirm = false, reload = false} = {}) {
  const bytes = Buffer.from('test VSIX bytes consumed by the mock installer');
  const metadata = {extension_id: 'federated-workspace.workspace-file-bridge', version};
  const download = {...metadata, package_base64: bytes.toString('base64'),
    sha256: crypto.createHash('sha256').update(bytes).digest('hex')};
  const installs = [], prompts = [], errors = [], requests = [], commands = [];
  const vscode = {workspace: {isTrusted: true, getConfiguration: () => ({get: () => auto})},
    Uri: {file: fsPath => ({fsPath})},
    window: {showInformationMessage: async (message, choice) => {
      prompts.push(message);return choice === 'Aktualizovat' ? (confirm ? choice : undefined) : (reload ? choice : undefined);
    }, showErrorMessage: async text => errors.push(text)},
    commands: {executeCommand: async (name, uri) => {
      commands.push(name);
      if (name === 'workbench.extensions.installExtension') {
        installs.push(uri.fsPath);assert.deepEqual(await fs.readFile(uri.fsPath), bytes);
        assert.equal((await fs.stat(uri.fsPath)).mode & 0o777, 0o600);
        if (fail) throw Error('installer failed');
      }
    }}};
  const request = async full => {requests.push(full); return full ? download : metadata;};
  const check = createUpdater(vscode, {extension: {packageJSON: {version: '0.4.1'}}}, request, text => errors.push(text));
  return {check, vscode, installs, prompts, errors, requests, commands, download, metadata};
}

test('numeric version comparison refuses downgrade, equality and malformed versions', () => {
  assert.equal(newer('0.10.0', '0.4.1'), true);
  assert.equal(newer('0.4.1', '0.4.1'), false);
  assert.equal(newer('0.4.0', '0.4.1'), false);
  for (const value of ['x', '01.4.2', '1.2.3-beta', '99999999999999999999.0.0'])
    assert.throws(() => newer(value, '0.4.1'));
});
test('automatic install is single flight, throttled, cleans package and never reloads without confirmation', async () => {
  const f = fixture();await Promise.all([f.check(), f.check()]);await f.check();
  assert.equal(f.installs.length, 1);assert.deepEqual(f.requests, [false, true]);
  await assert.rejects(fs.access(f.installs[0]));
  assert.deepEqual(f.commands, ['workbench.extensions.installExtension']);
  await f.check(true);assert.equal(f.installs.length, 1);
});
test('notification requires install approval; reload has independent confirmation', async () => {
  const dismissed = fixture({auto: false});await dismissed.check();
  assert.equal(dismissed.installs.length, 0);assert.deepEqual(dismissed.requests, [false]);
  const accepted = fixture({auto: false, confirm: true, reload: true});await accepted.check(true);
  assert.deepEqual(accepted.commands, ['workbench.extensions.installExtension', 'workbench.action.reloadWindow']);
});
test('installer failure cleans temporary package and manual check permits retry', async () => {
  const f = fixture({fail: true});await f.check(true);await f.check(true);
  assert.equal(f.installs.length, 2);assert.ok(f.errors.some(e => e.includes('installer failed')));
  for (const name of f.installs) await assert.rejects(fs.access(name));
});
test('invalid hash, changed version and wrong identity cannot reach installer', async () => {
  for (const mutate of [f => f.download.sha256 = '0'.repeat(64),
    f => f.download.version = '0.4.3', f => f.metadata.extension_id = 'other.extension',
    f => f.download.package_base64 = 'A'.repeat(3 * 1024 * 1024),
    f => f.download.package_base64 = 'invalid!']) {
    const f = fixture();mutate(f);await f.check(true);
    assert.equal(f.installs.length, 0);assert.ok(f.errors.length);
  }
});
test('untrusted workspace does not contact backend; current or older versions never install', async () => {
  const f = fixture();f.vscode.workspace.isTrusted = false;await f.check(true);
  assert.deepEqual(f.requests, []);
  for (const version of ['0.4.1', '0.3.9']) {
    const g = fixture({version});await g.check(true);assert.equal(g.installs.length, 0);
  }
});
test('unavailable connection is checked again without waiting for an hour; transport errors remain isolated', async () => {
  const f = fixture();let calls = 0;
  const check = createUpdater(f.vscode, {extension: {packageJSON: {version: '0.4.1'}}},
    async () => {calls++;return null;}, text => f.errors.push(text));
  await check();await check();assert.equal(calls, 2);
  const failed = createUpdater(f.vscode, {}, async () => {throw Error('backend unavailable');}, text => f.errors.push(text));
  await failed();assert.ok(f.errors.some(e => e.includes('backend unavailable')));
  assert.equal(f.installs.length, 0);
});
