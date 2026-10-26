# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only task graph projected from a project's committed Markdown TODOs."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
import re

from spikes.markdown_documents import document, main_todo_id
from spikes.metadata import ValidationError, require

SCHEMA = 'fpw-project-task-graph-v1'
TASK_ID = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+')
TASK = re.compile(r'^(\s*)[-+*]\s+\[([ xX])\]\s+\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]\s+(.+?)\s*$')
RELATION = re.compile(r'^(\s*)[-+*]\s+([^:]{1,32}):\s*(.+?)\s*$')
REFERENCE = re.compile(r'^\s*[-+*]\s+\[[ xX]\]\s+\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\](?:\s+.*)?$')
ALIASES = {
    'depends_on': 'depends_on', 'závisí na': 'depends_on', 'blocked_by': 'depends_on',
    'blokován': 'depends_on', 'blocks': 'blocks', 'blokuje': 'blocks',
    'duplicates': 'duplicates', 'duplikuje': 'duplicates', 'duplikován': 'duplicates',
    'supersedes': 'supersedes', 'nahrazuje': 'supersedes',
    'relates_to': 'relates_to', 'souvisí s': 'relates_to',
    'parent_of': 'parent_of', 'rodič': 'parent_of',
}
MAX_TASKS, MAX_RELATIONS, MAX_SUBGRAPHS = 1000, 4000, 100


def _visible_lines(body):
    fence = None
    for raw in body.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', raw)
        if marker:
            token, tail = marker.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                fence = None
            continue
        if fence is None:
            yield raw


def _targets(value):
    values = [item.strip() for item in value.split(',')]
    require(values and all(TASK_ID.fullmatch(item) for item in values),
            'Vztah musí obsahovat platná ID oddělená čárkou.')
    require(len(values) == len(set(values)), 'Vztah obsahuje duplicitní cíl.')
    return values


def parse_main_todo(body):
    tasks, pending, relation_count = {}, None, 0
    for line in _visible_lines(body):
        checkbox = re.match(r'^\s*[-+*]\s+\[[ xX]\]\s+', line)
        match = TASK.match(line)
        if checkbox and not match:
            raise ValidationError('Každý úkol v hlavním TODO musí začínat stabilním ID, např. [TASK-01].')
        if match:
            indent, checked, task_id, title = match.groups()
            require(task_id not in tasks, f'Duplicitní ID úkolu: {task_id}')
            require(0 < len(title) <= 500 and '\0' not in title, 'Neplatný název úkolu.')
            require(len(tasks) < MAX_TASKS, 'Hlavní TODO přesahuje limit 1000 úkolů.')
            pending = {'id': task_id, 'title': title, 'checked': checked.lower() == 'x',
                       'indent': len(indent.expandtabs(4)), 'relations': defaultdict(list)}
            tasks[task_id] = pending
            continue
        relation = RELATION.match(line)
        if relation and pending and len(relation.group(1).expandtabs(4)) > pending['indent']:
            key = ALIASES.get(relation.group(2).strip().lower())
            if key:
                values = _targets(relation.group(3)); relation_count += len(values)
                require(relation_count <= MAX_RELATIONS, 'TODO přesahuje limit 4000 vztahů.')
                pending['relations'][key].extend(values)
    require(tasks, 'Hlavní TODO neobsahuje žádný strukturovaný úkol.')
    return tasks


def _topology(tasks):
    unknown = sorted({target for item in tasks.values() for values in item['relations'].values()
                      for target in values if target not in tasks})
    require(not unknown, 'Neznámé ID ve vztahu: ' + ', '.join(unknown))
    derived = {task_id: defaultdict(set) for task_id in tasks}; seen = set()
    for source, item in tasks.items():
        for kind, targets in item['relations'].items():
            for target in targets:
                require(source != target, f'Úkol {source} nesmí odkazovat sám na sebe.')
                if kind == 'depends_on': key, inverse = ('dependency', target, source), 'blocks'
                elif kind == 'blocks': key, inverse = ('dependency', source, target), 'depends_on'
                elif kind in {'duplicates', 'relates_to'}: key, inverse = (kind, *sorted((source, target))), kind
                elif kind == 'supersedes': key, inverse = (kind, source, target), 'superseded_by'
                else: key, inverse = (kind, source, target), 'child_of'
                require(key not in seen, f'Vztah {source} → {target} je deklarován vícekrát.')
                seen.add(key); derived[source][kind].add(target); derived[target][inverse].add(source)
    dependencies = {task_id: set(derived[task_id]['depends_on']) for task_id in tasks}
    for task_id, parents in dependencies.items():
        require(task_id not in parents, f'Úkol {task_id} nesmí záviset sám na sobě.')
    indegree = {task_id: len(parents) for task_id, parents in dependencies.items()}
    children = {task_id: set() for task_id in tasks}
    for child, parents in dependencies.items():
        for parent in parents: children[parent].add(child)
    ready, order = sorted(task_id for task_id, degree in indegree.items() if not degree), []
    while ready:
        task_id = ready.pop(0); order.append(task_id)
        for child in sorted(children[task_id]):
            indegree[child] -= 1
            if not indegree[child]: ready.append(child); ready.sort()
    require(len(order) == len(tasks), 'Dependency vztahy obsahují cyklus.')
    paths, depths = {}, {}
    for task_id in order:
        parents = dependencies[task_id]
        if not parents: paths[task_id], depths[task_id] = [task_id], 0
        else:
            parent = min(parents, key=lambda value: (-len(paths[value]), paths[value]))
            paths[task_id] = paths[parent] + [task_id]
            depths[task_id] = max(depths[value] for value in parents) + 1
    critical = min(paths.values(), key=lambda value: (-len(value), value))
    return order, dependencies, derived, depths, critical


def _subgraphs(files, entities, canonical):
    result = []
    for artifact_id, metadata in sorted(entities.items()):
        if metadata.get('kind') != 'document' or 'plan-subgraph' not in metadata.get('tags', []):
            continue
        require(len(result) < MAX_SUBGRAPHS, 'Projekt přesahuje limit 100 podgrafů.')
        doc = document(files, entities, artifact_id); selected = []
        for line in _visible_lines(doc['body']):
            match = REFERENCE.match(line)
            if match: selected.append(match.group(1))
        require(selected and len(selected) == len(set(selected)),
                f'Podgraf {metadata["title"]} musí obsahovat jedinečná ID.')
        unknown = sorted(set(selected) - set(canonical))
        require(not unknown, f'Podgraf {metadata["title"]} odkazuje na neznámá ID: ' + ', '.join(unknown))
        result.append({'id': artifact_id, 'title': metadata['title'], 'task_ids': selected})
    return result


def project_task_graph(files, entities, project_id, commit_id):
    todo_id = main_todo_id(project_id)
    if todo_id not in entities:
        return {'schema': SCHEMA, 'status': 'missing', 'revision': commit_id, 'nodes': [],
                'critical_path': [], 'ready': [], 'blocked': [], 'subgraphs': []}
    try:
        tasks = parse_main_todo(document(files, entities, todo_id)['body'])
        order, dependencies, derived, depths, critical = _topology(tasks)
        subgraphs = _subgraphs(files, entities, tasks)
        nodes = []
        for task_id in order:
            task = tasks[task_id]; parents = sorted(dependencies[task_id])
            relations = {key: sorted(values) for key, values in derived[task_id].items()
                         if key != 'depends_on' and values}
            nodes.append({'id': task_id, 'title': task['title'], 'checked': task['checked'],
                          'depends_on': parents, 'relations': relations, 'depth': depths[task_id],
                          'critical': task_id in critical,
                          'ready': not task['checked'] and all(tasks[parent]['checked'] for parent in parents),
                          'blocked': not task['checked'] and any(not tasks[parent]['checked'] for parent in parents)})
        digest = sha256(json.dumps({'commit': commit_id, 'nodes': nodes, 'subgraphs': subgraphs},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        value = {'schema': SCHEMA, 'status': 'ready', 'revision': digest, 'nodes': nodes,
                 'critical_path': critical, 'ready': [n['id'] for n in nodes if n['ready']],
                 'blocked': [n['id'] for n in nodes if n['blocked']], 'subgraphs': subgraphs}
        value['svg'] = task_graph_svg(value)
        return value
    except (ValidationError, UnicodeError, ValueError) as exc:
        return {'schema': SCHEMA, 'status': 'invalid', 'revision': commit_id, 'error': str(exc),
                'nodes': [], 'critical_path': [], 'ready': [], 'blocked': [], 'subgraphs': []}


def task_graph_svg(value, selected=None):
    require(value.get('status') == 'ready', 'Plán není dostupný pro export.')
    ids = set(selected or [item['id'] for item in value['nodes']])
    nodes = [item for item in value['nodes'] if item['id'] in ids]
    positions, slots = {}, defaultdict(int)
    for item in nodes:
        slot = slots[item['depth']]; slots[item['depth']] += 1
        positions[item['id']] = (30 + item['depth'] * 260, 35 + slot * 78)
    width = 280 + max((item['depth'] for item in nodes), default=0) * 260
    height = 90 + max(slots.values(), default=1) * 78
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
             '<style>text{font-family:system-ui}.e{stroke:#91a5b1;fill:none}.n{fill:#fff;stroke:#557384;stroke-width:2}.r{stroke:#176b60;stroke-dasharray:6 3}.b{fill:#f8dddd}.c{stroke-width:4}</style>']
    for item in nodes:
        x2, y2 = positions[item['id']]
        for parent in item['depends_on']:
            if parent in positions:
                x1, y1 = positions[parent]; parts.append(f'<path class="e" d="M{x1+220} {y1+25} C{x1+240} {y1+25} {x2-20} {y2+25} {x2} {y2+25}"/>')
    for item in nodes:
        x, y = positions[item['id']]; classes = ['n']
        if item['ready']: classes.append('r')
        if item['blocked']: classes.append('b')
        if item['critical']: classes.append('c')
        parts.extend([f'<g><title>{escape(item["title"])}</title><rect class="{" ".join(classes)}" x="{x}" y="{y}" width="220" height="52" rx="8"/>',
                      f'<text x="{x+9}" y="{y+21}" font-weight="700">{escape(item["id"])}</text>',
                      f'<text x="{x+9}" y="{y+40}" font-size="11">{escape(item["title"][:32])}</text></g>'])
    parts.append(f'<metadata>{SCHEMA} {escape(value["revision"])}</metadata></svg>')
    return ''.join(parts)
