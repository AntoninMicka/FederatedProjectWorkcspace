# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import os
import http.client
import fcntl
import hashlib
import json
import secrets
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
from spikes.federation_accounts import MappingSignatures, canonical
from spikes.federation_sync import (
    ContentSyncControl, ContentSyncScheduler, SyncCancelled, SyncReceiver, SyncBusy, SyncConflict,
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
    def test_outbound_owner_is_bounded_preserves_pending_and_releases_after_failure(self):
        from spikes.federation_sync import _database
        from spikes.network_backend import private_root
        envelope, payload, _, refs, chats = _prepare(self.services[0],
            self.node_ids[1], self.project_id, str(uuid4()), [], force_bundle=True)
        with _database(self.nodes[0]) as db:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                (self.node_ids[1], self.project_id, envelope['exchange']['operation_id'],
                 canonical(envelope).decode('ascii'), payload,
                 canonical({'refs':refs,'chats':chats}).decode('ascii')))
            before = db.execute('SELECT * FROM outbound').fetchall()
        control = ContentSyncControl(self.nodes[0], deployment='web')
        path = private_root(self.nodes[0]) / 'federation-content-sync.lock'
        with path.open('a+b') as owner:
            path.chmod(0o600); fcntl.flock(owner, fcntl.LOCK_EX)
            with patch('spikes.federation_sync.synchronize', side_effect=AssertionError('dispatch')):
                # A worker thread must terminate while the other owner remains
                # held, rather than being released by the test's cleanup.
                errors = []
                def attempt():
                    try: control.synchronize(self.node_ids[1], self.project_id)
                    except Exception as exc: errors.append(exc)
                worker = threading.Thread(target=attempt, daemon=True); worker.start()
                worker.join(1)
                self.assertFalse(worker.is_alive(), 'Waiting indefinitely for outbound owner')
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], BlockingIOError)
            with _database(self.nodes[0]) as db:
                self.assertEqual(db.execute('SELECT * FROM outbound').fetchall(), before)
            self.assertEqual(control.statuses()[self.node_ids[1]+':'+self.project_id]['state'], 'busy')
        with patch('spikes.federation_sync.synchronize', side_effect=OSError('transport')):
            with self.assertRaises(OSError):
                control.synchronize(self.node_ids[1], self.project_id)
        with patch('spikes.federation_sync.synchronize', return_value={'state':'idle'}) as sending:
            self.assertEqual(control.synchronize(self.node_ids[1], self.project_id), {'state':'idle'})
            sending.assert_called_once()
        with _database(self.nodes[0]) as db:
            self.assertEqual(db.execute('SELECT * FROM outbound').fetchall(), before)

    def test_cancelled_outbound_request_does_not_wait_for_owner(self):
        from spikes.network_backend import private_root
        path = private_root(self.nodes[0]) / 'federation-content-sync.lock'
        with path.open('a+b') as owner:
            path.chmod(0o600); fcntl.flock(owner, fcntl.LOCK_EX)
            with patch('spikes.federation_sync.synchronize', side_effect=AssertionError('dispatch')):
                with self.assertRaises(SyncCancelled):
                    ContentSyncControl(self.nodes[0], deployment='web').synchronize(
                        self.node_ids[1], self.project_id, cancelled=lambda: True)

    def completed_request(self):
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        receiver = SyncReceiver(self.nodes[1], self.services[1])
        return envelope, payload, receiver.receive(envelope, payload)

    def inbound_row(self, envelope):
        from spikes.federation_sync import _database
        with _database(self.nodes[1]) as db:
            return db.execute('SELECT * FROM inbound WHERE operation_id=?',
                              (envelope['exchange']['operation_id'],)).fetchone()

    def test_completed_exact_replay_skips_git_history_and_publication(self):
        envelope, payload, expected = self.completed_request()
        before = self.inbound_row(envelope)
        receiver = SyncReceiver(self.nodes[1], self.services[1])
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with patch('spikes.federation_sync._apply', side_effect=AssertionError('publication')):
                with patch('spikes.federation_sync._apply_verified_history', side_effect=AssertionError('publication')):
                    with patch('spikes.federation_sync._prepare', side_effect=AssertionError('new response')):
                        self.assertEqual(receiver.receive(envelope, payload), expected)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_replay_rejects_changed_bytes_or_signed_envelope_under_same_id(self):
        from spikes.project_replication import _signature
        envelope, payload, _ = self.completed_request()
        before = self.inbound_row(envelope)
        changed = dict(envelope['exchange'], known_remote_refs=[
            {'ref': 'refs/heads/main', 'head': '0' * 40}])
        changed = _signature(self.services[0].root, changed, self.node_ids[0], 'exchange')
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            for request, body in ((envelope, payload[:-1] + bytes([payload[-1] ^ 1])),
                                  (changed, payload)):
                with self.subTest(envelope_changed=request is changed):
                    with self.assertRaisesRegex(ValueError, 'another request'):
                        SyncReceiver(self.nodes[1], self.services[1]).receive(request, body)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_new_request_validates_history_before_persisting_intent(self):
        from spikes.federation_sync import _verify_bundle
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=ValueError('invalid history')):
            with self.assertRaisesRegex(ValueError, 'invalid history'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertIsNone(self.inbound_row(envelope))
        with patch('spikes.federation_sync._verify_bundle', wraps=_verify_bundle) as history:
            SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(history.call_count, 1)

    def test_dirty_destination_refuses_before_history_and_keeps_exact_pending_request(self):
        self.commit_marker(0, 'Tracked content')
        self.exchange(0, 1)
        workspace = Projects(self.nodes[1]).workspace(self.project_id)
        path = next(p for p in workspace.git.snapshot(workspace.git.head()) if p.endswith('.md'))
        target = workspace.git.root / path
        target.write_text('Uncommitted destination edit\n')
        head = workspace.git.head()
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        from spikes.federation_sync import _database
        with _database(self.nodes[1]) as db:
            db.execute('INSERT INTO inbound VALUES (?,?,?,?,NULL,NULL)', (
                envelope['exchange']['operation_id'],
                hashlib.sha256(canonical(envelope) + payload).hexdigest(),
                canonical(envelope).decode('ascii'), payload))
        saved = self.inbound_row(envelope)
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with self.assertRaisesRegex(SyncConflict, 'local changes'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), saved)
        self.assertEqual(workspace.git.head(), head)
        self.assertEqual(target.read_text(), 'Uncommitted destination edit\n')
        # Resolving the local edit makes the SAME operation usable again.
        target.write_bytes(workspace.git.snapshot(head)[path])
        response, _ = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(response['exchange']['operation_id'], envelope['exchange']['operation_id'])

    def test_completed_replay_preserves_new_local_edit_without_republication(self):
        self.commit_marker(0, 'Tracked content')
        envelope, payload, expected = self.completed_request()
        workspace = Projects(self.nodes[1]).workspace(self.project_id)
        path = next(p for p in workspace.git.snapshot(workspace.git.head()) if p.endswith('.md'))
        target = workspace.git.root / path; target.write_text('New local edit\n')
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            self.assertEqual(SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload), expected)
        self.assertEqual(target.read_text(), 'New local edit\n')

    def test_unchanged_exchange_skips_git_export_on_both_nodes(self):
        self.commit_marker(0, 'Shared history');self.exchange(0, 1)
        from spikes.federation_sync import _inventory
        git = Projects(self.nodes[0]).workspace(self.project_id).git
        refs = _inventory(git, {'mode': 'all'})
        with patch('spikes.federation_sync.validate_history', side_effect=AssertionError('export history')), \
             patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('transfer history')):
            envelope, payload, _, local, _ = _prepare(
                self.services[0], self.node_ids[1], self.project_id, str(uuid4()), refs,
                force_bundle=True, peer_known_refs=refs)
            self.assertEqual(local, refs)
            self.assertEqual(envelope['exchange']['bundle_size'], 0)
            response, _ = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
            self.assertEqual(response['exchange']['bundle_size'], 0)
        self.assertEqual(Projects(self.nodes[1]).workspace(self.project_id).git.head(), git.head())

    def test_known_inventory_does_not_skip_new_heads_or_new_branches(self):
        from spikes.federation_sync import _inventory
        self.commit_marker(0, 'Original')
        git = Projects(self.nodes[0]).workspace(self.project_id).git
        known = _inventory(git, {'mode': 'all'})
        self.commit_marker(0, 'New head')
        with patch('spikes.federation_sync.validate_history', side_effect=ValueError('validation required')):
            with self.assertRaisesRegex(ValueError, 'validation required'):
                _build_bundle(self.nodes[0], self.project_id, {'mode': 'all'}, peer_known_refs=known)
        known = _inventory(git, {'mode': 'all'});git_run(git, 'branch', 'new-branch')
        with patch('spikes.federation_sync.validate_history', side_effect=ValueError('validation required')):
            with self.assertRaisesRegex(ValueError, 'validation required'):
                _build_bundle(self.nodes[0], self.project_id, {'mode': 'all'}, peer_known_refs=known)

    def test_direct_application_still_requires_full_history_validation(self):
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=ValueError('invalid history')):
            with self.assertRaisesRegex(ValueError, 'invalid history'):
                _apply(self.nodes[1], envelope['exchange'], payload, service=self.services[1])
        self.assertFalse(Projects(self.nodes[1]).list())

    def test_receiver_response_reuses_only_the_exact_verified_git_graph(self):
        from spikes.federation_sync import validate_history, _payloads
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync.validate_history', wraps=validate_history) as history:
            response, returned = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(history.call_count, 1)
        self.assertEqual(_payloads(response['exchange'], returned)[0],
                         _payloads(envelope['exchange'], payload)[0])

    def test_receiver_response_validates_additional_local_branches(self):
        from spikes.federation_sync import validate_history
        self.exchange(0, 1)
        git = Projects(self.nodes[1]).workspace(self.project_id).git
        git_run(git, 'branch', 'extra-local')
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync.validate_history', wraps=validate_history) as history:
            response, _ = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual({row['ref'] for row in response['exchange']['refs']},
                         {'refs/heads/main', 'refs/heads/extra-local'})
        self.assertGreater(history.call_count, 1)

    def test_verified_inbound_graph_is_not_reused_for_another_operation(self):
        from spikes.federation_sync import validate_history
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync._prepare', wraps=_prepare) as prepared:
            SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        proof = prepared.call_args.kwargs['verified']
        with patch('spikes.federation_sync.validate_history', wraps=validate_history) as history:
            _prepare(self.services[1], self.node_ids[0], self.project_id,
                     str(uuid4()), [], force_bundle=True, verified=proof)
        self.assertGreater(history.call_count, 0)

    def test_receiver_response_validates_a_different_local_head(self):
        from spikes.federation_sync import validate_history
        self.exchange(0, 1)
        ahead = self.commit_marker(1, 'Local ahead')
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync.validate_history', wraps=validate_history) as history:
            response, _ = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(response['exchange']['refs'], [{'ref': 'refs/heads/main', 'head': ahead}])
        self.assertGreater(history.call_count, 1)

    def test_receiver_response_validates_a_different_export_scope(self):
        from spikes.federation_sync import validate_history
        self.exchange(0, 1)
        self.actor['memberships'][self.project_id] = 'project-admin'
        for local, remote in ((0, 1), (1, 0)):
            self.change(local, action='update-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://127.0.0.1:8443',
                        trust='approved', sharing_level='same-company')
            self.change(local, action='set-project-share', peer_id=self.node_ids[remote],
                        project_id=self.project_id, enabled=True,
                        branch_mode='all-except-hidden' if local == 0 else 'selected-only',
                        branches=['refs/heads/hidden'] if local == 0 else ['refs/heads/main'],
                        include_patches=False)
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        with patch('spikes.federation_sync.validate_history', wraps=validate_history) as history:
            response, _ = SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertNotEqual(response['exchange']['scope'], envelope['exchange']['scope'])
        self.assertGreater(history.call_count, 1)

    def test_receiver_rechecks_chat_authority_after_history_validation(self):
        from spikes.federation_sync import _verify_bundle
        self.map_users(); self.chat_turn(0)
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        head = Projects(self.nodes[1]).repository(self.project_id).head()

        def validate_then_revoke(*args, **kwargs):
            result = _verify_bundle(*args, **kwargs)
            self.change(1, action='update-user', user_id=self.user_ids[1],
                        active=False, node_role='member', memberships={})
            return result

        with patch('spikes.federation_sync._verify_bundle', side_effect=validate_then_revoke):
            with self.assertRaisesRegex(ValueError, 'active project recipient'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(Projects(self.nodes[1]).repository(self.project_id).head(), head)

    def test_completed_replay_rechecks_revoked_peer_without_changing_journal(self):
        envelope, payload, _ = self.completed_request()
        before = self.inbound_row(envelope)
        self.change(1, action='update-peer', node_id=self.node_ids[0], name='Peer',
                    endpoint='https://127.0.0.1:8443', trust='revoked', sharing_level='same-team')
        with self.assertRaises(AccessDenied):
            SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_rechecks_incoming_chat_recipient(self):
        self.map_users(); self.chat_turn(0)
        envelope, payload, _ = self.completed_request()
        before = self.inbound_row(envelope)
        self.change(1, action='update-user', user_id=self.user_ids[1],
                    active=False, node_role='member', memberships={})
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with self.assertRaisesRegex(ValueError, 'active project recipient'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_rechecks_outgoing_chat_authority_without_incoming_chat(self):
        self.map_users(); self.exchange(0, 1); self.chat_turn(1)
        envelope, payload, expected = self.completed_request()
        self.assertEqual(envelope['exchange']['chat_size'], 0)
        self.assertGreater(expected[0]['exchange']['chat_size'], 0)
        before = self.inbound_row(envelope)
        self.change(1, action='update-user', user_id=self.user_ids[1],
                    active=False, node_role='member', memberships={})
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with self.assertRaisesRegex(ValueError, 'recipient changed'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_rejects_withdrawn_project_export(self):
        self.exchange(0, 1)
        self.actor['memberships'][self.project_id] = 'project-admin'
        for local, remote in ((0, 1), (1, 0)):
            self.change(local, action='update-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://127.0.0.1:8443',
                        trust='approved', sharing_level='same-company')
            self.change(local, action='set-project-share', peer_id=self.node_ids[remote],
                        project_id=self.project_id, enabled=True,
                        branch_mode='selected-only', branches=['refs/heads/main'], include_patches=False)
        envelope, payload, expected = self.completed_request()
        self.assertGreater(expected[0]['exchange']['bundle_size'], 0)
        before = self.inbound_row(envelope)
        self.change(1, action='set-project-share', peer_id=self.node_ids[0],
                    project_id=self.project_id, enabled=False,
                    branch_mode='selected-only', branches=['refs/heads/main'], include_patches=False)
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with self.assertRaisesRegex(ValueError, 'current project sharing policy'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_refuses_damaged_saved_response_without_history_or_repair(self):
        from spikes.federation_sync import _database
        envelope, payload, expected = self.completed_request()
        self.assertTrue(expected[1])
        for damage in ('payload', 'signature', 'missing-payload'):
            with self.subTest(damage=damage):
                response = json.loads(json.dumps(expected[0])); body = expected[1]
                if damage == 'payload':
                    body = body[:-1] + bytes([body[-1] ^ 1])
                elif damage == 'signature':
                    response['signature'] = 'AA=='
                else:
                    body = None
                with _database(self.nodes[1]) as db:
                    db.execute('UPDATE inbound SET response_envelope=?,response_bundle=? WHERE operation_id=?',
                               (json.dumps(response), body, envelope['exchange']['operation_id']))
                before = self.inbound_row(envelope)
                with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
                    with self.assertRaises(ValueError):
                        SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
                self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_refuses_registry_change_during_authority_checks(self):
        from spikes.federation_sync import _verify_payload
        envelope, payload, _ = self.completed_request()
        before = self.inbound_row(envelope)
        calls = 0

        def change_authority(*args):
            nonlocal calls
            result = _verify_payload(*args); calls += 1
            if calls == 2:
                self.change(1, action='update-peer', node_id=self.node_ids[0], name='Changed',
                            endpoint='https://127.0.0.1:8443', trust='approved', sharing_level='same-team')
            return result

        with patch('spikes.federation_sync._verify_payload', side_effect=change_authority):
            with self.assertRaisesRegex(ValueError, 'authority changed during replay'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_completed_replay_does_not_export_an_unregistered_project(self):
        envelope, payload, expected = self.completed_request()
        self.assertTrue(expected[1])
        before = self.inbound_row(envelope)
        node = json.loads(self.nodes[1].read_bytes()); node['projects'] = []
        self.nodes[1].write_text(json.dumps(node))
        with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
            with self.assertRaisesRegex(ValueError, 'no longer registered'):
                SyncReceiver(self.nodes[1], self.services[1]).receive(envelope, payload)
        self.assertEqual(self.inbound_row(envelope), before)

    def test_signed_https_receive_allows_ui_and_preserves_concurrent_project_edit(self):
        from spikes.web_server import make_server
        from spikes.federation_sync import _verify_bundle
        self.exchange(0, 1)
        source_head = self.commit_marker(0, 'Incoming revision')
        tls = NetworkBackend(self.nodes[1]).generate('127.0.0.1', 8443, '127.0.0.0/8')
        token_path = self.root / 'http-token'
        token = secrets.token_urlsafe(32)
        token_path.write_text(token); token_path.chmod(0o600)
        server = make_server('127.0.0.1', 0, '192.168.100.0/24',
                            tls['cert'], tls['key'], token_path, self.nodes[1])
        thread = threading.Thread(target=server.serve_forever); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        endpoint = 'https://127.0.0.1:' + str(server.server_port)
        self.change(0, action='update-peer', node_id=self.node_ids[1], name='Peer',
                    endpoint=endpoint, trust='approved', sharing_level='same-team')
        trust_ca(self.nodes[0], self.node_ids[1], Path(tls['ca']).read_bytes())
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []

        def verify(node, *args, **kwargs):
            if Path(node) == self.nodes[1] and not entered.is_set():
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test verification gate')
            return _verify_bundle(node, *args, **kwargs)

        def transfer():
            try:
                results.append(synchronize(self.nodes[0], self.node_ids[1],
                                           self.project_id, deployment='web'))
            except Exception as exc:
                errors.append(exc)

        with patch('spikes.federation_sync._verify_bundle', side_effect=verify):
            worker = threading.Thread(target=transfer); worker.start()
            try:
                self.assertTrue(entered.wait(5))
                for path in ('/v1/projects', '/v1/projects/open', '/v1/presentation/public', '/v1/diagnostics/status'):
                    connection = http.client.HTTPSConnection('127.0.0.1', server.server_port,
                        context=ssl.create_default_context(cafile=tls['ca']), timeout=3)
                    try:
                        request_body = ({'project_id':self.project_id}
                                        if path == '/v1/projects/open' else {})
                        connection.request('POST', path, body=json.dumps(request_body), headers={
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + token})
                        response = connection.getresponse(); body = response.read()
                        self.assertEqual(response.status, 200, (path, body))
                        if path.endswith('diagnostics/status'):
                            self.assertTrue(json.loads(body)['http']['lanes_busy']['content_sync_lane'])
                    finally:
                        connection.close()
                    self.assertTrue(worker.is_alive())
                # A genuine Workspace write while incoming history is being
                # verified must survive as a divergent head, never be replaced.
                local_head = self.commit_marker(1, 'Concurrent local revision')
            finally:
                release.set(); worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0]['state'], 'conflict')
        self.assertEqual(Projects(self.nodes[0]).workspace(self.project_id).git.head(), source_head)
        self.assertEqual(Projects(self.nodes[1]).workspace(self.project_id).git.head(), local_head)

    def test_receiver_ownership_covers_distinct_instances_and_releases_on_failure(self):
        from spikes.federation_sync import _inbound_lock
        receiver = SyncReceiver(self.nodes[1], self.services[1])
        with _inbound_lock(self.nodes[1]):
            with patch.object(receiver, '_receive', side_effect=AssertionError('dispatch')):
                with self.assertRaises(SyncBusy):
                    receiver.receive({}, b'')
        # Failed validation must release ownership; a valid exchange and exact
        # replay must still publish and return the same response.
        with self.assertRaises(ValueError):
            receiver.receive({}, b'')
        envelope, payload, _, _, _ = _prepare(
            self.services[0], self.node_ids[1], self.project_id,
            str(uuid4()), [], force_bundle=True)
        result = receiver.receive(envelope, payload)
        self.assertEqual(SyncReceiver(self.nodes[1], self.services[1]).receive(
            envelope, payload), result)

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
        self.assertIn("if(tab.id==='chats-tab')await loadChat()", JS)
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

    def test_signed_remote_catalog_drives_pull_candidates_automatic_and_manual_all(self):
        from spikes.federation_catalog import prepare, receive, CatalogStore
        envelope, _ = prepare(self.services[0], self.node_ids[1])
        receive(self.services[1], envelope)
        projection = CatalogStore(self.nodes[1]).projections()[0]
        self.assertEqual(projection['id'], self.project_id)
        self.assertNotIn('project_id', projection)
        self.assertFalse(Projects(self.nodes[1]).list())
        control = ContentSyncControl(self.nodes[1], deployment='web')
        expected = [{'peer_id': self.node_ids[0], 'project_id': self.project_id,
                     'eligible': True, 'reason': None}]
        self.assertEqual(control.candidates(), expected)
        with patch.object(control, 'start', return_value=True) as start:
            self.assertEqual(control.start_all()['started'], 1)
        start.assert_called_once_with(self.node_ids[0], self.project_id)
        with patch.object(control, 'synchronize', return_value={'state': 'idle'}) as run:
            self.assertEqual(control.run_automatic(), {'enabled': True, 'attempted': 1})
        run.assert_called_once_with(self.node_ids[0], self.project_id)
        # A project present both locally and remotely remains one candidate.
        self.exchange(0, 1)
        self.assertEqual(control.candidates(), expected)

    def test_same_company_remote_selection_uses_authenticated_catalog_id(self):
        from spikes.federation_catalog import prepare, receive
        for local, remote in ((0, 1), (1, 0)):
            self.change(local, action='update-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://127.0.0.1:8443',
                        trust='approved', sharing_level='same-company')
        self.actor['memberships'][self.project_id] = 'project-admin'
        self.change(0, action='set-project-share', peer_id=self.node_ids[1],
                    project_id=self.project_id, enabled=True, branch_mode='selected-only',
                    branches=['refs/heads/main'], include_patches=False)
        envelope, _ = prepare(self.services[0], self.node_ids[1])
        receive(self.services[1], envelope)
        control = ContentSyncControl(self.nodes[1], deployment='web')
        self.assertEqual(control.candidates(), [{'peer_id': self.node_ids[0],
            'project_id': self.project_id, 'eligible': True, 'reason': None}])

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
        from spikes.federation_sync import _validate_git_bundle
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
        with patch('spikes.federation_sync._validate_git_bundle', wraps=_validate_git_bundle) as history:
            response, response_payload = receiver.receive(envelope, payload)
        self.assertGreater(history.call_count, 0)  # Incomplete intent is not a completed replay.
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

    def test_bundle_branches_share_one_validation_budget(self):
        from spikes.git_budget import GitDeadlineExceeded
        from spikes.git_transfer import validate_history as native_validate
        root = Projects(self.nodes[0]).workspace(self.project_id).git
        head = root.head()
        root.run('branch', 'other-head', head)
        clock = [time.monotonic()]
        checked = []
        def validation(*args, **kwargs):
            result = native_validate(*args, **kwargs)
            checked.append(args[1])
            clock[0] += 35
            return result
        with patch('spikes.git_budget.time.monotonic', side_effect=lambda: clock[0]), \
             patch('spikes.federation_sync.validate_history', side_effect=validation):
            with self.assertRaises(GitDeadlineExceeded):
                _build_bundle(self.nodes[0], self.project_id, {'mode': 'all'})
        self.assertEqual(checked, [head, head])
        self.assertEqual(root.head(), head)
        # Scope restoration permits a subsequent ordinary export.
        refs, payload = _build_bundle(self.nodes[0], self.project_id, {'mode': 'all'})
        self.assertEqual(len(refs), 2)
        self.assertTrue(payload)

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
        # The receiver durably finishes, but its HTTP response arrives after
        # the sender deadline. Preserve the exact request for native replay.
        from spikes.federation_sync import _database
        received = threading.Event()
        release = threading.Event()
        original_receive = SyncReceiver.receive
        def delayed_receive(receiver, *args, **kwargs):
            result = original_receive(receiver, *args, **kwargs)
            received.set()
            release.wait(5)
            return result
        try:
            with patch.object(SyncReceiver, 'receive', delayed_receive), \
                    patch('spikes.federation_sync.NETWORK_TIMEOUT', 1.5):
                with self.assertRaises(TimeoutError):
                    synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                                deployment='web')
                self.assertTrue(received.is_set())
        finally:
            release.set()
        with _database(self.nodes[0]) as db:
            saved = db.execute('SELECT operation_id,envelope,bundle FROM outbound WHERE peer_id=? AND project_id=?',
                               (self.node_ids[1], self.project_id)).fetchone()
        self.assertIsNotNone(saved)
        with _database(self.nodes[1]) as db:
            receipt = db.execute('SELECT response_envelope FROM inbound WHERE operation_id=?',
                                 (saved[0],)).fetchone()
        self.assertIsNotNone(receipt[0])
        # Error hints cross a real TLS exchange but never change pending bytes.
        from spikes.request_ownership import ProjectBusy
        from spikes.sync_diagnostics import phase, snapshot as diagnostic
        def busy_journal(*args, **kwargs):
            phase('receive-prepare-response')
            raise ProjectBusy('private-payload', resource='sync-journal')
        with patch.object(SyncReceiver, '_receive', side_effect=busy_journal):
            with self.assertRaises(SyncBusy) as caught:
                ContentSyncControl(self.nodes[0], deployment='web').synchronize(
                    self.node_ids[1], self.project_id)
        self.assertEqual(caught.exception.busy_resource, 'sync-journal')
        self.assertEqual(caught.exception.peer_phase, 'receive-prepare-response')
        detail = diagnostic(self.nodes[0], self.node_ids[1], self.project_id, direction='outbound')
        self.assertEqual(detail['phase'], 'download')
        self.assertEqual(detail['busy_resource'], 'sync-journal')
        self.assertEqual(detail['peer_phase'], 'receive-prepare-response')
        self.assertNotIn('private-payload', str(detail))
        for hint in ({'busy_resource': 'secret-token', 'peer_phase': 'private-payload'},
                     {'busy_resource': [], 'peer_phase': {}}, {}):
            def malicious(handler):
                return handler.reply(503, dict(hint, error='secret-token private-payload'))
            with patch.object(ProbeHandler, 'do_POST', malicious):
                with self.assertRaises(SyncBusy) as caught:
                    ContentSyncControl(self.nodes[0], deployment='web').synchronize(
                        self.node_ids[1], self.project_id)
            self.assertEqual(caught.exception.busy_resource, 'unknown')
            self.assertIsNone(caught.exception.peer_phase)
            detail = diagnostic(self.nodes[0], self.node_ids[1], self.project_id, direction='outbound')
            self.assertNotIn('secret-token', str(detail)); self.assertNotIn('private-payload', str(detail))
        with _database(self.nodes[0]) as db:
            preserved = db.execute('SELECT operation_id,envelope,bundle FROM outbound WHERE peer_id=? AND project_id=?',
                (self.node_ids[1], self.project_id)).fetchone()
        self.assertEqual(preserved, saved)
        # A transient native writer collision is 503, not permanent rejection.
        # Both sides retain the exact request identity for the next attempt.
        from spikes.federation_sync import _database
        from spikes.git_budget import GitDeadlineExceeded
        with patch.object(SyncReceiver, '_receive', side_effect=GitDeadlineExceeded('validation budget')):
            with self.assertRaises(SyncBusy):
                synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                            deployment='web')
        with patch.object(SyncReceiver, '_receive', side_effect=BlockingIOError()):
            with self.assertRaises(SyncBusy):
                ContentSyncControl(self.nodes[0], deployment='web').synchronize(
                    self.node_ids[1], self.project_id)
        with _database(self.nodes[0]) as db:
            pending_id = db.execute('SELECT operation_id FROM outbound WHERE peer_id=? AND project_id=?',
                (self.node_ids[1], self.project_id)).fetchone()[0]
        status = ContentSyncControl(self.nodes[0], deployment='web').statuses()[
            self.node_ids[1] + ':' + self.project_id]
        self.assertEqual(status['state'], 'busy')
        with _database(self.nodes[0]) as db:
            self.assertEqual(tuple(db.execute(
                'SELECT operation_id,envelope,bundle FROM outbound WHERE peer_id=? AND project_id=?',
                (self.node_ids[1], self.project_id)).fetchone()), tuple(saved))
        result = synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                             deployment='web')
        self.assertEqual(result['state'], 'idle')
        with _database(self.nodes[0]) as db:
            self.assertIsNone(db.execute('SELECT operation_id FROM outbound WHERE operation_id=?',
                                         (saved[0],)).fetchone())
        with _database(self.nodes[1]) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM inbound WHERE operation_id=?',
                                        (saved[0],)).fetchone()[0], 1)
            self.assertIsNotNone(db.execute('SELECT response_envelope FROM inbound WHERE operation_id=?',
                (pending_id,)).fetchone()[0])
        # A lost HTTPS response is replayed byte-for-byte through the actual
        # peer protocol handler, without another Git verification or export.
        from spikes.federation_sync import _database, encode_body, PATH, CONTENT_TYPE
        with _database(self.nodes[1]) as db:
            row = db.execute('SELECT envelope,bundle,response_envelope,response_bundle FROM inbound').fetchone()
        replay_body = encode_body(json.loads(row[0]), bytes(row[1]))
        expected_body = encode_body(json.loads(row[2]), bytes(row[3]))
        connection = http.client.HTTPSConnection('127.0.0.1', server.server_port,
            context=ssl.create_default_context(cafile=tls['ca']), timeout=3)
        try:
            with patch('spikes.federation_sync._validate_git_bundle', side_effect=AssertionError('history')):
                connection.request('POST', PATH, body=replay_body, headers={'Content-Type': CONTENT_TYPE})
                response = connection.getresponse(); replayed = response.read()
            self.assertEqual(response.status, 200, replayed)
            self.assertEqual(replayed, expected_body)
        finally:
            connection.close()
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
        # Even a metadata-only poll gets a bounded conflict response when the
        # peer has local edits, rather than validating history and timing out.
        remote = Projects(self.nodes[1]).workspace(self.project_id)
        path = next(p for p in remote.git.snapshot(remote.git.head()) if p.endswith('.md'))
        target = remote.git.root / path
        target.write_bytes(target.read_bytes() + b'\nUncommitted peer change\n')
        with patch('spikes.federation_sync._verify_bundle', side_effect=AssertionError('history')):
            with self.assertRaises(SyncConflict):
                ContentSyncControl(self.nodes[0], deployment='web').synchronize(
                    self.node_ids[1], self.project_id)
        status = ContentSyncControl(self.nodes[0], deployment='web').statuses()[
            self.node_ids[1] + ':' + self.project_id]
        self.assertEqual(status['state'], 'conflict')
        with _database(self.nodes[0]) as db:
            pending = db.execute('SELECT operation_id FROM outbound WHERE peer_id=? AND project_id=?',
                                 (self.node_ids[1], self.project_id)).fetchone()
        self.assertIsNotNone(pending)
        self.assertIn('Uncommitted peer change', target.read_text())

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
  if not value:
   QTimer.singleShot(20,poll);return
  value=json.loads(value)
  assert value=={'fork':True,'origin':True,'writable':True,'refreshes':True,'syncControls':True},value
  print('project chat fork: WebEngine RW branch verified',flush=True);app.exit(0)
 def poll():
  page.runJavaScript('window.forkEvidence||null',0,received)
 def loaded(ok):
  if not ok:return app.exit(3)
  page.runJavaScript("""(async()=>{activeProject={id:'99999999-9999-4999-8999-999999999999',title:'P'};const t={thread_id:'11111111-1111-4111-8111-111111111111',node_id:'22222222-2222-4222-8222-222222222222',user_id:'33333333-3333-4333-8333-333333333333',status:'active',classification:'brainstorming',created_at:'2026-10-26T12:00:00Z',revision:2,project_id:activeProject.id,assignment_revision:1,response_language:null,forked_from_thread_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',forked_from_digest:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',messages:[],turns:[]};knownThreads=[t];activeThread=t;taskOutcomes=[];document.querySelector('#chat-draft').value='continue';renderThreadList(knownThreads);renderChat(t);let refreshes=0;loadChat=async()=>{refreshes++};document.querySelector('#chats-tab').click();await new Promise(resolve=>setTimeout(resolve,0));document.dispatchEvent(new CustomEvent('contentsynccompleted',{detail:{projectId:activeProject.id}}));window.forkEvidence=JSON.stringify({fork:document.querySelector('#sidebar-chat-tree').textContent.includes('fork'),origin:document.querySelector('#sidebar-chat-tree').textContent.includes('konflikt aaaaaaaa'),writable:!document.querySelector('#chat-submit').disabled,refreshes:refreshes===2,syncControls:document.querySelector('#admin-sync-all').textContent==='Synchronizovat vše'&&document.querySelector('#admin-sync-automatic').type==='checkbox'});})()""");QTimer.singleShot(20,poll)
 page.loadFinished.connect(loaded);page.setUrl(QUrl(server.origin+'/'));QTimer.singleShot(10000,lambda:app.exit(2));raise SystemExit(app.exec())
'''
        result = subprocess.run([sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WebEngine RW branch verified', result.stdout)


if __name__ == '__main__':
    unittest.main()
