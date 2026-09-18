# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.chat_threads import ChatThreads
from spikes.ollama_backend import OllamaAdapter, UnknownRun
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.summary_service import SUMMARY_END, SUMMARY_MARKER, SummaryService
from spikes.metadata import ValidationError, validate_snapshot
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests import test_local_api


class SummaryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'; self.root = self.base / 'project'
        created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root)
        self.artifact_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.artifact_id, base_head=self.git.head(), title='Source',
            body='Known fact.\n', new=True), str(uuid4()))
        self.state = self.base / 'summary-state'; self.state.mkdir(mode=0o700)
        self.chat_state = self.base / 'chat-state'; self.chat_state.mkdir(mode=0o700)
        self.calls = []

        def factory(runs):
            def transport(binding, raw):
                request = json.loads(raw)
                self.calls.append(request)
                return {'model': binding.model, 'response': '# Summary\n\nKnown fact.\n'}
            return OllamaAdapter(runs, transport=transport)
        self.factory = factory
        self.service = SummaryService(self.node, Projects(self.node), state_dir=self.state,
                                      chat_state_dir=self.chat_state,
                                      adapter_factory=factory)
        self.binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
            adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
            model='gemma3', target_id='local-process')
        self.service.configure(self.binding)

    def request(self, **changes):
        value = dict(schema='fpw-summary-request-v1', task_id=str(uuid4()), run_id=str(uuid4()),
            manifest_id=str(uuid4()), project_id=self.project_id,
            expected_head=self.git.head(), role_id='summarizer',
            role_revision='summarizer-v1', target=self.binding,
            selection={'kind': 'artifacts', 'artifact_ids': [self.artifact_id]},
            focus=None)
        value.update(changes)
        return value

    def test_preview_is_durable_readable_and_does_not_write_project(self):
        request = self.request(focus={'input_id': str(uuid4()),
            'content': 'Emphasize confirmed facts.', 'privacy': 'confidential'})
        head = self.git.head()
        result = self.service.preview(request)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['privacy'], 'confidential')
        self.assertEqual(self.git.head(), head)
        self.assertEqual(len(self.calls), 1)
        prompt = self.calls[0]['prompt']
        self.assertIn('Instruction:\nCreate a faithful Markdown summary', prompt)
        self.assertIn('Known fact.', prompt)
        self.assertIn('Focus:\nEmphasize confirmed facts.', prompt)
        self.assertNotIn('content_b64', prompt)

        restarted = SummaryService(self.node, Projects(self.node), state_dir=self.state,
                                   adapter_factory=self.factory)
        self.assertEqual(restarted.status()['tasks'][0]['response'],
                         '# Summary\n\nKnown fact.\n')
        self.assertEqual(restarted.preview(request)['response'], '# Summary\n\nKnown fact.\n')
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_backend_success_reconciles_without_second_request(self):
        request = self.request()
        def checkpoint(stage):
            if stage == 'response-received':
                raise RuntimeError('crash')
        with self.assertRaisesRegex(RuntimeError, 'crash'):
            self.service.preview(request, checkpoint=checkpoint)
        self.assertEqual(len(self.calls), 1)

    def test_assigned_thread_selection_preserves_order_and_privacy(self):
        node_id, user_id = self.service._identity()
        threads = ChatThreads(self.chat_state)
        thread_id, turn_id, first, second, run_id = (str(uuid4()) for _ in range(5))
        threads.create(thread_id=thread_id, node_id=node_id, user_id=user_id,
                       created_at='2026-09-18T14:00:00Z')
        threads.prepare_turn(thread_id=thread_id, node_id=node_id, user_id=user_id,
            turn_id=turn_id, message_id=first, content='Question', privacy='project',
            created_at='2026-09-18T14:00:00Z')
        threads.bind_run(turn_id=turn_id, node_id=node_id, user_id=user_id, run_id=run_id)
        threads.complete(turn_id=turn_id, node_id=node_id, user_id=user_id, run_id=run_id,
            message_id=second, content='Answer', privacy='local-only',
            created_at='2026-09-18T14:00:01Z')
        assigned = threads.assign_project(thread_id=thread_id, node_id=node_id, user_id=user_id,
            project_id=self.project_id, expected_revision=2)
        request = self.request(selection={'kind': 'messages', 'thread_id': thread_id,
            'thread_revision': assigned['revision'], 'message_ids': [first, second]})
        result = self.service.preview(request)
        self.assertEqual(result['privacy'], 'local-only')
        prompt = self.calls[-1]['prompt']
        self.assertLess(prompt.index('User message:\nQuestion'),
                        prompt.index('Assistant message:\nAnswer'))
        result = self.service.preview(request)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(len(self.calls), 1)

    def test_unknown_dispatch_is_durable_and_never_retried(self):
        attempts = []
        def factory(runs):
            def transport(binding, raw):
                attempts.append(raw); raise TimeoutError('lost')
            return OllamaAdapter(runs, transport=transport)
        service = SummaryService(self.node, Projects(self.node), state_dir=self.state,
                                 adapter_factory=factory)
        request = self.request()
        with self.assertRaises(UnknownRun):
            service.preview(request)
        with self.assertRaisesRegex(ValueError, 'cannot be retried'):
            service.preview(request)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(service.status()['tasks'][0]['state'], 'unknown')

    def test_validation_and_same_node_gate_fail_before_transport(self):
        with self.assertRaisesRegex(ValueError, '1 to 64'):
            self.service.preview(self.request(selection={'kind': 'artifacts',
                                                         'artifact_ids': []}))
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            self.service.preview(self.request(expected_head='0' * 40))
        lan = dict(self.binding, revision='two', boundary='private-network',
                   endpoint='https://10.0.0.2:11434', target_id=str(uuid4()),
                   tls_cert_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'same-node'):
            self.service.configure(lan)
        self.assertEqual(self.calls, [])

    def publication(self, preview, **changes):
        value = dict(task_id=preview['task_id'], preview_sha256=preview['response_sha256'],
            project_id=self.project_id, expected_head=self.git.head(), artifact_id=str(uuid4()),
            title='Local summary', created_at='2026-09-18T15:00:00Z',
            operation_id=str(uuid4()))
        value.update(changes)
        return value

    def test_confirmed_publication_preserves_provenance_privacy_and_is_idempotent(self):
        preview = self.service.preview(self.request(focus={'input_id': str(uuid4()),
            'content': 'Private focus', 'privacy': 'confidential'}))
        request = self.publication(preview)
        result = self.service.publish(request)
        self.assertEqual(result['state'], 'published')
        first_head = self.git.head()
        self.assertEqual(self.service.publish(request)['receipt']['commit_id'], first_head)
        self.assertEqual(self.git.head(), first_head)
        files = self.git.snapshot(first_head); entities = validate_snapshot(files)
        metadata = entities[request['artifact_id']]
        self.assertEqual((metadata['privacy'], metadata['provenance']),
                         ('confidential', 'llm-generated'))
        self.assertEqual(metadata['relations'],
                         [{'type': 'summarizes', 'target_id': self.artifact_id}])
        raw = files[f'artifacts/{request["artifact_id"]}/content.md']
        self.assertTrue(raw.startswith(SUMMARY_MARKER.encode()))
        record = json.loads(raw.split(SUMMARY_MARKER.encode(), 1)[1]
                            .split(SUMMARY_END.encode(), 1)[0])
        self.assertEqual(record['preview_sha256'], preview['response_sha256'])
        self.assertEqual(record['sources'][0]['input_id'], self.artifact_id)
        self.assertEqual(record['privacy'], 'confidential')

        document = next(item for item in Artifacts(self.node).open(self.project_id)['documents']
                        if item['metadata']['id'] == request['artifact_id'])
        with self.assertRaisesRegex(ValidationError, 'provenance changed'):
            Artifacts(self.node).save(dict(project_id=self.project_id,
                artifact_id=request['artifact_id'], base_head=self.git.head(),
                title='Local summary', body='# Replaced without envelope\n', new=False),
                str(uuid4()))

    def test_publish_recovery_after_workspace_completion_and_stale_head(self):
        preview = self.service.preview(self.request())
        request = self.publication(preview)
        def checkpoint(stage):
            if stage == 'workspace-complete':
                raise RuntimeError('lost publication response')
        with self.assertRaisesRegex(RuntimeError, 'lost publication'):
            self.service.publish(request, checkpoint=checkpoint)
        committed = self.git.head()
        self.assertEqual(self.service.status()['tasks'][0]['state'], 'publishing')
        result = self.service.publish(request)
        self.assertEqual(result['state'], 'published')
        self.assertEqual(result['receipt']['commit_id'], committed)
        self.assertEqual(self.git.head(), committed)

        later_preview = self.service.preview(self.request())
        stale = self.publication(later_preview)
        self.git.run('commit', '--allow-empty', '-m', 'Move HEAD')
        with self.assertRaisesRegex(ValueError, 'differs from preview'):
            self.service.publish(dict(stale, expected_head=self.git.head()))

    def test_publish_recovers_before_and_after_ref_without_duplicate_artifact(self):
        for crash_stage in ('before-ref', 'ref-updated'):
            with self.subTest(stage=crash_stage):
                preview = self.service.preview(self.request())
                request = self.publication(preview)
                seen = False
                def checkpoint(stage):
                    nonlocal seen
                    if stage == crash_stage and not seen:
                        seen = True
                        raise RuntimeError('publication crash')
                with self.assertRaisesRegex(RuntimeError, 'publication crash'):
                    self.service.publish(request, checkpoint=checkpoint)
                result = self.service.publish(request)
                self.assertEqual(result['state'], 'published')
                files = self.git.snapshot(self.git.head())
                entities = validate_snapshot(files)
                self.assertIn(request['artifact_id'], entities)
                self.assertEqual(sum(value == request['artifact_id'] for value in entities), 1)

    def test_authenticated_desktop_api_exposes_preview_and_publish(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler,
                         projects=Projects(self.node)) as server:
            server.summary_service = self.service
            preview_request = self.request()
            response = driver.request(server, path='/v1/summary/preview',
                                      body=json.dumps(preview_request).encode())
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            preview = json.loads(body)
            publish = self.publication(preview)
            response = driver.request(server, path='/v1/summary/publish',
                                      body=json.dumps(publish).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/summary/status', body=b'{}')
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            self.assertEqual(json.loads(body)['tasks'][0]['state'], 'published')
            driver.rejected(server, path='/v1/summary/status', body=b'{}',
                            headers={'Authorization': None})


if __name__ == '__main__':
    unittest.main()
