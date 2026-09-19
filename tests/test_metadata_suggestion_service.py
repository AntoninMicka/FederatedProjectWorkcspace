# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata_suggestion_service import MetadataSuggestionService
from spikes.metadata_suggestions import validate_preview
from spikes.ollama_backend import OllamaAdapter, UnknownRun
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git


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
