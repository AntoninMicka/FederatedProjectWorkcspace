# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.action_autonomy import (ActionRegistry, AutonomyQueue, UnknownEffect,
    digest, load_action_registry, parse_action_descriptor, parse_plan)
from spikes.metadata import ValidationError


class ActionAutonomyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name); self.state.chmod(0o700)
        self.registry = load_action_registry()
        self.node_id, self.user_id = str(uuid4()), str(uuid4())
        self.project_id, self.workflow_id = str(uuid4()), str(uuid4())
        self.head = 'a' * 40
        self.calls = []
        def handler(name):
            def invoke(value):
                self.calls.append((name, value)); return {'kind': name, 'ok': True}
            return invoke
        self.handlers = {
            ('analysis.read-only', '1.0'): handler('analysis'),
            ('query.external', '1.0'): handler('external'),
            ('workflow.role-handoff', '1.0'): handler('handoff'),
            ('artifact.create-local', '1.0'): handler('artifact'),
        }

    def step(self, action_id, inputs, *, privacy='project', cost=1, depends=None):
        return {'step_id': str(uuid4()),
            'action': {'id': action_id, 'version': '1.0'},
            'privacy': privacy, 'cost_units': cost,
            'depends_on': list(depends or []), 'input': inputs}

    def plan(self, steps, *, mode='automatic', workflow_id=None, privacy='project',
             max_cost=10000):
        return {'schema_version': 1,
            'workflow_id': workflow_id or self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.head,
            'mode': mode, 'privacy': privacy,
            'budget': {'max_steps': 16, 'max_cost_units': max_cost,
                       'max_seconds': 3600}, 'steps': steps}

    def queue(self, handlers=None):
        return AutonomyQueue(self.state, self.registry,
                             self.handlers if handlers is None else handlers)

    def advance(self, queue, workflow_id=None):
        return queue.advance(workflow_id or self.workflow_id,
            self.node_id, self.user_id,
            permissions={'project-read', 'external-dispatch', 'role-dispatch',
                         'project-write'},
            allowed_privacy={'public', 'project', 'confidential', 'local-only'},
            expected_head=self.head)

    def prepare_and_activate(self, queue, plan):
        proposed = queue.prepare(plan, self.node_id, self.user_id)
        self.assertEqual(proposed['state'], 'proposed')
        queue.attach_ui(plan['workflow_id'], self.node_id, self.user_id)
        return queue.activate(plan['workflow_id'], self.node_id, self.user_id,
                              proposed['activation_digest'])

    def test_reviewed_registry_is_strict_copy_safe_and_unknown_fails_closed(self):
        actions = self.registry.list()
        self.assertEqual([item['action_id'] for item in actions],
            ['analysis.read-only', 'artifact.create-local', 'query.external',
             'workflow.role-handoff'])
        actions[0]['permissions'].append('changed')
        self.assertNotIn('changed', self.registry.resolve(
            'analysis.read-only', '1.0')['permissions'])
        with self.assertRaises(ValidationError):
            self.registry.resolve('planner.invented', '1.0')
        local = self.registry.resolve('artifact.create-local', '1.0')
        local['confirmation'] = 'none'; local['automatable'] = True
        with self.assertRaisesRegex(ValidationError, 'exact output confirmation'):
            parse_action_descriptor(json.dumps(local).encode())
        with self.assertRaises(ValidationError):
            ActionRegistry([dict(self.registry.list()[0], endpoint='secret')])

    def test_automatic_mode_is_only_a_proposal_until_exact_opt_in(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); proposed = queue.prepare(self.plan([step]),
            self.node_id, self.user_id)
        queue.attach_ui(self.workflow_id, self.node_id, self.user_id)
        with self.assertRaisesRegex(ValidationError, 'not runnable'):
            self.advance(queue)
        with self.assertRaisesRegex(ValidationError, 'differs'):
            queue.activate(self.workflow_id, self.node_id, self.user_id, '0' * 64)
        activated = queue.activate(self.workflow_id, self.node_id, self.user_id,
                                   proposed['activation_digest'])
        self.assertEqual(activated['state'], 'queued')
        self.assertIsNotNone(activated['activated_at'])

    def test_independent_workflows_keep_separate_budget_and_results(self):
        queue = self.queue(); second_id = str(uuid4())
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64}, cost=2)
        second = self.step('analysis.read-only', {'selection_sha256': '2' * 64}, cost=3)
        self.prepare_and_activate(queue, self.plan([first], max_cost=2))
        self.prepare_and_activate(queue, self.plan([second], workflow_id=second_id,
                                                   max_cost=3))
        one = self.advance(queue)
        two = self.advance(queue, second_id)
        self.assertEqual((one['spent_cost'], two['spent_cost']), (2, 3))
        self.assertNotEqual(one['steps'][0]['result'], None)
        self.assertNotEqual(two['steps'][0]['result'], None)

    def test_combined_automatic_workflow_stops_for_external_and_each_local_output(self):
        analysis = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        external = self.step('query.external',
            {'request_sha256': '2' * 64, 'target': 'reviewed-provider'},
            privacy='public', depends=[analysis['step_id']])
        handoff = self.step('workflow.role-handoff',
            {'handoff_sha256': '3' * 64, 'role': 'opponent'},
            depends=[external['step_id']])
        output = self.step('artifact.create-local', {'target': 'artifacts/new/content.md',
            'content_type': 'text/markdown', 'content_sha256': '4' * 64,
            'privacy': 'project', 'provenance': {'workflow_id': self.workflow_id}},
            depends=[handoff['step_id']])
        queue = self.queue(); self.prepare_and_activate(queue, self.plan(
            [analysis, external, handoff, output], privacy='public'))
        result = self.advance(queue)
        self.assertEqual((result['steps'][0]['state'], self.calls[0][0]),
                         ('completed', 'analysis'))
        result = self.advance(queue)
        self.assertEqual(result['steps'][1]['state'], 'awaiting-approval')
        self.assertEqual(len(self.calls), 1)
        queue.approve(self.workflow_id, external['step_id'], self.node_id, self.user_id)
        self.advance(queue); self.advance(queue)
        result = self.advance(queue)
        self.assertEqual(result['steps'][3]['state'], 'awaiting-approval')
        self.assertEqual([name for name, _ in self.calls],
                         ['analysis', 'external', 'handoff'])
        approval = queue.approve(self.workflow_id, output['step_id'],
                                 self.node_id, self.user_id)
        self.assertRegex(approval['steps'][3]['approval_digest'], r'^[0-9a-f]{64}$')
        self.advance(queue); result = self.advance(queue)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual([name for name, _ in self.calls][-1], 'artifact')

    def test_manual_mode_requires_approval_even_for_read_only_action(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(
            queue, self.plan([step], mode='manual'))
        result = self.advance(queue)
        self.assertEqual(result['steps'][0]['state'], 'awaiting-approval')
        self.assertEqual(self.calls, [])
        queue.approve(self.workflow_id, step['step_id'], self.node_id, self.user_id)
        self.advance(queue)
        self.assertEqual(len(self.calls), 1)

    def test_detach_global_pause_permissions_privacy_and_head_fail_closed(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(queue, self.plan([step]))
        queue.detach_ui(self.workflow_id, self.node_id, self.user_id)
        with self.assertRaisesRegex(ValidationError, 'not runnable'):
            self.advance(queue)
        queue.attach_ui(self.workflow_id, self.node_id, self.user_id)
        queue.resume(self.workflow_id, self.node_id, self.user_id)
        queue.pause_all()
        with self.assertRaisesRegex(ValidationError, 'globally paused'):
            queue.resume(self.workflow_id, self.node_id, self.user_id)
        queue.resume_all(); queue.resume(self.workflow_id, self.node_id, self.user_id)
        with self.assertRaisesRegex(ValidationError, 'permissions'):
            queue.advance(self.workflow_id, self.node_id, self.user_id,
                permissions=set(), allowed_privacy={'project'}, expected_head=self.head)
        with self.assertRaisesRegex(ValidationError, 'privacy'):
            queue.advance(self.workflow_id, self.node_id, self.user_id,
                permissions={'project-read'}, allowed_privacy={'public'},
                expected_head=self.head)
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            queue.advance(self.workflow_id, self.node_id, self.user_id,
                permissions={'project-read'}, allowed_privacy={'project'},
                expected_head='b' * 40)

    def test_restart_pauses_queued_work_and_marks_dispatching_unknown(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(queue, self.plan([step]))
        restarted = self.queue()
        result = restarted.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((result['state'], result['ui_attached']), ('paused', False))
        restarted.attach_ui(self.workflow_id, self.node_id, self.user_id)
        restarted.resume(self.workflow_id, self.node_id, self.user_id)
        def crash(stage):
            if stage == 'dispatching':
                raise RuntimeError('crash')
        with self.assertRaisesRegex(RuntimeError, 'crash'):
            restarted.advance(self.workflow_id, self.node_id, self.user_id,
                permissions={'project-read'}, allowed_privacy={'project'},
                expected_head=self.head, checkpoint=crash)
        recovered = self.queue().get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((recovered['state'], recovered['steps'][0]['state']),
                         ('unknown', 'unknown'))
        self.assertEqual(self.calls, [])

    def test_unknown_effect_is_terminal_and_never_retried(self):
        attempts = []
        def uncertain(value):
            attempts.append(value); raise UnknownEffect('response was lost')
        handlers = dict(self.handlers)
        handlers[('analysis.read-only', '1.0')] = uncertain
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(handlers); self.prepare_and_activate(queue, self.plan([step]))
        result = self.advance(queue)
        self.assertEqual((result['state'], result['steps'][0]['state']),
                         ('unknown', 'unknown'))
        with self.assertRaisesRegex(ValidationError, 'not runnable'):
            self.advance(queue)
        self.assertEqual(len(attempts), 1)

    def test_plan_edit_discards_approval_but_cannot_follow_an_effect(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(
            queue, self.plan([first], mode='manual'))
        self.advance(queue); queue.approve(self.workflow_id, first['step_id'],
                                      self.node_id, self.user_id)
        replacement = self.step('analysis.read-only', {'selection_sha256': '2' * 64})
        edited = queue.replace_plan(self.plan([replacement], mode='manual'),
                                    self.node_id, self.user_id)
        self.assertEqual((edited['state'], edited['steps'][0]['approval_digest']),
                         ('proposed', None))
        queue.attach_ui(self.workflow_id, self.node_id, self.user_id)
        queue.activate(self.workflow_id, self.node_id, self.user_id,
                       edited['activation_digest'])
        self.advance(queue); queue.approve(self.workflow_id, replacement['step_id'],
                                      self.node_id, self.user_id)
        self.advance(queue)
        with self.assertRaisesRegex(ValidationError, 'produced an effect'):
            queue.replace_plan(self.plan([first], mode='manual'),
                               self.node_id, self.user_id)

    def test_budget_dependencies_and_local_output_contract_are_validated(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64}, cost=2)
        with self.assertRaisesRegex(ValidationError, 'cost budget'):
            parse_plan(self.plan([step], max_cost=1), self.registry)
        bad = deepcopy(step); bad['depends_on'] = [str(uuid4())]
        with self.assertRaisesRegex(ValidationError, 'earlier steps'):
            parse_plan(self.plan([bad]), self.registry)
        output = self.step('artifact.create-local', {'target': 'x.md',
            'content_type': 'text/markdown', 'content_sha256': 'bad',
            'privacy': 'project', 'provenance': {'source': 'workflow'}})
        with self.assertRaisesRegex(ValidationError, 'output hash'):
            parse_plan(self.plan([output]), self.registry)


if __name__ == '__main__':
    unittest.main()
