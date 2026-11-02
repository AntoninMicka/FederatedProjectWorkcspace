# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Revision-pinned edits of one node's own Markdown block, over Workspace."""
import hashlib
import re

from spikes.artifact_history import ArtifactHistory, commit_id
from spikes.markdown_documents import document, MAX_EDITOR
from spikes.metadata import require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_graph import TASK, TASK_ID, project_task_graph


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


class PlanItems:
    def __init__(self, node, *, network=False):
        self.node, self.network = node, network
        self.projects = Projects(node, network=network)
        self.history = ArtifactHistory(node, network=network)

    def model(self, files, project_id, artifact_id, task_id, head):
        uuid(project_id); uuid(artifact_id); commit_id(head)
        require(isinstance(task_id, str) and TASK_ID.fullmatch(task_id), 'Invalid task ID')
        entities = validate_snapshot(files)
        if self.network:
            require(all(item['privacy'] != 'local-only' for item in entities.values()), 'Project contains local-only data')
        plan = project_task_graph(files, entities, project_id, head)
        require(plan['status'] == 'ready', plan.get('error', 'Plán není platný.'))
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
