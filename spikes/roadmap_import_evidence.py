# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only completeness evidence for an applied source-first roadmap rebuild."""
from collections import Counter
import json
from pathlib import Path

from spikes.configuration import parse_node, read_config
from spikes.metadata import require, validate_snapshot
from spikes.roadmap_bundle import project_files
from spikes.roadmap_rebuild_bundle import accepted_rebuild
from spikes.roadmap_validation import _journal_state, load_bundle
from spikes.storage import Git


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit_import_evidence(run_dir, bundle, receipt_path, node_path):
    """Prove catalog -> candidate -> bundle -> committed snapshot completeness."""
    _, _, catalog, candidate, rebuild_report = accepted_rebuild(run_dir)
    operation, blobs = load_bundle(bundle)
    receipt = _json(receipt_path)
    node_path = Path(node_path).resolve(strict=True)
    node = parse_node(read_config(node_path), location=node_path)
    bindings = {item['project_id']: item for item in node['projects']}

    require(receipt.get('schema') == 'fpw-roadmap-import-receipt-v1'
            and receipt.get('completed') is True, 'Import receipt is incomplete')
    require(receipt.get('bundle_sha256') == operation['bundle_sha256'],
            'Receipt belongs to another bundle')
    catalog_blocks = {item['block_id'] for item in catalog['blocks']}
    evidenced_blocks = {item['provenance']['block_id'] for item in candidate['nodes']}
    evidenced_blocks.update(item['provenance']['block_id']
                            for item in candidate['supporting_records'])
    evidenced_blocks.update(provenance['block_id'] for item in candidate['nodes']
                            for provenance in item.get('provenance_all', []))
    missing_blocks = sorted(catalog_blocks - evidenced_blocks)
    require(not missing_blocks, 'Candidate omits source catalog blocks')

    receipt_projects = {item['repository_id']: item for item in receipt['projects']}
    bundle_projects = {item['repository_id']: item for item in operation['projects']}
    require(receipt_projects.keys() == bundle_projects.keys(),
            'Receipt project coverage differs from bundle')

    source_hashes = {}
    project_results = []
    all_bundle_text = []
    for repository_id, project in sorted(bundle_projects.items()):
        recorded = receipt_projects[repository_id]
        require(recorded['project_id'] == project['project_id']
                and recorded['operation_id'] == project['operation_id'],
                'Receipt project identity differs from bundle')
        binding = bindings.get(project['project_id'])
        require(binding is not None, 'Imported project is not registered on the node')
        commit_id = recorded['receipt']['commit_id']
        git = Git(binding['root'])
        head = git.head()
        require(head == commit_id, 'Imported project HEAD moved after the recorded import')
        snapshot = git.snapshot(commit_id)
        validate_snapshot(snapshot)
        expected = project_files(project, blobs)
        missing = sorted(path for path, raw in expected.items() if snapshot.get(path) != raw)
        require(not missing, 'Committed project differs from imported bundle files')
        journal = _journal_state(binding)
        require(not journal['pending_files'] and not journal['unfinished_operations'],
                'Imported project journal is not idle')
        for path, raw in expected.items():
            if path.endswith('/sources.json'):
                for source in json.loads(raw)['sources']:
                    previous = source_hashes.setdefault(source['key'], source['sha256'])
                    require(previous == source['sha256'], 'Conflicting bundled source hash')
            if path.endswith('.md'):
                all_bundle_text.append(raw.decode('utf-8'))
        project_results.append(dict(repository_id=repository_id,
            project_id=project['project_id'], commit_id=commit_id,
            files_verified=len(expected), snapshot_files=len(snapshot), journal=journal,
            node_types=project['summary']['node_types']))

    catalog_sources = {item['key']: item['sha256'] for item in catalog['sources']}
    require(all(source_hashes.get(key) == sha256
                for key, sha256 in catalog_sources.items()),
            'Bundled source inventory omits or changes a catalog source')
    text = '\n'.join(all_bundle_text)
    missing_nodes = sorted(item['candidate_id'] for item in candidate['nodes']
                           if f'[{item["candidate_id"]}]' not in text)
    require(not missing_nodes, 'Imported plans omit candidate nodes')
    missing_support = sorted(item['entity_key'] for item in candidate['supporting_records']
                             if item['summary'] not in text)
    require(not missing_support, 'Imported supporting documents omit candidate records')

    return dict(schema='fpw-roadmap-import-evidence-v1', complete=True,
        bundle_sha256=operation['bundle_sha256'],
        candidate_sha256=candidate['candidate_sha256'],
        catalog_sha256=catalog['catalog_sha256'],
        counts=dict(roadmap_source_files=len(catalog_sources),
                    bundled_source_files=len(source_hashes),
                    supporting_source_files=len(source_hashes) - len(catalog_sources),
                    source_blocks=len(catalog_blocks),
                    evidenced_source_blocks=len(catalog_blocks),
                    nodes=len(candidate['nodes']),
                    supporting_records=len(candidate['supporting_records']),
                    projects=len(project_results),
                    node_types=dict(sorted(Counter(item['kind']
                                                   for item in candidate['nodes']).items()))),
        projects=project_results,
        findings=[], verdict='complete-no-loss-detected',
        limitations=[
            'Deterministic evidence audit; it does not repeat the semantic LLM fidelity audit.',
            'HEAD equality proves the imported state before later project edits, not UI rendering.',
        ],
        source_fidelity=rebuild_report['fidelity'])


def render_summary(report):
    counts = report['counts']
    lines = ['# Evidenční kontrola importu roadmapy', '',
             f'Výsledek: **{report["verdict"]}**', '',
             f'- Roadmapové zdrojové soubory: {counts["roadmap_source_files"]}',
             f'- Všechny připnuté zdroje v bundle: {counts["bundled_source_files"]} '
             f'(z toho {counts["supporting_source_files"]} doprovodných)',
             f'- Zdrojové bloky: {counts["evidenced_source_blocks"]}/{counts["source_blocks"]}',
             f'- Uzly: {counts["nodes"]}',
             f'- Podpůrné záznamy: {counts["supporting_records"]}',
             f'- Projekty: {counts["projects"]}',
             f'- Původní fidelity audit: {report["source_fidelity"]}', '',
             '| Projekt | Commit | Bundle soubory | Snapshot soubory | Journal |',
             '| --- | --- | ---: | ---: | --- |']
    for project in report['projects']:
        journal = project['journal']
        lines.append(f'| `{project["repository_id"]}` | `{project["commit_id"][:12]}` | '
                     f'{project["files_verified"]} | {project["snapshot_files"]} | '
                     f'{journal["pending_files"]} pending / '
                     f'{journal["unfinished_operations"]} unfinished |')
    lines += ['', 'Nebyla provedena žádná změna projektů ani nový LLM scan.', '']
    return '\n'.join(lines)
