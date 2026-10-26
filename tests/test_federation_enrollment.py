# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.chat_threads import ChatThreads
from spikes.federation_accounts import MappingSignatures
from spikes.federation_enrollment import enroll
from spikes.federation_sync import ContentSyncControl, synchronize
from spikes.network_backend import private_root
from spikes.project_creation import ProjectCreation
from spikes.project_chat_sync import chat_root
from spikes.projects import Projects
from spikes.web_server import make_server


class FederationEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server_node = self.root / 'server-node.json'
        self.client_node = self.root / 'client-node.json'
        ProjectCreation(self.server_node).create(
            'Server seed', self.root / 'server-project', str(uuid4()))
        client = ProjectCreation(self.client_node).create(
            'Client seed', self.root / 'client-project', str(uuid4()))
        self.client_project_id = client['id']
        self.server_admin = Administration(self.server_node)
        self.client_admin = Administration(self.client_node, deployment='desktop')
        self.system_actor = {'id': None, 'node_role': 'federation-admin',
                             'memberships': {}}
        state = self.server_admin.request(self.system_actor, {'action': 'list'})
        state = self.server_admin.request(self.system_actor, {
            'action': 'create-user', 'expected_commit': state['commit_id'],
            'name': 'Server user', 'node_role': 'member'})
        self.access_key = state['access_key']
        self.server_user = state['users'][0]['id']
        self.server_id = state['node_id']
        self.cert, self.key = self.root / 'cert.pem', self.root / 'key.pem'
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(self.key), '-out', str(self.cert), '-days', '1',
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1'],
            check=True, capture_output=True)
        token_file = self.root / 'browser-token'
        token_file.write_text(secrets.token_urlsafe(32)); token_file.chmod(0o600)
        self.server = make_server(
            '127.0.0.1', 0, '192.168.100.0/24', self.cert, self.key,
            token_file, self.server_node, hostname='workspace.example.internal')
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start(); self.addCleanup(self.stop_server)
        fingerprint = MappingSignatures(self.server_admin.root).identity()['fingerprint']
        client_state = self.client_admin.request(self.system_actor, {'action': 'list'})
        client_state = self.client_admin.request(self.system_actor, {
            'action': 'add-peer', 'expected_commit': client_state['commit_id'],
            'node_id': self.server_id, 'name': 'Server',
            'endpoint': f'https://127.0.0.1:{self.server.server_port}',
            'fingerprint': fingerprint})
        self.client_admin.request(self.system_actor, {
            'action': 'convert-peer', 'expected_commit': client_state['commit_id'],
            'node_id': self.server_id, 'relationship_type': 'client-server',
            'sharing_level': 'same-team'})

    def stop_server(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()

    def state(self, service):
        return service.request(self.system_actor, {'action': 'list'})

    def test_login_approves_both_peers_binds_accounts_and_rotates_node_credential(self):
        operation = str(uuid4())
        result = enroll(self.client_node, self.server_id, self.access_key,
                        operation_id=operation, ca=self.cert)
        client_peer = result['peers'][0]
        server_peer = self.state(self.server_admin)['peers'][0]
        client_user = ProjectCreation(self.client_node).author_id()
        self.assertEqual(client_peer['trust'], 'approved')
        self.assertEqual(client_peer['sharing_level'], 'same-team')
        self.assertEqual(client_peer['account_binding'], {
            'local_user_id': client_user, 'remote_user_id': self.server_user})
        self.assertEqual(server_peer['trust'], 'approved')
        self.assertEqual(server_peer['sharing_level'], 'same-team')
        self.assertEqual(server_peer['local_role'], 'server')
        self.assertIsNone(server_peer['endpoint'])
        self.assertEqual(server_peer['account_binding'], {
            'local_user_id': self.server_user, 'remote_user_id': client_user})
        credential = private_root(self.client_node) / (self.server_id + '-enrollment.token')
        first_token = credential.read_text()
        self.assertNotEqual(first_token, self.access_key)
        first_client_commit = result['commit_id']
        first_server_commit = self.state(self.server_admin)['commit_id']
        repeated = enroll(self.client_node, self.server_id, self.access_key,
                          operation_id=operation, ca=self.cert)
        self.assertEqual(repeated['commit_id'], first_client_commit)
        self.assertEqual(self.state(self.server_admin)['commit_id'], first_server_commit)
        self.assertNotEqual(credential.read_text(), first_token)
        with sqlite3.connect(self.server_admin.root / 'node-credentials.sqlite') as db:
            self.assertEqual(db.execute(
                'SELECT revision FROM node_credentials WHERE peer_id=?',
                (self.state(self.client_admin)['node_id'],)).fetchone(), (2,))
        server_state = self.state(self.server_admin)
        second = self.server_admin.request(self.system_actor, {
            'action': 'create-user', 'expected_commit': server_state['commit_id'],
            'name': 'Other account', 'node_role': 'member'})
        with self.assertRaisesRegex(AccessDenied, 'rejected'):
            enroll(self.client_node, self.server_id, second['access_key'],
                   operation_id=str(uuid4()), ca=self.cert)
        self.assertEqual(self.state(self.server_admin)['peers'][0]['account_binding'], {
            'local_user_id': self.server_user, 'remote_user_id': client_user})
        server_state = self.state(self.server_admin)
        self.server_admin.request(self.system_actor, {
            'action': 'set-trust', 'expected_commit': server_state['commit_id'],
            'node_id': server_peer['id'], 'trust': 'revoked'})
        with sqlite3.connect(self.server_admin.root / 'node-credentials.sqlite') as db:
            self.assertIsNone(db.execute(
                'SELECT revision FROM node_credentials WHERE peer_id=?',
                (server_peer['id'],)).fetchone())

    def test_wrong_account_key_fails_without_creating_server_peer(self):
        with self.assertRaisesRegex(AccessDenied, 'rejected'):
            enroll(self.client_node, self.server_id, secrets.token_urlsafe(32),
                   operation_id=str(uuid4()), ca=self.cert)
        self.assertEqual(self.state(self.server_admin)['peers'], [])
        self.assertEqual(self.state(self.client_admin)['peers'][0]['trust'], 'pending')

    def test_lost_response_rolls_forward_without_duplicate_peer(self):
        operation = str(uuid4())
        with patch('spikes.federation_enrollment.accept_on_client',
                   side_effect=ConnectionError('lost response')):
            with self.assertRaises(ConnectionError):
                enroll(self.client_node, self.server_id, self.access_key,
                       operation_id=operation, ca=self.cert)
        server_state = self.state(self.server_admin)
        self.assertEqual(len(server_state['peers']), 1)
        self.assertEqual(server_state['peers'][0]['trust'], 'approved')
        result = enroll(self.client_node, self.server_id, self.access_key,
                        operation_id=operation, ca=self.cert)
        self.assertEqual(len(result['peers']), 1)
        self.assertEqual(result['peers'][0]['trust'], 'approved')
        self.assertEqual(len(self.state(self.server_admin)['peers']), 1)

    def test_enrollment_binding_automatically_maps_project_chat(self):
        enroll(self.client_node, self.server_id, self.access_key,
               operation_id=str(uuid4()), ca=self.cert)
        synchronize(self.client_node, self.server_id, self.client_project_id,
                    deployment='desktop', ca=self.cert)
        self.assertIn(self.client_project_id,
                      {item['id'] for item in Projects(self.server_node).catalog()})
        state = self.state(self.server_admin)
        self.server_admin.request(self.system_actor, {
            'action': 'update-user', 'expected_commit': state['commit_id'],
            'user_id': self.server_user, 'active': True, 'node_role': 'member',
            'memberships': {self.client_project_id: 'editor'},
        })
        client_state = self.state(self.client_admin)
        client_user = ProjectCreation(self.client_node).author_id()
        thread_id, turn_id, run_id = (str(uuid4()) for _ in range(3))
        chat_state = chat_root(self.client_node)
        chat_state.mkdir(mode=0o700, exist_ok=True)
        chats = ChatThreads(chat_state)
        chats.create(thread_id=thread_id, node_id=client_state['node_id'],
                     user_id=client_user, created_at='2026-10-26T14:00:00Z',
                     project_id=self.client_project_id)
        chats.prepare_turn(
            thread_id=thread_id, node_id=client_state['node_id'],
            user_id=client_user, turn_id=turn_id, message_id=str(uuid4()),
            content='Enrollment mapping', privacy='project',
            created_at='2026-10-26T14:00:01Z')
        chats.bind_run(turn_id=turn_id, node_id=client_state['node_id'],
                       user_id=client_user, run_id=run_id)
        chats.complete(
            turn_id=turn_id, node_id=client_state['node_id'],
            user_id=client_user, run_id=run_id, message_id=str(uuid4()),
            content='Automatically synchronized', privacy='project',
            created_at='2026-10-26T14:00:02Z')
        synchronize(self.client_node, self.server_id, self.client_project_id,
                    deployment='desktop', ca=self.cert)
        server_state = self.state(self.server_admin)
        received = ChatThreads(chat_root(self.server_node)).get(
            thread_id, server_state['node_id'], self.server_user)
        self.assertEqual(received['messages'][-1]['content'],
                         'Automatically synchronized')
        status = ContentSyncControl(
            self.client_node, deployment='desktop').statuses()[
                self.server_id + ':' + self.client_project_id]
        self.assertEqual(status['chat_summary'], {
            'shared': 1, 'received': 1, 'active_mappings': 1,
            'local_user_ids': [client_user]})


if __name__ == '__main__':
    unittest.main()
