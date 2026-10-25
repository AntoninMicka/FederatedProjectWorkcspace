# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.atlascloud_backend import AtlasCloudBinding
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
        self.atlascloud = AtlasCloudBinding.parse(dict(schema_version=1,
            binding_id=str(uuid4()), revision='atlas-one',
            adapter='atlascloud-responses', boundary='external-provider',
            endpoint='https://api.atlascloud.ai/v1/responses',
            model='deepseek-ai/deepseek-v3.2', target_id='api.atlascloud.ai',
            credential_ref='credential:atlascloud-primary', credential_revision=1,
            offer_id='atlascloud:deepseek-ai/deepseek-v3.2:responses',
            protocol='openai-responses-v1', knowledge_revision='review-v1',
            capabilities=['generate-text', 'json-output', 'streaming', 'text-output'],
            max_output_tokens=4096, timeout_seconds=180))

    def test_orchestration_accepts_exact_same_node_or_private_network_binding(self):
        choice = ChatRunChoice.parse(
            {'mode': 'orchestration', 'adapter': 'ollama', 'model': None})
        self.assertIs(choice.resolve(ollama=self.ollama), self.ollama)
        private = OllamaBinding.parse(dict(self.ollama.serialize(),
            boundary='private-network', endpoint='https://192.168.1.2:11434',
            target_id=str(uuid4()), tls_cert_sha256='a' * 64))
        with self.assertRaisesRegex(ValidationError, 'explicit'):
            choice.resolve(ollama=private)
        selected = ChatRunChoice.parse({'mode': 'orchestration', 'adapter': 'ollama',
            'model': None, 'binding_id': private.binding_id,
            'binding_revision': private.revision})
        self.assertIs(selected.resolve(ollama=private), private)
        changed = OllamaBinding.parse(dict(private.serialize(), revision='private-two'))
        with self.assertRaisesRegex(ValidationError, 'binding changed'):
            selected.resolve(ollama=changed)
        for value in (
            {'mode': 'orchestration', 'adapter': 'openai-responses', 'model': None},
            {'mode': 'orchestration', 'adapter': 'ollama', 'model': 'other'},
            {'mode': 'brainstorming', 'adapter': 'ollama', 'model': 'qwen3',
             'binding_id': private.binding_id, 'binding_revision': private.revision},
            {'mode': 'orchestration', 'adapter': 'ollama', 'model': None,
             'binding_id': None, 'binding_revision': private.revision},
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
        self.assertEqual(choice.resolve(ollama=None, openai=self.openai), selected)

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

    def test_atlascloud_choice_is_exact_and_does_not_fall_back(self):
        choice = ChatRunChoice.parse({'mode': 'brainstorming',
            'adapter': 'atlascloud-responses',
            'model': 'deepseek-ai/deepseek-v3.2'})
        selected = choice.resolve(ollama=None, atlascloud=self.atlascloud)
        self.assertEqual((selected.model, selected.adapter_id),
                         ('deepseek-ai/deepseek-v3.2', 'atlascloud-responses'))
        self.assertEqual(selected.offer_id, self.atlascloud.offer_id)
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            choice.resolve(ollama=None, openai=self.openai)


if __name__ == '__main__':
    unittest.main()
