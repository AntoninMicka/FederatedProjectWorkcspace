# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import http.client
import json
from http.server import HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.federation_accounts import MappingSignatures, canonical
from spikes.federation_catalog import (
    CONTENT_TYPE, PATH, CatalogControl, CatalogStore, prepare, receive,
)
from spikes.project_creation import ProjectCreation
from spikes.web_server import WebHandler


class FederationCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nodes = []
        self.services = []
        self.actors = []
        for index in range(2):
            directory = self.root / str(index); directory.mkdir(mode=0o700)
            node = directory / 'node.json'
            ProjectCreation(node).create(
                'Projekt ' + str(index), directory / 'project', str(uuid4()))
            service = Administration(node, deployment='web')
            actor = {'id': None, 'node_role': 'federation-admin',
                     'memberships': {}}
            service.request(actor, {'action': 'list'})
            self.nodes.append(node); self.services.append(service)
            self.actors.append(actor)
        self.node_ids = [self.state(i)['node_id'] for i in range(2)]
        self.fingerprints = [MappingSignatures(service.root).identity()['fingerprint']
                             for service in self.services]
        self.connect('same-team')

    def state(self, index):
        return self.services[index].request(
            self.actors[index], {'action': 'list'})

    def change(self, index, **request):
        return self.services[index].request(
            self.actors[index],
            dict(expected_commit=self.state(index)['commit_id'], **request))

    def connect(self, sharing_level):
        for local, remote in ((0, 1), (1, 0)):
            state = self.state(local)
            existing = next((peer for peer in state['peers']
                             if peer['id'] == self.node_ids[remote]), None)
            if existing:
                self.change(local, action='update-peer',
                            node_id=existing['id'], name='Peer',
                            endpoint='https://127.0.0.1:8443',
                            trust='approved', sharing_level=sharing_level)
                continue
            state = self.change(
                local, action='add-peer-relationship',
                relationship_type='p2p', sharing_level=sharing_level,
                node_id=self.node_ids[remote], name='Peer',
                endpoint='https://127.0.0.1:8443',
                fingerprint=self.fingerprints[remote])
            self.services[local].request(self.actors[local], {
                'action': 'update-peer', 'expected_commit': state['commit_id'],
                'node_id': self.node_ids[remote], 'name': 'Peer',
                'endpoint': 'https://127.0.0.1:8443', 'trust': 'approved',
                'sharing_level': sharing_level})

    def test_signed_exchange_stores_only_remote_project_identity_and_title(self):
        envelope, _ = prepare(self.services[0], self.node_ids[1])
        response = receive(self.services[1], envelope)
        returned = receive(self.services[0], response)
        self.assertEqual(returned['catalog']['source_node_id'], self.node_ids[0])
        first = CatalogStore(self.nodes[1]).projections()
        second = CatalogStore(self.nodes[0]).projections()
        self.assertEqual(set(first[0]), {
            'id', 'title', 'peer_id', 'revision', 'updated_at'})
        self.assertEqual(first[0]['title'], 'Projekt 0')
        self.assertEqual(second[0]['title'], 'Projekt 1')
        self.assertNotIn('description', canonical(envelope).decode())
        self.assertNotIn('refs/heads', canonical(envelope).decode())

    def test_same_company_and_external_send_only_selected_project(self):
        for level in ('same-company', 'external'):
            self.connect(level)
            empty, _ = prepare(self.services[0], self.node_ids[1])
            self.assertEqual(empty['catalog']['projects'], [])
            project = json.loads(self.nodes[0].read_text())['projects'][0]['project_id']
            self.actors[0]['memberships'][project] = 'project-admin'
            self.change(
                0, action='set-project-share', peer_id=self.node_ids[1],
                project_id=project, enabled=True,
                branch_mode=('export-only' if level == 'external'
                             else 'all-except-hidden'),
                branches=(['refs/heads/export'] if level == 'external' else []),
                include_patches=False)
            selected, _ = prepare(self.services[0], self.node_ids[1])
            self.assertEqual([row['id'] for row in selected['catalog']['projects']],
                             [project])

    def test_inbound_projection_is_atomic_monotonic_and_not_a_local_project(self):
        store = CatalogStore(self.nodes[1])
        project = {'id': str(uuid4()), 'title': 'Remote'}
        self.assertTrue(store.accept(self.node_ids[0], 2, [project]))
        self.assertFalse(store.accept(self.node_ids[0], 1, []))
        self.assertEqual(store.projections()[0]['id'], project['id'])
        with self.assertRaisesRegex(ValueError, 'changed content'):
            store.accept(self.node_ids[0], 2, [])
        registered = json.loads(self.nodes[1].read_text())['projects']
        self.assertNotIn(project['id'], {row['project_id'] for row in registered})

    def test_revoked_peer_cannot_send_and_external_is_not_automatic(self):
        self.connect('external')
        control = CatalogControl(self.nodes[0], deployment='web')
        with patch.object(control, 'synchronize') as sync:
            control.run_automatic()
        sync.assert_not_called()
        self.change(1, action='set-trust', node_id=self.node_ids[0],
                    trust='revoked')
        envelope, _ = prepare(self.services[0], self.node_ids[1])
        with self.assertRaises(AccessDenied):
            receive(self.services[1], envelope)

    def test_bounded_node_endpoint_rejects_browser_auth(self):
        envelope, _ = prepare(self.services[0], self.node_ids[1])
        server = HTTPServer(('127.0.0.1', 0), WebHandler)
        server.node = self.nodes[1]
        server.administration = self.services[1]
        server.hostname = None
        thread = threading.Thread(target=server.serve_forever); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def request(headers=None):
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            values = {'Content-Type': CONTENT_TYPE}; values.update(headers or {})
            connection.request('POST', PATH, body=canonical(envelope), headers=values)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result

        self.assertEqual(request({'Authorization': 'Bearer browser'})[0], 403)
        code, raw = request()
        self.assertEqual(code, 200, raw)
        self.assertEqual(json.loads(raw)['catalog']['source_node_id'], self.node_ids[1])


if __name__ == '__main__':
    unittest.main()
