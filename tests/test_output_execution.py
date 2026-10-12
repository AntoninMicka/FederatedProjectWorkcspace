# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import base64
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.output_capabilities import OutputCapabilityCatalog, read_output_capability
from spikes.output_execution import OutputExecutor, digest
from spikes.output_plans import output_policy_sha256
from spikes.project_creation import ProjectCreation
from spikes.storage import Git


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / 'modules' / 'output-capabilities' / 'web-static.output-capability.json'
SCHEMA = 'module://workspace.output.web/schemas/ordered-sections-v1.json'


class OutputExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.node = self.base / 'node.json'; self.project = self.base / 'project'
        created = ProjectCreation(self.node).create(
            'Output project', str(self.project), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.project)
        self.artifact_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.artifact_id, base_head=self.git.head(), title='Section',
            body='# Heading\n\n<script>alert(1)</script>\n', new=True), str(uuid4()))
        self.state = self.base / 'output-state'; self.state.mkdir(mode=0o700)
        self.web = read_output_capability(DESCRIPTOR)
        self.catalog = OutputCapabilityCatalog([self.web])
        self.policy = self.make_policy([self.web])
        self.node_id, self.user_id = str(uuid4()), str(uuid4())

    @staticmethod
    def make_policy(descriptors):
        return {'schema_version': 1, 'policy_id': 'output.local-preview',
            'revision': 'revision-1',
            'allowed_capabilities': [{'id': item['capability_id'],
                                      'version': item['capability_version']}
                                     for item in descriptors],
            'permissions': sorted({permission for item in descriptors
                                   for permission in item['permissions']}),
            'privacy': ['public', 'project', 'confidential', 'local-only'],
            'execution_boundaries': ['same-process'],
            'cost_classes': ['local-compute'], 'side_effects': ['local']}

    def artifact_source(self):
        head = self.git.head()
        rows = self.git.run('ls-tree', '-r', head, '--',
                            f'artifacts/{self.artifact_id}/').stdout.splitlines()
        info, path = next(row.split('\t', 1) for row in rows
                          if not row.endswith('/metadata.json'))
        _, _, oid = info.split()
        raw = self.git.run('cat-file', 'blob', oid, binary=True).stdout
        return {'source_id': str(uuid4()), 'artifact_id': self.artifact_id,
            'project_commit': head, 'path': path, 'blob_id': oid,
            'sha256': digest(raw), 'size': len(raw), 'schema': SCHEMA,
            'mime_type': 'text/markdown', 'format': 'markdown-section',
            'privacy': 'project'}

    def plan(self, *, source=None, operation_id=None):
        source = self.artifact_source() if source is None else source
        plan_id, step_id = str(uuid4()), str(uuid4())
        plan = {'schema_version': 1, 'plan_id': plan_id,
            'project_id': self.project_id, 'project_commit': self.git.head(),
            'policy': {'id': self.policy['policy_id'],
                       'revision': self.policy['revision'],
                       'sha256': output_policy_sha256(self.policy)},
            'privacy': source['privacy'],
            'artifacts': [source] if 'artifact_id' in source else [],
            'materialized': [source] if 'producer_plan_id' in source else [],
            'steps': [{'step_id': step_id,
                'capability': {'id': 'renderer.web-static', 'version': '1.0'},
                'privacy': source['privacy'], 'inputs': [{
                    'input_port': 'sections',
                    'source_type': 'artifact' if 'artifact_id' in source else 'materialized',
                    'source_id': source['source_id']}]}], 'edges': []}
        return (str(uuid4()) if operation_id is None else operation_id), plan

    def executor(self, **changes):
        values = dict(git=self.git, state_dir=self.state,
                      catalog=self.catalog, policy=self.policy)
        values.update(changes)
        return OutputExecutor(**values)

    def test_preview_confirmation_execution_and_restart_are_hash_bound(self):
        operation_id, plan = self.plan(); before = self.git.head()
        executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        self.assertEqual(prepared['state'], 'prepared')
        self.assertIn('<script>alert(1)</script>', prepared['preview']['sources'][0]['text'])
        self.assertEqual(prepared['preview']['not_included'],
                         ['project-write', 'publication', 'external-effect'])
        with self.assertRaisesRegex(ValueError, 'confirmation differs'):
            executor.execute(operation_id, self.node_id, self.user_id, '0' * 64)
        completed = executor.execute(operation_id, self.node_id, self.user_id,
                                     prepared['approval_digest'])
        self.assertEqual(completed['state'], 'completed')
        self.assertEqual(self.git.head(), before)
        output, receipt = executor.cache.load_generation(
            operation_id, plan['steps'][0]['step_id'])
        bundle = json.loads(output)
        html = base64.b64decode(bundle['files'][0]['content_b64']).decode()
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertEqual(receipt, completed['steps'][0]['receipt'])
        restarted = self.executor().store.get(operation_id, self.node_id, self.user_id)
        self.assertEqual(restarted['receipt'], completed['receipt'])

    def test_changed_head_after_preview_fails_before_dispatch(self):
        operation_id, plan = self.plan(); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.artifact_id, base_head=self.git.head(), title='Section',
            body='Changed.\n', new=False), str(uuid4()))
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'])
        stored = executor.store.get(operation_id, self.node_id, self.user_id)
        self.assertEqual((stored['state'], stored['steps'][0]['state']),
                         ('prepared', 'pending'))

    def test_interruption_before_output_becomes_unknown_without_retry(self):
        operation_id, plan = self.plan(); calls = []
        def renderer(inputs, descriptor):
            calls.append(1)
            return b'not reached'
        executor = self.executor(renderers={('renderer.web-static', '1.0'): renderer})
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        def checkpoint(stage):
            if stage == 'step-dispatching':
                raise RuntimeError('simulated crash')
        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'], checkpoint)
        self.assertEqual(calls, [])
        recovered = self.executor().reconcile(operation_id, self.node_id, self.user_id)
        self.assertEqual((recovered['state'], recovered['steps'][0]['state']),
                         ('unknown', 'unknown'))
        with self.assertRaisesRegex(ValueError, 'already terminal'):
            self.executor().execute(operation_id, self.node_id, self.user_id,
                                    prepared['approval_digest'])

    def test_published_generation_is_reconciled_without_second_render(self):
        operation_id, plan = self.plan(); calls = []
        from spikes.output_renderers import render_web_static
        def renderer(inputs, descriptor):
            calls.append(1); return render_web_static(inputs, descriptor)
        executor = self.executor(renderers={('renderer.web-static', '1.0'): renderer})
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        def checkpoint(stage):
            if stage == 'materialization-published':
                raise RuntimeError('simulated crash')
        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'], checkpoint)
        self.assertEqual(calls, [1])
        restarted = self.executor(renderers={('renderer.web-static', '1.0'): renderer})
        reconciled = restarted.reconcile(operation_id, self.node_id, self.user_id)
        self.assertEqual(reconciled['steps'][0]['state'], 'completed')
        completed = restarted.execute(operation_id, self.node_id, self.user_id,
                                      prepared['approval_digest'])
        self.assertEqual(completed['state'], 'completed')
        self.assertEqual(calls, [1])

    def test_renderer_failure_is_known_and_blocks_downstream(self):
        transform = deepcopy(self.web)
        transform.update({'capability_id': 'transform.markdown-set',
            'kind': 'transformation', 'output_kind': 'data',
            'display_name': 'Markdown transform',
            'description': 'Freeze selected sections.'})
        transform['output'] = {'port_id': 'sections-output', 'schema': SCHEMA,
                               'mime_types': ['text/markdown'],
                               'format': 'markdown-section'}
        catalog = OutputCapabilityCatalog([transform, self.web])
        policy = self.make_policy([transform, self.web])
        source = self.artifact_source(); first, second, edge = (str(uuid4()) for _ in range(3))
        plan = {'schema_version': 1, 'plan_id': str(uuid4()),
            'project_id': self.project_id, 'project_commit': self.git.head(),
            'policy': {'id': policy['policy_id'], 'revision': policy['revision'],
                       'sha256': output_policy_sha256(policy)}, 'privacy': 'project',
            'artifacts': [source], 'materialized': [],
            'steps': [{'step_id': first,
                'capability': {'id': 'transform.markdown-set', 'version': '1.0'},
                'privacy': 'project', 'inputs': [{'input_port': 'sections',
                    'source_type': 'artifact', 'source_id': source['source_id']}]},
                {'step_id': second,
                 'capability': {'id': 'renderer.web-static', 'version': '1.0'},
                 'privacy': 'project', 'inputs': [{'input_port': 'sections',
                    'source_type': 'edge', 'source_id': edge}]}],
            'edges': [{'edge_id': edge, 'from_step_id': first,
                'from_port': 'sections-output', 'to_step_id': second,
                'to_port': 'sections', 'schema': SCHEMA, 'mime_type': 'text/markdown',
                'format': 'markdown-section', 'privacy': 'project'}]}
        def fail(inputs, descriptor):
            raise RuntimeError('renderer failed after dispatch')
        executor = OutputExecutor(git=self.git, state_dir=self.state, catalog=catalog,
            policy=policy, renderers={('transform.markdown-set', '1.0'): fail})
        operation_id = str(uuid4())
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        with self.assertRaisesRegex(RuntimeError, 'renderer failed'):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'])
        result = executor.store.get(operation_id, self.node_id, self.user_id)
        self.assertEqual([item['state'] for item in result['steps']],
                         ['failed', 'blocked'])
        self.assertEqual(result['state'], 'failed')

    def test_exact_prior_materialization_can_be_used_as_input(self):
        executor = self.executor(); prior_operation, prior_step = str(uuid4()), str(uuid4())
        prior_plan, raw = str(uuid4()), b'# Prior materialized section\n'
        prior_plan_hash = 'a' * 64
        receipt = {'schema_version': 1, 'operation_id': prior_operation,
            'plan_id': prior_plan, 'plan_sha256': prior_plan_hash,
            'step_id': prior_step, 'manifest_sha256': 'b' * 64,
            'output_port': 'sections-output', 'output_sha256': digest(raw),
            'output_size': len(raw), 'contract': {'schema': SCHEMA,
                'mime_type': 'text/markdown', 'format': 'markdown-section',
                'privacy': 'confidential'}, 'completed_at': '2026-10-12T12:00:00Z'}
        executor.cache.publish(prior_operation, prior_step, raw, receipt)
        source = {'source_id': prior_operation, 'producer_plan_id': prior_plan,
            'producer_plan_sha256': prior_plan_hash, 'producer_step_id': prior_step,
            'producer_output_port': 'sections-output', 'sha256': digest(raw),
            'size': len(raw), 'schema': SCHEMA, 'mime_type': 'text/markdown',
            'format': 'markdown-section', 'privacy': 'confidential'}
        operation_id, plan = self.plan(source=source)
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        completed = executor.execute(operation_id, self.node_id, self.user_id,
                                     prepared['approval_digest'])
        self.assertEqual(completed['state'], 'completed')

    def test_same_operation_is_idempotent_but_cannot_change_request(self):
        operation_id, plan = self.plan(); executor = self.executor()
        first = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        second = executor.prepare(operation_id, self.node_id, self.user_id, deepcopy(plan))
        self.assertEqual(first['approval_digest'], second['approval_digest'])
        changed = deepcopy(plan); changed['steps'][0]['privacy'] = 'confidential'
        with self.assertRaises(ValueError):
            executor.prepare(operation_id, self.node_id, self.user_id, changed)

    def test_policy_or_reviewed_descriptor_change_invalidates_preview(self):
        operation_id, plan = self.plan(); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        changed_policy = deepcopy(self.policy)
        changed_policy['revision'] = 'revision-2'
        with self.assertRaises(ValueError):
            OutputExecutor(git=self.git, state_dir=self.state, catalog=self.catalog,
                policy=changed_policy).execute(operation_id, self.node_id, self.user_id,
                                               prepared['approval_digest'])
        changed_descriptor = deepcopy(self.web)
        changed_descriptor['description'] = 'A separately reviewed implementation.'
        changed_catalog = OutputCapabilityCatalog([changed_descriptor])
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            OutputExecutor(git=self.git, state_dir=self.state, catalog=changed_catalog,
                policy=self.policy).execute(operation_id, self.node_id, self.user_id,
                                            prepared['approval_digest'])
        self.assertEqual(executor.store.get(operation_id, self.node_id,
                                            self.user_id)['state'], 'prepared')

    def test_materialization_tampering_is_rejected(self):
        operation_id, plan = self.plan(); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id, plan)
        executor.execute(operation_id, self.node_id, self.user_id,
                         prepared['approval_digest'])
        path = (self.state / 'output-materializations' / operation_id /
                plan['steps'][0]['step_id'] / 'output.bin')
        path.write_bytes(path.read_bytes() + b'tampered')
        path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'differs from its receipt'):
            executor.cache.load_generation(operation_id, plan['steps'][0]['step_id'])


if __name__ == '__main__':
    unittest.main()
