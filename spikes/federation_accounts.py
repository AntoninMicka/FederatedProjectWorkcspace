# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Offline signed account consent and portable ACL contract, not a login protocol."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from uuid import UUID

from spikes.journal import sync_dir


def uid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Expected canonical UUID')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != {'schema_version', 'id', 'accounts', 'project_ids'} or type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('Invalid mapping specification')
    uid(spec['id'])
    accounts = spec['accounts']
    if not isinstance(accounts, list) or len(accounts) != 2:
        raise ValueError('Mapping requires two local accounts')
    for account in accounts:
        if not isinstance(account, dict) or set(account) != {'node_id', 'user_id'}:
            raise ValueError('Invalid account reference')
        uid(account['node_id']); uid(account['user_id'])
    if accounts[0]['node_id'] >= accounts[1]['node_id']:
        raise ValueError('Accounts must be on distinct nodes in canonical order')
    projects = spec['project_ids']
    if not isinstance(projects, list) or not 1 <= len(projects) <= 16:
        raise ValueError('Expected 1-16 scoped projects')
    for project in projects:
        uid(project)
    if projects != sorted(set(projects)):
        raise ValueError('Projects must be unique and sorted')
    return spec


def openssl(*args):
    return subprocess.run(['openssl', *args], check=True, capture_output=True, timeout=10).stdout


class MappingSignatures:
    def __init__(self, root):
        self.root = Path(root)
        self.key = self.root / 'federation-key.pem'

    def public_key(self):
        marker = self.root / 'federation-key.identity'
        if not os.path.lexists(self.key):
            if os.path.lexists(marker):
                raise ValueError('Federation private key is missing; restore the original key')
            fd, temporary = tempfile.mkstemp(prefix='.federation-key-', dir=self.root)
            os.close(fd)
            try:
                openssl('genpkey', '-algorithm', 'ED25519', '-out', temporary)
                with open(temporary, 'rb') as handle:
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, self.key)
                except FileExistsError:
                    pass
                sync_dir(self.root)
            finally:
                os.unlink(temporary)
        info = self.key.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Unsafe federation private key')
        public = openssl('pkey', '-in', str(self.key), '-pubout', '-outform', 'DER')
        if os.path.lexists(marker):
            info = marker.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or marker.read_bytes() != public:
                raise ValueError('Federation identity changed; restore original identity')
        else:
            fd, temporary = tempfile.mkstemp(prefix='.federation-identity-', dir=self.root)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(public); handle.flush(); os.fsync(handle.fileno())
                os.link(temporary, marker); sync_dir(self.root)
            finally:
                os.unlink(temporary)
        return public

    def identity(self):
        public = self.public_key()
        return {'public_key': base64.b64encode(public).decode(), 'fingerprint': hashlib.sha256(public).hexdigest()}

    def sign(self, spec, node_id, decision='confirm'):
        validate_spec(spec)
        if node_id not in [a['node_id'] for a in spec['accounts']] or decision not in {'confirm', 'revoke'}:
            raise ValueError('Invalid signer or decision')
        public = self.public_key()
        payload = {'spec': spec, 'signer_node_id': node_id, 'decision': decision}
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            message = Path(directory) / 'message'
            message.write_bytes(canonical(payload))
            signature = openssl('pkeyutl', '-sign', '-rawin', '-inkey', str(self.key), '-in', str(message))
        return dict(payload, public_key=base64.b64encode(public).decode(), signature=base64.b64encode(signature).decode())

    @staticmethod
    def verify(envelope, fingerprint):
        if not isinstance(envelope, dict) or set(envelope) != {'spec', 'signer_node_id', 'decision', 'public_key', 'signature'}:
            raise ValueError('Invalid consent envelope')
        validate_spec(envelope['spec'])
        if envelope['signer_node_id'] not in [a['node_id'] for a in envelope['spec']['accounts']] or not isinstance(envelope['decision'], str) or envelope['decision'] not in {'confirm', 'revoke'}:
            raise ValueError('Invalid consent signer/decision')
        if not isinstance(envelope['public_key'], str) or not isinstance(envelope['signature'], str) or len(envelope['public_key']) > 128 or len(envelope['signature']) > 128:
            raise ValueError('Invalid signature encoding')
        public = base64.b64decode(envelope['public_key'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
        # Only Ed25519 SubjectPublicKeyInfo is accepted, never arbitrary algorithms.
        if len(public) != 44 or public[:12] != bytes.fromhex('302a300506032b6570032100') or len(signature) != 64 or hashlib.sha256(public).hexdigest() != fingerprint:
            raise ValueError('Unpinned or unsupported signing key')
        payload = {k: envelope[k] for k in ('spec', 'signer_node_id', 'decision')}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'public').write_bytes(public); (root / 'signature').write_bytes(signature)
            (root / 'message').write_bytes(canonical(payload))
            openssl('pkeyutl', '-verify', '-pubin', '-keyform', 'DER', '-inkey', str(root / 'public'),
                    '-rawin', '-in', str(root / 'message'), '-sigfile', str(root / 'signature'))
        return envelope


ACTIONS = {'read', 'write', 'review', 'manage', 'export'}


def validate_rights(manifest):
    """Portable, deny-by-default metadata. Never strip ACL or rewrite its owners."""
    if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'project_id', 'commit_id', 'entries'} or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ValueError('Missing or invalid portable rights')
    uid(manifest['project_id'])
    if not isinstance(manifest['commit_id'], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', manifest['commit_id']):
        raise ValueError('Rights must be bound to a data commit')
    if not isinstance(manifest['entries'], list) or not 1 <= len(manifest['entries']) <= 10000:
        raise ValueError('Invalid rights entries')
    entities = set()
    for entry in manifest['entries']:
        if not isinstance(entry, dict) or set(entry) != {'entity_id', 'privacy', 'grants'}:
            raise ValueError('Invalid entity ACL')
        uid(entry['entity_id'])
        if entry['entity_id'] in entities or not isinstance(entry['privacy'], str) or entry['privacy'] not in {'public', 'project', 'confidential', 'local-only'}:
            raise ValueError('Duplicate entity or unknown privacy')
        entities.add(entry['entity_id'])
        if not isinstance(entry['grants'], list) or len(entry['grants']) > 1000:
            raise ValueError('Invalid grants')
        principals = set()
        for grant in entry['grants']:
            if not isinstance(grant, dict) or set(grant) != {'node_id', 'user_id', 'actions'}:
                raise ValueError('Invalid principal grant')
            uid(grant['node_id']); uid(grant['user_id'])
            principal = (grant['node_id'], grant['user_id'])
            if principal in principals:
                raise ValueError('Duplicate principal')
            principals.add(principal)
            actions = grant['actions']
            if not isinstance(actions, list) or any(not isinstance(a, str) or a not in ACTIONS for a in actions) or len(actions) != len(set(actions)):
                raise ValueError('Unknown or duplicate action')
    return manifest


def effective_actions(manifest, entity_id, spec, local_node_id, local_user_id, local_actions):
    """Call only with a verified bilateral mapping; roles never travel as admin rights."""
    validate_rights(manifest); validate_spec(spec)
    if manifest['project_id'] not in spec['project_ids']:
        return set()
    local = {'node_id': local_node_id, 'user_id': local_user_id}
    if local not in spec['accounts']:
        return set()
    remote = next(a for a in spec['accounts'] if a != local)
    entry = next((e for e in manifest['entries'] if e['entity_id'] == entity_id), None)
    if not entry or entry['privacy'] == 'local-only':
        return set()
    grant = next((g for g in entry['grants'] if g['node_id'] == remote['node_id'] and g['user_id'] == remote['user_id']), None)
    return set(grant['actions']) & set(local_actions) & ACTIONS if grant else set()
