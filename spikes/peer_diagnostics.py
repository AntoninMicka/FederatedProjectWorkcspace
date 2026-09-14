# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit bilateral connectivity check using one authorized SSH session."""
import base64
import json
from pathlib import Path
import re
import shlex

from spikes.administration import Administration
from spikes.deployment_targets import DeploymentTargets
from spikes.federation_probe import check_peer
from spikes.lxc_setup import ACTOR

REMOTE = '''import base64,json,sys
from spikes.administration import Administration
from spikes.federation_probe import check_peer
from spikes.lxc_setup import ACTOR,call
from spikes.network_backend import trust_ca,private_root
r=json.load(sys.stdin)
a=Administration('/var/lib/federated-workspace/node.json')
v=a.request(ACTOR,{'action':'list'})
if v['node_id']!=r['remote_node_id'] or v['mapping_identity']['fingerprint']!=r['remote_pin']:
 raise ValueError('LXC identity changed; nothing updated')
p=next((p for p in v['peers'] if p['id']==r['desktop_node_id']),None)
if not p or p['trust']!='approved' or p['fingerprint']!=r['desktop_pin']:
 raise ValueError('Desktop is not an approved peer with its original pin; nothing updated')
trust_ca(a.node,r['desktop_node_id'],base64.b64decode(r['ca'],validate=True))
call(a,'update-peer-endpoint',node_id=r['desktop_node_id'],endpoint=r['desktop_endpoint'])
ca=private_root(a.node)/(r['desktop_node_id']+'-ca.pem')
print(check_peer(r['desktop_endpoint'],ca,r['desktop_node_id'],r['desktop_pin']))
'''


def check_both(backend, target, peer_ca):
    from spikes.lxc_deployment import SSHSession
    if not backend.endpoint or not backend.config:
        raise ValueError('Nejdříve zapněte desktopový HTTPS backend.')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', target['host']):
        raise ValueError('Invalid remembered SSH host')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', target['container']):
        raise ValueError('Invalid remembered container')
    service = Administration(backend.node, deployment='desktop')
    view = service.request(ACTOR, {'action': 'list'})
    peer = next((p for p in view['peers'] if p['id'] == target['node_id']), None)
    if not peer or peer['trust'] != 'approved' or peer['fingerprint'] != target['fingerprint']:
        raise ValueError('LXC není schválený peer s původním pinem. Důvěra nebude změněna.')
    try:
        forward = check_peer(peer['endpoint'], peer_ca, peer['id'], peer['fingerprint'])
    except Exception as exc:
        raise ValueError('Desktop → LXC selhalo; na LXC se nic neměnilo.\n' + str(exc)) from exc
    certificate = Path(backend.config['ca']).read_bytes()
    if not certificate.startswith(b'-----BEGIN CERTIFICATE-----') or len(certificate) > 65536:
        raise ValueError('Desktop → LXC prošlo, ale veřejná CA desktopu je neplatná; přenos neproveden.')
    request = dict(remote_node_id=target['node_id'], remote_pin=target['fingerprint'],
                   desktop_node_id=view['node_id'], desktop_pin=view['mapping_identity']['fingerprint'],
                   desktop_endpoint=backend.endpoint, ca=base64.b64encode(certificate).decode())
    command = (f"lxc-attach -P /srv/lxc -n {target['container']} -- sh -c " +
               shlex.quote('cd /opt/federated-workspace/current && runuser -u federated-workspace -- .venv/bin/python -c ' + shlex.quote(REMOTE)))
    session = SSHSession(target['host'])
    try:
        try:
            reverse = session.run(command, json.dumps(request).encode()).strip()
        except Exception as exc:
            raise ValueError('Desktop → LXC prošlo. LXC → desktop nebo SSH příprava selhala.\n'
                             'CA a adresa desktopového peeru již mohou být aktualizované; '
                             'opakování je bezpečné, web neresetujte.\n' + str(exc)) from exc
    finally:
        session.close()
    result = 'Desktop → LXC: ' + forward + '\nLXC → desktop: ' + reverse
    try:
        DeploymentTargets(backend.node).remember(dict(target, desktop_endpoint=backend.endpoint))
    except Exception as exc:
        result += '\nOba směry ověřeny, ale lokální zapamatování adresy selhalo: ' + str(exc)
    return result + '\nOvěřena pouze dostupnost/TLS/identita. Projektová synchronizace se nezapíná.'
