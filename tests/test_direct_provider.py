# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Provider-independent recovery of the direct provider framework."""
import http.client
import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.direct_provider import (consume_stream, DirectAdapter, DirectBinding,
    DirectBindings, DirectCatalog, DirectCredentials, DirectResponseError, DirectRuns,
    DirectUnknownRun, ProviderSpec, read_sse)
from spikes.metadata import ValidationError


def _parse(value, binding):
    if not (isinstance(value, dict) and isinstance(value.get('text'), str)
            and value.get('model') == binding.model):
        raise ValueError('Invalid fake response')
    return {'id': 'r1', 'model': value['model'], 'response': value['text'],
            'usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3}}


def _event(state, event):
    if event.get('type') == 'error':
        raise DirectResponseError('Fake stream failed')
    if event.get('type') == 'done':
        state['done'] = event
        return None
    return event.get('delta')


def _final(state):
    if 'done' not in state:
        raise ConnectionError('Fake stream ended before completion')
    return state['done']['value']


SPEC = ProviderSpec(
    adapter_id='fake-direct', provider_id='fake', name='Fake', host='api.fake.example',
    endpoint='https://api.fake.example/v1/generate', protocol='xai-responses-v1',
    auth_headers=lambda secret: {'Authorization': 'Bearer ' + secret},
    generate_path=lambda model, stream: '/v1/generate',
    build_body=lambda prompt, binding, output_format, stream: {
        'model': binding.model, 'prompt': prompt, 'stream': stream},
    parse_response=_parse, stream_state=dict, stream_event=_event, stream_final=_final,
    models_path=lambda cursor: '/v1/models' + ('?after=' + cursor if cursor else ''),
    parse_models=lambda value: value)


class FakeBinding(DirectBinding):
    spec = SPEC


PAGES = {None: {'items': [{'model': 'fake-a', 'capabilities': {
                    'generate-text', 'text-output', 'streaming'}}], 'next_cursor': 'p2'},
         'p2': {'items': [{'model': 'fake-b', 'capabilities': {
                    'generate-text', 'text-output'}}], 'next_cursor': None}}


class DirectProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.secret = 'sk-fake-' + 'x' * 32
        self.credentials = DirectCredentials(self.state, SPEC)
        self.reference = self.credentials.new_reference('primary')
        self.credentials.put(self.reference, self.secret)
        self.value = {'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'r1',
            'adapter': 'fake-direct', 'boundary': 'external-provider',
            'endpoint': SPEC.endpoint, 'model': 'fake-a', 'target_id': SPEC.host,
            'credential_ref': self.reference, 'credential_revision': 1,
            'offer_id': 'fake:offer', 'protocol': SPEC.protocol,
            'knowledge_revision': 'empty-v1',
            'capabilities': ['generate-text', 'streaming', 'text-output'],
            'max_output_tokens': 100, 'timeout_seconds': 30}
        self.binding = FakeBinding.parse(self.value)
        self.runs = DirectRuns(self.state, SPEC)
        self.handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                                       self.binding.target(), b'text')

    def adapter(self, transport=None, stream_transport=None):
        return DirectAdapter(self.runs, self.credentials, transport, stream_transport)

    def test_binding_rejects_foreign_target_and_stores_no_secret(self):
        for changes in ({'endpoint': 'https://proxy.example/v1/generate'},
                        {'target_id': 'other.example'}, {'boundary': 'same-node'},
                        {'adapter': 'other'}, {'protocol': 'openai-responses-v1'},
                        {'credential_ref': 'credential:other-primary'},
                        {'capabilities': ['generate-text', 'text-output', 'tools']}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                FakeBinding.parse(dict(self.value, **changes))
        store = DirectBindings(self.state, FakeBinding); store.save(self.binding)
        self.assertEqual(store.load(), self.binding)
        self.assertNotIn(self.secret, store.path.read_text())
        self.assertEqual(FakeBinding.parse(self.binding.serialize()), self.binding)

    def test_catalog_collects_pages_and_requires_fresh_offer(self):
        cursors = []
        def transport(spec, secret, cursor):
            self.assertEqual(secret, self.secret); cursors.append(cursor)
            return PAGES[cursor]
        catalog = DirectCatalog(self.state, SPEC, transport)
        self.assertEqual(catalog.load()['discovery'], 'not-loaded')
        projected = catalog.refresh(self.secret)
        self.assertEqual(cursors, [None, 'p2'])
        self.assertEqual(sorted(item['provider_model_id'] for item in projected['offers']),
                         ['fake-a', 'fake-b'])
        offer = next(item for item in projected['offers']
                     if item['provider_model_id'] == 'fake-a')
        candidate = dict(self.value, offer_id=offer['offer_id'],
                         knowledge_revision=projected['knowledge_revision'])
        catalog.validate_binding_offer(candidate)
        with self.assertRaisesRegex(ValidationError, 'unsupported capability'):
            catalog.validate_binding_offer(dict(candidate, capabilities=[
                'generate-text', 'json-output', 'text-output']))
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            catalog.validate_binding_offer(dict(candidate, offer_id='fake:missing'))

    def test_failed_refresh_keeps_last_catalog(self):
        DirectCatalog(self.state, SPEC, lambda *_: PAGES['p2']).refresh(self.secret)
        def failing(*_):
            raise DirectResponseError('Fake request was rejected with HTTP 401')
        with self.assertRaises(DirectResponseError):
            DirectCatalog(self.state, SPEC, failing).refresh(self.secret)
        self.assertEqual([item['provider_model_id'] for item in
                          DirectCatalog(self.state, SPEC).load()['offers']], ['fake-b'])

    def test_success_is_idempotent_and_not_resent(self):
        calls = []
        def transport(binding, request, secret):
            calls.append(request); self.assertEqual(secret, self.secret)
            return {'model': 'fake-a', 'text': 'ok'}
        adapter = self.adapter(transport)
        first = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(first['response'], 'ok')
        self.assertEqual(adapter.dispatch(self.handoff, self.binding), first)
        self.assertEqual(len(calls), 1)

    def test_lost_response_stays_unknown_and_is_never_resent(self):
        calls = []
        def transport(*_):
            calls.append(1); raise TimeoutError('lost')
        adapter = self.adapter(transport)
        for _ in range(2):
            with self.assertRaises(DirectUnknownRun):
                adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(len(calls), 1)

    def test_crash_after_dispatch_mark_recovers_as_unknown(self):
        class Crash(BaseException):
            pass
        def transport(*_):
            raise Crash()
        with self.assertRaises(Crash):
            self.adapter(transport).dispatch(self.handoff, self.binding)
        recovered = self.adapter(lambda *_: self.fail('must not resend'))
        with self.assertRaises(DirectUnknownRun):
            recovered.dispatch(self.handoff, self.binding)

    def test_invalid_or_rejected_response_fails_without_retry(self):
        for error in (lambda *_: {'model': 'other', 'text': 'x'},
                      lambda *_: (_ for _ in ()).throw(DirectResponseError('HTTP 429'))):
            handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                                      self.binding.target(), b'text')
            with self.assertRaises(DirectResponseError):
                self.adapter(error).dispatch(handoff, self.binding)
            with self.assertRaises(DirectResponseError):
                self.adapter(lambda *_: self.fail('must not resend')).dispatch(
                    handoff, self.binding)

    def test_changed_credential_blocks_dispatch(self):
        self.credentials.put(self.reference, self.secret + 'y')
        with self.assertRaisesRegex(ValidationError, 'credential revision'):
            self.adapter(lambda *_: self.fail('must not send')).dispatch(
                self.handoff, self.binding)

    def test_streaming_requires_capability_and_json_requires_capability(self):
        limited = FakeBinding.parse(dict(self.value, capabilities=[
            'generate-text', 'text-output']))
        handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'b' * 64,
                                  limited.target(), b'text')
        with self.assertRaisesRegex(ValidationError, 'streaming'):
            DirectAdapter._request(handoff, limited, stream=True)
        with self.assertRaisesRegex(ValidationError, 'JSON'):
            DirectAdapter._request(handoff, limited, output_format='json')

    def sse(self, *events):
        return [line for event in events for line in (b'data: ' + event + b'\n', b'\n')]

    def test_stream_requires_completion_and_matching_deltas(self):
        deltas = []
        done = b'{"type":"done","value":{"model":"fake-a","text":"ab"}}'
        lines = [line for event in (b'{"delta":"a"}', b'{"delta":"b"}', done, b'[DONE]')
                 for line in self.sse(event)]
        value = consume_stream(SPEC, self.binding, lines, deltas.append)
        self.assertEqual((deltas, value['text']), (['a', 'b'], 'ab'))
        with self.assertRaises(ConnectionError):
            consume_stream(SPEC, self.binding, self.sse(b'{"delta":"a"}'), lambda _: None)
        with self.assertRaisesRegex(ValidationError, 'deltas differ'):
            consume_stream(SPEC, self.binding, self.sse(b'{"delta":"x"}') + self.sse(done),
                           lambda _: None)
        with self.assertRaises(DirectResponseError):
            consume_stream(SPEC, self.binding, self.sse(b'{"type":"error"}'), lambda _: None)

    def test_truncated_stream_is_a_lost_response_not_a_failure(self):
        for lines in ([b'data: {"delta":"a"}'], [b'data: {"delta":"a"}\n']):
            with self.subTest(lines=lines), self.assertRaises(ConnectionError):
                read_sse(lines, lambda _: None)
        def stream(binding, request, secret, on_delta):
            return consume_stream(SPEC, binding, [b'data: {"delta":"a"}'], on_delta)
        adapter = self.adapter(stream_transport=stream)
        with self.assertRaises(DirectUnknownRun):
            adapter.dispatch_stream(self.handoff, self.binding, lambda _: None)


class DirectTransportTests(DirectProviderTests):
    """The real HTTP code against a local server; only TLS is replaced."""
    def setUp(self):
        super().setUp()
        outer = self; self.requests = []; self.reply = (200, b'{}')
        class Handler(http.server.BaseHTTPRequestHandler):
            def handle_request(self):
                length = int(self.headers.get('Content-Length') or 0)
                outer.requests.append((self.command, self.path, dict(self.headers),
                                       self.rfile.read(length)))
                status, body = outer.reply
                self.send_response(status)
                if status == 302:
                    self.send_header('Location', 'http://127.0.0.1:1/elsewhere')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
            do_GET = do_POST = handle_request
            def log_message(self, *_): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        port = server.server_port
        patcher = patch('spikes.direct_provider._connection', lambda spec, timeout:
                        http.client.HTTPConnection('127.0.0.1', port, timeout=timeout))
        patcher.start(); self.addCleanup(patcher.stop)

    def test_real_transport_sends_secret_only_in_header(self):
        self.reply = (200, json.dumps({'model': 'fake-a', 'text': 'ok'}).encode())
        result = self.adapter().dispatch(self.handoff, self.binding)
        self.assertEqual(result['response'], 'ok')
        method, path, headers, body = self.requests[0]
        self.assertEqual((method, path), ('POST', '/v1/generate'))
        self.assertEqual(headers['Authorization'], 'Bearer ' + self.secret)
        self.assertNotIn(self.secret.encode(), body)

    def test_real_transport_refuses_redirect_and_rejected_status(self):
        for status, expected in ((302, 'redirect is forbidden'), (401, 'HTTP 401'),
                                 (429, 'HTTP 429'), (500, 'HTTP 500')):
            with self.subTest(status=status):
                self.requests.clear(); self.reply = (status, b'{"echo":"secret prompt"}')
                handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'a' * 64,
                                          self.binding.target(), b'text')
                with self.assertRaisesRegex(DirectResponseError, expected) as caught:
                    self.adapter().dispatch(handoff, self.binding)
                self.assertNotIn('secret prompt', str(caught.exception))
                self.assertEqual(len(self.requests), 1, 'no hidden retry or redirect')

    def test_real_stream_and_catalog(self):
        done = json.dumps({'type': 'done', 'value': {'model': 'fake-a', 'text': 'ab'}})
        self.reply = (200, ('data: {"delta":"a"}\n\ndata: {"delta":"b"}\n\n'
                            'data: ' + done + '\n\n').encode())
        deltas = []
        result = self.adapter().dispatch_stream(self.handoff, self.binding, deltas.append)
        self.assertEqual((deltas, result['response']), (['a', 'b'], 'ab'))
        self.assertEqual(self.requests[0][2]['Accept'], 'text/event-stream')
        self.reply = (200, json.dumps({'items': [{'model': 'fake-a', 'capabilities': []}],
                                       'next_cursor': None}).encode())
        with self.assertRaises(ValidationError):
            DirectCatalog(self.state, SPEC).refresh(self.secret)

    def test_real_stream_cut_off_is_unknown(self):
        self.reply = (200, b'data: {"delta":"a"}\n\n')
        with self.assertRaises(DirectUnknownRun):
            self.adapter().dispatch_stream(self.handoff, self.binding, lambda _: None)


if __name__ == '__main__':
    unittest.main()
