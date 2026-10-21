# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""SSH-authorized setup of a new web node; never exports credentials."""
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid5

from spikes.administration import Administration, identifier, label
from spikes.federation_accounts import MappingSignatures
from spikes.journal import sync_dir

ACTOR = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}


def call(service, action, **fields):
    view = service.request(ACTOR, {'action': 'list'})
    return service.request(ACTOR, dict(action=action, expected_commit=view['commit_id'], **fields))


def peer(service, node_id, name, endpoint, fingerprint):
    view = service.request(ACTOR, {'action': 'list'})
    existing = next((p for p in view['peers'] if p['id'] == node_id), None)
    if existing:
        if existing['fingerprint'] != fingerprint or existing['endpoint'] != endpoint or existing['trust'] != 'approved':
            raise ValueError('Existing peer differs or is not approved; resolve in federation management, no automatic overwrite')
        return view
    call(service, 'add-peer', node_id=node_id, name=name, endpoint=endpoint, fingerprint=fingerprint)
    return call(service, 'set-trust', node_id=node_id, trust='approved')


def setup(request):
    service = Administration('/var/lib/federated-workspace/node.json')
    action = request['action']
    if action == 'inspect':
        return service.request(ACTOR, {'action': 'list'})
    if action == 'initialize':
        identifier(request['desktop_node_id']); identifier(request['desktop_user_id'])
        name = label(request['name'])
        # Deterministic identity makes retry safe after a lost response/ref publication.
        with service.locked() as (git, state, commit, node):
            user_id = str(uuid5(UUID(node['id']), request['desktop_node_id'] + ':' + request['desktop_user_id']))
            user = next((u for u in state['users'] if u['id'] == user_id), None)
            key = service.root / 'deployment-admin-key'
            if user:
                if not user['active'] or user['node_role'] != 'federation-admin':
                    raise ValueError('Deployment administrator was changed; no automatic privilege restoration')
            else:
                if state['users'] or not request.get('new_installation'):
                    raise ValueError('Existing installation: administrator accounts are not provisioned automatically')
                reference, token = service.issue(user_id)
                # Key stays on this node. Publish before registry; an orphan cannot authenticate.
                if os.path.lexists(key):
                    raise ValueError('Interrupted administrator provisioning; preserve deployment-admin-key and resolve before retry')
                fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as handle:
                    handle.write(token + '\n'); handle.flush(); os.fsync(handle.fileno())
                sync_dir(service.root)
                state['users'].append(dict(id=user_id, home_node_id=node['id'], name=name, active=True,
                                          node_role='federation-admin', memberships={}, credential_ref=reference, revision=1))
                service.publish(git, state, commit)
        return {'node_id': node['id'], 'user_id': user_id, 'identity': MappingSignatures(service.root).identity()}
    if action == 'peer':
        return peer(service, request['node_id'], request['name'], request['endpoint'], request['fingerprint'])
    if action == 'confirm':
        view = call(service, 'import-mapping', envelope=request['envelope'])
        return call(service, 'confirm-mapping', mapping_id=request['envelope']['spec']['id'])
    raise ValueError('Unknown setup action')


def main():
    try:
        result = setup(json.load(sys.stdin))
        print(json.dumps(result))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
