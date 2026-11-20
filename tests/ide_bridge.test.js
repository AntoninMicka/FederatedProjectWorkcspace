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

test('connection transport waits for EOF, bounds its queue and recovers after rejection', async t => {
  const http = require('node:http');
  const seen = [];
  let finishFirst, firstSeen;
  const entered = new Promise(resolve => { firstSeen = resolve; });
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const request = JSON.parse(body);
      seen.push(request.action);
      if (request.action === 'hold') {
        res.writeHead(200, {'Content-Type': 'application/json'});
        res.write('{');
        finishFirst = () => res.end('"ok":true}');
        firstSeen();
      } else if (request.action === 'reject') {
        res.writeHead(422); res.end('{"error":"refused"}');
      } else res.end('{"ok":true}');
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const pairing = {schema_version: 2, connection_id: crypto.randomUUID(), token: 'a'.repeat(43),
    name: 'Test', expires_at: Math.floor(Date.now()/1000) + 1000,
    endpoint: `http://127.0.0.1:${server.address().port}`};
  const first = bridge.connectionRequest(pairing, {action: 'hold'});
  await entered;
  const refused = assert.rejects(bridge.connectionRequest(pairing, {action: 'reject'}), /422/);
  const following = Array.from({length: 30}, () => bridge.connectionRequest(pairing, {action: 'queued'}));
  await assert.rejects(bridge.connectionRequest(pairing, {action: 'overflow'}), /plná/);
  // Another connection progresses while this one waits for response EOF.
  await bridge.connectionRequest({...pairing, connection_id: crypto.randomUUID()}, {action: 'other'});
  // Status has its own backend lane and does not wait behind the held mutation.
  assert.deepEqual(await bridge.connectionRequest(pairing, {action: 'status'}), {ok: true});
  assert.deepEqual(seen, ['hold', 'other', 'status']);
  finishFirst();
  assert.deepEqual(await first, {ok: true});
  await refused;
  await Promise.all(following);
  assert.deepEqual(seen.slice(3), ['reject', ...Array(30).fill('queued')]);
  await bridge.connectionRequest(pairing, {action: 'after'});
  assert.equal(seen.at(-1), 'after');
});

test('expired queued requests never dispatch and do not break the next request', async t => {
  const http = require('node:http');
  let finish, firstSeen, calls = 0;
  const entered = new Promise(resolve => { firstSeen = resolve; });
  const server = http.createServer((req, res) => {
    req.resume();
    if (++calls === 1) { finish = () => res.end('{}'); firstSeen(); }
    else res.end('{}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const pairing = {schema_version: 2, connection_id: crypto.randomUUID(), token: 'a'.repeat(43),
    name: 'Test', expires_at: Math.floor(Date.now()/1000) + 1000,
    endpoint: `http://127.0.0.1:${server.address().port}`};
  const first = bridge.connectionRequest(pairing, {action: 'hold'});
  await entered;
  await assert.rejects(bridge.connectionRequest(pairing, {action: 'expired'}), /nebyl odeslán/);
  assert.equal(calls, 1);
  finish(); await first;
  await bridge.connectionRequest(pairing, {action: 'next'});
  assert.equal(calls, 2);
});

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
test('rejected requests expose a bounded reason and redact credentials without retrying writes', async t => {
  const http=require('node:http');let calls=0, stale=false;
  const pairing={schema_version:2,connection_id:crypto.randomUUID(),name:'IDE',token:'a'.repeat(43),
    endpoint:'',expires_at:Math.floor(Date.now()/1000)+1000};
  const server=http.createServer((req,res)=>{
    req.resume();calls++;res.statusCode=422;
    res.end(JSON.stringify({error:stale ? 'Packet superseded; Working queue changed; publish a new packet'
      : 'Bridge export exceeds 1 MiB\n'+pairing.token+' '+ 'x'.repeat(1000)}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  pairing.endpoint=`http://127.0.0.1:${server.address().port}`;
  await assert.rejects(bridge.connectionRequest(pairing,{action:'exchange'}),error=>{
    assert.equal(error.status,422);assert.match(error.message,/Bridge export exceeds 1 MiB/);
    assert(!error.message.includes(pairing.token));assert(!error.message.includes('\n'));
    assert(error.message.length<600);return true;
  });
  assert.equal(calls,1);
  stale=true;
  await assert.rejects(bridge.connectionRequest(pairing,{action:'exchange'}),error=>{
    assert.equal(error.staleReport,true);assert.equal(error.status,422);return true;
  });
  assert.equal(calls,2,'a terminal stale rejection must not retry the batch automatically');
});

test('typed codes, protocol header and legacy text both classify responses (AUDIT-B3, K6/K7)', async t => {
  const http=require('node:http');let calls=0, reply=null;const protocols=[];
  const server=http.createServer((req,res)=>{
    req.resume();calls++;protocols.push(req.headers['x-workspace-bridge-protocol']);
    const [status,body]=reply(calls);res.statusCode=status;res.end(JSON.stringify(body));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const pairing={schema_version:2,connection_id:crypto.randomUUID(),name:'IDE',token:'a'.repeat(43),
    endpoint:`http://127.0.0.1:${server.address().port}`,expires_at:Math.floor(Date.now()/1000)+1000};
  // New backend: the machine code decides, whatever the human text says.
  reply=n=>n<2?[503,{error:'Server je vytížený',code:'server_busy'}]:[200,{ok:true}];
  assert.deepEqual(await bridge.connectionRequest(pairing,{action:'status'}),{ok:true});
  assert.equal(calls,2);
  calls=0;reply=()=>[422,{error:'Report patří k nahrazenému exportu',code:'stale_report'}];
  await assert.rejects(bridge.connectionRequest(pairing,{action:'exchange'}),e=>e.staleReport===true);
  // A code wins over a matching legacy text: a different code is not busy or stale.
  calls=0;reply=()=>[503,{error:'server busy',code:'other'}];
  await assert.rejects(bridge.connectionRequest(pairing,{action:'status'}),/\(503\)/);assert.equal(calls,1);
  calls=0;reply=()=>[422,{error:'Wrong source revision',code:'other'}];
  await assert.rejects(bridge.connectionRequest(pairing,{action:'exchange'}),e=>e.staleReport===false);
  // Older backend without codes: the legacy text is still recognised.
  calls=0;reply=()=>[422,{error:'Wrong source revision'}];
  await assert.rejects(bridge.connectionRequest(pairing,{action:'exchange'}),e=>e.staleReport===true);
  // Protocol mismatch is shown with the side to update, never retried.
  calls=0;reply=()=>[426,{error:'Nepodporovaná verze schématu 1 pro ide-protocol; podporováno 2–2. Aktualizujte rozšíření Workspace.',
    code:'unsupported_version',update:'extension'}];
  await assert.rejects(bridge.connectionRequest(pairing,{action:'status'}),e=>e.status===426&&/Aktualizujte rozšíření/.test(e.message));
  assert.equal(calls,1);
  assert(protocols.every(value=>value==='1'),protocols.join(','));
});
test('pairing from a newer Workspace asks to update the extension', () => {
  const pairing={schema_version:3,connection_id:crypto.randomUUID(),name:'IDE',token:'a'.repeat(43),
    endpoint:'http://127.0.0.1:1',expires_at:Math.floor(Date.now()/1000)+1000};
  assert.throws(()=>bridge.validatePairing(pairing),/novější Workspace \(schéma 3, podporováno 1–2\)\. Aktualizujte rozšíření/);
  assert.throws(()=>bridge.validatePairing({...pairing,schema_version:0}),/Neplatné nebo expirované propojení/);
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
test('large snapshots stay readable when pretty JSON would exceed the file budget', async t => {
  const f=await fixture(t);
  f.response.snapshot.tasks=Array.from({length:1000},(_,i)=>({id:'TASK-'+i,
    description:'x'.repeat(1400),checklist:Array.from({length:10},()=>({text:'checkpoint',checked:false}))}));
  const snapshot=f.response.snapshot;
  assert(Buffer.byteLength(JSON.stringify(snapshot))<=2*1024*1024);
  assert(Buffer.byteLength(JSON.stringify(snapshot,null,2))>2*1024*1024);
  await bridge.sync(f.root,f.pairing,f.repo,null,async()=>f.response);
  assert.deepEqual(JSON.parse(await bridge.read(path.join(f.root,'snapshot.json'))),snapshot);
});

test('stale inbox report is retained without blocking current snapshot or other messages', async t => {
  const f = await fixture(t);
  await bridge.sync(f.root, f.pairing, f.repo, null, async () => f.response);
  const old = {message_id: crypto.randomUUID(), task_id: 'TASK-01', kind: 'progress'};
  const valid = {message_id: crypto.randomUUID(), task_id: 'TASK-02', kind: 'message'};
  for (const m of [old, valid]) await bridge.atomic(path.join(f.root, 'inbox', m.message_id+'.json'), JSON.stringify(m));
  const calls = [];
  const transport = async (_pairing, request) => {
    calls.push(request.messages.map(m=>m.message_id));
    if (request.messages.some(m=>m.message_id===old.message_id))
      throw Object.assign(new Error('Packet superseded'), {status:422, staleReport:true});
    return {...f.response, snapshot:{...f.response.snapshot, todo:'CURRENT TASKS'},
      receipts:request.messages.map(m=>({message_id:m.message_id,status:'received'}))};
  };
  const result = await bridge.sync(f.root, f.pairing, f.repo, null, transport);
  assert.equal(result.rejected_messages[0].message_id, old.message_id);
  assert.equal(await fs.readFile(path.join(f.root,'TODO.md'),'utf8'),'CURRENT TASKS');
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(f.root,'inbox',old.message_id+'.json'),'utf8')),old);
  await assert.rejects(fs.access(path.join(f.root,'receipts',old.message_id+'.json')), {code:'ENOENT'});
  calls.length=0;
  await bridge.sync(f.root, f.pairing, f.repo, null, transport);
  assert.deepEqual(calls,[[]]);
  await bridge.atomic(path.join(f.root,'inbox',old.message_id+'.json'),JSON.stringify({...old,body:'Changed'}));
  await assert.rejects(bridge.sync(f.root,f.pairing,f.repo,null,transport),/zpráva byla změněna/);
});

test('busy and unknown delivery never quarantine or discard an inbox report', async t => {
  const f = await fixture(t);
  await bridge.sync(f.root,f.pairing,f.repo,null,async()=>f.response);
  const m={message_id:crypto.randomUUID(),task_id:'TASK-01',kind:'completed'};
  await bridge.atomic(path.join(f.root,'inbox',m.message_id+'.json'),JSON.stringify(m));
  for (const failure of [Object.assign(new Error('resource busy'),{status:503}),new Error('lost response')]) {
    await assert.rejects(bridge.sync(f.root,f.pairing,f.repo,null,async()=>{throw failure;}));
    await assert.rejects(fs.access(path.join(f.root,'rejections',m.message_id+'.json')),{code:'ENOENT'});
    await fs.access(path.join(f.root,'inbox',m.message_id+'.json'));
  }
});

test('lost refresh after durable rejection recovers without sending rejected bytes again', async t => {
  const f=await fixture(t);
  await bridge.sync(f.root,f.pairing,f.repo,null,async()=>f.response);
  const m={message_id:crypto.randomUUID(),task_id:'TASK-01',kind:'progress'};
  await bridge.atomic(path.join(f.root,'inbox',m.message_id+'.json'),JSON.stringify(m));
  await assert.rejects(bridge.sync(f.root,f.pairing,f.repo,null,async(_p,request)=>{
    if(request.messages.length)throw Object.assign(new Error('Wrong source revision'),{staleReport:true,status:422});
    throw new Error('lost idle response');
  }),/lost idle response/);
  await bridge.sync(f.root,f.pairing,f.repo,null,async(_p,request)=>{
    assert.deepEqual(request.messages,[]);return f.response;
  });
  await fs.access(path.join(f.root,'inbox',m.message_id+'.json'));
  await fs.access(path.join(f.root,'rejections',m.message_id+'.json'));
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
  const synchronizations = [], notices = [], statusItems = [];
  let syncMode = 'ok', failSidebar = false, missingInbox = false;
  let loseMapResponse = false, loseBindResponse = false, mapCalls = 0, failStore = '', failSecrets = false;
  const outputLines = [];
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
    await fs.mkdir(root, {recursive: true, mode: 0o700});
    await fs.mkdir(path.join(root, 'inbox'), {recursive: true, mode: 0o700});
    await fs.mkdir(path.join(root, 'receipts'), {recursive: true});
    if (missingInbox) { missingInbox = false; await fs.rm(path.join(root, 'inbox'), {recursive: true}); }
    // 'review' = older backend (text only); 'review-typed' = typed state with a changed text (K6).
    if (syncMode === 'review-typed') return {queue_refresh_error: 'Fronta čeká na review: TASK-01 / report-id', queue_refresh_state: 'waiting_review', stale: true};
    return {queue_refresh_error: syncMode === 'review' ? 'Queue refresh waits for human review: TASK-01 / report-id (review the report in Workspace)' : null, stale: syncMode === 'review' || syncMode === 'stale' || (syncMode === 'refresh' && child.expected_head !== projects.find(p => p.project_id === child.project_id).expected_head)};
  };
  const vscode = {env: {}, StatusBarAlignment: {Left: 1},
    commands: {registerCommand: (name, callback) => {commands.set(name, callback);return {dispose(){}};}},
    workspace: {isTrusted: true, workspaceFolders: [first, second].map((f, index) => ({name: 'Local '+index, uri: {fsPath: f.repo}})),
      getConfiguration: () => ({get: () => false})},
    window: {createOutputChannel: () => ({appendLine(line){outputLines.push(line);},dispose(){}}),
      createStatusBarItem: () => {const item={show(){},dispose(){}};statusItems.push(item);return item;},
      showInformationMessage: async message => { notices.push({kind: 'info', message}); },
      showErrorMessage: message => {throw new Error(message);},
      showWarningMessage: async (message, options) => { if (!options?.modal) notices.push({kind: 'warning', message}); return 'Přiřadit'; },
      showQuickPick: async (items, options) => options.canPickMany ? (selection==='both' ? items : []) : items[folderPick++]}}
  ;
  Module._load = function(name, parent, isMain) {
    if (name === 'vscode') return vscode;
    if (name === './sidebar' && parent.filename.endsWith('/workspace-bridge/extension.js'))
      return {createSidebar: () => ({refresh: async () => {
        if (failSidebar) {failSidebar = false; throw Error('panel failed');}
      }})};
    return load.call(this, name, parent, isMain);
  };
  const extensionPath = require.resolve('../extensions/workspace-bridge/extension');
  delete require.cache[extensionPath];
  const extension = require(extensionPath);
  const contexts = [];
  function context() {
    const result = {subscriptions: [], globalStorageUri: {fsPath: path.join(first.base, 'storage')},
      globalState: {get: key => state.get(key), update: async (key,value) => state.set(key,value)},
      secrets: {get: async key => { if (failSecrets) throw new Error('SecretStorage read failed'); return secrets.get(key); }, store: async (key,value) => {
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
  assert.equal(statusItems.at(-1).command,'workspaceBridge.sync','restored connection must not open settings');
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
    assert.equal(statusItems.at(-1).command,'workspaceBridge.sync','failed sync must not redirect to configuration');
  }
  for (const mode of ['review', 'review-typed']) {
    syncMode = mode; notices.length = 0;
    await commands.get('workspaceBridge.sync')();
    assert.match(notices[0].message, /2 projektů, 2 zastaralých, 0 chyb/);
    assert.match(notices[0].message, /čeká na posouzení/);
    for (const mapping of mappings) {
      const file = path.join(first.base,'storage','bridge-private','sessions',mapping.session_id,'STATUS.json');
      const status = JSON.parse(await fs.readFile(file,'utf8'));
      assert.equal(status.waiting_review,true);
      assert.match(status.queue_refresh_error, /TASK-01.*report-id/);
      assert.equal(status.error,undefined);
    }
  }
  // B-ODD-10: a failed unavailability report is logged, not silently swallowed.
  failSecrets = true; outputLines.length = 0;
  await assert.rejects(commands.get('workspaceBridge.sync')(), /SecretStorage read failed/);
  failSecrets = false;
  assert.ok(outputLines.some(line => line === 'Hlášení nedostupnosti do Workspace selhalo: SecretStorage read failed'), outputLines.join('\n'));
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
  // A presentation failure must not leave the synchronization guard latched.
  failSidebar = true;
  await commands.get('workspaceBridge.sync')();
  const syncsBefore = synchronizations.length;
  await commands.get('workspaceBridge.sync')();
  assert.equal(synchronizations.length, syncsBefore + 2);
  // An interrupted/local cleanup before inbox creation is an empty outbox, not a blocker.
  projects[0].expected_head = '4'.repeat(40); missingInbox = true;
  await commands.get('workspaceBridge.sync')();
  assert.equal(mappings.find(m => m.project_id === previous.project_id).expected_head, projects[0].expected_head);
  assert.equal(notices.at(-1).kind, 'info');
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
