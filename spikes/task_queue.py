# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local task references. Workspace remains the authority for task state."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from uuid import uuid4

from spikes.journal import sync_dir
from spikes.local_api import private_directory
from spikes.metadata import require, uuid
from spikes.projects import Projects


EDITABLE_FLAGS = frozenset({'held'})
MAX_FLAG_AUDIT = 200


class QueueOutcomeUnknown(OSError):
    """Replace happened; reload status before any further mutation."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def assess(task_ids, graph, accepted=()):
    nodes = {n['id']: n for n in graph['nodes']}
    seen = set(); issues = []
    for identifier in task_ids:
        node = nodes.get(identifier)
        if node is None:
            issues.append(identifier + ': položka již není v roadmapě')
        elif node['checked'] and identifier not in accepted:
            issues.append(identifier + ': položka je dokončená')
        else:
            missing = [d for d in node['depends_on'] if not nodes[d]['checked'] and d not in seen]
            if missing:
                issues.append(identifier + ': nesplněný předpoklad chybí před položkou: ' + ', '.join(missing))
        seen.add(identifier)
    following = [n['id'] for n in graph['nodes'] if not n['checked'] and n['id'] not in seen
                 and any(not nodes[d]['checked'] for d in n['depends_on'])
                 and all(nodes[d]['checked'] or d in seen for d in n['depends_on'])]
    return issues, following


def adjacent_moves(task_ids, position, nodes, enabled):
    """Explain adjacent swaps without recomputing the whole valid queue per row."""
    result = {}
    for direction, offset in (('up', -1), ('down', 1)):
        target = position + offset
        reason = ''
        if not enabled:
            reason = 'Fronta není aktuální nebo upravitelná.'
        elif not 0 <= target < len(task_ids):
            reason = 'Položka je na začátku fronty.' if offset < 0 else 'Položka je na konci fronty.'
        else:
            before, after = (task_ids[target], task_ids[position]) if offset < 0 else (task_ids[position], task_ids[target])
            if not nodes[before]['checked'] and before in nodes[after]['depends_on']:
                reason = f'{after} závisí na {before}; předpoklad musí zůstat před položkou.'
        result['can_move_' + direction] = not reason
        result['move_' + direction + '_reason'] = reason
    return result


class TaskQueue:
    def __init__(self, node, *, network=False):
        self.node = Path(node).absolute()
        self.projects = Projects(node, network=network)
        self.root = self.node.parent / ('.' + self.node.name + '.task-queues')

    @contextmanager
    def _lock(self, project_id, actor_id):
        uuid(project_id)
        require(isinstance(actor_id, str) and 0 < len(actor_id) <= 256, 'Queue owner required')
        require(self.root.parent.resolve() == self.root.parent, 'Symlink queue parent')
        try:
            self.root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            sync_dir(self.root.parent)
        private_directory(self.root)
        outside = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--show-toplevel'],
                                 capture_output=True, timeout=5)
        require(outside.returncode == 128, 'Queue storage must be outside Git')
        key = hashlib.sha256(canonical([project_id, actor_id])).hexdigest()
        path = self.root / (key + '.json')
        fd = os.open(self.root / (key + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe queue lock')
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Frontu právě mění jiný požadavek; načtěte ji znovu.')
            yield path
        finally:
            os.close(fd)

    def _read(self, path, project_id, actor_id):
        if not os.path.lexists(path):
            return dict(schema=1, project_id=project_id, owner_id=actor_id, revision=0,
                        project_head=None, task_ids=[], held_task_ids=[], flag_audit=[])
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 1024 * 1024,
                    'Unsafe queue file')
            from spikes.metadata import pairs
            data = json.loads(stream.read(1024 * 1024 + 1), object_pairs_hook=pairs)
        # Queues written before IDE-QUEUE-UX-01 have no flag fields.
        require(isinstance(data, dict) and {
            'schema', 'project_id', 'owner_id', 'revision', 'project_head', 'task_ids'} <= set(data)
            <= {'schema', 'project_id', 'owner_id', 'revision', 'project_head', 'task_ids',
                'held_task_ids', 'flag_audit'}
            and data['schema'] == 1 and data['project_id'] == project_id and data['owner_id'] == actor_id,
            'Queue scope differs')
        require(type(data['revision']) is int and data['revision'] >= 0
                and isinstance(data['task_ids'], list) and len(data['task_ids']) <= 10000
                and all(isinstance(i, str) for i in data['task_ids'])
                and len(data['task_ids']) == len(set(data['task_ids']))
                and isinstance(data['project_head'], str), 'Invalid queue')
        data.setdefault('held_task_ids', []); data.setdefault('flag_audit', [])
        require(isinstance(data['held_task_ids'], list)
                and set(map(str, data['held_task_ids'])) <= set(data['task_ids'])
                and isinstance(data['flag_audit'], list)
                and len(data['flag_audit']) <= MAX_FLAG_AUDIT, 'Invalid queue flags')
        return data

    def _write(self, path, state, checkpoint):
        temporary = self.root / ('.' + str(uuid4()) + '.tmp')
        replaced = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(canonical(state)); stream.flush(); os.fsync(stream.fileno())
            checkpoint('queue-before-replace')
            os.replace(temporary, path); replaced = True
            checkpoint('queue-after-replace')
            sync_dir(self.root)
        except Exception as exc:
            if replaced:
                raise QueueOutcomeUnknown('Výsledek zápisu fronty je neznámý; znovu načtěte stav, neopakujte zápis.') from exc
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def execute(self, request, actor_id, *, checkpoint=lambda stage: None):
        require(isinstance(request, dict) and 'project_id' in request and 'action' in request,
                'Invalid queue request')
        action = request['action']; project_id = request['project_id']
        common = {'project_id', 'action'}
        fields = {'status': set(), 'add': {'task_id', 'revision', 'expected_head'},
                  'remove-preview': {'task_id', 'revision', 'expected_head'},
                  'remove': {'task_id', 'revision', 'expected_head', 'preview_sha256'},
                  'revalidate': {'revision', 'expected_head'},
                  'move': {'task_id', 'target_index', 'revision', 'expected_head'},
                  'set-flag': {'task_id', 'flag', 'value', 'revision', 'expected_head'}}
        require(isinstance(action, str) and action in fields and set(request) == common | fields[action],
                'Invalid queue action or fields')
        # Native read enforces registered-project/index/privacy state before opening local queue files.
        view = self.projects.open(project_id); graph = view['plan']
        require(graph['status'] == 'ready', 'Roadmapa nemá platný graf.')
        require(action == 'status' or not view.get('read_only'), 'Projekt je pouze pro čtení.')
        from spikes.ide_queue import completion_reports, queue_projection
        projection = queue_projection(self.node, project_id, actor_id, view)
        reports = completion_reports(self.node, project_id, actor_id)
        eligible = {i['id'] for i in (projection['items'] + projection['linked_items'] if projection else ())
                    if i['eligible']}

        startable = {i['id'] for i in (projection['items'] + projection['linked_items'] if projection else ()) if i.get('startable')}

        def item_reports(identifier, nodes, state):
            ids = [identifier]
            for current in ids:
                ids += [n['id'] for n in nodes.values() if n['parent_id'] == current]
            # Acceptance is revalidated by the review itself; this only drives the button.
            current = projection and (state['revision'] == projection['manifest']['queue_revision']
                                      and state['task_ids'] == [t['id'] for t in projection['manifest']['tasks']])
            return [dict(report, acceptable=bool(current and report['outcome'] is None
                                                 and report['queue_packet_id'] == projection['packet_id']
                                                 and report['task_id'] in (startable if report['kind'] == 'progress' else eligible)))
                    for i in ids for report in reports.get(i, [])]
        accepted = {i['id'] for i in projection['items'] if i['user_confirmed']} if projection else set()
        workspace = self.projects.workspace(project_id, blocking=False)
        with self._lock(project_id, actor_id) as path, workspace.journal.lock(), workspace.journal.connect() as db:
            require(not workspace._active(db) and not db.execute('SELECT 1 FROM pending').fetchone(),
                    'Projekt má nedokončenou operaci.')
            head = view['commit_id']
            require(workspace.git.head() == head, 'Projekt se změnil; načtěte jej znovu.')
            state = self._read(path, project_id, actor_id)
            issues, following = assess(state['task_ids'], graph, accepted)
            nodes = {n['id']: n for n in graph['nodes']}
            stale = state['project_head'] not in (None, head)
            if projection and state['revision'] == projection['manifest']['queue_revision'] and state['task_ids'] == [t['id'] for t in projection['manifest']['tasks']]:
                stale = False
            if action != 'status':
                require(type(request['revision']) is int and request['revision'] == state['revision'],
                        'Fronta se změnila; načtěte ji znovu.')
                require(request['expected_head'] == head, 'Roadmapa se změnila; načtěte ji znovu.')
                if action in {'add', 'remove-preview', 'remove', 'move', 'set-flag'}:
                    require(isinstance(request['task_id'], str), 'Task ID required')
            should_write = action != 'status'
            if action == 'move':
                require(not stale and not issues, 'Nejprve znovu ověřte frontu vůči roadmapě.')
                identifier, target = request['task_id'], request['target_index']
                require(identifier in state['task_ids'], 'Položka není ve frontě.')
                require(type(target) is int and 0 <= target < len(state['task_ids']),
                        'Cílová pozice není platná.')
                reordered = list(state['task_ids'])
                reordered.remove(identifier)
                reordered.insert(target, identifier)
                move_issues, _ = assess(reordered, graph, accepted)
                require(not move_issues, '; '.join(move_issues))
                should_write = reordered != state['task_ids']
                state['task_ids'] = reordered
            if action == 'set-flag':
                # Only a working-queue choice is editable here.  Reports, acceptance and
                # readiness keep their own lifecycle, so this cannot complete a task.
                require(not stale, 'Nejprve znovu ověřte frontu vůči roadmapě.')
                identifier = request['task_id']
                require(identifier in state['task_ids'], 'Položka není ve frontě.')
                require(request['flag'] in EDITABLE_FLAGS, 'Tento příznak nelze ručně upravit.')
                require(type(request['value']) is bool, 'Hodnota příznaku musí být ano, nebo ne.')
                old = identifier in state['held_task_ids']
                should_write = old != request['value']
                if should_write:
                    state['held_task_ids'] = [i for i in state['task_ids'] if i != identifier
                                              and i in state['held_task_ids']
                                              or i == identifier and request['value']]
                    state['flag_audit'] = (state['flag_audit'] + [dict(
                        task_id=identifier, flag=request['flag'], old=old, new=request['value'],
                        actor_id=actor_id, at=int(time.time()), revision=state['revision'] + 1,
                    )])[-MAX_FLAG_AUDIT:]
            if action == 'add':
                require(not stale and not issues, 'Nejprve znovu ověřte frontu vůči roadmapě.')
                identifier = request['task_id']; node = nodes.get(identifier)
                require(node is not None and not node['checked'] and identifier not in state['task_ids'],
                        'Položka není dostupná, je dokončená nebo je již ve frontě.')
                require(node['ready'] or identifier in following, 'Nesplněný předpoklad není ve frontě.')
                state['task_ids'].append(identifier)
            if action in {'remove-preview', 'remove'}:
                identifier = request['task_id']
                require(identifier in state['task_ids'], 'Položka není ve frontě.')
                removed = {identifier}
                while True:
                    # A completed prerequisite stays satisfied after removal, as in assess().
                    unmet = {i for i in removed if i in nodes and not nodes[i]['checked']}
                    expanded = removed | {i for i in state['task_ids'] if i in nodes
                                           and set(nodes[i]['depends_on']) & unmet}
                    if expanded == removed: break
                    removed = expanded
                preview = dict(project_id=project_id, owner_id=actor_id, expected_head=head,
                               revision=state['revision'], task_id=identifier,
                               removed_ids=[i for i in state['task_ids'] if i in removed])
                digest = hashlib.sha256(canonical(preview)).hexdigest()
                if action == 'remove-preview':
                    return dict(preview, preview_sha256=digest)
                require(request['preview_sha256'] == digest, 'Dopad odebrání se změnil; načtěte nový náhled.')
                state['task_ids'] = [i for i in state['task_ids'] if i not in removed]
                state['held_task_ids'] = [i for i in state['held_task_ids'] if i not in removed]
            if should_write:
                issues, following = assess(state['task_ids'], graph, accepted)
                if action != 'remove': require(not issues, '; '.join(issues))
                state.update(revision=state['revision'] + 1, project_head=head)
                require(workspace.git.head() == head, 'Roadmapa se změnila před zápisem.')
                self._write(path, state, checkpoint); stale = False
            if workspace.git.head() != head:
                if should_write:
                    raise QueueOutcomeUnknown('Roadmapa se během změny fronty změnila; znovu načtěte stav.')
                raise ValueError('Roadmapa se změnila; znovu načtěte stav fronty.')
            return dict(project_id=project_id, revision=state['revision'], expected_head=head,
                        stale=stale, valid=not stale and not issues, issues=issues,
                        task_ids=state['task_ids'], flag_audit=state['flag_audit'][-20:],
                        editable_flags=sorted(EDITABLE_FLAGS), following=following if not stale and not issues else [],
                        items=[dict(id=i, status=nodes[i].get('status', 'planned') if i in nodes else None,
                                    status_mode=nodes[i].get('status_mode') if i in nodes else None,
                                    status_counts=nodes[i].get('status_counts', {}) if i in nodes else {},
                                    title=nodes[i]['title'] if i in nodes else 'Nedostupná položka',
                                    agent_confirmed=bool(projection and any(x['id'] == i and x['agent_confirmed'] for x in projection['items'])),
                                    user_confirmed=i in accepted,
                                    user_requested=bool(projection and any(x['id'] == i and x.get('user_requested') for x in projection['items'])),
                                    held=i in state['held_task_ids'],
                                    reports=item_reports(i, nodes, state),
                                    children=[n['id'] for n in graph['nodes'] if n['parent_id'] == i],
                                    **adjacent_moves(state['task_ids'], position, nodes,
                                                     not stale and not issues and not view.get('read_only')))
                               for position, i in enumerate(state['task_ids'])])
