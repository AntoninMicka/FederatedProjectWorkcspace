# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.federation_accounts import MappingSignatures
from spikes.federation_sync import (
    SyncReceiver, _apply, _build_bundle, _prepare, synchronize,
)
from spikes.git_transfer import git_run
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.network_backend import NetworkBackend, ProbeHandler, trust_ca
from spikes.web_server import WebServer
from spikes.web_administration import ADMIN_JS, ADMIN_SHARING_HTML
from spikes.desktop_management import DesktopManagementHandler
from spikes.web_server import WebHandler
from tests.fixtures import markdown, metadata


class AllowLoopback:
    def allows(self, peer):
        return peer.is_loopback


class FederationSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nodes = [self.root / name / 'node.json' for name in ('a', 'b')]
        for node in self.nodes:
            node.parent.mkdir(mode=0o700)
        created = ProjectCreation(self.nodes[0]).create(
            'Shared', self.nodes[0].parent / 'project', str(uuid4()))
        self.project_id = created['id']
        ProjectCreation(self.nodes[1]).initialize_node()
        self.services = [Administration(node, deployment='web') for node in self.nodes]
        self.actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        self.node_ids = [self.state(i)['node_id'] for i in range(2)]
        pins = [MappingSignatures(service.root).identity()['fingerprint']
                for service in self.services]
        for local, remote in ((0, 1), (1, 0)):
            state = self.change(
                local, action='add-peer-relationship', relationship_type='p2p',
                sharing_level='same-team', node_id=self.node_ids[remote], name='Peer',
                endpoint='https://127.0.0.1:8443', fingerprint=pins[remote])
            self.services[local].request(self.actor, {
                'action': 'update-peer', 'expected_commit': state['commit_id'],
                'node_id': self.node_ids[remote], 'name': 'Peer',
                'endpoint': 'https://127.0.0.1:8443', 'trust': 'approved',
                'sharing_level': 'same-team'})

    def state(self, index):
        return self.services[index].request(self.actor, {'action': 'list'})

    def change(self, index, **request):
        return self.services[index].request(
            self.actor, dict(expected_commit=self.state(index)['commit_id'], **request))

    def exchange(self, source, target):
        operation = str(uuid4())
        envelope, payload, _, _ = _prepare(
            self.services[source], self.node_ids[target], self.project_id,
            operation, [], force_bundle=True)
        response, response_payload = SyncReceiver(
            self.nodes[target], self.services[target]).receive(envelope, payload)
        _apply(self.nodes[source], response['exchange'], response_payload)
        return response

    def commit_marker(self, index, name):
        workspace = Projects(self.nodes[index]).workspace(self.project_id)
        artifact = str(uuid4())
        data = markdown(metadata(title=name, entity_id=artifact))
        workspace.apply({f'artifacts/{artifact}/document.md': data},
                        author_name='Tester', author_email='test@example.invalid',
                        message=name)
        return workspace.git.head()

    def test_initial_import_and_fast_forward_work_in_both_directions(self):
        first = self.commit_marker(0, 'first')
        self.exchange(0, 1)
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), first)
        second = self.commit_marker(1, 'second')
        self.exchange(0, 1)
        self.assertEqual(Projects(self.nodes[0]).workspace(
            self.project_id).git.head(), second)
        third = self.commit_marker(0, 'third')
        self.exchange(0, 1)
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), third)

    def test_divergence_preserves_both_heads_without_merge(self):
        self.exchange(0, 1)
        left = self.commit_marker(0, 'left')
        right = self.commit_marker(1, 'right')
        response = self.exchange(0, 1)
        left_git = Projects(self.nodes[0]).workspace(self.project_id).git
        right_git = Projects(self.nodes[1]).workspace(self.project_id).git
        self.assertEqual(left_git.head(), left)
        self.assertEqual(right_git.head(), right)
        self.assertTrue(response['conflict'])
        self.assertEqual(git_run(
            left_git, 'rev-parse',
            'refs/federation/incoming/' + self.node_ids[1] + '/'
            + response['exchange']['operation_id'] + '/main'
        ).stdout.strip(), right)
        self.assertEqual(git_run(
            right_git, 'rev-parse',
            'refs/federation/incoming/' + self.node_ids[0] + '/'
            + response['exchange']['operation_id'] + '/main'
        ).stdout.strip(), left)

    def test_same_company_exports_only_selected_non_hidden_branches(self):
        for local, remote in ((0, 1), (1, 0)):
            self.change(local, action='update-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://127.0.0.1:8443',
                        trust='approved', sharing_level='same-company')
        self.actor['memberships'][self.project_id] = 'project-admin'
        self.change(0, action='set-project-share', peer_id=self.node_ids[1],
                    project_id=self.project_id, enabled=True,
                    branch_mode='all-except-hidden', branches=['refs/heads/secret'],
                    include_patches=False)
        git = Projects(self.nodes[0]).workspace(self.project_id).git
        git_run(git, 'branch', 'secret')
        scope = {'mode': 'all-except-hidden', 'branches': ['refs/heads/secret'],
                 'revision': 1}
        refs, _ = _build_bundle(self.nodes[0], self.project_id, scope)
        self.assertEqual([row['ref'] for row in refs], ['refs/heads/main'])

    def test_non_current_branch_fast_forwards_without_switching_receiver(self):
        git = Projects(self.nodes[0]).workspace(self.project_id).git
        git_run(git, 'branch', 'feature')
        self.exchange(0, 1)
        git_run(git, 'switch', 'feature')
        feature = self.commit_marker(0, 'feature change')
        self.exchange(0, 1)
        remote = Projects(self.nodes[1]).workspace(self.project_id).git
        self.assertEqual(git_run(remote, 'symbolic-ref', 'HEAD').stdout.strip(),
                         'refs/heads/main')
        self.assertEqual(git_run(remote, 'rev-parse',
                                 'refs/heads/feature').stdout.strip(), feature)

    def test_external_is_fail_closed_and_shared_ui_exposes_internal_sync(self):
        for local, remote in ((0, 1), (1, 0)):
            self.change(local, action='update-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://127.0.0.1:8443',
                        trust='approved', sharing_level='external')
        with self.assertRaises(AccessDenied):
            _prepare(self.services[0], self.node_ids[1], self.project_id,
                     str(uuid4()), [], force_bundle=True)
        self.assertIn('syncProjectContent', ADMIN_JS)
        self.assertIn('Synchronizovat obsah', ADMIN_JS)
        self.assertIn('nativní Git historii', ADMIN_SHARING_HTML)
        self.assertIn('/v1/federation/content/reconcile',
                      DesktopManagementHandler.post_paths)
        self.assertIn('/v1/federation/content/reconcile', WebHandler.post_paths)

    def test_retry_is_idempotent_and_crash_after_ref_update_rolls_forward(self):
        self.exchange(0, 1)
        candidate = self.commit_marker(0, 'candidate')
        operation = str(uuid4())
        envelope, payload, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            operation, [], force_bundle=True)

        def crash(stage):
            if stage == 'ref-updated':
                raise OSError('simulated crash')

        receiver = SyncReceiver(self.nodes[1], self.services[1])
        with self.assertRaisesRegex(OSError, 'simulated crash'):
            receiver.receive(envelope, payload, crash)
        response, response_payload = receiver.receive(envelope, payload)
        repeated, repeated_payload = receiver.receive(envelope, payload)
        self.assertEqual(repeated, response)
        self.assertEqual(repeated_payload, response_payload)
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), candidate)

    def test_local_only_history_is_rejected_before_bundle_publication(self):
        workspace = Projects(self.nodes[0]).workspace(self.project_id)
        artifact = str(uuid4())
        private = metadata(title='Local', entity_id=artifact)
        private['privacy'] = 'local-only'
        workspace.apply({f'artifacts/{artifact}/document.md': markdown(private)},
                        author_name='Tester', author_email='test@example.invalid',
                        message='local only')
        with self.assertRaisesRegex(ValueError, 'local-only'):
            _build_bundle(self.nodes[0], self.project_id, {'mode': 'all'})

    def test_pinned_https_endpoint_exchanges_native_bundle(self):
        tls = NetworkBackend(self.nodes[1]).generate(
            '127.0.0.1', 8443, '127.0.0.0/8')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls['cert'], tls['key'])
        server = WebServer(('127.0.0.1', 0), ProbeHandler)
        server.tls = context; server.hostname = None
        server.application_access = AllowLoopback()
        server.node = self.nodes[1]; server.administration = self.services[1]
        thread = threading.Thread(target=server.serve_forever); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        endpoint = 'https://127.0.0.1:' + str(server.server_port)
        self.change(0, action='update-peer', node_id=self.node_ids[1], name='Peer',
                    endpoint=endpoint, trust='approved', sharing_level='same-team')
        trust_ca(self.nodes[0], self.node_ids[1], Path(tls['ca']).read_bytes())
        result = synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                             deployment='web')
        self.assertEqual(result['state'], 'idle')
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), Projects(self.nodes[0]).workspace(
                self.project_id).git.head())


if __name__ == '__main__':
    unittest.main()
