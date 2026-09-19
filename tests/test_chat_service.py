# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.chat_service import ChatService
from spikes.configuration import read_config
from spikes.ollama_backend import OllamaAdapter, OllamaRuns, UnknownRun
from spikes.storage import Git
from spikes.projects import Projects
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests import test_local_api
from tests.fixtures import AUTHOR, ENTITY, encoded
from tests.test_configuration import project


NOW = '2026-09-18T14:00:00Z'


class FakeAdapter:
    def __init__(self, runs, calls, error=None):
        self.runs, self.calls, self.error = runs, calls, error

    def prepare(self, handoff, binding):
        self.calls.append(('prepare', handoff, binding))

    def dispatch(self, handoff, binding):
        self.calls.append(('dispatch', handoff, binding))
        if self.error:
            raise self.error
        return {'model': binding.model, 'response': 'Assistant answer'}


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'project'; self.root.mkdir()
        self.project_state = self.base / 'project-state'; self.project_state.mkdir(mode=0o700)
        self.chat_state = self.base / 'chat-state'; self.chat_state.mkdir(mode=0o700)
        self.node_path = self.base / 'node.json'
        self.node_id = str(uuid4())
        self.git = Git(self.root); self.git.run('init', '--initial-branch=main')
        self.root.chmod(0o755); (self.root / '.git').chmod(0o755)
        (self.root / 'project.json').write_bytes(encoded(project()))
        self.git.commit('Project')
        self.node_path.write_bytes(encoded(dict(schema_version=1, id=self.node_id, name='Node',
            projects=[dict(project_id=ENTITY, root=str(self.root),
                           state_dir=str(self.project_state))])))
        self.node_path.chmod(0o600)
        self.calls = []
        self.error = None
        self.service = ChatService(self.node_path, Projects(self.node_path),
            state_dir=self.chat_state,
            adapter_factory=lambda runs: FakeAdapter(runs, self.calls, self.error))
        self.binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
                            adapter='ollama', boundary='same-node',
                            endpoint='http://127.0.0.1:11434', model='gemma3',
                            target_id='local-process')
        self.service.configure(self.binding)

    def request(self, **changes):
        value = dict(project_id=ENTITY, expected_head=self.git.head(),
                     thread_id=str(uuid4()), turn_id=str(uuid4()), message_id=str(uuid4()),
                     run_id=str(uuid4()), manifest_id=str(uuid4()),
                     assistant_message_id=str(uuid4()), selected_message_ids=[],
                     content='First question', privacy='project', created_at=NOW)
        value.update(changes)
        return value

    def test_invalid_reconfiguration_preserves_confirmed_binding(self):
        before = self.service.status()['binding']
        invalid = dict(self.binding, revision='two', endpoint='http://localhost:11434')
        with self.assertRaises(ValueError):
            self.service.configure(invalid)
        self.assertEqual(self.service.status()['binding'], before)
        with self.assertRaisesRegex(ValueError, 'Unsupported backend adapter'):
            self.service.configure(dict(self.binding, adapter='unknown'))
        self.assertEqual(self.service.status()['binding'], before)

    def test_external_backend_configuration_is_visible_without_returning_secret(self):
        secret = 'sk-test-' + 'q' * 32
        request = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
                       adapter='openai-responses', boundary='external-provider',
                       endpoint='https://api.openai.com/v1/responses',
                       model='gpt-5.6-luna', target_id='api.openai.com',
                       max_output_tokens=4096, timeout_seconds=180, secret=secret)
        result = self.service.configure_external(request)
        encoded_result = json.dumps(result)
        self.assertEqual(result['binding']['adapter'], 'openai-responses')
        self.assertTrue(result['credential']['available'])
        self.assertNotIn(secret, encoded_result)
        self.assertNotIn('secret', encoded_result)
        self.assertEqual(ChatService(self.node_path, Projects(self.node_path),
            state_dir=self.chat_state).external_status(), result)
        self.assertNotIn(secret, self.git.snapshot(self.git.head()).values())

        class Catalog:
            def __init__(self, root, credentials):
                self.credentials = credentials
            def refresh(self, binding):
                _, revision = self.credentials.resolve(binding.credential_ref)
                return {'schema_version': 1, 'binding_id': binding.binding_id,
                        'credential_revision': revision, 'fetched_at': NOW,
                        'models': ['gpt-5.6-luna']}
        models = self.service.external_models(Catalog)
        self.assertEqual(models['models'], ['gpt-5.6-luna'])
        self.assertNotIn(secret, json.dumps(models))
        self.assertIsNone(self.service.external_status()['model_catalog'])

    def test_chat_uses_common_unscoped_execution_contract(self):
        calls = []
        service = ChatService(self.node_path, Projects(self.node_path),
            state_dir=self.chat_state, adapter_factory=lambda runs: OllamaAdapter(
                runs, transport=lambda binding, raw:
                (calls.append(raw), {'model': binding.model, 'response': 'Answer'})[1]))
        request = self.request(); service.send(**request)
        row = OllamaRuns(self.chat_state).get(request['run_id'])
        self.assertEqual((row['adapter_id'], row['operation'], row['output_format']),
                         ('ollama', 'generate-text', 'text'))
        self.assertIsNone(row['role_id'])
        self.assertEqual(len(row['manifest_sha256']), 64)
        self.assertEqual(len(calls), 1)

    def test_context_dispatch_and_restart_preserve_exact_messages_and_target(self):
        request = self.request()
        result = self.service.send(**request)
        self.assertEqual([item['content'] for item in result['thread']['messages']],
                         ['First question', 'Assistant answer'])
        self.assertEqual(result['target']['model'], 'gemma3')
        self.assertEqual([call[0] for call in self.calls], ['prepare', 'dispatch'])
        handoff = self.calls[0][1]
        payload = json.loads(handoff.payload)
        self.assertEqual(base64.b64decode(payload['inputs'][0]['content_b64']), b'First question')
        self.assertEqual(handoff.target.binding_id, self.binding['binding_id'])
        # The manifest digest binds the durable run to the exact thread selection.
        self.assertEqual(len(handoff.manifest_sha256), 64)
        self.assertEqual(handoff.manifest_id, request['manifest_id'])

        restarted = ChatService(self.node_path, Projects(self.node_path),
                                state_dir=self.chat_state,
                                adapter_factory=lambda runs: FakeAdapter(runs, self.calls))
        rows = restarted.status()['threads']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['messages'][1]['content'], 'Assistant answer')

    def test_followup_requires_explicit_ordered_selection(self):
        first = self.request(); result = self.service.send(**first)
        ids = [item['message_id'] for item in result['thread']['messages']]
        followup = self.request(thread_id=first['thread_id'], content='Follow up',
                                created_at='2026-09-18T14:00:02Z',
                                selected_message_ids=ids)
        result = self.service.send(**followup)
        payload = json.loads(self.calls[-2][1].payload)
        self.assertEqual([base64.b64decode(item['content_b64']).decode()
                          for item in payload['inputs']],
                         ['First question', 'Assistant answer', 'Follow up'])
        bad = self.request(thread_id=first['thread_id'], content='Bad order',
                           created_at='2026-09-18T14:00:03Z',
                           selected_message_ids=list(reversed(ids)))
        with self.assertRaisesRegex(ValueError, 'thread order'):
            self.service.send(**bad)

    def test_unknown_dispatch_is_durable_and_not_an_assistant_message(self):
        self.error = UnknownRun('lost response')
        request = self.request()
        with self.assertRaises(UnknownRun):
            self.service.send(**request)
        thread = self.service.status()['threads'][0]
        self.assertEqual([item['role'] for item in thread['messages']], ['user'])
        from spikes.chat_threads import ChatThreads
        turn = ChatThreads(self.chat_state).get_turn(request['turn_id'], self.node_id,
                                                       thread['user_id'])
        self.assertEqual(turn['state'], 'unknown')

    def test_stale_project_and_local_only_lan_fail_before_dispatch(self):
        stale = self.request(expected_head='0' * 40)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.send(**stale)
        self.assertEqual(self.service.status()['threads'], [])

        lan = dict(self.binding, revision='two', boundary='private-network',
                   endpoint='https://10.0.0.2:11434', target_id=str(uuid4()),
                   tls_cert_sha256='a' * 64)
        self.service.configure(lan)
        with self.assertRaisesRegex(ValueError, 'local-only'):
            self.service.send(**self.request(privacy='local-only'))
        self.assertFalse(any(call[0] == 'dispatch' for call in self.calls))

    def test_authenticated_desktop_api_exposes_status_and_send(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler,
                         projects=Projects(self.node_path)) as server:
            server.chat_service = self.service
            response = driver.request(server, path='/v1/chat/status', body=b'{}')
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            self.assertEqual(json.loads(body)['binding']['model'], 'gemma3')
            request = json.dumps(self.request()).encode()
            response = driver.request(server, path='/v1/chat/send', body=request)
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            thread = json.loads(body)['thread']
            self.assertEqual(thread['messages'][-1]['role'], 'assistant')
            assignment = json.dumps({'project_id': ENTITY, 'thread_id': thread['thread_id'],
                                     'expected_revision': thread['revision']}).encode()
            response = driver.request(server, path='/v1/chat/assign', body=assignment)
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            assigned = json.loads(body)
            snapshot = {'operation_id': str(uuid4()), 'project_id': ENTITY,
                        'thread_id': assigned['thread_id'],
                        'expected_thread_revision': assigned['revision'],
                        'expected_head': self.git.head(), 'snapshot_id': str(uuid4()),
                        'mode': 'full', 'title': 'Snapshot', 'created_at': NOW,
                        'base_snapshot_id': None, 'base_snapshot_sha256': None}
            response = driver.request(server, path='/v1/chat/snapshot',
                                      body=json.dumps(snapshot).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            driver.rejected(server, path='/v1/chat/status', body=b'{}',
                            headers={'Authorization': None})


if __name__ == '__main__':
    unittest.main()
