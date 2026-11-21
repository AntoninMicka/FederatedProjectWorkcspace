# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import json
import ssl
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

from tests import test_federation_sync as fixtures
from spikes import sync_fingerprint as state
from spikes.federation_sync import ContentSyncControl, SyncReceiver, _database, _prepare, synchronize
from spikes.federation_accounts import canonical
from spikes.network_backend import NetworkBackend, ProbeHandler, trust_ca
from spikes.project_replication import _signature
from spikes.projects import Projects
from spikes.web_server import WebServer


class SyncFingerprintTests(unittest.TestCase):
    setUp = fixtures.FederationSyncTests.setUp
    change = fixtures.FederationSyncTests.change
    state = fixtures.FederationSyncTests.state
    exchange = fixtures.FederationSyncTests.exchange
    map_users = fixtures.FederationSyncTests.map_users
    chat_turn = fixtures.FederationSyncTests.chat_turn
    commit_marker = fixtures.FederationSyncTests.commit_marker

    def server(self):
        tls = NetworkBackend(self.nodes[1]).generate('127.0.0.1', 8443, '127.0.0.0/8')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tls['cert'], tls['key'])
        server = WebServer(('127.0.0.1', 0), ProbeHandler)
        server.tls = context; server.hostname = None
        server.application_access = fixtures.AllowLoopback()
        server.node = self.nodes[1]; server.administration = self.services[1]
        thread = threading.Thread(target=server.serve_forever); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        self.change(0, action='update-peer', node_id=self.node_ids[1], name='Peer',
                    endpoint='https://127.0.0.1:'+str(server.server_port), trust='approved', sharing_level='same-team')
        trust_ca(self.nodes[0], self.node_ids[1], Path(tls['ca']).read_bytes())
        return server

    def test_idle_rounds_skip_preparation_but_remote_edit_is_detected_over_https(self):
        self.server()
        control = ContentSyncControl(self.nodes[0], deployment='web')
        self.assertEqual(control.run_automatic()['attempted'], 1)
        with patch('spikes.federation_sync._prepare', side_effect=AssertionError('expensive prepare')):
            self.assertEqual(control.run_automatic()['attempted'], 0)
            self.assertEqual(control.run_automatic()['attempted'], 0)
        self.commit_marker(1, 'Remote change')
        self.assertEqual(control.run_automatic()['attempted'], 1)
        # Publication changes the local snapshot; a subsequent confirmation round is conservative.
        self.assertLessEqual(control.run_automatic()['attempted'], 1)
        self.assertEqual(control.run_automatic()['attempted'], 0)
        self.assertEqual(Projects(self.nodes[0]).repository(self.project_id).head(),
                         Projects(self.nodes[1]).repository(self.project_id).head())

    def test_one_way_company_share_becomes_quiet_without_reverse_grant(self):
        self.server()
        for index in (0, 1):
            self.change(index, action='update-peer', node_id=self.node_ids[1-index], name='Peer',
                endpoint=self.state(index)['peers'][0]['endpoint'], trust='approved', sharing_level='same-company')
        self.actor['memberships'][self.project_id] = 'project-admin'
        self.change(0, action='set-project-share', peer_id=self.node_ids[1], project_id=self.project_id,
                    enabled=True, branch_mode='selected-only', branches=['refs/heads/main'], include_patches=False)
        control = ContentSyncControl(self.nodes[0], deployment='web')
        self.assertEqual(control.run_automatic()['attempted'], 1)
        self.assertEqual(control.run_automatic()['attempted'], 0)
        self.assertEqual(control.statuses()[self.node_ids[1]+':'+self.project_id]['automatic_check']['state'], 'unchanged')

    def test_registry_writer_never_blocks_direct_manifest_reader(self):
        import fcntl
        from spikes.request_ownership import ProjectBusy
        with (self.services[0].root/'lock').open('a+b') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX)
            with self.assertRaises(ProjectBusy):
                state.collect(self.services[0], self.node_ids[1], self.project_id)
        self.assertIn('fingerprint', state.collect(self.services[0], self.node_ids[1], self.project_id))

    def test_one_unavailable_peer_project_does_not_block_healthy_sync(self):
        from spikes.project_creation import ProjectCreation
        self.server()
        other = ProjectCreation(self.nodes[0]).create('Another', self.nodes[0].parent/'another', str(uuid4()))['id']
        original = state._collect
        def partial(service, peer_id, project, **kwargs):
            if service.node == self.nodes[1] and project == self.project_id:
                raise OSError('private path must not leave node')
            return original(service, peer_id, project, **kwargs)
        control = ContentSyncControl(self.nodes[0], deployment='web')
        with patch('spikes.sync_fingerprint._collect', partial):
            self.assertEqual(control.run_automatic()['attempted'], 1)
        self.assertEqual(Projects(self.nodes[1]).repository(other).head(),
                         Projects(self.nodes[0]).repository(other).head())
        check = control.statuses()[self.node_ids[1]+':'+self.project_id]['automatic_check']
        self.assertEqual(check['state'], 'unavailable')
        self.assertEqual(check['error_type'], 'StateUnavailable')

    def test_chat_changes_without_git_and_private_threads_stay_local(self):
        self.map_users()
        before = state.collect(self.services[0], self.node_ids[1], self.project_id)
        head = Projects(self.nodes[0]).repository(self.project_id).head()
        self.chat_turn(0, answer='Only chat changes')
        after = state.collect(self.services[0], self.node_ids[1], self.project_id)
        self.assertNotEqual(before, after)
        self.assertEqual(head, Projects(self.nodes[0]).repository(self.project_id).head())
        self.chat_turn(0, privacy='local-only')
        self.assertEqual(after, state.collect(self.services[0], self.node_ids[1], self.project_id))

    def test_collect_never_initializes_workspace_or_uses_chat_write_connection(self):
        self.map_users(); self.chat_turn(0)
        import sqlite3
        from contextlib import closing
        from spikes.project_chat_sync import chat_root
        with closing(sqlite3.connect(chat_root(self.nodes[0])/'chat-threads.sqlite')) as owner:
            owner.execute('BEGIN IMMEDIATE')
            self.assertIn('fingerprint', state.collect(self.services[0], self.node_ids[1], self.project_id))
        with patch('spikes.projects.Projects.workspace', side_effect=AssertionError('journal')), \
             patch('spikes.chat_threads.ChatThreads.connect', side_effect=AssertionError('writer')):
            self.assertIn('fingerprint', state.collect(self.services[0], self.node_ids[1], self.project_id))

    def test_concurrent_source_change_is_not_cleared_by_ack(self):
        self.server()
        original = SyncReceiver.receive
        def changing(receiver, *args, **kwargs):
            result = original(receiver, *args, **kwargs)
            self.commit_marker(0, 'Changed while awaiting ACK')
            return result
        with patch.object(SyncReceiver, 'receive', changing):
            synchronize(self.nodes[0], self.node_ids[1], self.project_id, deployment='web', state_manifest=True)
        with _database(self.nodes[0]) as db:
            confirmed = json.loads(db.execute('SELECT local_state FROM confirmed_states').fetchone()[0])
        self.assertNotEqual(confirmed, state.collect(self.services[0], self.node_ids[1], self.project_id))
        self.assertEqual(ContentSyncControl(self.nodes[0], deployment='web').run_automatic()['attempted'], 1)

    def test_receipt_replays_original_snapshot_and_rejects_substitution(self):
        envelope, payload, _, _, _ = _prepare(self.services[0], self.node_ids[1],
            self.project_id, str(uuid4()), [], force_bundle=True)
        receiver = SyncReceiver(self.nodes[1], self.services[1])
        response, _ = receiver.receive(envelope, payload)
        receipt = state.receipt(self.services[1], response)
        peer = self.state(0)['peers'][0]
        original = state.verify_receipt(receipt, response, peer)
        self.commit_marker(1, 'After original response')
        replay, _ = receiver.receive(envelope, payload)
        self.assertEqual(original, state.verify_receipt(state.receipt(self.services[1], replay), replay, peer))
        self.assertNotEqual(original, state.collect(self.services[1], self.node_ids[0], self.project_id))
        with self.assertRaises(ValueError):
            state.verify_receipt(receipt, dict(response, conflict=True), peer)
        with _database(self.nodes[1]) as db:
            db.execute('DELETE FROM response_states')
        self.assertIsNone(state.receipt(self.services[1], response))

    def test_legacy_fallback_and_probe_failure_never_imply_clean(self):
        control = ContentSyncControl(self.nodes[0], deployment='web')
        with patch('spikes.sync_fingerprint.probe', return_value=None), \
             patch.object(control, 'synchronize', return_value={'state':'idle'}) as run:
            self.assertEqual(control.run_automatic()['attempted'], 1)
            run.assert_called_once_with(self.node_ids[1], self.project_id, defer_when_busy=True)
        with patch('spikes.sync_fingerprint.probe', side_effect=TimeoutError), \
             patch.object(control, 'synchronize') as run:
            self.assertEqual(control.run_automatic()['attempted'], 0)
            run.assert_not_called()

    def slow_peer(self, delay):
        """Peer whose state answer takes longer than its response budget."""
        original = state._collect
        def slow(*args, **kwargs):
            time.sleep(delay)
            return original(*args, **kwargs)
        return [patch.object(state, '_collect', slow),
                patch.object(state, 'CONTENT_STATE_TIMEOUT', .6),
                patch('spikes.content_receive_jobs.HEARTBEAT_INTERVAL', .1),
                patch('spikes.peer_transport.HEARTBEAT_IDLE_TIMEOUT', .5)]

    def test_slow_peer_state_answer_is_awaited_with_heartbeats(self):
        """AUDIT-B7-T1: computing many projects on a slow peer is not a timeout."""
        self.server()
        expected = state.receive(self.services[1], _signature(
            self.services[0].root, dict(schema_version=1, source_node_id=self.node_ids[0],
            recipient_node_id=self.node_ids[1], nonce=str(uuid4()), projects=[self.project_id]),
            self.node_ids[0], 'state_request'))['state_manifest']['projects']
        with ExitStack() as stack:
            for item in self.slow_peer(1.2): stack.enter_context(item)
            started = time.monotonic()
            manifest = state.probe(self.services[0], self.node_ids[1], projects=[self.project_id])
        self.assertGreater(time.monotonic() - started, .6, 'longer than the response budget')
        self.assertEqual(manifest, {row['id']: {'fingerprint': row['fingerprint'],
                                                'policy': row['policy']} for row in expected})

    def test_cancelled_check_stops_at_the_next_heartbeat(self):
        from spikes.federation_sync import SyncCancelled
        from spikes.content_receive_jobs import STATE_JOBS
        self.server()
        with ExitStack() as stack:
            for item in self.slow_peer(1.0): stack.enter_context(item)
            with self.assertRaises(SyncCancelled):
                state.probe(self.services[0], self.node_ids[1], projects=[self.project_id],
                            cancelled=lambda: True)
        self.assertTrue(STATE_JOBS.drain(5), 'the read-only answer still ends by itself')

    def test_probe_failure_is_logged_with_type_and_duration_only(self):
        """AUDIT-B7-T1: a failing automatic check must be visible in the log."""
        control = ContentSyncControl(self.nodes[0], deployment='web')
        with patch('spikes.sync_fingerprint.probe', side_effect=TimeoutError('https://10.0.0.1 secret')), \
             patch.object(control, 'synchronize'), \
             self.assertLogs('spikes.federation_sync', 'WARNING') as logs:
            control.run_automatic()
        line = next(line for line in logs.output if 'content_state_failed' in line)
        self.assertIn('error_type=TimeoutError elapsed_ms=', line)
        self.assertNotIn('secret', line); self.assertNotIn('10.0.0.1', line)

    def test_state_answer_reads_authority_once_and_logs_when_slow(self):
        from spikes import federation_sync
        request = dict(schema_version=1, source_node_id=self.node_ids[0],
                       recipient_node_id=self.node_ids[1], nonce=str(uuid4()), projects=[self.project_id])
        envelope = _signature(self.services[0].root, request, self.node_ids[0], 'state_request')
        with patch.object(federation_sync, '_authority', wraps=federation_sync._authority) as read, \
             self.assertNoLogs('spikes.sync_fingerprint', 'WARNING'):
            fast = state.receive(self.services[1], envelope)
        # Once before and once after all projects, never per project.
        self.assertEqual(read.call_count, 2)
        self.assertTrue(fast['state_manifest']['projects'])
        envelope = _signature(self.services[0].root, dict(request, nonce=str(uuid4())),
                              self.node_ids[0], 'state_request')
        with patch.object(state, 'SLOW_STATE_MS', 0), \
             self.assertLogs('spikes.sync_fingerprint', 'WARNING') as logs:
            slow = state.receive(self.services[1], envelope)
        self.assertEqual([row['fingerprint'] for row in slow['state_manifest']['projects']],
                         [row['fingerprint'] for row in fast['state_manifest']['projects']])
        self.assertRegex(logs.output[0], r'content_state_slow elapsed_ms=\d+ projects=\d+ '
                                         r'slowest_project_ms=\d+ unavailable=0')

    def test_final_ack_failure_rolls_back_confirmation_and_replays_exact_intent(self):
        import sqlite3
        self.server()
        with _database(self.nodes[0]) as db:
            db.execute("CREATE TRIGGER stop_ack BEFORE DELETE ON outbound BEGIN "
                       "SELECT RAISE(ABORT, 'injected crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                        deployment='web', state_manifest=True)
        with _database(self.nodes[0]) as db:
            pending = db.execute('SELECT operation_id,envelope,bundle FROM outbound').fetchone()
            self.assertIsNotNone(pending)
            self.assertEqual(db.execute('SELECT * FROM confirmed_states').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM prepared_states').fetchone()[0], 1)
            db.execute('DROP TRIGGER stop_ack')
        with patch('spikes.federation_sync._prepare', side_effect=AssertionError('rebuild replay')):
            self.assertEqual(synchronize(self.nodes[0], self.node_ids[1], self.project_id,
                             deployment='web', state_manifest=True)['state'], 'idle')
        with _database(self.nodes[0]) as db:
            self.assertEqual(db.execute('SELECT * FROM outbound').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM confirmed_states').fetchone()[0], 1)

    def test_pending_intent_resumes_even_when_local_manifest_read_is_unavailable(self):
        from spikes.federation_accounts import canonical
        envelope, payload, _, refs, chats = _prepare(self.services[0], self.node_ids[1],
            self.project_id, str(uuid4()), [], force_bundle=True)
        with _database(self.nodes[0]) as db:
            db.execute('INSERT INTO outbound VALUES(?,?,?,?,?,?)', (self.node_ids[1], self.project_id,
                envelope['exchange']['operation_id'], canonical(envelope).decode(), payload,
                canonical(dict(refs=refs, chats=chats)).decode()))
        control = ContentSyncControl(self.nodes[0], deployment='web')
        with patch('spikes.sync_fingerprint.probe', return_value={}), \
             patch('spikes.sync_fingerprint.collect', side_effect=AssertionError('rebuild')), \
             patch.object(control, 'synchronize', return_value={'state':'idle'}) as run:
            self.assertEqual(control.run_automatic()['attempted'], 1)
            run.assert_called_once_with(self.node_ids[1], self.project_id, defer_when_busy=True, state_manifest=True)

    def test_probe_rejects_stale_nonce_and_only_explicit_legacy_statuses_fallback(self):
        self.server()
        service = self.services[1]
        status = [200]; stale = [False]
        class Response:
            def __init__(inner, raw): inner.raw = raw; inner.status = status[0]
            def read(inner, limit): return inner.raw[:limit]
            def getheader(inner, name): return state.CONTENT_TYPE  # a legacy, unstreamed peer
            def close(inner): pass
        class Connection:
            def __init__(inner, *args, **kwargs): pass
            def request(inner, method, path, *, body, headers):
                result = state.receive(service, json.loads(body))
                if stale[0]:
                    value = dict(result['state_manifest'], nonce=str(uuid4()))
                    result = _signature(service.root, value, self.node_ids[1], 'state_manifest')
                inner.raw = canonical(result)
            def getresponse(inner): return Response(inner.raw)
            def check_deadline(inner): pass
            def close(inner): pass
        with patch('spikes.sync_fingerprint.DeadlineHTTPSConnection', Connection):
            self.assertIsInstance(state.probe(self.services[0], self.node_ids[1]), dict)
            stale[0] = True
            with self.assertRaises(ValueError): state.probe(self.services[0], self.node_ids[1])
            for code in (404, 405, 415):
                status[0] = code
                self.assertIsNone(state.probe(self.services[0], self.node_ids[1]))
            for code in (403, 422, 503):
                status[0] = code
                with self.assertRaises(ValueError): state.probe(self.services[0], self.node_ids[1])

    def test_manifest_signature_recipient_and_nonce_are_enforced(self):
        request = dict(schema_version=1, source_node_id=self.node_ids[0],
                       recipient_node_id=self.node_ids[1], nonce=str(uuid4()), projects=[])
        envelope = _signature(self.services[0].root, request, self.node_ids[0], 'state_request')
        response = state.receive(self.services[1], envelope)
        self.assertEqual(response['state_manifest']['nonce'], request['nonce'])
        request['recipient_node_id'] = str(uuid4())
        with self.assertRaises(ValueError):
            state.receive(self.services[1], _signature(self.services[0].root, request, self.node_ids[0], 'state_request'))
        envelope['signature'] = 'x'
        with self.assertRaises(ValueError): state.receive(self.services[1], envelope)
