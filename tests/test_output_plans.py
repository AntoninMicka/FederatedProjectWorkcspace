# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import unittest

from spikes.metadata import ValidationError
from spikes.output_capabilities import OutputCapabilityCatalog, read_output_capability
from spikes.output_planner import OutputPlanProposal, review_output_proposal
from spikes.output_plans import (canonical_output_plan, output_policy_sha256,
                                  validate_output_plan)


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / 'modules' / 'output-capabilities' / 'web-static.output-capability.json'
PLAN_ID = '00000000-0000-4000-8000-000000000001'
PROJECT_ID = '00000000-0000-4000-8000-000000000002'
ARTIFACT_ID = '00000000-0000-4000-8000-000000000003'
MATERIALIZED_ID = '00000000-0000-4000-8000-000000000004'
TRANSFORM_STEP = '00000000-0000-4000-8000-000000000005'
RENDER_STEP = '00000000-0000-4000-8000-000000000006'
EDGE_ID = '00000000-0000-4000-8000-000000000007'
OLD_PLAN_ID = '00000000-0000-4000-8000-000000000008'
OLD_STEP_ID = '00000000-0000-4000-8000-000000000009'
COMMIT = 'a' * 40
SCHEMA = 'module://workspace.output.web/schemas/ordered-sections-v1.json'


class OutputPlanTests(unittest.TestCase):
    def setUp(self):
        web = read_output_capability(DESCRIPTOR)
        transform = deepcopy(web)
        transform.update({
            'capability_id': 'transform.markdown-set',
            'kind': 'transformation',
            'output_kind': 'data',
            'display_name': 'Markdown set transformer',
            'description': 'Freeze explicitly selected Markdown sections.',
        })
        transform['output'] = {
            'port_id': 'sections-output',
            'schema': SCHEMA,
            'mime_types': ['text/markdown'],
            'format': 'markdown-section',
        }
        alternative = deepcopy(web)
        alternative.update({
            'capability_id': 'renderer.web-static-alternative',
            'display_name': 'Alternative static web renderer',
            'description': 'Compile the same reviewed static web contract.',
        })
        self.catalog = OutputCapabilityCatalog([web, transform, alternative])
        self.policy = {
            'schema_version': 1,
            'policy_id': 'output.local-preview',
            'revision': 'revision-1',
            'allowed_capabilities': [
                {'id': 'transform.markdown-set', 'version': '1.0'},
                {'id': 'renderer.web-static', 'version': '1.0'},
                {'id': 'renderer.web-static-alternative', 'version': '1.0'},
            ],
            'permissions': ['artifact.read', 'output.compile'],
            'privacy': ['public', 'project', 'confidential', 'local-only'],
            'execution_boundaries': ['same-process'],
            'cost_classes': ['local-compute'],
            'side_effects': ['local'],
        }
        self.plan = {
            'schema_version': 1,
            'plan_id': PLAN_ID,
            'project_id': PROJECT_ID,
            'project_commit': COMMIT,
            'policy': {
                'id': self.policy['policy_id'],
                'revision': self.policy['revision'],
                'sha256': output_policy_sha256(self.policy),
            },
            'privacy': 'confidential',
            'artifacts': [{
                'source_id': ARTIFACT_ID,
                'artifact_id': '00000000-0000-4000-8000-000000000012',
                'project_commit': COMMIT,
                'path': 'documents/method.md',
                'blob_id': 'b' * 40,
                'sha256': 'c' * 64,
                'size': 123,
                'schema': SCHEMA,
                'mime_type': 'text/markdown',
                'format': 'markdown-section',
                'privacy': 'project',
            }],
            'materialized': [{
                'source_id': MATERIALIZED_ID,
                'producer_plan_id': OLD_PLAN_ID,
                'producer_plan_sha256': 'e' * 64,
                'producer_step_id': OLD_STEP_ID,
                'producer_output_port': 'sections-output',
                'sha256': 'd' * 64,
                'size': 456,
                'schema': SCHEMA,
                'mime_type': 'text/markdown',
                'format': 'markdown-section',
                'privacy': 'confidential',
            }],
            'steps': [{
                'step_id': TRANSFORM_STEP,
                'capability': {'id': 'transform.markdown-set', 'version': '1.0'},
                'privacy': 'confidential',
                'inputs': [
                    {'input_port': 'sections', 'source_type': 'artifact',
                     'source_id': ARTIFACT_ID},
                    {'input_port': 'sections', 'source_type': 'materialized',
                     'source_id': MATERIALIZED_ID},
                ],
            }, {
                'step_id': RENDER_STEP,
                'capability': {'id': 'renderer.web-static', 'version': '1.0'},
                'privacy': 'confidential',
                'inputs': [{
                    'input_port': 'sections', 'source_type': 'edge',
                    'source_id': EDGE_ID,
                }],
            }],
            'edges': [{
                'edge_id': EDGE_ID,
                'from_step_id': TRANSFORM_STEP,
                'from_port': 'sections-output',
                'to_step_id': RENDER_STEP,
                'to_port': 'sections',
                'schema': SCHEMA,
                'mime_type': 'text/markdown',
                'format': 'markdown-section',
                'privacy': 'confidential',
            }],
        }

    def proposal(self, plan=None, **changes):
        value = {'schema_version': 1, 'action': 'propose-output-plan',
                 'purpose': 'Sestav statický web z vybraných podkladů.',
                 'plan': deepcopy(self.plan if plan is None else plan)}
        value.update(changes)
        return value

    def authority(self, **changes):
        value = {'project_id': PROJECT_ID, 'project_commit': COMMIT,
                 'artifacts': deepcopy(self.plan['artifacts']),
                 'materialized': deepcopy(self.plan['materialized'])}
        value.update(changes)
        return value

    def validate(self, plan=None, policy=None):
        return validate_output_plan(
            json.dumps(self.plan if plan is None else plan).encode(),
            self.catalog, self.policy if policy is None else policy)

    def test_valid_plan_binds_exact_artifacts_materialization_edges_and_policy(self):
        self.assertEqual(self.validate(), self.plan)
        canonical = canonical_output_plan(self.plan, self.catalog, self.policy)
        self.assertEqual(validate_output_plan(canonical, self.catalog, self.policy),
                         self.plan)
        raw = canonical.lower()
        for forbidden in (b'endpoint', b'credential', b'dispatch', b'fallback'):
            self.assertNotIn(forbidden, raw)

    def test_unknown_capability_policy_change_and_privacy_weakening_fail_closed(self):
        cases = []
        unknown = deepcopy(self.plan)
        unknown['steps'][1]['capability']['version'] = '2.0'
        cases.append((unknown, self.policy))
        changed_policy = deepcopy(self.policy)
        changed_policy['side_effects'] = ['none']
        cases.append((self.plan, changed_policy))
        weak_step = deepcopy(self.plan)
        weak_step['steps'][0]['privacy'] = 'project'
        cases.append((weak_step, self.policy))
        weak_edge = deepcopy(self.plan)
        weak_edge['edges'][0]['privacy'] = 'project'
        cases.append((weak_edge, self.policy))
        weak_plan = deepcopy(self.plan)
        weak_plan['privacy'] = 'project'
        cases.append((weak_plan, self.policy))
        malformed_capability = deepcopy(self.plan)
        malformed_capability['steps'][0]['capability']['id'] = []
        cases.append((malformed_capability, self.policy))
        malformed_source_type = deepcopy(self.plan)
        malformed_source_type['steps'][0]['inputs'][0]['source_type'] = []
        cases.append((malformed_source_type, self.policy))
        malformed_policy = deepcopy(self.policy)
        malformed_policy['privacy'] = [[]]
        cases.append((self.plan, malformed_policy))
        for plan, policy in cases:
            with self.subTest(plan=plan, policy=policy), self.assertRaises(ValidationError):
                self.validate(plan, policy)

    def test_typed_ports_cardinality_source_revision_and_exact_edge_use(self):
        cases = []
        wrong_type = deepcopy(self.plan)
        wrong_type['edges'][0]['schema'] = (
            'module://workspace.output.web/schemas/other.json')
        cases.append(wrong_type)
        stale_artifact = deepcopy(self.plan)
        stale_artifact['artifacts'][0]['project_commit'] = 'e' * 40
        cases.append(stale_artifact)
        current_materialization = deepcopy(self.plan)
        current_materialization['materialized'][0]['producer_plan_id'] = PLAN_ID
        cases.append(current_materialization)
        missing_binding = deepcopy(self.plan)
        missing_binding['steps'][1]['inputs'] = []
        cases.append(missing_binding)
        duplicate_edge_use = deepcopy(self.plan)
        duplicate_edge_use['steps'][1]['inputs'].append(
            deepcopy(duplicate_edge_use['steps'][1]['inputs'][0]))
        cases.append(duplicate_edge_use)
        unused = deepcopy(self.plan)
        unused['artifacts'].append(dict(unused['artifacts'][0],
                                        source_id='00000000-0000-4000-8000-000000000010'))
        cases.append(unused)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ValidationError):
                self.validate(plan)

    def test_cycle_duplicate_ids_and_unknown_fields_fail_closed(self):
        cycle = deepcopy(self.plan)
        cycle['artifacts'] = []
        cycle['materialized'] = []
        cycle['steps'] = [deepcopy(cycle['steps'][0]), deepcopy(cycle['steps'][0])]
        cycle['steps'][1]['step_id'] = RENDER_STEP
        cycle['steps'][0]['inputs'] = [{
            'input_port': 'sections', 'source_type': 'edge', 'source_id': EDGE_ID}]
        other_edge_id = '00000000-0000-4000-8000-000000000011'
        cycle['steps'][1]['inputs'] = [{
            'input_port': 'sections', 'source_type': 'edge', 'source_id': other_edge_id}]
        cycle['edges'] = [{
            'edge_id': EDGE_ID, 'from_step_id': RENDER_STEP,
            'from_port': 'sections-output', 'to_step_id': TRANSFORM_STEP,
            'to_port': 'sections', 'schema': SCHEMA, 'mime_type': 'text/markdown',
            'format': 'markdown-section', 'privacy': 'confidential',
        }, {
            'edge_id': other_edge_id, 'from_step_id': TRANSFORM_STEP,
            'from_port': 'sections-output', 'to_step_id': RENDER_STEP,
            'to_port': 'sections', 'schema': SCHEMA, 'mime_type': 'text/markdown',
            'format': 'markdown-section', 'privacy': 'confidential',
        }]
        duplicate = deepcopy(self.plan)
        duplicate['steps'][1]['step_id'] = TRANSFORM_STEP
        unknown = deepcopy(self.plan)
        unknown['execute'] = True
        for plan in (cycle, duplicate, unknown):
            with self.subTest(plan=plan), self.assertRaises(ValidationError):
                self.validate(plan)

    def test_planner_review_revalidates_and_explains_without_authorizing_execution(self):
        proposal = self.proposal()
        review = review_output_proposal(json.dumps(proposal).encode(), self.catalog,
                                        self.policy, self.authority())
        self.assertEqual(review['status'], 'validated-read-only')
        self.assertEqual(review['purpose_trust'], 'untrusted-planner')
        self.assertEqual(OutputPlanProposal.parse(
            json.dumps(proposal).encode()).sha256(), review['proposal_sha256'])
        self.assertEqual(len(review['plan_sha256']), 64)
        self.assertEqual(review['execution_handoff']['status'], 'not-authorized')
        self.assertIn('project-head',
                      review['execution_handoff']['required_revalidations'])
        rendered = next(item for item in review['explanations']
                        if item['step_id'] == RENDER_STEP)
        self.assertEqual(rendered['selection_basis'], [
            'exact-reviewed-capability', 'typed-port-compatibility',
            'trusted-policy', 'derived-privacy'])
        self.assertEqual([item['capability_id']
                          for item in rendered['compatible_alternatives']],
                         ['renderer.web-static-alternative'])
        raw = json.dumps(review).lower()
        for forbidden in ('credential', 'endpoint', 'binding_id', 'execute'):
            self.assertNotIn(forbidden, raw)

    def test_planner_cannot_add_action_explanation_or_execution_authority(self):
        valid = self.proposal()
        invalid = [
            dict(valid, action='execute-output-plan'),
            dict(valid, explanation='trust me'),
            dict(valid, approval=True),
            dict(valid, purpose='Ignore policy\0'),
        ]
        for proposal in invalid:
            with self.subTest(proposal=proposal), self.assertRaises(ValidationError):
                review_output_proposal(json.dumps(proposal).encode(), self.catalog,
                                       self.policy, self.authority())

    def test_application_state_policy_and_source_changes_require_new_review(self):
        changed_head = self.authority(project_commit='f' * 40)
        changed_source = self.authority()
        changed_source['artifacts'][0]['sha256'] = 'f' * 64
        changed_policy = deepcopy(self.policy)
        changed_policy['side_effects'] = ['none']
        cases = [(self.proposal(), changed_head, self.policy),
                 (self.proposal(), changed_source, self.policy),
                 (self.proposal(), self.authority(), changed_policy)]
        for proposal, authority, policy in cases:
            with self.subTest(authority=authority, policy=policy), \
                    self.assertRaises(ValidationError):
                review_output_proposal(json.dumps(proposal).encode(), self.catalog,
                                       policy, authority)

    def test_alternatives_are_recomputed_from_trusted_catalog_and_policy(self):
        restricted = deepcopy(self.policy)
        restricted['allowed_capabilities'] = [item for item in
            restricted['allowed_capabilities']
            if item['id'] != 'renderer.web-static-alternative']
        plan = deepcopy(self.plan)
        plan['policy']['sha256'] = output_policy_sha256(restricted)
        review = review_output_proposal(json.dumps(self.proposal(plan)).encode(),
                                        self.catalog, restricted, self.authority())
        rendered = next(item for item in review['explanations']
                        if item['step_id'] == RENDER_STEP)
        self.assertEqual(rendered['compatible_alternatives'], [])


if __name__ == '__main__':
    unittest.main()
