# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

from spikes.backend_contract import BackendCapabilities
from spikes.media_backend import (ComfyImageAdapter, ComfyImageBinding,
                                  ImageGenerationRequest, MediaResponseError,
                                  MediaRuns, MediaUnknownRun, OpenAIImageAdapter,
                                  OpenAIImageBinding, validate_png)
from spikes.openai_backend import OpenAICredentials


def chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data
            + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))


def png(width=1024, height=1024):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', b'x') + chunk(b'IEND', b'')


class MediaBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name); os.chmod(self.root, 0o700)
        self.runs = MediaRuns(self.root)
        self.request = ImageGenerationRequest.parse({
            'run_id': str(uuid.uuid4()), 'manifest_sha256': 'a' * 64,
            'prompt': 'A small red house', 'size': '1024x1024',
            'quality': 'medium', 'seed': None})

    def comfy_request(self):
        value = dict(self.request.__dict__)
        value.update(quality='auto', seed=42)
        return ImageGenerationRequest.parse(value)

    def tearDown(self):
        self.temporary.cleanup()

    def openai_binding(self):
        return OpenAIImageBinding.parse({
            'schema_version': 1, 'binding_id': str(uuid.uuid4()),
            'revision': 'images-v1', 'adapter': 'openai-images',
            'boundary': 'external-provider',
            'endpoint': 'https://api.openai.com/v1/images/generations',
            'model': 'gpt-image-1', 'target_id': 'api.openai.com',
            'credential_ref': 'credential:test', 'credential_revision': 1,
            'timeout_seconds': 30})

    def comfy_binding(self, **changes):
        workflow = {
            '1': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'placeholder'}},
            '2': {'class_type': 'EmptyLatentImage',
                  'inputs': {'width': 1, 'height': 1}},
            '3': {'class_type': 'KSampler', 'inputs': {'seed': 0}},
            '9': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0]}}}
        digest = hashlib.sha256(json.dumps(workflow, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        value = {'schema_version': 1, 'binding_id': str(uuid.uuid4()),
                 'revision': 'comfy-v1', 'adapter': 'comfyui',
                 'boundary': 'same-node', 'endpoint': 'http://127.0.0.1:8188',
                 'target_id': 'local-process', 'workflow_revision': 'workflow-v1',
                 'workflow_sha256': digest, 'workflow': workflow,
                 'parameters': {
                     'prompt': {'node_id': '1', 'input': 'text'},
                     'width': {'node_id': '2', 'input': 'width'},
                     'height': {'node_id': '2', 'input': 'height'},
                     'seed': {'node_id': '3', 'input': 'seed'}},
                 'output_node_id': '9', 'timeout_seconds': 30}
        value.update(changes)
        return ComfyImageBinding.parse(value)

    def credentials(self):
        credentials = OpenAICredentials(self.root)
        credentials.put('credential:test', 'sk-' + 'x' * 40)
        return credentials

    def test_capabilities_include_image_without_changing_role_contract(self):
        BackendCapabilities(1, 'image-v1', frozenset({'generate-image'}),
                            frozenset({'image/png'})).validate()
        with self.assertRaises(ValueError):
            BackendCapabilities(1, 'bad', frozenset({'edit-image'}),
                                frozenset({'image/png'})).validate()

    def test_png_validation_checks_dimensions_crc_and_trailing_bytes(self):
        result = validate_png(png(), (1024, 1024))
        self.assertEqual(result['mime'], 'image/png')
        with self.assertRaisesRegex(MediaResponseError, 'dimensions'):
            validate_png(png(10, 10), (1024, 1024))
        corrupt = bytearray(png()); corrupt[-1] ^= 1
        with self.assertRaisesRegex(MediaResponseError, 'CRC'):
            validate_png(bytes(corrupt), (1024, 1024))
        with self.assertRaisesRegex(MediaResponseError, 'end'):
            validate_png(png() + b'x', (1024, 1024))

    def test_openai_success_is_durable_idempotent_and_secret_free(self):
        calls = []
        def transport(binding, request):
            calls.append(request)
            return png(), {'created': 1}
        adapter = OpenAIImageAdapter(self.runs, self.credentials(), transport)
        result = adapter.dispatch(self.request, self.openai_binding())
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['image'], png())
        self.assertEqual(calls[0], {'model': 'gpt-image-1', 'prompt': 'A small red house',
                                   'n': 1, 'size': '1024x1024', 'quality': 'medium',
                                   'output_format': 'png'})
        binding = self.openai_binding()
        # A different binding identity must not claim the existing run.
        with self.assertRaises(ValueError):
            adapter.dispatch(self.request, binding)
        stored = self.runs.get(self.request.run_id)
        self.assertNotIn('image', stored)
        self.assertNotIn('sk-', json.dumps(stored))

    def test_same_exact_openai_run_returns_stored_blob_without_retry(self):
        binding = self.openai_binding(); calls = []
        adapter = OpenAIImageAdapter(self.runs, self.credentials(),
                                     lambda _binding, _request: (calls.append(1) or png(), {}))
        adapter.dispatch(self.request, binding)
        second = adapter.dispatch(self.request, binding)
        self.assertEqual(second['image'], png()); self.assertEqual(len(calls), 1)

    def test_transport_uncertainty_is_durable_and_never_retried(self):
        binding = self.openai_binding(); calls = []
        def timeout(_binding, _request):
            calls.append(1); raise TimeoutError()
        adapter = OpenAIImageAdapter(self.runs, self.credentials(), timeout)
        with self.assertRaises(MediaUnknownRun): adapter.dispatch(self.request, binding)
        self.assertEqual(self.runs.get(self.request.run_id)['state'], 'unknown')
        with self.assertRaises(MediaUnknownRun): adapter.dispatch(self.request, binding)
        self.assertEqual(len(calls), 1)

    def test_malformed_provider_image_is_known_failure(self):
        binding = self.openai_binding()
        adapter = OpenAIImageAdapter(self.runs, self.credentials(),
                                     lambda _binding, _request: (b'not png', {}))
        with self.assertRaises(MediaResponseError): adapter.dispatch(self.request, binding)
        self.assertEqual(self.runs.get(self.request.run_id)['state'], 'failed')

    def test_comfy_only_substitutes_allowlisted_inputs_and_persists_identity(self):
        binding = self.comfy_binding(); original = json.dumps(binding.workflow, sort_keys=True)
        seen = []
        def transport(_binding, request):
            seen.append(request)
            return png(), {'prompt_id': 'provider-1'}
        request = self.comfy_request()
        result = ComfyImageAdapter(self.runs, transport).dispatch(request, binding)
        rendered = seen[0]['prompt']
        self.assertEqual(rendered['1']['inputs']['text'], request.prompt)
        self.assertEqual(rendered['2']['inputs']['width'], 1024)
        self.assertEqual(rendered['3']['inputs']['seed'], 42)
        self.assertEqual(json.dumps(binding.workflow, sort_keys=True), original)
        self.assertEqual(result['metadata']['provider']['prompt_id'], 'provider-1')
        self.assertEqual(result['execution']['adapter_id'], 'comfyui')

    def test_comfy_binding_rejects_unmapped_parameter_and_bad_boundary(self):
        with self.assertRaises(ValueError):
            self.comfy_binding(parameters={})
        with self.assertRaises(ValueError):
            self.comfy_binding(endpoint='http://192.168.1.2:8188')


if __name__ == '__main__':
    unittest.main()
