// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const crypto = require('node:crypto');
const bridge = require('../extensions/workspace-bridge/bridge');

async function fixture(t) {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'ide-bridge-'));
  t.after(() => fs.rm(base, {recursive: true, force: true}));
  const repo = path.join(base, 'repo'); await fs.mkdir(repo);
  execFileSync('git', ['-C', repo, 'init', '-q']);
  execFileSync('git', ['-C', repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture']);
  const pairing = {schema_version: 1, session_id: crypto.randomUUID(), token: 'a'.repeat(43),
    project_id: crypto.randomUUID(), repository: repo, endpoint: 'http://127.0.0.1:9999', expires_at: Math.floor(Date.now()/1000)+1000};
  const root = path.join(base, 'mailbox');
  const response = {session_id: pairing.session_id, repository: repo, stale: false, instructions: 'Test',
    snapshot: {project_id: pairing.project_id, revision: 'b'.repeat(64), todo: '- [ ] [TASK-01] Test\n', tasks: [{id: 'TASK-01'}]}, receipts: []};
  return {base, root, repo, pairing, response};
}
test('ordinary files, retry after transport failure, receipt recovery and no Git changes', async t => {
  const f = await fixture(t);
  await bridge.sync(f.root, f.pairing, f.repo, null, async () => f.response);
  assert.match(await fs.readFile(path.join(f.root, 'TODO.md'), 'utf8'), /TASK-01/);
  const message = {message_id: crypto.randomUUID(), task_id: 'TASK-01', kind: 'clarification', body: 'Question', revision: f.response.snapshot.revision, repository_commit: await bridge.git(f.repo, 'rev-parse', 'HEAD')};
  await bridge.atomic(path.join(f.root, 'inbox', message.message_id + '.json'), JSON.stringify(message));
  await assert.rejects(bridge.sync(f.root, f.pairing, f.repo, null, async () => {throw new Error('lost response');}), /lost response/);
  let sent;
  const transport = async (_pairing, request) => {sent = request.messages; return {...f.response, receipts: request.messages.map(m => ({message_id: m.message_id, status: 'received'}))};};
  await bridge.sync(f.root, f.pairing, f.repo, null, transport);
  assert.deepEqual(sent, [message]);
  await bridge.sync(f.root, f.pairing, f.repo, null, transport);
  assert.deepEqual(sent, []);
  assert.equal(await bridge.git(f.repo, 'status', '--porcelain'), '');
  assert.equal((await fs.stat(path.join(f.root, 'snapshot.json'))).mode & 0o777, 0o600);
});
test('rejects Git-contained mailbox, symlinks, repository mismatch and wrong server response', async t => {
  const f = await fixture(t);
  await assert.rejects(bridge.sync(path.join(f.repo, 'mailbox'), f.pairing, f.repo, null, async () => f.response), /mimo Git/);
  const alias = path.join(f.base, 'alias'); await fs.symlink(f.repo, alias);
  await assert.rejects(bridge.safeDirectory(alias), /Symlink/);
  await assert.rejects(bridge.repository(f.repo, '/wrong'), /Identita/);
  await assert.rejects(bridge.sync(f.root, f.pairing, f.repo, null, async () => ({...f.response, session_id: crypto.randomUUID()})), /identita/);
});
test('rejects unsafe pairing URLs and expired credentials', () => {
  const pairing = {schema_version: 1, session_id: crypto.randomUUID(), project_id: crypto.randomUUID(), token: 'a'.repeat(43), repository: 'repo', endpoint: 'http://remote:8888', expires_at: Math.floor(Date.now()/1000)+100};
  assert.throws(() => bridge.validatePairing(pairing), /adresa/);
  assert.throws(() => bridge.validatePairing({...pairing, endpoint: 'http://127.0.0.1:8888', expires_at: 0}), /expirované/);
});
test('plugin settings map multiple projects and restore them after restart', async t => {
  const first = await fixture(t), second = await fixture(t);
  const Module = require('node:module');
  const load = Module._load;
  const commands = new Map(), state = new Map(), secrets = new Map();
  const pairing = {schema_version: 2, connection_id: crypto.randomUUID(), token: 'a'.repeat(43),
    name: 'Work IDE', endpoint: 'http://127.0.0.1:9999', expires_at: Math.floor(Date.now()/1000)+1000};
  const projects = [first, second].map((f, index) => ({project_id: f.pairing.project_id,
    title: 'Project ' + index, expected_head: 'b'.repeat(40)}));
  let mappings = [], folderPick = 0, selection = 'both';
  const synchronizations = [];
  const originalRequest = bridge.connectionRequest, originalSync = bridge.sync;
  bridge.connectionRequest = async (_pairing, request) => {
    if (request.action === 'status') return {connection_id: pairing.connection_id, name: pairing.name, projects, mappings};
    if (request.action === 'map') {
      const previous = mappings.find(item => item.project_id === request.mapping.project_id);
      assert.equal(request.mapping.expected_mapping, previous?.session_id || null);
      mappings = mappings.filter(item => item.project_id !== request.mapping.project_id);
      if (!request.mapping.enabled) return {enabled: false, session_id: null};
      const item = {...request.mapping, session_id: crypto.randomUUID(), bound: false,
        title: projects.find(p => p.project_id === request.mapping.project_id).title};
      mappings.push(item);return {enabled: true, session_id: item.session_id};
    }
    if (request.action === 'bind') {
      const item = mappings.find(m => m.session_id === request.session_id);item.bound = true;
      return item;
    }
    throw new Error('Unexpected request');
  };
  bridge.sync = async (root, child, repository) => {
    synchronizations.push({root, session: child.session_id, repository}); return {stale: false};
  };
  const vscode = {env: {}, StatusBarAlignment: {Left: 1},
    commands: {registerCommand: (name, callback) => {commands.set(name, callback);return {dispose(){}};}},
    workspace: {isTrusted: true, workspaceFolders: [first, second].map((f, index) => ({name: 'Local '+index, uri: {fsPath: f.repo}})),
      getConfiguration: () => ({get: () => false})},
    window: {createOutputChannel: () => ({appendLine(){},dispose(){}}),
      createStatusBarItem: () => ({show(){},dispose(){}}),
      showInformationMessage: async () => undefined,
      showErrorMessage: message => {throw new Error(message);},
      showWarningMessage: async () => 'Přiřadit',
      showQuickPick: async (items, options) => options.canPickMany ? (selection==='both' ? items : []) : items[folderPick++]}}
  ;
  Module._load = function(name, parent, isMain) {return name === 'vscode' ? vscode : load.call(this, name, parent, isMain);};
  const extensionPath = require.resolve('../extensions/workspace-bridge/extension');
  delete require.cache[extensionPath];
  const extension = require(extensionPath);
  const contexts = [];
  function context() {
    const result = {subscriptions: [], globalStorageUri: {fsPath: path.join(first.base, 'storage')},
      globalState: {get: key => state.get(key), update: async (key,value) => state.set(key,value)},
      secrets: {get: async key => secrets.get(key), store: async (key,value) => secrets.set(key,value), delete: async key => secrets.delete(key)}};
    contexts.push(result);return result;
  }
  t.after(() => {
    for (const ctx of contexts) for (const disposable of ctx.subscriptions) disposable.dispose();
    Module._load = load;bridge.connectionRequest = originalRequest;bridge.sync = originalSync;
    delete require.cache[extensionPath];
  });
  state.set('connection',pairing.connection_id);
  secrets.set('connection:'+pairing.connection_id,JSON.stringify({pairing,mappings:{}}));
  await extension.activate(context());
  await commands.get('workspaceBridge.configure')();
  const stored = JSON.parse(secrets.get('connection:'+pairing.connection_id));
  assert.equal(Object.keys(stored.mappings).length,2);
  assert.equal(new Set(synchronizations.map(item=>item.root)).size,2);
  assert.deepEqual(new Set(synchronizations.map(item=>item.repository)),new Set([first.repo,second.repo]));
  synchronizations.length=0;
  await extension.activate(context());
  assert.equal(synchronizations.length,2,'restart must restore both mappings');
  selection='none';
  await commands.get('workspaceBridge.configure')();
  assert.deepEqual(mappings,[]);
  assert.deepEqual(JSON.parse(secrets.get('connection:'+pairing.connection_id)).mappings,{});
});
