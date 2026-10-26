# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.chat_history_sync import (ChatHistoryReceiver, prepare, received,
                                      reconcile, status, synchronize)
from spikes.chat_threads import ChatThreads
from spikes.federation_accounts import MappingSignatures
from spikes.project_creation import ProjectCreation
from spikes.desktop_ui import DesktopHandler, JS
from spikes.network_backend import NetworkBackend, ProbeHandler, trust_ca
from spikes.web_server import WebHandler, WebServer


NOW = '2026-10-26T12:00:00Z'


class AllowLoopback:
    def allows(self, peer):
        return peer.is_loopback


class ChatHistorySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.project_id = str(uuid4())
        self.nodes = []
        for name in ('a', 'b'):
            folder = self.root / name; folder.mkdir(mode=0o700)
            node = folder / 'node.json'
            node.write_text(json.dumps({'schema_version': 1, 'id': str(uuid4()),
                'name': name, 'projects': [{'project_id': self.project_id,
                    'root': str(folder / 'project'),
                    'state_dir': str(folder / 'project-state')}]}))
            node.chmod(0o600); self.nodes.append(node)
        self.services = [Administration(node, deployment='desktop')
                         for node in self.nodes]
        self.actor = {'id': None, 'node_role': 'federation-admin',
                      'memberships': {}}
        self.states = [self.state(index) for index in range(2)]
        self.node_ids = [state['node_id'] for state in self.states]
        self.user_ids = [ProjectCreation(node).author_id() for node in self.nodes]
        pins = [MappingSignatures(service.root).identity()['fingerprint']
                for service in self.services]
        # P2P relationship creation is a server-side administration action;
        # the resulting signed registry is shared with the desktop projection.
        for local, remote in ((0, 1), (1, 0)):
            web = Administration(self.nodes[local], deployment='web')
            state = web.request(self.actor, {'action': 'list'})
            state = web.request(self.actor, {'action': 'add-peer-relationship',
                'expected_commit': state['commit_id'], 'relationship_type': 'p2p',
                'sharing_level': 'same-team', 'node_id': self.node_ids[remote],
                'name': 'Peer', 'endpoint': 'https://127.0.0.1:8443',
                'fingerprint': pins[remote]})
            web.request(self.actor, {'action': 'update-peer',
                'expected_commit': state['commit_id'],
                'node_id': self.node_ids[remote], 'name': 'Peer',
                'endpoint': 'https://127.0.0.1:8443', 'trust': 'approved',
                'sharing_level': 'same-team'})
        proposed = self.change(0, action='propose-mapping',
            local_user_id=self.user_ids[0], peer_node_id=self.node_ids[1],
            peer_user_id=self.user_ids[1], project_ids=[self.project_id])
        self.mapping_id = proposed['mappings'][0]['spec']['id']
        confirmed = self.change(0, action='confirm-mapping',
                                mapping_id=self.mapping_id)
        imported = self.change(1, action='import-mapping',
                               envelope=confirmed['mapping_envelope'])
        confirmed = self.change(1, action='confirm-mapping',
                                mapping_id=self.mapping_id)
        self.change(0, action='import-mapping',
                    envelope=confirmed['mapping_envelope'])
        self.chat_roots = []
        for node in self.nodes:
            root = node.parent / ('.' + node.name + '.chat')
            root.mkdir(mode=0o700); self.chat_roots.append(root)

    def state(self, index):
        return self.services[index].request(self.actor, {'action': 'list'})

    def change(self, index, **request):
        return self.services[index].request(self.actor, dict(
            expected_commit=self.state(index)['commit_id'], **request))

    def thread(self, *, privacy='project', project=True, answer='Answer', index=0):
        store = ChatThreads(self.chat_roots[index]); thread_id = str(uuid4())
        store.create(thread_id=thread_id, node_id=self.node_ids[index],
                     user_id=self.user_ids[index], created_at=NOW,
                     project_id=self.project_id if project else None)
        turn_id, run_id = str(uuid4()), str(uuid4())
        store.prepare_turn(thread_id=thread_id, node_id=self.node_ids[index],
            user_id=self.user_ids[index], turn_id=turn_id,
            message_id=str(uuid4()), content='Question', privacy=privacy,
            created_at=NOW)
        store.bind_run(turn_id=turn_id, node_id=self.node_ids[index],
                       user_id=self.user_ids[index], run_id=run_id)
        store.complete(turn_id=turn_id, node_id=self.node_ids[index],
            user_id=self.user_ids[index], run_id=run_id,
            message_id=str(uuid4()), content=answer, privacy=privacy,
            created_at='2026-10-26T12:00:01Z')
        return thread_id

    def transfer(self, thread_id, operation_id=None):
        operation_id = operation_id or str(uuid4())
        envelope = prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                           [thread_id], operation_id)
        receipt = ChatHistoryReceiver(
            self.nodes[1], self.services[1]).receive(envelope)
        return envelope, receipt

    def test_signed_snapshot_is_read_only_idempotent_and_separate(self):
        thread_id = self.thread(); operation_id = str(uuid4())
        envelope, first = self.transfer(thread_id, operation_id)
        second = ChatHistoryReceiver(
            self.nodes[1], self.services[1]).receive(envelope)
        self.assertEqual(first, second)
        snapshots = received(self.nodes[1])
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0]['read_only'])
        self.assertEqual(snapshots[0]['recipient_user_id'], self.user_ids[1])
        self.assertEqual(snapshots[0]['original_thread_id'], thread_id)
        self.assertEqual(received(self.nodes[1], recipient_user_id=str(uuid4())), [])
        self.assertFalse((self.chat_roots[1] / 'chat-threads.sqlite').exists())

    def test_new_revision_is_retained_as_divergence_without_overwrite(self):
        thread_id = self.thread(answer='First')
        self.transfer(thread_id)
        store = ChatThreads(self.chat_roots[0])
        # A later immutable turn creates a second snapshot of the same origin.
        turn_id, run_id = str(uuid4()), str(uuid4())
        store.prepare_turn(thread_id=thread_id, node_id=self.node_ids[0],
            user_id=self.user_ids[0], turn_id=turn_id,
            message_id=str(uuid4()), content='Again', privacy='project',
            created_at='2026-10-26T12:01:00Z')
        store.bind_run(turn_id=turn_id, node_id=self.node_ids[0],
                       user_id=self.user_ids[0], run_id=run_id)
        store.complete(turn_id=turn_id, node_id=self.node_ids[0],
            user_id=self.user_ids[0], run_id=run_id,
            message_id=str(uuid4()), content='Second', privacy='project',
            created_at='2026-10-26T12:01:01Z')
        self.transfer(thread_id)
        snapshots = received(self.nodes[1])
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(item['divergent'] for item in snapshots))
        self.assertEqual({len(item['messages']) for item in snapshots}, {2, 4})

    def test_project_and_unassigned_histories_work_in_both_directions(self):
        unassigned = self.thread(project=False)
        self.transfer(unassigned)
        reverse = self.thread(index=1)
        envelope = prepare(self.nodes[1], self.node_ids[0], self.mapping_id,
                           [reverse], str(uuid4()))
        ChatHistoryReceiver(self.nodes[0], self.services[0]).receive(envelope)
        self.assertEqual(received(self.nodes[1],
                                  recipient_user_id=self.user_ids[1])[0]
                         ['project_id'], None)
        self.assertEqual(received(self.nodes[0],
                                  recipient_user_id=self.user_ids[0])[0]
                         ['project_id'], self.project_id)
        self.change(0, action='update-peer', node_id=self.node_ids[1],
            name='Peer', endpoint='https://127.0.0.1:8443', trust='approved',
            sharing_level='same-company')
        with self.assertRaisesRegex(ValueError, 'same-team'):
            prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                    [self.thread(project=False)], str(uuid4()))

    def test_local_only_active_turn_and_revoked_trust_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'local-only'):
            prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                    [self.thread(privacy='local-only')], str(uuid4()))
        store = ChatThreads(self.chat_roots[0]); active = str(uuid4())
        store.create(thread_id=active, node_id=self.node_ids[0],
                     user_id=self.user_ids[0], created_at=NOW,
                     project_id=self.project_id)
        store.prepare_turn(thread_id=active, node_id=self.node_ids[0],
            user_id=self.user_ids[0], turn_id=str(uuid4()),
            message_id=str(uuid4()), content='Pending', privacy='project',
            created_at=NOW)
        with self.assertRaisesRegex(ValueError, 'Active'):
            prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                    [active], str(uuid4()))
        self.change(0, action='update-peer', node_id=self.node_ids[1],
            name='Peer', endpoint='https://127.0.0.1:8443', trust='revoked',
            sharing_level='same-team')
        with self.assertRaises((AccessDenied, ValueError)):
            prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                    [self.thread()], str(uuid4()))

    def test_status_exposes_only_explicit_operations_and_received_snapshots(self):
        self.assertEqual(status(self.nodes[0])['operations'], [])
        thread_id = self.thread(); operation_id = str(uuid4())
        prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                [thread_id], operation_id)
        operation = status(self.nodes[0])['operations'][0]
        self.assertEqual(operation['state'], 'prepared')
        self.assertEqual(operation['operation_id'], operation_id)

    def test_unknown_reconcile_resends_exact_durable_package(self):
        operation_id = str(uuid4())
        prepare(self.nodes[0], self.node_ids[1], self.mapping_id,
                [self.thread()], operation_id)
        bodies = []

        class Connection:
            def request(self, method, path, body, headers):
                bodies.append(body)
            def getresponse(self):
                raise TimeoutError('lost response')
            def close(self):
                pass

        with patch('spikes.chat_history_sync.ssl.create_default_context',
                   return_value=type('Context', (), {'minimum_version': None})()), \
             patch('spikes.chat_history_sync.http.client.HTTPSConnection',
                   side_effect=lambda *args, **kwargs: Connection()):
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    reconcile(self.nodes[0], {'operation_id': operation_id})
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(status(self.nodes[0])['operations'][0]['state'], 'unknown')

    def test_http_and_ui_expose_separate_read_only_history_flow(self):
        self.assertIn('/v1/chat-history/status', DesktopHandler.post_paths)
        self.assertIn('/v1/federation/chat-history', WebHandler.post_paths)
        self.assertIn('spikes.chat_history_sync', ProbeHandler.do_POST.__code__.co_names)
        self.assertIn('Synchronizované historie', JS)
        self.assertIn('!activeThread.read_only', JS)
        self.assertIn("projectRequest('/v1/chat-history/reconcile'", JS)

    def test_pinned_https_transfers_selected_snapshot(self):
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
        self.change(0, action='update-peer', node_id=self.node_ids[1],
            name='Peer', endpoint=endpoint, trust='approved',
            sharing_level='same-team')
        trust_ca(self.nodes[0], self.node_ids[1], Path(tls['ca']).read_bytes())
        result = synchronize(self.nodes[0], {'operation_id': str(uuid4()),
            'peer_id': self.node_ids[1], 'mapping_id': self.mapping_id,
            'thread_ids': [self.thread()]})
        self.assertEqual(result['operations'][0]['state'], 'succeeded')
        self.assertEqual(len(received(self.nodes[1])), 1)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1',
                         'Requires real Qt/WebEngine')
    def test_real_webengine_renders_synced_history_read_only(self):
        script = r'''
import json
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from spikes.desktop import request_policy
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
app = QApplication([])
with running_api('http', handler=DesktopHandler) as server:
    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            policy=request_policy(info.requestUrl().toString(),info.initiator().toString(),bytes(info.requestMethod()).decode(),server.origin)
            if policy=='block': info.block(True)
            elif policy=='authenticate': info.setHttpHeader(b'Authorization',('Bearer '+server.token).encode())
    profile=QWebEngineProfile(app);interceptor=Interceptor(profile);profile.setUrlRequestInterceptor(interceptor);page=QWebEnginePage(profile,app)
    snapshot={'thread_id':'11111111-1111-4111-8111-111111111111','node_id':'22222222-2222-4222-8222-222222222222','user_id':'33333333-3333-4333-8333-333333333333','status':'active','classification':'brainstorming','created_at':'2026-10-26T12:00:00Z','revision':2,'project_id':None,'assignment_revision':0,'response_language':None,'messages':[{'message_id':'44444444-4444-4444-8444-444444444444','sequence':1,'role':'assistant','content':'Imported answer','content_sha256':'x','privacy':'project','author_id':'backend:55555555-5555-4555-8555-555555555555','created_at':'2026-10-26T12:00:01Z','supersedes_id':None}],'turns':[{'turn_id':'66666666-6666-4666-8666-666666666666','user_message_id':'77777777-7777-4777-8777-777777777777','run_id':'55555555-5555-4555-8555-555555555555','assistant_message_id':'44444444-4444-4444-8444-444444444444','state':'completed','error':None,'manifest_id':None,'response_language':None,'language_source':None,'language_compliance':None}],'read_only':True,'snapshot_id':'snapshot-one','source_node_id':'22222222-2222-4222-8222-222222222222','source_user_id':'33333333-3333-4333-8333-333333333333','original_thread_id':'11111111-1111-4111-8111-111111111111','snapshot_digest':'digest','operation_id':'88888888-8888-4888-8888-888888888888','received_at':'2026-10-26T12:00:02Z','divergent':True}
    def received(value):
        if not value:return
        result=json.loads(value);assert result=={'branch':True,'readonly':True,'runtime':False,'composer':True,'text':True},result
        print('chat history: WebEngine read-only branch verified',flush=True);app.exit(0)
    def loaded(ok):
        if not ok:return app.exit(3)
        payload=json.dumps(snapshot,ensure_ascii=False)
        page.runJavaScript("activeProject={id:'99999999-9999-4999-8999-999999999999',title:'P'};syncedHistories=["+payload+"];renderThreadList([]);activeThread=syncedHistories[0];taskOutcomes=[];renderChat(activeThread);JSON.stringify({branch:document.querySelector('#sidebar-chat-tree').textContent.includes('Synchronizované historie'),readonly:!threadWritable(),runtime:Boolean(document.querySelector('.ollama-runtime-record,.chat-message button')),composer:document.querySelector('#chat-submit').disabled,text:document.querySelector('#chat-messages').textContent.includes('Imported answer')});",0,received)
    page.loadFinished.connect(loaded);page.setUrl(QUrl(server.origin+'/'));QTimer.singleShot(10000,lambda:app.exit(2));raise SystemExit(app.exec())
'''
        result = subprocess.run([sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WebEngine read-only branch verified', result.stdout)


if __name__ == '__main__':
    unittest.main()
