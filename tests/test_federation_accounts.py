# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import copy
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.federation_accounts import MappingSignatures, validate_rights
from spikes.project_creation import ProjectCreation


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.project = str(uuid4()); self.entity = str(uuid4())
        self.actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        self.services = []
        for name in ('a', 'b'):
            root = self.root / name; root.mkdir(mode=0o700)
            node = root / 'node.json'
            node.write_text(json.dumps({'schema_version': 1, 'id': str(uuid4()), 'name': name, 'projects': [
                {'project_id': self.project, 'root': str(root / 'project'), 'state_dir': str(root / 'state')}]})); node.chmod(0o600)
            self.services.append(Administration(node))
        self.a, self.b = self.services
        self.states = [self.change(s, action='create-user', name='Own user', node_role='member') for s in self.services]
        self.users = [state['users'][0]['id'] for state in self.states]
        for index, service in enumerate(self.services):
            self.change(service, action='update-user', user_id=self.users[index], active=True, node_role='member', memberships={self.project: 'reader'})
            remote = self.states[1-index]
            self.change(service, action='add-peer', node_id=remote['node_id'], name='Peer', endpoint='https://192.168.100.2:8443', fingerprint=remote['mapping_identity']['fingerprint'])
            self.change(service, action='set-trust', node_id=remote['node_id'], trust='approved')

    def state(self, service):
        return service.request(self.actor, {'action': 'list'})

    def change(self, service, **request):
        return service.request(self.actor, dict(expected_commit=self.state(service)['commit_id'], **request))

    def bilateral(self):
        state = self.change(self.a, action='propose-mapping', local_user_id=self.users[0], peer_node_id=self.states[1]['node_id'], peer_user_id=self.users[1], project_ids=[self.project])
        mapping = state['mappings'][0]['spec']['id']
        state = self.change(self.a, action='confirm-mapping', mapping_id=mapping)
        self.assertFalse(state['mappings'][0]['active'])
        a_envelope = state['mapping_envelope']
        state = self.change(self.b, action='import-mapping', envelope=a_envelope)
        self.assertFalse(state['mappings'][0]['active'])
        state = self.change(self.b, action='confirm-mapping', mapping_id=mapping)
        self.assertTrue(state['mappings'][0]['active'])
        state = self.change(self.a, action='import-mapping', envelope=state['mapping_envelope'])
        self.assertTrue(state['mappings'][0]['active'])
        return mapping, a_envelope

    def manifest(self, privacy='project'):
        return {'schema_version': 1, 'project_id': self.project, 'commit_id': 'a'*40, 'entries': [
            {'entity_id': self.entity, 'privacy': privacy, 'grants': [
                {'node_id': self.states[1]['node_id'], 'user_id': self.users[1], 'actions': ['read', 'write']}]}]}

    def test_bilateral_consent_does_not_enable_foreign_login_or_expand_rights(self):
        mapping, envelope = self.bilateral()
        self.assertIsNone(self.a.authenticate('Bearer '+self.states[1]['access_key']))
        self.assertEqual(self.a.authenticate('Bearer '+self.states[0]['access_key'])['id'],self.users[0])
        manifest = self.manifest(); before = copy.deepcopy(manifest)
        self.assertEqual(self.a.mapped_actions(self.users[0],mapping,manifest,self.entity,{'read','write','manage'}),{'read'})
        self.assertEqual(manifest,before)
        self.assertEqual(self.a.mapped_actions(self.users[0],mapping,self.manifest('local-only'),self.entity,{'read'}),set())
        self.assertNotIn('access_key',json.dumps(envelope));self.assertNotIn('credential',json.dumps(envelope))
        self.assertEqual(Administration(self.a.node).request(self.actor,{'action':'list'})['mappings'][0]['spec']['id'],mapping)

    def test_signed_revocation_cannot_be_replayed_as_confirmation(self):
        mapping, original = self.bilateral()
        state=self.change(self.a,action='revoke-mapping',mapping_id=mapping)
        self.assertFalse(state['mappings'][0]['active'])
        state=self.change(self.b,action='import-mapping',envelope=state['mapping_envelope'])
        self.assertFalse(state['mappings'][0]['active'])
        with self.assertRaises(ValueError):self.change(self.b,action='import-mapping',envelope=original)

    def test_tampered_scope_and_wrong_pin_are_rejected(self):
        mapping, envelope=self.bilateral()
        tampered=copy.deepcopy(envelope);tampered['spec']['project_ids']=[str(uuid4())]
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):MappingSignatures.verify(tampered,self.states[0]['mapping_identity']['fingerprint'])
        with self.assertRaises(ValueError):MappingSignatures.verify(envelope,'0'*64)
        self.change(self.a,action='set-trust',node_id=self.states[1]['node_id'],trust='revoked')
        self.change(self.a,action='set-trust',node_id=self.states[1]['node_id'],trust='approved')
        self.assertFalse(self.state(self.a)['mappings'][0]['active'])

    def test_desktop_has_only_running_identity_and_no_account_key_login(self):
        desktop=Administration(self.a.node,deployment='desktop')
        state=self.state(desktop)
        self.assertEqual(len(state['users']),1)
        self.assertEqual(state['users'][0]['id'],ProjectCreation(self.a.node).author_id())
        with self.assertRaises(AccessDenied):self.change(desktop,action='create-user',name='Foreign',node_role='member')
        self.assertIsNone(desktop.authenticate('Bearer '+self.states[0]['access_key']))

    def test_missing_unknown_or_malformed_rights_are_rejected(self):
        with self.assertRaises(ValueError):validate_rights({})
        manifest=self.manifest();manifest['entries'][0]['grants'][0]['actions']=['node-admin']
        with self.assertRaises(ValueError):validate_rights(manifest)

    def test_missing_node_key_is_not_silently_replaced(self):
        signatures=MappingSignatures(self.a.root);signatures.key.unlink()
        with self.assertRaises(ValueError):signatures.identity()
        self.assertFalse(signatures.key.exists())

    def test_v1_registry_migration_preserves_local_account_and_credentials(self):
        with self.a.locked() as (git,state,commit,_):
            old={k:v for k,v in state.items() if k!='mappings'};old['schema_version']=1
            self.a.publish(git,old,commit)
        restored=Administration(self.a.node)
        self.assertEqual(restored.authenticate('Bearer '+self.states[0]['access_key'])['id'],self.users[0])
        with restored.locked() as (_,state,_,_):
            self.assertEqual(state['schema_version'],2);self.assertEqual(state['mappings'],[])

    def test_native_api_has_one_user_and_rejects_foreign_credentials(self):
        import http.client
        from spikes.desktop_management import DesktopManagementHandler
        from spikes.local_api import running_api
        from spikes.projects import Projects
        with running_api('http',handler=DesktopManagementHandler,projects=Projects(self.a.node)) as server:
            server.administration=Administration(self.a.node,deployment='desktop')
            def request(token,body):
                connection=http.client.HTTPConnection(*server.server_address,timeout=5)
                connection.request('POST','/v1/administration',body=json.dumps(body),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                response=connection.getresponse();result=response.status,json.loads(response.read());connection.close();return result
            code,state=request(server.token,{'action':'list'})
            self.assertEqual(code,200);self.assertEqual(len(state['users']),1);self.assertEqual(state['deployment'],'desktop')
            self.assertEqual(request(self.states[0]['access_key'],{'action':'list'})[0],401)
            self.assertEqual(request(server.token,{'action':'create-user','expected_commit':state['commit_id'],'name':'No','node_role':'member'})[0],403)

    def test_revocation_arriving_before_confirmation_is_retained(self):
        state=self.change(self.a,action='propose-mapping',local_user_id=self.users[0],peer_node_id=self.states[1]['node_id'],peer_user_id=self.users[1],project_ids=[self.project])
        mapping=state['mappings'][0]['spec']['id']
        confirmation=self.change(self.a,action='confirm-mapping',mapping_id=mapping)['mapping_envelope']
        revocation=self.change(self.a,action='revoke-mapping',mapping_id=mapping)['mapping_envelope']
        state=self.change(self.b,action='import-mapping',envelope=revocation)
        self.assertFalse(state['mappings'][0]['active']);self.assertIsNotNone(state['mappings'][0]['revocation'])
        with self.assertRaises(ValueError):self.change(self.b,action='import-mapping',envelope=confirmation)
