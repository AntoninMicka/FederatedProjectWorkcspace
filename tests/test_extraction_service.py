# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.extraction_schemas import validate_preview
from spikes.extraction_service import ExtractionService
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.ollama_backend import OllamaAdapter, OllamaRuns, UnknownRun
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from tests import test_local_api


class ExtractionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'; self.root = self.base / 'project'
        created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root)
        self.artifact_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.artifact_id, base_head=self.git.head(), title='Source',
            body='The launch date is Friday.\n', new=True), str(uuid4()))
        self.state = self.base / 'ai-state'; self.state.mkdir(mode=0o700)
        self.calls = []; self.response = None; self.error = None

        def factory(runs):
            def transport(binding, raw):
                self.calls.append(json.loads(raw))
                if self.error:
                    raise self.error
                response = self.response or json.dumps({'schema': 'facts-v1', 'items': [
                    {'statement': 'The launch date is Friday.',
                     'source_ids': [self.artifact_id]}]})
                return {'model': binding.model, 'response': response}
            return OllamaAdapter(runs, transport=transport)
        self.factory = factory
        self.service = ExtractionService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=factory)
        self.binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
            adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
            model='gemma3', target_id='local-process')
        self.service.configure(self.binding)

    def request(self, **changes):
        value = dict(schema='fpw-extraction-request-v1', task_id=str(uuid4()),
            run_id=str(uuid4()), manifest_id=str(uuid4()), project_id=self.project_id,
            expected_head=self.git.head(), role_id='extractor', role_revision='extractor-v1',
            target=self.binding, schema_id='facts', schema_revision='facts-v1',
            selection={'kind': 'artifacts', 'artifact_ids': [self.artifact_id]}, focus=None)
        value.update(changes)
        return value

    def test_valid_preview_is_canonical_durable_and_does_not_write_git(self):
        head = self.git.head(); request = self.request()
        result = self.service.preview(request)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(json.loads(result['response'])['schema'], 'facts-v1')
        self.assertEqual(result['response'], json.dumps(json.loads(result['response']),
            ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        self.assertEqual(self.git.head(), head)
        self.assertIn('Return JSON only', self.calls[0]['prompt'])
        run = OllamaRuns(self.state).get(request['run_id'])
        self.assertEqual((run['role_id'], run['role_revision'], run['output_format']),
                         ('extractor', 'extractor-v1', 'json'))
        restarted = ExtractionService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=self.factory)
        self.assertEqual(restarted.preview(request)['response'], result['response'])
        self.assertEqual(len(self.calls), 1)

    def test_invalid_or_unexpected_json_is_failed_and_never_a_preview(self):
        invalid = ['```json\n{}\n```', '{"schema":"facts-v1","items":[{"statement":"x"}]}',
                   '{"schema":"facts-v1","items":[],"extra":true}',
                   '{"schema":"facts-v1","schema":"facts-v1","items":[]}']
        for raw in invalid:
            with self.subTest(raw=raw):
                self.response = raw; request = self.request()
                with self.assertRaises(ValueError):
                    self.service.preview(request)
                task = next(item for item in self.service.status()['tasks']
                            if item['task_id'] == request['task_id'])
                self.assertEqual(task['state'], 'failed')
                self.assertIsNone(task['response'])

    def test_schema_source_references_and_limits_are_strict(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported extraction schema'):
            self.service.preview(self.request(schema_revision='custom-v1'))
        foreign = str(uuid4())
        raw = json.dumps({'schema': 'facts-v1', 'items': [
            {'statement': 'Invented', 'source_ids': [foreign]}]})
        with self.assertRaisesRegex(ValueError, 'unselected source'):
            validate_preview(raw, 'facts', 'facts-v1', [self.artifact_id])
        action = json.dumps({'schema': 'action-items-v1', 'items': [
            {'title': 'Ship', 'details': 'Prepare release',
             'source_ids': [self.artifact_id]}]})
        self.assertEqual(json.loads(validate_preview(action, 'action-items',
            'action-items-v1', [self.artifact_id]))['items'][0]['title'], 'Ship')

    def test_unknown_dispatch_is_not_retried(self):
        self.error = TimeoutError('lost'); request = self.request()
        with self.assertRaises(UnknownRun):
            self.service.preview(request)
        with self.assertRaisesRegex(ValueError, 'cannot be retried'):
            self.service.preview(request)
        self.assertEqual(len(self.calls), 1)

    def publish_request(self, preview, **changes):
        value = dict(task_id=preview['task_id'], preview_sha256=preview['response_sha256'],
            project_id=self.project_id, expected_head=self.git.head(), artifact_id=str(uuid4()),
            title='Extracted facts', created_at='2026-09-19T10:00:00Z',
            operation_id=str(uuid4()))
        value.update(changes)
        return value

    def test_publish_creates_immutable_source_with_provenance_and_relation(self):
        preview = self.service.preview(self.request()); publish = self.publish_request(preview)
        result = self.service.publish(publish)
        self.assertEqual(result['state'], 'published')
        files = self.git.snapshot(result['receipt']['commit_id'])
        prefix = 'artifacts/' + publish['artifact_id'] + '/'
        metadata = json.loads(files[prefix + 'metadata.json'])
        content = json.loads(files[prefix + 'extraction.json'])
        self.assertEqual(metadata['kind'], 'source')
        self.assertEqual(metadata['provenance'], 'llm-generated')
        self.assertEqual(metadata['relations'], [{'target_id': self.artifact_id,
                                                  'type': 'derived-from'}])
        self.assertEqual(content['schema'], 'fpw-extraction-v1')
        self.assertEqual(content['provenance']['preview_sha256'], preview['response_sha256'])
        self.assertEqual(content['data']['schema'], 'facts-v1')
        self.assertEqual(self.service.publish(publish), result)

    def test_publish_rejects_stale_head_without_partial_artifact(self):
        preview = self.service.preview(self.request()); publish = self.publish_request(preview)
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=str(uuid4()), base_head=self.git.head(), title='Other', body='changed',
            new=True), str(uuid4()))
        with self.assertRaisesRegex(ValueError, 'changed before extraction publication'):
            self.service.publish(publish)
        self.assertNotIn('artifacts/' + publish['artifact_id'] + '/metadata.json',
                         self.git.snapshot(self.git.head()))

    def test_publish_resumes_after_workspace_commit(self):
        preview = self.service.preview(self.request()); publish = self.publish_request(preview)
        with self.assertRaisesRegex(RuntimeError, 'crash'):
            self.service.publish(publish, checkpoint=lambda stage:
                (_ for _ in ()).throw(RuntimeError('crash')) if stage == 'workspace-complete' else None)
        restarted = ExtractionService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factory=self.factory)
        result = restarted.publish(publish)
        self.assertEqual(result['state'], 'published')

    def test_publish_recovers_before_and_after_ref_without_duplicate_artifact(self):
        for crash_stage in ('before-ref', 'ref-updated'):
            with self.subTest(stage=crash_stage):
                preview = self.service.preview(self.request()); publish = self.publish_request(preview)
                seen = False
                def checkpoint(stage):
                    nonlocal seen
                    if stage == crash_stage and not seen:
                        seen = True
                        raise RuntimeError('publication crash')
                with self.assertRaisesRegex(RuntimeError, 'publication crash'):
                    self.service.publish(publish, checkpoint=checkpoint)
                result = self.service.publish(publish)
                self.assertEqual(result['state'], 'published')
                matches = [path for path in self.git.snapshot(self.git.head())
                           if path == 'artifacts/' + publish['artifact_id'] + '/metadata.json']
                self.assertEqual(len(matches), 1)

    def test_authenticated_desktop_api_exposes_preview_and_publish(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            server.extraction_service = self.service
            preview_request = self.request()
            response = driver.request(server, path='/v1/extraction/preview',
                                      body=json.dumps(preview_request).encode())
            self.assertIn(b'HTTP/1.0 200', response)
            preview = json.loads(response.split(b'\r\n\r\n', 1)[1])
            publish = self.publish_request(preview)
            response = driver.request(server, path='/v1/extraction/publish',
                                      body=json.dumps(publish).encode())
            self.assertIn(b'HTTP/1.0 200', response)


if __name__ == '__main__':
    unittest.main()
