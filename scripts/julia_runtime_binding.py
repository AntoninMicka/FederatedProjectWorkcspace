# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Create a pinned Julia runtime binding after separate archive verification."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from spikes.julia_computation import (RUNTIME_SCHEMA, _distribution_digest, _tree_digest,
                                      validate_runtime_binding)
from spikes.output_execution import canonical, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--archive-sha256', required=True)
    parser.add_argument('--depot', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--binding-id', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.runtime_root.resolve(strict=True)
        archive = args.archive.resolve(strict=True); depot = args.depot.resolve(strict=True)
        executable, sysimage = root / 'bin/julia', root / 'lib/julia/sys.so'
        actual_archive = digest(archive.read_bytes())
        if actual_archive != args.archive_sha256:
            raise ValueError('Julia archive SHA-256 differs from expected value')
        version = subprocess.run([str(executable), '--version'], check=True,
            capture_output=True, text=True, timeout=15,
            env={'HOME': '/nonexistent', 'LC_ALL': 'C'}).stdout.strip()
        if version != 'julia version ' + args.version:
            raise ValueError('Julia executable version differs from binding')
        binding = validate_runtime_binding({'schema': RUNTIME_SCHEMA,
            'binding_id': args.binding_id, 'revision': args.revision,
            'executable': str(executable), 'version': args.version,
            'platform': 'linux-' + os.uname().machine.lower(),
            'executable_sha256': digest(executable.read_bytes()),
            'distribution_sha256': _distribution_digest(root), 'sysimage': str(sysimage),
            'sysimage_sha256': digest(sysimage.read_bytes()), 'depot': str(depot),
            'depot_sha256': _tree_digest(depot)})
        output = args.output.absolute(); output.parent.resolve(strict=True)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(canonical(binding) + b'\n'); handle.flush(); os.fsync(handle.fileno())
        print(output)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Julia binding failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
