# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Validate one project.json or local node.json without modifying it."""
import argparse
from pathlib import Path
import sys

from spikes.configuration import parse_node, parse_project, read_config
from spikes.metadata import ValidationError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('project', 'node'))
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        data = read_config(args.path)
        if args.kind == 'project':
            parse_project(data)
        else:
            parse_node(data, location=args.path)
    except (OSError, ValueError, RuntimeError) as exc:
        # Do not echo parser errors: they may contain pieces of credential input.
        if isinstance(exc, ValidationError):
            reason = 'invalid schema, values or JSON'
        else:
            reason = 'cannot safely read or resolve configuration'
        print(f'Configuration validation failed: {reason}.', file=sys.stderr)
        return 1
    print(f'Valid {args.kind} configuration v1; no files changed. '
          'Project contents, identity and credential availability are not checked.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
