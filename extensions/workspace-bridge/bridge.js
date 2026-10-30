// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const crypto = require('node:crypto');
const os = require('node:os');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const exec = promisify(execFile);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
async function git(root, ...args) {
  return (await exec('git', ['-C', root, ...args], {timeout: 5000, maxBuffer: 65536})).stdout.trim();
}
async function outsideGit(root) {
  try { await git(root, 'rev-parse', '--show-toplevel'); }
  catch (error) { if (error.code === 128) return; throw error; }
  throw new Error('Komunikační soubory musí být mimo Git.');
}
async function safeDirectory(root) {
  await fs.mkdir(root, {recursive: true, mode: 0o700});
  if (path.resolve(root) !== await fs.realpath(root)) throw new Error('Symlink v komunikační cestě.');
  const stat = await fs.lstat(root);
  if (!stat.isDirectory()) throw new Error('Očekáván adresář.');
  if (process.platform !== 'win32' && (stat.mode & 0o077)) throw new Error('Adresář musí mít oprávnění 0700.');
  await outsideGit(root);
}
async function regular(file) {
  const stat = await fs.lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > 2 * 1024 * 1024)
    throw new Error('Nepodporovaný nebo příliš velký soubor.');
}
async function read(file) {
  await regular(file);
  return fs.readFile(file, 'utf8');
}
async function atomic(file, data) {
  await safeDirectory(path.dirname(file));
  const temporary = path.join(path.dirname(file), '.' + crypto.randomUUID() + '.tmp');
  const handle = await fs.open(temporary, 'wx', 0o600);
  try { await handle.writeFile(data); await handle.sync(); } finally { await handle.close(); }
  await fs.rename(temporary, file);
}
function validatePairing(pairing) {
  if (!pairing || ![1, 2].includes(pairing.schema_version) || !/^[A-Za-z0-9_-]{43}$/.test(pairing.token)
      || !Number.isInteger(pairing.expires_at) || pairing.expires_at * 1000 <= Date.now())
    throw new Error('Neplatné nebo expirované propojení.');
  if (pairing.schema_version === 2 && (!UUID.test(pairing.connection_id) || typeof pairing.name !== 'string'))
    throw new Error('Neplatné připojení k Workspace.');
  if ((pairing.schema_version === 1 || pairing.session_id) &&
      (!UUID.test(pairing.session_id) || !UUID.test(pairing.project_id) || typeof pairing.repository !== 'string' || !pairing.repository))
    throw new Error('Neplatné propojení projektu.');
  const url = new URL(pairing.endpoint);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || !url.port
      || (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))))
    throw new Error('Nepovolená adresa Workspace.');
  return pairing;
}
async function repository(root, identity) {
  const actual = await fs.realpath(root);
  if (await fs.realpath(await git(actual, 'rev-parse', '--show-toplevel')) !== actual) throw new Error('Vyberte kořen Git repozitáře.');
  let remote = '';
  try { remote = await git(actual, 'remote', 'get-url', 'origin'); } catch (_) { /* local repository */ }
  if (identity !== actual && identity !== remote) throw new Error('Identita repozitáře nesouhlasí s propojením.');
  return {root: actual, commit: await git(actual, 'rev-parse', 'HEAD')};
}
async function discover(pairing, root = path.join(os.homedir(), '.local', 'state', 'federated-workspace', 'ide-discovery')) {
  validatePairing(pairing);
  // Web/TLS connections never consult local discovery or downgrade transport.
  if (new URL(pairing.endpoint).protocol !== 'http:') return pairing;
  const id = pairing.connection_id || pairing.session_id;
  let text;
  try {
    const stat = await fs.lstat(root);
    if (!stat.isDirectory() || stat.isSymbolicLink() || path.resolve(root) !== await fs.realpath(root)
        || (process.getuid && (stat.uid !== process.getuid() || (stat.mode & 0o077))))
      throw new Error('Neplatný adresář pro obnovení spojení.');
    await outsideGit(root);
    const file = path.join(root, id + '.json');
    await regular(file);
    const info = await fs.lstat(file);
    if (process.getuid && (info.uid !== process.getuid() || (info.mode & 0o077)))
      throw new Error('Neplatná oprávnění adresy Workspace.');
    text = await read(file);
  } catch (error) {
    if (error.code === 'ENOENT') return pairing; // compatibility with older desktop
    throw error;
  }
  const value = JSON.parse(text);
  if (value.id !== id || typeof value.endpoint !== 'string' || !/^[a-f0-9]{64}$/.test(value.signature))
    throw new Error('Neplatná adresa pro obnovení spojení.');
  const key = crypto.createHash('sha256').update(pairing.token).digest();
  const signature = crypto.createHmac('sha256', key).update(id + '\n' + value.endpoint).digest();
  if (!crypto.timingSafeEqual(signature, Buffer.from(value.signature, 'hex')))
    throw new Error('Podpis adresy Workspace nesouhlasí.');
  const url = new URL(value.endpoint);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1')
    throw new Error('Obnovení spojení vyžaduje lokální Workspace.');
  return validatePairing({...pairing, endpoint: value.endpoint});
}
async function httpRequest(pairing, route, body, ca, attempt = 0) {
  pairing = await discover(pairing);
  const url = new URL(route, pairing.endpoint);
  const data = JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const transport = url.protocol === 'https:' ? https : http;
    const options = {method: 'POST', headers: {'Authorization': 'Bearer ' + pairing.token,
      'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data)}};
    if (ca) options.ca = ca;
    const req = transport.request(url, options, response => {
      let chunks = [], size = 0;
      response.on('data', chunk => {size += chunk.length; if (size > 4 * 1024 * 1024) req.destroy(new Error('Příliš velká odpověď.')); else chunks.push(chunk);});
      response.on('error', reject);
      response.on('end', () => {try {
        const text = Buffer.concat(chunks).toString('utf8');
        // This response is emitted before dispatch: replay cannot repeat a write.
        let busy = false;
        if (response.statusCode === 503) {
          try { busy = JSON.parse(text).error === 'server busy'; } catch (_) { /* other 503 */ }
        }
        if (busy && attempt < 3) {
          setTimeout(() => httpRequest(pairing, route, body, ca, attempt + 1).then(resolve, reject),
            250 * (2 ** attempt));
          return;
        }
        if (busy) throw new Error('Workspace je zaneprázdněný. Synchronizaci zkuste znovu za chvíli (503).');
        if (response.statusCode !== 200) throw new Error(`Workspace odmítl synchronizaci (${response.statusCode}).`);
        resolve(JSON.parse(text));
      } catch (error) { reject(error); }});
    });
    req.setTimeout(10000, () => req.destroy(new Error('Workspace neodpovídá.')));
    req.on('error', reject); req.end(data);
  });
}
function connectionRequest(pairing, body, ca) {
  return httpRequest(pairing, '/v1/ide-bridge/connection/exchange', {...body, connection_id: pairing.connection_id}, ca);
}
function request(pairing, body, ca) {
  return pairing.connection_id ? connectionRequest(pairing, {action: 'exchange', request: body}, ca)
    : httpRequest(pairing, '/v1/ide-bridge/exchange', body, ca);
}
async function sync(root, pairing, repoRoot, ca, transport = request) {
  validatePairing(pairing);
  await repository(repoRoot, pairing.repository);
  await safeDirectory(root);
  for (const dir of ['inbox', 'receipts']) await safeDirectory(path.join(root, dir));
  const files = (await fs.readdir(path.join(root, 'inbox'))).filter(name => /^[0-9a-f-]{36}\.json$/.test(name)).sort();
  const messages = [];
  for (const name of files) {
    if (messages.length === 20) break;
    const message = JSON.parse(await read(path.join(root, 'inbox', name)));
    if (!UUID.test(message.message_id) || name !== message.message_id + '.json') throw new Error('Neshoda ID zprávy.');
    try {
      const receipt = JSON.parse(await read(path.join(root, 'receipts', name)));
      if (receipt.message_id === message.message_id) continue;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    messages.push(message);
  }
  const result = await transport(pairing, {session_id: pairing.session_id, messages}, ca);
  if (result.session_id !== pairing.session_id || result.snapshot?.project_id !== pairing.project_id
      || result.repository !== pairing.repository || typeof result.snapshot.todo !== 'string'
      || !Array.isArray(result.receipts)) throw new Error('Nesouhlasí identita odpovědi.');
  for (const receipt of result.receipts) {
    if (!messages.some(m => m.message_id === receipt.message_id) || !['received', 'stale'].includes(receipt.status))
      throw new Error('Neočekávané potvrzení.');
    await atomic(path.join(root, 'receipts', receipt.message_id + '.json'), JSON.stringify(receipt, null, 2));
  }
  await atomic(path.join(root, 'TODO.md'), result.snapshot.todo);
  await atomic(path.join(root, 'INSTRUCTIONS.md'),
    '# Instrukce\n\n' + result.instructions + '\n\nTODO je export připnuté revize. Neupravujte jej jako autoritativní plán.\n'
    + 'Zprávy zapisujte do inbox/<message_id>.json přes dočasný soubor a přejmenování.\n'
    + 'Doručení a lidská akceptace jsou oddělené. Přijetí ověřte v receipts/.\n'
    + 'Povolené kind: completed, clarification, message. task_id vyberte ze snapshot.json.\n'
    + 'message_id je nové UUID; revision je snapshot.revision; repository_commit je skutečný Git HEAD.\n'
    + 'Přihlašovací údaje do schránky nepatří.\n');
  // The snapshot is published last. Recovery reruns the same immutable export.
  await atomic(path.join(root, 'snapshot.json'), JSON.stringify(result.snapshot, null, 2));
  await atomic(path.join(root, 'STATUS.json'), JSON.stringify({stale: result.stale, synchronized_at: new Date().toISOString()}, null, 2));
  return result;
}
module.exports = {discover, git, outsideGit, safeDirectory, read, atomic, validatePairing, repository, request, connectionRequest, sync};
