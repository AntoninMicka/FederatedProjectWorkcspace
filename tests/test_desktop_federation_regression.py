# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration
from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


class DesktopFederationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.node=Path(self.temp.name)/'fresh'/'node.json'

    def request(self,server,body):
        connection=http.client.HTTPConnection(*server.server_address,timeout=10)
        connection.request('POST','/v1/administration',body=json.dumps(body),headers={
            'Content-Type':'application/json','Authorization':'Bearer '+server.token})
        response=connection.getresponse();result=response.status,json.loads(response.read());connection.close()
        return result

    def test_empty_desktop_can_add_peer_before_first_project(self):
        with running_api('http',handler=DesktopManagementHandler,projects=Projects(self.node)) as server:
            server.administration=Administration(self.node,deployment='desktop')
            self.assertFalse(self.node.exists())
            code,state=self.request(server,{'action':'list'})
            self.assertEqual(code,200);self.assertEqual(len(state['users']),1);self.assertEqual(state['projects'],[])
            node_id=state['node_id'];author_id=state['users'][0]['id']
            code,state=self.request(server,{'action':'add-peer','expected_commit':state['commit_id'],
                'node_id':str(uuid4()),'name':'Peer','endpoint':'https://192.168.100.2:8443','fingerprint':'a'*64})
            self.assertEqual(code,200);self.assertEqual(state['peers'][0]['name'],'Peer')
            self.assertEqual(self.request(server,{'action':'list'})[1]['node_id'],node_id)
            self.assertEqual(ProjectCreation(self.node).author_id(),author_id)

    def test_corrupt_or_lost_previous_identity_is_not_replaced(self):
        with running_api('http',handler=DesktopManagementHandler,projects=Projects(self.node)) as server:
            server.administration=Administration(self.node,deployment='desktop')
            self.assertEqual(self.request(server,{'action':'list'})[0],200)
            before=self.node.read_bytes();self.node.write_bytes(b'not JSON')
            self.assertEqual(self.request(server,{'action':'list'})[0],422)
            self.assertEqual(self.node.read_bytes(),b'not JSON')
            self.node.write_bytes(before);self.node.unlink()
            code,error=self.request(server,{'action':'list'})
            self.assertEqual(code,422);self.assertIn('původní node.json',error['error'])
            self.assertFalse(self.node.exists())

    def test_bootstrap_retry_after_publication_failure_preserves_uuid(self):
        from spikes.journal import sync_dir
        creator=ProjectCreation(self.node)
        def fail_after_publication(directory):
            if Path(directory)==self.node.parent and self.node.exists():
                raise OSError('Interrupted after publication')
            return sync_dir(directory)
        with patch('spikes.project_creation.sync_dir',side_effect=fail_after_publication):
            with self.assertRaises(OSError):creator.initialize_node()
        published=json.loads(self.node.read_bytes())
        self.assertEqual(creator.initialize_node()['id'],published['id'])
        self.assertEqual(creator.initialize_node()['projects'],[])
