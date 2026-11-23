# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""External failures retain useful text without accepting an incomplete result."""
import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from spikes.backend_contract import BackendResponseError, external_response_failure
from spikes.desktop_ui import JS
from spikes.local_api import running_api
from spikes.openai_backend import OpenAIAdapter
from tests.test_desktop import TransportDesktopHandler
from tests import test_local_api


class ExternalResponseFailureTests(unittest.TestCase):
    def test_diagnostics_allowlist_never_exposes_arbitrary_provider_text(self):
        limited = external_response_failure(BackendResponseError(
            'Claude response was truncated by max_tokens'))
        self.assertEqual(limited['diagnostic'], 'output-limit')
        self.assertIn('Zvyšte', limited['error'])
        self.assertEqual((limited['outcome'], limited['retry']), ('failed', 'new-run'))
        unsafe = external_response_failure(BackendResponseError('secret request content'))
        self.assertNotIn('secret', json.dumps(unsafe))
        self.assertEqual(unsafe['diagnostic'], 'invalid-response')

    def test_stream_keeps_deltas_then_reports_specific_terminal_failure(self):
        class Service:
            calls = 0
            def external_send_stream(self, request, on_delta):
                self.calls += 1
                on_delta('užitečný neúplný text')
                raise BackendResponseError('Claude response was truncated by max_tokens')
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=TransportDesktopHandler) as server:
            server.chat_service = Service()
            response = driver.request(server, path='/v1/external/send-stream', body=b'{}')
        events = [json.loads(line) for line in response.split(b'\r\n\r\n', 1)[1].splitlines()]
        self.assertEqual(events[0], {'type': 'delta', 'delta': 'užitečný neúplný text'})
        self.assertEqual(events[1]['diagnostic'], 'output-limit')
        self.assertEqual(events[1]['type'], 'error')
        self.assertFalse(any(e['type'] == 'result' for e in events))
        self.assertEqual(server.chat_service.calls, 1)

    def test_openai_incomplete_and_model_mismatch_are_distinct(self):
        binding = SimpleNamespace(model='bound-model')
        value = dict(id='response', status='incomplete', model='bound-model', output=[],
                     incomplete_details={'reason': 'max_output_tokens'})
        with self.assertRaisesRegex(ValueError, 'exceeded max_output_tokens'):
            OpenAIAdapter._response(value, binding)
        value['model'] = 'other-model'
        with self.assertRaisesRegex(ValueError, 'model differs'):
            OpenAIAdapter._response(value, binding)
        value['model'] = binding.model
        value['incomplete_details'] = {'reason': 'other'}
        with self.assertRaisesRegex(ValueError, 'did not complete'):
            OpenAIAdapter._response(value, binding)

    def test_openai_incomplete_terminal_event_is_not_a_lost_stream(self):
        value = dict(id='response', status='incomplete', model='bound-model', output=[],
                     incomplete_details={'reason': 'max_output_tokens'})
        events = [{'type': 'response.output_text.delta', 'delta': 'partial'},
                  {'type': 'response.incomplete', 'response': value}]
        lines = iter(part for event in events for part in
                     [b'data: ' + json.dumps(event).encode() + b'\n', b'\n'])
        class Response:
            status = 200
            def readline(self, _limit): return next(lines, b'')
            def close(self): pass
        class Connection:
            sock = None
            def connect(self): pass
            closed = False
            def __init__(self, *_args, **_kwargs): pass
            def request(self, *_args, **_kwargs): pass
            def getresponse(self): return Response()
            def close(self): Connection.closed = True
        binding = SimpleNamespace(model='bound-model', timeout_seconds=30)
        deltas = []
        with patch('spikes.openai_backend.http.client.HTTPSConnection', Connection):
            with self.assertRaisesRegex(ValueError, 'exceeded max_output_tokens'):
                OpenAIAdapter._http_stream_transport(binding, b'{}', 'secret', deltas.append)
        self.assertEqual(deltas, ['partial'])
        self.assertTrue(Connection.closed)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node for DOM behavior')
    def test_partial_text_is_preserved_as_untrusted_downloadable_notice(self):
        start = JS.index('function preserveRejectedExternalStream()')
        end = JS.index('\n}', start) + 2
        harness = r'''
const assert=require('node:assert/strict');
function element(){return {dataset:{},style:{},children:[],textContent:'',append(...xs){this.children.push(...xs)},addEventListener(name,fn){this[name]=fn},remove(){},click(){}};}
const chatStream={textContent:'<script>untrusted</script>'},chatMessages=element();
const document={createElement:element,body:element()};
'''
        checks = r'''
preserveRejectedExternalStream();
assert.equal(chatMessages.children.length,1);
const notice=chatMessages.children[0];
assert.equal(notice.dataset.incomplete,'true');
assert.match(notice.children[0].textContent,/není součástí historie/);
assert.equal(notice.children[1].textContent,chatStream.textContent);
assert.equal(notice.children[2].textContent,'Stáhnout přijatý text');
chatStream.textContent='';preserveRejectedExternalStream();
assert.equal(chatMessages.children.length,1);
'''
        subprocess.run(['node', '-e', harness + JS[start:end] + checks], check=True)
        external = JS[JS.index("if(mode==='brainstorming' && adapter!=='ollama')"):
                      JS.index("if(mode==='brainstorming' && adapter==='ollama')")]
        self.assertIn('preserveRejectedExternalStream();', external)
