# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed, read-only validation of an assembled roadmap import bundle."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from spikes.configuration import local_path, overlap, parse_node, parse_project, read_config
from spikes.administration import Administration
from spikes.metadata import MAX_FILE, parse_json, require, safe_path, uuid, validate_snapshot, validate_transition
from spikes.project_creation import ProjectCreation, regular
from spikes.projects import Projects
from spikes.roadmap_bundle import SCHEMA, digest, project_files
from spikes.roadmap_migration import canonical, LINK, visible_markdown_lines
from spikes.task_graph import project_task_graph

SHA256 = re.compile(r'[0-9a-f]{64}')
GIT_HEAD = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
URL = re.compile(r'[a-zA-Z][a-zA-Z0-9+.-]*://')


def _result(code, status, detail, **evidence):
    return dict(code=code, status=status, detail=detail, evidence=evidence)


def load_bundle(root):
    """Load only a complete content-addressed bundle and reject loose data."""
    root = Path(root).resolve(strict=True)
    operation_raw = (root / 'operation.json').read_bytes()
    require(len(operation_raw) <= MAX_FILE, 'Operation manifest exceeds limit')
    operation = parse_json(operation_raw, MAX_FILE)
    require(operation.get('schema') == SCHEMA and operation.get('stage') == 'assembled',
            'Unsupported import package')
    claimed = operation.get('bundle_sha256')
    require(isinstance(claimed, str) and SHA256.fullmatch(claimed), 'Invalid package digest')
    unsigned = {key: value for key, value in operation.items() if key != 'bundle_sha256'}
    require(claimed == digest(canonical(unsigned)), 'Package manifest digest differs')
    require(operation.get('project_write_performed') is False and operation.get('import_ready') is False,
            'Review accepts only an unapplied assembled package')
    blob_root = root / 'blobs'
    require(blob_root.is_dir() and not blob_root.is_symlink(), 'Bundle blob directory is unavailable')
    blobs = {}
    for path in blob_root.iterdir():
        require(path.is_file() and not path.is_symlink() and SHA256.fullmatch(path.name),
                'Invalid bundle blob entry')
        raw = path.read_bytes()
        require(len(raw) <= MAX_FILE and hashlib.sha256(raw).hexdigest() == path.name,
                'Bundle blob differs from its name')
        blobs[path.name] = raw
    referenced, project_ids, operation_ids = set(), set(), set()
    for project in operation.get('projects', []):
        uuid(project['project_id']); uuid(project['operation_id'])
        require(project['project_id'] not in project_ids and project['operation_id'] not in operation_ids,
                'Duplicate project or operation identity')
        project_ids.add(project['project_id']); operation_ids.add(project['operation_id'])
        files = project_files(project, blobs)
        referenced.update(entry['sha256'] for entry in project['files'])
        payload = root.joinpath(*safe_path(project['payload_directory']))
        for relative, raw in files.items():
            mirror = payload.joinpath(*safe_path(relative))
            require(mirror.is_file() and not mirror.is_symlink() and mirror.read_bytes() == raw,
                    'Human-readable payload mirror differs from blob data')
    require(referenced == set(blobs), 'Unreferenced or missing package blobs')
    require(all(set(project.get('depends_on_operations', [])) <= operation_ids
                and project['operation_id'] not in project.get('depends_on_operations', [])
                for project in operation['projects']), 'Invalid operation dependency')
    return operation, blobs


def _actor(node):
    database = ProjectCreation(node).database
    regular(database)
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        rows = connection.execute('SELECT id FROM local_author').fetchall()
    require(len(rows) == 1, 'Expected one durable local author')
    uuid(rows[0][0])
    return rows[0][0]


def _journal_state(binding):
    database = Path(binding['state_dir']) / 'journal.sqlite'
    if not database.exists():
        return {'present': False, 'pending_files': 0, 'unfinished_operations': 0}
    regular(database)
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        owner = connection.execute('SELECT root FROM owner').fetchall()
        pending = connection.execute('SELECT count(*) FROM pending').fetchone()[0]
        unfinished = connection.execute('SELECT count(*) FROM operations WHERE done=0').fetchone()[0]
    require(owner == [(str(Path(binding['root']).resolve()),)], 'Journal owner differs from project root')
    return {'present': True, 'pending_files': pending, 'unfinished_operations': unfinished}


def _links(files, project):
    artifacts = project['artifacts']
    generated_roles = {'main-todo', 'free-description', 'module-links'}
    paths = set(files)
    relative, broken_artifact, external = [], [], []
    for entry in project['files']:
        if entry['role'] == 'metadata' or entry['artifact_role'] not in generated_roles or not entry['path'].endswith('.md'):
            continue
        raw = files[entry['path']]
        for line_no, _, _, line, _ in visible_markdown_lines(raw):
            for target in LINK.findall(line):
                target = target.strip().strip('<>')
                destination = target.split('#', 1)[0]
                if not destination or target.startswith('#'):
                    continue
                if URL.match(target):
                    external.append({'path': entry['path'], 'line': line_no, 'target': target})
                elif destination.startswith('artifacts/'):
                    if destination not in paths:
                        broken_artifact.append({'path': entry['path'], 'line': line_no, 'target': target})
                else:
                    relative.append({'path': entry['path'], 'line': line_no, 'target': target})
    return relative, broken_artifact, external


def _new_location(project, location, node, source_roots):
    if location is None:
        return _result('new-project-location', 'blocked', 'Nový modulový projekt nemá zvolenou fyzickou cestu.')
    path = local_path(str(location))
    state = path.parent / ('.workspace-state-' + project['project_id'])
    config = parse_node(read_config(node), location=node)
    protected = [Path(node).resolve(), ProjectCreation(node).runtime.resolve()]
    for binding in config['projects']:
        protected.extend([Path(binding['root']).resolve(), Path(binding['state_dir']).resolve()])
    protected.extend(Path(item).resolve() for item in source_roots)
    require(not any(overlap(path, item) or overlap(state, item) for item in protected),
            'New project or state path overlaps protected data')
    require(not os.path.lexists(path) and not os.path.lexists(state),
            'New project or state path already exists')
    require(path.parent.is_dir() and os.access(path.parent, os.W_OK), 'New project parent is not writable')
    parse_project((json.dumps(project['project_metadata_proposal']) + '\n').encode())
    return _result('new-project-location', 'passed', 'Cesta a odpovídající state adresář jsou volné.',
                   root=str(path), state_dir=str(state))


def validate_bundle(bundle, node, *, locations=None, source_privacy=None, source_roots=()):
    """Validate current live context without constructing Workspace or Journal."""
    operation, blobs = load_bundle(bundle)
    node = Path(node).resolve(strict=True)
    config = parse_node(read_config(node), location=node)
    bindings = {row['project_id']: row for row in config['projects']}
    locations = locations or {}; source_privacy = source_privacy or {}
    require(set(locations) <= {project['repository_id'] for project in operation['projects']},
            'Location supplied for an unknown scope')
    source_keys = set()
    for project in operation['projects']:
        incoming = project_files(project, blobs)
        for path in incoming:
            if path.endswith('/sources.json'):
                source_keys.update(item['key'] for item in parse_json(incoming[path])['sources'])
    require(set(source_privacy) <= source_keys
            and all(value in {'public', 'project', 'confidential', 'local-only'}
                    for value in source_privacy.values()), 'Invalid source privacy classification')
    results = [_result('bundle-integrity', 'passed', 'Manifest, blobs a payload mirror jsou shodné.',
                       bundle_sha256=operation['bundle_sha256'])]
    actor = _actor(node)
    results.append(_result('local-author', 'passed' if actor == operation['prepared_by'] else 'blocked',
                           'Připravující identita odpovídá lokálnímu autorovi.' if actor == operation['prepared_by']
                           else 'Připravující identita neodpovídá lokálnímu autorovi.'))
    privacy_order = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
    for project in operation['projects']:
        scope = project['repository_id']; incoming = project_files(project, blobs)
        prefix = scope + ':'
        manifests = [raw for path, raw in incoming.items() if project['artifacts'][path.split('/')[1]]['role'] == 'source-manifest'
                     and path.endswith('/sources.json')]
        sources = parse_json(manifests[0])['sources'] if len(manifests) == 1 else []
        missing_privacy = [item['key'] for item in sources if item['key'] not in source_privacy]
        too_private = [item['key'] for item in sources if item['key'] in source_privacy
                       and privacy_order[source_privacy[item['key']]] > privacy_order[project['privacy_proposal']]]
        if missing_privacy:
            results.append(_result(prefix+'source-privacy', 'needs-review',
                                   'Zdrojové soubory nemají potvrzenou privacy klasifikaci.', count=len(missing_privacy), keys=missing_privacy))
        elif too_private:
            results.append(_result(prefix+'source-privacy', 'blocked',
                                   'Navržená privacy projektu je nižší než privacy zdroje.', keys=too_private))
        else:
            results.append(_result(prefix+'source-privacy', 'passed', 'Privacy obálka pokrývá všechny zdroje.'))
        relative, broken, external = _links(incoming, project)
        if relative or broken:
            results.append(_result(prefix+'source-links', 'blocked',
                                   'Odvozené dokumenty obsahují nepřevedené nebo neexistující odkazy.',
                                   relative_count=len(relative), broken_artifact_count=len(broken),
                                   relative_targets=sorted({row['target'] for row in relative}), examples=(relative+broken)[:20]))
        else:
            results.append(_result(prefix+'source-links', 'passed', 'Interní odkazy v odvozených dokumentech jsou uzavřené.'))
        results.append(_result(prefix+'external-links', 'needs-review' if external else 'passed',
                               'Externí odkazy nebyly síťově ověřeny.' if external else 'Odvozené dokumenty nemají externí odkazy.', count=len(external)))
        if project['mode'] == 'create-seeded-project':
            entities = validate_snapshot(incoming)
            graph = project_task_graph(incoming, entities, project['project_id'], '0' * 40)
            require(graph['status'] == 'ready', graph.get('error', 'Invalid new project graph'))
            results.append(_result(prefix+'full-candidate', 'passed', 'Seed snapshot a task graph jsou validní.', files=len(incoming)))
            results.append(_new_location(project, locations.get(scope), node, source_roots))
            continue
        git = Projects(node).repository(project['project_id'])
        administration = Administration(node, deployment='desktop')
        read_only = False
        if administration.repo.exists():
            with administration.read_locked() as state:
                replication = next((row for row in state['replications']
                                    if row['spec']['project_id'] == project['project_id']
                                    and not row['revocation']), None)
                if replication:
                    local = next(item for item in replication['spec']['nodes']
                                 if item['node_id'] == state['node_id'])
                    read_only = local['role'] == 'read-only-replica'
        results.append(_result(prefix+'native-write-authority', 'blocked' if read_only else 'passed',
                               'Projekt je na tomto uzlu read-only replica.' if read_only
                               else 'Nativní replica policy nezakazuje lokální zápis.'))
        head = git.head()
        status = git.run('status', '--porcelain=v1', env_extra={'GIT_OPTIONAL_LOCKS': '0'}).stdout
        unmerged = git.run('ls-files', '-u').stdout
        branch = git.run('symbolic-ref', '-q', 'HEAD', check=False)
        context_ok = head == project['expected_head'] and not status and not unmerged and branch.returncode == 0
        results.append(_result(prefix+'live-git-context', 'passed' if context_ok else 'blocked',
                               'Živý Git odpovídá připnutému čistému HEAD.' if context_ok else 'Živý Git se liší od připnutého kontextu.',
                               expected_head=project['expected_head'], observed_head=head,
                               dirty=bool(status), unmerged=bool(unmerged), detached=branch.returncode != 0))
        journal = _journal_state(bindings[project['project_id']])
        idle = not journal['pending_files'] and not journal['unfinished_operations']
        results.append(_result(prefix+'journal', 'passed' if idle else 'blocked',
                               'Journal nemá rozpracovanou operaci.' if idle else 'Journal obsahuje rozpracovanou operaci.', **journal))
        base = git.snapshot(head); candidate = dict(base)
        collision = []
        for entry in project['files']:
            path = entry['path']; raw = incoming[path]
            if entry['action'] == 'create' and path in base and base[path] != raw:
                collision.append(path)
            elif entry['action'] == 'replace' and path not in base:
                collision.append(path)
            candidate[path] = raw
        if collision:
            results.append(_result(prefix+'full-candidate', 'blocked', 'Akce payloadu kolidují s živým snapshotem.', paths=collision))
        else:
            entities = validate_transition(base, candidate)
            graph = project_task_graph(candidate, entities, project['project_id'], head)
            require(graph['status'] == 'ready', graph.get('error', 'Invalid merged task graph'))
            results.append(_result(prefix+'full-candidate', 'passed',
                                   'Celý sloučený snapshot, přechod metadat a task graph jsou validní.',
                                   preserved_files=len(set(base)-set(incoming)), candidate_files=len(candidate)))
    blocking = [row for row in results if row['status'] == 'blocked']
    review = [row for row in results if row['status'] == 'needs-review']
    return dict(schema='fpw-roadmap-prewrite-review-v1', bundle_sha256=operation['bundle_sha256'],
                project_write_performed=False, checks=results,
                summary=dict(passed=sum(row['status'] == 'passed' for row in results),
                             blocked=len(blocking), needs_review=len(review)),
                prewrite_checks_passed=not blocking and not review,
                import_ready=False,
                remaining_gate='Writer, journal recovery and idempotent apply are not implemented.')
