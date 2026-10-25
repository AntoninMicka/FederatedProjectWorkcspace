# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed chat-mode policy and immutable per-run backend selection."""
from dataclasses import dataclass
import hashlib

from spikes.metadata import require, uuid
from spikes.ollama_backend import OllamaBinding
from spikes.openai_backend import OpenAIBinding
from spikes.atlascloud_backend import AtlasCloudBinding


MODES = frozenset({'orchestration', 'brainstorming'})
ADAPTERS = frozenset({'ollama', 'openai-responses', 'atlascloud-text'})


def _model(value):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and len(value.encode('utf-8')) <= 128
            and not any(char in value for char in '\0\r\n'),
            'Invalid brainstorm model')
    return value


@dataclass(frozen=True)
class ChatRunChoice:
    mode: str
    adapter_id: str
    model: str | None
    binding_id: str | None = None
    binding_revision: str | None = None

    @classmethod
    def parse(cls, value):
        core = {'mode', 'adapter', 'model'}
        selected = core | {'binding_id', 'binding_revision'}
        require(isinstance(value, dict) and frozenset(value) in {frozenset(core),
                                                                 frozenset(selected)},
                'Unknown or missing chat run choice field')
        require(value['mode'] in MODES and value['adapter'] in ADAPTERS,
                'Unsupported chat mode or adapter')
        if value['mode'] == 'orchestration':
            if value['adapter'] == 'ollama':
                require(value['model'] is None,
                        'Local task execution fixes the configured Ollama model')
            else:
                require(set(value) == core,
                        'External task execution cannot select an Ollama binding')
                _model(value['model'])
            if set(value) == selected and value['adapter'] == 'ollama':
                binding_id = value['binding_id']
                revision = value['binding_revision']
                uuid(binding_id)
                require(isinstance(revision, str) and revision.strip() == revision
                        and bool(revision) and len(revision.encode('utf-8')) <= 128,
                        'Invalid orchestration binding revision')
            else:
                binding_id = revision = None
        else:
            require(set(value) == core,
                    'Brainstorming cannot select an orchestration binding')
            _model(value['model'])
            binding_id = revision = None
        return cls(value['mode'], value['adapter'], value['model'], binding_id, revision)

    def resolve(self, *, ollama, openai=None, atlascloud=None):
        """Return an immutable run binding without changing saved configuration."""
        if self.mode == 'orchestration' and self.adapter_id == 'ollama':
            require(isinstance(ollama, OllamaBinding), 'Configured Ollama binding is required')
            if ollama.boundary == 'private-network':
                require(self.binding_id is not None,
                        'Private-network orchestration requires explicit Ollama binding selection')
            if self.binding_id is not None:
                require((self.binding_id, self.binding_revision) ==
                        (ollama.binding_id, ollama.revision),
                        'Selected orchestration binding changed')
            return ollama
        bases = {'ollama': ollama, 'openai-responses': openai,
                 'atlascloud-text': atlascloud}
        expected_types = {'ollama': OllamaBinding, 'openai-responses': OpenAIBinding,
                          'atlascloud-text': AtlasCloudBinding}
        base = bases[self.adapter_id]; expected = expected_types[self.adapter_id]
        require(isinstance(base, expected), 'Selected brainstorm backend is unavailable')
        if self.adapter_id == 'atlascloud-text':
            require(self.model == base.model,
                    'AtlasCloud run must use the exact bound offer model')
            return base
        value = base.serialize()
        value['model'] = self.model
        suffix = hashlib.sha256(self.model.encode('utf-8')).hexdigest()[:16]
        value['revision'] = base.revision + '.run-model-' + suffix
        return expected.parse(value)

    def validate_context(self, *, project_input_ids, text_input_ids):
        require(isinstance(project_input_ids, tuple) and isinstance(text_input_ids, tuple),
                'Chat context selections must be immutable tuples')
        require(all(isinstance(value, str) for value in project_input_ids + text_input_ids),
                'Invalid chat context selection')
        if self.mode == 'brainstorming' or self.adapter_id != 'ollama':
            require(not project_input_ids,
                    'This mode cannot include project artifact inputs')
        require(bool(project_input_ids or text_input_ids),
                'Chat run requires explicit context')
        return self
