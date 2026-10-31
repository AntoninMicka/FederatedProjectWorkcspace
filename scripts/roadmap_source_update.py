# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Preview or explicitly apply a reviewed, same-node roadmap source update."""
import argparse
import base64
import json
from pathlib import Path

from spikes.metadata import MAX_SNAPSHOT, parse_json, require
from spikes.project_creation import default_node_path
from spikes.roadmap_source_update import RoadmapSourceUpdate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--request', required=True,
                        help='reviewed fpw-roadmap-source-update-v1 JSON; candidate bytes are base64')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('preview')
    apply = commands.add_parser('apply')
    apply.add_argument('--operation-id', required=True)
    apply.add_argument('--expected-preview-sha256', required=True)
    args = parser.parse_args(argv)
    path = Path(args.request)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SNAPSHOT * 2,
            'Invalid source update request file')
    request = parse_json(path.read_bytes(), MAX_SNAPSHOT * 2)
    require(isinstance(request, dict) and request.get('schema') == 'fpw-roadmap-source-update-v1'
            and set(request) == {'schema', 'project_id', 'baseline_commit', 'expected_head',
                                 'source_root', 'source_revision', 'managed_paths',
                                 'incoming_files', 'decisions'}, 'Invalid source update request schema')
    request.pop('schema')
    require(isinstance(request['incoming_files'], dict)
            and all(isinstance(raw, str) for raw in request['incoming_files'].values()),
            'Expected base64 candidate bytes')
    request['incoming_files'] = {path: base64.b64decode(raw, validate=True)
                                 for path, raw in request['incoming_files'].items()}
    service = RoadmapSourceUpdate(args.node)
    if args.command == 'preview':
        result = service.preview(**request)
    else:
        result = service.apply(**request, operation_id=args.operation_id,
                               expected_preview_sha256=args.expected_preview_sha256)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
