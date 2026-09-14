# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native immutable-source import using the existing Workspace transaction."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.configuration import committed_project
from spikes.metadata import (MAX_FILE, MAX_METADATA, require, safe_path, uuid,
                             validate_metadata, validate_snapshot)
from spikes.project_creation import ProjectCreation

SUFFIXES = {'.md', '.png', '.jpg', '.jpeg', '.pdf'}


def content_type(filename, raw):
    require(len(safe_path(filename)) == 1 and len(filename.encode('utf-8')) <= 200
            and filename != 'metadata.json' and not any(ord(c) < 32 or ord(c) == 127 for c in filename),
            'Vyberte bezpečný název souboru bez adresářů, nejvýše 200 bajtů UTF-8.')
    suffix = Path(filename).suffix.lower()
    require(suffix in SUFFIXES and len(raw) <= MAX_FILE, 'Import podporuje Markdown, PNG, JPEG a PDF do 16 MiB.')
    if suffix == '.md':
        require(b'\0' not in raw, 'Markdown nesmí obsahovat nulové bajty.')
        try:
            raw.decode('utf-8')
        except UnicodeError as exc:
            raise ValueError('Markdown musí být UTF-8; import jeho obsah nepřekóduje.') from exc
    elif suffix == '.png':
        require(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Soubor nemá PNG hlavičku.')
    elif suffix in {'.jpg', '.jpeg'}:
        require(raw.startswith(b'\xff\xd8\xff'), 'Soubor nemá JPEG hlavičku.')
    else:
        require(raw.startswith(b'%PDF-'), 'Soubor nemá PDF hlavičku.')


def read_source(path):
    path = Path(path).absolute()
    require(path == path.resolve(), 'Zdrojová cesta nesmí obsahovat symlinky.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE, 'Vyberte běžný soubor do 16 MiB.')
        raw = handle.read(MAX_FILE + 1)
        after = os.fstat(handle.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Zdroj se při čtení změnil. Vyberte jej znovu.')
    content_type(path.name, raw)
    return raw


def request_from_file(project_id, base_head, path, title, description, tags, privacy):
    raw = read_source(path)
    return dict(project_id=project_id, artifact_id=str(uuid4()), base_head=base_head,
                filename=Path(path).name, title=title, description=description, tags=tags, privacy=privacy,
                created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                content=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())


class Sources(Artifacts):
    def import_source(self, request, operation_id, *, checkpoint=lambda stage: None):
        fields = {'project_id', 'artifact_id', 'base_head', 'filename', 'title', 'description',
                  'tags', 'privacy', 'created_at', 'content', 'sha256'}
        require(isinstance(request, dict) and request.keys() == fields, 'Invalid source import request')
        uuid(request['project_id']); uuid(request['artifact_id'])
        require(isinstance(request['base_head'], str) and bool(re.fullmatch(r'[a-f0-9]{40,64}', request['base_head'])), 'Invalid base commit')
        require(isinstance(request['content'], str) and len(request['content']) <= 4 * ((MAX_FILE + 2) // 3), 'Oversized encoded source')
        raw = base64.b64decode(request['content'], validate=True)
        content_type(request['filename'], raw)
        require(hashlib.sha256(raw).hexdigest() == request['sha256'], 'Source digest differs')
        require(isinstance(request['title'], str) and 0 < len(request['title'].strip()) <= 200
                and not any(c in request['title'] for c in '\r\n\0'), 'Vyplňte název zdroje do 200 znaků.')
        ws = self.workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()
        meta = dict(schema_version=1, id=request['artifact_id'], title=request['title'], kind='source',
                    created_at=request['created_at'], author_id=author, privacy=request['privacy'], provenance='external',
                    file=request['filename'], description=request['description'], tags=request['tags'])
        validate_metadata(meta, sidecar=True)
        encoded_meta = (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        require(len(encoded_meta) <= MAX_METADATA, 'Metadata importu přesahují 64 KiB.')
        # The digest binds exact bytes without duplicating them in the intent JSON.
        intent = {key: value for key, value in request.items() if key != 'content'}
        intent.update(action='import-source', author_id=author)

        def prepare(workspace):
            head = workspace.git.head()
            require(head == request['base_head'], 'Projekt se změnil. Import nelze přepsat na jiný HEAD; nejprve načtěte projekt.')
            committed_project(workspace.git, head, request['project_id'])
            files = workspace.git.snapshot(head)
            entities = validate_snapshot(files)
            require(request['artifact_id'] not in entities, 'Source UUID already exists')
            prefix = 'artifacts/' + request['artifact_id'] + '/'
            require(not any(path.startswith(prefix) for path in files), 'Source directory already exists')
            changes = {prefix + request['filename']: raw, prefix + 'metadata.json': encoded_meta}
            candidate = dict(files); candidate.update(changes)
            validate_snapshot(candidate)
            return changes, 'Local workspace author', author + '@local.invalid', 'Import original source'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)
