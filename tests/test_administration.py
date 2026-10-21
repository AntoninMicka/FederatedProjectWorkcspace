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

    def test_peer_requires_separate_approval_and_federation_admin(self):
        peer = str(uuid4())
        state = self.change(action='add-peer', node_id=peer, name='Desktop', endpoint='https://192.168.100.3:8443', fingerprint='a'*64)
        self.assertEqual(state['peers'][0]['trust'],'pending')
        self.assertEqual(state['transport'],'not-implemented')
        state = self.change(action='set-trust', node_id=peer, trust='approved')
        self.assertEqual(state['peers'][0]['trust'],'approved')
        node_admin = {'id':None, 'node_role':'node-admin', 'memberships':{}}
        with self.assertRaises(AccessDenied):
            self.service.request(node_admin, {'action':'set-trust','expected_commit':state['commit_id'],'node_id':peer,'trust':'revoked'})
        state=self.change(action='set-trust',node_id=peer,trust='revoked')
        self.assertEqual(state['peers'][0]['trust'],'revoked')
        with self.assertRaises(ValueError):
            self.change(action='add-peer',node_id=peer,name='Duplicate',endpoint='https://192.168.100.4',fingerprint='b'*64)

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
