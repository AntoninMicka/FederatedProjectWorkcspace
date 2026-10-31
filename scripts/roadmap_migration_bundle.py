# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Assemble a private import package; no apply command is provided."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from spikes.metadata import require
from spikes.roadmap_bundle import assemble_bundle, write_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--source-root', nargs=2, action='append', required=True, metavar=('REPOSITORY_ID', 'PATH'))
    parser.add_argument('--author-id', required=True, help='Durable local author UUID, never node UUID')
    parser.add_argument('--created-at', help='Fixed UTC package preparation timestamp for reproducibility')
    parser.add_argument('--privacy', required=True, choices=['public','project','confidential','local-only'])
    parser.add_argument('--target-location', nargs=2, action='append', default=[],
                        metavar=('REPOSITORY_ID', 'ABSOLUTE_PATH'))
    parser.add_argument('--output', required=True, help='New private output directory')
    args = parser.parse_args()
    roots = dict(args.source_root)
    require(len(roots) == len(args.source_root), 'Duplicate source root')
    locations = dict(args.target_location)
    require(len(locations) == len(args.target_location), 'Duplicate target location')
    value = json.loads(Path(args.inventory).read_text(encoding='utf-8'))
    mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8'))
    when = args.created_at or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    operation, blobs = assemble_bundle(value, mapping, roots, author_id=args.author_id,
                                      created_at=when, privacy=args.privacy, target_locations=locations)
    write_bundle(args.output, operation, blobs)
    print(json.dumps({p['repository_id']:p['summary'] for p in operation['projects']},ensure_ascii=False,indent=2))
    print('Assembled only; no Workspace changes. Package:', args.output)


if __name__ == '__main__':
    main()
