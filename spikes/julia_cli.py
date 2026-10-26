# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit local CLI for pinned Julia computations and publication."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from spikes.julia_computation import JuliaExecutor
from spikes.metadata import MAX_METADATA, ValidationError, parse_json
from spikes.output_execution import canonical
from spikes.storage import Git
from spikes.workspace import Workspace


def _json(path, maximum=MAX_METADATA):
    path = Path(path)
    info = path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_nlink != 1:
        raise ValidationError(f'Expected regular JSON file: {path}')
    return parse_json(path.read_bytes(), maximum)


def _executor(args):
    return JuliaExecutor(git=Git(args.project.resolve(strict=True)),
                         state_dir=args.state.resolve(strict=True),
                         runtime_binding=_json(args.binding))


def _emit(value):
    sys.stdout.buffer.write(canonical(value) + b'\n')


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path,
                        help='registered project Git worktree')
    parser.add_argument('--state', required=True, type=Path,
                        help='private mode-0700 Julia state directory')
    parser.add_argument('--binding', required=True, type=Path,
                        help='pinned fpw-julia-runtime-v1 JSON binding')
    parser.add_argument('--node-id', required=True)
    parser.add_argument('--user-id', required=True)
    commands = parser.add_subparsers(dest='command', required=True)

    prepare = commands.add_parser('prepare', help='validate and durably preview a run')
    prepare.add_argument('--operation-id', required=True)
    prepare.add_argument('--project-id', required=True)
    prepare.add_argument('--computation', required=True, type=Path)
    prepare.add_argument('--parameters', required=True, type=Path)

    execute = commands.add_parser('execute', help='execute an approved prepared run')
    execute.add_argument('--operation-id', required=True)
    execute.add_argument('--approval-digest', required=True)

    for name in ('cancel', 'reconcile', 'status'):
        command = commands.add_parser(name)
        command.add_argument('--operation-id', required=True)

    output = commands.add_parser('output', help='copy one verified output without overwrite')
    output.add_argument('--operation-id', required=True)
    output.add_argument('--name', required=True)
    output.add_argument('--destination', required=True, type=Path)

    publish = commands.add_parser('publish', help='publish one output through Workspace')
    publish.add_argument('--operation-id', required=True)
    publish.add_argument('--publication-id', required=True)
    publish.add_argument('--artifact-id', required=True)
    publish.add_argument('--output-name', required=True)
    publish.add_argument('--title', required=True)
    publish.add_argument('--filename', required=True)
    publish.add_argument('--expected-head', required=True)
    publish.add_argument('--author-id', required=True)
    publish.add_argument('--author-name', required=True)
    publish.add_argument('--author-email', required=True)
    publish.add_argument('--privacy', choices=('public', 'project', 'confidential',
                                                'local-only'))
    publish.add_argument('--workspace-state', required=True, type=Path)
    return parser


def run(args):
    executor = _executor(args)
    common = (args.operation_id, args.node_id, args.user_id)
    if args.command == 'prepare':
        return executor.prepare(args.operation_id, args.node_id, args.user_id,
                                args.project_id, _json(args.computation),
                                _json(args.parameters))
    if args.command == 'execute':
        return executor.execute(*common, args.approval_digest)
    if args.command == 'cancel':
        return executor.cancel(*common)
    if args.command == 'reconcile':
        return executor.reconcile(*common)
    if args.command == 'status':
        return executor.status(*common)
    if args.command == 'output':
        content, item, _ = executor.output(*common, args.name)
        destination = args.destination.absolute()
        destination.parent.resolve(strict=True)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {'output': item, 'destination': str(destination)}
    if args.command == 'publish':
        workspace = Workspace(args.project.resolve(strict=True),
                              args.workspace_state.resolve(strict=True))
        return executor.publish(args.publication_id, *common, args.output_name,
            args.artifact_id, args.title, args.filename, workspace, args.expected_head,
            args.author_id, privacy=args.privacy, author_name=args.author_name,
            author_email=args.author_email)
    raise AssertionError('unreachable command')


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        _emit(run(args))
        return 0
    except (OSError, ValidationError, RuntimeError, TimeoutError,
            subprocess.SubprocessError,
            InterruptedError) as exc:
        print(f'Julia computation failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
