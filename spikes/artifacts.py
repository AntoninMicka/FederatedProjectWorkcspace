"""Native Markdown editing over the registered Workspace transaction boundary."""
from datetime import datetime, timezone
import json
import re
import time

import yaml

from spikes.configuration import committed_project
from spikes.metadata import require, safe_path, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation, regular
from spikes.projects import Projects
from spikes.storage import StaleIndex
from spikes.markdown_documents import MAX_EDITOR, main_todo_id, checklist_items, document

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
        required = {'project_id', 'artifact_id', 'base_head', 'title', 'body', 'new'}
        require(isinstance(request, dict) and required <= request.keys() <= required | {'metadata', 'filename'},
                'Invalid editor request')
        if 'filename' in request:
            filename = request['filename']
            require(len(safe_path(filename)) == 1 and filename.endswith('.md')
                    and len(filename.encode('utf-8')) <= 200
                    and not any(ord(c) < 32 or ord(c) == 127 for c in filename),
                    'Název souboru musí končit .md, bez složek, nejvýše 200 bajtů UTF-8.')
        patch = request.get('metadata', {})
        require(isinstance(patch, dict) and patch.keys() <= {'description', 'tags'}, 'Invalid editable metadata')
        if 'description' in patch:
            require(isinstance(patch['description'], str), 'Invalid description')
        if 'tags' in patch:
            require(isinstance(patch['tags'], list) and
                    all(isinstance(tag, str) and tag.strip() for tag in patch['tags']), 'Invalid tags')
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
            old_path = path
            if 'filename' in request:
                path = f'artifacts/{id_}/' + request['filename']
                require(path == old_path or path not in files, 'Cílový soubor již existuje.')
                if sidecar:
                    meta['file'] = request['filename']
            meta.update(patch)
            body = request['body'].encode()
            if sidecar:
                changes = {path: body, sidecar: (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()}
            else:
                changes = {path: ('---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=True) + '---\n').encode() + body}
            if path != old_path and not request['new']:
                # A pure rename preserves original content bytes, including YAML formatting.
                if request['body'] == doc['body'] and (sidecar or meta == doc['metadata']):
                    changes[path] = files[old_path]
                changes[old_path] = None
            return changes, 'Local workspace author', author + '@local.invalid', 'Save Markdown document'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)
