# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.metadata import ValidationError
from spikes.openai_backend import (OPENAI_ENDPOINT, OpenAIAdapter, OpenAIBinding,
                                   OpenAIBindings, OpenAICredentials,
                                   OpenAIModelCatalog,
                                   OpenAIResponseError, OpenAIRuns,
                                   OpenAIUnknownRun)


class OpenAIBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.value = dict(schema_version=1, binding_id=str(uuid4()),
                          revision='revision-1', adapter='openai-responses',
                          boundary='external-provider', endpoint=OPENAI_ENDPOINT,
                          model='gpt-5.6-luna', target_id='api.openai.com',
                          credential_ref='credential:openai-primary',
                          credential_revision=1,
                          max_output_tokens=2048, timeout_seconds=30)
        self.binding = OpenAIBinding.parse(self.value)
        self.credentials = OpenAICredentials(self.state)
        self.credentials.put(self.binding.credential_ref, 'sk-test-' + 'x' * 32)
        self.handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                                       self.binding.target(), b'presny text')

    def response(self, text='odpoved'):
        return {'id': 'resp_test', 'status': 'completed',
                'model': self.binding.model,
                'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': text}]}],
                'usage': {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5}}

    def test_binding_is_fixed_external_target_and_persists_without_secret(self):
        store = OpenAIBindings(self.state); store.save(self.binding)
        self.assertEqual(OpenAIBindings(self.state).load(), self.binding)
        self.assertNotIn('sk-test', store.path.read_text())
        for changes in ({'endpoint': 'https://proxy.example/v1/responses'},
                        {'boundary': 'same-node'}, {'model': 'gpt/invalid'},
                        {'secret': 'sk-leak'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                OpenAIBinding.parse(dict(self.value, **changes))

    def test_current_official_model_ids_are_accepted_without_invented_dates(self):
        for model in ('gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol', 'gpt-6-astra'):
            with self.subTest(model=model):
                self.assertEqual(OpenAIBinding.parse(dict(self.value, model=model)).model,
                                 model)

    def test_credential_status_is_write_only_and_revision_changes(self):
        status = self.credentials.status(self.binding.credential_ref)
        self.assertEqual(status, {'reference': self.binding.credential_ref,
                                  'available': True, 'revision': 1})
        self.assertNotIn('secret', json.dumps(status))
        updated = self.credentials.put(self.binding.credential_ref,
                                       'sk-test-' + 'y' * 32)
        self.assertEqual(updated['revision'], 2)
        self.credentials.delete(self.binding.credential_ref)
        self.assertFalse(self.credentials.status(self.binding.credential_ref)['available'])
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            self.credentials.resolve(self.binding.credential_ref)

    def test_model_catalog_is_filtered_bounded_cached_and_never_exposes_secret(self):
        calls = []
        def transport(binding, secret):
            calls.append((binding.model, secret))
            return {'object': 'list', 'data': [
                {'id': 'text-embedding-3-large'}, {'id': 'gpt-5.6-luna'},
                {'id': 'o3'}, {'id': 'dall-e-3'}, {'id': 'gpt-image-1'},
                {'id': 'gpt-4o-realtime-preview'}, {'id': 'gpt-5.6-luna'}]}
        catalog = OpenAIModelCatalog(self.state, self.credentials, transport)
        value = catalog.refresh(self.binding)
        self.assertEqual(value['models'], ['gpt-5.6-luna', 'o3'])
        self.assertEqual(catalog.load(self.binding), value)
        self.assertEqual(calls[0][0], self.binding.model)
        self.assertNotIn(calls[0][1], catalog.path.read_text())
        self.assertEqual(catalog.path.stat().st_mode & 0o777, 0o600)

    def test_failed_model_refresh_preserves_previous_cache(self):
        catalog = OpenAIModelCatalog(self.state, self.credentials,
            lambda *_: {'object': 'list', 'data': [{'id': 'gpt-5.6-luna'}]})
        previous = catalog.refresh(self.binding)
        failing = OpenAIModelCatalog(self.state, self.credentials,
            lambda *_: {'object': 'list', 'data': [{'missing': 'id'}]})
        with self.assertRaisesRegex(ValidationError, 'model entry'):
            failing.refresh(self.binding)
        self.assertEqual(catalog.load(self.binding), previous)

    def test_success_is_durable_and_request_is_explicit(self):
        calls = []
        def transport(binding, request, secret):
            calls.append((json.loads(request), secret)); return self.response()
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials, transport)
        first = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.dispatch(self.handoff, self.binding), first)
        self.assertEqual(len(calls), 1)
        request, secret = calls[0]
        self.assertEqual(request['model'], self.binding.model)
        self.assertEqual(request['input'], 'presny text')
        self.assertEqual((request['store'], request['stream'], request['truncation']),
                         (False, False, 'disabled'))
        self.assertNotIn(secret, json.dumps(request))
        self.assertEqual(first['usage']['total_tokens'], 5)
        self.assertEqual(OpenAIRuns(self.state).get(self.handoff.run_id)['state'],
                         'succeeded')
        self.credentials.delete(self.binding.credential_ref)
        restarted = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                  lambda *args: self.fail('must not resend'))
        self.assertEqual(restarted.dispatch(self.handoff, self.binding), first)

    def test_changed_credential_invalidates_prepared_run(self):
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                lambda *args: self.fail('must not dispatch'))
        adapter.prepare(self.handoff, self.binding)
        self.credentials.put(self.binding.credential_ref, 'sk-test-' + 'z' * 32)
        with self.assertRaisesRegex(ValidationError, 'revision differs'):
            adapter.dispatch(self.handoff, self.binding)

    def test_lost_response_is_unknown_and_never_retried(self):
        calls = []
        def lost(*args):
            calls.append(1); raise TimeoutError('lost')
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials, lost)
        with self.assertRaises(OpenAIUnknownRun):
            adapter.dispatch(self.handoff, self.binding)
        with self.assertRaisesRegex(OpenAIUnknownRun, 'automatic retry'):
            adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(len(calls), 1)

    def test_tool_call_model_change_and_malformed_output_fail_durably(self):
        invalid = [
            dict(self.response(), model='other-model'),
            dict(self.response(), output=[{'type': 'function_call', 'name': 'send'}]),
            dict(self.response(), output=[]),
        ]
        for index, response in enumerate(invalid):
            with self.subTest(index=index):
                handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'b' * 64,
                                           self.binding.target(), b'text')
                adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                        lambda *args, response=response: response)
                with self.assertRaises((ValidationError, OpenAIResponseError)):
                    adapter.dispatch(handoff, self.binding)
                self.assertEqual(adapter.runs.get(handoff.run_id)['state'], 'failed')

    def test_http_transport_rejects_redirect_without_exposing_secret(self):
        events = []
        class Response:
            status = 302
        class Connection:
            def __init__(self, *args, **kwargs): events.append(kwargs['timeout'])
            def request(self, method, path, body=None, headers=None):
                events.append((method, path, headers['Authorization']))
            def getresponse(self): return Response()
            def close(self): events.append('closed')
        with patch('spikes.openai_backend.http.client.HTTPSConnection', Connection):
            with self.assertRaisesRegex(OpenAIResponseError, 'redirect'):
                OpenAIAdapter._http_transport(self.binding, b'{}', 'sk-secret-value')
        self.assertEqual(events[0], 30)
        self.assertEqual(events[-1], 'closed')


if __name__ == '__main__':
    unittest.main()
