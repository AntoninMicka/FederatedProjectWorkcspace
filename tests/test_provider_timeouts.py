# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Binding timeouts: absolute without streaming, inactivity bound with streaming."""
import http.client
import re
import time
import unittest
from unittest.mock import patch

from spikes import provider_deadline
from spikes.atlascloud_backend import AtlasCloudAdapter, AtlasCloudBinding
from spikes.desktop_ui import HTML, JS
from spikes.direct_provider import _http_stream_transport, _http_transport
from spikes.openai_backend import OpenAIAdapter, OpenAIBinding
from spikes.provider_deadline import (EXTERNAL_CLIENT_TIMEOUT_MS, MAX_PROVIDER_TIMEOUT,
                                      provider_connection)
from tests import test_atlascloud_backend, test_direct_provider, test_openai_backend
from tests import test_http_deadline as peers


class StreamDeadlineTests(unittest.TestCase):
    peer = peers.HTTPDeadlineTests.peer

    @classmethod
    def setUpClass(cls):
        peers.HTTPDeadlineTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        peers.HTTPDeadlineTests.tearDownClass.__func__(cls)

    def read(self, serve, *, stream, seconds=.2):
        peer = self.peer(serve, budget=2)
        connection = provider_connection(http.client.HTTPSConnection(peer.host, peer.port,
            context=peer._context, timeout=seconds), seconds, stream=stream)
        self.addCleanup(connection.close)
        connection.request('GET', '/')
        return connection.getresponse().read()

    @staticmethod
    def trickle(chunks, gap):
        def serve(conn, stop):
            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: '
                         + str(chunks).encode() + b'\r\n\r\n')
            for _ in range(chunks):
                if stop.wait(gap):
                    return
                conn.sendall(b'x')
        return serve

    def test_active_stream_outlives_binding_timeout_but_plain_request_does_not(self):
        started = time.monotonic()
        self.assertEqual(self.read(self.trickle(12, .05), stream=True), b'x' * 12)
        self.assertGreater(time.monotonic() - started, .4)
        with self.assertRaises(TimeoutError):
            self.read(self.trickle(12, .05), stream=False)

    def test_stream_inactivity_still_uses_binding_timeout(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.read(self.trickle(3, 1), stream=True)
        self.assertLess(time.monotonic() - started, .8)

    def test_trickling_stream_stops_at_absolute_cap(self):
        started = time.monotonic()
        with patch.object(provider_deadline, 'STREAM_TOTAL_SECONDS', .4), \
                self.assertRaises(TimeoutError):
            self.read(self.trickle(100, .05), stream=True)
        self.assertLess(time.monotonic() - started, 1)


class BindingLimitTests(unittest.TestCase):
    def fixture(self, case):
        test = case(); test.setUp(); self.addCleanup(test.doCleanups)
        return test

    def test_every_text_provider_accepts_the_shared_maximum_only(self):
        for case, binding in ((test_openai_backend.OpenAIBackendTests, OpenAIBinding),
                              (test_atlascloud_backend.AtlasCloudBackendTests,
                               AtlasCloudBinding),
                              (test_direct_provider.DirectProviderTests,
                               test_direct_provider.FakeBinding)):
            value = self.fixture(case).value
            with self.subTest(binding=binding.__name__):
                self.assertEqual(binding.parse({**value, 'timeout_seconds':
                    MAX_PROVIDER_TIMEOUT}).timeout_seconds, MAX_PROVIDER_TIMEOUT)
                with self.assertRaises(ValueError):
                    binding.parse({**value, 'timeout_seconds': MAX_PROVIDER_TIMEOUT + 1})

    def test_transports_request_inactivity_semantics_only_for_streams(self):
        calls = []

        def record(connection, seconds, *, stream=False):
            calls.append((seconds, stream)); raise ConnectionAbortedError('recorded')
        openai = self.fixture(test_openai_backend.OpenAIBackendTests).binding
        atlas = self.fixture(test_atlascloud_backend.AtlasCloudBackendTests).binding
        direct = self.fixture(test_direct_provider.DirectProviderTests).binding
        cases = (('spikes.openai_backend', lambda: OpenAIAdapter._http_transport(
                      openai, b'{}', 's'), False),
                 ('spikes.openai_backend', lambda: OpenAIAdapter._http_stream_transport(
                      openai, b'{}', 's', print), True),
                 ('spikes.atlascloud_backend', lambda: AtlasCloudAdapter._http_transport(
                      atlas, b'{}', 's'), False),
                 ('spikes.atlascloud_backend', lambda: AtlasCloudAdapter
                      ._http_stream_transport(atlas, b'{}', 's', print), True),
                 ('spikes.direct_provider', lambda: _http_transport(direct, b'{}', 's'),
                  False),
                 ('spikes.direct_provider', lambda: _http_stream_transport(
                      direct, b'{}', 's', print), True))
        for module, call, stream in cases:
            calls.clear()
            with self.subTest(module=module, stream=stream), \
                    patch(module + '.provider_connection', record), \
                    self.assertRaises(ConnectionAbortedError):
                call()
            self.assertEqual(calls, [(30, stream)])


class ClientTimeoutTests(unittest.TestCase):
    def test_ui_waits_longer_than_any_backend_deadline(self):
        self.assertGreater(EXTERNAL_CLIENT_TIMEOUT_MS, MAX_PROVIDER_TIMEOUT * 1000)
        self.assertTrue(JS.startswith(
            f'const EXTERNAL_CLIENT_TIMEOUT_MS={EXTERNAL_CLIENT_TIMEOUT_MS};'))
        for path in ("'/v1/external/send',pendingChatRequest,",
                     "'/v1/external/confirm',", "'/v1/tasks/external/confirm',{"):
            with self.subTest(path=path):
                start = JS.index(path)
                self.assertIn('EXTERNAL_CLIENT_TIMEOUT_MS', JS[start:JS.index(';', start)])

    def test_text_backend_forms_offer_shared_limits_and_useful_defaults(self):
        for form in ('external', 'atlascloud', 'anthropic-messages', 'gemini-generate',
                     'xai-responses'):
            with self.subTest(form=form):
                match = re.search(r'<form id="' + form + r'-backend-form"[^>]*>(.*?)</form>',
                                  HTML, re.S)
                self.assertIsNotNone(match)
                body = match.group(1)
                self.assertIn('name="timeout_seconds" type="number" min="1" max="'
                              + str(MAX_PROVIDER_TIMEOUT) + '" value="300"', body)
                self.assertIn('name="max_output_tokens" type="number" min="1" '
                              'max="128000" value="16384"', body)


if __name__ == '__main__':
    unittest.main()
