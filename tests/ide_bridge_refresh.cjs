// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
// Real HTTP/filesystem extension recovery, with only the editor API replaced.
'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const bridge = require('../extensions/workspace-bridge/bridge');
(async () => {
  const input = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
  let saved = JSON.stringify({pairing: input.pairing, mappings: {
    [input.session]: {repository: input.repository, editor_workspace: input.repository}}});
  const commands = new Map(), subscriptions = [], errors = [], opened = [];
  const oldRoot = path.join(input.storage, 'bridge-private', 'sessions', input.session);
  const vscode = {env: {}, StatusBarAlignment: {Left: 1}, Uri: {file: fsPath => ({fsPath})},
    workspace: {isTrusted: true, getConfiguration: () => ({get: () => false})},
    commands: {registerCommand: (name, fn) => {commands.set(name, fn); return {dispose(){}};}},
    window: {createOutputChannel: () => ({appendLine: text => errors.push(text), dispose(){}}),
      createStatusBarItem: () => ({show(){}, dispose(){}}),
      visibleTextEditors: [{document: {uri: {fsPath: path.join(oldRoot, 'TODO.md')}}, viewColumn: 1}],
      showTextDocument: async uri => {opened.push(uri.fsPath); await fs.access(uri.fsPath);},
      showWarningMessage: () => assert.fail('unexpected prompt'),
      showInformationMessage: () => assert.fail('unexpected prompt'),
      showErrorMessage: () => assert.fail('unexpected prompt')}};
  const load = Module._load;
  Module._load = function(name, ...args) {return name === 'vscode' ? vscode : load.call(this, name, ...args);};
  const extension = require('../extensions/workspace-bridge/extension');
  Module._load = load;
  const context = {subscriptions, globalStorageUri: {fsPath: input.storage},
    globalState: {get: name => name === 'connection' ? input.pairing.connection_id : undefined, update: async () => {}},
    secrets: {get: async () => saved, store: async (_key, value) => {saved = value;}}};
  const request = bridge.connectionRequest;
  const sync = bridge.sync;
  let lost = false, exportFailed = false;
  bridge.connectionRequest = async (...args) => {
    const response = await request(...args);
    if (!lost && args[1].action === 'map') {lost = true; throw new Error('lost map response');}
    return response;
  };
  bridge.sync = async (...args) => {
    if (args[1].session_id !== input.session && !exportFailed) {
      exportFailed = true; throw new Error('interrupted snapshot export');
    }
    return sync(...args);
  };
  try {
    await extension.activate(context);
    assert.ok(lost);
    assert.ok(JSON.parse(saved).mappings[input.session].refresh);
    await extension.activate(context); // fresh activation reads durable intent
    assert.ok(exportFailed);
    await extension.activate(context); // mapping saved, but its first export failed
    const mappings = JSON.parse(saved).mappings, sessions = Object.keys(mappings);
    assert.equal(sessions.length, 1);
    assert.notEqual(sessions[0], input.session);
    assert.equal(mappings[sessions[0]].repository, input.repository);
    assert.equal(mappings[sessions[0]].refresh, undefined);
    const root = path.join(input.storage, 'bridge-private', 'sessions', sessions[0]);
    const snapshot = JSON.parse(await fs.readFile(path.join(root, 'snapshot.json'), 'utf8'));
    assert.equal(snapshot.commit_id, input.head);
    assert.match(snapshot.todo, /TASK-03/);
    assert.equal(JSON.parse(await fs.readFile(path.join(root, 'STATUS.json'), 'utf8')).stale, false);
    assert.deepEqual(opened, [path.join(root, 'TODO.md')]);
    assert.ok(errors.some(text => text.includes('lost map response')));
    console.log(JSON.stringify({session: sessions[0], head: snapshot.commit_id}));
  } finally {
    for (const disposable of subscriptions) disposable.dispose();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
