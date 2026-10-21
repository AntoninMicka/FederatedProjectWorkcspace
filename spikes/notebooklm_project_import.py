# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Plan and atomically create one project from a personal NotebookLM Takeout."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid5

from spikes.metadata import require, timestamp, uuid, validate_snapshot
from spikes.notebooklm_import import NotebookLMTakeout, PARSER_REVISION
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


IMPORTER = {'name': 'notebooklm-takeout-import', 'version': '1'}
PLAN_FORMAT = 'notebooklm-project-import-plan-v1'
PRIVACY = {'public', 'project', 'confidential', 'local-only'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def normalized_timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def artifact_id(operation_id, role, source_path):
    return str(uuid5(UUID(operation_id), f'notebooklm:{role}:{source_path}'))


def artifact_specs(preview, operation_id):
    specs = []
    for source in preview['sources']:
        specs.append({'id': artifact_id(operation_id, 'source', source['content_path']),
                      'role': 'source', 'title': source['title'],
                      'content_path': source['content_path'],
                      'metadata_path': source['metadata_path'],
                      'source_created_at': normalized_timestamp(source['source_created_at']),
                      'representation': source['representation']})
    for item in preview['artifacts']:
        specs.append({'id': artifact_id(operation_id, 'generated-output', item['content_path']),
                      'role': 'generated-output', 'title': item['title'],
                      'content_path': item['content_path'],
                      'metadata_path': item['metadata_path'], 'representation': 'md'})
    for number, item in enumerate(preview['chats'], 1):
        specs.append({'id': artifact_id(operation_id, 'chat', item['path']),
                      'role': 'chat', 'title': f'NotebookLM chat {number}',
                      'content_path': item['path'], 'representation': 'html'})
    for number, item in enumerate(preview['discovered_sources'], 1):
        specs.append({'id': artifact_id(operation_id, 'discovered-sources', item['path']),
                      'role': 'discovered-sources',
                      'title': f'NotebookLM discovered sources {number}',
                      'content_path': item['path'], 'representation': 'json'})
    for role, title in (('export-metadata', 'NotebookLM export metadata'),
                        ('import-report', 'NotebookLM import report')):
        specs.append({'id': artifact_id(operation_id, role, role), 'role': role,
                      'title': title, 'representation': 'json' if role == 'export-metadata' else 'md'})
    return specs


class NotebookLMProjectImport:
    def __init__(self, node_path):
        self.node_path = Path(node_path).absolute()

    def preview(self, archive_path):
        return NotebookLMTakeout(archive_path).preview()

    def plan(self, archive_path, selection_digest, target_root, privacy, operation_id,
             *, imported_at=None):
        uuid(operation_id)
        require(privacy in PRIVACY, 'Invalid import privacy')
        root = Path(target_root).absolute()
        preview = self.preview(archive_path)
        matches = [item for item in preview['notebooks']
                   if item['selection_digest'] == selection_digest]
        require(len(matches) == 1, 'NotebookLM selection is missing or ambiguous')
        require(matches[0]['importable'], 'NotebookLM selection contains unsupported data')
        when = imported_at or datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        timestamp(when, 'imported_at')
        return self._plan(preview, matches[0], root, privacy, operation_id, when)

    def _plan(self, bundle, notebook, root, privacy, operation_id, imported_at):
        project_id = str(uuid5(UUID(operation_id), 'notebooklm-project'))
        value = {
            'format': PLAN_FORMAT, 'parser_revision': PARSER_REVISION,
            'operation_id': operation_id, 'archive_sha256': bundle['archive_sha256'],
            'archive_size': bundle['archive_size'],
            'selection_digest': notebook['selection_digest'],
            'notebook_folder': notebook['folder'], 'title': notebook['title'],
            'target_root': str(root), 'privacy': privacy, 'imported_at': imported_at,
            'project_id': project_id,
            'artifacts': artifact_specs(notebook, operation_id),
            'warnings': notebook['warnings'], 'unsupported': notebook['unsupported'],
            'existing_imports': self._duplicates(notebook['selection_digest'], project_id),
        }
        value['request_digest'] = digest(value)
        return value

    def _duplicates(self, selection_digest, exclude_project_id):
        matches = []
        projects = Projects(self.node_path)
        for row in projects.catalog():
            if not row['available'] or row['id'] == exclude_project_id:
                continue
            try:
                workspace = projects.workspace(row['id'])
                head = workspace.git.head(); files = workspace.git.snapshot(head)
                entities = validate_snapshot(files)
                for identity, meta in entities.items():
                    if meta['kind'] != 'snapshot' or 'export-metadata' not in meta.get('tags', []):
                        continue
                    raw = files[f'artifacts/{identity}/{meta["file"]}']
                    value = json.loads(raw.decode('utf-8'))
                    if value.get('format') == 'notebooklm-export-metadata-envelope-v1' \
                            and value.get('selection_digest') == selection_digest:
                        matches.append({'project_id': row['id'], 'title': row['title']})
                        break
            except (ValueError, OSError, KeyError, UnicodeError, json.JSONDecodeError, RecursionError):
                continue
        return sorted(matches, key=lambda item: item['project_id'])

    def confirm(self, archive_path, plan, *, author_id=None, checkpoint=lambda stage: None):
        required = {'format', 'parser_revision', 'operation_id', 'archive_sha256',
                    'archive_size', 'selection_digest', 'notebook_folder', 'title',
                    'target_root', 'privacy', 'imported_at', 'project_id', 'artifacts',
                    'warnings', 'unsupported', 'existing_imports', 'request_digest'}
        require(isinstance(plan, dict) and set(plan) == required, 'Invalid NotebookLM import plan')
        supplied = dict(plan); supplied_digest = supplied.pop('request_digest')
        require(digest(supplied) == supplied_digest, 'NotebookLM import plan changed after preview')
        creator = ProjectCreation(self.node_path)
        resumed = creator.resume_seeded(
            plan['title'], plan['target_root'], plan['operation_id'], plan['project_id'],
            plan['request_digest'], checkpoint=checkpoint)
        if resumed is not None:
            return resumed
        materialized = NotebookLMTakeout(archive_path).materialize(
            plan['archive_sha256'], plan['selection_digest'])
        preview = materialized['preview']
        bundle = {'archive_sha256': materialized['archive_sha256'],
                  'archive_size': materialized['archive_size']}
        expected = self._plan(bundle, preview, Path(plan['target_root']), plan['privacy'],
                              plan['operation_id'], plan['imported_at'])
        require(expected == plan, 'NotebookLM import plan no longer matches the export')
        author = author_id or creator.author_id()
        uuid(author)
        files = self._snapshot(plan, preview, materialized['members'], author)
        return creator.create(
            plan['title'], plan['target_root'], plan['operation_id'], initial_files=files,
            project_id=plan['project_id'], created_at=plan['imported_at'],
            request_digest=plan['request_digest'], commit_message='Import NotebookLM project',
            checkpoint=checkpoint)

    @staticmethod
    def _snapshot(plan, preview, members, author):
        files, consumed, metadata_paths = {}, set(), []
        for item in plan['artifacts']:
            if item['role'] in {'export-metadata', 'import-report'}:
                continue
            source_path = item['content_path']
            raw = members[source_path]
            consumed.add(source_path)
            if 'metadata_path' in item:
                metadata_paths.append(item['metadata_path'])
                consumed.add(item['metadata_path'])
            suffix = '.' + item['representation']
            filename = item['role'] + suffix
            provenance = {'imported_at': plan['imported_at'], 'imported_by': author,
                          'content_sha256': hashlib.sha256(raw).hexdigest(),
                          'importer': IMPORTER}
            if 'source_created_at' in item:
                provenance['source_created_at'] = item['source_created_at']
            if 'metadata_path' in item:
                provenance['source_revision'] = hashlib.sha256(
                    members[item['metadata_path']]).hexdigest()
            NotebookLMProjectImport._add_source(
                files, item['id'], filename, raw, item['title'], item['role'],
                plan['privacy'], plan['imported_at'], author, provenance)

        root_metadata = [path for path in members
                         if path not in consumed and PurePosixPath(path).parent.name == preview['folder']]
        require(len(root_metadata) == 1, 'NotebookLM notebook metadata is missing or ambiguous')
        metadata_paths.append(root_metadata[0]); consumed.add(root_metadata[0])
        envelope = {'format': 'notebooklm-export-metadata-envelope-v1',
                    'archive_sha256': plan['archive_sha256'],
                    'selection_digest': plan['selection_digest'],
                    'parser_revision': plan['parser_revision'],
                    'records': [{'path': path, 'sha256': hashlib.sha256(members[path]).hexdigest(),
                                 'base64': base64.b64encode(members[path]).decode('ascii')}
                                for path in sorted(metadata_paths)],
                    'member_manifest': [{'path': path, 'size': len(raw),
                                         'sha256': hashlib.sha256(raw).hexdigest()}
                                        for path, raw in sorted(members.items())],
                    'artifact_mapping': [{'artifact_id': item['id'], 'role': item['role'],
                                          'content_path': item.get('content_path')}
                                         for item in plan['artifacts']],
                    'warnings': preview['warnings'],
                    'unresolved_artifact_source_references': sum(
                        item['source_reference_count'] for item in preview['artifacts'])}
        envelope_raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        envelope_item = next(item for item in plan['artifacts'] if item['role'] == 'export-metadata')
        NotebookLMProjectImport._add_snapshot(
            files, envelope_item['id'], 'export-metadata.json', envelope_raw,
            envelope_item['title'], 'export-metadata', plan['privacy'], plan['imported_at'], author,
            'Odvozená obálka; pole base64 zachovávají přesné bajty exportovaných metadat.')
        report = NotebookLMProjectImport._report(preview).encode('utf-8')
        report_item = next(item for item in plan['artifacts'] if item['role'] == 'import-report')
        NotebookLMProjectImport._add_snapshot(
            files, report_item['id'], 'import-report.md', report,
            report_item['title'], 'import-report', plan['privacy'], plan['imported_at'], author,
            'Odvozený soupis importovaných a nedostupných částí; nejde o původní obsah NotebookLM.')
        require(consumed == set(members), 'NotebookLM export contains unaccounted members')
        return files

    @staticmethod
    def _add_source(files, identity, filename, raw, title, role, privacy, created, author, provenance):
        meta = {'schema_version': 2, 'id': identity, 'title': title, 'kind': 'source',
                'created_at': created, 'author_id': author, 'privacy': privacy,
                'provenance': 'external', 'file': filename, 'tags': ['notebooklm', role],
                'description': 'Přesná importovaná reprezentace z osobního Google Takeout.',
                'import': provenance}
        prefix = f'artifacts/{identity}/'
        files[prefix + filename] = raw
        files[prefix + 'metadata.json'] = (
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

    @staticmethod
    def _add_snapshot(files, identity, filename, raw, title, role, privacy, created, author, description):
        meta = {'schema_version': 1, 'id': identity, 'title': title, 'kind': 'snapshot',
                'created_at': created, 'author_id': author, 'privacy': privacy,
                'provenance': 'snapshot', 'file': filename,
                'tags': ['notebooklm', role], 'description': description}
        prefix = f'artifacts/{identity}/'
        files[prefix + filename] = raw
        files[prefix + 'metadata.json'] = (
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

    @staticmethod
    def _report(preview):
        return (
            '# Přehled importu NotebookLM\n\n'
            f'- Zdroje: {len(preview["sources"])}\n'
            f'- Generované výstupy: {len(preview["artifacts"])}\n'
            f'- Historie chatu: {len(preview["chats"])}\n'
            f'- Nalezené zdroje: {len(preview["discovered_sources"])}\n'
            '- Samostatné poznámky: v exportu nebyly nalezeny.\n'
            '- Zdrojové HTML/JSON je reprezentace Takeoutu, nikoli původní PDF, obrázek nebo Google dokument.\n'
            '- Odkazy generovaných výstupů na source UUID nebyly propojeny, protože exportované zdroje nemají doložená ID.\n'
            '- HTML bylo uloženo jako data a během importu se nespouštělo.\n')
