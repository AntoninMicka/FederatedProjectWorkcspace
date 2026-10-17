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

    def test_sources_are_canonical_and_match_actual_selections(self):
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.plan(source_kinds=['artifacts', 'conversation'])
        with self.assertRaisesRegex(ValueError, 'artifact selection'):
            self.plan().validate_request_selections(artifact_ids=[str(uuid4())],
                                                    message_ids=[])
        with self.assertRaisesRegex(ValueError, 'conversation selection'):
            self.plan(source_kinds=['artifacts']).validate_request_selections(
                artifact_ids=[str(uuid4())], message_ids=[str(uuid4())])


if __name__ == '__main__':
    unittest.main()
