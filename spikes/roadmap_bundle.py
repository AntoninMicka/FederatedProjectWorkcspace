# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Assemble immutable import payloads; no project, Git or journal writes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from spikes.markdown_documents import main_todo_id
from spikes.metadata import require, safe_path, timestamp, uuid, validate_snapshot
from spikes.roadmap_mapping import load_sources, validate_mapping_binding
from spikes.roadmap_migration import canonical
from spikes.task_graph import project_task_graph

SCHEMA = 'fpw-roadmap-import-bundle-v1'
IMPORTER = {'name': 'roadmap-git-migration', 'version': '1'}
PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _identity(scope, role):
    return str(uuid5(NAMESPACE_URL, 'roadmap-import:' + scope + ':' + role))


def project_files(project, blobs):
    """Resolve exact candidate bytes in memory, not into a live repository."""
    files = {}
    for entry in project['files']:
        parts = safe_path(entry['path'])
        require(len(parts) == 3 and parts[0] == 'artifacts', 'Invalid package path')
        uuid(parts[1])
        require(parts[1] == entry['artifact_id'] and entry['path'] not in files, 'Package identity/path collision')
        data = blobs.get(entry['sha256'])
        require(isinstance(data, bytes) and len(data) == entry['size']
                and digest(data) == entry['sha256'], 'Missing or modified package blob')
        files[entry['path']] = data
    return files


def _scoped_mapping(mapping, scope):
    """Keep module internals out of the host project (ADR 0026)."""
    return dict(schema='fpw-roadmap-identity-map-v1', repository_id=scope,
                mapping_sha256=mapping['mapping_sha256'], inventory_sha256=mapping['inventory_sha256'],
                definitions=[item for item in mapping['definitions'] if item['repository_id'] == scope],
                anonymous_identities=[item for item in mapping['anonymous_identities'] if item['repository_id'] == scope],
                coverage={key: item for key, item in mapping['coverage'].items() if key.startswith(scope + ':')},
                dependency_hints=mapping['preserved_dependency_hints'] if scope == 'federated-workspace' else [],
                historical_dependency_context=mapping.get('historical_dependency_context', []) if scope == 'federated-workspace' else [],
                milestone_completion_evidence=[item for item in mapping.get('milestone_completion_evidence', [])
                                               if item['repository_id'] == scope])


def assemble_bundle(value, mapping, roots, *, author_id, created_at, privacy, target_locations=None):
    """Return a manifest and content-addressed blobs for subsequent validation.

    created_at is package preparation time, never a guessed original source
    timestamp. New module UUIDs are proposals supported by seeded creation.
    Artifact shape checks here do not replace authorization/recovery gates.
    """
    uuid(author_id); timestamp(created_at)
    target_locations = target_locations or {}
    require(privacy in PRIVACY_ORDER, 'Invalid proposed import privacy')
    validate_mapping_binding(mapping, value)
    require(mapping.get('mapping_policy') == 'history-inclusive-and-free-descriptions-v2',
            'Build a current history-inclusive mapping before assembling')
    raw = load_sources(value, roots)
    host = next((p for p in mapping['projects'] if p['repository_id'] == 'federated-workspace'), None)
    require(host and host.get('target_project_id') and host.get('target_preview'), 'Bind the existing host target first')
    require(host['target_preview']['action'] == 'replace-test-plan'
            and host['target_preview'].get('replacement_authorized'), 'Test-plan replacement is not authorized')
    host_id = host['target_project_id']; uuid(host_id)
    targets = {p['repository_id']: p.get('target_project_id') or
               str(uuid5(UUID(host_id), 'module-project:' + p['repository_id'])) for p in mapping['projects']}
    require(len(targets.values()) == len(set(targets.values())), 'Two scopes select the same target project')
    require(set(target_locations) <= set(targets), 'Target location supplied for an unknown scope')
    blobs, projects = {}, []

    def blob(data):
        key = digest(data)
        require(key not in blobs or blobs[key] == data, 'Blob collision')
        blobs[key] = data
        return key

    for project in mapping['projects']:
        scope = project['repository_id']; project_id = targets[scope]
        uuid(project_id)
        require(project.get('graph') is not None, 'Project hierarchy is missing')
        own_sources = [s for s in value['sources'] if s['repository_id'] == scope]
        files, entries, artifact_roles = {}, [], {}
        replace_artifact_ids = set(project.get('replace_artifact_ids', []))
        replacement_metadata = project.get('replacement_metadata', {})

        def add(id_, filename, content, role, title, *, source_revision=None, source_mime=None, root_meta=None):
            uuid(id_)
            require(id_ not in artifact_roles, 'Duplicate artifact identity')
            require(len(safe_path(filename)) == 1 and filename != 'metadata.json', 'Invalid artifact filename')
            require(isinstance(content, bytes), 'Artifact bytes required')
            original_title = title
            if len(title) > 200:
                title = 'Podklad ' + id_
            preserved_meta = root_meta if root_meta is not None else replacement_metadata.get(id_)
            if preserved_meta is not None:
                # Preserve immutable identity/origin fields while discarding
                # optional test-plan labels, descriptions and relationships.
                meta = {key: preserved_meta[key] for key in (
                    'schema_version', 'id', 'kind', 'created_at', 'author_id', 'privacy', 'provenance')}
                require(meta['id'] == id_ and meta['kind'] in {'document', 'source'},
                        'Existing replacement identity differs')
                require(PRIVACY_ORDER[privacy] >= PRIVACY_ORDER[meta['privacy']], 'Proposed privacy would relax existing root')
                meta.update(file=filename, title=title, privacy=privacy, tags=['main-todo', 'roadmap-import'])
                if root_meta is None:
                    meta['tags'] = list(preserved_meta.get('tags', ['roadmap-import', role]))
                if 'import' in preserved_meta:
                    meta['import'] = preserved_meta['import']
            else:
                meta = dict(schema_version=2, id=id_, title=title,
                            kind='source' if role in {'original-source', 'identity-map', 'source-manifest'} else 'document',
                            created_at=created_at, author_id=author_id, privacy=privacy, provenance='external',
                            file=filename, tags=['roadmap-import', role],
                            import_=dict(imported_at=created_at, imported_by=author_id,
                                         content_sha256=digest(content), importer=IMPORTER,
                                         source_revision=source_revision or mapping['mapping_sha256']))
                meta['import'] = meta.pop('import_')
                if source_mime:
                    meta['import']['source_mime_type'] = source_mime
                if filename.endswith('.md'):
                    meta['import']['export_mime_type'] = 'text/markdown'
                    meta['import'].setdefault('source_mime_type', 'text/markdown')
            prefix = f'artifacts/{id_}/'
            for path, data, payload_role in [(prefix + filename, content, role),
                                             (prefix + 'metadata.json', encoded(meta), 'metadata')]:
                require(path not in files, 'Duplicate output path')
                files[path] = data
                entries.append(dict(path=path, sha256=blob(data), size=len(data), artifact_id=id_,
                                    role=payload_role, artifact_role=role,
                                    action='replace' if preserved_meta is not None or id_ in replace_artifact_ids
                                    else 'create'))
            artifact_roles[id_] = dict(role=role, title=title, original_title=original_title, path=prefix + filename)

        manifest_sources = []
        for key, relative in sorted(project['source_references'].items()):
            source = next((s for s in own_sources if s['key'] == key), None)
            require(source is not None, 'Project references a foreign or unselected source')
            parts = safe_path(relative)
            require(len(parts) == 3 and parts[0] == 'artifacts', 'Invalid source artifact path')
            mime = 'text/markdown' if source['path'].endswith('.md') else 'application/json'
            add(parts[1], parts[2], raw[key], 'original-source', source['path'],
                source_revision=source['commit_id'], source_mime=mime)
            manifest_sources.append(dict(source, artifact_id=parts[1], artifact_path=relative))
        require({s['key'] for s in own_sources} == set(project['source_references']), 'Source selection is incomplete')
        for note in project.get('prose_documents', []):
            require(note['repository_id'] == scope, 'Foreign note in project')
            require(safe_path(note['path']) == ['artifacts', note['id'], 'content.md'], 'Invalid note path')
            add(note['id'], 'content.md', note['body'].encode('utf-8'), 'free-description', note['title'])

        identities = _scoped_mapping(mapping, scope)
        identity_bytes = encoded(identities)
        identity_id = _identity(scope, 'identity-map:' + digest(identity_bytes))
        add(identity_id, 'mapping.json', identity_bytes, 'identity-map', 'Mapování ID a původních záznamů',
            source_mime='application/json')
        provenance = dict(schema='fpw-roadmap-source-manifest-v1', repository_id=scope,
                          prepared_at=created_at, prepared_by=author_id, sources=manifest_sources,
                          inventory_sha256=value['inventory_sha256'], mapping_sha256=mapping['mapping_sha256'],
                          target_test_plan_is_source=False, source_times='Only pinned Git revisions are asserted; no original timestamp is guessed')
        provenance_bytes = encoded(provenance)
        provenance_id = _identity(scope, 'source-manifest:' + digest(provenance_bytes))
        add(provenance_id, 'sources.json', provenance_bytes, 'source-manifest', 'Zdrojové revize a provenance',
            source_mime='application/json')

        related = []
        if scope == 'federated-workspace':
            related = [dict(module_id=other, project_id=id_) for other, id_ in sorted(targets.items()) if other != scope]
            if related:
                link_id = _identity(scope, 'module-links')
                lines = ['# Propojené modulové projekty', '', 'Identita modulu a odpovídajícího Workspace projektu.', '']
                lines += [f'- {item["module_id"]}: `{item["project_id"]}`' for item in related]
                add(link_id, 'content.md', ('\n'.join(lines) + '\n').encode(), 'module-links', 'Propojené modulové projekty')
        body = project['body']
        require('# Migrační náhled\n' in body, 'Unexpected generated plan header')
        body = body.replace('# Migrační náhled\n', '# Roadmapa projektu\n', 1)
        body = body.replace('Testovací cílový plán se nepoužívá jako zdroj a bude kompletně nahrazen.\n', '', 1)
        body = body.replace('Přiložené původní texty jsou zdrojové snapshoty, nikoli nové pokyny k migraci.\n',
                            'Přiložené původní texty jsou zdrojové snapshoty; autoritativní stav úkolů drží tento plán.\n', 1)
        body += f'\n## Provenance importu\n\n[Mapování ID](artifacts/{identity_id}/mapping.json) · '
        body += f'[Zdrojové revize](artifacts/{provenance_id}/sources.json)\n'
        if related:
            body += f'\n[Propojené modulové projekty](artifacts/{link_id}/content.md)\n'
        root_meta = project.get('target_preview', {}).get('original_metadata')
        root_filename = root_meta.get('file') if root_meta else 'content.md'
        require(root_filename is not None, 'Existing frontmatter main TODO needs an explicit layout conversion plan')
        add(main_todo_id(project_id), root_filename, body.encode('utf-8'), 'main-todo', 'Roadmapa projektu', root_meta=root_meta)
        entities = validate_snapshot(files)
        graph = project_task_graph(files, entities, project_id, '0' * 40)
        require(graph['status'] == 'ready', 'Assembled task graph is invalid: ' + graph.get('error', 'unknown'))
        expected = {(n['id'], n['type'], n['parent_id'], n['checked']) for n in project['graph']['nodes']}
        actual = {(n['id'], n['type'], n['parent_id'], n['checked']) for n in graph['nodes']}
        require(expected == actual, 'Assembly changed the mapped plan')
        context = dict(mapping_sha256=mapping['mapping_sha256'], project_id=project_id,
                       author_id=author_id, created_at=created_at, privacy=privacy)
        operation_id = str(uuid5(UUID(project_id), digest(canonical(context))))
        preview = project.get('target_preview')
        declaration = next((json.loads(raw[s['key']]) for s in own_sources if s['role'] == 'module-manifest'), {})
        project_title = declaration.get('display_name', scope)
        target_location = target_locations.get(scope)
        require(target_location is None or (isinstance(target_location, str) and target_location.startswith('/')),
                'Target location must be an absolute path')
        require(preview is None or target_location is None, 'Existing registered project does not accept a target location')
        projects.append(dict(repository_id=scope, project_id=project_id, operation_id=operation_id,
                             payload_directory='payload/' + scope,
                             mode='replace-test-plan' if preview else 'create-seeded-project',
                             expected_head=preview['expected_head'] if preview else None,
                             target_location=target_location,
                             location_resolution='registered-project' if preview else
                             ('explicit' if target_location else 'required-before-create'),
                             project_metadata_proposal=None if preview else dict(schema_version=1, id=project_id,
                                 title=project_title, created_at=created_at, author_id=author_id),
                             privacy_proposal=privacy, preserve_unlisted_entities=True, deletions=[],
                             files=sorted(entries, key=lambda entry: entry['path']),
                             artifacts=artifact_roles, related_projects=related,
                             validation=dict(metadata_shape='passed', task_graph='passed',
                                             complete_prewrite_gate='not-run'),
                             summary=dict(artifacts=len(entities), files=len(files), bytes=sum(map(len, files.values())),
                                          node_types=dict(sorted(Counter(n['type'] for n in graph['nodes']).items())))))
    operation = dict(schema=SCHEMA, stage='assembled', prepared_at=created_at, prepared_by=author_id,
                     inventory_sha256=value['inventory_sha256'], mapping_sha256=mapping['mapping_sha256'],
                     projects=projects, project_write_performed=False, import_ready=False,
                     transaction_boundary='one Workspace transaction per project; no cross-project atomicity',
                     pending_checks=['live target HEAD and authorization', 'privacy classification review',
                                     'full candidate merge and path collisions', 'source-link reconciliation',
                                     'new project location', 'journal recovery and idempotent writer'])
    module_operations = [p['operation_id'] for p in projects if p['repository_id'] != 'federated-workspace']
    for project in projects:
        project['depends_on_operations'] = module_operations if project['repository_id'] == 'federated-workspace' else []
    operation['bundle_sha256'] = digest(canonical(operation))
    return operation, blobs


def write_bundle(output, operation, blobs):
    """A new private directory; manifest is published last, never an import receipt."""
    require(operation.get('schema') == SCHEMA and operation.get('stage') == 'assembled', 'Unsupported import package')
    payload = {key: value for key, value in operation.items() if key != 'bundle_sha256'}
    require(operation['bundle_sha256'] == digest(canonical(payload)), 'Package manifest digest differs')
    referenced = set()
    for project in operation['projects']:
        project_files(project, blobs)
        require(safe_path(project['payload_directory']) == ['payload', project['repository_id']],
                'Invalid payload directory')
        referenced.update(entry['sha256'] for entry in project['files'])
    require(referenced == set(blobs), 'Unreferenced or missing package blobs')
    output = Path(output)
    output.mkdir(mode=0o700)
    (output / 'blobs').mkdir(mode=0o700)
    for key, raw in sorted(blobs.items()):
        require(digest(raw) == key, 'Bundle blob hash differs')
        (output / 'blobs' / key).write_bytes(raw)
    for project in operation['projects']:
        for relative, raw in project_files(project, blobs).items():
            path = output / project['payload_directory'] / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)
    lines = ['# Připravený importní balík', '', 'Stav: assembled. Do projektu nebylo zapsáno.', '',
             f'Bundle SHA-256: `{operation["bundle_sha256"]}`', '',
             '| Projekt | Režim | Artefakty | Soubory | Bajty |', '| --- | --- | ---: | ---: | ---: |']
    for project in operation['projects']:
        s = project['summary']
        root = next(entry for entry in project['files'] if entry['role'] == 'main-todo')
        link = project['payload_directory'] + '/' + root['path']
        lines.append(f'| [{project["repository_id"]}]({link}) | {project["mode"]} | {s["artifacts"]} | {s["files"]} | {s["bytes"]} |')
    lines += ['', 'operation.json obsahuje přesné cesty, ID, metadata a odkazy na blobs/<sha256>.',
              'Závěrečná předzápisová validace a samotný zápis/recovery nejsou součástí tohoto balíku.', '']
    (output / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    # Source data can be regenerated if preparation is interrupted. Only a
    # fully written operation.json describes a complete assembled package.
    temporary = output / 'operation.json.tmp'
    temporary.write_bytes(encoded(operation))
    temporary.replace(output / 'operation.json')
