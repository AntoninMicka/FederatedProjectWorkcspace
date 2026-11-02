# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Claude wire format through the direct provider framework; no network."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.claude_backend import API_VERSION, ClaudeBinding, SPEC
from spikes.context_builder import DispatchHandoff
from spikes.direct_provider import (consume_stream, DirectAdapter, DirectCatalog,
                                    DirectCredentials, DirectResponseError, DirectRuns,
                                    DirectUnknownRun)
from spikes.metadata import ValidationError


MODEL = 'claude-test-a'
SECRET = 'sk-test-' + 'x' * 32


def binding_value(**changes):
    return {'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'r1',
            'adapter': 'anthropic-messages', 'boundary': 'external-provider',
            'endpoint': SPEC.endpoint, 'model': MODEL, 'target_id': SPEC.host,
            'credential_ref': 'credential:anthropic-messages-primary',
            'credential_revision': 1, 'offer_id': 'anthropic:offer',
            'protocol': SPEC.protocol, 'knowledge_revision': 'empty-v1',
            'capabilities': ['generate-text', 'streaming', 'text-output'],
            'max_output_tokens': 321, 'timeout_seconds': 30, **changes}


def message(**changes):
    return {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': MODEL,
            'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn',
            'stop_sequence': None, 'stop_details': None,
            'usage': {'input_tokens': 10, 'output_tokens': 5}, **changes}


def sse(*events):
    lines = []
    for event in events:
        lines.append(b'event: ' + event['type'].encode() + b'\n')
        lines.append(b'data: ' + json.dumps(event).encode() + b'\n')
        lines.append(b'\n')
    return lines


def start(**usage):
    return {'type': 'message_start', 'message': {
        'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'content': [],
        'model': MODEL, 'stop_reason': None, 'stop_sequence': None,
        'usage': {'input_tokens': 25, 'output_tokens': 1, **usage}}}


def block_start(index, kind, **fields):
    return {'type': 'content_block_start', 'index': index,
            'content_block': {'type': kind, **fields}}


def delta(index, kind, **fields):
    return {'type': 'content_block_delta', 'index': index,
            'delta': {'type': kind, **fields}}


def block_stop(index):
    return {'type': 'content_block_stop', 'index': index}


def message_delta(reason='end_turn', usage=None, **fields):
    return {'type': 'message_delta', 'usage': usage or {'output_tokens': 15},
            'delta': {'stop_reason': reason, 'stop_sequence': None, **fields}}


STOP = {'type': 'message_stop'}
TEXT_STREAM = (block_start(0, 'text', text=''), delta(0, 'text_delta', text='Hel'),
               {'type': 'ping'}, delta(0, 'text_delta', text='lo'), block_stop(0))


class ClaudeWireTests(unittest.TestCase):
    def setUp(self):
        self.binding = ClaudeBinding.parse(binding_value())

    def parse(self, value):
        return SPEC.parse_response(value, self.binding)

    def test_body_is_minimal_and_pins_the_bound_model(self):
        body = SPEC.build_body('hello', self.binding, 'text', False)
        self.assertEqual(body, {'model': MODEL, 'max_tokens': 321,
                                'messages': [{'role': 'user', 'content': 'hello'}]})
        streaming = SPEC.build_body('hello', self.binding, 'text', True)
        self.assertEqual(streaming, {**body, 'stream': True})
        for forbidden in ('temperature', 'top_p', 'top_k', 'thinking', 'fallbacks'):
            self.assertNotIn(forbidden, streaming)

    def test_json_output_is_refused_and_never_discovered(self):
        with self.assertRaisesRegex(ValueError, 'only text'):
            SPEC.build_body('hello', self.binding, 'json', False)
        page = SPEC.parse_models({'data': [{'type': 'model', 'id': MODEL, 'capabilities': {
            'structured_outputs': {'supported': True}}}], 'has_more': False, 'last_id': MODEL})
        self.assertNotIn('json-output', page['items'][0]['capabilities'])

    def test_auth_headers_hold_the_secret_and_paths_do_not(self):
        self.assertEqual(API_VERSION, '2026-10-21')
        self.assertEqual(SPEC.auth_headers(SECRET), {
            'Authorization': 'Bearer ' + SECRET, 'anthropic-version': API_VERSION})
        for path in (SPEC.generate_path(MODEL, False), SPEC.generate_path(MODEL, True),
                     SPEC.models_path(None), SPEC.models_path('cursor')):
            self.assertNotIn(SECRET, path)

    def test_binding_rejects_foreign_targets(self):
        for changes in ({'endpoint': 'https://proxy.example/v1/messages'},
                        {'target_id': 'proxy.example'}, {'protocol': 'openai-responses-v1'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ClaudeBinding.parse(binding_value(**changes))

    def test_only_end_turn_is_a_complete_answer(self):
        self.assertEqual(self.parse(message())['response'], 'ok')
        for reason, expected in (('max_tokens', 'max_tokens'), ('tool_use', 'tool'),
                                 ('pause_turn', 'pause_turn'),
                                 ('stop_sequence', 'stop_sequence'),
                                 ('model_context_window_exceeded', 'context_window'),
                                 ('brand_new', 'brand_new'), (None, 'unknown'),
                                 ('Bad reason\nprompt', 'unknown')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, expected):
                self.parse(message(stop_reason=reason))

    def test_stop_reason_is_checked_before_content(self):
        with self.assertRaisesRegex(ValueError, 'max_tokens'):
            self.parse(message(stop_reason='max_tokens', content=[{'type': 'tool_use'}]))

    def test_refusal_reports_category_but_never_explanation(self):
        details = {'type': 'refusal', 'category': 'cyber', 'explanation': 'SECRET PROMPT'}
        with self.assertRaises(ValueError) as caught:
            self.parse(message(stop_reason='refusal', stop_details=details))
        self.assertIn('cyber', str(caught.exception))
        self.assertNotIn('SECRET PROMPT', str(caught.exception))
        for stop_details in (None, {'category': None}, {'category': 'free text here'}):
            with self.subTest(details=stop_details):
                with self.assertRaisesRegex(ValueError, 'refused.*unknown'):
                    self.parse(message(stop_reason='refusal', stop_details=stop_details))

    def test_thinking_is_ignored_and_text_blocks_concatenate(self):
        content = [{'type': 'thinking', 'thinking': 'hidden', 'signature': 's'},
                   {'type': 'text', 'text': 'a'}, {'type': 'redacted_thinking', 'data': 'x'},
                   {'type': 'text', 'text': 'b', 'citations': None}]
        self.assertEqual(self.parse(message(content=content))['response'], 'ab')

    def test_unsupported_block_or_missing_text_is_rejected(self):
        for content in ([{'type': 'text', 'text': 'a'}, {'type': 'tool_use'}],
                        [{'type': 'thinking', 'thinking': ''}], [],
                        [{'type': 'text', 'text': ''}], [{'type': 'text'}], ['x'], None):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.parse(message(content=content))

    def test_model_and_message_shape_are_enforced(self):
        for changes in ({'model': 'claude-test-b'}, {'model': None}, {'type': 'error'},
                        {'role': 'user'}, {'id': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.parse(message(**changes))
        with self.assertRaises(ValueError):
            self.parse([])

    def test_usage_adds_cache_tokens(self):
        usage = self.parse(message(usage={
            'input_tokens': 10, 'output_tokens': 5, 'cache_creation_input_tokens': 2,
            'cache_read_input_tokens': 3, 'service_tier': 'standard'}))['usage']
        self.assertEqual(usage, {'input_tokens': 15, 'output_tokens': 5, 'total_tokens': 20})
        usage = self.parse(message(usage={
            'input_tokens': 10, 'output_tokens': 5, 'cache_creation_input_tokens': None,
            'cache_read_input_tokens': 0}))['usage']
        self.assertEqual(usage['input_tokens'], 10)

    def test_invalid_usage_is_omitted(self):
        for usage in (None, [], {}, {'input_tokens': 1}, {'input_tokens': -1, 'output_tokens': 1},
                      {'input_tokens': True, 'output_tokens': 1},
                      {'input_tokens': 1, 'output_tokens': '2'},
                      {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': -1},
                      {'input_tokens': 1, 'output_tokens': 2,
                       'cache_creation_input_tokens': 1.5}):
            with self.subTest(usage=usage):
                self.assertNotIn('usage', self.parse(message(usage=usage)))


class ClaudeStreamTests(unittest.TestCase):
    def setUp(self):
        self.binding = ClaudeBinding.parse(binding_value())

    def consume(self, *events):
        deltas = []
        value = consume_stream(SPEC, self.binding, sse(*events), deltas.append)
        return value, deltas

    def test_full_stream_with_thinking_succeeds(self):
        value, deltas = self.consume(
            start(cache_read_input_tokens=5), {'type': 'ping'},
            block_start(0, 'thinking', thinking='', signature=''),
            delta(0, 'thinking_delta', thinking='hidden'),
            delta(0, 'signature_delta', signature='sig'), block_stop(0),
            *[dict(item, index=1) for item in TEXT_STREAM if 'index' in item],
            {'type': 'future_event', 'payload': 1}, message_delta(), STOP)
        self.assertEqual(deltas, ['Hel', 'lo'])
        parsed = SPEC.parse_response(value, self.binding)
        self.assertEqual(parsed['response'], 'Hello')
        self.assertEqual(parsed['usage'], {'input_tokens': 30, 'output_tokens': 15,
                                           'total_tokens': 45})
        json.dumps(value)

    def test_usage_in_delta_is_cumulative_and_null_keeps_earlier_value(self):
        value, _ = self.consume(start(), *TEXT_STREAM, message_delta(usage={
            'input_tokens': 40, 'output_tokens': 15, 'cache_read_input_tokens': None}), STOP)
        self.assertEqual(SPEC.parse_response(value, self.binding)['usage']['input_tokens'], 40)
        value, _ = self.consume(start(), *TEXT_STREAM, message_delta(usage={
            'input_tokens': None, 'output_tokens': 15}), STOP)
        self.assertEqual(SPEC.parse_response(value, self.binding)['usage']['input_tokens'], 25)

    def test_stream_without_usable_usage_still_succeeds(self):
        first = start(); del first['message']['usage']
        event = message_delta(); del event['usage']
        value, _ = self.consume(first, *TEXT_STREAM, event, STOP)
        self.assertNotIn('usage', SPEC.parse_response(value, self.binding))

    def test_truncated_stream_is_a_lost_response(self):
        for events in ((start(),), (start(), *TEXT_STREAM),
                       (start(), *TEXT_STREAM, message_delta())):
            with self.subTest(count=len(events)), self.assertRaises(ConnectionError):
                self.consume(*events)
        lines = sse(start(), *TEXT_STREAM)
        with self.assertRaises(ConnectionError):
            consume_stream(SPEC, self.binding, lines + [b'data: {"type":"mess'], lambda _: None)

    def test_error_event_raises_without_provider_text(self):
        event = {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'PROMPT'}}
        with self.assertRaises(DirectResponseError) as caught:
            self.consume(start(), *TEXT_STREAM, event)
        self.assertIn('overloaded_error', str(caught.exception))
        self.assertNotIn('PROMPT', str(caught.exception))
        with self.assertRaisesRegex(DirectResponseError, 'unknown'):
            self.consume({'type': 'error'})

    def test_refusal_stream_fails_after_partial_text(self):
        details = {'type': 'refusal', 'category': 'bio', 'explanation': 'x'}
        with self.assertRaisesRegex(ValueError, 'refused.*bio'):
            self.consume(start(), *TEXT_STREAM,
                         message_delta('refusal', stop_details=details), STOP)

    def test_other_stream_stop_reasons_and_missing_reason_fail(self):
        with self.assertRaisesRegex(ValueError, 'max_tokens'):
            self.consume(start(), *TEXT_STREAM, message_delta('max_tokens'), STOP)
        with self.assertRaisesRegex(ValueError, 'stop_reason'):
            self.consume(start(), *TEXT_STREAM, STOP)

    def test_stream_model_mismatch_and_foreign_block_fail(self):
        foreign = start(); foreign['message']['model'] = 'claude-test-b'
        with self.assertRaisesRegex(ValueError, 'model differs'):
            self.consume(foreign, *TEXT_STREAM, message_delta(), STOP)
        with self.assertRaisesRegex(ValueError, 'tool_use'):
            self.consume(start(), block_start(0, 'tool_use', id='t', name='n', input={}),
                         delta(0, 'input_json_delta', partial_json='{'), block_stop(0),
                         *[dict(item, index=1) for item in TEXT_STREAM if 'index' in item],
                         message_delta(), STOP)

    def test_malformed_event_order_fails(self):
        cases = {'no start': (block_start(0, 'text', text=''),),
                 'second start': (start(), start()),
                 'no open block': (start(), delta(0, 'text_delta', text='a')),
                 'text in thinking': (start(), block_start(0, 'thinking'),
                                      delta(0, 'text_delta', text='a')),
                 'duplicate index': (start(), block_start(0, 'text'), block_stop(0),
                                     block_start(0, 'text')),
                 'bad index': (start(), block_start(True, 'text')),
                 'unopened stop': (start(), block_stop(0)),
                 'stop in block': (start(), block_start(0, 'text'), STOP),
                 'after stop': (start(), *TEXT_STREAM, message_delta(), STOP,
                                delta(0, 'text_delta', text='late'))}
        for name, events in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.consume(*events)

    def test_text_in_block_start_counts_as_a_delta(self):
        value, deltas = self.consume(start(), block_start(0, 'text', text='a'),
                                     delta(0, 'text_delta', text='b'), block_stop(0),
                                     message_delta(), STOP)
        self.assertEqual(deltas, ['a', 'b'])
        self.assertEqual(SPEC.parse_response(value, self.binding)['response'], 'ab')


class ClaudeProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.state = Path(temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.credentials = DirectCredentials(self.state, SPEC)
        reference = self.credentials.new_reference('primary')
        self.credentials.put(reference, SECRET)
        self.binding = ClaudeBinding.parse(binding_value(credential_ref=reference))
        self.runs = DirectRuns(self.state, SPEC)

    def handoff(self):
        return DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                               self.binding.target(), b'hello')

    def test_catalog_paginates_and_exposes_text_capabilities(self):
        pages = {None: {'data': [{'type': 'model', 'id': 'claude-a/b', 'lifecycle': 'active'}],
                        'first_id': 'claude-a/b', 'has_more': True, 'last_id': 'claude-a/b'},
                 'claude-a/b': {'data': [{'type': 'model', 'id': 'claude-b',
                                          'lifecycle': 'deprecated'}],
                                'has_more': False, 'last_id': 'claude-b'}}
        cursors = []
        def transport(spec, secret, cursor):
            self.assertEqual(secret, SECRET); cursors.append(cursor)
            return pages[cursor]
        projected = DirectCatalog(self.state, SPEC, transport).refresh(SECRET)
        self.assertEqual(cursors, [None, 'claude-a/b'])
        self.assertEqual(sorted(item['provider_model_id'] for item in projected['offers']),
                         ['claude-a/b', 'claude-b'])
        for offer in projected['offers']:
            self.assertEqual(sorted(item['name'] for item in offer['capabilities']
                                    if item['supported']),
                             ['generate-text', 'streaming', 'text-output'])
        offer = projected['offers'][0]
        candidate = binding_value(
            model=offer['provider_model_id'], offer_id=offer['offer_id'],
            knowledge_revision=projected['knowledge_revision'])
        catalog = DirectCatalog(self.state, SPEC)
        catalog.validate_binding_offer(candidate)
        with self.assertRaisesRegex(ValidationError, 'unsupported capability'):
            catalog.validate_binding_offer(dict(candidate, capabilities=[
                'generate-text', 'json-output', 'text-output']))
        self.assertEqual(SPEC.models_path(None), '/v1/models?limit=1000')
        self.assertEqual(SPEC.models_path('claude-a/b'),
                         '/v1/models?limit=1000&after_id=claude-a%2Fb')

    def test_catalog_filters_foreign_retired_and_alias_entries(self):
        page = SPEC.parse_models({'data': [
            {'type': 'model', 'id': 'claude-x'},
            {'type': 'other', 'id': 'not-a-model'},
            {'type': 'model', 'id': 'claude-gone', 'lifecycle': 'retired'},
            {'type': 'model', 'id': 'claude-old-1-5'},
            {'type': 'model', 'id': 'claude-old-1-5-20250101'}],
            'has_more': False, 'last_id': None})
        self.assertEqual([item['model'] for item in page['items']],
                         ['claude-x', 'claude-old-1-5-20250101'])
        self.assertIsNone(page['next_cursor'])

    def test_malformed_catalog_is_rejected(self):
        good = {'data': [], 'has_more': False, 'last_id': None}
        for value in ([], {}, dict(good, data={}), dict(good, has_more='no'),
                      {'data': [], 'last_id': None}, dict(good, last_id=1),
                      dict(good, has_more=True), dict(good, has_more=True, last_id=''),
                      dict(good, data=['x']), dict(good, data=[{'type': 'model'}]),
                      dict(good, data=[{'type': 'model', 'id': 1}])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SPEC.parse_models(value)
        catalog = DirectCatalog(self.state, SPEC, lambda *_: dict(
            good, data=[{'type': 'model', 'id': 'bad id with spaces'}]))
        with self.assertRaises(ValidationError):
            catalog.refresh(SECRET)

    def test_adapter_dispatch_end_to_end_is_not_resent(self):
        calls = []
        def transport(binding, request, secret):
            calls.append(json.loads(request)); self.assertEqual(secret, SECRET)
            return message()
        adapter = DirectAdapter(self.runs, self.credentials, transport)
        handoff = self.handoff()
        first = adapter.dispatch(handoff, self.binding)
        self.assertEqual(first['response'], 'ok')
        self.assertEqual(first['usage']['total_tokens'], 15)
        self.assertEqual(adapter.dispatch(handoff, self.binding), first)
        self.assertEqual(calls, [{'model': MODEL, 'max_tokens': 321, 'messages': [
            {'role': 'user', 'content': 'hello'}]}])

    def test_adapter_stream_success_truncation_and_refusal(self):
        def stream(*events):
            return lambda binding, request, secret, on_delta: consume_stream(
                SPEC, binding, sse(*events), on_delta)
        deltas = []
        adapter = DirectAdapter(self.runs, self.credentials, stream_transport=stream(
            start(), *TEXT_STREAM, message_delta(), STOP))
        self.assertEqual(adapter.dispatch_stream(self.handoff(), self.binding,
                                                 deltas.append)['response'], 'Hello')
        self.assertEqual(deltas, ['Hel', 'lo'])
        truncated = DirectAdapter(self.runs, self.credentials,
                                  stream_transport=stream(start(), *TEXT_STREAM))
        with self.assertRaises(DirectUnknownRun):
            truncated.dispatch_stream(self.handoff(), self.binding, lambda _: None)
        refused = DirectAdapter(self.runs, self.credentials, stream_transport=stream(
            start(), *TEXT_STREAM, message_delta('refusal'), STOP))
        with self.assertRaisesRegex(DirectResponseError, 'refused'):
            refused.dispatch_stream(self.handoff(), self.binding, lambda _: None)

    def test_adapter_records_rejected_response_without_resend(self):
        handoff = self.handoff()
        adapter = DirectAdapter(self.runs, self.credentials,
                                lambda *_: message(stop_reason='max_tokens'))
        with self.assertRaisesRegex(DirectResponseError, 'max_tokens'):
            adapter.dispatch(handoff, self.binding)
        again = DirectAdapter(self.runs, self.credentials,
                              lambda *_: self.fail('must not resend'))
        with self.assertRaisesRegex(DirectResponseError, 'max_tokens'):
            again.dispatch(handoff, self.binding)


if __name__ == '__main__':
    unittest.main()
