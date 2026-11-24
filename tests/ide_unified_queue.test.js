// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
// ADR 0090: one background poller per IDE profile, one merged queue, busy handling.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const bridge = require('../extensions/workspace-bridge/bridge');
const coordination = require('../extensions/workspace-bridge/coordination');
const unified = require('../extensions/workspace-bridge/unified');
const queue = require('../extensions/workspace-bridge/queue');
const {createSidebar} = require('../extensions/workspace-bridge/sidebar');

async function privateDir(t) {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'fpw-unified-'));
  t.after(() => fs.rm(base, {recursive: true, force: true}));
  const root = path.join(base, 'private');
  await bridge.safeDirectory(root);
  return {base, root};
}
async function repository(base, name) {
  const root = path.join(base, name);
  await fs.mkdir(root);
  execFileSync('git', ['init', '-q', root]);
  execFileSync('git', ['-C', root, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'init']);
  return fs.realpath(root);
}
// A valid pinned packet for one project with the given task IDs (no documents).
function packet(project, ids) {
  const manifest = {schema: 'fpw-queue-packet-v1', project_id: project.snapshot.project_id, session_id: project.session,
    revision: project.snapshot.revision, project_head: project.snapshot.commit_id, repository: project.identity,
    documents: [], tasks: ids.map(id => ({id, title: id, checklist: []})), instructions: 'Test'};
  const packet_id = crypto.createHash('sha256').update(queue.stable(manifest)).digest('hex');
  return {packet_id, manifest, blockers: [], linked_items: [],
    items: ids.map(id => ({id, title: 'Task ' + id, eligible: true, startable: true, status: 'planned'}))};
}
async function project(base, title, ids) {
  const repo = await repository(base, title.replace(/\W/g, ''));
  const session = crypto.randomUUID(), root = path.join(base, 'private', 'sessions', session);
  await bridge.safeDirectory(root);
  const value = {session, root, repository: repo, editor_workspace: repo, identity: repo, pending: [], state: {stale: false},
    snapshot: {project_id: crypto.randomUUID(), project_title: title, revision: crypto.randomUUID(), commit_id: 'a'.repeat(40),
      tasks: ids.map(id => ({id, title: 'Task ' + id, checked: false, checklist: []}))}};
  await bridge.atomic(path.join(root, 'queue.json'), JSON.stringify(packet(value, ids)));
  return value;
}

test('one lease holder per profile; expiry, dead or same process and release hand over', async t => {
  const {root} = await privateDir(t);
  let clock = 1000;
  const alive = new Set([11, 22]);
  const options = pid => ({pid, now: () => clock, isAlive: candidate => alive.has(candidate)});
  const first = coordination.createLease(root, options(11)), second = coordination.createLease(root, options(22));
  assert.equal(await first.acquire(), true);
  assert.equal(await second.acquire(), false, 'a live holder keeps the lease');
  assert.equal(await first.acquire(), true, 'the holder renews');
  clock += coordination.LEASE_MS + 1;
  assert.equal(await second.acquire(), true, 'an expired lease is taken over');
  assert.equal(await first.acquire(), false);
  alive.delete(22);
  assert.equal(await first.acquire(), true, 'a dead holder process is replaced');
  const reloaded = coordination.createLease(root, options(11));
  assert.equal(await reloaded.acquire(), true, 'a previous activation of the same process is replaced');
  await reloaded.release();
  alive.add(22);
  assert.equal(await second.acquire(), true, 'a released lease is free at once');
  await fs.writeFile(path.join(root, 'sync-lease.json'), '{torn', {mode: 0o600});
  assert.equal(await first.acquire(), true, 'a torn lease is repaired, not fatal');
  // Followers re-render exactly once per published generation.
  assert.equal(await second.changed(), null);
  await first.publish({status: 'Workspace: 2 projektů'});
  assert.equal((await second.changed()).status, 'Workspace: 2 projektů');
  assert.equal(await second.changed(), null);
  assert.equal(await first.changed(), null, 'the publisher does not re-render its own generation');
});

test('busy backoff grows to its bound and resets on success', () => {
  let clock = 0;
  const backoff = coordination.createBackoff({base: 10, max: 35, now: () => clock});
  assert.equal(backoff.due(), true);
  assert.deepEqual([backoff.failure(), backoff.failure(), backoff.failure(), backoff.failure()], [10, 20, 35, 35]);
  assert.equal(backoff.due(), false);
  clock = 35; assert.equal(backoff.due(), true);
  backoff.success(); assert.equal(backoff.failures, 0); assert.equal(backoff.due(), true);
});

test('merged queue follows owner order, keeps unknown refs visible and never adds unmapped projects', () => {
  const a = {snapshot: {project_id: crypto.randomUUID()}, queue: {items: [{id: 'A-1'}, {id: 'A-2'}, {id: 'A-3'}]}};
  const b = {snapshot: {project_id: crypto.randomUUID()}, queue: {items: [{id: 'B-1'}]}};
  const c = {snapshot: {project_id: crypto.randomUUID()}, queue: null};
  const hidden = crypto.randomUUID(), connection = crypto.randomUUID();
  const owner = unified.validateOwner({connection_id: connection, revision: 3, sessions: {},
    order: [[b.snapshot.project_id, 'B-1'], [a.snapshot.project_id, 'A-2'], [hidden, 'X-1'], [a.snapshot.project_id, 'A-9'],
      [a.snapshot.project_id, 'A-1'], [b.snapshot.project_id, 'B-1']]}, connection);
  const merged = unified.merge([a, b, c], owner);
  assert.equal(merged.ordered, true);
  assert.deepEqual(merged.rows.map(r => [r.taskId, r.missing, Boolean(r.unordered), r.index]),
    [['B-1', false, false, 0], ['A-2', false, false, 1], ['A-9', true, false, 2], ['A-1', false, false, 3], ['A-3', false, true, 4]]);
  assert.equal(merged.projects, 2);
  // Older Workspace: per-project order, explicitly not owner-ordered.
  const fallback = unified.merge([a, b], unified.validateOwner({unsupported: true, connection_id: connection}, connection));
  assert.equal(fallback.ordered, false);
  assert.deepEqual(fallback.rows.map(r => r.taskId), ['A-1', 'A-2', 'A-3', 'B-1']);
  assert.equal(unified.validateOwner({connection_id: crypto.randomUUID(), revision: 1, order: [], sessions: {}}, connection), null,
    'another connection order is ignored');
  for (const bad of [{connection_id: connection, revision: -1, order: [], sessions: {}},
    {connection_id: connection, revision: 1, order: [['not-a-uuid', 'X']], sessions: {}},
    {connection_id: connection, revision: 1, order: [[hidden]], sessions: {}}])
    assert.throws(() => unified.validateOwner(bad, connection), /Neplatn/);
});

test('owner-ordered items without a packet name the real cause instead of advising a sync', () => {
  const id = crypto.randomUUID(), connection = crypto.randomUUID();
  const owner = unified.validateOwner({connection_id: connection, revision: 1, sessions: {}, order: [[id, 'M-1']]}, connection);
  // Document export disabled: Workspace never publishes a packet, a sync cannot help.
  const disabled = {snapshot: {project_id: id}, queue: null, panel: {export_documents: false}};
  const [row] = unified.merge([disabled], owner).rows;
  assert.equal(row.missing, true);
  assert.match(unified.missingReason(row.project), /export podkladů/);
  assert.doesNotMatch(unified.missingReason(row.project), /balíčku projektu/);
  assert.match(unified.missingReason({queue: null, panel: {export_documents: true}}), /zatím nemá .* balíček fronty/);
  assert.match(unified.missingReason({queue: null, panel: null}), /zatím nemá .* balíček fronty/);
  assert.match(unified.missingReason({queue: {items: []}, panel: {export_documents: true}}), /Není v připnutém balíčku/);
});

test('active project prefers the explicit choice, then the open folder or workspace file', () => {
  const a = {snapshot: {project_id: 'a'}, repository: '/work/a', editor_workspace: '/work/a.code-workspace'};
  const b = {snapshot: {project_id: 'b'}, repository: '/work/b', editor_workspace: '/work/b'};
  assert.equal(unified.activeProject([a, b], undefined, {folders: ['/work/b/src']}), 'b');
  assert.equal(unified.activeProject([a, b], undefined, {folders: ['/work/bb']}), null, 'no prefix confusion');
  assert.equal(unified.activeProject([a, b], undefined, {workspaceFile: '/work/a.code-workspace'}), 'a');
  assert.equal(unified.activeProject([a, b], 'a', {folders: ['/work/b']}), 'a');
  assert.equal(unified.activeProject([a, b], 'all', {folders: ['/work/b']}), null);
  assert.equal(unified.activeProject([a, b], 'gone', {folders: ['/work/b']}), 'b', 'an unmapped choice falls back');
});

test('resource busy repeats reads and not-started writes only; others stay busy without retry', async t => {
  let calls = 0, outcome = 'unknown';
  const server = http.createServer((req, res) => {
    req.resume(); calls++;
    res.statusCode = 503; res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({error: 'resource busy', retry: 'same-operation', outcome, busy_resource: 'project'}));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const pairing = {schema_version: 2, connection_id: crypto.randomUUID(), name: 'Test', token: 'b'.repeat(43),
    endpoint: `http://127.0.0.1:${server.address().port}`, expires_at: Math.floor(Date.now() / 1000) + 1000};
  for (const action of ['panel', 'queue', 'owner-queue']) {
    calls = 0;
    await assert.rejects(bridge.connectionRequest(pairing, {action, request: {session_id: crypto.randomUUID()}}),
      error => error.busy === true && /zaneprázdněný/.test(error.message));
    assert.equal(calls, 4, action + ' is a read and is repeated');
  }
  calls = 0;
  await assert.rejects(bridge.connectionRequest(pairing, {action: 'exchange', request: {session_id: crypto.randomUUID(), messages: []}}),
    error => error.busy === true && error.status === 503 && /resource busy/.test(error.message));
  assert.equal(calls, 1, 'a write with an unknown outcome is never repeated automatically');
  outcome = 'not-started'; calls = 0;
  await assert.rejects(bridge.connectionRequest(pairing, {action: 'exchange', request: {session_id: crypto.randomUUID(), messages: []}}),
    error => error.busy === true);
  assert.equal(calls, 4, 'a write the server did not start may be repeated');
});

test('failed atomic publication leaves no orphan temporary file', async t => {
  const {root} = await privateDir(t);
  await fs.mkdir(path.join(root, 'target.json'), {mode: 0o700});
  await fs.writeFile(path.join(root, 'target.json', 'keep'), 'x');
  await assert.rejects(bridge.atomic(path.join(root, 'target.json'), '{}'));
  assert.deepEqual((await fs.readdir(root)).filter(name => name.endsWith('.tmp')), []);
});

test('an already published packet is refreshed with one request and unchanged AGENT.md', async t => {
  const {base} = await privateDir(t);
  const item = await project(base, 'Alpha', ['TASK-01']);
  const value = JSON.parse(await fs.readFile(path.join(item.root, 'queue.json'), 'utf8'));
  const requests = [];
  const request = async (_project, action) => { requests.push(action); return {queue: value}; };
  await queue.synchronize(item, request);
  assert.deepEqual(requests, ['queue', 'queue'], 'a new generation is checked again before publication');
  const agent = path.join(item.root, 'packets', value.packet_id, 'AGENT.md'), before = (await fs.stat(agent)).mtimeMs;
  requests.length = 0;
  await new Promise(resolve => setTimeout(resolve, 20));
  await queue.synchronize(item, request);
  assert.deepEqual(requests, ['queue']);
  assert.equal((await fs.stat(agent)).mtimeMs, before);
  await fs.rm(agent);
  requests.length = 0;
  await queue.synchronize(item, request);
  assert.deepEqual(requests, ['queue']);
  await fs.access(agent);
});

test('queue view shows this window project and all queued tasks with unique IDs; switching keeps actions per project', async t => {
  const {base} = await privateDir(t);
  const alpha = await project(base, 'Alpha', ['TASK-01', 'TASK-02']), beta = await project(base, 'Beta', ['TASK-01']);
  const connection = crypto.randomUUID();
  let owner = {connection_id: connection, revision: 1, sessions: {}, fetched_at: new Date().toISOString(),
    order: [[beta.snapshot.project_id, 'TASK-01'], [alpha.snapshot.project_id, 'TASK-02'], [alpha.snapshot.project_id, 'TASK-01']]};
  const commands = new Map(), views = new Map(), state = new Map(), opened = [];
  let pick = null;
  class Emitter { event = () => ({dispose() {}}); fire() {} dispose() {} }
  const vscode = {EventEmitter: Emitter, ThemeIcon: class { constructor(id) { this.id = id; } },
    TreeItem: class { constructor(label, state) { this.label = label; this.collapsibleState = state; } },
    TreeItemCollapsibleState: {None: 0, Collapsed: 1, Expanded: 2},
    commands: {registerCommand: (id, fn) => { commands.set(id, fn); return {dispose() {}}; }},
    workspace: {isTrusted: true, workspaceFolders: [{uri: {fsPath: beta.repository}}]},
    window: {createTreeView: (id, options) => { const view = {visible: false, provider: options.treeDataProvider,
      onDidChangeVisibility: () => ({dispose() {}}), dispose() {}}; views.set(id, view); return view; },
    showQuickPick: async items => items.find(pick), showErrorMessage: async message => { throw Error(message); }}};
  const context = {subscriptions: [], workspaceState: {get: key => state.get(key), update: async (key, value) => state.set(key, value)}};
  const sidebar = createSidebar(vscode, context, {projects: async () => [alpha, beta].map(p => ({...p})),
    request: async () => { throw Error('no remote read expected'); }, synchronize: async () => {},
    ownerQueue: async () => unified.validateOwner(owner, connection), open: async (target, title) => opened.push([target, title])});
  await sidebar.refresh(false);
  assert.equal(sidebar.active(), beta.snapshot.project_id, 'the open folder selects the project');
  const roots = sidebar.children('queue');
  assert.deepEqual(roots.map(r => r.kind), ['project', 'queueAll']);
  assert.equal(roots[0].projectId, beta.snapshot.project_id);
  assert.deepEqual(sidebar.children('queue', roots[0]).map(r => r.taskId), ['TASK-01']);
  const all = sidebar.children('queue', roots[1]);
  assert.deepEqual(all.map(r => [r.projectId, r.taskId]), owner.order);
  const items = [...sidebar.children('queue', roots[0]), ...all].map(sidebar.treeItem);
  assert.equal(new Set(items.map(i => i.id)).size, items.length, 'the same task under both nodes keeps unique tree IDs');
  assert.match(items[1].label, /^1\. /); assert.match(items[1].description, /^Beta · /);
  assert.equal(items[1].contextValue, 'queueTask.start', 'merged rows keep the per-project start action');
  assert.match(sidebar.treeItem(roots[1]).description, /3 položek · 2 projektů$/);
  assert.equal(sidebar.children('tasks').length, 1, 'other views focus this window project');
  // Switch to everything: the merged list becomes the root itself.
  pick = item => item.choice === 'all';
  await commands.get('workspaceBridge.switchProject')();
  assert.equal(state.get('activeProject'), 'all');
  assert.deepEqual(sidebar.children('queue').map(r => r.taskId), ['TASK-01', 'TASK-02', 'TASK-01']);
  assert.equal(sidebar.children('tasks').length, 2);
  assert.deepEqual(opened, []);
  // Switch to Alpha: focus moves and opening it is offered, never forced.
  pick = item => item.choice === alpha.snapshot.project_id;
  await commands.get('workspaceBridge.switchProject')();
  assert.equal(sidebar.children('queue')[0].projectId, alpha.snapshot.project_id);
  assert.deepEqual(opened, [[alpha.repository, 'Alpha']]);
  // An older Workspace without owner order: labelled per-project order.
  owner = {unsupported: true, connection_id: connection};
  await sidebar.refresh(false);
  assert.match(sidebar.treeItem({kind: 'queueAll'}).description, /pořadí po projektech/);
});

test('a sync requested during a run gets one follow-up run; busy projects are labelled and back off', async t => {
  const {base} = await privateDir(t);
  const Module = require('node:module'), load = Module._load;
  const repo = await repository(base, 'Repo');
  const connection = crypto.randomUUID(), session = crypto.randomUUID(), projectId = crypto.randomUUID();
  const pairing = {schema_version: 2, connection_id: connection, token: 'c'.repeat(43), name: 'IDE',
    endpoint: 'http://127.0.0.1:9', expires_at: Math.floor(Date.now() / 1000) + 1000};
  const mapping = {session_id: session, project_id: projectId, title: 'Alpha', repository: repo, editor_workspace: repo, bound: true, expected_head: 'a'.repeat(40)};
  const commands = new Map(), statusItems = [], requests = [];
  let gate = null, mode = 'ok', syncs = 0;
  const originalRequest = bridge.connectionRequest, originalSync = bridge.sync;
  bridge.connectionRequest = async (_pairing, body) => {
    requests.push(body.action);
    if (body.action === 'status') return {connection_id: connection, name: 'IDE', projects: [{project_id: projectId, title: 'Alpha', expected_head: mapping.expected_head}], mappings: [mapping]};
    if (body.action === 'owner-queue') throw Object.assign(new Error('Workspace odmítl synchronizaci (422): Unsupported connection action'), {status: 422});
    throw new Error('unexpected ' + body.action);
  };
  bridge.sync = async () => {
    syncs++;
    if (gate) await gate.promise;
    if (mode === 'busy') throw Object.assign(new Error('Workspace odmítl synchronizaci (503): resource busy'), {status: 503, busy: true});
    return {stale: false, has_queue: false, queue_refresh_error: null};
  };
  const vscode = {env: {}, StatusBarAlignment: {Left: 1},
    commands: {registerCommand: (name, callback) => { commands.set(name, callback); return {dispose() {}}; }},
    workspace: {isTrusted: true, workspaceFolders: [], getConfiguration: () => ({get: () => false})},
    window: {createOutputChannel: () => ({appendLine() {}, dispose() {}}),
      createStatusBarItem: () => { const item = {show() {}, dispose() {}}; statusItems.push(item); return item; },
      showInformationMessage: async () => {}, showWarningMessage: async () => {}, showErrorMessage: async message => { throw Error(message); }}};
  Module._load = function(name, parent, isMain) {
    if (name === 'vscode') return vscode;
    if (name === './sidebar' && parent.filename.endsWith('/workspace-bridge/extension.js'))
      return {createSidebar: () => ({refresh: async () => {}})};
    return load.call(this, name, parent, isMain);
  };
  const extensionPath = require.resolve('../extensions/workspace-bridge/extension');
  delete require.cache[extensionPath];
  const extension = require(extensionPath);
  const secrets = new Map([['connection:' + connection, JSON.stringify({pairing, mappings: {[session]: {repository: repo, editor_workspace: repo}}})]]);
  const context = {subscriptions: [], extensionPath: base, globalStorageUri: {fsPath: path.join(base, 'storage')},
    globalState: {get: key => key === 'connection' ? connection : undefined, update: async () => {}},
    secrets: {get: async key => secrets.get(key), store: async (key, value) => secrets.set(key, value), delete: async key => secrets.delete(key)}};
  t.after(() => { for (const item of context.subscriptions) item.dispose(); Module._load = load;
    bridge.connectionRequest = originalRequest; bridge.sync = originalSync; delete require.cache[extensionPath]; });
  await extension.activate(context);
  assert.equal(syncs, 1);
  const storage = path.join(base, 'storage', 'bridge-private');
  assert.equal(await fs.readFile(path.join(storage, 'sessions', session, 'queue.json'), 'utf8'), 'null', 'no packet clears the pointer without a request');
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(storage, 'owner-queue.json'), 'utf8')), {unsupported: true, connection_id: connection});
  assert.ok(!requests.includes('queue'));
  // Two requests during one in-flight run share exactly one follow-up run.
  syncs = 0; gate = {}; gate.promise = new Promise(resolve => { gate.resolve = resolve; });
  const first = commands.get('workspaceBridge.sync')();
  await new Promise(resolve => setTimeout(resolve, 20));
  const second = commands.get('workspaceBridge.sync')(), third = commands.get('workspaceBridge.sync')();
  gate.resolve(); gate = null;
  await Promise.all([first, second, third]);
  assert.equal(syncs, 2, 'one in-flight run plus one follow-up');
  requests.length = 0;
  await commands.get('workspaceBridge.sync')();
  assert.ok(!requests.includes('owner-queue'), 'an older Workspace is not asked again at once');
  // Lock contention: labelled as busy, last known state kept, not an error count.
  mode = 'busy';
  await commands.get('workspaceBridge.sync')();
  assert.match(statusItems[0].text, /1 zaneprázdněných/);
  assert.doesNotMatch(statusItems[0].text, /chyb/);
  const state = JSON.parse(await fs.readFile(path.join(storage, 'sessions', session, 'STATUS.json'), 'utf8'));
  assert.equal(state.busy, true); assert.equal(state.stale, true);
  const marker = JSON.parse(await fs.readFile(path.join(storage, 'sync-state.json'), 'utf8'));
  assert.equal(marker.status, statusItems[0].text, 'other windows get the same status text');
});

test('plan work states have distinct themed icons in tasks and queue', async t => {
  const {statusIcon, STATUS_ICONS} = require('../extensions/workspace-bridge/sidebar');
  assert.deepEqual(statusIcon({status: 'in progress'}), ['play-circle', 'charts.blue']);
  assert.deepEqual(statusIcon({status: 'completed'}), ['pass-filled', 'testing.iconPassed']);
  assert.deepEqual(statusIcon({status: 'failed'}), ['error', 'testing.iconFailed']);
  assert.deepEqual(statusIcon({status: 'resolved'}), ['check', 'charts.green']);
  assert.deepEqual(statusIcon({status: 'deferred'}), ['debug-pause', 'disabledForeground']);
  assert.deepEqual(statusIcon({status: 'novel'}), ['question', 'editorWarning.foreground'], 'an unknown state is never shown as planned');
  assert.deepEqual(statusIcon({checked: true}), STATUS_ICONS.completed);
  assert.deepEqual(statusIcon({checked: false}), STATUS_ICONS.planned);
  assert.equal(new Set(Object.values(STATUS_ICONS).map(([icon]) => icon)).size, 6);
  // Rendered tree items carry the icon and its theme colour.
  const {base} = await privateDir(t);
  const alpha = await project(base, 'Alpha', ['TASK-01', 'TASK-02']);
  const value = JSON.parse(await fs.readFile(path.join(alpha.root, 'queue.json'), 'utf8'));
  value.items[0].status = 'in progress'; value.items[1].held = true;
  await bridge.atomic(path.join(alpha.root, 'queue.json'), JSON.stringify(value));
  alpha.snapshot.tasks[0].status = 'in progress';
  class Emitter { event = () => ({dispose() {}}); fire() {} dispose() {} }
  const vscode = {EventEmitter: Emitter, ThemeIcon: class { constructor(id, color) { this.id = id; this.color = color; } },
    ThemeColor: class { constructor(id) { this.id = id; } },
    TreeItem: class { constructor(label, state) { this.label = label; this.collapsibleState = state; } },
    TreeItemCollapsibleState: {None: 0, Collapsed: 1, Expanded: 2}, commands: {registerCommand: () => ({dispose() {}})},
    workspace: {isTrusted: true, workspaceFolders: []},
    window: {createTreeView: (id, options) => ({visible: false, onDidChangeVisibility: () => ({dispose() {}}), dispose() {}})}};
  const sidebar = createSidebar(vscode, {subscriptions: []}, {projects: async () => [{...alpha}], request: async () => ({}), synchronize: async () => {}});
  await sidebar.refresh(false);
  const [running, held] = sidebar.children('queue').map(sidebar.treeItem);
  assert.deepEqual([running.iconPath.id, running.iconPath.color.id], ['play-circle', 'charts.blue']);
  assert.deepEqual([held.iconPath.id, held.iconPath.color.id], ['debug-pause', 'charts.yellow']);
  const task = sidebar.children('tasks', {kind: 'project', projectId: alpha.snapshot.project_id}).map(sidebar.treeItem)[0];
  assert.deepEqual([task.iconPath.id, task.iconPath.color.id], ['play-circle', 'charts.blue']);
});
