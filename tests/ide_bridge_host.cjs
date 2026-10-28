// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
exports.run = async function () {
  const fixture = JSON.parse(await fs.readFile(process.env.WORKSPACE_BRIDGE_SMOKE, 'utf8'));
  const extension = vscode.extensions.getExtension('federated-workspace.workspace-file-bridge');
  assert.ok(extension, 'installed extension must be discovered');
  await extension.activate();
  assert.ok(extension.isActive);
  const commands = await vscode.commands.getCommands();
  assert.ok(commands.includes('workspaceBridge.connect'));
  const bridge = require(path.join(extension.extensionPath, 'bridge.js'));
  const result = await bridge.sync(fixture.mailbox, fixture.pairing, fixture.repository);
  const message = {message_id: crypto.randomUUID(), task_id: 'TASK-01', kind: 'completed',
    body: 'Real VSCodium extension host smoke', revision: result.snapshot.revision,
    repository_commit: await bridge.git(fixture.repository, 'rev-parse', 'HEAD')};
  await bridge.atomic(path.join(fixture.mailbox, 'inbox', message.message_id + '.json'), JSON.stringify(message));
  const response = await bridge.sync(fixture.mailbox, fixture.pairing, fixture.repository);
  assert.equal(response.receipts[0].status, 'received');
  await bridge.sync(fixture.mailbox, fixture.pairing, fixture.repository);
  assert.equal(await bridge.git(fixture.repository, 'status', '--porcelain'), '');
  await fs.writeFile(fixture.result, JSON.stringify({active: true, receipt: response.receipts[0], todo: await fs.readFile(path.join(fixture.mailbox, 'TODO.md'), 'utf8')}));
};
