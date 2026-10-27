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

SCHEMA = 'fpw-project-task-graph-v2'
TASK_ID = re.compile(r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+')
TASK = re.compile(r'^(\s*)[-+*]\s+\[([ xX])\]\s+\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]\s+(.+?)\s*$')
RELATION = re.compile(r'^(\s*)[-+*]\s+([^:]{1,32}):\s*(.+?)\s*$')
DESCRIPTION = re.compile(r'^(\s*)[-+*]\s+(.+?)\s*$')
REFERENCE = re.compile(r'^\s*[-+*]\s+\[[ xX]\]\s+\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\](?:\s+.*)?$')
PROFILE = re.compile(r'^\s*<!--\s*fpw-plan-profile:\s*([^\s]+)\s*-->\s*$')
PLAN_DOCUMENT = re.compile(r'^\s*<!--\s*fpw-plan-document:\s*definitions/v1\s*-->\s*$')
DOCUMENT_LINK = re.compile(r'^\[([^\]]+)\]\((artifacts/([0-9a-f-]{36})/[^)]+\.md)\)$')
ALIASES = {
    'depends_on': 'depends_on', 'závisí na': 'depends_on', 'blocked_by': 'depends_on',
    'blokován': 'depends_on', 'blocks': 'blocks', 'blokuje': 'blocks',
    'duplicates': 'duplicates', 'duplikuje': 'duplicates', 'duplikován': 'duplicates',
    'supersedes': 'supersedes', 'nahrazuje': 'supersedes',
    'relates_to': 'relates_to', 'souvisí s': 'relates_to',
    'parent_of': 'parent_of', 'rodič': 'parent_of',
}
MAX_TASKS, MAX_RELATIONS, MAX_SUBGRAPHS = 1000, 4000, 100
MAX_DESCRIPTION_BYTES = 8192
SOFTWARE_PROFILE = 'software-development/v1'
CHILD_TYPES = {'milestone': {'batch'}, 'batch': {'task'}, 'task': set()}


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


def _document_source(files, entities, artifact_id):
    doc = document(files, entities, artifact_id)
    return doc, {'artifact_id': artifact_id, 'path': doc['path']}


def _targets(value):
    values = [item.strip() for item in value.split(',')]
    require(values and all(TASK_ID.fullmatch(item) for item in values),
            'Vztah musí obsahovat platná ID oddělená čárkou.')
    require(len(values) == len(set(values)), 'Vztah obsahuje duplicitní cíl.')
    return values


def parse_main_todo(body, *, source=None, inherited_parent=None, require_profile=False):
    tasks, pending, relation_count = {}, None, 0
    profile = None
    ancestors = []
    visible = list(_visible_lines(body))
    for line_number, line in enumerate(visible, 1):
        profile_match = PROFILE.match(line)
        if profile_match:
            require(profile is None, 'Plán smí deklarovat profil právě jednou.')
            profile = profile_match.group(1)
            continue
        checkbox = re.match(r'^\s*[-+*]\s+\[[ xX]\]\s+', line)
        match = TASK.match(line)
        if checkbox and not match:
            raise ValidationError('Každý úkol v hlavním TODO musí začínat stabilním ID, např. [TASK-01].')
        if match:
            indent, checked, task_id, title = match.groups()
            require(task_id not in tasks, f'Duplicitní ID úkolu: {task_id}')
            require(0 < len(title) <= 500 and '\0' not in title, 'Neplatný název úkolu.')
            require(len(tasks) < MAX_TASKS, 'Hlavní TODO přesahuje limit 1000 úkolů.')
            indent_value = len(indent.expandtabs(4))
            while ancestors and ancestors[-1][0] >= indent_value:
                ancestors.pop()
            parent_id = ancestors[-1][1] if ancestors else inherited_parent
            link = DOCUMENT_LINK.fullmatch(title)
            pending = {'id': task_id, 'title': title, 'checked': checked.lower() == 'x',
                       'indent': indent_value, 'relations': defaultdict(list),
                       'description_lines': [],
                       'type': None, 'parent_id': parent_id,
                       'document_link': link.group(2) if link else None,
                       'source': source, 'line': line_number}
            if link:
                pending['title'] = link.group(1)
            tasks[task_id] = pending
            ancestors.append((indent_value, task_id))
            continue
        relation = RELATION.match(line)
        if relation and pending and len(relation.group(1).expandtabs(4)) > pending['indent']:
            key = ALIASES.get(relation.group(2).strip().lower())
            if key:
                values = _targets(relation.group(3)); relation_count += len(values)
                require(relation_count <= MAX_RELATIONS, 'TODO přesahuje limit 4000 vztahů.')
                pending['relations'][key].extend(values)
                continue
            elif relation.group(2).strip().lower() in {'type', 'typ'}:
                value = relation.group(3).strip().lower()
                require(value in CHILD_TYPES, f'Neznámý typ uzlu: {value}')
                require(pending['type'] is None, f'Uzel {pending["id"]} deklaruje typ vícekrát.')
                pending['type'] = value
                continue
        description = DESCRIPTION.match(line)
        if (description and pending
                and len(description.group(1).expandtabs(4)) > pending['indent']):
            text = description.group(2).strip()
            require(text and '\0' not in text, 'Popis uzlu nesmí být prázdný.')
            pending['description_lines'].append(text)
            require(len('\n'.join(pending['description_lines']).encode('utf-8'))
                    <= MAX_DESCRIPTION_BYTES,
                    f'Popis uzlu {pending["id"]} přesahuje limit 8 KiB.')
    require(tasks, 'Hlavní TODO neobsahuje žádný strukturovaný úkol.')
    if require_profile:
        require(profile is None, 'Externí soubor nesmí měnit profil plánu.')
    return tasks, profile


def _profiled_tasks(files, entities, project_id):
    todo_id = main_todo_id(project_id)
    root, source = _document_source(files, entities, todo_id)
    tasks, profile = parse_main_todo(root['body'], source=source)
    if profile is None:
        return tasks, None
    require(profile == SOFTWARE_PROFILE, f'Neznámý profil plánu: {profile}')
    paths = {}
    for artifact_id, metadata in entities.items():
        if metadata.get('kind') != 'document' or 'plan-subgraph' in metadata.get('tags', []):
            continue
        try:
            candidate, candidate_source = _document_source(files, entities, artifact_id)
        except (ValidationError, UnicodeError):
            continue
        paths[candidate_source['path']] = (candidate, candidate_source)
    linked = []
    for task in list(tasks.values()):
        if task['document_link']:
            require(task['type'] == 'batch', 'Odkaz na soubor může nést pouze batch.')
            linked.append(task)
    for batch in linked:
        inline = [item['id'] for item in tasks.values() if item['parent_id'] == batch['id']]
        require(not inline, f'Batch {batch["id"]} nesmí současně obsahovat pododrážky a odkaz na soubor.')
        require(batch['document_link'] in paths,
                f'Batch {batch["id"]} odkazuje na neznámý soubor: {batch["document_link"]}')
        external, external_source = paths[batch['document_link']]
        require(any(PLAN_DOCUMENT.match(line) for line in external['body'].splitlines()),
                f'Externí soubor batch {batch["id"]} nemá značku fpw-plan-document.')
        children, child_profile = parse_main_todo(
            external['body'], source=external_source, inherited_parent=batch['id'],
            require_profile=True)
        require(child_profile is None, 'Externí soubor nesmí deklarovat profil.')
        require(all(item['parent_id'] == batch['id'] for item in children.values()),
                f'Externí soubor batch {batch["id"]} smí obsahovat pouze kořenové task odrážky.')
        require(not any(item['document_link'] for item in children.values()),
                f'Externí soubor batch {batch["id"]} nesmí obsahovat další souborový odkaz.')
        duplicates = sorted(set(tasks) & set(children))
        require(not duplicates, 'Duplicitní ID úkolu v bundle: ' + ', '.join(duplicates))
        tasks.update(children)
        require(len(tasks) <= MAX_TASKS, 'Plánovací bundle přesahuje limit 1000 úkolů.')
        relation_count = sum(len(targets) for item in tasks.values()
                             for targets in item['relations'].values())
        require(relation_count <= MAX_RELATIONS,
                'Plánovací bundle přesahuje limit 4000 vztahů.')
    _validate_hierarchy(tasks)
    return tasks, profile


def _validate_hierarchy(tasks):
    for task in tasks.values():
        require(task['type'] in CHILD_TYPES, f'Uzel {task["id"]} nemá platný type.')
        parent_id = task['parent_id']
        if parent_id is None:
            require(task['type'] == 'milestone',
                    f'Kořenový uzel {task["id"]} musí být milestone.')
            continue
        require(parent_id in tasks, f'Uzel {task["id"]} má neznámého rodiče {parent_id}.')
        parent = tasks[parent_id]
        require(task['type'] in CHILD_TYPES[parent['type']],
                f'Hierarchie {parent["type"]} → {task["type"]} není v profilu povolená.')
    for parent in tasks.values():
        for child_id in parent['relations'].get('parent_of', []):
            require(child_id in tasks, f'Uzel {parent["id"]} má neznámé dítě {child_id}.')
            require(tasks[child_id]['parent_id'] == parent['id'],
                    f'Deklarovaný parent_of {parent["id"]} → {child_id} neodpovídá souborové hierarchii.')
    for task in tasks.values():
        seen, current = set(), task
        while current['parent_id'] is not None:
            require(current['id'] not in seen, 'Hierarchie plánu obsahuje cyklus.')
            seen.add(current['id']); current = tasks[current['parent_id']]


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
        tasks, profile = _profiled_tasks(files, entities, project_id)
        order, dependencies, derived, depths, critical = _topology(tasks)
        subgraphs = _subgraphs(files, entities, tasks)
        nodes = []
        for task_id in order:
            task = tasks[task_id]; parents = sorted(dependencies[task_id])
            relations = {key: sorted(values) for key, values in derived[task_id].items()
                         if key != 'depends_on' and values}
            nodes.append({'id': task_id, 'title': task['title'],
                          'description': '\n'.join(task['description_lines']),
                          'checked': task['checked'],
                          'depends_on': parents, 'relations': relations, 'depth': depths[task_id],
                          'dependency_depth': depths[task_id],
                          'type': task['type'], 'parent_id': task['parent_id'],
                          'hierarchy_depth': _hierarchy_depth(tasks, task_id),
                          'source': task['source'], 'line': task['line'],
                          'critical': task_id in critical,
                          'ready': not task['checked'] and all(tasks[parent]['checked'] for parent in parents),
                          'blocked': not task['checked'] and any(not tasks[parent]['checked'] for parent in parents)})
        if profile:
            for node in nodes:
                node['depth'] = node['hierarchy_depth']
        digest = sha256(json.dumps({'commit': commit_id, 'nodes': nodes, 'subgraphs': subgraphs},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        value = {'schema': SCHEMA, 'status': 'ready', 'revision': digest, 'profile': profile,
                 'nodes': nodes,
                 'critical_path': critical, 'ready': [n['id'] for n in nodes if n['ready']],
                 'blocked': [n['id'] for n in nodes if n['blocked']], 'subgraphs': subgraphs}
        value['svg'] = task_graph_svg(value)
        return value
    except (ValidationError, UnicodeError, ValueError) as exc:
        return {'schema': SCHEMA, 'status': 'invalid', 'revision': commit_id, 'error': str(exc),
                'nodes': [], 'critical_path': [], 'ready': [], 'blocked': [], 'subgraphs': []}


def _hierarchy_depth(tasks, task_id):
    depth, current = 0, tasks[task_id]
    while current['parent_id'] is not None:
        depth += 1; current = tasks[current['parent_id']]
    return depth


def task_graph_svg(value, selected=None):
    require(value.get('status') == 'ready', 'Plán není dostupný pro export.')
    if value.get('profile') == SOFTWARE_PROFILE and selected is None:
        return _profiled_task_graph_svg(value)
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
        parent = item.get('parent_id')
        if parent in positions:
            x1, y1 = positions[parent]
            parts.append(f'<path class="e" d="M{x1+220} {y1+25} L{x2} {y2+25}"/>')
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


def _profiled_task_graph_svg(value):
    milestones = sorted((item for item in value['nodes'] if item['type'] == 'milestone'),
                        key=lambda item: ((item['source'] or {}).get('path', ''), item['line']))
    batches = [item for item in value['nodes'] if item['type'] == 'batch']
    label_width, column_width, card_width, card_height = 220, 270, 220, 96
    positions, lanes = {}, []
    top, max_depth = 10, 0
    for milestone in milestones:
        slots, max_slot = defaultdict(int), 0
        for batch in (item for item in batches if item['parent_id'] == milestone['id']):
            depth = batch['dependency_depth']; slot = slots[depth]; slots[depth] += 1
            max_slot = max(max_slot, slot); max_depth = max(max_depth, depth)
            positions[batch['id']] = (label_width + 28 + depth * column_width,
                                      top + 18 + slot * (card_height + 10))
        height = 36 + (max_slot + 1) * card_height + max_slot * 10
        lanes.append((milestone, top, height)); top += height + 10
    width, height = label_width + 68 + (max_depth + 1) * column_width, max(top, 140)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
             '<style>text{font-family:system-ui}.lane{fill:#edf3f5}.label{font-weight:700;fill:#18384a}.description{font-size:11px;fill:#526b79}.edge{stroke:#91a5b1;stroke-width:2;fill:none}.card{fill:#fff;stroke:#557384;stroke-width:2}.ready{stroke:#176b60;stroke-dasharray:6 3}.blocked{fill:#f8dddd}.done{fill:#e2f3eb}.critical{stroke-width:4}</style>']
    for milestone, lane_top, lane_height in lanes:
        full_description = milestone['description'].replace('\n', ' ') or 'Bez doplňujícího popisu.'
        parts.append(f'<g><title>{escape(milestone["title"])} — {escape(full_description)}</title><rect class="lane" x="10" y="{lane_top}" width="{width-20}" height="{lane_height}" rx="11"/>')
        parts.append(f'<text class="label" x="28" y="{lane_top+28}">{escape(milestone["id"])} · {escape(milestone["title"][:28])}</text>')
        parts.append(f'<text class="description" x="28" y="{lane_top+49}">{escape(full_description[:30])}</text></g>')
    for batch in batches:
        target = positions.get(batch['id'])
        if not target:
            continue
        x2, y2 = target
        for parent in batch['depends_on']:
            if parent in positions:
                x1, y1 = positions[parent]
                parts.append(f'<path class="edge" d="M{x1+card_width} {y1+card_height//2} C{x1+card_width+28} {y1+card_height//2} {x2-28} {y2+card_height//2} {x2} {y2+card_height//2}"/>')
    for batch in batches:
        if batch['id'] not in positions:
            continue
        x, y = positions[batch['id']]; classes = ['card']
        if batch['checked']: classes.append('done')
        if batch['ready']: classes.append('ready')
        if batch['blocked']: classes.append('blocked')
        if batch['critical']: classes.append('critical')
        description = batch['description'].replace('\n', ' ') or 'Bez doplňujícího popisu.'
        parts.extend([f'<g><title>{escape(batch["title"])} — {escape(description)}</title><rect class="{" ".join(classes)}" x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="9"/>',
                      f'<text x="{x+10}" y="{y+22}" font-weight="700">{escape(batch["id"])}</text>',
                      f'<text x="{x+10}" y="{y+43}" font-size="11">{escape(batch["title"][:31])}</text>',
                      f'<text class="description" x="{x+10}" y="{y+64}">{escape(description[:31])}</text></g>'])
    parts.append(f'<metadata>{SCHEMA} {escape(value["revision"])}</metadata></svg>')
    return ''.join(parts)
