# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.metadata import ValidationError
from spikes.ollama_backend import (OllamaAdapter, OllamaBinding, OllamaResponseError,
                                   OllamaBindings, OllamaRuns, UnknownRun)


class OllamaBindingTests(unittest.TestCase):
    def binding(self, **changes):
        value = dict(schema_version=1, binding_id=str(uuid4()), revision='revision-1',
                     adapter='ollama', boundary='same-node',
                     endpoint='http://127.0.0.1:11434', model='gemma3',
                     target_id='local-process')
        value.update(changes)
        return value

    def test_same_node_requires_numeric_loopback_without_pin(self):
        binding = OllamaBinding.parse(self.binding())
        self.assertEqual(binding.target().boundary, 'same-node')
        for endpoint in ('http://localhost:11434', 'http://192.168.1.2:11434',
                         'https://127.0.0.1:11434', 'http://127.0.0.1'):
            with self.subTest(endpoint=endpoint), self.assertRaises((ValidationError, ValueError)):
                OllamaBinding.parse(self.binding(endpoint=endpoint))

    def test_private_network_requires_literal_private_https_and_pin(self):
        peer = str(uuid4()); pin = 'a' * 64
        binding = OllamaBinding.parse(self.binding(boundary='private-network',
            endpoint='https://192.168.10.4:11434', target_id=peer,
            tls_cert_sha256=pin))
        self.assertEqual(binding.target().target_id, peer)
        for endpoint in ('https://ollama.lan:11434', 'http://192.168.10.4:11434',
                         'https://8.8.8.8:11434', 'https://127.0.0.1:11434'):
            with self.subTest(endpoint=endpoint), self.assertRaises((ValidationError, ValueError)):
                OllamaBinding.parse(self.binding(boundary='private-network', endpoint=endpoint,
                    target_id=peer, tls_cert_sha256=pin))

    def test_unknown_fields_credentials_and_missing_identity_fail_closed(self):
        for changes in ({'token': 'secret'}, {'endpoint': 'http://u:p@127.0.0.1:11434'},
                        {'boundary': 'private-network', 'endpoint': 'https://10.0.0.2:11434',
                         'target_id': str(uuid4())}):
            with self.subTest(changes=changes), self.assertRaises((ValidationError, ValueError)):
                OllamaBinding.parse(self.binding(**changes))

    def test_binding_survives_restart_and_unsafe_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'; state.mkdir(mode=0o700)
            store = OllamaBindings(state)
            expected = OllamaBinding.parse(self.binding())
            store.save(expected)
            self.assertEqual(OllamaBindings(state).load(), expected)
            store.path.chmod(0o644)
            with self.assertRaisesRegex(ValidationError, 'Unsafe'):
                OllamaBindings(state).load()


class OllamaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='revision-1', adapter='ollama', boundary='same-node',
            endpoint='http://127.0.0.1:11434', model='gemma3', target_id='local-process'))
        self.handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'b' * 64,
                                       self.binding.target(), b'{"context":"exact"}')

    def test_success_is_durable_and_retry_does_not_send_again(self):
        calls = []
        def transport(binding, request):
            calls.append((binding, request))
            return {'model': 'gemma3', 'response': 'answer', 'done': True}
        adapter = OllamaAdapter(OllamaRuns(self.state), transport)
        first = adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.dispatch(self.handoff, self.binding), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'succeeded')
        self.assertEqual(hashlib.sha256(self.handoff.payload).hexdigest(),
                         hashlib.sha256(b'{"context":"exact"}').hexdigest())
        restarted = OllamaAdapter(OllamaRuns(self.state),
                                  lambda binding, request: self.fail('must not resend'))
        self.assertEqual(restarted.dispatch(self.handoff, self.binding), first)

    def test_lost_response_becomes_unknown_without_automatic_retry(self):
        calls = []
        def transport(binding, request):
            calls.append(request)
            raise TimeoutError('lost response')
        adapter = OllamaAdapter(OllamaRuns(self.state), transport)
        with self.assertRaisesRegex(UnknownRun, 'outcome is unknown'):
            adapter.dispatch(self.handoff, self.binding)
        with self.assertRaisesRegex(UnknownRun, 'automatic retry is forbidden'):
            adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(len(calls), 1)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'unknown')

    def test_known_failure_and_binding_change_fail_closed(self):
        def rejected(binding, request):
            raise OllamaResponseError('redirect forbidden')
        adapter = OllamaAdapter(OllamaRuns(self.state), rejected)
        with self.assertRaises(OllamaResponseError):
            adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'failed')
        with self.assertRaises(OllamaResponseError):
            adapter.dispatch(self.handoff, self.binding)
        changed = OllamaBinding.parse(dict(schema_version=1, binding_id=self.binding.binding_id,
            revision='revision-2', adapter='ollama', boundary='same-node',
            endpoint='http://127.0.0.1:11434', model='gemma3', target_id='local-process'))
        other = DispatchHandoff(str(uuid4()), str(uuid4()), 'c' * 64,
                                self.binding.target(), b'{}')
        with self.assertRaisesRegex(ValidationError, 'differs'):
            OllamaAdapter(OllamaRuns(self.state), rejected).dispatch(other, changed)

    def test_invalid_response_is_a_durable_known_failure(self):
        adapter = OllamaAdapter(OllamaRuns(self.state),
                                lambda binding, request: {'model': 'other', 'response': 7})
        with self.assertRaisesRegex(OllamaResponseError, 'Invalid Ollama response'):
            adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'failed')

    def test_http_transport_forbids_redirect(self):
        events = []
        class Response:
            status = 302
        class Connection:
            def __init__(self, *args, **kwargs): events.append(('timeout', kwargs['timeout']))
            def connect(self): events.append('connect')
            def request(self, *args, **kwargs): events.append('request')
            def getresponse(self): return Response()
            def close(self): events.append('close')
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            with self.assertRaisesRegex(OllamaResponseError, 'redirect'):
                OllamaAdapter._http_transport(self.binding, b'{}')
        self.assertEqual(events, [('timeout', 180), 'connect', 'request', 'close'])

    def test_private_tls_pin_is_checked_before_request(self):
        certificate = b'test certificate'; events = []
        peer = str(uuid4())
        binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='revision-1', adapter='ollama', boundary='private-network',
            endpoint='https://10.0.0.2:11434', model='gemma3', target_id=peer,
            tls_cert_sha256=hashlib.sha256(certificate).hexdigest()))
        class Socket:
            def getpeercert(self, binary_form=False):
                events.append('pin'); return certificate
        class Response:
            status = 200
            def read(self, limit): return b'{"model":"gemma3","response":"ok"}'
        class Connection:
            def __init__(self, *args, **kwargs):
                self.sock = Socket(); events.append(('timeout', kwargs['timeout']))
            def connect(self): events.append('connect')
            def request(self, *args, **kwargs): events.append('request')
            def getresponse(self): return Response()
            def close(self): events.append('close')
        with patch('spikes.ollama_backend.http.client.HTTPSConnection', Connection):
            result = OllamaAdapter._http_transport(binding, b'{}')
        self.assertEqual(result['response'], 'ok')
        self.assertEqual(events, [('timeout', 180), 'connect', 'pin', 'request', 'close'])
