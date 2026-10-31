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

test('HTTP retries only pre-dispatch busy responses and bounds persistent overload', async t => {
  const http = require('node:http');
  let calls = 0, mode = 'recover';
  const server = http.createServer((req, res) => {
    req.resume();
    calls++;
    res.setHeader('Content-Type', 'application/json');
    if (mode === 'recover' && calls > 2) return res.end('{"ok":true}');
    res.statusCode = mode === 'forbidden' ? 403 : 503;
    res.end(mode === 'other' ? '{"error":"unavailable"}' : '{"error":"server busy"}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const pairing = {schema_version: 2, connection_id: crypto.randomUUID(), name: 'Test IDE',
    token: 'a'.repeat(43), endpoint: `http://127.0.0.1:${server.address().port}`,
    expires_at: Math.floor(Date.now()/1000) + 1000};
  assert.deepEqual(await bridge.connectionRequest(pairing, {action: 'status'}), {ok: true});
  assert.equal(calls, 3);
  mode = 'busy'; calls = 0;
  await assert.rejects(bridge.connectionRequest(pairing, {action: 'status'}), /zaneprázdněný/);
  assert.equal(calls, 4);
  for (const value of ['other', 'forbidden']) {
    mode = value; calls = 0;
    await assert.rejects(bridge.connectionRequest(pairing, {action: 'status'}),
      value === 'other' ? /\(503\)/ : /\(403\)/);
    assert.equal(calls, 1);
  }
});

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
  const synchronizations = [], notices = [];
  let syncMode = 'ok';
  let loseMapResponse = false, loseBindResponse = false, mapCalls = 0, failStore = '';
  const originalRequest = bridge.connectionRequest, originalSync = bridge.sync;
  bridge.connectionRequest = async (_pairing, request) => {
    if (request.action === 'status') return {connection_id: pairing.connection_id, name: pairing.name, projects, mappings};
    if (request.action === 'map') {
      mapCalls++;
      const previous = mappings.find(item => item.project_id === request.mapping.project_id);
      assert.equal(request.mapping.expected_mapping, previous?.session_id || null);
      mappings = mappings.filter(item => item.project_id !== request.mapping.project_id);
      if (!request.mapping.enabled) return {enabled: false, session_id: null};
      const item = {...request.mapping, session_id: crypto.randomUUID(), bound: false,
        title: projects.find(p => p.project_id === request.mapping.project_id).title};
      mappings.push(item);
      if (loseMapResponse) { loseMapResponse = false; throw new Error('lost map response'); }
      return {enabled: true, session_id: item.session_id};
    }
    if (request.action === 'bind') {
      const item = mappings.find(m => m.session_id === request.session_id);item.bound = true;
      if (loseBindResponse) { loseBindResponse = false; throw new Error('lost bind response'); }
      return item;
    }
    throw new Error('Unexpected request');
  };
  bridge.sync = async (root, child, repository) => {
    synchronizations.push({root, session: child.session_id, repository});
    if (syncMode === 'failed' || (syncMode === 'partial' && repository === first.repo)) throw new Error('socket hang up');
    await fs.mkdir(path.join(root, 'inbox'), {recursive: true});
    await fs.mkdir(path.join(root, 'receipts'), {recursive: true});
    return {stale: syncMode === 'stale' || (syncMode === 'refresh' && child.expected_head !== projects.find(p => p.project_id === child.project_id).expected_head)};
  };
  const vscode = {env: {}, StatusBarAlignment: {Left: 1},
    commands: {registerCommand: (name, callback) => {commands.set(name, callback);return {dispose(){}};}},
    workspace: {isTrusted: true, workspaceFolders: [first, second].map((f, index) => ({name: 'Local '+index, uri: {fsPath: f.repo}})),
      getConfiguration: () => ({get: () => false})},
    window: {createOutputChannel: () => ({appendLine(){},dispose(){}}),
      createStatusBarItem: () => ({show(){},dispose(){}}),
      showInformationMessage: async message => { notices.push({kind: 'info', message}); },
      showErrorMessage: message => {throw new Error(message);},
      showWarningMessage: async (message, options) => { if (!options?.modal) notices.push({kind: 'warning', message}); return 'Přiřadit'; },
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
      secrets: {get: async key => secrets.get(key), store: async (key,value) => {
        const pending = Object.values(JSON.parse(value).mappings).some(local => local.refresh);
        if ((failStore === 'intent' && pending) || (failStore === 'final' && !pending)) {
          failStore = ''; throw new Error('SecretStorage unavailable');
        }
        secrets.set(key,value);
      }, delete: async key => secrets.delete(key)}};
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
  for (const [mode, pattern] of [['stale', /2 projektů, 2 zastaralých, 0 chyb/],
      ['partial', /1 projektů, 0 zastaralých, 1 chyb/], ['failed', /0 projektů, 0 zastaralých, 2 chyb/]]) {
    syncMode = mode; notices.length = 0;
    await commands.get('workspaceBridge.sync')();
    assert.equal(notices.length, 1);
    assert.equal(notices[0].kind, 'warning');
    assert.match(notices[0].message, pattern);
  }
  syncMode = 'ok'; notices.length = 0;
  await commands.get('workspaceBridge.sync')();
  assert.equal(notices[0].kind, 'info');
  assert.match(notices[0].message, /2 projektů, 0 zastaralých, 0 chyb/);
  // A changed assignment follows HEAD without picking a folder or changing its identity.
  syncMode = 'refresh';
  const previous = {...mappings[0]}, picksBefore = folderPick;
  const historical = path.join(first.base, 'storage', 'bridge-private', 'sessions', previous.session_id);
  const messageName = crypto.randomUUID() + '.json';
  await fs.writeFile(path.join(historical, 'inbox', messageName), '{"old":"message"}');
  projects[0].expected_head = 'c'.repeat(40);
  await commands.get('workspaceBridge.sync')();
  assert.equal(mappings[0].session_id, previous.session_id, 'pending old messages postpone refresh');
  await fs.writeFile(path.join(historical, 'receipts', messageName), JSON.stringify({message_id: messageName.slice(0, -5), status: 'stale'}));
  await commands.get('workspaceBridge.sync')();
  let refreshed = mappings.find(m => m.project_id === previous.project_id);
  assert.notEqual(refreshed.session_id, previous.session_id);
  assert.equal(refreshed.expected_head, projects[0].expected_head);
  assert.equal(refreshed.repository, previous.repository);
  assert.equal(refreshed.editor_workspace, previous.editor_workspace);
  assert.equal(folderPick, picksBefore, 'revision refresh must not prompt for a target');
  assert.equal(await fs.readFile(path.join(historical, 'inbox', messageName), 'utf8'), '{"old":"message"}');
  assert.equal(notices.at(-1).kind, 'info');
  // Server commit with lost map/bind response is resumed from persisted intent on restart.
  for (const stage of ['map', 'bind']) {
    projects[0].expected_head = (stage === 'map' ? 'd' : 'e').repeat(40);
    if (stage === 'map') loseMapResponse = true; else loseBindResponse = true;
    await commands.get('workspaceBridge.sync')();
    assert.match(notices.at(-1).message, /1 projektů, 0 zastaralých, 1 chyb/);
    const saved = JSON.parse(secrets.get('connection:'+pairing.connection_id));
    assert.ok(Object.values(saved.mappings).some(local => local.refresh));
    const callsBefore = mapCalls;
    // A newer server HEAD does not cause the lost response to create yet another session.
    if (stage === 'map') projects[0].expected_head = 'f'.repeat(40);
    await extension.activate(context());
    assert.equal(mapCalls, callsBefore);
    const recovered = JSON.parse(secrets.get('connection:'+pairing.connection_id));
    assert.ok(Object.values(recovered.mappings).every(local => !local.refresh));
    assert.equal(Object.keys(recovered.mappings).length, 2);
    await commands.get('workspaceBridge.sync')();
    assert.equal(notices.at(-1).kind, 'info');
  }
  // Do not adopt an intervening target change after a lost response.
  projects[0].expected_head = '1'.repeat(40); loseMapResponse = true;
  await commands.get('workspaceBridge.sync')();
  refreshed = mappings.find(m => m.project_id === previous.project_id);
  refreshed.editor_workspace = '/different-target';
  const callsBeforeConflict = mapCalls;
  await commands.get('workspaceBridge.sync')();
  assert.equal(mapCalls, callsBeforeConflict);
  assert.match(notices.at(-1).message, /1 projektů, 0 zastaralých, 1 chyb/);
  refreshed.editor_workspace = previous.editor_workspace;
  await commands.get('workspaceBridge.sync')();
  assert.equal(notices.at(-1).kind, 'info');
  for (const stage of ['intent', 'final']) {
    projects[0].expected_head = (stage === 'intent' ? '2' : '3').repeat(40);
    failStore = stage;
    const callsBefore = mapCalls;
    await commands.get('workspaceBridge.sync')();
    assert.match(notices.at(-1).message, /1 projektů, 0 zastaralých, 1 chyb/);
    assert.equal(mapCalls, callsBefore + (stage === 'intent' ? 0 : 1));
    await extension.activate(context());
    assert.ok(Object.values(JSON.parse(secrets.get('connection:'+pairing.connection_id)).mappings)
      .every(local => !local.refresh));
    await commands.get('workspaceBridge.sync')();
    assert.equal(notices.at(-1).kind, 'info');
  }
  selection='none';
  await commands.get('workspaceBridge.configure')();
  assert.equal(notices.at(-1).kind, 'warning');
  assert.match(notices.at(-1).message, /Nastavení projektů/);
  assert.deepEqual(mappings,[]);
  assert.deepEqual(JSON.parse(secrets.get('connection:'+pairing.connection_id)).mappings,{});
});

test('signed desktop discovery recovers old credentials and refuses unsafe destinations', async t => {
  const f = await fixture(t);
  const root = path.join(f.base, 'discovery');
  await fs.mkdir(root, {mode: 0o700});
  const id = f.pairing.session_id;
  const file = path.join(root, id + '.json');
  const write = async (endpoint, changes = {}) => {
    const key = crypto.createHash('sha256').update(f.pairing.token).digest();
    const signature = crypto.createHmac('sha256', key).update(id + '\n' + endpoint).digest('hex');
    await bridge.atomic(file, JSON.stringify({id, endpoint, signature, ...changes}));
  };
  assert.deepEqual(await bridge.discover(f.pairing, root), f.pairing);
  await write('http://127.0.0.1:12345');
  assert.equal((await bridge.discover(f.pairing, root)).endpoint, 'http://127.0.0.1:12345');
  await write('http://127.0.0.1:12346');
  assert.equal((await bridge.discover(f.pairing, root)).endpoint, 'http://127.0.0.1:12346');
  await write('http://127.0.0.1:12346', {signature: '0'.repeat(64)});
  await assert.rejects(bridge.discover(f.pairing, root), /Podpis/);
  await write('http://127.0.0.1:12346', {id: crypto.randomUUID()});
  await assert.rejects(bridge.discover(f.pairing, root), /Neplatná/);
  for (const endpoint of ['http://evil.example:1234', 'https://127.0.0.1:1234',
      'http://127.0.0.1:1234/other', 'http://user:password@127.0.0.1:1234']) {
    await write(endpoint);
    await assert.rejects(bridge.discover(f.pairing, root));
  }
  await write('http://127.0.0.1:12346');
  await fs.chmod(file, 0o644);
  await assert.rejects(bridge.discover(f.pairing, root), /oprávnění/);
  await fs.chmod(file, 0o600);
  const alias = path.join(f.base, 'discovery-alias');
  await fs.symlink(root, alias);
  await assert.rejects(bridge.discover(f.pairing, alias), /adresář/);
  await fs.writeFile(file, '{');
  await assert.rejects(bridge.discover(f.pairing, root), SyntaxError);
  const web = {...f.pairing, endpoint: 'https://example.test:4433'};
  assert.deepEqual(await bridge.discover(web, root), web);
  await fs.rm(file);
  await fs.symlink(path.join(f.base, 'other'), file);
  await assert.rejects(bridge.discover(f.pairing, root), /soubor/);
});
