# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Generate the opt-in Debian LXC viewer installation; secrets are never bundled."""
import ipaddress
import re
import shlex


def validate_hostname(hostname):
    if hostname is None:
        return None
    if (not isinstance(hostname, str) or len(hostname) > 253
            or hostname.endswith('.') or '.' not in hostname):
        raise ValueError('Expected a DNS hostname such as workspace.example.internal')
    labels = hostname.split('.')
    if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
           for label in labels):
        raise ValueError('Expected a DNS hostname such as workspace.example.internal')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname.lower()
    raise ValueError('DNS hostname must not be an IP address')


def install_script(release, lan, *, hostname=None, update_only=False):
    network = ipaddress.ip_network(lan)
    if network.version != 4 or not network.is_private or network.prefixlen < 8:
        raise ValueError('Expected private IPv4 LAN')
    if len(release) != 32 or any(c not in '0123456789abcdef' for c in release):
        raise ValueError('Invalid release')
    hostname = validate_hostname(hostname)
    hostname_preflight = ''
    if hostname:
        hostname_preflight = f'''command -v openssl >/dev/null 2>&1 || {{ echo 'openssl is required for DNS certificate validation' >&2; exit 1; }}
openssl x509 -in "$config/tls.crt" -noout -checkhost {hostname} >/dev/null 2>&1 || {{ echo 'TLS certificate does not cover configured DNS hostname' >&2; exit 1; }}'''
    preparation = '''
missing=""
for package in python3 python3-venv git ca-certificates poppler-utils; do
 if [ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || :)" != 'install ok installed' ]; then
  missing="$missing $package"
 fi
done
if [ -n "$missing" ]; then
 echo "Installing missing system dependencies:$missing"
 export DEBIAN_FRONTEND=noninteractive
 apt-get update
 apt-get install -y --no-install-recommends $missing
else
 echo 'System dependencies already installed; skipping apt'
fi
id federated-workspace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/federated-workspace --shell /usr/sbin/nologin federated-workspace
install -d -m 0700 -o federated-workspace -g federated-workspace /var/lib/federated-workspace
chown root:federated-workspace "$config" "$config/tls.crt" "$config/tls.key" "$config/ca.crt"
chmod 0750 "$config"
chmod 0640 "$config/tls.crt" "$config/tls.key" "$config/ca.crt"
'''
    preflight = ''
    bootstrap = '(cd "$release" && runuser -u federated-workspace -- "$release/.venv/bin/python" -m spikes.web_bootstrap /var/lib/federated-workspace)'
    if update_only:
        preparation = "echo 'Application-only update; system provisioning skipped'"
        bootstrap = "echo 'Existing node identity and credentials preserved; bootstrap skipped'"
        preflight = '''
[ -L "$base/current" ] && [ -x "$base/current/.venv/bin/python" ] && [ -f "$unit" ] || { echo 'No existing web installation; run deployment without --update-only' >&2; exit 1; }
id federated-workspace >/dev/null 2>&1
[ -s /var/lib/federated-workspace/node.json ] && [ -s /var/lib/federated-workspace/access-key ] || { echo 'Existing node configuration is incomplete; use normal deployment for diagnosis' >&2; exit 1; }
for command in python3 git pdftoppm runuser; do
 command -v "$command" >/dev/null 2>&1 || { echo "Missing dependency: $command; run deployment without --update-only" >&2; exit 1; }
done
python3 -c 'import sys,venv; assert sys.version_info >= (3,11)'
'''
    hostname_option = f' --hostname {hostname}' if hostname else ''
    unit = f'''# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
[Unit]
Description=Federated workspace HTTPS viewer
After=network.target
[Service]
User=federated-workspace
Group=federated-workspace
WorkingDirectory=/opt/federated-workspace/current
ExecStart=/opt/federated-workspace/current/.venv/bin/python -m spikes.web_server --lan {network} --cert /etc/federated-workspace/tls.crt --key /etc/federated-workspace/tls.key --token-file /var/lib/federated-workspace/access-key --node /var/lib/federated-workspace/node.json{hostname_option}
Restart=on-failure
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/federated-workspace
PrivateTmp=true
[Install]
WantedBy=multi-user.target
'''
    # All durable deployment changes have a rollback snapshot before publication.
    return f'''set -eu
umask 077
. /etc/os-release
[ "$ID" = debian ]
base=/opt/federated-workspace
config=/etc/federated-workspace
unit=/etc/systemd/system/federated-workspace.service
{preflight}
[ -f "$config/tls.crt" ] && [ -f "$config/tls.key" ] && [ -f "$config/ca.crt" ] || {{ echo 'Provision TLS certificate, key and CA first' >&2; exit 1; }}
{hostname_preflight}
[ ! -L "$base" ] && [ ! -L "$base/releases" ]
mkdir -p "$base/releases"
[ ! -L "$base/web-deploy.lock" ]
exec 9>"$base/web-deploy.lock"
flock -n 9
[ ! -e "$base/web-rollback" ] || {{ echo 'Recover interrupted web deployment first; see README' >&2; exit 1; }}
release="$base/releases/{release}"
mkdir "$release"
tar -xzf - -C "$release" --no-same-owner --no-same-permissions
{preparation}
echo 'Preparing isolated application release and Python dependencies'
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install -r "$release/requirements.txt"
# Release is immutable to the service account, but traversable/readable.
chmod 0755 "$base" "$base/releases" "$release"
chmod -R a+rX "$release"
{bootstrap}
# Snapshot persists after SIGKILL/power loss. Recovery commands are in README.
rm -rf "$base/.web-rollback-preparing"
mkdir "$base/.web-rollback-preparing"
[ ! -e "$base/current" ] || [ -L "$base/current" ]
readlink "$base/current" > "$base/.web-rollback-preparing/previous" || :
if [ -f "$unit" ]; then cp -p "$unit" "$base/.web-rollback-preparing/unit"; fi
systemctl is-enabled --quiet federated-workspace.service && touch "$base/.web-rollback-preparing/enabled" || :
systemctl is-active --quiet federated-workspace.service && touch "$base/.web-rollback-preparing/active" || :
sync
mv "$base/.web-rollback-preparing" "$base/web-rollback"
sync
rollback() {{
 systemctl stop federated-workspace.service || :
 if [ -s "$base/web-rollback/previous" ]; then
  ln -s "$(cat "$base/web-rollback/previous")" "$base/.restore-{release}"
  mv -Tf "$base/.restore-{release}" "$base/current"
 else rm -f "$base/current"; fi
 if [ -f "$base/web-rollback/unit" ]; then cp -p "$base/web-rollback/unit" "$unit"; else rm -f "$unit"; fi
 systemctl daemon-reload
 if [ -f "$base/web-rollback/enabled" ]; then systemctl enable federated-workspace.service; else systemctl disable federated-workspace.service || :; fi
 if [ -f "$base/web-rollback/active" ]; then systemctl start federated-workspace.service; fi
}}
trap 'status=$?; rollback || echo "Rollback incomplete; use --recover" >&2; exit "$status"' EXIT
printf %s {shlex.quote(unit)} > "$unit.new"
mv -f "$unit.new" "$unit"
ln -s "releases/{release}" "$base/.current-{release}"
mv -Tf "$base/.current-{release}" "$base/current"
systemctl daemon-reload
systemctl enable federated-workspace.service
systemctl restart federated-workspace.service
# A Type=simple unit becomes active before Python imports and recovery finish. Probe the
# actual HTTPS listener for a bounded interval, especially on slower ARM routers.
if ! python3 -c '
import http.client, ssl, time
context = ssl.create_default_context(cafile="/etc/federated-workspace/ca.crt")
context.check_hostname = False
deadline = time.monotonic() + 45
while True:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SystemExit(1)
    connection = http.client.HTTPSConnection(
        "127.0.0.1", 8443, context=context, timeout=min(2, remaining))
    try:
        connection.request("GET", "/")
        if connection.getresponse().status == 200:
            raise SystemExit(0)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    time.sleep(min(1, max(0, deadline - time.monotonic())))
'; then
 if systemctl is-active --quiet federated-workspace.service; then
  echo 'New workspace service did not expose HTTPS within 45 seconds' >&2
 else
  echo 'New workspace service exited before HTTPS became ready' >&2
 fi
 systemctl --no-pager --full status federated-workspace.service >&2 || :
 journalctl -u federated-workspace.service -n 120 --no-pager >&2 || :
 exit 70
fi
trap - EXIT
rm -r "$base/web-rollback"
echo 'HTTPS viewer installed; access key remains in /var/lib/federated-workspace/access-key'
'''
