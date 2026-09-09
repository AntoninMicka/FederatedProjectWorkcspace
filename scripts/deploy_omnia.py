"""Explicit manual deployment of the headless PoC to an existing Debian LXC."""
import argparse
import io
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def bundle(root):
    files = [root / name for name in ('requirements.txt', 'LICENSE')]
    files += sorted((root / 'spikes').glob('*.py'))
    # Fixed source allowlist: no .git, credentials, private catalog or user data.
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Invalid deployment source: {path.name}')
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return stream.getvalue(), [str(p.relative_to(root)) for p in files]


def remote_script(container, release):
    # Both interpolated values have been validated/generated locally.
    return f'''set -eu
awk '$2 == "/srv" && $3 == "btrfs" {{found=1}} END {{exit !found}}' /proc/mounts || {{ echo 'SSD /srv not mounted as Btrfs' >&2; exit 1; }}
[ "$(lxc-info -P /srv/lxc -n {container} -sH < /dev/null)" = RUNNING ]
# Check actual container filesystem, not a guessed rootfs path.
hostdev=$(stat -c %d /srv)
containerdev=$(lxc-attach -P /srv/lxc -n {container} -- stat -c %d / < /dev/null)
[ "$hostdev" = "$containerdev" ] || {{ echo 'Container root is not on /srv filesystem' >&2; exit 1; }}
lxc-attach -P /srv/lxc -n {container} -- sh -c {shlex.quote(install_script(release))}
'''


def install_script(release):
    return f'''set -eu
umask 077
. /etc/os-release
[ "$ID" = debian ] || {{ echo 'Debian container required' >&2; exit 1; }}
base=/opt/federated-workspace
mkdir -p "$base/releases"
[ ! -L "$base" ] && [ ! -L "$base/releases" ]
release="$base/releases/{release}"
mkdir "$release"
# Incomplete releases are retained for diagnosis; current is changed only on success.
tar -xzf - -C "$release" --no-same-owner --no-same-permissions
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates
python3 -c 'import sys; assert sys.version_info >= (3,11)'
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install -r "$release/requirements.txt"
cd "$release"
"$release/.venv/bin/python" -m spikes.demo
[ ! -e "$base/current" ] || [ -L "$base/current" ]
ln -s "releases/{release}" "$base/.current-{release}"
mv -Tf "$base/.current-{release}" "$base/current"
echo 'PoC installed: /opt/federated-workspace/current'
echo 'No daemon started; run .venv/bin/python -m spikes.demo from current.'
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='SSH user@host of the router (password prompt allowed)')
    parser.add_argument('--container', default='workspace-m0')
    parser.add_argument('--dry-run', action='store_true', help='Show plan without SSH or writes')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('host must be user@hostname or user@IPv4')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', args.container):
        parser.error('invalid container name')
    payload, files = bundle(ROOT)
    release = uuid.uuid4().hex
    command = remote_script(args.container, release)
    if args.dry_run:
        print(f'Target: {args.host}; container: {args.container}; release: {release}')
        print('Files: ' + ', '.join(files))
        print(command)
        return 0
    # Ignore broken/implicit client proxy config; retain known-host verification and ssh-agent.
    result = subprocess.run(['ssh', '-F', '/dev/null', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'ConnectTimeout=10', args.host, 'sh -c ' + shlex.quote(command)],
                            input=payload)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
