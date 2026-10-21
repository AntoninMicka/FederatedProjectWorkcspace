# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.metadata_suggestion_service import MetadataSuggestionService
from spikes.metadata_suggestions import validate_preview
from spikes.metadata import validate_snapshot
from spikes.ollama_backend import OllamaAdapter, OllamaRuns, UnknownRun
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from tests import test_local_api


class MetadataSuggestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name); self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root); self.artifact_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id, artifact_id=self.artifact_id,
            base_head=self.git.head(), title='Manual title', body='Launch planning notes.', new=True,
            metadata={'description': 'Manual description', 'tags': ['Planning']}), str(uuid4()))
        self.state = self.base / 'ai-state'; self.state.mkdir(mode=0o700)
        self.calls = []; self.response = None; self.error = None
        def factory(runs):
            def transport(binding, raw):
                self.calls.append(json.loads(raw))
                if self.error: raise self.error
                return {'model': binding.model, 'response': self.response or json.dumps({
                    'schema': 'metadata-suggestions-v1', 'description': 'Release planning.',
                    'tags': ['Planning', 'Release']})}
            return OllamaAdapter(runs, transport=transport)
        self.factory = factory
        self.service = MetadataSuggestionService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=factory)
        self.binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
            adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
            model='gemma3', target_id='local-process')
        self.service.configure(self.binding)

    def request(self, **changes):
        value = dict(schema='fpw-metadata-suggestion-request-v1', task_id=str(uuid4()),
            run_id=str(uuid4()), manifest_id=str(uuid4()), project_id=self.project_id,
            expected_head=self.git.head(), role_id='metadata-advisor',
            role_revision='metadata-advisor-v1', target=self.binding,
            selection={'kind': 'artifacts', 'artifact_ids': [self.artifact_id]}, focus=None,
            metadata_input_id=str(uuid4()))
        value.update(changes); return value

    def test_preview_manifests_metadata_returns_diff_and_does_not_write_git(self):
        head = self.git.head(); request = self.request(); result = self.service.preview(request)
        self.assertEqual(self.git.head(), head)
        self.assertEqual(result['original']['description'], 'Manual description')
        self.assertEqual(result['diff']['tags']['suggested_additions'], ['Release'])
        task = self.service.status()['tasks'][0]
        self.assertEqual(len(task['response']), len(result['response']))
        run = OllamaRuns(self.state).get(request['run_id'])
        self.assertEqual((run['role_id'], run['role_revision'], run['output_format']),
                         ('metadata-advisor', 'metadata-advisor-v1', 'json'))
        restarted = MetadataSuggestionService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=self.factory)
        self.assertEqual(restarted.preview(request), result)
        self.assertEqual(len(self.calls), 1)

    def test_output_validation_rejects_unknown_empty_duplicate_and_controls(self):
        invalid = [
            '{"schema":"metadata-suggestions-v1","description":null,"tags":[],"x":1}',
            '{"schema":"metadata-suggestions-v1","description":"","tags":[]}',
            '{"schema":"metadata-suggestions-v1","description":null,"tags":["A","a"]}',
            '{"schema":"metadata-suggestions-v1","description":null,"tags":["bad\\n"]}',
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_preview(value)

    def test_invalid_response_is_failed_and_unknown_is_not_retried(self):
        self.response = '```json\n{}\n```'; request = self.request()
        with self.assertRaises(ValueError): self.service.preview(request)
        self.assertEqual(self.service.status()['tasks'][0]['state'], 'failed')
        self.error = TimeoutError('lost'); request = self.request()
        with self.assertRaises(UnknownRun): self.service.preview(request)
        with self.assertRaisesRegex(ValueError, 'cannot be retried'):
            self.service.preview(request)

    def publication(self, preview, **changes):
        value = dict(task_id=preview['task_id'], preview_sha256=preview['response_sha256'],
            project_id=self.project_id, expected_head=self.git.head(),
            artifact_id=self.artifact_id, apply_description=True, tags=['Release'],
            operation_id=str(uuid4()))
        value.update(changes); return value

    def test_confirmed_publication_preserves_manual_metadata_and_is_idempotent(self):
        preview = self.service.preview(self.request()); request = self.publication(preview)
        result = self.service.publish(request)
        self.assertEqual(result['state'], 'published')
        files = self.git.snapshot(result['receipt']['commit_id'])
        entities = validate_snapshot(files)
        metadata = entities[self.artifact_id]
        self.assertEqual(metadata['description'], 'Release planning.')
        self.assertEqual(metadata['tags'], ['Planning', 'Release'])
        self.assertEqual(metadata['title'], 'Manual title')
        self.assertEqual(metadata['privacy'], 'project')
        self.assertEqual(metadata['provenance'], 'user')
        self.assertEqual(self.service.publish(request), result)

    def test_partial_selection_stale_head_and_unconfirmed_values_fail_closed(self):
        preview = self.service.preview(self.request())
        result = self.service.publish(self.publication(preview,
            apply_description=False, tags=['Release']))
        entities = validate_snapshot(self.git.snapshot(result['receipt']['commit_id']))
        self.assertEqual(entities[self.artifact_id]['description'], 'Manual description')
        with self.assertRaises(ValueError):
            self.service.publish(self.publication(preview, expected_head=self.git.head(),
                tags=['Invented']))

    def test_publish_recovers_before_after_ref_and_workspace_completion(self):
        for crash_stage in ('before-ref', 'ref-updated', 'workspace-complete'):
            with self.subTest(stage=crash_stage):
                # Each subtest needs a fresh proposal over the latest HEAD.
                self.response = json.dumps({'schema': 'metadata-suggestions-v1',
                    'description': 'Description ' + crash_stage,
                    'tags': ['Tag-' + crash_stage]})
                preview = self.service.preview(self.request())
                request = self.publication(preview, tags=['Tag-' + crash_stage])
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

    def test_authenticated_desktop_api_exposes_preview_and_publish(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            server.metadata_suggestion_service = self.service
            response = driver.request(server, path='/v1/metadata-suggestions/preview',
                                      body=json.dumps(self.request()).encode())
            self.assertIn(b'HTTP/1.0 200', response)
            preview = json.loads(response.split(b'\r\n\r\n', 1)[1])
            response = driver.request(server, path='/v1/metadata-suggestions/publish',
                                      body=json.dumps(self.publication(preview)).encode())
            self.assertIn(b'HTTP/1.0 200', response)
