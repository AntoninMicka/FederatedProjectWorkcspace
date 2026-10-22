# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import copy
import http.client
from http.server import HTTPServer
import json
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.git_transfer import validate_history
from spikes.project_creation import ProjectCreation
from spikes.project_repair import ProjectDiagnostics
from spikes.projects import Projects
from spikes.project_replication import (
    CONTENT_TYPE, PATH as REPLICATION_PATH, ReplicationReceiver,
    decode_body, encode_body, prepare, send,
)
from spikes.network_backend import ProbeHandler
from spikes.source_import import Sources, request_from_file
from spikes.storage import Git
from spikes.workspace import PendingOperation


class ProjectReplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.nodes = [self.base / name / 'node.json' for name in ('a', 'b')]
        for node in self.nodes:
            node.parent.mkdir(mode=0o700)
        created = ProjectCreation(self.nodes[0]).create(
            'Replicated', self.nodes[0].parent / 'project', str(uuid4()))
        self.project_id = created['id']
        ProjectCreation(self.nodes[1]).initialize_node()
        self.services = [Administration(node) for node in self.nodes]
        self.actors = [
            {'id': None, 'node_role': 'federation-admin',
             'memberships': {self.project_id: 'project-admin'}},
            {'id': None, 'node_role': 'federation-admin', 'memberships': {}},
        ]
        states = [self.change(index, action='create-user', name='Owner',
                              node_role='member') for index in (0, 1)]
        self.users = [state['users'][0]['id'] for state in states]
        self.node_ids = [state['node_id'] for state in states]
        self.pins = [state['mapping_identity']['fingerprint'] for state in states]
        self.change(0, action='update-user', user_id=self.users[0], active=True,
                    node_role='member', memberships={self.project_id: 'project-admin'})
        for index in (0, 1):
            remote = 1 - index
            self.change(index, action='add-peer', node_id=self.node_ids[remote],
                        name='Peer', endpoint='https://192.168.100.2:8443',
                        fingerprint=self.pins[remote])
            self.change(index, action='set-trust', node_id=self.node_ids[remote],
                        trust='approved')
        state = self.change(
            0, action='propose-mapping', local_user_id=self.users[0],
            peer_node_id=self.node_ids[1], peer_user_id=self.users[1],
            project_ids=[self.project_id])
        self.mapping_id = state['mappings'][0]['spec']['id']
        first = self.change(0, action='confirm-mapping',
                            mapping_id=self.mapping_id)['mapping_envelope']
        self.change(1, action='import-mapping', envelope=first)
        second = self.change(1, action='confirm-mapping',
                             mapping_id=self.mapping_id)['mapping_envelope']
        self.change(0, action='import-mapping', envelope=second)
        state = self.change(
            0, action='propose-replication', mapping_id=self.mapping_id,
            project_id=self.project_id, primary_node_id=self.node_ids[0],
            privacy=['project', 'public'])
        self.replication_id = state['replications'][0]['spec']['id']
        first = self.change(0, action='confirm-replication',
                            replication_id=self.replication_id)['replication_envelope']
        self.change(1, action='import-replication', envelope=first)
        second = self.change(1, action='confirm-replication',
                             replication_id=self.replication_id)['replication_envelope']
        self.change(0, action='import-replication', envelope=second)
        for index in (0, 1):
            self.change(index, action='set-replication-enabled',
                        replication_id=self.replication_id, enabled=True)

    def state(self, index):
        return self.services[index].request(self.actors[index], {'action': 'list'})

    def change(self, index, **request):
        return self.services[index].request(
            self.actors[index], dict(expected_commit=self.state(index)['commit_id'],
                                     **request))

    def import_source(self, name, privacy='project'):
        path = self.base / (name + '.md'); path.write_text('# ' + name + '\n')
        git = Git(self.nodes[0].parent / 'project')
        request = request_from_file(
            self.project_id, git.head(), str(path), name, '', [], privacy)
        Sources(self.nodes[0]).import_source(request, str(uuid4()))
        return git.head()

    def prepared(self, expected_base):
        return prepare(self.nodes[0], self.replication_id, str(uuid4()),
                       expected_base, deployment='web')

    def receive(self, envelope, payload, checkpoint=lambda stage: None):
        return ReplicationReceiver(
            self.nodes[1], self.services[1]).receive(envelope, payload, checkpoint)

    def test_initial_replica_and_followup_fast_forward_are_idempotent(self):
        first_head = self.import_source('first')
        envelope, payload, _, count = self.prepared(None)
        framed = encode_body(envelope, payload)
        decoded, decoded_payload = decode_body(framed)
        self.assertEqual(decoded, envelope); self.assertEqual(decoded_payload, payload)
        receipt = self.receive(envelope, payload)
        self.assertEqual(receipt['receipt']['head'], first_head)
        self.assertGreaterEqual(count, 2)
        self.assertEqual(self.receive(envelope, payload), receipt)
        destination = self.nodes[1].parent / 'projects' / ('project-' + self.project_id)
        self.assertEqual(Git(destination).head(), first_head)

        second_head = self.import_source('second')
        update, update_payload, _, _ = self.prepared(first_head)
        receipt = self.receive(update, update_payload)
        self.assertEqual(receipt['receipt']['head'], second_head)
        self.assertEqual(Git(destination).head(), second_head)
        self.assertEqual(self.receive(update, update_payload), receipt)

    def test_crash_after_cas_rolls_forward_without_second_ref_effect(self):
        base = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)
        self.receive(initial, payload)
        candidate = self.import_source('candidate')
        update, payload, _, _ = self.prepared(base)

        def crash(stage):
            if stage == 'ref-updated':
                raise OSError('simulated crash')

        with self.assertRaisesRegex(OSError, 'simulated crash'):
            self.receive(update, payload, crash)
        destination = self.nodes[1].parent / 'projects' / ('project-' + self.project_id)
        self.assertEqual(Git(destination).head(), candidate)
        receipt = self.receive(update, payload)
        self.assertEqual(receipt['receipt']['head'], candidate)
        self.assertEqual(Git(destination).run('status', '--porcelain').stdout, '')

    def test_pre_cas_marker_blocks_reads_and_repair_does_not_guess(self):
        base = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)
        self.receive(initial, payload)
        self.import_source('candidate')
        update, payload, _, _ = self.prepared(base)

        def crash(stage):
            if stage == 'prepared':
                raise OSError('simulated pre-CAS crash')

        with self.assertRaisesRegex(OSError, 'pre-CAS'):
            self.receive(update, payload, crash)
        report = ProjectDiagnostics(self.nodes[1]).check(self.project_id)
        finding = next(row for row in report['findings']
                       if row['code'] == 'journal-external-replication')
        self.assertEqual(finding['action'], 'manual')
        with self.assertRaisesRegex(PendingOperation, 'unfinished operation'):
            Projects(self.nodes[1]).open(self.project_id)
        self.receive(update, payload)

    def test_initial_registration_crash_recovers_same_destination(self):
        head = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)

        def crash(stage):
            if stage == 'node-published':
                raise OSError('simulated registration crash')

        with self.assertRaisesRegex(OSError, 'registration crash'):
            self.receive(initial, payload, crash)
        receipt = self.receive(initial, payload)
        self.assertEqual(receipt['receipt']['head'], head)
        catalog = Projects(self.nodes[1]).catalog()
        self.assertEqual([row['id'] for row in catalog], [self.project_id])

    def test_divergence_tampering_revocation_and_local_only_fail_closed(self):
        base = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)
        self.receive(initial, payload)
        candidate = self.import_source('candidate')
        update, update_payload, _, _ = self.prepared(base)
        tampered = bytearray(update_payload); tampered[-1] ^= 1
        with self.assertRaises(ValueError):
            self.receive(update, bytes(tampered))

        destination = self.nodes[1].parent / 'projects' / ('project-' + self.project_id)
        marker = destination / 'foreign.txt'; marker.write_text('foreign')
        Git(destination).commit('Foreign replica commit')
        with self.assertRaisesRegex(ValueError, 'diverged'):
            self.receive(update, update_payload)
        self.assertNotEqual(Git(destination).head(), candidate)

        self.change(1, action='revoke-replication',
                    replication_id=self.replication_id)
        with self.assertRaises(AccessDenied):
            self.receive(update, update_payload)

        # Source-side validation independently rejects local-only history.
        self.import_source('private', privacy='local-only')
        with self.assertRaisesRegex(ValueError, 'local-only'):
            self.prepared(base)

    def test_candidate_must_include_expected_base_and_match_signed_bytes(self):
        self.import_source('first')
        envelope, payload, _, _ = self.prepared(None)
        changed = copy.deepcopy(envelope)
        changed['request']['candidate_head'] = '0' * 40
        with self.assertRaises((ValueError, subprocess.SubprocessError)):
            self.receive(changed, payload)
        self.assertGreaterEqual(validate_history(
            Git(self.nodes[0].parent / 'project'),
            Git(self.nodes[0].parent / 'project').head(), self.project_id,
            frozenset({'public', 'project'})), 2)

    def test_bounded_binary_endpoint_uses_node_signature_not_browser_token(self):
        base = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)
        self.receive(initial, payload)
        candidate = self.import_source('candidate')
        update, payload, _, _ = self.prepared(base)
        server = HTTPServer(('127.0.0.1', 0), ProbeHandler)
        server.node = self.nodes[1]; server.administration = self.services[1]
        thread = threading.Thread(target=server.serve_forever); thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def request(headers=None):
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            values = {'Content-Type': CONTENT_TYPE}; values.update(headers or {})
            connection.request('POST', REPLICATION_PATH,
                               body=encode_body(update, payload), headers=values)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result

        self.assertEqual(request({'Authorization': 'Bearer browser-token'})[0], 403)
        code, raw = request()
        self.assertEqual(code, 200, raw)
        self.assertEqual(Git(self.nodes[1].parent / 'projects' /
                             ('project-' + self.project_id)).head(), candidate)

    def test_source_accepts_only_matching_signed_receipt_and_stores_it(self):
        base = self.import_source('base')
        initial, payload, _, _ = self.prepared(None)
        self.receive(initial, payload)
        self.import_source('candidate')
        operation = str(uuid4())
        envelope, payload, authority, count = prepare(
            self.nodes[0], self.replication_id, operation, base,
            deployment='web')
        receipt = self.receive(envelope, payload)
        response = Mock(status=200)
        response.read.return_value = json.dumps(receipt).encode()
        connection = Mock(); connection.getresponse.return_value = response
        with patch('spikes.project_replication.prepare',
                   return_value=(envelope, payload, authority, count)), \
             patch('spikes.project_replication.ssl.create_default_context'), \
             patch('spikes.project_replication.http.client.HTTPSConnection',
                   return_value=connection):
            result = send(self.nodes[0], self.replication_id, operation, base,
                          ca=self.base / 'unused-ca.pem', deployment='web')
        self.assertEqual(result['head'], envelope['request']['candidate_head'])
        journal = self.nodes[0].parent / ('.' + self.nodes[0].name + '.network') \
            / 'git-transfer-journal.sqlite'
        with sqlite3.connect(journal) as db:
            done, stored = db.execute(
                'SELECT done,receipt FROM transfers WHERE operation_id=?',
                (operation,)).fetchone()
        self.assertEqual(done, 1); self.assertIsNotNone(stored)


if __name__ == '__main__':
    unittest.main()
