# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native deploy orchestration over exactly one framed SSH process."""
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import uuid

from scripts.deploy_omnia import bundle, remote_script, remote_recovery_script, remote_reset_script
from spikes.administration import Administration
from spikes.project_creation import ProjectCreation
from spikes.lxc_setup import ACTOR, call, peer

ROOT = Path(__file__).resolve().parents[1]
RUNNER = '''import base64,json,subprocess,sys
for line in sys.stdin:
 r=json.loads(line)
 if r.get('quit'):break
 p=subprocess.run(['sh','-c',r['command']],input=base64.b64decode(r['payload']),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 print(json.dumps({'code':p.returncode,'out':base64.b64encode(p.stdout).decode(),'err':base64.b64encode(p.stderr).decode()}),flush=True)
'''


class SSHSession:
    def __init__(self, host):
        self.directory = tempfile.TemporaryDirectory(prefix='fw-ssh-')
        root = Path(self.directory.name)
        helper = root / 'askpass'
        python = 'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); from spikes.ssh_askpass import main; raise SystemExit(main())'
        helper.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, '-c', python]) + ' "$@"\n')
        helper.chmod(0o700)
        self.errors = tempfile.TemporaryFile()
        env = dict(os.environ, SSH_ASKPASS=str(helper), SSH_ASKPASS_REQUIRE='force')
        self.process = subprocess.Popen(['ssh', '-T', '-F', '/dev/null', '-o', 'StrictHostKeyChecking=yes',
                                         '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
                                         '-o', 'ServerAliveCountMax=3', host,
                                         'python3 -u -c ' + shlex.quote(RUNNER)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, env=env,
                                        start_new_session=True)

    def run(self, command, payload=b''):
        request = json.dumps(dict(command=command, payload=base64.b64encode(payload).decode())).encode() + b'\n'
        self.process.stdin.write(request); self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            self.errors.seek(0)
            raise RuntimeError('SSH connection closed: ' + self.errors.read().decode(errors='replace'))
        result = json.loads(line)
        out, err = (base64.b64decode(result[key]).decode(errors='replace') for key in ('out', 'err'))
        if result['code']:
            raise RuntimeError(out + '\n' + err)
        return out + ('\n' + err if err else '')

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write(b'{"quit":true}\n'); self.process.stdin.flush()
                self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
        finally:
            self.process.stdin.close(); self.process.stdout.close()
            self.errors.close(); self.directory.cleanup()


def deploy(node, host, container, lan, desktop_endpoint, mode, progress, *, remembered=None):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', host):
        raise ValueError('Expected SSH user@host')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', container):
        raise ValueError('Invalid container name')
    network = ipaddress.ip_network(lan)
    if network.version != 4 or not network.is_private or network.prefixlen < 8:
        raise ValueError('Expected private IPv4 LAN')
    if mode not in {'install', 'update', 'recover', 'reset', 'address'}:
        raise ValueError('Invalid deployment mode')
    if mode == 'install':
        Administration.endpoint(desktop_endpoint)
    if mode == 'address' and not remembered:
        raise ValueError('Select a remembered deployment before updating its container address')
    attach = f'lxc-attach -P /srv/lxc -n {container} -- '
    payload = bundle(ROOT)[0] if mode in {'install', 'update'} else b''
    session = SSHSession(host)
    installed = False
    try:
        progress('SSH connected; checking container.')
        if mode in {'recover', 'reset'}:
            command = (attach + 'sh -c ' + shlex.quote(remote_recovery_script(cleanup=True))
                       if mode == 'recover' else remote_reset_script(container))
            progress(session.run(command)); return
        previous = session.run(attach + "sh -c 'if [ -L /opt/federated-workspace/current ]; then echo existing; else echo new; fi'").strip()
        if mode != 'address':
            progress(session.run(remote_script(container, uuid.uuid4().hex, lan=str(network), update_only=mode == 'update'), payload))
            installed = True
        addresses = session.run(f'lxc-info -P /srv/lxc -n {container} -iH').split()
        ips = sorted({str(ipaddress.ip_address(value)) for value in addresses
                      if ipaddress.ip_address(value).version == 4 and ipaddress.ip_address(value) in network})
        if len(ips) != 1:
            raise ValueError('Container must have exactly one IPv4 in the configured LAN; found: ' + ', '.join(ips))
        endpoint = f'https://{ips[0]}:8443'
        progress('Container address detected: ' + endpoint)
        setup_command = attach + "sh -c " + shlex.quote('cd /opt/federated-workspace/current && runuser -u federated-workspace -- .venv/bin/python -m spikes.lxc_setup')
        def remote(request):
            return json.loads(session.run(setup_command, json.dumps(request).encode()))
        identity = remote({'action': 'inspect'})
        target = dict(host=host, container=container, lan=str(network), desktop_endpoint=desktop_endpoint,
                      endpoint=endpoint, node_id=identity['node_id'], fingerprint=identity['mapping_identity']['fingerprint'])
        if remembered and (target['node_id'] != remembered['node_id'] or target['fingerprint'] != remembered['fingerprint']):
            raise ValueError('Remembered container identity changed; refusing automatic replacement')
        if mode == 'address':
            check = ('import http.client,ssl; '
                     'c=ssl.create_default_context(cafile="/etc/federated-workspace/ca.crt"); '
                     f'h=http.client.HTTPSConnection({ips[0]!r},8443,context=c,timeout=5); '
                     'h.request("GET","/"); assert h.getresponse().status==200; h.close()')
            session.run(attach + 'python3 -c ' + shlex.quote(check))
            service = Administration(node, deployment='desktop')
            view = service.request(ACTOR, {'action': 'list'})
            existing = next((p for p in view['peers'] if p['id'] == target['node_id']), None)
            if not existing or existing['fingerprint'] != target['fingerprint'] or existing['trust'] != 'approved':
                raise ValueError('Container identity is not an approved desktop peer; resolve in federation management')
            call(service, 'update-peer-endpoint', node_id=target['node_id'], endpoint=endpoint)
            progress('Container TLS and identity verified; desktop peer address updated. No software or certificates changed.')
            return target
        certificate = session.run(attach + 'cat /etc/federated-workspace/ca.crt').encode()
        if not certificate.startswith(b'-----BEGIN CERTIFICATE-----'):
            raise ValueError('Invalid public CA response')
        session.run('umask 022; cat > /etc/federated-workspace-ca.pem; chmod 0644 /etc/federated-workspace-ca.pem', certificate)
        from spikes.network_backend import trust_ca
        trust_ca(node, target['node_id'], certificate)
        progress('Public CA copied to router; private keys remain in LXC.')
        if mode == 'update':
            progress('Update complete. Existing accounts and pairing unchanged.'); return target
        if previous != 'new':
            progress('Existing installation preserved. Automatic administrator provisioning and pairing skipped.'); return target
        service = Administration(node, deployment='desktop')
        if not os.path.lexists(service.node) and service.repo.exists():
            raise ValueError('Missing original desktop node.json; restore it, do not replace its identity')
        ProjectCreation(node).initialize_node()
        local = service.request(ACTOR, {'action': 'list'})
        user = local['users'][0]
        other = remote(dict(action='initialize', desktop_node_id=local['node_id'], desktop_user_id=user['id'],
                            name=user['name'], new_installation=True))
        progress('Local administrator created on LXC. Its access key remains in .node.json.administration/deployment-admin-key on LXC.')
        progress('Desktop pin: ' + local['mapping_identity']['fingerprint'] + '\nLXC pin: ' + other['identity']['fingerprint'])
        remote(dict(action='peer', node_id=local['node_id'], name='Desktop ' + user['name'],
                    endpoint=desktop_endpoint, fingerprint=local['mapping_identity']['fingerprint']))
        peer(service, other['node_id'], 'LXC ' + container, endpoint, other['identity']['fingerprint'])
        progress('Both nodes approved through the authorized SSH setup. Network communication is not yet verified.')
        remote_view = remote({'action': 'inspect'})
        local_projects = {p['project_id'] for p in ProjectCreation(node).projects.catalog()} if False else set()
        # No project data is copied by deployment. New nodes usually have no common scope.
        from spikes.configuration import parse_node, read_config
        local_projects = {p['project_id'] for p in parse_node(read_config(service.node), location=service.node)['projects']}
        remote_projects = session.run(attach + "cat /var/lib/federated-workspace/node.json")
        common = sorted(local_projects & {p['project_id'] for p in json.loads(remote_projects)['projects']})
        if not common:
            progress('Node pairing complete. Account mapping awaits a common registered project; no synchronization has been enabled.'); return target
        view = call(service, 'propose-mapping', local_user_id=user['id'], peer_node_id=other['node_id'],
                    peer_user_id=other['user_id'], project_ids=common[:16])
        mapping = view['mappings'][-1]['spec']['id']
        view = call(service, 'confirm-mapping', mapping_id=mapping)
        confirmed = remote(dict(action='confirm', envelope=view['mapping_envelope']))
        call(service, 'import-mapping', envelope=confirmed['mapping_envelope'])
        progress('Bilateral project account mapping confirmed. Data transport is not implemented.')
        return target
    except Exception as exc:
        if installed:
            raise RuntimeError('Application deployed, but subsequent setup failed. Do not reset the working application. '
                               'Inspect federation management before retrying pairing.\n' + str(exc)) from exc
        if mode == 'address':
            raise RuntimeError('Container address update failed. Verify TLS SAN and identity; do not reset the application.\n' + str(exc)) from exc
        raise RuntimeError('Deployment failed. Use Recover first; Reset discards the rollback snapshot and is not rollback.\n' + str(exc)) from exc
    finally:
        session.close()
