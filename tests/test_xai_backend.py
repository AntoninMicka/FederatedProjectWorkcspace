# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Wire format of the xAI Grok connector; no network, fixtures follow the xAI OpenAPI."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.direct_provider import (consume_stream, DirectAdapter, DirectCatalog,
    DirectCredentials, DirectResponseError, DirectRuns, DirectUnknownRun)
from spikes.metadata import ValidationError
from spikes.xai_backend import GrokBinding, SPEC


MODEL = 'grok-test-model'
MESSAGE = {'type': 'message', 'role': 'assistant', 'status': 'completed', 'id': 'msg_1',
           'content': [{'type': 'output_text', 'text': 'ab', 'annotations': [],
                        'logprobs': None}]}
REASONING = {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': 'opaque'}
USAGE = {'input_tokens': 32, 'output_tokens': 9, 'total_tokens': 151,
         'input_tokens_details': {'cached_tokens': 8},
         'output_tokens_details': {'reasoning_tokens': 110}}


def completed(**changes):
    return {'id': 'resp_1', 'object': 'response', 'status': 'completed', 'model': MODEL,
            'store': False, 'error': None, 'incomplete_details': None,
            'output': [REASONING, MESSAGE], 'usage': USAGE, **changes}


def sse(*events):
    lines = []
    for event in events:
        name = event.get('type', 'message')
        lines += [b'event: ' + name.encode() + b'\n',
                  b'data: ' + json.dumps(event).encode() + b'\n', b'\n']
    return lines + [b'data: [DONE]\n', b'\n']


def model(name, *, output=('text',), input_=('text',), aliases=()):
    return {'id': name, 'fingerprint': 'fp_1', 'created': 1, 'object': 'model',
            'owned_by': 'xai', 'version': '1.0', 'input_modalities': list(input_),
            'output_modalities': list(output), 'aliases': list(aliases)}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.secret = 'xai-test-' + 'k' * 32
        self.credentials = DirectCredentials(self.state, SPEC)
        self.reference = self.credentials.new_reference('primary')
        self.credentials.put(self.reference, self.secret)
        self.value = {'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'r1',
            'adapter': 'xai-responses', 'boundary': 'external-provider',
            'endpoint': SPEC.endpoint, 'model': MODEL, 'target_id': SPEC.host,
            'credential_ref': self.reference, 'credential_revision': 1,
            'offer_id': 'xai:offer', 'protocol': SPEC.protocol,
            'knowledge_revision': 'empty-v1',
            'capabilities': ['generate-text', 'json-output', 'streaming', 'text-output'],
            'max_output_tokens': 100, 'timeout_seconds': 30}
        self.binding = GrokBinding.parse(self.value)
        self.handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                                       self.binding.target(), b'hello')

    def adapter(self, transport=None, stream_transport=None):
        return DirectAdapter(DirectRuns(self.state, SPEC), self.credentials, transport,
                             stream_transport)


class RequestTests(Base):
    def test_body_is_unstored_and_sends_only_documented_fields(self):
        self.assertEqual(SPEC.build_body('p', self.binding, 'text', False), {
            'model': MODEL, 'input': 'p', 'store': False, 'max_output_tokens': 100,
            'stream': False})
        self.assertIs(SPEC.build_body('p', self.binding, 'text', True)['stream'], True)

    def test_json_uses_documented_format(self):
        self.assertEqual(SPEC.build_body('p', self.binding, 'json', False)['text'],
                         {'format': {'type': 'json_object'}})
        with self.assertRaises(ValidationError):
            SPEC.build_body('p', self.binding, 'xml', False)

    def test_paths_and_headers(self):
        self.assertEqual(SPEC.generate_path(MODEL, True), '/v1/responses')
        self.assertEqual(SPEC.auth_headers('k'), {'Authorization': 'Bearer k'})

    def test_binding_rejects_foreign_endpoint(self):
        for changes in ({'endpoint': 'https://proxy.example/v1/responses'},
                        {'endpoint': 'https://api.x.ai/v1/chat/completions'},
                        {'target_id': 'proxy.example'}, {'adapter': 'openai'},
                        {'protocol': 'openai-responses-v1'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                GrokBinding.parse(dict(self.value, **changes))


class ResponseTests(Base):
    def parse(self, value):
        return SPEC.parse_response(value, self.binding)

    def test_completed(self):
        self.assertEqual(self.parse(completed()), {
            'id': 'resp_1', 'model': MODEL, 'response': 'ab',
            'usage': {'input_tokens': 32, 'output_tokens': 9, 'total_tokens': 151}})

    def test_incomplete_and_failed_name_only_the_reason(self):
        secret_text = 'prompt echo with spaces'
        for value, message in (
                (completed(status='incomplete', incomplete_details={
                    'reason': 'max_output_tokens'}), 'incomplete: max_output_tokens'),
                (completed(status='incomplete'), 'incomplete: unspecified'),
                (completed(status='failed', error={'code': 'server_error',
                    'message': secret_text}), 'failed: server_error'),
                (completed(status='failed', error={'code': secret_text}),
                 'failed: unspecified'),
                (completed(status='in_progress'), 'did not complete')):
            with self.subTest(value=value['status']):
                with self.assertRaisesRegex(ValueError, message) as caught:
                    self.parse(value)
                self.assertNotIn(secret_text, str(caught.exception))

    def test_invalid_answers_are_rejected(self):
        for label, value in (
                ('wrong model', completed(model='grok-other')),
                ('alias', completed(model='latest')),
                ('no id', completed(id='')),
                ('stored', completed(store=True)),
                ('error', completed(error={'code': 'x'})),
                ('two messages', completed(output=[MESSAGE, MESSAGE])),
                ('no message', completed(output=[REASONING])),
                ('empty', completed(output=[])),
                ('client tool item', completed(output=[MESSAGE, {'type': 'function_call'}])),
                ('content', completed(output=[dict(MESSAGE, content=[
                    {'type': 'refusal', 'refusal': 'no'}])])),
                ('mixed', completed(output=[dict(MESSAGE, content=[
                    MESSAGE['content'][0], {'type': 'refusal'}])])),
                ('no content', completed(output=[dict(MESSAGE, content=[])])),
                ('message state', completed(output=[dict(MESSAGE, status='incomplete')])),
                ('not an object', [])):
            with self.subTest(label), self.assertRaises(ValueError):
                self.parse(value)

    def test_search_calls_report_bounded_sources_and_enable_adds_the_tool(self):
        text = dict(MESSAGE['content'][0], annotations=[
            {'type': 'url_citation', 'url': 'https://a.example/', 'title': 'A'},
            {'type': 'url_citation', 'url': 'file:///etc/passwd', 'title': 'Bad'}])
        result = self.parse(completed(output=[{'type': 'web_search_call'},
            dict(MESSAGE, content=[text])], citations=['https://b.example/', 'https://a.example/']))
        self.assertEqual({'requests': 1, 'sources': [
            {'url': 'https://a.example/', 'title': 'A'},
            {'url': 'https://b.example/', 'title': 'https://b.example/'}]}, result['web_search'])

    def test_invalid_usage_is_omitted(self):
        for usage in (None, 'x', {'input_tokens': 1}, dict(USAGE, input_tokens=-1),
                      dict(USAGE, output_tokens=True), dict(USAGE, total_tokens='9')):
            with self.subTest(usage=usage):
                self.assertNotIn('usage', self.parse(completed(usage=usage)))


class StreamTests(Base):
    def consume(self, *events):
        deltas = []
        value = consume_stream(SPEC, self.binding, sse(*events), deltas.append)
        return value, deltas

    def test_realistic_stream_succeeds(self):
        value, deltas = self.consume(
            {'type': 'response.created', 'sequence_number': 0, 'response': {}},
            {'type': 'response.output_item.added', 'sequence_number': 1},
            {'type': 'response.output_text.delta', 'sequence_number': 2, 'delta': 'a'},
            {'type': 'response.output_text.delta', 'sequence_number': 3, 'delta': 'b'},
            {'type': 'response.completed', 'sequence_number': 4, 'response': completed()})
        self.assertEqual(deltas, ['a', 'b'])
        self.assertEqual(SPEC.parse_response(value, self.binding)['response'], 'ab')

    def test_sequence_number_is_optional(self):
        _, deltas = self.consume(
            {'type': 'response.output_text.delta', 'delta': 'ab'},
            {'type': 'response.completed', 'response': completed()})
        self.assertEqual(deltas, ['ab'])

    def test_missing_completed_is_a_lost_response(self):
        with self.assertRaises(ConnectionError):
            self.consume({'type': 'response.output_text.delta', 'delta': 'a'})

    def test_reported_failures_do_not_succeed(self):
        for event, message in (
                ({'type': 'response.failed', 'response': completed(
                    status='failed', error={'code': 'server_error'})}, 'server_error'),
                ({'type': 'response.incomplete', 'response': completed(
                    status='incomplete', incomplete_details={
                        'reason': 'content_filter'})}, 'content_filter'),
                ({'type': 'response.failed'}, 'failure'),
                ({'type': 'error', 'code': 'rate_limit'}, 'rate_limit')):
            with self.subTest(event=event['type']), self.assertRaisesRegex(
                    DirectResponseError, message):
                self.consume({'type': 'response.output_text.delta', 'delta': 'a'}, event)

    def test_failure_after_completed_does_not_succeed(self):
        with self.assertRaises(DirectResponseError):
            self.consume({'type': 'response.completed', 'response': completed()},
                         {'type': 'error'})

    def test_invalid_streams_are_rejected(self):
        delta = {'type': 'response.output_text.delta', 'delta': 'ab'}
        done = {'type': 'response.completed', 'response': completed()}
        for label, events in (
                ('out of order', [dict(delta, sequence_number=5),
                                  dict(done, sequence_number=4)]),
                ('repeated', [dict(delta, sequence_number=5),
                              dict(done, sequence_number=5)]),
                ('not an int', [dict(delta, sequence_number='1'), done]),
                ('bad delta', [dict(delta, delta=1), done]),
                ('no type', [{'delta': 'ab'}, done]),
                ('after completion', [done, delta]),
                ('two completions', [delta, done, done]),
                ('bad completed', [delta, dict(done, response='x')]),
                ('wrong deltas', [dict(delta, delta='x'), done]),
                ('not completed', [delta, dict(done, response=completed(
                    status='incomplete'))]),
                ('wrong model', [delta, dict(done, response=completed(model='x'))])):
            with self.subTest(label), self.assertRaises(ValueError):
                self.consume(*events)


class CatalogTests(Base):
    def test_models_path_rejects_cursor(self):
        self.assertEqual(SPEC.models_path(None), '/v1/language-models')
        with self.assertRaises(ValidationError):
            SPEC.models_path('next')

    def test_only_concrete_text_models_are_offered(self):
        cursors = []
        def transport(spec, secret, cursor):
            self.assertEqual(secret, self.secret); cursors.append(cursor)
            return {'models': [
                model('grok-a', input_=('text', 'image'), aliases=('grok', 'grok-latest')),
                model('grok-b'),
                model('grok'), model('grok-latest'), model('latest'),
                model('grok-imagine-image', output=('image',)),
                model('grok-imagine-video', input_=('text', 'image'), output=('video',)),
                model('grok-text-embed', output=('embedding',)),
                model('grok-mixed', output=('text', 'image')),
                model('grok-image-only', input_=('image',))]}
        projected = DirectCatalog(self.state, SPEC, transport).refresh(self.secret)
        self.assertEqual(cursors, [None])
        self.assertEqual(sorted(item['provider_model_id'] for item in projected['offers']),
                         ['grok-a', 'grok-b'])
        offer = next(item for item in projected['offers']
                     if item['provider_model_id'] == 'grok-a')
        self.assertEqual(sorted(item['name'] for item in offer['capabilities']),
                         ['generate-text', 'json-output', 'streaming', 'text-output'])
        self.assertEqual(offer['protocol'], 'xai-responses-v1')

    def test_malformed_catalog_is_rejected(self):
        for value in ([], {}, {'data': []}, {'models': {}}, {'models': ['x']},
                      {'models': [{'id': 'a'}]},
                      {'models': [dict(model('a'), id=1)]},
                      {'models': [dict(model('a'), aliases=None)]},
                      {'models': [dict(model('a'), output_modalities='text')]},
                      {'models': [dict(model('a'), input_modalities=[1])]},
                      {'models': [model('bad id')]},
                      {'models': [model('a'), model('a')]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DirectCatalog(self.state, SPEC, lambda *_: value).refresh(self.secret)


class AdapterTests(Base):
    def test_dispatch_end_to_end_is_idempotent(self):
        calls = []
        def transport(binding, request, secret):
            calls.append(request); self.assertEqual(secret, self.secret)
            return completed()
        adapter = self.adapter(transport)
        first = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(first['response'], 'ab')
        self.assertEqual(adapter.dispatch(self.handoff, self.binding), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0]), {'model': MODEL, 'input': 'hello',
            'store': False, 'max_output_tokens': 100, 'stream': False})

    def test_stream_end_to_end(self):
        def stream(binding, request, secret, on_delta):
            self.assertIs(json.loads(request)['stream'], True)
            return consume_stream(SPEC, binding, sse(
                {'type': 'response.output_text.delta', 'delta': 'ab'},
                {'type': 'response.completed', 'response': completed()}), on_delta)
        deltas = []
        result = self.adapter(stream_transport=stream).dispatch_stream(
            self.handoff, self.binding, deltas.append)
        self.assertEqual((deltas, result['response']), (['ab'], 'ab'))

    def test_incomplete_fails_the_run_without_resending(self):
        value = completed(status='incomplete',
                          incomplete_details={'reason': 'max_output_tokens'})
        with self.assertRaisesRegex(DirectResponseError, 'max_output_tokens'):
            self.adapter(lambda *_: value).dispatch(self.handoff, self.binding)
        with self.assertRaises(DirectResponseError):
            self.adapter(lambda *_: self.fail('must not resend')).dispatch(
                self.handoff, self.binding)

    def test_stream_without_completion_is_unknown(self):
        def stream(binding, request, secret, on_delta):
            return consume_stream(SPEC, binding, sse(
                {'type': 'response.output_text.delta', 'delta': 'a'}), on_delta)
        with self.assertRaises(DirectUnknownRun):
            self.adapter(stream_transport=stream).dispatch_stream(
                self.handoff, self.binding, lambda _: None)

    def test_secret_reaches_only_the_authorization_header(self):
        class Response:
            status = 200
            def read(_self, _limit):
                return json.dumps(completed()).encode()
        class Connection:
            sent = []
            def request(_self, method, path, body=None, headers=None):
                Connection.sent.append((method, path, body, headers))
            def getresponse(_self):
                return Response()
            def close(_self):
                pass
        with mock.patch('spikes.direct_provider._connection', lambda *_: Connection()):
            self.adapter().dispatch(self.handoff, self.binding)
        (method, path, body, headers), = Connection.sent
        self.assertEqual((method, path), ('POST', '/v1/responses'))
        self.assertEqual(headers['Authorization'], 'Bearer ' + self.secret)
        self.assertNotIn(self.secret.encode(), body)
        self.assertNotIn(self.secret, path)
        self.assertEqual([key for key, item in headers.items() if self.secret in item],
                         ['Authorization'])
        self.assertNotIn(self.secret.encode(),
                         (self.state / 'xai-responses-runs.sqlite').read_bytes())


if __name__ == '__main__':
    unittest.main()
