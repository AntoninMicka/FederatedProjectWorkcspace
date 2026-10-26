# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.chat_threads import ChatThreads
from spikes.federation_accounts import MappingSignatures
from spikes.federation_sync import (
    ContentSyncControl, ContentSyncScheduler, SyncCancelled, SyncReceiver,
    _apply, _build_bundle, _prepare, synchronize,
)
from spikes.git_transfer import git_run
from spikes.project_creation import ProjectCreation
from spikes.project_chat_sync import chat_root, digest as chat_digest
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
        envelope, payload, _, _, _ = _prepare(
            self.services[source], self.node_ids[target], self.project_id,
            operation, [], force_bundle=True)
        response, response_payload = SyncReceiver(
            self.nodes[target], self.services[target]).receive(envelope, payload)
        _apply(self.nodes[source], response['exchange'], response_payload,
               service=self.services[source])
        return response

    def map_users(self):
        # User/project mapping is activated only after both nodes know the project.
        self.exchange(0, 1)
        mapped = [self.change(index, action='create-user', name='Chat owner',
                              node_role='member') for index in range(2)]
        self.user_ids = [state['users'][-1]['id'] for state in mapped]
        for index in range(2):
            self.change(index, action='update-user', user_id=self.user_ids[index],
                        active=True, node_role='member',
                        memberships={self.project_id: 'editor'})
        desktop = self.services
        def state(index):
            return desktop[index].request(self.actor, {'action': 'list'})
        def change(index, **request):
            return desktop[index].request(
                self.actor, dict(expected_commit=state(index)['commit_id'], **request))
        proposed = change(0, action='propose-mapping',
                          local_user_id=self.user_ids[0],
                          peer_node_id=self.node_ids[1],
                          peer_user_id=self.user_ids[1],
                          project_ids=[self.project_id])
        mapping_id = proposed['mappings'][0]['spec']['id']
        confirmed = change(0, action='confirm-mapping', mapping_id=mapping_id)
        change(1, action='import-mapping', envelope=confirmed['mapping_envelope'])
        confirmed = change(1, action='confirm-mapping', mapping_id=mapping_id)
        change(0, action='import-mapping', envelope=confirmed['mapping_envelope'])
        return mapping_id

    def chat_turn(self, index, thread_id=None, prompt='Question', answer='Answer',
                  privacy='project', owner_id=None):
        root = chat_root(self.nodes[index]); root.mkdir(mode=0o700, exist_ok=True)
        store = ChatThreads(root)
        owner_id = owner_id or self.user_ids[index]
        if thread_id is None:
            thread_id = str(uuid4())
            store.create(thread_id=thread_id, node_id=self.node_ids[index],
                         user_id=owner_id,
                         created_at='2026-10-26T12:00:00Z',
                         project_id=self.project_id)
        turn_id, run_id = str(uuid4()), str(uuid4())
        store.prepare_turn(thread_id=thread_id, node_id=self.node_ids[index],
                           user_id=owner_id, turn_id=turn_id,
                           message_id=str(uuid4()), content=prompt, privacy=privacy,
                           created_at='2026-10-26T12:00:01Z')
        store.bind_run(turn_id=turn_id, node_id=self.node_ids[index],
                       user_id=owner_id, run_id=run_id)
        store.complete(turn_id=turn_id, node_id=self.node_ids[index],
                       user_id=owner_id, run_id=run_id,
                       message_id=str(uuid4()), content=answer, privacy=privacy,
                       created_at='2026-10-26T12:00:02Z')
        return thread_id

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

    def test_project_chat_is_rw_and_continues_in_both_directions(self):
        self.map_users()
        thread_id = self.chat_turn(0)
        self.exchange(0, 1)
        remote = ChatThreads(chat_root(self.nodes[1])).get(
            thread_id, self.node_ids[1], self.user_ids[1])
        self.assertNotIn('read_only', remote)
        self.assertEqual([item['content'] for item in remote['messages']],
                         ['Question', 'Answer'])
        self.chat_turn(1, thread_id, prompt='Follow up', answer='Remote answer')
        self.exchange(0, 1)
        local = ChatThreads(chat_root(self.nodes[0])).get(
            thread_id, self.node_ids[0], self.user_ids[0])
        self.assertEqual([item['content'] for item in local['messages']],
                         ['Question', 'Answer', 'Follow up', 'Remote answer'])

    def test_one_exchange_converges_disjoint_project_thread_sets(self):
        self.map_users()
        left = self.chat_turn(0, prompt='Left only', answer='Left answer')
        state = self.change(1, action='create-user', name='Second project member',
                            node_role='member')
        second_owner = state['users'][-1]['id']
        self.change(1, action='update-user', user_id=second_owner,
                    active=True, node_role='member',
                    memberships={self.project_id: 'editor'})
        right = self.chat_turn(1, prompt='Right only', answer='Right answer',
                               owner_id=second_owner)

        self.exchange(0, 1)

        snapshots = []
        for index in range(2):
            rows = ChatThreads(chat_root(self.nodes[index])).list_project(
                self.node_ids[index], self.project_id)
            snapshots.append(sorted(
                row['thread_id'] for row in rows))
        self.assertEqual(sorted([left, right]), snapshots[0])
        self.assertEqual(snapshots[0], snapshots[1])

    def test_divergent_project_chat_forks_and_converges_without_overwrite(self):
        self.map_users()
        thread_id = self.chat_turn(0)
        self.exchange(0, 1)
        self.chat_turn(0, thread_id, prompt='Left', answer='Left answer')
        self.chat_turn(1, thread_id, prompt='Right', answer='Right answer')
        response = self.exchange(0, 1)
        self.assertTrue(response['conflict'])
        snapshots = []
        for index in range(2):
            rows = [row for row in ChatThreads(chat_root(self.nodes[index])).list(
                self.node_ids[index], self.user_ids[index])
                if row['project_id'] == self.project_id]
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(row['forked_from_thread_id'] == thread_id
                                 for row in rows), 1)
            snapshots.append(sorted((row['thread_id'], chat_digest(row))
                                    for row in rows))
        self.assertEqual(snapshots[0], snapshots[1])
        fork_id = next(item[0] for item in snapshots[0] if item[0] != thread_id)
        self.chat_turn(0, fork_id, prompt='Fork continues', answer='Writable')

    def test_local_only_and_inflight_chats_stay_local_without_blocking_project(self):
        self.map_users()
        visible = self.chat_turn(0)
        hidden = self.chat_turn(0, privacy='local-only')
        root = chat_root(self.nodes[0]); store = ChatThreads(root)
        active = str(uuid4())
        store.create(thread_id=active, node_id=self.node_ids[0],
                     user_id=self.user_ids[0], created_at='2026-10-26T12:01:00Z',
                     project_id=self.project_id)
        store.prepare_turn(thread_id=active, node_id=self.node_ids[0],
                           user_id=self.user_ids[0], turn_id=str(uuid4()),
                           message_id=str(uuid4()), content='Pending', privacy='project',
                           created_at='2026-10-26T12:01:01Z')
        self.exchange(0, 1)
        remote = ChatThreads(chat_root(self.nodes[1])).list(
            self.node_ids[1], self.user_ids[1])
        self.assertEqual([row['thread_id'] for row in remote], [visible])
        self.assertNotEqual(hidden, visible)

    def test_changed_user_mapping_rejects_prepared_chat_payload(self):
        self.map_users(); self.chat_turn(0)
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        self.change(1, action='update-user', user_id=self.user_ids[1],
                    active=False, node_role='member', memberships={})
        with self.assertRaises((AccessDenied, ValueError)):
            SyncReceiver(self.nodes[1], self.services[1]).receive(
                envelope, payload)

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
        self.assertIn("localExists&&remoteExists?'Sync':localExists?'Push':'Pull'",
                      ADMIN_JS)
        self.assertIn('Obsah aktuální', ADMIN_JS)
        self.assertIn('admin-sync-action', ADMIN_JS)
        self.assertIn("document.createElement('progress')", ADMIN_JS)
        self.assertIn('cancelProjectContent', ADMIN_JS)
        self.assertNotIn('admin-remote-projects', ADMIN_SHARING_HTML)
        self.assertIn('nativní Git historii', ADMIN_SHARING_HTML)
        self.assertIn('/v1/federation/content/reconcile',
                      DesktopManagementHandler.post_paths)
        self.assertIn('/v1/federation/content/reconcile', WebHandler.post_paths)
        self.assertIn('/v1/federation/content/cancel',
                      DesktopManagementHandler.post_paths)
        self.assertIn('/v1/federation/content/cancel', WebHandler.post_paths)
        self.assertIn('/v1/federation/content/start-all',
                      DesktopManagementHandler.post_paths)
        self.assertIn('/v1/federation/content/start-all', WebHandler.post_paths)
        self.assertIn('/v1/federation/content/settings',
                      DesktopManagementHandler.post_paths)
        self.assertIn('/v1/federation/content/settings', WebHandler.post_paths)
        self.assertIn('Synchronizovat vše', ADMIN_SHARING_HTML)
        self.assertIn('admin-sync-automatic', ADMIN_SHARING_HTML)
        self.assertIn('syncAllProjectContent', ADMIN_JS)
        self.assertIn('configureAutomaticContentSync', ADMIN_JS)
        self.assertNotIn('/v1/federation/chat-history', WebHandler.post_paths)
        self.assertNotIn('/v1/chat-history/status', WebHandler.post_paths)
        from spikes.desktop_ui import JS
        self.assertNotIn('Synchronizované historie', JS)
        self.assertIn("thread.forked_from_thread_id?' · fork'", JS)
        self.assertIn("#chats-tab').addEventListener('click',()=>loadChat())", JS)
        self.assertIn("contentsynccompleted", JS)
        self.assertIn('function contentSyncSummary', ADMIN_JS)
        self.assertIn('chybí aktivní vazba účtů z přihlášení', ADMIN_JS)
        self.assertNotIn('aktuální webová relace používá jiný účet', ADMIN_JS)
        self.assertIn('Chaty: sdíleno', ADMIN_JS)

    def test_sync_settings_are_revisioned_persistent_and_disable_scheduler(self):
        control = ContentSyncControl(self.nodes[0], deployment='web')
        self.assertEqual(control.settings(), {
            'schema_version': 1, 'revision': 0, 'automatic_enabled': True})
        self.assertEqual(control.configure(
            automatic_enabled=False, expected_revision=0), {
                'schema_version': 1, 'revision': 1,
                'automatic_enabled': False})
        restarted = ContentSyncControl(self.nodes[0], deployment='web')
        self.assertFalse(restarted.settings()['automatic_enabled'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            restarted.configure(automatic_enabled=True, expected_revision=0)
        with patch.object(restarted, 'candidates') as candidates:
            self.assertEqual(restarted.run_automatic(), {
                'enabled': False, 'attempted': 0})
            candidates.assert_not_called()
        restarted.configure(automatic_enabled=True, expected_revision=1)
        candidate = {'peer_id': self.node_ids[1],
                     'project_id': self.project_id,
                     'eligible': True, 'reason': None}
        with patch.object(restarted, 'candidates', return_value=[candidate]), \
                patch.object(restarted, 'synchronize', side_effect=OSError):
            self.assertEqual(restarted.run_automatic(), {
                'enabled': True, 'attempted': 1})

    def test_sync_all_uses_shared_policy_and_reports_partial_results(self):
        control = ContentSyncControl(self.nodes[0], deployment='web')
        candidates = control.candidates()
        self.assertEqual(candidates, [{
            'peer_id': self.node_ids[1], 'project_id': self.project_id,
            'eligible': True, 'reason': None}])
        synthetic = [candidates[0],
            {'peer_id': str(uuid4()), 'project_id': str(uuid4()),
             'eligible': True, 'reason': None},
            {'peer_id': str(uuid4()), 'project_id': str(uuid4()),
             'eligible': True, 'reason': None},
            {'peer_id': str(uuid4()), 'project_id': str(uuid4()),
             'eligible': False, 'reason': 'not-internal-sharing'}]
        with patch.object(control, 'candidates', return_value=synthetic), \
                patch.object(control, 'start', side_effect=[True, False, OSError]):
            result = control.start_all()
        self.assertEqual({key: result[key] for key in (
            'started', 'already_running', 'skipped', 'errors')}, {
                'started': 1, 'already_running': 1,
                'skipped': 1, 'errors': 1})
        self.assertEqual(['started', 'already-running', 'error', 'skipped'],
                         [row['state'] for row in result['targets']])

        self.change(0, action='update-peer', node_id=self.node_ids[1], name='Peer',
                    endpoint='https://127.0.0.1:8443', trust='approved',
                    sharing_level='external')
        self.assertEqual(control.candidates()[0]['reason'],
                         'not-internal-sharing')

    def test_manual_sync_reports_progress_and_cancels_at_safe_boundary(self):
        started = threading.Event(); finished = threading.Event()
        force_stop = threading.Event(); self.addCleanup(force_stop.set)

        def waiting_sync(*args, cancelled=None, **kwargs):
            started.set()
            try:
                while not cancelled() and not force_stop.wait(.01):
                    pass
                raise SyncCancelled('cancelled by test')
            finally:
                finished.set()

        control = ContentSyncControl(self.nodes[0], deployment='web')
        with patch('spikes.federation_sync.synchronize', side_effect=waiting_sync):
            self.assertTrue(control.start(self.node_ids[1], self.project_id))
            self.assertTrue(started.wait(2))
            self.assertEqual(control.statuses()[
                self.node_ids[1] + ':' + self.project_id]['state'], 'running')
            self.assertFalse(control.start(self.node_ids[1], self.project_id))
            self.assertTrue(control.cancel(self.node_ids[1], self.project_id))
            self.assertTrue(finished.wait(2))
            deadline = time.monotonic() + 2
            while (control.statuses()[self.node_ids[1] + ':' + self.project_id]
                   ['state'] != 'cancelled' and time.monotonic() < deadline):
                time.sleep(.01)
            self.assertEqual(control.statuses()[
                self.node_ids[1] + ':' + self.project_id]['state'], 'cancelled')

    def test_scheduler_survives_transient_startup_failure(self):
        scheduler = ContentSyncScheduler(self.nodes[0], deployment='web',
                                         interval=.01)
        recovered = threading.Event(); attempts = 0

        def run():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError('simulated startup race')
            recovered.set(); scheduler.stopping.set()

        with patch.object(scheduler.control, 'run_automatic', side_effect=run):
            scheduler.start()
            self.assertTrue(recovered.wait(2))
            scheduler.stop()
        self.assertGreaterEqual(attempts, 2)

    def test_retry_is_idempotent_and_crash_after_ref_update_rolls_forward(self):
        self.exchange(0, 1)
        candidate = self.commit_marker(0, 'candidate')
        operation = str(uuid4())
        envelope, payload, _, _, _ = _prepare(
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

    def test_chat_crash_rolls_forward_from_same_durable_content_exchange(self):
        self.map_users()
        thread_id = self.chat_turn(0)
        operation = str(uuid4())
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            operation, [], force_bundle=True)
        receiver = SyncReceiver(self.nodes[1], self.services[1])
        def crash(stage):
            if stage == 'chats-applied':
                raise OSError('simulated chat publication crash')
        with self.assertRaisesRegex(OSError, 'chat publication crash'):
            receiver.receive(envelope, payload, crash)
        response, response_payload = receiver.receive(envelope, payload)
        repeated, repeated_payload = receiver.receive(envelope, payload)
        self.assertEqual((repeated, repeated_payload),
                         (response, response_payload))
        self.assertEqual(ChatThreads(chat_root(self.nodes[1])).get(
            thread_id, self.node_ids[1], self.user_ids[1])['messages'][-1]['content'],
            'Answer')

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
        self.map_users()
        chat_id = self.chat_turn(0, answer='Sent with project sync')
        server_only = ProjectCreation(self.nodes[1]).create(
            'Server only', self.nodes[1].parent / 'server-only', str(uuid4()))
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
        status = ContentSyncControl(self.nodes[0], deployment='web').statuses()[
            self.node_ids[1] + ':' + self.project_id]
        self.assertEqual(status['chat_summary'], {
            'shared': 1, 'received': 1, 'active_mappings': 1})
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), Projects(self.nodes[0]).workspace(
                self.project_id).git.head())
        self.assertEqual(ChatThreads(chat_root(self.nodes[1])).get(
            chat_id, self.node_ids[1], self.user_ids[1])['messages'][-1]['content'],
            'Sent with project sync')
        pulled = synchronize(self.nodes[0], self.node_ids[1], server_only['id'],
                             deployment='web')
        self.assertEqual(pulled['state'], 'idle')
        self.assertEqual(Projects(self.nodes[0]).workspace(
            server_only['id']).git.head(), Projects(self.nodes[1]).workspace(
                server_only['id']).git.head())
        changed_after_restart = self.commit_marker(0, 'after restart')
        ContentSyncControl(self.nodes[0], deployment='web').run_automatic()
        self.assertEqual(Projects(self.nodes[1]).workspace(
            self.project_id).git.head(), changed_after_restart)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1',
                         'Requires real Qt/WebEngine')
    def test_real_webengine_shows_fork_as_normal_writable_chat(self):
        script = r'''
import json
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from spikes.desktop import request_policy
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
app=QApplication([])
with running_api('http',handler=DesktopHandler) as server:
 class Interceptor(QWebEngineUrlRequestInterceptor):
  def interceptRequest(self,info):
   policy=request_policy(info.requestUrl().toString(),info.initiator().toString(),bytes(info.requestMethod()).decode(),server.origin)
   if policy=='block':info.block(True)
   elif policy=='authenticate':info.setHttpHeader(b'Authorization',('Bearer '+server.token).encode())
 profile=QWebEngineProfile(app);interceptor=Interceptor(profile);profile.setUrlRequestInterceptor(interceptor);page=QWebEnginePage(profile,app)
 def received(value):
  value=json.loads(value)
  assert value=={'fork':True,'origin':True,'writable':True,'refreshes':True,'syncControls':True},value
  print('project chat fork: WebEngine RW branch verified',flush=True);app.exit(0)
 def loaded(ok):
  if not ok:return app.exit(3)
  page.runJavaScript("""activeProject={id:'99999999-9999-4999-8999-999999999999',title:'P'};const t={thread_id:'11111111-1111-4111-8111-111111111111',node_id:'22222222-2222-4222-8222-222222222222',user_id:'33333333-3333-4333-8333-333333333333',status:'active',classification:'brainstorming',created_at:'2026-10-26T12:00:00Z',revision:2,project_id:activeProject.id,assignment_revision:1,response_language:null,forked_from_thread_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',forked_from_digest:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',messages:[],turns:[]};knownThreads=[t];activeThread=t;taskOutcomes=[];document.querySelector('#chat-draft').value='continue';renderThreadList(knownThreads);renderChat(t);let refreshes=0;loadChat=async()=>{refreshes++};document.querySelector('#chats-tab').click();document.dispatchEvent(new CustomEvent('contentsynccompleted',{detail:{projectId:activeProject.id}}));JSON.stringify({fork:document.querySelector('#sidebar-chat-tree').textContent.includes('fork'),origin:document.querySelector('#sidebar-chat-tree').textContent.includes('konflikt aaaaaaaa'),writable:!document.querySelector('#chat-submit').disabled,refreshes:refreshes===2,syncControls:document.querySelector('#admin-sync-all').textContent==='Synchronizovat vše'&&document.querySelector('#admin-sync-automatic').type==='checkbox'})""",0,received)
 page.loadFinished.connect(loaded);page.setUrl(QUrl(server.origin+'/'));QTimer.singleShot(10000,lambda:app.exit(2));raise SystemExit(app.exec())
'''
        result = subprocess.run([sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WebEngine RW branch verified', result.stdout)


if __name__ == '__main__':
    unittest.main()
