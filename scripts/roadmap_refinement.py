# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Scan, review and apply local Ollama roadmap refinement proposals."""
import argparse
import json

from spikes.project_creation import default_node_path
from spikes.roadmap_refinement import RoadmapRefinement
from spikes.roadmap_refinement_tui import launch, launch_project_selector


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--project')
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan'); scan.add_argument('--limit', type=int, default=1)
    sub.add_parser('list')
    decide = sub.add_parser('decide'); decide.add_argument('--proposal', required=True)
    choice = decide.add_mutually_exclusive_group(required=True)
    choice.add_argument('--accept', action='store_true'); choice.add_argument('--reject', action='store_true')
    apply = sub.add_parser('apply'); apply.add_argument('--operation-id', required=True)
    tui = sub.add_parser('tui'); tui.add_argument('--limit', type=int, default=5)
    args = parser.parse_args(argv)
    if args.command == 'tui' and not args.project:
        launch_project_selector(args.node, scan_limit=args.limit)
        return 0
    if not args.project:
        parser.error('--project je povinný pro příkaz ' + args.command)
    service = RoadmapRefinement(args.node, args.project)
    if args.command == 'scan':
        result = service.scan(limit=args.limit)
    elif args.command == 'list':
        result = service.list()
    elif args.command == 'decide':
        result = service.decide(args.proposal, 'accept' if args.accept else 'reject')
    elif args.command == 'tui':
        launch(service, scan_limit=args.limit)
        return 0
    else:
        result = service.apply(args.operation_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
