# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.project_creation import ProjectCreation


class AdministrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.node = self.root / 'node.json'
        ProjectCreation(self.node).create('Seed', self.root / 'seed', str(uuid4()))
        self.service = Administration(self.node)
        self.actor = {'id':None, 'node_role':'federation-admin', 'memberships':{}}

    def state(self):
        return self.service.request(self.actor, {'action':'list'})

    def change(self, **request):
        return self.service.request(self.actor, dict(expected_commit=self.state()['commit_id'], **request))

    def test_registry_restart_stale_update_and_credentials_are_not_in_git(self):
        before = self.state()
        state = self.change(action='create-user', name='User', node_role='member')
        key = state['access_key']; user = state['users'][0]
        actor = Administration(self.node).authenticate('Bearer ' + key)
        self.assertEqual(actor['id'], user['id']); self.assertEqual(actor['home_node_id'], state['node_id'])
        with self.assertRaises(AccessDenied):
            self.service.request(self.actor, {'action':'create-user', 'expected_commit':before['commit_id'], 'name':'Stale', 'node_role':'member'})
        with self.service.locked() as (git, _, _, _):
            for oid in git.run('rev-list', '--objects', '--all').stdout.splitlines():
                content = git.run('cat-file', '-p', oid.split()[0]).stdout
                self.assertNotIn(key,content)
        self.assertNotIn('credential_ref',user)

    def test_orphan_credential_cannot_authenticate_after_publication_failure(self):
        with patch.object(self.service, 'publish', side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):
                self.change(action='create-user', name='Interrupted', node_role='member')
        self.assertEqual(self.state()['users'], [])
        with self.service.locked():
            ref, key = self.service.issue(str(uuid4()))
        self.assertIsNone(self.service.authenticate('Bearer '+key))
        self.assertEqual(Administration(self.node).request(self.actor, {'action':'list'})['users'], [])

    def test_peer_requires_separate_approval_and_node_admin_can_manage_island(self):
        peer = str(uuid4())
        state = self.change(action='add-peer', node_id=peer, name='Desktop', endpoint='https://192.168.100.3:8443', fingerprint='a'*64)
        self.assertEqual(state['peers'][0]['trust'],'pending')
        self.assertEqual(state['peers'][0]['relationship_type'], 'legacy')
        self.assertIsNone(state['peers'][0]['local_role'])
        self.assertEqual(state['transport'],'signed-https-v1')
        self.assertTrue(state['can_federate'])
        state = self.change(action='set-trust', node_id=peer, trust='approved')
        self.assertEqual(state['peers'][0]['trust'],'approved')
        node_admin = {'id':None, 'node_role':'node-admin', 'memberships':{}}
        state = self.service.request(node_admin, {
            'action':'set-trust','expected_commit':state['commit_id'],
            'node_id':peer,'trust':'revoked'})
        self.assertEqual(state['peers'][0]['trust'],'revoked')
        self.assertIsNotNone(state['mapping_identity'])
        with self.assertRaises(ValueError):
            self.change(action='add-peer',node_id=peer,name='Duplicate',endpoint='https://192.168.100.4',fingerprint='b'*64)

    def test_peer_editor_updates_mutable_fields_but_keeps_pinned_identity(self):
        peer = str(uuid4())
        state = self.change(action='add-peer-relationship',
                            relationship_type='p2p', node_id=peer,
                            name='Old name',
                            endpoint='https://192.168.100.3:8443',
                            fingerprint='a'*64)
        state = self.service.request(self.actor, {
            'action': 'update-peer', 'expected_commit': state['commit_id'],
            'node_id': peer, 'name': 'New name',
            'endpoint': 'https://192.168.100.4:9443', 'trust': 'approved'})
        edited = state['peers'][0]
        self.assertEqual(edited, {
            'id': peer, 'name': 'New name',
            'endpoint': 'https://192.168.100.4:9443',
            'fingerprint': 'a'*64, 'trust': 'approved', 'revision': 2,
            'relationship_type': 'p2p', 'local_role': 'peer',
            'account_binding': None})
        unchanged_commit = state['commit_id']
        state = self.service.request(self.actor, {
            'action': 'update-peer', 'expected_commit': unchanged_commit,
            'node_id': peer, 'name': 'New name',
            'endpoint': 'https://192.168.100.4:9443', 'trust': 'approved'})
        self.assertEqual(state['commit_id'], unchanged_commit)
        with self.assertRaises(ValueError):
            self.change(action='update-peer', node_id=peer, name='Bad',
                        endpoint='http://example.invalid', trust='approved')

    def test_legacy_peer_must_be_converted_and_conversion_is_pending(self):
        peer = str(uuid4())
        state = self.change(action='add-peer', node_id=peer, name='Legacy',
                            endpoint='https://192.168.100.3:8443',
                            fingerprint='a'*64)
        with self.assertRaisesRegex(ValueError, 'converted or removed'):
            self.change(action='update-peer', node_id=peer, name='Changed',
                        endpoint='https://192.168.100.3:8443', trust='pending')
        state = self.service.request(self.actor, {
            'action': 'convert-peer', 'expected_commit': state['commit_id'],
            'node_id': peer, 'relationship_type': 'client-server'})
        converted = state['peers'][0]
        self.assertEqual(converted['relationship_type'], 'client-server')
        self.assertEqual(converted['local_role'], 'server')
        self.assertIsNone(converted['endpoint'])
        self.assertEqual(converted['trust'], 'pending')
        with self.assertRaisesRegex(AccessDenied, 'established by login'):
            self.change(action='set-trust', node_id=peer, trust='approved')

    def test_p2p_is_server_only_and_client_server_is_not_manually_added(self):
        peer = str(uuid4())
        desktop = Administration(self.node, deployment='desktop')
        with self.assertRaisesRegex(AccessDenied, 'server-only'):
            desktop.request(self.actor, {
                'action': 'add-peer-relationship',
                'expected_commit': desktop.request(self.actor, {'action': 'list'})['commit_id'],
                'relationship_type': 'p2p', 'node_id': peer, 'name': 'Peer',
                'endpoint': 'https://192.168.100.3:8443',
                'fingerprint': 'a' * 64})
        with self.assertRaisesRegex(AccessDenied, 'created by login'):
            self.change(action='add-peer-relationship',
                        relationship_type='client-server', node_id=peer,
                        name='Peer', endpoint='https://192.168.100.3:8443',
                        fingerprint='a' * 64)

    def test_v3_peer_registry_migrates_to_legacy_without_data_loss(self):
        peer = str(uuid4())
        current = self.change(action='add-peer', node_id=peer, name='Existing',
                              endpoint='https://192.168.100.3:8443',
                              fingerprint='a' * 64)
        with self.service.locked() as (git, state, commit, _):
            old = dict(state, schema_version=3)
            old['peers'] = [{key: value for key, value in item.items()
                             if key not in {'relationship_type', 'local_role',
                                            'account_binding'}}
                            for item in state['peers']]
            self.service.publish(git, old, commit)
        migrated = self.state()
        self.assertNotEqual(migrated['commit_id'], current['commit_id'])
        self.assertEqual(migrated['peers'][0], {
            'id': peer, 'name': 'Existing',
            'endpoint': 'https://192.168.100.3:8443',
            'fingerprint': 'a' * 64, 'trust': 'pending', 'revision': 1,
            'relationship_type': 'legacy', 'local_role': None,
            'account_binding': None})

    def test_rotation_interrupted_before_ref_keeps_previous_key_valid(self):
        from spikes.storage import Git
        state=self.change(action='create-user',name='Original',node_role='member')
        key=state['access_key'];user=state['users'][0];original=Git.run
        def interrupted(git, *args, **kwargs):
            if 'update-ref' in args:
                raise OSError('Interrupted before publication')
            return original(git,*args,**kwargs)
        with patch.object(Git,'run',interrupted):
            with self.assertRaises(OSError):
                self.change(action='rotate-key',user_id=user['id'])
        self.assertEqual(self.state()['commit_id'],state['commit_id'])
        self.assertEqual(Administration(self.node).authenticate('Bearer '+key)['id'],user['id'])

    def test_user_editor_updates_name_role_and_project_memberships(self):
        project = json.loads(self.node.read_text())['projects'][0]['project_id']
        state = self.change(action='create-user', name='Old name',
                            node_role='member')
        user = state['users'][0]
        state = self.service.request(self.actor, {
            'action': 'update-user', 'expected_commit': state['commit_id'],
            'user_id': user['id'], 'name': 'New name', 'active': True,
            'node_role': 'node-admin',
            'memberships': {project: 'project-admin'}})
        edited = state['users'][0]
        self.assertEqual(edited['name'], 'New name')
        self.assertEqual(edited['node_role'], 'node-admin')
        self.assertEqual(edited['memberships'], {project: 'project-admin'})
        self.assertEqual(edited['revision'], 2)

    def test_invalid_fields_do_not_publish_and_cannot_escalate(self):
        before=self.state()['commit_id']
        with self.assertRaises(AccessDenied):
            self.change(action='create-user',name='Bad',node_role=['node-admin'])
        with self.assertRaises(ValueError):
            self.change(action='add-peer',node_id=str(uuid4()),name='Bad',endpoint='http://example.invalid',fingerprint='a'*64)
        self.assertEqual(self.state()['commit_id'],before)
        member={'id':str(uuid4()),'node_role':'member','memberships':{}}
        with self.assertRaises(AccessDenied):
            self.service.request(member,{'action':'list'})
