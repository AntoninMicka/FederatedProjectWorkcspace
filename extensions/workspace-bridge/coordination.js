// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
// Cross-window coordination of background synchronization (ADR 0090).
// Every IDE window shares one profile, one connection and one mailbox. Only the
// lease holder polls Workspace in the background; the other windows render the
// files it publishes. The lease is coordination only: it never authorizes or
// orders project data, messages, receipts or review, and losing it is harmless.
const path = require('node:path');
const crypto = require('node:crypto');
const bridge = require('./bridge');

const LEASE_MS = 30000;

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (error) { return error.code === 'EPERM'; }
}

async function readJSON(file) {
  try { return JSON.parse(await bridge.read(file)); }
  catch (error) {
    if (error.code === 'ENOENT') return null;
    // A torn or foreign lease is treated as free; atomic replace repairs it.
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}

function createLease(root, {id = crypto.randomUUID(), pid = process.pid, now = Date.now, isAlive = alive} = {}) {
  const leaseFile = path.join(root, 'sync-lease.json'), markerFile = path.join(root, 'sync-state.json');
  let seen = null;
  async function holder() {
    const value = await readJSON(leaseFile);
    if (!value || typeof value.holder !== 'string' || !Number.isFinite(value.expires_at)) return null;
    // Each IDE window has its own extension host process: a lease of this
    // process under another ID is a previous activation (reload/restart).
    if (value.holder !== id && (value.expires_at <= now() || value.pid === pid || !isAlive(value.pid))) return null;
    return value;
  }
  return {
    id,
    // Last writer wins a simultaneous takeover; the next tick re-reads and the
    // loser becomes a follower. Concurrent syncs remain as safe as before.
    async acquire() {
      const current = await holder();
      if (current && current.holder !== id) return false;
      await bridge.atomic(leaseFile, JSON.stringify({holder: id, pid, expires_at: now() + LEASE_MS}));
      return (await holder())?.holder === id;
    },
    async release() {
      const current = await readJSON(leaseFile);
      if (current?.holder === id) await bridge.atomic(leaseFile, JSON.stringify({holder: id, pid, expires_at: 0}));
    },
    // Followers re-render only when the holder published a new local generation.
    async publish({status = null} = {}) {
      const generation = crypto.randomUUID();
      seen = generation;
      await bridge.atomic(markerFile, JSON.stringify({generation, holder: id, status,
        at: new Date(now()).toISOString()}));
    },
    // The new marker, or null when nothing was published since the last look.
    async changed() {
      const value = await readJSON(markerFile);
      if (!value || typeof value.generation !== 'string' || value.generation === seen) return null;
      seen = value.generation;
      return value;
    },
  };
}

// Exponential pause after lock contention so the IDE does not compete with the
// Workspace UI for the same project locks. Success resets it.
function createBackoff({base = 10000, max = 60000, now = Date.now} = {}) {
  let failures = 0, next = 0;
  return {
    due: () => now() >= next,
    failure() { failures++; next = now() + Math.min(max, base * (2 ** (failures - 1))); return next; },
    success() { failures = 0; next = 0; },
    get failures() { return failures; },
  };
}

module.exports = {createLease, createBackoff, alive, LEASE_MS};
