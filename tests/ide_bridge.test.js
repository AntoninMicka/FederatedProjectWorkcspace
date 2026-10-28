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
