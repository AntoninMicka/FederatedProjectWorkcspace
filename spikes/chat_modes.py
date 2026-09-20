# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed chat-mode policy and immutable per-run backend selection."""
from dataclasses import dataclass
import hashlib

from spikes.metadata import require
from spikes.ollama_backend import OllamaBinding
from spikes.openai_backend import OpenAIBinding


MODES = frozenset({'orchestration', 'brainstorming'})
ADAPTERS = frozenset({'ollama', 'openai-responses'})


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

    @classmethod
    def parse(cls, value):
        require(isinstance(value, dict) and set(value) == {'mode', 'adapter', 'model'},
                'Unknown or missing chat run choice field')
        require(value['mode'] in MODES and value['adapter'] in ADAPTERS,
                'Unsupported chat mode or adapter')
        if value['mode'] == 'orchestration':
            require(value['adapter'] == 'ollama' and value['model'] is None,
                    'Orchestration fixes the configured local model')
        else:
            _model(value['model'])
        return cls(value['mode'], value['adapter'], value['model'])

    def resolve(self, *, ollama, openai=None):
        """Return an immutable run binding without changing saved configuration."""
        require(isinstance(ollama, OllamaBinding), 'Configured Ollama binding is required')
        if self.mode == 'orchestration':
            require(ollama.boundary == 'same-node',
                    'Orchestration requires same-node Ollama')
            return ollama
        base = ollama if self.adapter_id == 'ollama' else openai
        expected = OllamaBinding if self.adapter_id == 'ollama' else OpenAIBinding
        require(isinstance(base, expected), 'Selected brainstorm backend is unavailable')
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
        if self.mode == 'brainstorming':
            require(not project_input_ids,
                    'Brainstorming cannot include project artifact inputs')
        require(bool(project_input_ids or text_input_ids),
                'Chat run requires explicit context')
        return self
