# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import unittest

from spikes.metadata import ValidationError
from spikes.output_capabilities import OutputCapabilityCatalog, read_output_capability
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
        self.catalog = OutputCapabilityCatalog([web, transform])
        self.policy = {
            'schema_version': 1,
            'policy_id': 'output.local-preview',
            'revision': 'revision-1',
            'allowed_capabilities': [
                {'id': 'transform.markdown-set', 'version': '1.0'},
                {'id': 'renderer.web-static', 'version': '1.0'},
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


if __name__ == '__main__':
    unittest.main()
