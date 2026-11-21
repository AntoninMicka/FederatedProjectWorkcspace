# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One owner queue across projects, retaining project-scoped IDE projections."""
import hashlib
import sqlite3
import subprocess

from spikes.metadata import require, uuid
from spikes.task_queue import TaskQueue, queue_faults, QueueOutcomeUnknown, canonical
from spikes.workspace import PendingOperation


class OwnerTaskQueue(TaskQueue):
    def status(self, actor_id, *, can_read=lambda pid: True, can_write=lambda pid: True):
        # Read only scopes the authenticated actor may see, before any project read.
        with self._lock(None, actor_id, shared=True) as path:
            bundle = self._bundle(path, actor_id)
            revision = bundle['revision']
            order = list(bundle['order'])
        scopes = {}
        issues = []
        registered = {b['project_id'] for b in self.projects._bindings()}
        for pid in dict.fromkeys(ref[0] for ref in order):
            if pid not in registered or not can_read(pid):
                continue
            try:
                view = self.execute(dict(project_id=pid, action='status'), actor_id)
                project = self.projects.plan_view(pid)
                require(project['commit_id'] == view['expected_head'], 'Project changed during queue read')
                view['project_title'] = project['title']
                view['read_only'] = bool(project.get('read_only') or not can_write(pid))
                scopes[pid] = view
                issues += [view['project_title'] + ': ' + issue for issue in view['issues']]
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, PendingOperation):
                # No unverified titles/definitions, and no deletion of retained references.
                scopes[pid] = dict(project_id=pid, project_title=pid, read_only=True,
                                   items=[], unavailable=True)
                issues.append(pid + ': Projekt není dostupný; obnovte frontu.')
        with self._lock(None, actor_id, shared=True) as path:
            require(self._bundle(path, actor_id)['revision'] == revision,
                    'Fronta se během čtení změnila; obnovte ji.')
        items = []
        by_project = {pid: {i['id']: i for i in scope['items']} for pid, scope in scopes.items()}
        for pid, task in order:
            scope = scopes.get(pid)
            if scope is None or scope.get('unavailable'):
                continue
            item = by_project[pid].get(task)
            items.append(dict(item or dict(id=task, title='Nedostupná položka', unavailable=True),
                              project_id=pid, project_title=scope['project_title'],
                              read_only=scope['read_only'], expected_head=scope.get('expected_head'),
                              queue_revision=scope.get('revision')))
        view_revision = hashlib.sha256(canonical([revision, [
            [i['project_id'], i['id'], i['expected_head'], i['read_only']] for i in items]])).hexdigest()
        return dict(revision=revision, view_revision=view_revision, items=items, issues=issues,
                    projects=list(scopes.values()))

    def move(self, request, actor_id, *, can_read=lambda pid: True,
             can_write=lambda pid: True, checkpoint=lambda stage: None):
        require(isinstance(request, dict) and set(request) == {
            'action', 'project_id', 'task_id', 'target_index', 'revision', 'expected_head', 'view_revision'},
            'Invalid owner queue move')
        pid = request['project_id']; uuid(pid)
        require(request['action'] == 'move' and can_read(pid) and can_write(pid),
                'Projekt nelze upravovat.')
        require(type(request['revision']) is int and request['revision'] >= 0
                and isinstance(request['task_id'], str), 'Invalid queue revision or task')
        current = self.status(actor_id, can_read=can_read, can_write=can_write)
        require(request['revision'] == current['revision'] and request['view_revision'] == current['view_revision'],
                'Fronta se změnila nebo má jiný rozsah; obnovte ji.')
        view = self.projects.plan_view(pid)
        require(not view.get('read_only') and view['plan']['status'] == 'ready',
                'Projekt nemá upravitelný platný plán.')
        workspace = self.projects.workspace(pid, blocking=False)
        with self._lock(None, actor_id) as path, workspace.journal.lock(), workspace.journal.connect() as db:
            require(not workspace._active(db) and not db.execute('SELECT 1 FROM pending').fetchone(),
                    'Projekt má nedokončenou operaci.')
            head = view['commit_id']
            require(request['expected_head'] == head and workspace.git.head() == head,
                    'Roadmapa se změnila; obnovte frontu.')
            bundle = self._bundle(path, actor_id)
            require(request['revision'] == bundle['revision'], 'Fronta se změnila; obnovte ji.')
            # Hidden project entries keep their positions and are never returned.
            visible = [[i['project_id'], i['id']] for i in current['items']]
            ref = [pid, request['task_id']]
            target = request['target_index']
            require(ref in visible and type(target) is int and 0 <= target < len(visible),
                    'Položka nebo cílová pozice není platná.')
            reordered = list(visible); reordered.remove(ref); reordered.insert(target, ref)
            if reordered != visible:
                state = bundle['projects'][pid]
                task_ids = [task for project, task in reordered if project == pid]
                graph = view['plan']
                require(queue_faults(task_ids, graph, ()) <= queue_faults(state['task_ids'], graph, ()),
                        'Přesun by porušil pořadí předpokladů úkolu.')
                iterator = iter(reordered)
                visible_set = {tuple(ref) for ref in visible}
                bundle['order'] = [next(iterator) if tuple(ref) in visible_set else ref
                                   for ref in bundle['order']]
                if task_ids != state['task_ids']:
                    state.update(task_ids=task_ids, revision=state['revision'] + 1, project_head=head)
                bundle['revision'] += 1
                require(workspace.git.head() == head, 'Roadmapa se změnila před zápisem.')
                self._atomic_write(path, bundle, checkpoint)
                if workspace.git.head() != head:
                    raise QueueOutcomeUnknown('Roadmapa se během změny změnila; obnovte frontu.')
        return self.status(actor_id, can_read=can_read, can_write=can_write)
