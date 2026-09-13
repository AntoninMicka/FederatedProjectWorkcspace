# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Explicit manual deployment of the headless PoC to an existing Debian LXC."""
import argparse
import io
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import time
import uuid

if __package__:
    from .license_files import license_files
    from .install_web import install_script as web_install_script
else:
    from license_files import license_files
    from install_web import install_script as web_install_script

ROOT = Path(__file__).resolve().parents[1]


def remote_recovery_script():
    return r'''set -eu
base=/opt/federated-workspace
unit=/etc/systemd/system/federated-workspace.service
test -d "$base/web-rollback" || { echo 'No interrupted web deployment state'; exit 0; }
if command -v flock >/dev/null 2>&1; then
  exec 9>"$base/web-deploy.lock" || exit 1
  flock -n 9 || exit 1
fi
systemctl stop federated-workspace.service || :
if [ -s "$base/web-rollback/previous" ]; then
  ln -s "$(cat "$base/web-rollback/previous")" "$base/.manual-restore"
  mv -Tf "$base/.manual-restore" "$base/current"
else
  rm -f "$base/current"
fi
if [ -f "$base/web-rollback/unit" ]; then
  cp -p "$base/web-rollback/unit" "$unit"
else
  rm -f "$unit"
fi
systemctl daemon-reload
if [ -f "$base/web-rollback/enabled" ]; then
  systemctl enable federated-workspace.service
else
  systemctl disable federated-workspace.service || true
fi
if [ -f "$base/web-rollback/active" ]; then
  systemctl start federated-workspace.service || true
fi
echo 'Recovered interrupted web deployment'
'''


def run_ssh(host, command, payload):
    args = ['ssh', '-F', '/dev/null', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', host, 'sh -c ' + shlex.quote(command)]
    return subprocess.run(args, input=payload)


def bundle(root):
    files = [root / 'requirements.txt', *license_files(root)]
    files += sorted((root / 'spikes').glob('*.py'))
    # Fixed source allowlist: no .git, credentials, private catalog or user data.
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Invalid deployment source: {path.name}')
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return stream.getvalue(), [str(p.relative_to(root)) for p in files]


def remote_script(container, release, *, lan=None):
    # Both interpolated values have been validated/generated locally.
    return f'''set -eu
awk '$2 == "/srv" && $3 == "btrfs" {{found=1}} END {{exit !found}}' /proc/mounts || {{ echo 'SSD /srv not mounted as Btrfs' >&2; exit 1; }}
[ "$(lxc-info -P /srv/lxc -n {container} -sH < /dev/null)" = RUNNING ]
# Check actual container filesystem, not a guessed rootfs path.
hostdev=$(stat -c %d /srv)
containerdev=$(lxc-attach -P /srv/lxc -n {container} -- stat -c %d / < /dev/null)
[ "$hostdev" = "$containerdev" ] || {{ echo 'Container root is not on /srv filesystem' >&2; exit 1; }}
lxc-attach -P /srv/lxc -n {container} -- sh -c {shlex.quote(web_install_script(release, lan) if lan else install_script(release))}
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
    parser.add_argument('--retries', type=int, default=3, help='Deployment retry count on failure')
    parser.add_argument('--web-lan', help='Opt in to HTTPS viewer; allowed private IPv4 client subnet')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('host must be user@hostname or user@IPv4')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', args.container):
        parser.error('invalid container name')
    payload, files = bundle(ROOT)
    release = uuid.uuid4().hex
    try:
        command = remote_script(args.container, release, lan=args.web_lan)
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(f'Target: {args.host}; container: {args.container}; release: {release}')
        print('Files: ' + ', '.join(files))
        print(command)
        return 0
    if args.retries < 1:
        parser.error('retries must be >= 1')

    result = None
    for attempt in range(1, args.retries + 1):
        if attempt > 1:
            recover_result = run_ssh(args.host, remote_recovery_script(), b'')
            if recover_result.returncode != 0:
                print(f'Attempt {attempt}: recovery failed')
                return recover_result.returncode
            print(f'Attempt {attempt}/{args.retries}: retrying deployment')
        # Ignore broken/implicit client proxy config; retain known-host verification and ssh-agent.
        result = run_ssh(args.host, command, payload)
        if result.returncode == 0:
            return 0
        if attempt < args.retries:
            time.sleep(2 ** (attempt - 1))
            print(f'Attempt {attempt}/{args.retries}: failed, retrying')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
