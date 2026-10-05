# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import uuid4
import zlib

from spikes.media_backend import ComfyImageAdapter, MediaUnknownRun
from spikes.media_service import MediaService, PREVIEW_LIMIT
from spikes.metadata import validate_snapshot
from spikes.openai_backend import OpenAIBinding, OpenAIBindings, OpenAICredentials
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests import test_local_api


def chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data
            + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))


def png(width=1024, height=1024, payload=b'x'):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', payload) + chunk(b'IEND', b''))


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'; self.project_root = self.base / 'project'
        created = ProjectCreation(self.node).create('Media', str(self.project_root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.project_root)
        self.state = self.base / 'media-state'; self.state.mkdir(mode=0o700)
        self.calls = []

        def factory(runs):
            def transport(_binding, request):
                self.calls.append(request)
                return png(), {'prompt_id': 'provider-1',
                    'workflow_revision': 'workflow-v1',
                    'workflow_sha256': self.binding['workflow_sha256']
                        if hasattr(self, 'binding') else request['workflow_sha256'],
                    'image': {'filename': 'result.png', 'subfolder': '', 'type': 'output'}}
            return ComfyImageAdapter(runs, transport=transport)

        self.factory = factory
        self.service = MediaService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factories={'comfyui': factory})
        workflow = {
            '1': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'placeholder'}},
            '2': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 1, 'height': 1}},
            '3': {'class_type': 'KSampler', 'inputs': {'seed': 0}},
            '9': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0]}}}
        digest = hashlib.sha256(json.dumps(workflow, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        self.binding = {'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': 'comfy-v1', 'adapter': 'comfyui', 'boundary': 'same-node',
            'endpoint': 'http://127.0.0.1:8188', 'target_id': 'local-process',
            'workflow_revision': 'workflow-v1', 'workflow_sha256': digest,
            'workflow': workflow, 'parameters': {
                'prompt': {'node_id': '1', 'input': 'text'},
                'width': {'node_id': '2', 'input': 'width'},
                'height': {'node_id': '2', 'input': 'height'},
                'seed': {'node_id': '3', 'input': 'seed'}},
            'output_node_id': '9', 'timeout_seconds': 30}
        self.service.configure_comfy(self.binding)

    def request(self, **changes):
        value = {'schema': 'fpw-image-request-v1', 'approval_id': str(uuid4()),
            'run_id': str(uuid4()), 'manifest_id': str(uuid4()),
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'adapter': 'comfyui', 'prompt': 'A small red house',
            'size': '1024x1024', 'quality': 'auto', 'seed': 42,
            'privacy': 'local-only'}
        value.update(changes); return value

    def publication(self, result, **changes):
        value = {'approval_id': result['approval_id'],
            'result_sha256': result['result_sha256'], 'project_id': self.project_id,
            'expected_head': self.git.head(), 'artifact_id': str(uuid4()),
            'title': 'Generated house', 'created_at': '2026-10-05T12:00:00Z',
            'operation_id': str(uuid4()), 'privacy': result['privacy']}
        value.update(changes); return value

    def test_preview_confirmation_restart_and_publication_are_separate(self):
        request = self.request(); head = self.git.head()
        preview = self.service.preview(request)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.git.head(), head)
        self.assertNotIn('workflow', preview['target'])
        self.assertNotIn('credential', json.dumps(preview))

        restarted = MediaService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factories={'comfyui': self.factory})
        result = restarted.confirm({'approval_id': request['approval_id'],
            'project_id': self.project_id, 'preview_sha256': preview['preview_sha256'],
            'approved': True, 'privacy': 'local-only'})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result['image_base64'],
                         __import__('base64').b64encode(png()).decode())
        self.assertEqual(self.git.head(), head)
        self.assertEqual(restarted.confirm({'approval_id': request['approval_id'],
            'project_id': self.project_id, 'preview_sha256': preview['preview_sha256'],
            'approved': True, 'privacy': 'local-only'})['result_sha256'],
            result['result_sha256'])
        self.assertEqual(len(self.calls), 1)

        publication = self.publication(result)
        replacement = dict(self.binding, binding_id=str(uuid4()), revision='comfy-v2',
                           workflow_revision='workflow-v2')
        self.service.configure_comfy(replacement)
        published = restarted.publish(publication)
        published_head = self.git.head()
        self.assertEqual(restarted.publish(publication)['receipt']['commit_id'], published_head)
        self.assertEqual(published['receipt']['commit_id'], published_head)
        files = self.git.snapshot(published_head); metadata = validate_snapshot(files)[publication['artifact_id']]
        self.assertEqual((metadata['schema_version'], metadata['privacy'],
                          metadata['provenance'], metadata['file']),
                         (3, 'local-only', 'llm-generated', 'image.png'))
        self.assertEqual(metadata['generation']['run_id'], request['run_id'])
        self.assertEqual(metadata['generation']['binding_id'], self.binding['binding_id'])
        self.assertEqual(metadata['generation']['workflow']['revision'], 'workflow-v1')
        self.assertEqual(metadata['generation']['result_sha256'], hashlib.sha256(png()).hexdigest())
        self.assertNotIn('A small red house', json.dumps(metadata))
        self.assertEqual(files[f'artifacts/{publication["artifact_id"]}/image.png'], png())

    def test_confirmation_rejects_changed_privacy_head_and_preview(self):
        request = self.request(privacy='project'); preview = self.service.preview(request)
        base = {'approval_id': request['approval_id'], 'project_id': self.project_id,
            'preview_sha256': preview['preview_sha256'], 'approved': True,
            'privacy': 'project'}
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.service.confirm(dict(base, privacy='confidential'))
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.service.confirm(dict(base, preview_sha256='0' * 64))

    def test_confirmation_recovers_stored_result_without_redispatch(self):
        request = self.request(); preview = self.service.preview(request)
        confirmation = {'approval_id': request['approval_id'],
            'project_id': self.project_id, 'preview_sha256': preview['preview_sha256'],
            'approved': True, 'privacy': request['privacy']}
        crashed = False
        def checkpoint(stage):
            nonlocal crashed
            if stage == 'response-received' and not crashed:
                crashed = True
                raise RuntimeError('lost approval result')
        with self.assertRaisesRegex(RuntimeError, 'lost approval result'):
            self.service.confirm(confirmation, checkpoint=checkpoint)
        self.assertEqual(len(self.calls), 1)

        restarted = MediaService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factories={'comfyui': self.factory})
        result = restarted.confirm(confirmation)
        self.assertEqual(result['image_sha256'], hashlib.sha256(png()).hexdigest())
        self.assertEqual(len(self.calls), 1)

    def test_timeout_requires_a_consciously_new_approval_and_run(self):
        calls = []
        def factory(runs):
            def transport(_binding, _request):
                calls.append(1)
                if len(calls) == 1: raise TimeoutError('provider timeout')
                return png(), {'prompt_id': 'provider-2',
                    'workflow_revision': 'workflow-v1',
                    'workflow_sha256': self.binding['workflow_sha256'],
                    'image': {'filename': 'result.png', 'subfolder': '', 'type': 'output'}}
            return ComfyImageAdapter(runs, transport=transport)
        service = MediaService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factories={'comfyui': factory})
        first = self.request(); first_preview = service.preview(first)
        first_confirmation = {'approval_id': first['approval_id'],
            'project_id': self.project_id, 'preview_sha256': first_preview['preview_sha256'],
            'approved': True, 'privacy': first['privacy']}
        with self.assertRaises(MediaUnknownRun): service.confirm(first_confirmation)
        with self.assertRaisesRegex(ValueError, 'cannot be dispatched again'):
            service.confirm(first_confirmation)
        self.assertEqual(len(calls), 1)

        second = self.request(); second_preview = service.preview(second)
        result = service.confirm({'approval_id': second['approval_id'],
            'project_id': self.project_id, 'preview_sha256': second_preview['preview_sha256'],
            'approved': True, 'privacy': second['privacy']})
        self.assertEqual(result['run_id'], second['run_id'])
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(len(calls), 2)

    def test_large_valid_result_is_publishable_without_inline_preview(self):
        large = png(payload=b'x' * (PREVIEW_LIMIT + 1))
        def factory(runs):
            return ComfyImageAdapter(runs, transport=lambda _binding, _request:
                (large, {'prompt_id': 'provider-large',
                    'workflow_revision': 'workflow-v1',
                    'workflow_sha256': self.binding['workflow_sha256'],
                    'image': {'filename': 'large.png', 'subfolder': '', 'type': 'output'}}))
        service = MediaService(self.node, Projects(self.node), state_dir=self.state,
            adapter_factories={'comfyui': factory})
        request = self.request(); preview = service.preview(request)
        result = service.confirm({'approval_id': request['approval_id'],
            'project_id': self.project_id, 'preview_sha256': preview['preview_sha256'],
            'approved': True, 'privacy': request['privacy']})
        self.assertFalse(result['preview_available'])
        self.assertNotIn('image_base64', result)
        publication = self.publication(result)
        published = service.publish(publication)
        files = self.git.snapshot(published['receipt']['commit_id'])
        self.assertEqual(files[f'artifacts/{publication["artifact_id"]}/image.png'], large)

    def test_publication_recovers_without_duplicate_provider_or_artifact(self):
        for crash_stage in ('before-ref', 'ref-updated', 'workspace-complete'):
            with self.subTest(stage=crash_stage):
                request = self.request(); preview = self.service.preview(request)
                result = self.service.confirm({'approval_id': request['approval_id'],
                    'project_id': self.project_id, 'preview_sha256': preview['preview_sha256'],
                    'approved': True, 'privacy': request['privacy']})
                publication = self.publication(result)
                crashed = False
                def checkpoint(stage):
                    nonlocal crashed
                    if stage == crash_stage and not crashed:
                        crashed = True
                        raise RuntimeError('publication crash')
                with self.assertRaisesRegex(RuntimeError, 'publication crash'):
                    self.service.publish(publication, checkpoint=checkpoint)
                recovered = self.service.publish(publication)
                self.assertEqual(recovered['state'], 'published')
                entities = validate_snapshot(self.git.snapshot(self.git.head()))
                self.assertIn(publication['artifact_id'], entities)
                self.assertEqual(len(self.calls), 1 + list(
                    ('before-ref', 'ref-updated', 'workspace-complete')).index(crash_stage))

    def test_openai_image_binding_reuses_secret_without_exposing_it_and_rejects_local_only(self):
        credentials = OpenAICredentials(self.state)
        credential = credentials.put('credential:test', 'sk-' + 'x' * 40)
        shared = OpenAIBinding.parse({'schema_version': 1,
            'binding_id': str(uuid4()), 'revision': 'responses-v1',
            'adapter': 'openai-responses', 'boundary': 'external-provider',
            'endpoint': 'https://api.openai.com/v1/responses', 'model': 'gpt-5.6-luna',
            'target_id': 'api.openai.com', 'credential_ref': credential['reference'],
            'credential_revision': credential['revision'], 'max_output_tokens': 4096,
            'timeout_seconds': 30})
        OpenAIBindings(self.state).save(shared)
        configured = self.service.configure_openai({'model': 'gpt-image-1',
                                                    'timeout_seconds': 30})
        self.assertEqual(configured['binding']['model'], 'gpt-image-1')
        self.assertNotIn('credential', json.dumps(configured))
        status = self.service.status()
        self.assertNotIn('credential', json.dumps(status['bindings']['openai-images']))
        with self.assertRaisesRegex(ValueError, 'local-only'):
            self.service.preview(self.request(adapter='openai-images', quality='medium',
                                              seed=None, privacy='local-only'))

    def test_authenticated_desktop_api_exposes_preview_confirm_and_publish(self):
        driver = test_local_api.LocalAPITests(); request = self.request(privacy='project')
        with running_api('http', handler=DesktopHandler,
                         projects=Projects(self.node)) as server:
            server.media_service = self.service
            response = driver.request(server, path='/v1/media/preview',
                                      body=json.dumps(request).encode())
            preview = json.loads(response.split(b'\r\n\r\n', 1)[1])
            confirmation = {'approval_id': request['approval_id'],
                'project_id': self.project_id,
                'preview_sha256': preview['preview_sha256'],
                'approved': True, 'privacy': 'project'}
            response = driver.request(server, path='/v1/media/confirm',
                                      body=json.dumps(confirmation).encode())
            result = json.loads(response.split(b'\r\n\r\n', 1)[1])
            publication = self.publication(result, privacy='project')
            response = driver.request(server, path='/v1/media/publish',
                                      body=json.dumps(publication).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            driver.rejected(server, path='/v1/media/preview',
                            body=json.dumps(self.request()).encode(),
                            headers={'Authorization': None})


if __name__ == '__main__':
    unittest.main()
