# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Small fail-closed contracts shared by LLM backend adapters and services."""
from dataclasses import dataclass
import json

from spikes.metadata import require


CAPABILITY_SCHEMA = 1
ROLE_SCHEMA = 1


class BackendUnknown(RuntimeError):
    pass


class BackendResponseError(RuntimeError):
    pass


def _text(value, label):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and not any(char in value for char in '\0\r\n'), f'Invalid {label}')
    return value


@dataclass(frozen=True)
class BackendCapabilities:
    schema_version: int
    revision: str
    operations: frozenset
    output_formats: frozenset

    def validate(self):
        require(self.schema_version == CAPABILITY_SCHEMA,
                'Unsupported backend capability schema')
        _text(self.revision, 'backend capability revision')
        require(isinstance(self.operations, frozenset)
                and self.operations <= {'generate-text'} and bool(self.operations),
                'Unknown or empty backend capability set')
        require(isinstance(self.output_formats, frozenset)
                and self.output_formats <= {'text', 'json'} and bool(self.output_formats),
                'Unknown or empty backend output format set')
        return self

    def require(self, operation, output_format):
        self.validate()
        require(operation in self.operations, 'Backend capability is not available')
        require(output_format in self.output_formats, 'Backend output format is not available')
        return self


@dataclass(frozen=True)
class RoleDefinition:
    schema_version: int
    role_id: str
    revision: str
    operation: str
    output_format: str

    def validate(self):
        require(self.schema_version == ROLE_SCHEMA, 'Unsupported role schema')
        _text(self.role_id, 'role ID'); _text(self.revision, 'role revision')
        require(self.operation == 'generate-text', 'Unknown role capability')
        require(self.output_format in {'text', 'json'}, 'Unknown role output format')
        return self


class RoleRegistry:
    def __init__(self, roles):
        self._roles = {}
        for role in roles:
            require(isinstance(role, RoleDefinition), 'Invalid role definition')
            role.validate(); key = (role.role_id, role.revision)
            require(key not in self._roles, 'Duplicate role definition')
            self._roles[key] = role

    def resolve(self, role_id, revision):
        role = self._roles.get((role_id, revision))
        require(role is not None, 'Unsupported role or role revision')
        return role


ROLES = RoleRegistry((
    RoleDefinition(1, 'creator', 'creator-v1', 'generate-text', 'text'),
    RoleDefinition(1, 'external-call-planner', 'external-call-planner-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'summarizer', 'summarizer-v1', 'generate-text', 'text'),
    RoleDefinition(1, 'extractor', 'extractor-v1', 'generate-text', 'json'),
    RoleDefinition(1, 'metadata-advisor', 'metadata-advisor-v1', 'generate-text', 'json'),
))


@dataclass(frozen=True)
class BackendExecution:
    adapter_id: str
    binding_id: str
    binding_revision: str
    capability_revision: str
    operation: str
    output_format: str
    role_id: str = ''
    role_revision: str = ''

    def validate(self):
        for value, label in ((self.adapter_id, 'adapter ID'),
                             (self.binding_id, 'binding ID'),
                             (self.binding_revision, 'binding revision'),
                             (self.capability_revision, 'capability revision'),
                             (self.operation, 'backend operation'),
                             (self.output_format, 'backend output format')):
            _text(value, label)
        require(bool(self.role_id) == bool(self.role_revision),
                'Role ID and revision must be supplied together')
        if self.role_id:
            _text(self.role_id, 'role ID'); _text(self.role_revision, 'role revision')
        return self

    def canonical(self):
        self.validate()
        return json.dumps(self.__dict__, sort_keys=True,
                          separators=(',', ':')).encode()


class BackendRegistry:
    """Explicit adapter registry; it never discovers or falls back to providers."""
    def __init__(self):
        self._parsers = {}

    def register(self, adapter_id, parser):
        _text(adapter_id, 'adapter ID')
        require(adapter_id not in self._parsers and callable(parser),
                'Duplicate or invalid backend adapter')
        self._parsers[adapter_id] = parser

    def parse_binding(self, value):
        require(isinstance(value, dict), 'Backend binding must be an object')
        adapter_id = value.get('adapter')
        require(isinstance(adapter_id, str) and adapter_id in self._parsers,
                'Unsupported backend adapter')
        binding = self._parsers[adapter_id](value)
        require(getattr(binding, 'adapter_id', None) == adapter_id,
                'Backend parser returned a different adapter')
        return binding
