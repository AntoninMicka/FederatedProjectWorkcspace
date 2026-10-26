# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Create a pinned Julia runtime binding after separate archive verification."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import NAMESPACE_URL, uuid5

from spikes.julia_computation import (RUNTIME_SCHEMA, _distribution_digest, _tree_digest,
                                      validate_runtime_binding)
from spikes.metadata import parse_json
from spikes.output_execution import canonical, digest

SUPPORTED_ARCHIVES = {
    ('1.10.12', 'linux-aarch64'):
        'cc257b21967049642bfe17de1aff7dae17477eba4f423f98cb400c002080e5a2',
}


def _regular_file(path, label):
    path = Path(path).absolute()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1:
        raise ValueError(f'{label} must be one regular non-symlink file')
    return path


def _file_digest(path, maximum=1024 ** 3):
    path = _regular_file(path, 'Julia archive')
    if path.stat().st_size > maximum:
        raise ValueError('Julia archive exceeds size limit')
    value = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _runtime_version(root):
    executable = root / 'bin/julia'
    result = subprocess.run([str(executable), '--version'], check=True,
        capture_output=True, text=True, timeout=15,
        env={'HOME': '/nonexistent', 'LC_ALL': 'C'})
    prefix = 'julia version '
    if not result.stdout.strip().startswith(prefix):
        raise ValueError('Julia executable returned an invalid version')
    return result.stdout.strip()[len(prefix):]


def build_binding(runtime_root, archive, expected_archive_sha256, depot, version,
                  binding_id, revision):
    root = Path(runtime_root).resolve(strict=True)
    archive = _regular_file(archive, 'Julia archive')
    depot = Path(depot).resolve(strict=True)
    executable, sysimage = root / 'bin/julia', root / 'lib/julia/sys.so'
    actual_archive = _file_digest(archive)
    if actual_archive != expected_archive_sha256:
        raise ValueError('Julia archive SHA-256 differs from expected value')
    if _runtime_version(root) != version:
        raise ValueError('Julia executable version differs from binding')
    return validate_runtime_binding({'schema': RUNTIME_SCHEMA,
        'binding_id': binding_id, 'revision': revision,
        'executable': str(executable), 'version': version,
        'platform': 'linux-' + os.uname().machine.lower(),
        'executable_sha256': digest(executable.read_bytes()),
        'distribution_sha256': _distribution_digest(root), 'sysimage': str(sysimage),
        'sysimage_sha256': digest(sysimage.read_bytes()), 'depot': str(depot),
        'depot_sha256': _tree_digest(depot)})


def write_new_binding(output, binding):
    output = Path(output).absolute()
    output.parent.resolve(strict=True)
    raw = canonical(binding) + b'\n'
    pending = output.with_name('.' + output.name + '.pending')
    if output.exists():
        if pending.exists() and os.path.samefile(output, pending):
            pending.unlink()
        raise FileExistsError(output)
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    except FileExistsError:
        existing = _regular_file(pending, 'Pending Julia binding')
        if existing.read_bytes() != raw or stat.S_IMODE(existing.stat().st_mode) != 0o600:
            raise ValueError('Conflicting pending Julia binding requires manual recovery')
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    os.link(pending, output, follow_symlinks=False)
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
        pending.unlink()
        os.fsync(directory)
    finally:
        os.close(directory)
    return output


def _private_directory(path):
    path = Path(path).absolute()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or path.is_symlink() or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError(f'Private directory requires owned mode 0700: {path}')
    return path


def probe_bubblewrap(executable):
    executable = _regular_file(executable, 'bubblewrap executable')
    if not os.access(executable, os.X_OK):
        raise ValueError('bubblewrap is not executable')
    command = [str(executable), '--die-with-parent', '--new-session', '--unshare-all',
               '--clearenv', '--proc', '/proc', '--dev', '/dev']
    for source in ('/usr', '/bin', '/lib', '/lib64'):
        if Path(source).exists():
            command += ['--ro-bind', source, source]
    command += ['--', '/bin/true']
    subprocess.run(command, check=True, capture_output=True, timeout=15,
                   env={'HOME': '/nonexistent', 'LC_ALL': 'C'})
    return str(executable)


def setup_runtime(runtime_root, archive, setup_root, bubblewrap='/usr/bin/bwrap'):
    root = Path(runtime_root).resolve(strict=True)
    archive = _regular_file(archive, 'Julia archive')
    version = _runtime_version(root)
    platform_name = 'linux-' + os.uname().machine.lower()
    expected = SUPPORTED_ARCHIVES.get((version, platform_name))
    if expected is None:
        raise ValueError(f'Unsupported Julia setup profile: {version} {platform_name}')
    actual = _file_digest(archive)
    if actual != expected:
        raise ValueError('Julia archive SHA-256 differs from supported profile')
    bwrap = probe_bubblewrap(bubblewrap)

    destination = _private_directory(setup_root)
    depot = _private_directory(destination / 'depot')
    state = _private_directory(destination / 'state')
    revision = f'official-{version}-{platform_name}'
    binding_id = str(uuid5(NAMESPACE_URL,
        f'fpw-julia:{revision}:{actual}:{root}:{depot}'))
    binding = build_binding(root, archive, expected, depot, version, binding_id, revision)
    output = destination / 'binding.json'
    reused = False
    if output.exists():
        pending = output.with_name('.' + output.name + '.pending')
        if pending.exists():
            if not os.path.samefile(output, pending):
                raise ValueError('Conflicting pending Julia binding requires manual recovery')
            pending.unlink()
        existing = _regular_file(output, 'Julia binding')
        if (stat.S_IMODE(existing.stat().st_mode) != 0o600
                or existing.stat().st_uid != os.getuid()
                or parse_json(existing.read_bytes(), 64 * 1024) != binding):
            raise ValueError('Existing Julia binding differs; choose a new setup root')
        reused = True
    else:
        write_new_binding(output, binding)
    next_command = ['federated-workspace-poc-julia', '--project', 'PROJECT_WORKTREE',
        '--state', str(state), '--binding', str(output), '--node-id', 'NODE_UUID',
        '--user-id', 'USER_UUID', 'prepare', '--operation-id', 'RUN_UUID',
        '--project-id', 'PROJECT_UUID', '--computation', 'computation.json',
        '--parameters', 'parameters.json']
    return {
        'schema': 'fpw-julia-setup-result-v1',
        'status': 'ready',
        'reused': reused,
        'version': version,
        'platform': platform_name,
        'archive_sha256': actual,
        'archive_signature': 'not-verified-by-setup',
        'bubblewrap': bwrap,
        'binding': str(output),
        'state': str(state),
        'depot': str(depot),
        'next': {'action': 'prepare-versioned-computation', 'command': next_command},
    }


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
        binding = build_binding(args.runtime_root, args.archive, args.archive_sha256,
            args.depot, args.version, args.binding_id, args.revision)
        output = write_new_binding(args.output, binding)
        print(output)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Julia binding failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
