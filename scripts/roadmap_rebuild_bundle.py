# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Build a native, still-unapplied import bundle from an accepted rebuild run."""
import argparse
import json

from spikes.project_creation import default_node_path
from spikes.roadmap_rebuild_bundle import assemble_rebuild_bundle, local_author_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--target-project-id', required=True)
    parser.add_argument('--existing-target', nargs=2, action='append', default=[],
                        metavar=('REPOSITORY_ID', 'PROJECT_ID'))
    parser.add_argument('--source-root', nargs=2, action='append', required=True,
                        metavar=('REPOSITORY_ID', 'PATH'))
    parser.add_argument('--target-location', nargs=2, action='append', default=[],
                        metavar=('REPOSITORY_ID', 'ABSOLUTE_PATH'))
    parser.add_argument('--privacy', default='project',
                        choices=['public', 'project', 'confidential', 'local-only'])
    parser.add_argument('--created-at')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    roots = dict(args.source_root); locations = dict(args.target_location)
    targets = dict(args.existing_target)
    if (len(roots) != len(args.source_root) or len(locations) != len(args.target_location)
            or len(targets) != len(args.existing_target)):
        raise ValueError('Duplicate source root, target location or existing target')
    author_id = local_author_id(args.node)
    operation, mapping = assemble_rebuild_bundle(args.run_dir, roots, args.node,
        args.target_project_id, author_id=author_id, privacy=args.privacy,
        output=args.output, target_locations=locations, target_projects=targets,
        created_at=args.created_at)
    print(json.dumps({'bundle_sha256': operation['bundle_sha256'],
                      'candidate_sha256': mapping['rebuild']['candidate_sha256'],
                      'projects': {item['repository_id']: item['summary']
                                   for item in operation['projects']},
                      'project_write_performed': False, 'output': args.output},
                     ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
