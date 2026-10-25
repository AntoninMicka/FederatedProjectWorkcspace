# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.atlascloud_backend import (ATLASCLOUD_ENDPOINT, ATLASCLOUD_PROTOCOL,
    AtlasCloudAdapter, AtlasCloudBinding, AtlasCloudBindings, AtlasCloudCatalog,
    AtlasCloudCredentials, AtlasCloudResponseError, AtlasCloudRuns,
    AtlasCloudUnknownRun)
from spikes.context_builder import DispatchHandoff
from spikes.metadata import ValidationError


NOW = '2026-10-25T18:00:00+00:00'


class AtlasCloudBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.model = 'deepseek-ai/deepseek-v3.2'
        self.offer_id = 'atlascloud:' + hashlib.sha256(
            (self.model + '\0' + ATLASCLOUD_PROTOCOL).encode()).hexdigest()[:32]
        self.catalog = AtlasCloudCatalog(self.state, lambda _secret: {
            'code': '200', 'data': [{'model': self.model, 'type': 'Text',
                'display_console': True, 'supported_protocols': [
                    'openai.chat.completions'],
                'supported_features': ['json_mode'],
                'output_modalities': ['text']}]})
        self.catalog.refresh('apikey-' + 'd' * 32)
        self.value = {'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': 'atlas-binding-v1', 'adapter': 'atlascloud-text',
            'boundary': 'external-provider', 'endpoint': ATLASCLOUD_ENDPOINT,
            'model': self.model, 'target_id': 'api.atlascloud.ai',
            'credential_ref': 'credential:atlascloud-primary',
            'credential_revision': 1, 'offer_id': self.offer_id,
            'protocol': ATLASCLOUD_PROTOCOL, 'knowledge_revision': 'empty-v1',
            'capabilities': ['generate-text', 'json-output', 'streaming', 'text-output'],
            'max_output_tokens': 2048, 'timeout_seconds': 30}
        self.binding = AtlasCloudBinding.parse(self.value)
        self.credentials = AtlasCloudCredentials(self.state)
        self.credentials.put(self.binding.credential_ref, 'apikey-' + 'x' * 32)
        self.handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
            self.binding.target(), 'přesný text'.encode())

    def response(self, text='odpověď'):
        return {'id': 'chatcmpl_atlas', 'model': self.model,
                'choices': [{'index': 0, 'message': {
                    'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 4, 'completion_tokens': 6,
                          'total_tokens': 10}}

    def test_binding_is_fixed_reviewed_and_persists_without_secret(self):
        self.catalog.validate_binding_offer(self.value)
        store = AtlasCloudBindings(self.state); store.save(self.binding)
        self.assertEqual(store.load(), self.binding)
        self.assertNotIn('apikey-', store.path.read_text())
        for changes in ({'endpoint': 'https://proxy.example/v1/chat/completions'},
                        {'protocol': 'openai-responses-v1'},
                        {'target_id': 'other.example'}, {'boundary': 'same-node'},
                        {'capabilities': ['generate-text', 'text-output', 'tools']}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                AtlasCloudBinding.parse(dict(self.value, **changes))

    def test_catalog_requires_exact_discovered_offer_and_capabilities(self):
        catalog = self.catalog
        projection = catalog.load()
        self.assertEqual(projection['discovery'], 'live')
        self.assertEqual([item['offer_id'] for item in projection['offers']],
                         [self.offer_id])
        catalog.validate_binding_offer(self.value)
        for changes in ({'offer_id': 'atlascloud:missing'},
                        {'model': 'different/model'},
                        {'knowledge_revision': 'stale-review'},
                        {'capabilities': self.value['capabilities'] + ['tools']}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                catalog.validate_binding_offer(dict(self.value, **changes))

    def test_discovery_maps_provider_protocol_profiles_and_filters_non_text(self):
        payload = {'code': 200, 'data': [
            {'model': 'dual/model', 'type': 'Text', 'display_console': True,
             'supported_protocols': ['openai.chat.completions', 'openai.responses'],
             'supported_features': [], 'output_modalities': ['text']},
            {'model': 'hidden/model', 'type': 'Text', 'display_console': False,
             'supported_protocols': ['openai.chat.completions'],
             'supported_features': [], 'output_modalities': ['text']},
            {'model': 'media/model', 'type': 'Image',
             'supported_protocols': None, 'output_modalities': ['image']} ]}
        isolated_state = Path(self.temp.name) / 'discovery-state'
        isolated_state.mkdir(mode=0o700)
        catalog = AtlasCloudCatalog(isolated_state, lambda _secret: payload)
        result = catalog.refresh('apikey-' + 'e' * 32)
        self.assertEqual([(item['provider_model_id'], item['protocol'])
                          for item in result['offers']], [
            ('dual/model', 'openai-chat-completions-v1'),
            ('dual/model', 'openai-responses-v1')])
        self.assertTrue(all(item['freshness'] == 'fresh' for item in result['offers']))

    def test_credentials_are_write_only_revisioned_and_deletable(self):
        status = self.credentials.status(self.binding.credential_ref)
        self.assertEqual(status['revision'], 1)
        self.assertNotIn('secret', status)
        updated = self.credentials.put(self.binding.credential_ref,
                                       'apikey-' + 'y' * 32)
        self.assertEqual(updated['revision'], 2)
        self.credentials.delete(self.binding.credential_ref)
        self.assertFalse(self.credentials.status(self.binding.credential_ref)['available'])
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            self.credentials.resolve(self.binding.credential_ref)

    def test_success_is_durable_exact_and_does_not_resend(self):
        calls = []
        def transport(binding, request, secret):
            calls.append((json.loads(request), secret)); return self.response()
        adapter = AtlasCloudAdapter(AtlasCloudRuns(self.state), self.credentials, transport)
        result = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.dispatch(self.handoff, self.binding), result)
        self.assertEqual(len(calls), 1)
        request, secret = calls[0]
        self.assertEqual((request['model'], request['messages']),
                         (self.model, [{'role': 'user', 'content': 'přesný text'}]))
        self.assertFalse(request['stream'])
        self.assertNotIn(secret, json.dumps(request))
        self.assertEqual(result['usage']['total_tokens'], 10)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['adapter_id'],
                         'atlascloud-text')

    def test_json_and_stream_require_reviewed_capabilities(self):
        limited = AtlasCloudBinding.parse(dict(self.value,
            capabilities=['generate-text', 'text-output']))
        limited_handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'b' * 64,
                                          limited.target(), b'text')
        with self.assertRaisesRegex(ValidationError, 'JSON'):
            AtlasCloudAdapter._request(limited_handoff, limited, output_format='json')
        with self.assertRaisesRegex(ValidationError, 'streaming'):
            AtlasCloudAdapter._request(limited_handoff, limited, stream=True)
        request, _, execution = AtlasCloudAdapter._request(
            self.handoff, self.binding, output_format='json', stream=True)
        self.assertEqual(json.loads(request)['response_format']['type'], 'json_object')
        self.assertEqual(execution.output_format, 'json')

    def test_responses_profile_uses_responses_contract(self):
        value = dict(self.value, endpoint='https://api.atlascloud.ai/v1/responses',
                     protocol='openai-responses-v1')
        binding = AtlasCloudBinding.parse(value)
        handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'e' * 64,
                                  binding.target(), b'responses text')
        request, _, _ = AtlasCloudAdapter._request(
            handoff, binding, output_format='json', stream=True)
        body = json.loads(request)
        self.assertEqual((body['input'], body['max_output_tokens']),
                         ('responses text', 2048))
        self.assertEqual(body['text']['format']['type'], 'json_object')
        response = {'id': 'resp_atlas', 'status': 'completed', 'model': self.model,
            'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'responses answer'}]}]}
        self.assertEqual(AtlasCloudAdapter._response(response, binding)['response'],
                         'responses answer')

    def test_streaming_is_durable_and_interruption_is_unknown_without_retry(self):
        deltas = []; calls = []
        def stream(_binding, _request, _secret, on_delta):
            calls.append(1); on_delta('odpo'); on_delta('věď'); return self.response()
        adapter = AtlasCloudAdapter(AtlasCloudRuns(self.state), self.credentials,
                                    stream_transport=stream)
        result = adapter.dispatch_stream(self.handoff, self.binding, deltas.append)
        self.assertEqual((deltas, result['response'], len(calls)),
                         (['odpo', 'věď'], 'odpověď', 1))
        self.assertEqual(adapter.dispatch_stream(
            self.handoff, self.binding, lambda _: self.fail('must not emit')), result)

        interrupted_handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'c' * 64,
                                               self.binding.target(), b'other')
        interrupted_calls = []
        def interrupted(*_args):
            interrupted_calls.append(1); raise TimeoutError('lost')
        broken = AtlasCloudAdapter(AtlasCloudRuns(self.state), self.credentials,
                                   stream_transport=interrupted)
        with self.assertRaises(AtlasCloudUnknownRun):
            broken.dispatch_stream(interrupted_handoff, self.binding, lambda _: None)
        with self.assertRaisesRegex(AtlasCloudUnknownRun, 'automatic retry'):
            broken.dispatch_stream(interrupted_handoff, self.binding, lambda _: None)
        self.assertEqual(interrupted_calls, [1])

    def test_invalid_response_and_changed_credential_fail_closed(self):
        invalid = dict(self.response(), model='other/model')
        adapter = AtlasCloudAdapter(AtlasCloudRuns(self.state), self.credentials,
                                    lambda *_: invalid)
        with self.assertRaises(AtlasCloudResponseError):
            adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'failed')

        other = DispatchHandoff(str(uuid4()), str(uuid4()), 'd' * 64,
                                self.binding.target(), b'other')
        adapter.prepare(other, self.binding)
        self.credentials.put(self.binding.credential_ref, 'apikey-' + 'z' * 32)
        with self.assertRaisesRegex(ValidationError, 'revision differs'):
            adapter.dispatch(other, self.binding)

    def test_sse_ignores_keepalive_and_rejects_redirect(self):
        event = {'id': 'chatcmpl_atlas', 'model': self.model,
                 'choices': [{'index': 0, 'delta': {'content': 'odpověď'},
                              'finish_reason': None}],
                 'usage': {'prompt_tokens': 4, 'completion_tokens': 6,
                           'total_tokens': 10}}
        final = {'id': 'chatcmpl_atlas', 'model': self.model,
                 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
        lines = iter([b': keep-alive\n', b'\n',
            b'data: ' + json.dumps(event, ensure_ascii=False).encode() + b'\n', b'\n',
            b'data: ' + json.dumps(final).encode() + b'\n', b'\n',
            b'data: [DONE]\n', b'\n'])
        class Response:
            status = 200
            def readline(self, _limit): return next(lines, b'')
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *_args, **_kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        deltas = []
        with patch('spikes.atlascloud_backend.http.client.HTTPSConnection', Connection):
            result = AtlasCloudAdapter._http_stream_transport(
                self.binding, b'{}', 'apikey-secret-value', deltas.append)
        self.assertEqual(deltas, ['odpověď'])
        self.assertEqual(AtlasCloudAdapter._response(result, self.binding)['response'],
                         'odpověď')

        class Redirect(Response): status = 302
        class RedirectConnection(Connection):
            def getresponse(self): return Redirect()
        with patch('spikes.atlascloud_backend.http.client.HTTPSConnection',
                   RedirectConnection):
            with self.assertRaisesRegex(AtlasCloudResponseError, 'redirect'):
                AtlasCloudAdapter._http_transport(
                    self.binding, b'{}', 'apikey-secret-value')


if __name__ == '__main__':
    unittest.main()
