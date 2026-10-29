# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Build and audit a fresh roadmap candidate from pinned sequential sources."""
import argparse
import json

from spikes.project_creation import default_node_path
from spikes.roadmap_rebuild import RoadmapRebuild


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--run-dir', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--repository', required=True)
    prepare.add_argument('--revision', default='HEAD')
    prepare.add_argument('--module', nargs=3, action='append', default=[],
                         metavar=('MODULE_ID', 'REPOSITORY', 'REVISION'))
    run = sub.add_parser('run'); run.add_argument('--limit', type=int, default=1)
    sub.add_parser('status')
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        service = RoadmapRebuild.prepare(args.node, args.run_dir, args.repository,
                                         revision=args.revision, modules=args.module)
        result = service.status()
    else:
        service = RoadmapRebuild(args.node, args.run_dir)
        result = service.run(limit=args.limit) if args.command == 'run' else service.status()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
