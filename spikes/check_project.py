"""Read-only validation of an M0 working-tree artifact/registry projection."""
import argparse
from pathlib import Path
import sys

from spikes.journal import snapshot
from spikes.metadata import ValidationError, validate_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    try:
        root = args.project.resolve(strict=True)
        if not root.is_dir():
            raise ValidationError('Project must be a directory')
        entities = validate_snapshot(snapshot(root))
    except (OSError, ValidationError) as exc:
        print(f'Validation failed: {exc}', file=sys.stderr)
        return 1
    print(f'Valid artifact/registry projection: {len(entities)} entities (project.json not checked).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
