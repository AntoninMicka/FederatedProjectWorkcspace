# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.chat_modes import ChatRunChoice
from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaBinding
from spikes.openai_backend import OpenAIBinding


class ChatModePolicyTests(unittest.TestCase):
    def setUp(self):
        self.ollama = OllamaBinding.parse(dict(schema_version=1,
            binding_id=str(uuid4()), revision='local-one', adapter='ollama',
            boundary='same-node', endpoint='http://127.0.0.1:11434',
            model='gemma3', target_id='local-process'))
        self.openai = OpenAIBinding.parse(dict(schema_version=1,
            binding_id=str(uuid4()), revision='external-one',
            adapter='openai-responses', boundary='external-provider',
            endpoint='https://api.openai.com/v1/responses', model='gpt-5.6-luna',
            target_id='api.openai.com', credential_ref='credential:test',
            credential_revision=1, max_output_tokens=4096, timeout_seconds=180))

    def test_orchestration_requires_configured_same_node_model(self):
        choice = ChatRunChoice.parse(
            {'mode': 'orchestration', 'adapter': 'ollama', 'model': None})
        self.assertIs(choice.resolve(ollama=self.ollama), self.ollama)
        private = OllamaBinding.parse(dict(self.ollama.serialize(),
            boundary='private-network', endpoint='https://192.168.1.2:11434',
            target_id=str(uuid4()), tls_cert_sha256='a' * 64))
        with self.assertRaisesRegex(ValidationError, 'same-node'):
            choice.resolve(ollama=private)
        for value in (
            {'mode': 'orchestration', 'adapter': 'openai-responses', 'model': None},
            {'mode': 'orchestration', 'adapter': 'ollama', 'model': 'other'},
        ):
            with self.assertRaises(ValidationError):
                ChatRunChoice.parse(value)

    def test_brainstorm_model_is_per_run_and_does_not_mutate_base(self):
        choice = ChatRunChoice.parse(
            {'mode': 'brainstorming', 'adapter': 'openai-responses', 'model': 'gpt-5.6-sol'})
        selected = choice.resolve(ollama=self.ollama, openai=self.openai)
        self.assertEqual(selected.model, 'gpt-5.6-sol')
        self.assertNotEqual(selected.revision, self.openai.revision)
        self.assertEqual(selected.credential_ref, self.openai.credential_ref)
        self.assertEqual(self.openai.model, 'gpt-5.6-luna')
        self.assertEqual(choice.resolve(ollama=self.ollama, openai=self.openai), selected)

    def test_brainstorm_allows_text_but_rejects_artifacts(self):
        choice = ChatRunChoice.parse(
            {'mode': 'brainstorming', 'adapter': 'ollama', 'model': 'qwen3'})
        choice.validate_context(project_input_ids=(), text_input_ids=('prepared-text',))
        selected = choice.resolve(ollama=self.ollama)
        self.assertEqual((selected.model, self.ollama.model), ('qwen3', 'gemma3'))
        with self.assertRaisesRegex(ValidationError, 'artifact'):
            choice.validate_context(project_input_ids=('artifact-id',),
                                    text_input_ids=('prepared-text',))
        with self.assertRaisesRegex(ValidationError, 'explicit context'):
            choice.validate_context(project_input_ids=(), text_input_ids=())


if __name__ == '__main__':
    unittest.main()
