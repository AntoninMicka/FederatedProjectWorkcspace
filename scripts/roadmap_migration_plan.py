# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Render a private hierarchy proposal and exact source archives, without apply."""
import argparse
import json
from pathlib import Path

from spikes.metadata import require
from spikes.roadmap_mapping import (bind_target_preview, build_mapping, load_sources,
                                    render_mapping_summary, validate_mapping_binding)


def write_preview(output, value, mapping, roots):
    validate_mapping_binding(mapping, value)
    raw = load_sources(value, roots)
    output = Path(output)
    output.mkdir(mode=0o700)
    for project in mapping['projects']:
        folder = output / project['repository_id']
        folder.mkdir(mode=0o700)
        (folder / 'TODO.md').write_text(project['body'], encoding='utf-8')
        if project.get('target_preview'):
            (folder / 'target-before.md').write_bytes(project['target_preview']['original_content'].encode('utf-8'))
            (folder / 'target.diff').write_text(project['target_preview']['diff'], encoding='utf-8')
        for source, relative in project['source_references'].items():
            path = folder / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw[source])
        for doc in project.get('prose_documents', []):
            path = folder / doc['path']
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_text(doc['body'], encoding='utf-8')
        for filename, history in [('requirements.md', False), ('history.md', True)]:
            lines = ['# ' + ('Historické důkazy' if history else 'Katalog požadavků'), '',
                     'Náhled mapování; původní zdroje jsou přiloženy beze změny.', '']
            for locator, coverage in mapping['coverage'].items():
                source, line = locator.rsplit(':', 1)
                if source not in project['source_references']:
                    continue
                is_history = coverage['classification'] == 'historical-evidence'
                if is_history != history or coverage['classification'] in {'batch', 'task', 'checklist', 'supporting-document'}:
                    continue
                text = raw[source].decode('utf-8').splitlines()[int(line) - 1]
                lines += ['## ' + (coverage['id'] or 'Historická položka bez ID'), '',
                          f'Zdroj: [{source}:{line}]({project["source_references"][source]})', '',
                          '    ' + text, '']
            (folder / filename).write_text('\n'.join(lines), encoding='utf-8')
    (output / 'summary.md').write_text(render_mapping_summary(mapping), encoding='utf-8')
    (output / 'inventory.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Last file is the complete report. An interrupted write is never an import receipt.
    (output / 'mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--source-root', nargs=2, action='append', required=True, metavar=('REPOSITORY_ID', 'PATH'))
    parser.add_argument('--module-placements', help='JSON list of explicitly proposed module milestone placements')
    parser.add_argument('--reuse-mapping', help='Replay a frozen mapping against its exact inventory')
    parser.add_argument('--target', nargs=2, metavar=('NODE_CONFIG', 'PROJECT_ID'),
                        help='Read-only root-plan diff against an existing registered target')
    parser.add_argument('--output', required=True, help='New private report directory')
    args = parser.parse_args()
    roots = dict(args.source_root)
    require(len(roots) == len(args.source_root), 'Duplicate source root')
    value = json.loads(Path(args.inventory).read_text(encoding='utf-8'))
    placements = json.loads(Path(args.module_placements).read_text(encoding='utf-8')) if args.module_placements else []
    require(isinstance(placements, list), 'Placements must be a list')
    require(not (args.reuse_mapping and args.module_placements), 'Replay cannot change module placements')
    if args.reuse_mapping:
        mapping = json.loads(Path(args.reuse_mapping).read_text(encoding='utf-8'))
        validate_mapping_binding(mapping, value)
    else:
        mapping = build_mapping(value, roots, module_placements=placements)
    if args.target:
        mapping = bind_target_preview(mapping, *args.target)
    write_preview(args.output, value, mapping, roots)
    print(json.dumps(mapping['summary'], ensure_ascii=False, indent=2))
    print('Hierarchy preview only; no Workspace changes. Report:', args.output)


if __name__ == '__main__':
    main()
