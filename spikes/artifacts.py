"""Native Markdown editing over the registered Workspace transaction boundary."""
from datetime import datetime, timezone
import json
import re
import time
from uuid import UUID, uuid5

import yaml

from spikes.configuration import committed_project
from spikes.metadata import MAX_METADATA, require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation, regular
from spikes.projects import Projects
from spikes.storage import StaleIndex

MAX_EDITOR = 1024 * 1024


def main_todo_id(project_id):
    uuid(project_id)
    return str(uuid5(UUID(project_id), 'federated-workspace:main-todo:v1'))


def checklist_items(body):
    """Return source offsets for list checkboxes, excluding fenced code blocks.

    The supported subset is -, + or * lists (including indented lists) and
    backtick/tilde fences. Raw HTML and links are never rendered or executed.
    """
    result, offset, fence = [], 0, None
    for line in body.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if marker:
            token, tail = marker.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                fence = None
        elif fence is None:
            match = re.match(r'^\s*[-+*]\s+\[([ xX])\][ \t]+(.*?)[\r\n]*$', line)
            if match:
                result.append(dict(offset=offset + match.start(1), checked=match[1].lower() == 'x',
                                   title=match[2]))
        offset += len(line)
    return result


def document(files, entities, artifact_id):
    prefix = f'artifacts/{artifact_id}/'
    entries = {p: data for p, data in files.items() if p.startswith(prefix)}
    require(entries and artifact_id in entities, 'Artifact does not exist')
    meta = entities[artifact_id]
    require(meta['kind'] == 'document', 'Only document artifacts are editable')
    sidecar = prefix + 'metadata.json'
    path = prefix + meta['file'] if sidecar in entries else next(iter(entries))
    require(path.endswith('.md'), 'Only Markdown documents are editable')
    raw = entries[path]
    require(len(raw) <= MAX_EDITOR + MAX_METADATA, 'Editor limit is 1 MiB')
    if sidecar in entries:
        body = raw.decode('utf-8')
    else:
        lines = raw.splitlines(keepends=True)
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip(b'\r\n') == b'---')
        body = b''.join(lines[end + 1:]).decode('utf-8')
    require(len(body.encode()) <= MAX_EDITOR, 'Editor limit is 1 MiB')
    return dict(id=artifact_id, title=meta['title'], body=body, metadata=meta,
                path=path, sidecar=sidecar if sidecar in entries else None)


class Artifacts:
    def __init__(self, node_path, *, timeout=60):
        self.projects = Projects(node_path)
        self.node_path, self.timeout = node_path, timeout

    def workspace(self, project_id):
        from pathlib import Path
        node = Path(self.node_path).absolute()
        require(node == node.resolve(), 'Node configuration must not use symlinks')
        regular(node, private=False)
        return self.projects.workspace(project_id, blocking=False, deadline=time.monotonic() + self.timeout)

    def open(self, project_id):
        ws = self.workspace(project_id)
        # A native open is an explicit recovery entrypoint; HTTP open stays read-only.
        ws.recover()
        with ws.journal.lock(), ws.journal.connect() as db:
            ws._branch()
            require(not ws.git.run('ls-files', '-u').stdout, 'Unresolved merge')
            head = ws.git.head()
            meta = committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head)
            entities = validate_snapshot(files)
            rows = ws._read_locked(db)
            require(rows == sorted((m['id'], m['title']) for m in entities.values()),
                    'Index differs from validated commit')
            docs = []
            for id_, item in entities.items():
                if item['kind'] == 'document' and any(p.startswith(f'artifacts/{id_}/') and p.endswith('.md') for p in files):
                    docs.append(document(files, entities, id_))
            if ws.git.head() != head:
                raise StaleIndex('Project changed while reading')
            return dict(id=project_id, title=meta['title'], commit_id=head, documents=docs,
                        main_todo_id=main_todo_id(project_id))

    def save(self, request, operation_id, *, checkpoint=lambda stage: None):
        require(isinstance(request, dict) and request.keys() == {
            'project_id', 'artifact_id', 'base_head', 'title', 'body', 'new'}, 'Invalid editor request')
        for key in ('project_id', 'artifact_id'):
            uuid(request[key])
        require(type(request['new']) is bool, 'Invalid create flag')
        require(isinstance(request['base_head'], str) and re.fullmatch(r'[0-9a-f]{40,64}', request['base_head']), 'Invalid base commit')
        require(isinstance(request['title'], str) and 0 < len(request['title'].strip()) <= 200
                and not any(c in request['title'] for c in '\r\n\0'), 'Invalid document title')
        require(isinstance(request['body'], str) and '\0' not in request['body']
                and len(request['body'].encode()) <= MAX_EDITOR, 'Invalid or oversized Markdown')
        ws = self.workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()
        intent = dict(request, author_id=author)

        def prepare(workspace):
            head = workspace.git.head()
            require(head == request['base_head'], 'Projekt se změnil. Otevřete aktuální verzi; rozepsaný text zachovejte.')
            committed_project(workspace.git, head, request['project_id'])
            files = workspace.git.snapshot(head)
            entities = validate_snapshot(files)
            id_ = request['artifact_id']
            if request['new']:
                require(id_ not in entities, 'Artifact ID already exists')
                prefix = f'artifacts/{id_}/'
                meta = dict(schema_version=1, id=id_, title=request['title'], kind='document',
                            created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                            author_id=author, privacy='project', provenance='user', file='content.md')
                path, sidecar = prefix + 'content.md', prefix + 'metadata.json'
            else:
                doc = document(files, entities, id_)
                meta, path, sidecar = dict(doc['metadata']), doc['path'], doc['sidecar']
                meta['title'] = request['title']
            body = request['body'].encode()
            if sidecar:
                changes = {path: body, sidecar: (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()}
            else:
                changes = {path: ('---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=True) + '---\n').encode() + body}
            return changes, 'Local workspace author', author + '@local.invalid', 'Save Markdown document'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)
