# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Authenticated desktop-to-server enrollment for client-server peers."""
import base64
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.administration import Administration, AccessDenied, identifier, label
from spikes.federation_accounts import MappingSignatures, canonical, openssl
from spikes.network_backend import private_root, publish
from spikes.project_creation import ProjectCreation


PATH = '/v1/federation/enroll'
MAX_RESPONSE = 16 * 1024
PURPOSE = 'client-server-enrollment-v1'


def _payload(value, *, response=False):
    common = {'schema_version', 'purpose', 'operation_id', 'server_node_id',
              'client_node_id', 'client_user_id', 'client_name'}
    expected = common | ({'server_user_id', 'node_credential',
                          'credential_revision'} if response else set())
    if (not isinstance(value, dict) or set(value) != expected
            or value.get('schema_version') != 1 or value.get('purpose') != PURPOSE):
        raise ValueError('Invalid enrollment payload')
    for field in ('operation_id', 'server_node_id', 'client_node_id',
                  'client_user_id'):
        identifier(value[field])
    label(value['client_name'])
    if response:
        identifier(value['server_user_id'])
        if (not isinstance(value['node_credential'], str)
                or not 43 <= len(value['node_credential']) <= 128
                or not value['node_credential'].replace('-', '').replace('_', '').isalnum()
                or type(value['credential_revision']) is not int
                or value['credential_revision'] < 1):
            raise ValueError('Invalid enrollment credential')
    return value


def _sign(root, payload):
    identity = MappingSignatures(root)
    public = identity.public_key()
    with tempfile.TemporaryDirectory(dir=root) as directory:
        message = Path(directory) / 'enrollment'
        message.write_bytes(canonical(payload))
        signature = openssl('pkeyutl', '-sign', '-rawin', '-inkey',
                            str(identity.key), '-in', str(message))
    return {'payload': payload,
            'public_key': base64.b64encode(public).decode(),
            'signature': base64.b64encode(signature).decode()}


def _verify(envelope, fingerprint, *, response=False):
    if not isinstance(envelope, dict) or set(envelope) != {
            'payload', 'public_key', 'signature'}:
        raise ValueError('Invalid enrollment envelope')
    payload = _payload(envelope['payload'], response=response)
    if (not isinstance(envelope['public_key'], str)
            or not isinstance(envelope['signature'], str)):
        raise ValueError('Invalid enrollment signature')
    public = base64.b64decode(envelope['public_key'], validate=True)
    signature = base64.b64decode(envelope['signature'], validate=True)
    if (len(public) != 44 or public[:12] != bytes.fromhex('302a300506032b6570032100')
            or len(signature) != 64
            or hashlib.sha256(public).hexdigest() != fingerprint):
        raise ValueError('Enrollment identity does not match the pinned node')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'public').write_bytes(public)
        (root / 'signature').write_bytes(signature)
        (root / 'payload').write_bytes(canonical(payload))
        openssl('pkeyutl', '-verify', '-pubin', '-keyform', 'DER',
                '-inkey', str(root / 'public'), '-rawin',
                '-in', str(root / 'payload'),
                '-sigfile', str(root / 'signature'))
    return payload


def request_envelope(service, server_node_id, operation_id):
    """Create proof that the desktop owns its node identity and local account."""
    identifier(server_node_id); identifier(operation_id)
    with service.locked() as (_, state, _, _):
        peer = next((item for item in state['peers']
                     if item['id'] == server_node_id), None)
        if (not peer or peer['relationship_type'] != 'client-server'
                or peer['local_role'] != 'client'
                or peer['trust'] == 'revoked'):
            raise AccessDenied('Server is not a pending client-server peer')
        payload = {
            'schema_version': 1, 'purpose': PURPOSE,
            'operation_id': operation_id,
            'server_node_id': server_node_id,
            'client_node_id': state['node_id'],
            'client_user_id': ProjectCreation(service.node).author_id(),
            'client_name': label(os.environ.get('USER') or 'Desktop user'),
        }
        return _sign(service.root, payload), dict(peer)


def accept_on_server(service, actor, envelope):
    """Commit server trust/account binding, then rotate a scoped credential."""
    if service.deployment != 'web' or not actor or not actor.get('id'):
        raise AccessDenied('Enrollment requires an active server account')
    if not isinstance(envelope, dict) or not isinstance(envelope.get('payload'), dict):
        raise ValueError('Invalid enrollment envelope')
    if not isinstance(envelope.get('public_key'), str):
        raise ValueError('Invalid enrollment public key')
    public = base64.b64decode(envelope['public_key'], validate=True)
    fingerprint = hashlib.sha256(public).hexdigest()
    payload = _verify(envelope, fingerprint)
    with service.locked() as (git, state, commit, _):
        if payload['server_node_id'] != state['node_id']:
            raise AccessDenied('Enrollment targets another server')
        peer = next((item for item in state['peers']
                     if item['id'] == payload['client_node_id']), None)
        binding = {'local_user_id': actor['id'],
                   'remote_user_id': payload['client_user_id']}
        if peer:
            if (peer['relationship_type'] != 'client-server'
                    or peer['local_role'] != 'server'
                    or peer['trust'] == 'revoked'
                    or peer['fingerprint'] != fingerprint):
                raise AccessDenied('Existing peer does not match this client enrollment')
            if peer['account_binding'] not in (None, binding):
                raise AccessDenied('Client is already bound to another server account')
            changed = (peer['trust'] != 'approved'
                       or peer['account_binding'] != binding
                       or peer['name'] != payload['client_name'])
            if changed:
                peer.update(name=payload['client_name'], trust='approved',
                            account_binding=binding,
                            revision=peer['revision'] + 1)
        else:
            state['peers'].append({
                'id': payload['client_node_id'], 'name': payload['client_name'],
                'endpoint': None, 'fingerprint': fingerprint,
                'trust': 'approved', 'revision': 1,
                'relationship_type': 'client-server', 'local_role': 'server',
                'account_binding': binding,
            })
            changed = True
        if changed:
            service.publish(git, state, commit,
                            message='Administration: enroll-client\n')
        token, revision = service.issue_node_credential(
            payload['client_node_id'], actor['id'], payload['client_user_id'])
    response = dict(payload, server_user_id=actor['id'],
                    node_credential=token, credential_revision=revision)
    return _sign(service.root, response)


def accept_on_client(service, server_node_id, operation_id, envelope):
    """Verify the server response, save the credential, then publish trust."""
    identifier(server_node_id); identifier(operation_id)
    with service.locked() as (_, state, _, _):
        peer = next((item for item in state['peers']
                     if item['id'] == server_node_id), None)
        if (not peer or peer['relationship_type'] != 'client-server'
                or peer['local_role'] != 'client' or peer['trust'] == 'revoked'):
            raise AccessDenied('Server is not a client-server peer')
        fingerprint = peer['fingerprint']
    payload = _verify(envelope, fingerprint, response=True)
    local_user = ProjectCreation(service.node).author_id()
    if (payload['operation_id'] != operation_id
            or payload['server_node_id'] != server_node_id
            or payload['client_user_id'] != local_user):
        raise AccessDenied('Enrollment response does not match this request')
    with service.locked() as (git, state, commit, _):
        peer = next((item for item in state['peers']
                     if item['id'] == server_node_id), None)
        if (not peer or peer['relationship_type'] != 'client-server'
                or peer['local_role'] != 'client' or peer['trust'] == 'revoked'
                or peer['fingerprint'] != fingerprint):
            raise AccessDenied('Server relationship changed during enrollment')
        binding = {'local_user_id': local_user,
                   'remote_user_id': payload['server_user_id']}
        if peer['account_binding'] not in (None, binding):
            raise AccessDenied('Server is already bound to another account')
        root = private_root(service.node)
        credential_path = root / (server_node_id + '-enrollment.token')
        publish(root, credential_path, payload['node_credential'].encode())
        if peer['trust'] != 'approved' or peer['account_binding'] != binding:
            peer.update(trust='approved', account_binding=binding,
                        revision=peer['revision'] + 1)
            commit = service.publish(git, state, commit,
                                     message='Administration: complete-enrollment\n')
        return service.public(state, commit, {
            'id': None, 'node_role': 'federation-admin', 'memberships': {}})


def enroll(node, server_node_id, access_key, *, operation_id=None, ca=None):
    """Run one bounded TLS enrollment without persisting the user access key."""
    if (not isinstance(access_key, str) or not 43 <= len(access_key) <= 128
            or not access_key.replace('-', '').replace('_', '').isalnum()):
        raise ValueError('Invalid server access key')
    service = Administration(node, deployment='desktop')
    operation_id = operation_id or str(uuid4())
    request, peer = request_envelope(service, server_node_id, operation_id)
    parsed = urlsplit(peer['endpoint'])
    if (parsed.scheme != 'https' or not parsed.hostname
            or parsed.path not in ('', '/') or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('Invalid enrollment endpoint')
    address = ipaddress.ip_address(parsed.hostname)
    if (address.version != 4 or address.is_unspecified
            or not (address.is_private or address.is_loopback)):
        raise ValueError('Enrollment server must use a private IPv4 address')
    ca = Path(ca) if ca else private_root(node) / (server_node_id + '-ca.pem')
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(
        str(address), parsed.port or 443, context=context, timeout=10)
    try:
        body = json.dumps(request)
        connection.request('POST', PATH, body=body, headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + access_key,
            'Host': parsed.netloc,
        })
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('Enrollment response exceeds limit')
        if response.status != 200:
            raise AccessDenied('Server rejected client enrollment')
        result = json.loads(raw)
    finally:
        connection.close()
    return accept_on_client(service, server_node_id, operation_id, result)
