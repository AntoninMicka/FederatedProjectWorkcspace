# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.context_builder import DispatchHandoff
from spikes.backend_contract import (BackendCapabilities, BackendRegistry, ROLES,
                                     RoleDefinition)
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

    def test_private_network_normalizes_common_openssl_fingerprint(self):
        raw = 'sha256 Fingerprint=' + ':'.join(['AB'] * 32)
        binding = OllamaBinding.parse(self.binding(boundary='private-network',
            endpoint='https://192.168.10.4:11443', target_id=str(uuid4()),
            tls_cert_sha256=raw))
        self.assertEqual(binding.tls_cert_sha256, 'ab' * 32)
        self.assertEqual(binding.serialize()['tls_cert_sha256'], 'ab' * 32)

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

    def test_bounded_invalid_draft_is_atomic_secret_free_and_restart_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'; state.mkdir(mode=0o700)
            store = OllamaBindings(state)
            draft = self.binding(boundary='private-network',
                                 endpoint='https://192.168.10.4:11443',
                                 target_id=str(uuid4()), tls_cert_sha256='unfinished')
            store.save_draft(draft)
            self.assertEqual(OllamaBindings(state).load_draft(), draft)
            self.assertEqual(store.draft_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValidationError, 'draft endpoint'):
                store.save_draft(dict(draft, endpoint=11443))
            with self.assertRaisesRegex(ValidationError, 'credentials'):
                store.save_draft(dict(draft, endpoint='https://user:secret@192.168.10.4:11443'))
            self.assertEqual(store.load_draft(), draft)
            store.draft_path.chmod(0o644)
            with self.assertRaisesRegex(ValidationError, 'Unsafe'):
                store.load_draft()

    def test_backend_registry_capabilities_and_roles_fail_closed(self):
        registry = BackendRegistry(); registry.register('ollama', OllamaBinding.parse)
        binding = registry.parse_binding(self.binding())
        binding.capabilities().require('generate-text', 'json')
        role = ROLES.resolve('extractor', 'extractor-v1')
        self.assertEqual((role.operation, role.output_format), ('generate-text', 'json'))
        with self.assertRaisesRegex(ValidationError, 'Unsupported backend adapter'):
            registry.parse_binding(dict(self.binding(), adapter='unknown'))
        with self.assertRaisesRegex(ValidationError, 'Unsupported role'):
            ROLES.resolve('extractor', 'extractor-v2')
        with self.assertRaisesRegex(ValidationError, 'Unknown or empty'):
            BackendCapabilities(1, 'bad', frozenset({'embeddings'}),
                                frozenset({'text'})).validate()
        with self.assertRaisesRegex(ValidationError, 'Unknown role capability'):
            RoleDefinition(1, 'bad', 'v1', 'browse', 'text').validate()


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

    def test_stream_success_is_durable_and_only_final_response_is_authoritative(self):
        calls = []; deltas = []; statuses = []
        def stream(binding, request, on_delta, on_status):
            calls.append(json.loads(request)); on_status('waiting-first-token')
            on_status('generating'); on_delta('první '); on_delta('část')
            return {'model': binding.model, 'created_at': '2026-10-12T12:00:00Z',
                    'response': 'první část', 'done': True,
                    'prompt_eval_count': 3, 'eval_count': 2}
        adapter = OllamaAdapter(OllamaRuns(self.state), stream_transport=stream)
        result = adapter.dispatch_stream(
            self.handoff, self.binding, deltas.append, statuses.append)
        self.assertEqual((deltas, result['response']), (['první ', 'část'], 'první část'))
        self.assertTrue(calls[0]['stream'])
        self.assertEqual(statuses, ['connecting', 'waiting-first-token',
                                    'generating'])
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['response'], result)
        self.assertEqual(adapter.dispatch_stream(
            self.handoff, self.binding, self.fail), result)
        self.assertEqual(len(calls), 1)

    def test_invalid_stream_after_delta_fails_without_persisting_partial_text(self):
        def malformed(_binding, _request, on_delta, _on_status):
            on_delta('torzo')
            raise OllamaResponseError('Invalid Ollama NDJSON frame',
                                      code='invalid-stream-json')
        adapter = OllamaAdapter(OllamaRuns(self.state), stream_transport=malformed)
        with self.assertRaises(OllamaResponseError):
            adapter.dispatch_stream(self.handoff, self.binding, lambda _delta: None)
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual((row['state'], row['response'], row['error_code']),
                         ('failed', None, 'invalid-stream-json'))

    def test_interrupted_stream_is_unknown_and_never_automatically_retried(self):
        calls = []
        def interrupted(_binding, _request, on_delta, _on_status):
            calls.append('dispatch'); on_delta('torzo')
            raise TimeoutError('idle')
        adapter = OllamaAdapter(OllamaRuns(self.state), stream_transport=interrupted)
        with self.assertRaises(UnknownRun):
            adapter.dispatch_stream(self.handoff, self.binding, lambda _delta: None)
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['state'], 'unknown')
        restarted = OllamaAdapter(OllamaRuns(self.state), stream_transport=lambda *_args:
                                  self.fail('must not reconnect after restart'))
        with self.assertRaisesRegex(UnknownRun, 'automatic retry is forbidden'):
            restarted.dispatch_stream(self.handoff, self.binding, lambda _delta: None)
        self.assertEqual(calls, ['dispatch'])

    def test_http_stream_accepts_fragmented_ndjson_and_normalizes_final_frame(self):
        frames = (b'{"model":"gemma3","created_at":"thinking","response":"",'
                  b'"thinking":"reasoning","done":false}\n'
                  b'{"model":"gemma3","created_at":"now","response":"A","done":false}\n'
                  b'{"model":"gemma3","created_at":"later","response":"","thinking":"",'
                  b'"done":true,'
                  b'"prompt_eval_count":4,"eval_count":1}\n')
        class Socket:
            def settimeout(self, value): self.timeout = value
        class Response:
            status = 200
            def __init__(self): self.data = bytearray(frames)
            def readline(self, limit):
                if not self.data: return b''
                newline = self.data.index(10) + 1
                value = bytes(self.data[:newline]); del self.data[:newline]
                return value
        class Connection:
            def __init__(self, *args, **kwargs): self.sock = Socket()
            def connect(self): pass
            def request(self, method, path, body=None, headers=None):
                self.request_body = json.loads(body)
            def getresponse(self): return Response()
            def close(self): pass
        deltas = []; statuses = []
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            result = OllamaAdapter._http_stream_transport(
                self.binding, b'{"stream":true}', deltas.append, statuses.append)
        self.assertEqual((deltas, result['response']), (['A'], 'A'))
        self.assertNotIn('thinking', result)
        self.assertEqual((result['prompt_eval_count'], result['eval_count']), (4, 1))
        self.assertEqual(statuses, ['waiting-first-token', 'thinking', 'generating'])

    def test_stream_first_token_and_idle_timeouts_are_durable_unknown(self):
        class Socket:
            def settimeout(self, value): self.timeout = value
        class Response:
            status = 200
            def __init__(self, first): self.first = first
            def readline(self, limit):
                if self.first is not None:
                    value = self.first; self.first = None; return value
                raise TimeoutError('slow stream')
        for first, code in ((None, 'first-token-timeout'),
                            (b'{"model":"gemma3","created_at":"now",'
                             b'"response":"A","done":false}\n', 'idle-timeout')):
            with self.subTest(code=code):
                handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'e' * 64,
                                          self.binding.target(), b'{"context":"exact"}')
                class Connection:
                    def __init__(self, *args, **kwargs): self.sock = Socket()
                    def connect(self): pass
                    def request(self, *args, **kwargs): pass
                    def getresponse(self): return Response(first)
                    def close(self): pass
                adapter = OllamaAdapter(OllamaRuns(self.state))
                with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
                    with self.assertRaises(UnknownRun) as caught:
                        adapter.dispatch_stream(handoff, self.binding, lambda _delta: None)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(adapter.runs.get(handoff.run_id)['state'], 'unknown')

    def test_concurrent_same_run_never_starts_second_transport(self):
        entered = threading.Event(); release = threading.Event(); calls = []
        def transport(binding, request):
            calls.append(request); entered.set(); self.assertTrue(release.wait(2))
            return {'model': binding.model, 'response': 'answer'}
        adapter = OllamaAdapter(OllamaRuns(self.state), transport)
        result = []
        worker = threading.Thread(target=lambda: result.append(
            adapter.dispatch(self.handoff, self.binding)))
        worker.start(); self.assertTrue(entered.wait(2))
        try:
            with self.assertRaisesRegex(UnknownRun, 'automatic retry is forbidden'):
                adapter.dispatch(self.handoff, self.binding)
        finally:
            release.set(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(result[0]['response'], 'answer')

    def test_new_run_records_backend_execution_identity(self):
        role = ROLES.resolve('extractor', 'extractor-v1')
        adapter = OllamaAdapter(OllamaRuns(self.state), lambda binding, request:
                                {'model': binding.model, 'response': '{}'})
        adapter.dispatch(self.handoff, self.binding, role, 'json')
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual(row['adapter_id'], 'ollama')
        self.assertEqual(row['binding_id'], self.binding.binding_id)
        self.assertEqual(row['binding_revision'], self.binding.revision)
        self.assertEqual(row['capability_revision'], 'ollama-generate-v1')
        self.assertEqual((row['operation'], row['output_format']),
                         ('generate-text', 'json'))
        self.assertEqual((row['role_id'], row['role_revision']),
                         ('extractor', 'extractor-v1'))
        self.assertEqual(row['manifest_sha256'], self.handoff.manifest_sha256)

    def test_legacy_prepared_run_migrates_in_place_and_remains_idempotent(self):
        request = json.dumps(dict(model=self.binding.model,
            prompt=OllamaAdapter._prompt(self.handoff.payload), stream=False),
            sort_keys=True, separators=(',', ':')).encode()
        legacy_digest = hashlib.sha256(self.handoff.manifest_sha256.encode()
                                       + b'\0' + request).hexdigest()
        path = self.state / 'ollama-runs.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE runs (run_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, '
                       'state TEXT NOT NULL, response TEXT, error TEXT)')
            db.execute('INSERT INTO runs(run_id,request_digest,state) VALUES (?,?,?)',
                       (self.handoff.run_id, legacy_digest, 'prepared'))
        path.chmod(0o600)
        calls = []
        adapter = OllamaAdapter(OllamaRuns(self.state), lambda binding, raw:
            (calls.append(raw), {'model': binding.model, 'response': 'ok'})[1])
        self.assertEqual(adapter.dispatch(self.handoff, self.binding)['response'], 'ok')
        self.assertEqual(adapter.dispatch(self.handoff, self.binding)['response'], 'ok')
        self.assertEqual(len(calls), 1)
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual((row['state'], row['adapter_id']), ('succeeded', 'ollama'))
        self.assertNotEqual(row['request_digest'], legacy_digest)

    def test_legacy_unknown_run_is_not_migrated_or_retried(self):
        request = json.dumps(dict(model=self.binding.model,
            prompt=OllamaAdapter._prompt(self.handoff.payload), stream=False),
            sort_keys=True, separators=(',', ':')).encode()
        legacy_digest = hashlib.sha256(self.handoff.manifest_sha256.encode()
                                       + b'\0' + request).hexdigest()
        path = self.state / 'ollama-runs.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE runs (run_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, '
                       'state TEXT NOT NULL, response TEXT, error TEXT)')
            db.execute('INSERT INTO runs(run_id,request_digest,state) VALUES (?,?,?)',
                       (self.handoff.run_id, legacy_digest, 'unknown'))
        path.chmod(0o600)
        adapter = OllamaAdapter(OllamaRuns(self.state),
                                lambda binding, raw: self.fail('must not retry'))
        with self.assertRaisesRegex(UnknownRun, 'automatic retry is forbidden'):
            adapter.dispatch(self.handoff, self.binding)
        restarted = OllamaAdapter(OllamaRuns(self.state),
                                  lambda binding, raw: self.fail('must not retry after restart'))
        with self.assertRaisesRegex(UnknownRun, 'automatic retry is forbidden'):
            restarted.dispatch(self.handoff, self.binding)
        row = adapter.runs.get(self.handoff.run_id)
        self.assertIsNone(row['adapter_id'])

    def test_capability_change_after_prepare_is_rejected_without_dispatch(self):
        adapter = OllamaAdapter(OllamaRuns(self.state),
                                lambda binding, raw: self.fail('must not dispatch'))
        adapter.prepare(self.handoff, self.binding)
        changed = BackendCapabilities(1, 'ollama-generate-v2',
            frozenset({'generate-text'}), frozenset({'text', 'json'}))
        with patch.object(OllamaBinding, 'capabilities', return_value=changed):
            with self.assertRaisesRegex(ValidationError, 'different backend execution'):
                adapter.dispatch(self.handoff, self.binding)

    def test_conversation_payload_is_rendered_as_roles_not_base64_json(self):
        first, second = str(uuid4()), str(uuid4())
        payload = json.dumps(dict(schema_version=1, inputs=[
            dict(input_id=first, content_b64=base64.b64encode('ahoj'.encode()).decode()),
            dict(input_id=second, content_b64=base64.b64encode(
                'co je dnes za den?'.encode()).decode())], conversation=[
                    dict(message_id=first, role='user'),
                    dict(message_id=second, role='user')])).encode()
        handoff = DispatchHandoff(str(uuid4()), str(uuid4()), 'd' * 64,
                                  self.binding.target(), payload)
        captured = []
        adapter = OllamaAdapter(OllamaRuns(self.state), lambda binding, request:
            (captured.append(json.loads(request)),
             {'model': 'gemma3', 'response': 'answer'})[1])
        adapter.dispatch(handoff, self.binding)
        self.assertEqual(captured[0]['prompt'],
                         'User:\nahoj\n\nUser:\nco je dnes za den?\n\nAssistant:\n')
        self.assertNotIn('content_b64', captured[0]['prompt'])

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
        self.assertEqual(adapter.runs.get(self.handoff.run_id)['error_code'],
                         'transport-unknown')

    def test_connect_failure_is_known_and_diagnostic_survives_restart(self):
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def connect(self): raise ConnectionRefusedError('refused')
            def close(self): pass
        adapter = OllamaAdapter(OllamaRuns(self.state))
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            with self.assertRaisesRegex(OllamaResponseError, 'unavailable') as first:
                adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(first.exception.code, 'unavailable')
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual((row['state'], row['error_code']), ('failed', 'unavailable'))
        restarted = OllamaAdapter(OllamaRuns(self.state),
                                  lambda *_args: self.fail('must not redispatch'))
        with self.assertRaises(OllamaResponseError) as second:
            restarted.dispatch(self.handoff, self.binding)
        self.assertEqual(second.exception.code, 'unavailable')

    def test_timeout_after_request_is_unknown_and_diagnostic_survives_restart(self):
        events = []
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def connect(self): events.append('connect')
            def request(self, *args, **kwargs): events.append('request')
            def getresponse(self): raise TimeoutError('slow response')
            def close(self): events.append('close')
        adapter = OllamaAdapter(OllamaRuns(self.state))
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            with self.assertRaises(UnknownRun) as first:
                adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(first.exception.code, 'response-timeout')
        self.assertEqual(events, ['connect', 'request', 'close'])
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual((row['state'], row['error_code']),
                         ('unknown', 'response-timeout'))
        restarted = OllamaAdapter(OllamaRuns(self.state),
                                  lambda *_args: self.fail('must not redispatch'))
        with self.assertRaises(UnknownRun) as second:
            restarted.dispatch(self.handoff, self.binding)
        self.assertEqual(second.exception.code, 'response-timeout')

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

    def test_wrong_private_tls_pin_fails_before_request(self):
        certificate = b'unexpected certificate'; events = []
        binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='revision-1', adapter='ollama', boundary='private-network',
            endpoint='https://10.0.0.2:11434', model='gemma3', target_id=str(uuid4()),
            tls_cert_sha256='a' * 64))
        class Socket:
            def getpeercert(self, binary_form=False): return certificate
        class Connection:
            def __init__(self, *args, **kwargs): self.sock = Socket()
            def connect(self): events.append('connect')
            def request(self, *args, **kwargs): events.append('request')
            def close(self): events.append('close')
        with patch('spikes.ollama_backend.http.client.HTTPSConnection', Connection):
            with self.assertRaises(OllamaResponseError) as caught:
                OllamaAdapter._http_transport(binding, b'{}')
        self.assertEqual(caught.exception.code, 'tls-pin-mismatch')
        self.assertEqual(events, ['connect', 'close'])

    def test_invalid_wire_json_has_specific_known_diagnostic(self):
        class Response:
            status = 200
            def read(self, limit): return b'not-json'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def connect(self): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        adapter = OllamaAdapter(OllamaRuns(self.state))
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            with self.assertRaises(OllamaResponseError) as caught:
                adapter.dispatch(self.handoff, self.binding)
        self.assertEqual(caught.exception.code, 'invalid-json')
        row = adapter.runs.get(self.handoff.run_id)
        self.assertEqual((row['state'], row['error_code']), ('failed', 'invalid-json'))

    def test_probe_reads_only_model_catalog_and_reports_missing_model(self):
        events = []
        class Response:
            status = 200
            def read(self, limit):
                return b'{"models":[{"name":"other:latest"}]}'
        class Connection:
            def __init__(self, *args, **kwargs): events.append(('timeout', kwargs['timeout']))
            def connect(self): events.append('connect')
            def request(self, method, path, body=None, headers=None):
                events.append((method, path, body))
            def getresponse(self): return Response()
            def close(self): events.append('close')
        with patch('spikes.ollama_backend.http.client.HTTPConnection', Connection):
            result = OllamaAdapter.probe(self.binding)
        self.assertEqual(result['diagnostic'], 'model-unavailable')
        self.assertFalse(result['model_available'])
        self.assertEqual(result['model_count'], 1)
        self.assertEqual(events, [('timeout', 10), 'connect', ('GET', '/api/tags', None), 'close'])
