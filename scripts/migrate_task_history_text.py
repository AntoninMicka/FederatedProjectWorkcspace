# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Audit, then transfer finished local task records into their owning task text."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spikes.metadata import require, validate_snapshot
from spikes.task_activity_text import ActivityText, TYPES
from spikes.task_graph import project_task_graph
from spikes.task_work import TaskWork, canonical


def definitions(nodes):
    return [{key: value for key, value in node.items() if key != 'line'} for node in nodes]


def audit(work):
    store = ActivityText(work)
    with work._db() as db:
        source = db.execute('SELECT * FROM operations WHERE user_id=?', (work.user_id,)).fetchall() if db else []
    projects = {}; entries = []
    for row in source:
        op = json.loads(row['doc'])
        if op.get('record_type') not in TYPES: continue
        envelope = store.envelope(row); pid = envelope['project_id']
        if pid not in projects:
            git = work.projects.repository(pid); head = git.head(); files = git.snapshot(head)
            require(not git.run('status', '--porcelain').stdout, 'Project has uncommitted changes')
            graph = project_task_graph(files, validate_snapshot(files), pid, head)
            require(graph['status'] == 'ready', 'Invalid task graph')
            projects[pid] = dict(head=head, nodes=graph['nodes'])
        require(any(t['id'] == envelope['task_id'] for t in projects[pid]['nodes']), 'Original task is missing')
        pending = ((op['outcome'] == 'unknown' and 'response_code' not in op) or bool(op.get('offer', {}).get('pending_operation_id'))
            if op['record_type'] == 'task-activity' else op['state'] != 'completed')
        entries.append(dict(id=row['id'], project_id=pid, task_id=envelope['task_id'],
            record_type=op['record_type'], sha256=hashlib.sha256(canonical(dict(row)).encode()).hexdigest(),
            already_in_text=store.read(pid).get(row['id']) == dict(row), pending=pending))
    return dict(schema='fpw-task-history-migration-v1', user_id=work.user_id, projects=projects, entries=entries)


def apply(work, plan):
    current = audit(work)
    require(current == plan, 'Migration inputs changed; create and review a fresh audit')
    source = {}
    with work._db() as db:
        for entry in plan['entries']:
            row = db.execute('SELECT * FROM operations WHERE id=? AND user_id=?', (entry['id'], work.user_id)).fetchone()
            source[entry['id']] = dict(row)
    migrated = ActivityText(work).drain({e['id'] for e in plan['entries'] if not e['pending']})
    destinations = {pid: ActivityText(work).read(pid) for pid in plan['projects']}
    for identifier in migrated:
        entry = next(e for e in plan['entries'] if e['id'] == identifier)
        require(destinations[entry['project_id']].get(identifier) == source[identifier], 'Migrated task text differs from SQLite source')
    final_heads = {}
    for pid, original in plan['projects'].items():
        git = work.projects.repository(pid); head = git.head(); files = git.snapshot(head)
        graph = project_task_graph(files, validate_snapshot(files), pid, head)
        require(graph['status'] == 'ready' and definitions(graph['nodes']) == definitions(original['nodes']), 'Task definitions or completion states changed during migration')
        require(not git.run('status', '--porcelain').stdout, 'Project is dirty after migration')
        ws = work.projects.workspace(pid, for_snapshot=True)
        with ws.journal.lock(shared=True), ws.journal.connect() as db:
            require(ws._active(db) is None and not db.execute('SELECT 1 FROM pending').fetchone(), 'Project recovery is unfinished')
        final_heads[pid] = head
    return dict(migrated=migrated, retained_pending=[e['id'] for e in plan['entries'] if e['pending']], heads=final_heads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True, type=Path)
    parser.add_argument('--user-id')
    parser.add_argument('--audit', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    work = TaskWork(args.node, args.user_id)
    if args.apply:
        result = apply(work, json.loads(args.audit.read_text()))
    else:
        plan = audit(work)
        args.audit.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2)+'\n')
        result = dict(records=len(plan['entries']), missing=sum(not e['already_in_text'] for e in plan['entries']),
            pending=sum(e['pending'] for e in plan['entries']), projects={pid: p['head'] for pid, p in plan['projects'].items()})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
