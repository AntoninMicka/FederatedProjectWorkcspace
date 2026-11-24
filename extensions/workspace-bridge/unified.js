// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
'use strict';
// One merged queue across projects (ADR 0087/0090). The owner order from
// Workspace only arranges rows; every row's state and every action still come
// from the pinned packet of its own project. Nothing here is a second plan.
const path = require('node:path');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function validateOwner(value, connectionId) {
  // Another (previous) connection's order is never applied to this one.
  if (!value || typeof value !== 'object' || value.connection_id !== connectionId) return null;
  if (value.unsupported === true) return {unsupported: true};
  if (!Number.isInteger(value.revision) || value.revision < 0
      || !Array.isArray(value.order) || value.order.length > 10000 || !value.sessions || typeof value.sessions !== 'object')
    throw Error('Neplatné společné pořadí fronty.');
  for (const ref of value.order)
    if (!Array.isArray(ref) || ref.length !== 2 || !UUID.test(ref[0]) || typeof ref[1] !== 'string')
      throw Error('Neplatná položka společného pořadí.');
  return value;
}

// rows: [{project, entry, taskId, index, missing}] in owner order. Items the
// owner order does not list keep their project order at the end; an owner
// reference without a current packet entry stays visible as read-only.
function merge(projects, owner) {
  const byProject = new Map(projects.map(project => [project.snapshot.project_id, project]));
  const rows = [], placed = new Set();
  const ordered = Boolean(owner && !owner.unsupported);
  if (ordered) {
    for (const [projectId, taskId] of owner.order) {
      const project = byProject.get(projectId);
      if (!project) continue; // not assigned in this IDE: never propagated
      const key = projectId + '\n' + taskId;
      if (placed.has(key)) continue;
      placed.add(key);
      const entry = (project.queue?.items || []).find(item => item.id === taskId) || null;
      rows.push({project, entry, taskId, missing: !entry});
    }
  }
  for (const project of projects)
    for (const entry of project.queue?.items || []) {
      const key = project.snapshot.project_id + '\n' + entry.id;
      if (placed.has(key)) continue;
      placed.add(key);
      rows.push({project, entry, taskId: entry.id, missing: false, unordered: ordered});
    }
  rows.forEach((row, index) => { row.index = index; });
  return {rows, ordered, projects: new Set(rows.map(row => row.project.snapshot.project_id)).size};
}

// Why an owner-ordered item has no entry in its project's pinned packet. Only
// a missing packet entry with a current packet can be fixed by a new handoff;
// without document export Workspace never publishes a packet for the project.
function missingReason(project) {
  if (project.queue) return 'Není v připnutém balíčku projektu; synchronizujte nebo frontu ve Workspace předejte znovu.';
  if (project.panel && project.panel.export_documents === false)
    return 'Projekt nemá ve Workspace zapnutý export podkladů, proto nemá balíček fronty; zapněte jej v nastavení projektu.';
  return 'Projekt zatím nemá ve Workspace předaný balíček fronty; synchronizujte nebo frontu ve Workspace předejte.';
}

// The project of this window: explicit choice first, then the open folder or
// .code-workspace file. 'all' shows the merged list without a project focus.
function activeProject(projects, choice, {folders = [], workspaceFile = null} = {}) {
  if (choice === 'all') return null;
  if (choice && projects.some(project => project.snapshot.project_id === choice)) return choice;
  const inside = (root, folder) => folder === root || folder.startsWith(root.endsWith(path.sep) ? root : root + path.sep);
  const match = projects.find(project => (workspaceFile && project.editor_workspace === workspaceFile)
    || folders.some(folder => project.repository && inside(project.repository, folder)
      || project.editor_workspace && folder === project.editor_workspace));
  return match ? match.snapshot.project_id : null;
}

module.exports = {validateOwner, merge, missingReason, activeProject};
