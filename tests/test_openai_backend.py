# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.backend_contract import RunSelection
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
        self.assertEqual([item['provider_model_id'] for item in value['offers']],
                         ['gpt-5.6-luna', 'o3'])
        selected = value['offers'][0]
        self.assertEqual(selected['availability'], 'available')
        self.assertEqual({item['state'] for item in selected['capabilities']},
                         {'reported'})
        other = value['offers'][1]
        self.assertEqual({item['state'] for item in other['capabilities']},
                         {'reported'})
        self.assertEqual(catalog.load(self.binding), value)
        self.assertEqual(calls[0][0], self.binding.model)
        paths = list(self.state.glob('model-discovery-*.json'))
        self.assertEqual(len(paths), 1)
        self.assertNotIn(calls[0][1], paths[0].read_text())
        self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)

    def test_failed_model_refresh_preserves_previous_cache(self):
        catalog = OpenAIModelCatalog(self.state, self.credentials,
            lambda *_: {'object': 'list', 'data': [{'id': 'gpt-5.6-luna'}]})
        previous = catalog.refresh(self.binding)
        failing = OpenAIModelCatalog(self.state, self.credentials,
            lambda *_: {'object': 'list', 'data': [{'missing': 'id'}]})
        stale = failing.refresh(self.binding)
        self.assertEqual((stale['freshness'], stale['refresh_error']),
                         ('stale', 'invalid-response'))
        self.assertEqual([item['provider_model_id'] for item in stale['offers']],
                         [item['provider_model_id'] for item in previous['offers']])
        self.assertTrue(all(item['freshness'] == 'stale'
                            and item['refresh_error'] == 'invalid-response'
                            for item in stale['offers']))
        self.assertEqual(catalog.load(self.binding), previous)
        limited = OpenAIModelCatalog(self.state, self.credentials,
            lambda *_: (_ for _ in ()).throw(
                OpenAIResponseError('OpenAI model list was rejected with HTTP 429')))
        stale = limited.refresh(self.binding)
        self.assertEqual((stale['freshness'], stale['refresh_error']),
                         ('stale', 'rate-limited'))
        self.credentials.delete(self.binding.credential_ref)
        stale = catalog.refresh(self.binding)
        self.assertEqual((stale['freshness'], stale['refresh_error']),
                         ('stale', 'unavailable'))

    def test_legacy_model_cache_projects_stale_readonly_without_capabilities(self):
        legacy = {'schema_version': 1, 'binding_id': self.binding.binding_id,
                  'credential_revision': 1, 'fetched_at': '2026-10-01T00:00:00+00:00',
                  'models': ['gpt-5.6-luna']}
        path = self.state / 'openai-models.json'
        path.write_text(json.dumps(legacy)); path.chmod(0o600)
        catalog = OpenAIModelCatalog(self.state, self.credentials,
                                     lambda *_: self.fail('load must not refresh'))
        value = catalog.load(self.binding)
        self.assertEqual(value['freshness'], 'stale')
        self.assertEqual(value['offers'][0]['provider_model_id'], 'gpt-5.6-luna')
        self.assertTrue(all(item['state'] == 'unknown'
                            for item in value['offers'][0]['capabilities']))
        self.assertTrue(path.exists())
        self.assertEqual(list(self.state.glob('model-discovery-*.json')), [])

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

    def test_dispatch_persists_exact_run_selection(self):
        selection = RunSelection(1, 'selection-openai-one', 'openai-responses',
            self.binding.binding_id, self.binding.revision,
            'openai-responses:' + self.binding.model, self.binding.model,
            'openai-responses-v1', 'capabilities-openai-one',
            ('generate-text', 'json-output', 'streaming', 'text-output'),
            'knowledge-one', self.binding.credential_revision)
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                lambda *args: self.response())
        adapter.dispatch(self.handoff, self.binding, run_selection=selection)
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual(row['run_selection'], selection.serialize())
        self.assertEqual(row['selection_sha256'], selection.digest())

    def test_reasoning_items_and_split_output_text_are_accepted_without_exposure(self):
        response = self.response()
        response['output'] = [
            {'id': 'rs_test', 'type': 'reasoning', 'summary': []},
            {'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'první '},
                {'type': 'output_text', 'text': 'část'}]}]
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                lambda *args: response)
        result = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(result['response'], 'první část')
        self.assertNotIn('reasoning', json.dumps(result))

    def test_streaming_uses_distinct_request_and_durable_final_response(self):
        calls = []; deltas = []
        def stream(binding, request, secret, on_delta):
            calls.append((json.loads(request), secret))
            on_delta('odpo'); on_delta('ved')
            return self.response()
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
            stream_transport=stream)
        prepared = adapter.prepare(self.handoff, self.binding, stream=True)
        self.assertEqual(prepared['state'], 'prepared')
        result = adapter.dispatch_stream(self.handoff, self.binding, deltas.append)
        self.assertEqual((deltas, result['response']), (['odpo', 'ved'], 'odpoved'))
        self.assertTrue(calls[0][0]['stream'])
        self.assertNotIn(calls[0][1], json.dumps(calls[0][0]))
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'succeeded')
        self.assertEqual(adapter.dispatch_stream(
            self.handoff, self.binding, lambda _: self.fail('must not emit')), result)

    def test_sse_transport_validates_deltas_and_final_response(self):
        response = self.response('odpověď')
        events = [
            {'type': 'response.output_text.delta', 'sequence_number': 1, 'delta': 'odpo'},
            {'type': 'response.output_text.delta', 'sequence_number': 2, 'delta': 'věď'},
            {'type': 'response.completed', 'sequence_number': 3, 'response': response}]
        lines = iter([part for event in events for part in
            [b'data: ' + json.dumps(event, ensure_ascii=False).encode() + b'\n', b'\n']])
        class Response:
            status = 200
            def readline(self, _limit): return next(lines, b'')
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *_args, **_kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        deltas = []
        with patch('spikes.openai_backend.http.client.HTTPSConnection', Connection):
            result = OpenAIAdapter._http_stream_transport(
                self.binding, b'{}', 'sk-secret-value', deltas.append)
        self.assertEqual((deltas, result), (['odpo', 'věď'], response))

    def test_malformed_stream_fails_durably_without_partial_response(self):
        def malformed(_binding, _request, _secret, on_delta):
            on_delta('neúplná')
            raise ValueError('Invalid OpenAI SSE sequence')
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                stream_transport=malformed)
        adapter.prepare(self.handoff, self.binding, stream=True)
        with self.assertRaisesRegex(OpenAIResponseError, 'SSE sequence'):
            adapter.dispatch_stream(self.handoff, self.binding, lambda _delta: None)
        run = adapter.runs.get(self.handoff.run_id)
        self.assertEqual(run['state'], 'failed')
        self.assertIsNone(run['response'])

    def test_interrupted_stream_is_unknown_and_partial_text_is_not_a_response(self):
        deltas = []
        def interrupted(_binding, _request, _secret, on_delta):
            on_delta('částečný text')
            raise TimeoutError('stream interrupted')
        adapter = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                stream_transport=interrupted)
        with self.assertRaises(OpenAIUnknownRun):
            adapter.dispatch_stream(self.handoff, self.binding, deltas.append)
        run = adapter.runs.get(self.handoff.run_id)
        self.assertEqual(deltas, ['částečný text'])
        self.assertEqual(run['state'], 'unknown')
        self.assertIsNone(run['response'])

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

        replacement = DispatchHandoff(str(uuid4()), str(uuid4()), 'c' * 64,
                                      self.binding.target(), b'new explicit attempt')
        succeeded = OpenAIAdapter(OpenAIRuns(self.state), self.credentials,
                                  lambda *_args: self.response('nový výsledek'))
        self.assertEqual(succeeded.dispatch(replacement, self.binding)['response'],
                         'nový výsledek')
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'unknown')

    def test_tool_call_model_change_and_malformed_output_fail_durably(self):
        invalid = [
            dict(self.response(), model='other-model'),
            dict(self.response(), output=[{'type': 'function_call', 'name': 'send'}]),
            dict(self.response(), output=[
                {'type': 'reasoning', 'summary': []},
                {'type': 'function_call', 'name': 'send'},
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'answer'}]}]),
            dict(self.response(), output=[
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'one'}]},
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'two'}]}]),
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
