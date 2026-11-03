# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.chat_modes import ChatRunChoice
from spikes.task_plan import ExplicitTaskPlan, task_output_instruction


class ExplicitTaskPlanTests(unittest.TestCase):
    def plan(self, **changes):
        value = {'schema_version': 1, 'source_kinds': ['conversation'],
                 'output_kind': 'conversation', 'execution': 'local-ollama',
                 'search_query': None, 'public_source_run_ids': []}
        value.update(changes)
        return ExplicitTaskPlan.parse(value)

    def test_exact_plan_deterministically_selects_one_output_role(self):
        plan = self.plan(source_kinds=['conversation', 'artifacts'],
                         output_kind='document')
        self.assertEqual(plan.expected_outcome_kind, 'artifact-draft')
        self.assertEqual(plan.role_revision, 'task-output-document-v1')
        self.assertEqual(plan.digest(), plan.digest())
        instruction = task_output_instruction(plan)
        self.assertIn('"kind":"artifact-draft"', instruction)
        self.assertNotIn('presentation-proposal', instruction)
        plan.validate_request_selections(artifact_ids=[str(uuid4())], message_ids=[])

    def test_web_requires_query_before_acquisition_or_explicit_runs_after(self):
        acquiring = self.plan(source_kinds=['public-web'], search_query='exact query')
        self.assertTrue(acquiring.acquiring_public_web)
        run_id = str(uuid4())
        loaded = self.plan(source_kinds=['conversation', 'public-web'],
                           search_query=None, public_source_run_ids=[run_id])
        self.assertFalse(loaded.acquiring_public_web)
        for changes in ({'source_kinds': ['public-web']},
                        {'source_kinds': ['conversation'], 'search_query': 'hidden'},
                        {'source_kinds': ['public-web'], 'search_query': None,
                         'public_source_run_ids': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**changes)

    def test_external_execution_rejects_artifacts_and_wrong_backend(self):
        with self.assertRaisesRegex(ValueError, 'project artifacts'):
            self.plan(source_kinds=['artifacts'], execution='external-openai')
        plan = self.plan(execution='external-openai')
        plan.validate_execution(ChatRunChoice.parse({
            'mode': 'brainstorming', 'adapter': 'openai-responses', 'model': 'gpt'}))
        with self.assertRaisesRegex(ValueError, 'selected backend'):
            plan.validate_execution(ChatRunChoice.parse({
                'mode': 'brainstorming', 'adapter': 'ollama', 'model': 'gemma'}))
        atlas = self.plan(execution='external-atlascloud')
        atlas.validate_execution(ChatRunChoice.parse({
            'mode': 'brainstorming', 'adapter': 'atlascloud-text',
            'model': 'deepseek-ai/deepseek-v3.2'}))
        with self.assertRaisesRegex(ValueError, 'selected backend'):
            atlas.validate_execution(ChatRunChoice.parse({
                'mode': 'brainstorming', 'adapter': 'openai-responses', 'model': 'gpt'}))

    def test_sources_are_canonical_and_match_actual_selections(self):
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.plan(source_kinds=['artifacts', 'conversation'])
        with self.assertRaisesRegex(ValueError, 'artifact selection'):
            self.plan().validate_request_selections(artifact_ids=[str(uuid4())],
                                                    message_ids=[])
        with self.assertRaisesRegex(ValueError, 'conversation selection'):
            self.plan(source_kinds=['artifacts']).validate_request_selections(
                artifact_ids=[str(uuid4())], message_ids=[str(uuid4())])

    def test_compose_plan_lets_any_backend_write_the_query_and_keeps_old_digests(self):
        plain = self.plan(); plan = self.plan(search_compose=True)
        self.assertTrue(plan.search_compose); self.assertNotEqual(plain.digest(), plan.digest())
        self.assertNotIn('search_compose', plain.serialize())
        self.assertEqual('task-output-search-query-v1', plan.role_revision)
        self.assertEqual(plan, ExplicitTaskPlan.parse(plan.serialize()))
        self.assertTrue(self.plan(search_compose=True, execution='external-openai').search_compose)
        for changes in (dict(search_compose=False), dict(output_kind='document'),
                        dict(search_on_demand=True),
                        dict(source_kinds=['conversation', 'public-web'], search_query='q')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**{'search_compose': True, **changes})

    def test_search_instructions_carry_date_and_forbid_copying_the_prompt(self):
        for plan in (self.plan(search_compose=True), self.plan(search_on_demand=True)):
            text = task_output_instruction(plan, '2026-11-03T10:00:00.000000Z')
            self.assertIn('Today is 2026-11-03.', text)
            self.assertIn('not a copy of the user message', text)
        self.assertIn('Never guess', task_output_instruction(self.plan(search_on_demand=True)))
        self.assertIn('Do not answer the task', task_output_instruction(self.plan(search_compose=True)))
        self.assertNotIn('Today is', task_output_instruction(self.plan()))

    def test_search_on_demand_is_local_conversation_only_and_keeps_old_digests(self):
        plain = self.plan(); plan = self.plan(search_on_demand=True)
        self.assertTrue(plan.search_on_demand); self.assertNotEqual(plain.digest(), plan.digest())
        self.assertNotIn('search_on_demand', plain.serialize())
        self.assertEqual('task-output-conversation-search-v1', plan.role_revision)
        self.assertIn('web-search-request', task_output_instruction(plan))
        self.assertEqual(plan, ExplicitTaskPlan.parse(plan.serialize()))
        for changes in (dict(search_on_demand=False), dict(output_kind='document'),
                        dict(execution='external-openai'),
                        dict(source_kinds=['conversation', 'public-web'], search_query='q')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**{'search_on_demand': True, **changes})


if __name__ == '__main__':
    unittest.main()
