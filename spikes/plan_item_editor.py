# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Revision-pinned plan edits (item text, new nodes, dependencies, deletion), over Workspace."""
import hashlib
import re

from spikes.artifact_history import ArtifactHistory, commit_id
from spikes.markdown_documents import document, main_todo_id, MAX_EDITOR
from spikes.metadata import require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_graph import ALIASES, DOCUMENT_LINK, RELATION, SOFTWARE_PROFILE, TASK, TASK_ID, project_task_graph

MAX_DEPENDENCIES = 200
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
CHILD_TYPE = {'milestone': 'batch', 'batch': 'task'}


def _fence_after(line, fence):
    """Return the fence state after a physical line; the marker line itself is never visible."""
    marker = FENCE.match(line.rstrip('\r\n'))
    if marker:
        token, tail = marker.groups()
        if fence is None:
            return (token[0], len(token))
        if token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
            return None
    return fence


def _width(line):
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def _leading(line):
    return line[:len(line) - len(line.lstrip(' \t'))]


def item_span(body, task_id):
    """Use physical offsets, ignoring fenced examples; never include child nodes."""
    lines = body.splitlines(keepends=True)
    offset = 0; fence = None; start = end = indent = None
    for line in lines:
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        visible = fence is None and not marker
        if marker:
            token, tail = marker.groups()
            if fence is None: fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip(): fence = None
        match = TASK.match(line.rstrip('\r\n')) if visible else None
        if start is not None:
            if match or (line.strip() and len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip()) <= indent):
                break
            if line.strip(): end = offset + len(line)
        elif match and match[3] == task_id:
            start = offset; end = offset + len(line); indent = len(match[1].expandtabs(4))
        offset += len(line)
    require(start is not None, 'Položka nemá bezpečně rozpoznaný Markdown blok.')
    return start, end


def subtree_span(body, task_id):
    """Own block plus every physically nested line; a fence only ends at its closing marker."""
    start = item_span(body, task_id)[0]
    lines = body[start:].splitlines(keepends=True)
    indent, offset, end, fence = _width(lines[0]), start, start, None
    for number, line in enumerate(lines):
        if number and fence is None and line.strip() and _width(line) <= indent:
            break
        fence = _fence_after(line, fence)
        offset += len(line)
        if line.strip():
            end = offset
    return start, end


def with_dependencies(block, node_id, targets, current):
    """Rewrite only own depends_on lines; other declarations in the block keep their bytes."""
    lines = block.splitlines(keepends=True)
    newline = '\r\n' if lines[0].endswith('\r\n') else '\n'
    indent, fence, declared, rows, type_row, nested = _width(lines[0]), None, [], [], None, None
    for number, line in enumerate(lines[1:], 1):
        visible = fence is None and not FENCE.match(line.rstrip('\r\n'))
        fence = _fence_after(line, fence)
        if not visible or not line.strip() or _width(line) <= indent:
            continue
        nested = nested or _leading(line)
        relation = RELATION.match(line.rstrip('\r\n'))
        if not relation:
            continue
        key = relation[2].strip().lower()
        if key in {'type', 'typ'}:
            type_row = number
        elif ALIASES.get(key) == 'depends_on':
            rows.append(number)
            declared += [item.strip() for item in relation[3].split(',')]
    inherited = set(current) - set(declared)
    missing = sorted(inherited - set(targets))
    require(not missing, f'Závislost {node_id} na {", ".join(missing)} je deklarovaná vztahem blocks '
                         'na druhé položce; odeberte ji tam.')
    own = [item for item in declared if item in targets]
    own += [item for item in targets if item not in own and item not in inherited]
    require(set(own) != set(declared) or len(own) != len(declared), 'Závislosti se nemění.')
    if rows:
        first = lines[rows[0]]
        ending = first[len(first.rstrip('\r\n')):]
        match = RELATION.match(first.rstrip('\r\n'))
        lines[rows[0]] = f'{match[1]}- {match[2].strip()}: {", ".join(own)}{ending}' if own else ''
        for number in rows[1:]:
            lines[number] = ''
    elif own:
        anchor = type_row if type_row is not None else 0
        prefix = nested if nested is not None else _leading(lines[0]) + '  '
        row = f'{prefix}- depends_on: {", ".join(own)}'
        if lines[anchor].endswith(('\n', '\r')):
            row += newline
        else:
            lines[anchor] += newline
        lines.insert(anchor + 1, row)
    return ''.join(lines)


def _text_lines(value):
    require(isinstance(value, str) and '\0' not in value, 'Invalid plan item text')
    return [line.strip() for line in value.splitlines() if line.strip()]


def _targets(value):
    require(isinstance(value, list) and len(value) <= MAX_DEPENDENCIES
            and all(isinstance(item, str) and TASK_ID.fullmatch(item) for item in value)
            and len(value) == len(set(value)), 'Invalid dependency list')
    return value


def _unchanged_except(before, after, *ignored):
    """Stored fields of untouched nodes; relations derived from removed declarations may differ."""
    for identifier, prior in before.items():
        if identifier in ignored or identifier not in after:
            continue
        fields = ('parent_id', 'type', 'source', 'title', 'checked', 'description', 'checklist', 'depends_on')
        require(all(prior.get(k) == after[identifier].get(k) for k in fields),
                'Změna zasahuje jinou položku nebo hierarchii.')


class PlanItems:
    def __init__(self, node, *, network=False):
        self.node, self.network = node, network
        self.projects = Projects(node, network=network)
        self.history = ArtifactHistory(node, network=network)

    def plan(self, files, project_id, head):
        entities = validate_snapshot(files)
        if self.network:
            require(all(item['privacy'] != 'local-only' for item in entities.values()), 'Project contains local-only data')
        plan = project_task_graph(files, entities, project_id, head)
        require(plan['status'] == 'ready', plan.get('error', 'Plán není platný.'))
        return plan, entities

    def model(self, files, project_id, artifact_id, task_id, head):
        uuid(project_id); uuid(artifact_id); commit_id(head)
        require(isinstance(task_id, str) and TASK_ID.fullmatch(task_id), 'Invalid task ID')
        plan, entities = self.plan(files, project_id, head)
        node = next((n for n in plan['nodes'] if n['id'] == task_id), None)
        require(node and node['source']['artifact_id'] == artifact_id, 'Položka není v tomto zdroji plánu.')
        doc = document(files, entities, artifact_id)
        start, end = item_span(doc['body'], task_id)
        return plan, node, doc, start, end

    def open(self, project_id, artifact_id, task_id, expected_head):
        with self.history._read(project_id, artifact_id, expected_head) as git:
            _, node, doc, start, end = self.model(git.snapshot(expected_head), project_id, artifact_id, task_id, expected_head)
            body = doc['body'][start:end]
            return dict(project_id=project_id, artifact_id=artifact_id, task_id=task_id,
                        expected_head=expected_head, title=node['title'], body=body,
                        parent_id=node['parent_id'], type=node['type'],
                        fragment_sha256=hashlib.sha256(body.encode()).hexdigest())

    def save(self, request, operation_id, *, checkpoint=lambda stage: None):
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'artifact_id', 'task_id', 'expected_head', 'fragment_sha256', 'body'}, 'Invalid plan item request')
        uuid(request['project_id']); uuid(request['artifact_id']); commit_id(request['expected_head'])
        require(isinstance(request['body'], str) and '\0' not in request['body']
                and 0 < len(request['body'].encode()) <= MAX_EDITOR, 'Invalid or oversized item draft')
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        author = ProjectCreation(self.node).author_id()

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'], 'Projekt se změnil. Rozepsanou položku zachovejte a načtěte aktuální stav.')
            files = ws.git.snapshot(head)
            plan, node, doc, start, end = self.model(files, request['project_id'], request['artifact_id'], request['task_id'], head)
            old = doc['body'][start:end]
            require(hashlib.sha256(old.encode()).hexdigest() == request['fragment_sha256'], 'Blok položky se změnil.')
            require(not old.endswith('\n') or request['body'].endswith('\n'), 'Zachovejte koncový nový řádek položky.')
            body = doc['body'][:start] + request['body'] + doc['body'][end:]
            require(len(body.encode()) <= MAX_EDITOR, 'Editor limit is 1 MiB')
            require(item_span(body, request['task_id']) == (start, start+len(request['body'])),
                    'Upravujte pouze vlastní blok položky, bez okolních nadpisů nebo dalších uzlů.')
            raw = files[doc['path']]; suffix = doc['body'].encode()
            require(raw.endswith(suffix), 'Nepodporované hranice dokumentu.')
            prefix = raw[:len(raw)-len(suffix)]
            candidate = dict(files, **{doc['path']: prefix + body.encode()})
            updated = project_task_graph(candidate, validate_snapshot(candidate), request['project_id'], head)
            require(updated['status'] == 'ready', updated.get('error', 'Plán není platný.'))
            before = {n['id']: n for n in plan['nodes']}; after = {n['id']: n for n in updated['nodes']}
            require(before.keys() == after.keys(), 'Editor položky nemění stabilní ID ani nepřidává další uzly.')
            for identifier, prior in before.items():
                fields = ['parent_id', 'type', 'source']
                if identifier != node['id']:
                    fields += ['title', 'checked', 'description', 'relations', 'checklist']
                require(all(prior.get(k) == after[identifier].get(k) for k in fields), 'Změna zasahuje jinou položku nebo hierarchii.')
            return {doc['path']: candidate[doc['path']]}, 'Local workspace author', author+'@local.invalid', 'Edit selected plan item'

        receipt = workspace.transact(operation_id, dict(action='edit-plan-item', **request), prepare,
                                     expected_head=request['expected_head'], checkpoint=checkpoint)
        return dict(project_id=request['project_id'], artifact_id=request['artifact_id'],
                    task_id=request['task_id'], commit_id=receipt['commit_id'])

    @staticmethod
    def _replaced(files, doc, body, project_id, head):
        """Candidate bytes keep the frontmatter/sidecar prefix; the whole bundle is revalidated."""
        require(len(body.encode()) <= MAX_EDITOR, 'Editor limit is 1 MiB')
        raw = files[doc['path']]; suffix = doc['body'].encode()
        require(raw.endswith(suffix), 'Nepodporované hranice dokumentu.')
        candidate = dict(files, **{doc['path']: raw[:len(raw)-len(suffix)] + body.encode()})
        return candidate, project_task_graph(candidate, validate_snapshot(candidate), project_id, head)

    def _write(self, action, request, operation_id, change, message, checkpoint):
        """One file, one commit: ADR 0059 journal, Git CAS and index recovery apply unchanged."""
        uuid(request['project_id']); commit_id(request['expected_head'])
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        author = ProjectCreation(self.node).author_id()

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'], 'Projekt se změnil. Načtěte aktuální stav plánu a akci zopakujte.')
            files = ws.git.snapshot(head)
            return change(files, head), 'Local workspace author', author+'@local.invalid', message

        return workspace.transact(operation_id, dict(action=action, **request), prepare,
                                  expected_head=request['expected_head'], checkpoint=checkpoint)

    def create(self, request, operation_id, *, checkpoint=lambda stage: None):
        """Append a node as the last child of its parent; a linked batch appends to its own file."""
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'parent_id', 'expected_head', 'task_id', 'title', 'description', 'depends_on'}, 'Invalid plan item request')
        uuid(operation_id)
        parent_id, wanted = request['parent_id'], request['task_id']
        require(parent_id is None or (isinstance(parent_id, str) and TASK_ID.fullmatch(parent_id)), 'Invalid parent ID')
        require(wanted is None or (isinstance(wanted, str) and TASK_ID.fullmatch(wanted)),
                'ID musí mít tvar např. FEATURE-01.')
        title = request['title'].strip() if isinstance(request['title'], str) else ''
        require(0 < len(title) <= 500 and len(title.splitlines()) == 1 and '\0' not in title, 'Zadejte jednořádkový název položky.')
        require(not DOCUMENT_LINK.fullmatch(title), 'Odkaz na soubor připojte v editoru celého plánu.')
        description, depends_on = _text_lines(request['description']), _targets(request['depends_on'])
        # Stable under replay: transact does not run prepare again for a known operation.
        identifier = wanted or 'NEW-' + hashlib.sha256(operation_id.encode()).hexdigest()[:10].upper() + '-1'

        def change(files, head):
            plan, entities = self.plan(files, request['project_id'], head)
            nodes = sorted(plan['nodes'], key=lambda n: n['line'])
            before = {n['id']: n for n in nodes}
            profiled = plan.get('profile') == SOFTWARE_PROFILE
            if parent_id is None:
                kind = 'milestone' if profiled else None
                doc = document(files, entities, main_todo_id(request['project_id']))
                siblings = [n for n in nodes if n['parent_id'] is None and n['source']['path'] == doc['path']]
                link = None
            else:
                parent = before.get(parent_id)
                require(parent, 'Nadřazená položka již není v plánu.')
                kind = CHILD_TYPE.get(parent['type'])
                require(profiled and kind, 'Pod tento typ položky nelze přidat další uzel.')
                require(not parent['checked'], 'Dokončená položka nepřijímá nové podřízené položky.')
                doc = document(files, entities, parent['source']['artifact_id'])
                start, end = item_span(doc['body'], parent_id)
                title_match = TASK.match(doc['body'][start:end].splitlines()[0])
                link = DOCUMENT_LINK.fullmatch(title_match[4])
                if link:
                    doc = document(files, entities, link[3])
                siblings = [n for n in nodes if n['parent_id'] == parent_id]
            require(identifier not in before, f'ID {identifier} už v plánu existuje.')
            body = doc['body']
            if siblings:
                last = siblings[-1]['id']
                position = subtree_span(body, last)[1]
                prefix = _leading(body[item_span(body, siblings[0]['id'])[0]:])
            else:
                position = subtree_span(body, parent_id)[1]
                prefix = _leading(body[item_span(body, parent_id)[0]:]) + '  '
            newline = '\r\n' if '\r\n' in body else '\n'
            rows = [f'{prefix}- [ ] [{identifier}] {title}']
            if kind:
                rows.append(f'{prefix}  - type: {kind}')
            if depends_on:
                rows.append(f'{prefix}  - depends_on: {", ".join(depends_on)}')
            rows += [f'{prefix}  - {line}' for line in description]
            text = newline.join(rows)
            if position and body[position-1] not in '\r\n':
                text = newline + text
            else:
                text += newline
            candidate, updated = self._replaced(files, doc, body[:position] + text + body[position:], request['project_id'], head)
            require(updated['status'] == 'ready', updated.get('error', 'Plán není platný.'))
            after = {n['id']: n for n in updated['nodes']}
            require(set(after) == set(before) | {identifier}, 'Popis nebo název vytváří další uzel.')
            _unchanged_except(before, after, identifier)
            made = after[identifier]
            require(made['title'] == title and made['parent_id'] == parent_id and made['type'] == kind
                    and made['description'] == '\n'.join(description) and not made['checklist']
                    and made['depends_on'] == sorted(depends_on),
                    'Popis nesmí obsahovat metadata, vztahy ani podmínky; doplňte je úpravou položky.')
            return {doc['path']: candidate[doc['path']]}

        receipt = self._write('create-plan-item', request, operation_id, change, 'Add plan item', checkpoint)
        return dict(project_id=request['project_id'], parent_id=parent_id, task_id=identifier, commit_id=receipt['commit_id'])

    def set_dependencies(self, request, operation_id, *, checkpoint=lambda stage: None):
        """Make the node's prerequisites exactly the requested set; a cycle fails the bundle check."""
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'task_id', 'expected_head', 'depends_on'}, 'Invalid plan item request')
        require(isinstance(request['task_id'], str) and TASK_ID.fullmatch(request['task_id']), 'Invalid task ID')
        targets, identifier = _targets(request['depends_on']), request['task_id']

        def change(files, head):
            plan, entities = self.plan(files, request['project_id'], head)
            before = {n['id']: n for n in plan['nodes']}
            node = before.get(identifier)
            require(node, 'Položka již není v plánu.')
            doc = document(files, entities, node['source']['artifact_id'])
            start, end = item_span(doc['body'], identifier)
            old = doc['body'][start:end]
            block = with_dependencies(old, identifier, targets, node['depends_on'])
            candidate, updated = self._replaced(files, doc, doc['body'][:start] + block + doc['body'][end:], request['project_id'], head)
            require(updated['status'] == 'ready', updated.get('error', 'Plán není platný.'))
            after = {n['id']: n for n in updated['nodes']}
            require(after.keys() == before.keys() and after[identifier]['depends_on'] == sorted(targets),
                    'Závislosti nelze bezpečně změnit v tomto bloku.')
            _unchanged_except(before, after, identifier)
            return {doc['path']: candidate[doc['path']]}

        receipt = self._write('set-plan-item-dependencies', request, operation_id, change, 'Change plan item dependencies', checkpoint)
        return dict(project_id=request['project_id'], task_id=identifier, commit_id=receipt['commit_id'])

    def _deletion(self, files, project_id, task_id, head):
        plan, entities = self.plan(files, project_id, head)
        nodes = {n['id']: n for n in plan['nodes']}
        node = nodes.get(task_id)
        require(node, 'Položka již není v plánu.')
        removed = {task_id}
        for item in sorted(nodes.values(), key=lambda n: n['hierarchy_depth']):
            if item['parent_id'] in removed:
                removed.add(item['id'])
        doc = document(files, entities, node['source']['artifact_id'])
        start, end = subtree_span(doc['body'], task_id)
        first = TASK.match(doc['body'][start:end].splitlines()[0])
        dependents = sorted(n['id'] for n in nodes.values() if n['id'] not in removed and removed & set(n['depends_on']))
        blocker, candidate = None, None
        if DOCUMENT_LINK.fullmatch(first[4]):
            blocker = 'Dávka odkazuje na samostatný soubor; odkaz odeberte v editoru celého plánu.'
        elif dependents:
            blocker = 'Na položce závisí: ' + ', '.join(dependents) + '. Nejprve u nich závislost odeberte.'
        else:
            candidate, updated = self._replaced(files, doc, doc['body'][:start] + doc['body'][end:], project_id, head)
            if updated['status'] != 'ready':
                blocker = 'Po smazání by plán nebyl platný: ' + updated.get('error', 'neplatný formát')
            else:
                after = {n['id']: n for n in updated['nodes']}
                require(set(after) == set(nodes) - removed, 'Blok položky neodpovídá jejímu podstromu.')
                _unchanged_except(nodes, after)
        return node, [nodes[i] for i in sorted(removed, key=lambda i: nodes[i]['line'])], dependents, blocker, candidate, doc

    def delete_preview(self, project_id, task_id, expected_head):
        require(isinstance(task_id, str) and TASK_ID.fullmatch(task_id), 'Invalid task ID')
        with self.history._read(project_id, main_todo_id(project_id), expected_head) as git:
            node, removed, dependents, blocker, _, _ = self._deletion(git.snapshot(expected_head), project_id, task_id, expected_head)
        return dict(project_id=project_id, task_id=task_id, expected_head=expected_head, title=node['title'],
                    removed=[dict(id=n['id'], title=n['title'], type=n['type'], checked=n['checked']) for n in removed],
                    dependents=dependents, blocker=blocker)

    def delete(self, request, operation_id, *, checkpoint=lambda stage: None):
        """Remove the node with its nested subtree; Git history keeps the removed text."""
        require(isinstance(request, dict) and set(request) == {'project_id', 'task_id', 'expected_head'}, 'Invalid plan item request')
        require(isinstance(request['task_id'], str) and TASK_ID.fullmatch(request['task_id']), 'Invalid task ID')

        def change(files, head):
            _, _, _, blocker, candidate, doc = self._deletion(files, request['project_id'], request['task_id'], head)
            require(blocker is None, blocker)
            return {doc['path']: candidate[doc['path']]}

        receipt = self._write('delete-plan-item', request, operation_id, change, 'Delete plan item', checkpoint)
        return dict(project_id=request['project_id'], task_id=request['task_id'], commit_id=receipt['commit_id'])
