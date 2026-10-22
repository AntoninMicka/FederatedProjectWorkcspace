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
from spikes.federation_accounts import (
    MappingSignatures, ReplicationSignatures, validate_replication_spec,
    validate_rights,
)
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
            old={k:v for k,v in state.items() if k not in {'mappings','replications'}};old['schema_version']=1
            old['peers'] = [{key: value for key, value in peer.items()
                             if key not in {'relationship_type', 'local_role',
                                            'account_binding'}}
                            for peer in old['peers']]
            self.a.publish(git,old,commit)
        restored=Administration(self.a.node)
        self.assertEqual(restored.authenticate('Bearer '+self.states[0]['access_key'])['id'],self.users[0])
        with restored.locked() as (_,state,_,_):
            self.assertEqual(state['schema_version'],5);self.assertEqual(state['mappings'],[])
            self.assertEqual(state['replications'],[])

    def test_native_api_has_one_user_and_rejects_foreign_credentials(self):
        import http.client
        from spikes.desktop_management import DesktopManagementHandler
        from spikes.local_api import running_api
        from spikes.projects import Projects
        with running_api('http',handler=DesktopManagementHandler,projects=Projects(self.a.node)) as server:
            server.administration=Administration(self.a.node,deployment='desktop')
            def request(token,body,path='/v1/administration'):
                connection=http.client.HTTPConnection(*server.server_address,timeout=5)
                connection.request('POST',path,body=json.dumps(body),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                response=connection.getresponse();result=response.status,json.loads(response.read());connection.close();return result
            code,state=request(server.token,{'action':'list'})
            self.assertEqual(code,200);self.assertEqual(len(state['users']),1);self.assertEqual(state['deployment'],'desktop')
            self.assertEqual(request(server.token,{},'/v1/replications/status'),
                             (200, {'statuses': {}}))
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

    def replication(self):
        mapping, _ = self.bilateral()
        self.actor['memberships'][self.project] = 'project-admin'
        state = self.change(
            self.a, action='propose-replication', mapping_id=mapping,
            project_id=self.project, primary_node_id=self.states[0]['node_id'],
            privacy=['confidential', 'project', 'public'])
        replication = state['replications'][0]['spec']['id']
        self.assertFalse(state['replications'][0]['authorized'])
        self.assertFalse(state['replications'][0]['enabled'])
        with self.assertRaises(AccessDenied):
            self.change(self.a, action='set-replication-enabled',
                        replication_id=replication, enabled=True)
        state = self.change(self.a, action='confirm-replication',
                            replication_id=replication)
        primary_confirmation = state['replication_envelope']
        state = self.change(self.b, action='import-replication',
                            envelope=primary_confirmation)
        state = self.change(self.b, action='confirm-replication',
                            replication_id=replication)
        replica_confirmation = state['replication_envelope']
        self.assertTrue(state['replications'][0]['authorized'])
        state = self.change(self.a, action='import-replication',
                            envelope=replica_confirmation)
        self.assertTrue(state['replications'][0]['authorized'])
        return replication, primary_confirmation

    def test_bilateral_replication_grant_requires_local_enable_on_each_node(self):
        replication, _ = self.replication()
        state = self.change(self.a, action='set-replication-enabled',
                            replication_id=replication, enabled=True)
        self.assertTrue(state['replications'][0]['active'])
        first_commit = state['commit_id']
        state = self.change(self.a, action='set-replication-enabled',
                            replication_id=replication, enabled=True)
        self.assertEqual(state['commit_id'], first_commit)
        self.assertFalse(self.state(self.b)['replications'][0]['active'])
        state = self.change(self.b, action='set-replication-enabled',
                            replication_id=replication, enabled=True)
        self.assertTrue(state['replications'][0]['active'])
        spec = state['replications'][0]['spec']
        self.assertEqual(spec['ref'], 'refs/heads/main')
        self.assertEqual({node['role'] for node in spec['nodes']},
                         {'primary', 'read-only-replica'})
        self.assertNotIn('credential', json.dumps(state['replications']))
        self.assertNotIn('access_key', json.dumps(state['replications']))
        with self.assertRaises(ValueError):
            self.change(self.a, action='set-replication-enabled',
                        replication_id=str(uuid4()), enabled=True)

    def test_replication_scope_is_fail_closed_and_domain_separated(self):
        mapping, _ = self.bilateral()
        with self.assertRaises(AccessDenied):
            self.change(
                self.a, action='propose-replication', mapping_id=mapping,
                project_id=self.project, primary_node_id=self.states[0]['node_id'],
                privacy=['project'])
        self.actor['memberships'][self.project] = 'project-admin'
        with self.assertRaises(ValueError):
            self.change(
                self.a, action='propose-replication', mapping_id=mapping,
                project_id=self.project, primary_node_id=self.states[0]['node_id'],
                privacy=['local-only'])
        state = self.change(
            self.a, action='propose-replication', mapping_id=mapping,
            project_id=self.project, primary_node_id=self.states[0]['node_id'],
            privacy=['project'])
        replication = state['replications'][0]['spec']['id']
        envelope = self.change(
            self.a, action='confirm-replication',
            replication_id=replication)['replication_envelope']
        with self.assertRaises(ValueError):
            MappingSignatures.verify(
                envelope, self.states[0]['mapping_identity']['fingerprint'])
        tampered = copy.deepcopy(envelope)
        tampered['spec']['privacy'] = ['confidential']
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            ReplicationSignatures.verify(
                tampered, self.states[0]['mapping_identity']['fingerprint'])

    def test_replication_revocation_is_durable_and_confirmation_cannot_replay(self):
        replication, original = self.replication()
        self.change(self.a, action='set-replication-enabled',
                    replication_id=replication, enabled=True)
        state = self.change(self.a, action='revoke-replication',
                            replication_id=replication)
        self.assertFalse(state['replications'][0]['enabled'])
        self.assertFalse(state['replications'][0]['authorized'])
        state = self.change(self.b, action='import-replication',
                            envelope=state['replication_envelope'])
        self.assertFalse(state['replications'][0]['active'])
        with self.assertRaises(ValueError):
            self.change(self.b, action='import-replication', envelope=original)

    def test_v2_registry_migrates_without_changing_existing_mapping(self):
        mapping, _ = self.bilateral()
        with self.a.locked() as (git, state, commit, _):
            old = {key: value for key, value in state.items()
                   if key != 'replications'}
            old['schema_version'] = 2
            old['peers'] = [{key: value for key, value in peer.items()
                             if key not in {'relationship_type', 'local_role',
                                            'account_binding'}}
                            for peer in old['peers']]
            self.a.publish(git, old, commit)
        with Administration(self.a.node).locked() as (_, state, _, _):
            self.assertEqual(state['schema_version'], 5)
            self.assertEqual(state['mappings'][0]['spec']['id'], mapping)
            self.assertEqual(state['replications'], [])
            self.assertEqual(state['peers'][0]['relationship_type'], 'legacy')
            self.assertIsNone(state['peers'][0]['local_role'])
            self.assertIsNone(state['peers'][0]['account_binding'])

    def test_legacy_conversion_revokes_existing_mapping_and_replication(self):
        replication, _ = self.replication()
        state = self.change(
            self.a, action='convert-peer',
            node_id=self.states[1]['node_id'], relationship_type='p2p')
        self.assertEqual(state['peers'][0]['relationship_type'], 'p2p')
        self.assertEqual(state['peers'][0]['trust'], 'pending')
        self.assertIsNotNone(state['mappings'][0]['revocation'])
        item = next(row for row in state['replications']
                    if row['spec']['id'] == replication)
        self.assertIsNotNone(item['revocation'])
        self.assertFalse(item['enabled'])

    def test_replication_spec_rejects_unknown_fields_and_noncanonical_privacy(self):
        spec = {
            'schema_version': 1, 'id': str(uuid4()), 'mapping_id': str(uuid4()),
            'project_id': self.project, 'ref': 'refs/heads/main',
            'nodes': sorted([
                {'node_id': self.states[0]['node_id'], 'user_id': self.users[0],
                 'role': 'primary', 'fingerprint': 'a' * 64,
                 'identity_revision': 1},
                {'node_id': self.states[1]['node_id'], 'user_id': self.users[1],
                 'role': 'read-only-replica', 'fingerprint': 'b' * 64,
                 'identity_revision': 1}], key=lambda node: node['node_id']),
            'privacy': ['project', 'public'], 'actions': ['read', 'replicate']}
        self.assertIs(validate_replication_spec(spec), spec)
        malformed = copy.deepcopy(spec); malformed['privacy'] = ['public', 'project']
        with self.assertRaises(ValueError): validate_replication_spec(malformed)
        malformed = copy.deepcopy(spec); malformed['transport_token'] = 'secret'
        with self.assertRaises(ValueError): validate_replication_spec(malformed)
