# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Gemini wire format against documented shapes; nothing here reaches a live API."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.direct_provider import (consume_stream, DirectAdapter, DirectCatalog,
    DirectCredentials, DirectResponseError, DirectRuns, DirectUnknownRun)
from spikes.gemini_backend import GeminiBinding, SPEC
from spikes.metadata import ValidationError


MODEL = 'gemini-3.8-flash'


def value(model=MODEL, **changes):
    return {'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'r1',
        'adapter': 'gemini-generate', 'boundary': 'external-provider',
        'endpoint': SPEC.endpoint, 'model': model, 'target_id': SPEC.host,
        'credential_ref': 'credential:gemini-generate-primary', 'credential_revision': 1,
        'offer_id': 'google:offer', 'protocol': SPEC.protocol,
        'knowledge_revision': 'empty-v1',
        'capabilities': ['generate-text', 'json-output', 'streaming', 'text-output'],
        'max_output_tokens': 123, 'timeout_seconds': 30, **changes}


def reply(*parts, finish='STOP', **top):
    candidate = {'content': {'role': 'model', 'parts': list(parts)}, 'index': 0}
    if finish is not None:
        candidate['finishReason'] = finish
    return {'candidates': [candidate], 'modelVersion': MODEL, 'responseId': 'resp-1', **top}


def sse(*events):
    lines = []
    for event in events:
        lines += [b'data: ' + json.dumps(event).encode() + b'\r\n', b'\r\n']
    return lines


USAGE = {'promptTokenCount': 4, 'candidatesTokenCount': 5, 'thoughtsTokenCount': 2,
         'totalTokenCount': 11}


class WireFormatTests(unittest.TestCase):
    def setUp(self):
        self.binding = GeminiBinding.parse(value())

    def parse(self, response, binding=None):
        return SPEC.parse_response(response, binding or self.binding)

    def test_paths_and_auth_keep_the_key_out_of_the_url(self):
        secret = 'AIza' + 'k' * 32
        self.assertEqual(SPEC.auth_headers(secret), {'x-goog-api-key': secret})
        self.assertEqual(SPEC.generate_path(MODEL, False),
                         '/v1beta/models/gemini-3.8-flash:generateContent')
        self.assertEqual(SPEC.generate_path(MODEL, True),
                         '/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse')
        self.assertEqual(SPEC.generate_path('a/b c', False),
                         '/v1beta/models/a%2Fb%20c:generateContent')
        for path in (SPEC.generate_path(MODEL, True), SPEC.models_path('next')):
            self.assertNotIn('key=', path); self.assertNotIn(secret, path)

    def test_body_shape_and_json_mode(self):
        self.assertEqual(SPEC.build_body('hi', self.binding, 'text', False), {
            'contents': [{'role': 'user', 'parts': [{'text': 'hi'}]}],
            'generationConfig': {'maxOutputTokens': 123}})
        self.assertEqual(SPEC.build_body('hi', self.binding, 'json', True)['generationConfig'],
                         {'maxOutputTokens': 123, 'responseMimeType': 'application/json'})

    def test_success_returns_exact_framework_keys(self):
        self.assertEqual(self.parse(reply({'text': 'a'}, {'text': 'b'},
                                          usageMetadata=USAGE)),
            {'id': 'resp-1', 'model': MODEL, 'response': 'ab',
             'usage': {'input_tokens': 4, 'output_tokens': 7, 'total_tokens': 11}})

    def test_bad_finish_reasons_are_named(self):
        for reason in ('MAX_TOKENS', 'SAFETY', 'RECITATION', 'NEW_REASON'):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.parse(reply({'text': 'partial'}, finish=reason))
        with self.assertRaisesRegex(ValueError, 'UNKNOWN'):
            self.parse(reply({'text': 'partial'}, finish=None))
        with self.assertRaisesRegex(ValueError, 'UNKNOWN') as caught:
            self.parse(reply({'text': 'x'}, finish='echoed prompt text'))
        self.assertNotIn('echoed', str(caught.exception))
        # A filtered candidate has no content; the reason must still be the error.
        with self.assertRaisesRegex(ValueError, 'SAFETY'):
            self.parse({'candidates': [{'finishReason': 'SAFETY'}]})

    def test_prompt_block_is_named(self):
        with self.assertRaisesRegex(ValueError, 'PROHIBITED_CONTENT'):
            self.parse({'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'}})
        with self.assertRaises(ValueError):
            self.parse({'promptFeedback': 'blocked', 'candidates': []})

    def test_thought_parts_are_skipped(self):
        response = reply({'text': 'secret', 'thought': True}, {'text': 'answer'})
        self.assertEqual(self.parse(response)['response'], 'answer')
        with self.assertRaisesRegex(ValueError, 'no text'):
            self.parse(reply({'text': 'only', 'thought': True}))
        with self.assertRaises(ValueError):
            self.parse(reply({'text': 'x', 'thought': 'yes'}))

    def test_non_text_part_and_empty_results_are_rejected(self):
        for parts in (({'text': 'a'}, {'functionCall': {'name': 'f'}}),
                      ({'inlineData': {'mimeType': 'image/png', 'data': 'AA'}},),
                      ({'text': ''},), ()):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                self.parse(reply(*parts))

    def test_candidate_count_must_be_one(self):
        one = reply({'text': 'a'})['candidates'][0]
        for candidates in ([], [one, one], None, ['x']):
            with self.subTest(candidates=candidates), self.assertRaisesRegex(
                    ValueError, 'exactly one'):
                self.parse({'candidates': candidates})

    def test_usage_without_thoughts_and_invalid_usage_is_omitted(self):
        plain = {'promptTokenCount': 1, 'candidatesTokenCount': 2, 'totalTokenCount': 3}
        self.assertEqual(self.parse(reply({'text': 'a'}, usageMetadata=plain))['usage'],
                         {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3})
        for usage in ('x', {}, dict(plain, promptTokenCount=-1),
                      dict(plain, totalTokenCount=True), dict(plain, totalTokenCount=2),
                      dict(plain, candidatesTokenCount='2'),
                      dict(plain, thoughtsTokenCount=1)):
            with self.subTest(usage=usage):
                self.assertNotIn('usage', self.parse(reply({'text': 'a'},
                                                           usageMetadata=usage)))

    def test_response_id_is_used_or_derived_stably(self):
        response = reply({'text': 'a'}); del response['responseId']
        first = self.parse(response)['id']
        self.assertRegex(first, r'^gemini-[0-9a-f]{32}$')
        self.assertEqual(self.parse(response)['id'], first)
        for bad in ('', 7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.parse(reply({'text': 'a'}, responseId=bad))

    def test_model_rule_rejects_only_a_definitely_different_model(self):
        accepted = (('gemini-2.5-flash', 'gemini-2.5-flash'),
                    ('gemini-2.5-flash', 'models/gemini-2.5-flash'),
                    ('gemini-2.5-flash', 'gemini-2.5-flash-001'),
                    ('gemini-2.5-flash', 'gemini-2.5-flash-preview-09-2025'),
                    ('gemini-flash-latest', 'gemini-3.8-flash'),
                    ('gemini-flash-latest', 'gemini-flash-latest'),
                    ('gemini-pro-latest', 'gemini-3.8-pro-preview-09-2026'))
        rejected = (('gemini-2.5-flash', 'gemini-2.5-pro'),
                    ('gemini-2.5-flash', 'gemini-2.5-flash-lite'),
                    ('gemini-2.5-flash', 'gemini-2.5-flash-tts'),
                    ('gemini-2.5-flash', 'gemini-2.5-flash2'),
                    ('gemini-3.7-flash', 'gemini-3.8-flash'),
                    ('gemini-flash-latest', 'gemini-3.8-flash-lite'),
                    ('gemini-flash-latest', 'gemini-3.8-pro'),
                    ('gemini-2.5-flash', 7))
        for requested, served in accepted:
            with self.subTest(requested=requested, served=served):
                binding = GeminiBinding.parse(value(requested))
                result = self.parse(reply({'text': 'a'}, modelVersion=served), binding)
                self.assertEqual(result['model'], requested)
        for requested, served in rejected:
            with self.subTest(requested=requested, served=served), self.assertRaisesRegex(
                    ValueError, 'different model'):
                self.parse(reply({'text': 'a'}, modelVersion=served),
                           GeminiBinding.parse(value(requested)))
        missing = reply({'text': 'a'}); del missing['modelVersion']
        self.assertEqual(self.parse(missing)['model'], MODEL)

    def test_binding_rejects_foreign_endpoint(self):
        for changes in ({'endpoint': 'https://proxy.example/v1beta/models'},
                        {'target_id': 'proxy.example'},
                        {'endpoint': 'https://aiplatform.googleapis.com/v1/models'},
                        {'protocol': 'openai-responses-v1'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                GeminiBinding.parse(value(**changes))


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.binding = GeminiBinding.parse(value())

    def consume(self, *events):
        deltas = []
        final = consume_stream(SPEC, self.binding, sse(*events), deltas.append)
        return deltas, final

    def test_realistic_stream_succeeds(self):
        raw = (b'data: {"candidates":[{"content":{"parts":[{"text":"think","thought":true},'
               b'{"text":"Hel"}],"role":"model"},"index":0}],"modelVersion":"gemini-3.8-flash",'
               b'"responseId":"r9"}\r\n\r\n'
               b'data: {"candidates":[{"content":{"parts":[{"text":"lo"}],"role":"model"},'
               b'"index":0}],"usageMetadata":{"promptTokenCount":1},'
               b'"modelVersion":"gemini-3.8-flash","responseId":"r9"}\r\n\r\n'
               b'data: {"candidates":[{"content":{"role":"model"},"finishReason":"STOP",'
               b'"index":0}],"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":2,'
               b'"thoughtsTokenCount":1,"totalTokenCount":6},'
               b'"modelVersion":"gemini-3.8-flash","responseId":"r9"}\r\n\r\n')
        deltas = []
        final = consume_stream(SPEC, self.binding, raw.splitlines(keepends=True),
                               deltas.append)
        self.assertEqual(deltas, ['Hel', 'lo'])
        self.assertEqual(SPEC.parse_response(final, self.binding), {
            'id': 'r9', 'model': MODEL, 'response': 'Hello',
            'usage': {'input_tokens': 3, 'output_tokens': 3, 'total_tokens': 6}})

    def test_no_finish_reason_is_a_lost_stream(self):
        with self.assertRaises(ConnectionError):
            self.consume(reply({'text': 'a'}, finish=None))
        with self.assertRaises(ConnectionError):
            self.consume()

    def test_error_event_raises_without_echoing_its_message(self):
        with self.assertRaisesRegex(DirectResponseError, 'RESOURCE_EXHAUSTED') as caught:
            self.consume(reply({'text': 'a'}, finish=None),
                         {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED',
                                    'message': 'echoed prompt'}})
        self.assertNotIn('echoed', str(caught.exception))
        with self.assertRaises(DirectResponseError):
            self.consume({'error': 'text'})

    def test_safety_and_prompt_block_fail_the_stream(self):
        with self.assertRaisesRegex(ValueError, 'SAFETY'):
            self.consume(reply({'text': 'a'}, finish=None), reply(finish='SAFETY'))
        with self.assertRaisesRegex(ValueError, 'SAFETY'):
            self.consume(reply({'text': 'a'}, finish='SAFETY'), reply(finish='STOP'))
        with self.assertRaisesRegex(ValueError, 'SAFETY'):
            self.consume({'promptFeedback': {'blockReason': 'SAFETY'}})

    def test_prompt_feedback_neither_completes_nor_hides_a_block(self):
        with self.assertRaises(ConnectionError):
            self.consume({'promptFeedback': {'safetyRatings': []}})
        with self.assertRaisesRegex(ValueError, 'OTHER'):
            self.consume({'promptFeedback': {'blockReason': 'OTHER'}},
                         {'promptFeedback': {'safetyRatings': []}})

    def test_stream_rejects_changed_model_and_multiple_candidates(self):
        with self.assertRaisesRegex(ValueError, 'changed model'):
            self.consume(reply({'text': 'a'}, finish=None),
                         reply({'text': 'b'}, modelVersion='gemini-3.8-pro'))
        with self.assertRaisesRegex(ValueError, 'different model'):
            self.consume(reply({'text': 'a'}, modelVersion='gemini-3.8-pro'))
        one = reply({'text': 'a'})['candidates'][0]
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.consume({'candidates': [one, one]})
        with self.assertRaisesRegex(ValueError, 'non-text'):
            self.consume(reply({'functionCall': {'name': 'f'}}))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.secret = 'AIza' + 'k' * 32
        self.credentials = DirectCredentials(self.state, SPEC)
        self.credentials.put('credential:gemini-generate-primary', self.secret)
        self.binding = GeminiBinding.parse(value())
        self.adapter_runs = DirectRuns(self.state, SPEC)

    def handoff(self):
        return DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                               self.binding.target(), b'hello')

    def test_catalog_paginates_filters_and_strips_prefix(self):
        generate = ['generateContent', 'countTokens']
        pages = {None: {'models': [
                    {'name': 'models/gemini-3.8-flash', 'supportedGenerationMethods':
                        generate + ['streamGenerateContent']},
                    {'name': 'models/gemini-embedding-2',
                     'supportedGenerationMethods': ['embedContent']},
                    {'name': 'models/gemini-embedding-3', 'supportedGenerationMethods': generate},
                    {'name': 'models/gemini-3.1-flash-image',
                     'supportedGenerationMethods': generate},
                    {'name': 'models/gemini-nano-banana-2.1',
                     'supportedGenerationMethods': generate},
                    {'name': 'models/gemini-3.8-flash-tts',
                     'supportedGenerationMethods': generate},
                    {'name': 'models/gemini-3.8-live', 'supportedGenerationMethods': generate},
                    {'name': 'models/gemini-2.5-flash-native-audio-preview-12-2025',
                     'supportedGenerationMethods': generate}],
                 'nextPageToken': 'page-2'},
                 'page-2': {'models': [{'name': 'models/gemini-3.8-pro',
                                        'supportedGenerationMethods': generate}]}}
        cursors = []
        def transport(spec, secret, cursor):
            self.assertEqual(secret, self.secret); cursors.append(cursor)
            return pages[cursor]
        projected = DirectCatalog(self.state, SPEC, transport).refresh(self.secret)
        self.assertEqual(cursors, [None, 'page-2'])
        offers = {item['provider_model_id']: item for item in projected['offers']}
        self.assertEqual(sorted(offers), ['gemini-3.8-flash', 'gemini-3.8-pro'])
        names = lambda model: {item['name'] for item in offers[model]['capabilities']
                               if item['supported']}
        self.assertEqual(names('gemini-3.8-flash'), {
            'generate-text', 'json-output', 'streaming', 'text-output'})
        self.assertEqual(names('gemini-3.8-pro'), {
            'generate-text', 'json-output', 'text-output'})

    def test_models_path_limits_and_quotes_the_cursor(self):
        self.assertEqual(SPEC.models_path(None), '/v1beta/models?pageSize=1000')
        self.assertEqual(SPEC.models_path('a+b/c='),
                         '/v1beta/models?pageSize=1000&pageToken=a%2Bb%2Fc%3D')

    def test_malformed_catalog_is_rejected(self):
        good = {'name': 'models/gemini-x', 'supportedGenerationMethods': ['generateContent']}
        for page in ([], {}, {'models': 'x'}, {'models': [good], 'nextPageToken': 7},
                     {'models': ['x']}, {'models': [dict(good, name='gemini-x')]},
                     {'models': [dict(good, name='tunedModels/gemini-x')]},
                     {'models': [dict(good, name='models/bad name')]},
                     {'models': [dict(good, name=7)]},
                     {'models': [dict(good, supportedGenerationMethods='generateContent')]},
                     {'models': [dict(good, supportedGenerationMethods=[1])]},
                     {'models': [{'name': 'models/gemini-x'}]}):
            with self.subTest(page=page), self.assertRaises(ValueError):
                DirectCatalog(self.state, SPEC, lambda *_: page).refresh(self.secret)
        self.assertEqual(DirectCatalog(self.state, SPEC).load()['discovery'], 'not-loaded')

    def test_adapter_dispatch_end_to_end(self):
        calls = []
        def transport(binding, request, secret):
            calls.append(json.loads(request)); self.assertEqual(secret, self.secret)
            return reply({'text': 'ok'}, usageMetadata=USAGE)
        adapter = DirectAdapter(self.adapter_runs, self.credentials, transport)
        handoff = self.handoff()
        first = adapter.dispatch(handoff, self.binding)
        self.assertEqual(first['response'], 'ok')
        self.assertEqual(adapter.dispatch(handoff, self.binding), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['contents'][0]['parts'], [{'text': 'hello'}])
        self.assertEqual(calls[0]['generationConfig'], {'maxOutputTokens': 123})

    def test_adapter_stream_failure_and_loss_are_recorded(self):
        def stream_with(*events):
            def stream(binding, request, secret, on_delta):
                return consume_stream(SPEC, binding, sse(*events), on_delta)
            return DirectAdapter(self.adapter_runs, self.credentials,
                                 stream_transport=stream)
        ok = reply({'text': 'ok'})
        deltas = []
        self.assertEqual(stream_with(ok).dispatch_stream(
            self.handoff(), self.binding, deltas.append)['response'], 'ok')
        self.assertEqual(deltas, ['ok'])
        with self.assertRaisesRegex(DirectResponseError, 'SAFETY'):
            stream_with(reply(finish='SAFETY')).dispatch_stream(
                self.handoff(), self.binding, lambda _: None)
        with self.assertRaises(DirectUnknownRun):
            stream_with(reply({'text': 'x'}, finish=None)).dispatch_stream(
                self.handoff(), self.binding, lambda _: None)


if __name__ == '__main__':
    unittest.main()
