# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Small fail-closed contracts shared by LLM backend adapters and services."""
from dataclasses import dataclass, replace
import hashlib
import json
import re

from spikes.metadata import require


CAPABILITY_SCHEMA = 1
ROLE_SCHEMA = 1
_SHA256 = re.compile(r'[0-9a-f]{64}')


class BackendUnknown(RuntimeError):
    pass


class BackendResponseError(RuntimeError):
    pass


def _text(value, label):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and not any(char in value for char in '\0\r\n'), f'Invalid {label}')
    return value


@dataclass(frozen=True)
class RunSelection:
    """Immutable provider-neutral offer identity pinned before dispatch."""
    schema_version: int
    selection_revision: str
    adapter_id: str
    binding_id: str
    binding_revision: str
    offer_id: str
    provider_model_id: str
    protocol: str
    capability_revision: str
    capabilities: tuple
    knowledge_revision: str
    credential_revision: int | None = None

    @classmethod
    def parse(cls, value):
        fields = {'schema_version', 'selection_revision', 'adapter_id', 'binding_id',
                  'binding_revision', 'offer_id', 'provider_model_id', 'protocol',
                  'capability_revision', 'capabilities', 'knowledge_revision',
                  'credential_revision'}
        require(isinstance(value, dict) and set(value) == fields
                and isinstance(value['capabilities'], list),
                'Invalid stored run selection')
        return cls(value['schema_version'], value['selection_revision'],
                   value['adapter_id'], value['binding_id'], value['binding_revision'],
                   value['offer_id'], value['provider_model_id'], value['protocol'],
                   value['capability_revision'], tuple(value['capabilities']),
                   value['knowledge_revision'], value['credential_revision']).validate()

    def validate(self):
        require(self.schema_version == 1, 'Unsupported run selection schema')
        for value, label in ((self.selection_revision, 'selection revision'),
                             (self.adapter_id, 'selection adapter ID'),
                             (self.binding_id, 'selection binding ID'),
                             (self.binding_revision, 'selection binding revision'),
                             (self.offer_id, 'selection offer ID'),
                             (self.provider_model_id, 'selection model ID'),
                             (self.protocol, 'selection protocol'),
                             (self.capability_revision, 'selection capability revision'),
                             (self.knowledge_revision, 'selection knowledge revision')):
            _text(value, label)
        require(isinstance(self.capabilities, tuple) and bool(self.capabilities)
                and self.capabilities == tuple(sorted(set(self.capabilities))),
                'Invalid run selection capabilities')
        for value in self.capabilities: _text(value, 'selection capability')
        require(self.credential_revision is None
                or type(self.credential_revision) is int and self.credential_revision >= 1,
                'Invalid run selection credential revision')
        return self

    def serialize(self):
        self.validate()
        return {'schema_version': self.schema_version,
                'selection_revision': self.selection_revision,
                'adapter_id': self.adapter_id, 'binding_id': self.binding_id,
                'binding_revision': self.binding_revision, 'offer_id': self.offer_id,
                'provider_model_id': self.provider_model_id, 'protocol': self.protocol,
                'capability_revision': self.capability_revision,
                'capabilities': list(self.capabilities),
                'knowledge_revision': self.knowledge_revision,
                'credential_revision': self.credential_revision}

    def canonical(self):
        return json.dumps(self.serialize(), sort_keys=True,
                          separators=(',', ':')).encode()

    def public_serialize(self):
        """Return inspectable offer identity without credential metadata."""
        value = self.serialize()
        value.pop('credential_revision')
        return value

    def digest(self):
        return hashlib.sha256(self.canonical()).hexdigest()


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
                and self.operations <= {'generate-text', 'generate-image'}
                and bool(self.operations),
                'Unknown or empty backend capability set')
        require(isinstance(self.output_formats, frozenset)
                and self.output_formats <= {'text', 'json', 'image/png'}
                and bool(self.output_formats),
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
    RoleDefinition(1, 'opponent', 'opponent-v1', 'generate-text', 'text'),
    RoleDefinition(1, 'external-call-planner', 'external-call-planner-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'task-router', 'task-router-v1', 'generate-text', 'json'),
    RoleDefinition(1, 'task-router', 'task-router-presentation-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'task-output', 'task-output-conversation-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'task-output', 'task-output-document-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'task-output', 'task-output-presentation-v1',
                   'generate-text', 'json'),
    RoleDefinition(1, 'researcher', 'researcher-v1', 'generate-text', 'text'),
    RoleDefinition(1, 'researcher', 'researcher-v2', 'generate-text', 'json'),
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
    selection_sha256: str = ''

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
        require(not self.selection_sha256 or bool(_SHA256.fullmatch(self.selection_sha256)),
                'Invalid run selection digest')
        return self

    def canonical(self):
        self.validate()
        value = dict(self.__dict__)
        if not self.selection_sha256: value.pop('selection_sha256')
        return json.dumps(value, sort_keys=True,
                          separators=(',', ':')).encode()


def pin_execution(execution, run_selection, model):
    """Bind an adapter execution to one already revalidated model offer."""
    require(isinstance(execution, BackendExecution), 'Backend execution is required')
    if run_selection is None:
        return execution
    require(isinstance(run_selection, RunSelection), 'Validated run selection is required')
    run_selection.validate()
    require((run_selection.adapter_id, run_selection.binding_id,
             run_selection.binding_revision, run_selection.provider_model_id) ==
            (execution.adapter_id, execution.binding_id,
             execution.binding_revision, model),
            'Run selection differs from backend execution')
    return replace(execution, selection_sha256=run_selection.digest()).validate()


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
