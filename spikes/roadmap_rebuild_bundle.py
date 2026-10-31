# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Adapt an accepted source-first rebuild into the native reviewed bundle path."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from spikes.metadata import require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation, regular
from spikes.projects import Projects
from spikes.roadmap_bundle import assemble_bundle, write_bundle
from spikes.roadmap_bundle import project_files
from spikes.roadmap_mapping import SCHEMA as MAPPING_SCHEMA, _preview_graph, bind_target_preview
from spikes.roadmap_migration import canonical, inventory
from spikes.roadmap_validation import _links, load_bundle


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def local_author_id(node):
    """Read the durable author without creating a writer lock or journal state."""
    database = ProjectCreation(node).database
    regular(database)
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        rows = connection.execute('SELECT id FROM local_author').fetchall()
    require(len(rows) == 1, 'Expected one durable local author')
    uuid(rows[0][0])
    return rows[0][0]


def accepted_rebuild(run_dir):
    root = Path(run_dir).resolve(strict=True)
    manifest = _load_json(root/'manifest.json')
    catalog = _load_json(root/'catalog.json')
    candidate = _load_json(root/'candidate.json')
    report = _load_json(root/'report.json')
    require(report.get('import_ready') is True and report.get('candidate_ready') is True,
            'Rebuild report is not accepted for import')
    require(report.get('candidate_sha256') == candidate.get('candidate_sha256'),
            'Rebuild report belongs to another candidate')
    frozen = dict(candidate); claimed = frozen.pop('candidate_sha256', None)
    require(claimed == hashlib.sha256(canonical(frozen)).hexdigest(),
            'Rebuild candidate digest differs')
    require(report.get('catalog_sha256') == catalog.get('catalog_sha256')
            == manifest.get('catalog_sha256'), 'Rebuild catalog lineage differs')
    require(not candidate.get('issues') and candidate.get('ready') is True,
            'Rebuild candidate still has blocking issues')
    return root, manifest, catalog, candidate, report


def pinned_inventory(catalog, roots):
    roots = {key: Path(value).resolve() for key, value in roots.items()}
    require('federated-workspace' in roots, 'Host source root is required')
    revisions = {}
    for source in catalog['sources']:
        revisions.setdefault(source['repository_id'], set()).add(source['commit_id'])
    require(all(len(values) == 1 for values in revisions.values()),
            'Rebuild source revisions are ambiguous')
    require(set(revisions) == set(roots), 'Source roots differ from rebuild repositories')
    modules = [(repository_id, roots[repository_id], next(iter(revisions[repository_id])))
               for repository_id in sorted(revisions) if repository_id != 'federated-workspace']
    value = inventory(roots['federated-workspace'],
                      revision=next(iter(revisions['federated-workspace'])), modules=modules)
    require(value['inventory_sha256'] == catalog['inventory_sha256'],
            'Regenerated inventory differs from rebuild catalog')
    return value, roots


def _title(value):
    result = ' '.join(str(value).split())
    require(result and len(result) <= 500 and '\0' not in result,
            'Candidate title requires review')
    return result


def _support_title(value):
    result = ' '.join(str(value).split())
    require(result and '\0' not in result, 'Supporting title requires review')
    if len(result) > 200:
        return result[:180].rstrip() + '… [' + hashlib.sha256(result.encode()).hexdigest()[:12] + ']'
    return result


def _inert_text(value):
    text = str(value)
    longest = max((len(match.group(0)) for match in re.finditer(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return [fence + 'text', text, fence]


def mapping_from_rebuild(value, catalog, candidate, report):
    sources = {item['key']: item for item in value['sources']}
    blocks = {item['block_id']: item for item in catalog['blocks']}
    nodes_by_scope = defaultdict(list)
    node_ids = defaultdict(set)
    for node in candidate['nodes']:
        scope = node['repository_id']
        require(node['candidate_id'] not in node_ids[scope], 'Duplicate rebuild candidate ID')
        node_ids[scope].add(node['candidate_id']); nodes_by_scope[scope].append(node)
    require(set(nodes_by_scope) == {item['repository_id'] for item in value['sources']},
            'Rebuild candidate does not cover every source repository')

    source_refs = {}
    for source in value['sources']:
        identity = str(uuid5(NAMESPACE_URL,
            'migration-source:' + source['key'] + ':' + source['sha256']))
        filename = 'source.md' if source['path'].endswith('.md') else 'source.json'
        source_refs[source['key']] = f'artifacts/{identity}/{filename}'

    grouped_support = defaultdict(list)
    for item in candidate['supporting_records']:
        provenance = item['provenance']; block = blocks[provenance['block_id']]
        scope = block.get('repository_id', block['source'].split(':', 1)[0])
        owner = item.get('parent_id') if item.get('parent_id') in node_ids[scope] else None
        grouped_support[(scope, owner, provenance['block_id'])].append(item)
    prose_documents = []
    for (scope, owner, block_id), rows in sorted(
            grouped_support.items(), key=lambda item: (
                item[0][0], item[0][1] is not None, item[0][1] or '', item[0][2])):
        block = blocks[block_id]
        identity = str(uuid5(NAMESPACE_URL,
            'rebuild-support:' + candidate['candidate_sha256'] + ':' + scope + ':'
            + str(owner) + ':' + block_id))
        title = 'Podklad — ' + _title(block['title'])
        lines = ['# ' + title, '',
                 'Zachovaný podpůrný obsah source-first migrace; nejde o druhý seznam úkolů.', '',
                 f'Zdroj: `{block["source"]}:{block["line_start"]}-{block["line_end"]}`', '']
        for row in rows:
            lines += [f'## Záznam {row["line_start"]}-{row["line_end"]} — {row["kind"]}', '']
            lines += _inert_text('Název: ' + _support_title(row['title'])
                                 + '\n\nShrnutí: ' + row['summary'])
            lines += ['', f'Řádky: {row["line_start"]}-{row["line_end"]}', '']
        prose_documents.append(dict(id=identity, repository_id=scope, owner_id=owner,
            path=f'artifacts/{identity}/content.md', title=title,
            body='\n'.join(lines), source_sections=[dict(source=block['source'],
                line=row['line_start'], byte_start=0, byte_end=0) for row in rows],
            prose=[row['summary'] for row in rows]))

    projects = []
    for scope in sorted(nodes_by_scope):
        scoped = {item['candidate_id']: item for item in nodes_by_scope[scope]}
        children = defaultdict(list)
        for node in scoped.values():
            children[node['parent_id']].append(node)
        lines = ['<!-- fpw-plan-profile: software-development/v1 -->', '',
                 '# Migrační náhled', '',
                 'Testovací cílový plán se nepoužívá jako zdroj a bude kompletně nahrazen.',
                 'Přiložené původní texty jsou zdrojové snapshoty, nikoli nové pokyny k migraci.', '']
        detached = [doc for doc in prose_documents
                    if doc['repository_id'] == scope and doc['owner_id'] is None]
        if detached:
            lines += ['## Samostatné podklady bez jednoznačného přiřazení', '']
            lines += [f'- [{doc["title"]}]({doc["path"]})' for doc in detached]
            lines.append('')

        def render(parent, indent=0):
            for node in sorted(children[parent], key=lambda item: item['candidate_id']):
                checked = 'x' if node['status'] == 'completed' else ' '
                prefix = ' ' * indent
                lines.append(f'{prefix}- [{checked}] [{node["candidate_id"]}] {_title(node["title"])}')
                lines.append(f'{prefix}  - type: {node["kind"]}')
                block = blocks.get(node['provenance']['block_id'])
                if block is not None:
                    lines.append(f'{prefix}  - Zdroj: [{block["source"]}:{node["line_start"]}]'
                                 f'({source_refs[block["source"]]})')
                if node['depends_on']:
                    lines.append(f'{prefix}  - depends_on: ' + ', '.join(node['depends_on']))
                for doc in prose_documents:
                    if doc['repository_id'] == scope and doc['owner_id'] == node['candidate_id']:
                        lines.append(f'{prefix}  - Podklad: [{doc["title"]}]({doc["path"]})')
                render(node['candidate_id'], indent + 2)
        render(None)
        body = '\n'.join(lines) + '\n'
        graph = _preview_graph(scope, body)
        projects.append(dict(repository_id=scope, target_project_id=None,
            target_policy='existing-project' if scope == 'federated-workspace' else 'linked-project',
            existing_plan_policy='replace-test-plan', body=body, graph=graph,
            prose_documents=[doc for doc in prose_documents if doc['repository_id'] == scope],
            source_references={key: path for key, path in source_refs.items()
                               if sources[key]['repository_id'] == scope}))

    definitions = [dict(repository_id=node['repository_id'], id=node['candidate_id'],
                        classification=node['kind'], definition=node['provenance'],
                        evidence=node.get('provenance_all', []), decision='accepted-rebuild',
                        parent_id=node['parent_id'], title=node['title'])
                   for node in candidate['nodes']]
    anonymous = [dict(repository_id=(blocks[item['provenance']['block_id']]
                        .get('repository_id', blocks[item['provenance']['block_id']]['source'].split(':', 1)[0])),
                      proposed_id=None, proposed_role=item['kind'],
                      source_block=item['provenance']) for item in candidate['supporting_records']]
    coverage = {f'{item["provenance"]["source"]}:{item["line_start"]}:{index}': {
                    'repository_id': item['repository_id'], 'id': item['candidate_id'],
                    'classification': item['kind']}
                for index, item in enumerate(candidate['nodes'])}
    mapping = dict(schema=MAPPING_SCHEMA, stage='accepted-rebuild-preview', import_ready=False,
        approval='pending-live-target-preview', inventory_sha256=value['inventory_sha256'],
        mapping_policy='history-inclusive-and-free-descriptions-v2',
        test_plan_policy='excluded-as-source; full-replacement-authorized',
        module_placements=[], projects=projects, definitions=definitions,
        anonymous_identities=anonymous, coverage=coverage,
        warnings=candidate.get('resolution_warnings', []),
        preserved_dependency_hints=value['dependency_hints'], historical_dependency_context=[],
        milestone_completion_evidence=[],
        rebuild=dict(candidate_sha256=candidate['candidate_sha256'],
                     catalog_sha256=report['catalog_sha256'], fidelity=report['fidelity'],
                     verdicts=report['verdicts'], audit_overrides=report['audit_overrides']),
        summary=dict(projects=len(projects), projected_nodes=len(candidate['nodes']),
                     supporting_records=len(candidate['supporting_records']),
                     node_types=dict(sorted(Counter(item['kind'] for item in candidate['nodes']).items()))),
        limitations=['Accepted source-first rebuild; live target and bundle review remain separate.',
                     'Resolution warnings are preserved in the identity map.',
                     'Original source bytes must accompany import.'])
    mapping['mapping_sha256'] = hashlib.sha256(canonical(mapping)).hexdigest()
    return mapping


def assemble_rebuild_bundle(run_dir, roots, node, target_project_id, *, author_id,
                            privacy, output, target_locations=None, target_projects=None,
                            created_at=None):
    _, _, catalog, candidate, report = accepted_rebuild(run_dir)
    value, roots = pinned_inventory(catalog, roots)
    mapping = mapping_from_rebuild(value, catalog, candidate, report)
    targets = dict(target_projects or {})
    require('federated-workspace' not in targets, 'Host target must use target_project_id')
    targets['federated-workspace'] = target_project_id
    require(set(targets) <= {item['repository_id'] for item in mapping['projects']},
            'Existing target supplied for an unknown rebuild scope')
    for repository_id, project_id in sorted(targets.items()):
        mapping = bind_target_preview(mapping, node, project_id,
                                      repository_id=repository_id)
        project = next(item for item in mapping['projects']
                       if item['repository_id'] == repository_id)
        git = Projects(node).repository(project_id)
        require(git.head() == project['target_preview']['expected_head'],
                'Target HEAD changed while binding rebuild artifacts')
        entities = validate_snapshot(git.snapshot(project['target_preview']['expected_head']))
        replacement = {artifact_id: metadata for artifact_id, metadata in entities.items()
                       if 'roadmap-import' in metadata.get('tags', [])}
        project['replace_artifact_ids'] = sorted(replacement)
        project['replacement_metadata'] = replacement
        mapping.pop('mapping_sha256', None)
        mapping['mapping_sha256'] = hashlib.sha256(canonical(mapping)).hexdigest()
    when = created_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    operation, blobs = assemble_bundle(value, mapping, roots, author_id=author_id,
        created_at=when, privacy=privacy, target_locations=target_locations or {})
    write_bundle(output, operation, blobs)
    return operation, mapping


def rebind_source_review(bundle, prior_review, decisions, *, reviewed_at=None):
    operation, blobs = load_bundle(bundle)
    prior = _load_json(prior_review)
    require(prior.get('schema') == 'fpw-roadmap-source-review-v1',
            'Unsupported prior source review')
    decision_map = {key: (privacy, rationale) for key, privacy, rationale in decisions}
    require(len(decision_map) == len(decisions), 'Duplicate source review decision')
    source_hashes, external = {}, Counter()
    for project in operation['projects']:
        files = project_files(project, blobs)
        for path, raw in files.items():
            if path.endswith('/sources.json'):
                for item in json.loads(raw)['sources']:
                    require(item['key'] not in source_hashes, 'Duplicate source in bundle')
                    source_hashes[item['key']] = item['sha256']
        external.update(item['target'] for item in _links(files, project)[2])
    require(set(decision_map) <= set(source_hashes), 'Decision supplied for an unknown source')
    prior_sources = {(item['key'], item['sha256']): item
                     for item in prior['source_classifications']}
    rows = []
    for key, sha256 in sorted(source_hashes.items()):
        if key in decision_map:
            privacy, rationale = decision_map[key]
            require(privacy in {'public', 'project', 'confidential', 'local-only'}
                    and isinstance(rationale, str) and rationale.strip(),
                    'Invalid explicit source review decision')
            rows.append(dict(key=key, sha256=sha256, privacy=privacy,
                             rationale=rationale.strip()))
        else:
            previous = prior_sources.get((key, sha256))
            require(previous is not None,
                    'Changed source requires an explicit review decision: ' + key)
            rows.append(dict(previous))
    prior_links = {(item['url'], item['occurrences']): item for item in prior['external_links']}
    links = []
    for url, occurrences in sorted(external.items()):
        previous = prior_links.get((url, occurrences))
        require(previous is not None,
                'New or changed external link requires explicit review: ' + url)
        links.append(dict(previous))
    return dict(schema='fpw-roadmap-source-review-v1',
                bundle_sha256=operation['bundle_sha256'],
                reviewed_at=reviewed_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                source_classifications=rows, external_links=links)
