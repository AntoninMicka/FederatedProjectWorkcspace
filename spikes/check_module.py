# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only CLI for module manifest and live API compatibility checks."""
import sys

from spikes.metadata import ValidationError
from spikes.module_manifest import fetch_and_verify_module, read_module_manifest


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in {1, 2}:
        print('Usage: python3 -m spikes.check_module MANIFEST [API_BASE_URL]', file=sys.stderr)
        return 2
    try:
        manifest = read_module_manifest(args[0])
        if len(args) == 2:
            fetch_and_verify_module(args[0], args[1])
            print(f"Compatible module API: {manifest['module_id']} {manifest['module_version']}")
        else:
            print(f"Valid module manifest: {manifest['module_id']} {manifest['module_version']}")
        return 0
    except (OSError, ValidationError):
        print('Module manifest validation failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
