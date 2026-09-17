# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaBinding


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
