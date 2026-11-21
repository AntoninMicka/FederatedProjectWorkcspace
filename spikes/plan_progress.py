# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared, side-effect-free candidate for starting a roadmap task."""
from spikes.markdown_documents import document
from spikes.metadata import require, validate_snapshot, validate_transition
from spikes.plan_item_editor import item_span, _fence_after
from spikes.task_graph import RELATION, project_task_graph, dependency_start_blockers


def mark_in_progress(body, task_id):
    start, end = item_span(body, task_id)
    block = body[start:end].splitlines(keepends=True)
    newline = '\r\n' if block[0].endswith('\r\n') else '\n'
    fence, found = None, False
    for index in range(1, len(block)):
        visible = fence is None
        fence = _fence_after(block[index], fence)
        relation = RELATION.match(block[index].rstrip('\r\n')) if visible and fence is None else None
        if relation and relation[2].strip().lower() == 'status':
            ending = newline if block[index].endswith(('\n', '\r')) else ''
            block[index] = relation[1] + '- status: in progress' + ending
            found = True
    if not found:
        terminated = block[0].endswith(('\n', '\r'))
        if not terminated:
            block[0] += newline
        indent = block[0][:len(block[0])-len(block[0].lstrip())]
        block.insert(1, indent + '  - status: in progress' + (newline if terminated else ''))
    return body[:start] + ''.join(block) + body[end:]


def progress_changes(files, project_id, head, task_id):
    entities = validate_snapshot(files)
    graph = project_task_graph(files, entities, project_id, head)
    require(graph['status'] == 'ready', 'Invalid project task graph')
    nodes = {n['id']: n for n in graph['nodes']}
    task = nodes.get(task_id)
    require(task is not None and task['type'] in {None, 'task'}
            and not any(n['parent_id'] == task_id for n in graph['nodes']), 'Zahajte konkrétní úkol.')
    require(not task['checked'] and task.get('status_mode') != 'sum', 'Dokončený úkol nebo SUM nelze zahájit.')
    require(not dependency_start_blockers(task['depends_on'], nodes),
            'Zahájení vyžaduje vyřešené závislosti a nejvýše jednu probíhající.')
    if task['status'] == 'in progress':
        return {}
    doc = document(files, entities, task['source']['artifact_id'])
    body = mark_in_progress(doc['body'], task_id)
    raw = files[doc['path']]
    prefix = raw[:-len(doc['body'].encode())] if doc['body'] else raw
    candidate = dict(files, **{doc['path']: prefix + body.encode()})
    validate_transition(files, candidate)
    require(project_task_graph(candidate, validate_snapshot(candidate), project_id, head)['status'] == 'ready',
            'Start produces invalid task graph')
    return {doc['path']: candidate[doc['path']]}


def completion_changes(files, project_id, head, task_id):
    """Reuse the native human-review formatter without creating an IDE report."""
    graph=project_task_graph(files,validate_snapshot(files),project_id,head)
    require(graph['status']=='ready','Invalid project task graph')
    nodes={n['id']:n for n in graph['nodes']};task=nodes.get(task_id)
    require(task and task['type'] in {None,'task'} and not any(n['parent_id']==task_id for n in nodes.values()),'Dokončete konkrétní úkol.')
    require(not task['checked'],'Úkol již byl dokončen.')
    require(task.get('status_mode')!='sum','Souhrnný stav dokončete prostřednictvím jeho dílčích úkolů.')
    require(all(nodes[d]['checked'] for d in task['depends_on']),'Dokončení vyžaduje potvrzené dokončení všech závislostí.')
    require(all(point['checked'] for point in task['checklist']),'Nejprve potvrďte zbývající body checklistu v zadání úkolu.')
    from spikes.ide_bridge_panel import _changes
    changes=_changes(files,project_id,head,dict(kind='completed',task_id=task_id))
    validate_transition(files,dict(files,**changes))
    return changes
