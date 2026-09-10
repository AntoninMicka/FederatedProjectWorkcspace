# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Generate the opt-in Debian LXC viewer installation; secrets are never bundled."""
import ipaddress
import shlex


def install_script(release, lan):
    network = ipaddress.ip_network(lan)
    if network.version != 4 or not network.is_private or network.prefixlen < 8:
        raise ValueError('Expected private IPv4 LAN')
    if len(release) != 32 or any(c not in '0123456789abcdef' for c in release):
        raise ValueError('Invalid release')
    unit = f'''# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
[Unit]
Description=Federated workspace HTTPS viewer
After=network.target
[Service]
User=federated-workspace
Group=federated-workspace
WorkingDirectory=/opt/federated-workspace/current
ExecStart=/opt/federated-workspace/current/.venv/bin/python -m spikes.web_server --lan {network} --cert /etc/federated-workspace/tls.crt --key /etc/federated-workspace/tls.key --token-file /var/lib/federated-workspace/access-key --node /var/lib/federated-workspace/node.json
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
[ -f "$config/tls.crt" ] && [ -f "$config/tls.key" ] && [ -f "$config/ca.crt" ] || {{ echo 'Provision TLS certificate, key and CA first' >&2; exit 1; }}
[ ! -L "$base" ] && [ ! -L "$base/releases" ]
mkdir -p "$base/releases"
[ ! -L "$base/web-deploy.lock" ]
exec 9>"$base/web-deploy.lock"
flock -n 9
[ ! -e "$base/web-rollback" ] || {{ echo 'Recover interrupted web deployment first; see README' >&2; exit 1; }}
release="$base/releases/{release}"
mkdir "$release"
tar -xzf - -C "$release" --no-same-owner --no-same-permissions
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates poppler-utils
id federated-workspace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/federated-workspace --shell /usr/sbin/nologin federated-workspace
install -d -m 0700 -o federated-workspace -g federated-workspace /var/lib/federated-workspace
chown root:federated-workspace "$config" "$config/tls.crt" "$config/tls.key" "$config/ca.crt"
chmod 0750 "$config"
chmod 0640 "$config/tls.crt" "$config/tls.key" "$config/ca.crt"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install -r "$release/requirements.txt"
# Release is immutable to the service account, but traversable/readable.
chmod 0755 "$base" "$base/releases" "$release"
chmod -R a+rX "$release"
(cd "$release" && runuser -u federated-workspace -- "$release/.venv/bin/python" -m spikes.web_bootstrap /var/lib/federated-workspace)
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
trap 'rollback' EXIT
printf %s {shlex.quote(unit)} > "$unit.new"
mv -f "$unit.new" "$unit"
ln -s "releases/{release}" "$base/.current-{release}"
mv -Tf "$base/.current-{release}" "$base/current"
systemctl daemon-reload
systemctl enable federated-workspace.service
systemctl restart federated-workspace.service
# Give startup a bounded interval. The service validates token and TLS on start.
i=0
until systemctl is-active --quiet federated-workspace.service; do
 i=$((i+1)); [ "$i" -lt 10 ]; sleep 1
done
python3 -c 'import http.client,ssl,time; c=ssl.create_default_context(cafile="/etc/federated-workspace/ca.crt"); c.check_hostname=False; time.sleep(1); h=http.client.HTTPSConnection("127.0.0.1",8443,context=c,timeout=3); h.request("GET","/"); assert h.getresponse().status==200; h.close()'
trap - EXIT
rm -r "$base/web-rollback"
echo 'HTTPS viewer installed; access key remains in /var/lib/federated-workspace/access-key'
'''
