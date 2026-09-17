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


def request_from_file(project_id, base_head, path, title, description, tags, privacy, *,
                      source_url=None, source_author=None, source_created_at=None, source_revision=None,
                      supersedes=None):
    raw = read_source(path)
    request = dict(project_id=project_id, artifact_id=str(uuid4()), base_head=base_head,
                   filename=Path(path).name, title=title, description=description, tags=tags, privacy=privacy,
                   created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                   content=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest(),
                   source_url=source_url, source_author=source_author,
                   source_created_at=source_created_at, source_revision=source_revision)
    if supersedes is not None:
        request['supersedes'] = supersedes
    return request


class Sources(Artifacts):
    def duplicate_ids(self, project_id, base_head, digest):
        """Return same-project source IDs with identical evidenced bytes."""
        uuid(project_id)
        require(isinstance(base_head, str) and bool(re.fullmatch(r'[a-f0-9]{40,64}', base_head)),
                'Invalid base commit')
        require(isinstance(digest, str) and bool(re.fullmatch(r'[a-f0-9]{64}', digest)),
                'Invalid source digest')
        ws = self.workspace(project_id)
        with ws.journal.lock(), ws.journal.connect() as db:
            require(ws.git.head() == base_head, 'Projekt se změnil. Načtěte jej znovu.')
            files = ws.git.snapshot(base_head)
            entities = validate_snapshot(files)
            matches = []
            for id_, meta in entities.items():
                if meta['kind'] != 'source':
                    continue
                prefix = f'artifacts/{id_}/'
                path = prefix + meta['file'] if 'file' in meta else next(
                    path for path in files if path.startswith(prefix))
                if hashlib.sha256(files[path]).hexdigest() == digest:
                    matches.append(id_)
            return sorted(matches)

    def import_source(self, request, operation_id, *, checkpoint=lambda stage: None):
        fields = {'project_id', 'artifact_id', 'base_head', 'filename', 'title', 'description',
                  'tags', 'privacy', 'created_at', 'content', 'sha256', 'source_url',
                  'source_author', 'source_created_at', 'source_revision'}
        require(isinstance(request, dict) and fields <= request.keys() <= fields | {'supersedes'},
                'Invalid source import request')
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
        imported = dict(imported_at=request['created_at'], imported_by=author,
                        content_sha256=request['sha256'],
                        importer={'name': 'workspace-native-import', 'version': '2'})
        for key in ('source_author', 'source_created_at', 'source_revision'):
            if request[key] is not None:
                imported[key] = request[key]
        meta = dict(schema_version=2, id=request['artifact_id'], title=request['title'], kind='source',
                    created_at=request['created_at'], author_id=author, privacy=request['privacy'], provenance='external',
                    file=request['filename'], description=request['description'], tags=request['tags'])
        meta['import'] = imported
        if request['source_url'] is not None:
            meta['source_url'] = request['source_url']
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
            candidate_meta = meta
            if 'supersedes' in request:
                uuid(request['supersedes'])
                predecessor = entities.get(request['supersedes'])
                require(predecessor is not None and predecessor['kind'] == 'source',
                        'Superseded source is missing or is not a source')
                candidate_meta = dict(meta, relations=[{'type': 'supersedes', 'target_id': request['supersedes']}])
                validate_metadata(candidate_meta, sidecar=True)
            candidate_encoded = (json.dumps(candidate_meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
            require(len(candidate_encoded) <= MAX_METADATA, 'Metadata importu přesahují 64 KiB.')
            prefix = 'artifacts/' + request['artifact_id'] + '/'
            require(not any(path.startswith(prefix) for path in files), 'Source directory already exists')
            changes = {prefix + request['filename']: raw, prefix + 'metadata.json': candidate_encoded}
            candidate = dict(files); candidate.update(changes)
            validate_snapshot(candidate)
            return changes, 'Local workspace author', author + '@local.invalid', 'Import original source'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)

    def edit_metadata(self, request, operation_id, *, checkpoint=lambda stage: None):
        """Version allowed source annotations; privacy relaxation needs an explicit authorization bit."""
        fields = {'project_id', 'artifact_id', 'base_head', 'patch', 'authorize_privacy_relaxation'}
        require(isinstance(request, dict) and request.keys() == fields, 'Invalid source metadata request')
        uuid(request['project_id']); uuid(request['artifact_id'])
        require(type(request['authorize_privacy_relaxation']) is bool, 'Invalid privacy authorization')
        require(isinstance(request['patch'], dict) and request['patch'].keys() <=
                {'title', 'description', 'tags', 'relations', 'source_url', 'privacy'} and request['patch'],
                'Invalid source metadata patch')
        ws = self.workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()
        intent = dict(request, action='edit-source-metadata', author_id=author)

        def prepare(workspace):
            head = workspace.git.head()
            require(head == request['base_head'], 'Projekt se změnil. Načtěte aktuální zdroj.')
            committed_project(workspace.git, head, request['project_id'])
            files = workspace.git.snapshot(head)
            entities = validate_snapshot(files)
            meta = entities.get(request['artifact_id'])
            require(meta is not None and meta['kind'] == 'source' and 'file' in meta,
                    'Source artifact not found')
            updated = dict(meta); updated.update(request['patch'])
            validate_metadata(updated, sidecar=True)
            encoded = (json.dumps(updated, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
            require(len(encoded) <= MAX_METADATA, 'Metadata přesahují 64 KiB.')
            return {f"artifacts/{request['artifact_id']}/metadata.json": encoded}, \
                'Local workspace author', author + '@local.invalid', 'Edit source metadata'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'],
                           allow_privacy_relaxation=request['authorize_privacy_relaxation'],
                           checkpoint=checkpoint)

    def migrate_source(self, request, operation_id, *, checkpoint=lambda stage: None):
        """Upgrade one evidenced native v1 import without inventing source facts."""
        fields = {'project_id', 'artifact_id', 'base_head', 'import_commit'}
        require(isinstance(request, dict) and request.keys() == fields, 'Invalid source migration request')
        uuid(request['project_id']); uuid(request['artifact_id'])
        for key in ('base_head', 'import_commit'):
            require(isinstance(request[key], str) and bool(re.fullmatch(r'[a-f0-9]{40,64}', request[key])),
                    'Invalid commit')
        ws = self.workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()
        intent = dict(request, action='migrate-source-provenance-v2', author_id=author)

        def prepare(workspace):
            head = workspace.git.head()
            require(head == request['base_head'], 'Projekt se změnil. Migraci opakujte nad aktuálním HEAD.')
            committed_project(workspace.git, head, request['project_id'])
            ancestor = workspace.git.run('merge-base', '--is-ancestor', request['import_commit'], head, check=False)
            require(ancestor.returncode == 0, 'Import commit is not an ancestor of current HEAD')
            prefix = 'artifacts/' + request['artifact_id'] + '/'
            current_files = workspace.git.snapshot(head)
            current_entities = validate_snapshot(current_files)
            current = current_entities.get(request['artifact_id'])
            require(current is not None and current['kind'] == 'source' and current['provenance'] == 'external'
                    and current['schema_version'] == 1, 'Only external v1 sources can be migrated')
            origin_files = workspace.git.snapshot(request['import_commit'])
            origin_entities = validate_snapshot(origin_files)
            origin = origin_entities.get(request['artifact_id'])
            require(origin is not None and origin['kind'] == 'source' and origin['provenance'] == 'external'
                    and origin['schema_version'] == 1, 'Import commit does not contain the v1 source')
            parent = workspace.git.run('rev-parse', request['import_commit'] + '^', check=False)
            if parent.returncode == 0:
                require(not any(path.startswith(prefix) for path in workspace.git.snapshot(parent.stdout.strip())),
                        'Source already existed before the claimed import commit')
            proof = workspace.git.run('show', '-s', '--format=%s%n%b', request['import_commit']).stdout
            operation = re.search(r'^Workspace-Operation: ([^\r\n]+)$', proof, re.MULTILINE)
            require(proof.splitlines()[:1] == ['Import original source'] and operation is not None,
                    'Import commit lacks native Workspace evidence')
            uuid(operation.group(1))
            immutable = ('id', 'kind', 'created_at', 'author_id', 'provenance', 'file')
            require(all(current[key] == origin[key] for key in immutable),
                    'Current source no longer matches immutable import metadata')
            content_path = prefix + current['file']
            require(content_path in current_files and current_files[content_path] == origin_files.get(content_path),
                    'Current source bytes differ from the import commit')
            upgraded = dict(current, schema_version=2)
            upgraded['import'] = dict(imported_at=origin['created_at'], imported_by=origin['author_id'],
                                      content_sha256=hashlib.sha256(origin_files[content_path]).hexdigest(),
                                      importer={'name': 'workspace-native-import', 'version': '1'})
            validate_metadata(upgraded, sidecar=True)
            encoded = (json.dumps(upgraded, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
            require(len(encoded) <= MAX_METADATA, 'Metadata importu přesahují 64 KiB.')
            changes = {prefix + 'metadata.json': encoded}
            candidate = dict(current_files); candidate.update(changes)
            validate_snapshot(candidate)
            return changes, 'Local workspace author', author + '@local.invalid', 'Migrate source provenance to v2'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)
