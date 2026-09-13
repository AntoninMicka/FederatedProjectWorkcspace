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


def remote_tls_bootstrap_script(lan, regenerate=False):
    if regenerate:
        condition_block = 'echo "Regenerating TLS artifacts on request"'
    else:
        condition_block = ('if [ -s /etc/federated-workspace/ca.crt ] && [ -s /etc/federated-workspace/tls.crt ] && [ -s /etc/federated-workspace/tls.key ]; then\n'
                          '  if openssl verify -CAfile /etc/federated-workspace/ca.crt /etc/federated-workspace/tls.crt >/dev/null 2>&1; then\n'
                          '    tls_san_ok=$(openssl x509 -in /etc/federated-workspace/tls.crt -noout -text | tr \"\\n\" \" \" | grep -q "IP Address:127.0.0.1"; echo $?)\n'
                          '    ca_constraints_ok=$(openssl x509 -in /etc/federated-workspace/ca.crt -noout -text | tr \"\\n\" \" \" | grep -q "X509v3 Basic Constraints:.*CA:TRUE"; echo $?)\n'
                          '    ca_key_usage_ok=$(openssl x509 -in /etc/federated-workspace/ca.crt -noout -text | tr \"\\n\" \" \" | grep -q "X509v3 Key Usage:.*Certificate Sign"; echo $?)\n'
                          '    if [ "$tls_san_ok" -eq 0 ] && [ "$ca_constraints_ok" -eq 0 ] && [ "$ca_key_usage_ok" -eq 0 ]; then\n'
                          '      echo "Using existing TLS artifacts"\n'
                          '      return\n'
                          '    fi\n'
                          '  fi\n'
                          '  echo "Existing TLS artifacts invalid or outdated; regenerating"\n'
                          'fi')
    return f'''ensure_tls() {{
{condition_block}
command -v openssl >/dev/null 2>&1 || {{ echo "openssl is required for auto TLS setup" >&2; exit 1; }}
mkdir -p /etc/federated-workspace
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ip="$(ip -4 -o addr show scope global | awk '/inet / {{print $4}}' | cut -d/ -f1 | awk '/^(10\\.|127\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[0-1])\\.)/ {{print $1; exit}}')"
cat > "$tmp/ca.cnf" <<'EOF'
[ req ]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[ dn ]
CN = Federated Workspace Local CA
[ v3_ca ]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
EOF
openssl req -x509 -nodes -newkey rsa:3072 -keyout "$tmp/ca.key" -out "$tmp/ca.crt" -days 3650 -sha256 -subj "/CN=Federated Workspace Local CA" -extensions v3_ca -config "$tmp/ca.cnf"
cat > "$tmp/server.ext" <<EOF
[ server_ext ]
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[ alt_names ]
IP.1 = 127.0.0.1
EOF
if [ -n "$ip" ]; then
  echo "IP.2 = $ip" >> "$tmp/server.ext"
fi
openssl req -new -nodes -newkey rsa:3072 -keyout "$tmp/tls.key" -out "$tmp/tls.csr" -subj "/CN=Federated Workspace Viewer" >/dev/null 2>&1
openssl x509 -req -in "$tmp/tls.csr" -CA "$tmp/ca.crt" -CAkey "$tmp/ca.key" -CAcreateserial -out "$tmp/tls.crt" -days 825 -sha256 -extfile "$tmp/server.ext" -extensions server_ext >/dev/null 2>&1
cp "$tmp/ca.crt" "$tmp/tls.key" "$tmp/tls.crt" /etc/federated-workspace/
chmod 0640 /etc/federated-workspace/ca.crt /etc/federated-workspace/tls.crt /etc/federated-workspace/tls.key
echo "Generated TLS artifacts for HTTPS viewer"
}}
ensure_tls
'''


def remote_reset_script(container):
    reset = r'''set -eu
base=/opt/federated-workspace
if [ ! -d "$base" ]; then
  echo "No federated-workspace base"
  exit 0
fi
if [ -d "$base/web-rollback" ]; then
  rm -rf "$base/web-rollback"
fi
if [ ! -d "$base/web-rollback" ]; then
  echo "No interrupted web deployment state"
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop federated-workspace.service || :
  systemctl daemon-reload || :
  systemctl reset-failed federated-workspace.service || :
fi
rm -rf "$base/.web-rollback-preparing" "$base/.manual-restore" "$base/.restore-"* "$base/web-deploy.lock"
echo "Web deployment state reset"
'''
    return f'''lxc-attach -P /srv/lxc -n {container} -- sh -c {shlex.quote(reset)}'''


def remote_recovery_script(cleanup=False):
    cleanup_block = 'rm -rf "$base/web-rollback"' if cleanup else 'echo "Keeping recovery snapshot for manual verification"'
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
''' + cleanup_block + r'''
echo 'Recovered interrupted web deployment'
'''


def run_ssh(host, command, payload):
    args = ['ssh', '-F', '/dev/null', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', host, 'sh -c ' + shlex.quote(command)]
    return subprocess.run(args, input=payload)


def run_ssh_output(host, command):
    args = ['ssh', '-F', '/dev/null', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', host, 'sh -c ' + shlex.quote(command)]
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def sync_ca_to_router(host, container):
    cert_result = run_ssh_output(host, f'lxc-attach -P /srv/lxc -n {container} -- cat /etc/federated-workspace/ca.crt')
    if cert_result.returncode != 0:
        print(cert_result.stderr.decode(errors='ignore'))
        return cert_result.returncode
    if not cert_result.stdout.strip():
        print('CA certificate is empty')
        return 1
    write_result = run_ssh(
        host,
        'cat > /etc/federated-workspace-ca.pem && chmod 0644 /etc/federated-workspace-ca.pem',
        cert_result.stdout,
    )
    if write_result.returncode != 0:
        print(write_result.stderr.decode(errors='ignore'))
    else:
        print('CA certificate copied to router')
    return write_result.returncode


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


def remote_script(container, release, *, lan=None, force_tls=False):
    # Both interpolated values have been validated/generated locally.
    command = web_install_script(release, lan) if lan else install_script(release)
    web_tls = f'\n{remote_tls_bootstrap_script(lan, regenerate=force_tls)}\n' if lan else ''
    web_exec = f'{web_tls}sh -c {shlex.quote(command)}'
    return f'''set -eu
awk '$2 == "/srv" && $3 == "btrfs" {{found=1}} END {{exit !found}}' /proc/mounts || {{ echo 'SSD /srv not mounted as Btrfs' >&2; exit 1; }}
[ "$(lxc-info -P /srv/lxc -n {container} -sH < /dev/null)" = RUNNING ]
# Check actual container filesystem, not a guessed rootfs path.
hostdev=$(stat -c %d /srv)
containerdev=$(lxc-attach -P /srv/lxc -n {container} -- stat -c %d / < /dev/null)
[ "$hostdev" = "$containerdev" ] || {{ echo 'Container root is not on /srv filesystem' >&2; exit 1; }}
lxc-attach -P /srv/lxc -n {container} -- sh -c {shlex.quote(web_exec)}
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
    parser.add_argument('--regen-tls', action='store_true', help='Force TLS regeneration in container (web mode only)')
    parser.add_argument('--reset', action='store_true', help='Recover interrupted web deploy state and clear web-rollback snapshot')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('host must be user@hostname or user@IPv4')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', args.container):
        parser.error('invalid container name')
    if args.regen_tls and not args.web_lan:
        parser.error('--regen-tls requires --web-lan')
    payload, files = bundle(ROOT)
    release = uuid.uuid4().hex
    try:
        command = remote_script(args.container, release, lan=args.web_lan, force_tls=args.regen_tls)
    except ValueError as error:
        parser.error(str(error))
    if args.reset:
        if args.dry_run:
            print('Reset command:')
            print(remote_reset_script(args.container))
            return 0
        reset_result = run_ssh(args.host, remote_reset_script(args.container), b'')
        return reset_result.returncode
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
            recover_result = run_ssh(args.host, remote_recovery_script(cleanup=True), b'')
            if recover_result.returncode != 0:
                print(f'Attempt {attempt}: recovery failed')
                return recover_result.returncode
            print(f'Attempt {attempt}/{args.retries}: retrying deployment')
        # Ignore broken/implicit client proxy config; retain known-host verification and ssh-agent.
        result = run_ssh(args.host, command, payload)
        if result.returncode == 0:
            if args.web_lan:
                sync_result = sync_ca_to_router(args.host, args.container)
                return sync_result
            return 0
        if attempt < args.retries:
            time.sleep(2 ** (attempt - 1))
            print(f'Attempt {attempt}/{args.retries}: failed, retrying')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
