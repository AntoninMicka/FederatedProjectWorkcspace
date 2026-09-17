# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict node-local Ollama binding contract; transport is added separately."""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit

from spikes.context_builder import Target
from spikes.metadata import require, uuid


@dataclass(frozen=True)
class OllamaBinding:
    binding_id: str
    revision: str
    boundary: str
    endpoint: str
    model: str
    target_id: str
    tls_cert_sha256: str | None = None

    @classmethod
    def parse(cls, value):
        require(isinstance(value, dict), 'Ollama binding must be an object')
        common = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                  'endpoint', 'model', 'target_id'}
        require(value.keys() in (common, common | {'tls_cert_sha256'}),
                'Unknown or missing Ollama binding field')
        require(value['schema_version'] == 1 and value['adapter'] == 'ollama',
                'Unsupported Ollama binding')
        uuid(value['binding_id'])
        for key in ('revision', 'endpoint', 'model', 'target_id'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    f'Invalid Ollama {key}')
        require(value['boundary'] in {'same-node', 'private-network'},
                'Ollama boundary must be same-node or private-network')
        parsed = urlsplit(value['endpoint'])
        require(not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {'', '/'}, 'Invalid Ollama endpoint')
        require(parsed.port is not None, 'Ollama endpoint requires an explicit port')
        try:
            address = ipaddress.ip_address(parsed.hostname or '')
        except ValueError as exc:
            raise ValueError('Ollama endpoint requires a numeric IP address') from exc
        pin = value.get('tls_cert_sha256')
        if value['boundary'] == 'same-node':
            require(parsed.scheme == 'http' and address.is_loopback,
                    'same-node Ollama requires a numeric loopback HTTP endpoint')
            require(pin is None and value['target_id'] == 'local-process',
                    'same-node Ollama must identify the local process without TLS pin')
        else:
            require(parsed.scheme == 'https' and address.is_private and not address.is_loopback,
                    'private-network Ollama requires a private numeric HTTPS endpoint')
            require(isinstance(pin, str) and bool(re.fullmatch(r'[0-9a-f]{64}', pin)),
                    'private-network Ollama requires a SHA-256 TLS certificate pin')
            uuid(value['target_id'])
        return cls(value['binding_id'], value['revision'], value['boundary'],
                   value['endpoint'].rstrip('/'), value['model'], value['target_id'], pin)

    def target(self):
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.model)
