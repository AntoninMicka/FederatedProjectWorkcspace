# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from contextlib import closing
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
            def invoke(value, execution):
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
            self.handlers if handlers is None else handlers, countdown_seconds=0)

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
             'search.iterative-query', 'workflow.role-handoff'])
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

    def test_version_one_journal_is_migrated_in_place(self):
        path = self.state / 'autonomy-queue.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''
                CREATE TABLE schema_info(version INTEGER NOT NULL);
                INSERT INTO schema_info VALUES(1);
                CREATE TABLE settings(global_paused INTEGER NOT NULL);
                INSERT INTO settings VALUES(0);
                CREATE TABLE workflows(workflow_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,project_id TEXT NOT NULL,plan_digest TEXT NOT NULL,
                    plan_json BLOB NOT NULL,state TEXT NOT NULL,ui_attached INTEGER NOT NULL,
                    spent_cost INTEGER NOT NULL,created_at TEXT NOT NULL,activated_at TEXT,
                    updated_at TEXT NOT NULL,error TEXT);
                CREATE TABLE steps(workflow_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                    step_id TEXT NOT NULL UNIQUE,action_id TEXT NOT NULL,
                    action_version TEXT NOT NULL,descriptor_digest TEXT NOT NULL,
                    state TEXT NOT NULL,approval_digest TEXT,result_json BLOB,error TEXT,
                    PRIMARY KEY(workflow_id,ordinal),
                    FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id));
            ''')
        path.chmod(0o600)
        queue = self.queue()
        with closing(sqlite3.connect(queue.path)) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], 3)
            self.assertIn('ui_seen_at', [row[1] for row in
                                        db.execute('PRAGMA table_info(workflows)')])
            self.assertIn('not_before', [row[1] for row in
                                        db.execute('PRAGMA table_info(steps)')])
            self.assertIn('activation_digest', [row[1] for row in
                db.execute('PRAGMA table_info(workflows)')])

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
        listed = queue.list(self.node_id, self.user_id, self.project_id)
        self.assertEqual({item['workflow_id'] for item in listed['workflows']},
                         {self.workflow_id, second_id})
        self.assertEqual(queue.list(str(uuid4()), str(uuid4()))['workflows'], [])

    def test_second_dispatch_in_same_workflow_is_rejected(self):
        queue = self.queue()
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        second = self.step('analysis.read-only', {'selection_sha256': '2' * 64})
        self.prepare_and_activate(queue, self.plan([first, second]))
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE steps SET state='dispatching' WHERE step_id=?",
                       (first['step_id'],))
            db.execute("UPDATE workflows SET state='running' WHERE workflow_id=?",
                       (self.workflow_id,))
            db.commit()
        with self.assertRaisesRegex(ValidationError, 'already has a dispatching'):
            self.advance(queue)
        self.assertEqual(self.calls, [])

    def test_time_budget_and_cancel_fail_closed_before_effect(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(queue, self.plan([step]))
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE workflows SET activated_at='2000-01-01T00:00:00Z' "
                       "WHERE workflow_id=?", (self.workflow_id,))
            db.commit()
        with self.assertRaisesRegex(ValidationError, 'time budget'):
            self.advance(queue)
        cancelled = queue.cancel(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((cancelled['state'], cancelled['steps'][0]['state']),
                         ('cancelled', 'cancelled'))
        self.assertEqual(self.calls, [])

    def test_automatic_countdown_and_expired_ui_lease_prevent_dispatch(self):
        queue = AutonomyQueue(self.state, self.registry, self.handlers,
                              countdown_seconds=3)
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        self.prepare_and_activate(queue, self.plan([step]))
        countdown = self.advance(queue)
        self.assertEqual((countdown['state'], countdown['steps'][0]['state']),
                         ('countdown', 'countdown'))
        self.assertIsNotNone(countdown['steps'][0]['not_before'])
        with self.assertRaisesRegex(ValidationError, 'countdown'):
            self.advance(queue)
        paused = queue.pause(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((paused['state'], paused['steps'][0]['state']),
                         ('paused', 'queued'))
        queue.attach_ui(self.workflow_id, self.node_id, self.user_id)
        queue.resume(self.workflow_id, self.node_id, self.user_id)
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE workflows SET ui_seen_at='2000-01-01T00:00:00Z' "
                       "WHERE workflow_id=?", (self.workflow_id,)); db.commit()
        self.assertFalse(queue.get(self.workflow_id, self.node_id,
                                   self.user_id)['ui_attached'])
        with self.assertRaisesRegex(ValidationError, 'live attached UI'):
            self.advance(queue)

    def test_restart_detaches_proposal_and_approval_without_losing_evidence(self):
        step = self.step('query.external',
            {'approval_id': str(uuid4()), 'preview_sha256': '2' * 64,
             'privacy': 'public'},
            privacy='public')
        plan = self.plan([step], privacy='public')
        queue = self.queue(); proposed = queue.prepare(plan, self.node_id, self.user_id)
        queue.attach_ui(self.workflow_id, self.node_id, self.user_id)
        restarted = self.queue()
        result = restarted.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((result['state'], result['ui_attached']), ('proposed', False))
        restarted.attach_ui(self.workflow_id, self.node_id, self.user_id)
        restarted.activate(self.workflow_id, self.node_id, self.user_id,
                           proposed['activation_digest'])
        result = self.advance(restarted)
        self.assertEqual(result['steps'][0]['state'], 'awaiting-approval')
        restarted = self.queue()
        result = restarted.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((result['state'], result['ui_attached'],
                          result['steps'][0]['state']),
                         ('awaiting-approval', False, 'awaiting-approval'))
        with self.assertRaisesRegex(ValidationError, 'attached workflow'):
            restarted.approve(self.workflow_id, step['step_id'],
                              self.node_id, self.user_id)

    def test_combined_automatic_workflow_stops_for_external_and_each_local_output(self):
        analysis = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        external = self.step('query.external',
            {'approval_id': str(uuid4()), 'preview_sha256': '2' * 64,
             'privacy': 'public'},
            privacy='public', depends=[analysis['step_id']])
        handoff = self.step('workflow.role-handoff',
            {'workflow_id': str(uuid4()), 'creator_sha256': '3' * 64},
            depends=[external['step_id']])
        output = self.step('artifact.create-local', {'target': 'artifacts/new/content.md',
            'content_type': 'text/markdown', 'content_sha256': '4' * 64,
            'privacy': 'project', 'provenance': {'workflow_id': self.workflow_id},
            'request': {'kind': 'test-publication'}},
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

    def test_version_two_search_policy_binds_countdown_and_appends_one_exact_step(self):
        task_id = str(uuid4())
        def search_step(query, round_index, parent=None, depends=None):
            request = {'task_id': task_id, 'search_id': str(uuid4()),
                'synthesis_run_id': str(uuid4()),
                'synthesis_manifest_id': str(uuid4())}
            if parent is not None:
                request.update(parent_search_id=parent, query=query)
            preview = {'schema_version': 2, **request, 'query': query,
                'purpose': 'Test', 'privacy': 'project',
                'round_index': round_index, 'parent_search_id': parent,
                'result_limit': 3,
                'budget': {'max_rounds': 3, 'max_queries': 3,
                           'max_results': 30, 'max_seconds': 300},
                'language': 'cs-CZ', 'binding': {'adapter': 'searxng'},
                'message_ids': [], 'artifact_ids': [], 'warning': 'Untrusted.'}
            return self.step('search.iterative-query', {
                'request': request, 'preview': preview,
                'preview_sha256': digest(preview)}, depends=depends)
        first = search_step('first', 1)
        plan = {'schema_version': 2, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.head,
            'mode': 'automatic', 'privacy': 'project', 'countdown_seconds': 4,
            'continuation': {'kind': 'iterative-search-v1', 'task_id': task_id,
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'follow_up_policy': 'first-proposed-v1'},
            'budget': {'max_steps': 3, 'max_cost_units': 3,
                       'max_seconds': 300}, 'steps': [first]}
        queue = AutonomyQueue(self.state, self.registry, self.handlers,
                              countdown_seconds=0)
        activated = self.prepare_and_activate(queue, plan)
        self.assertEqual(activated['countdown_seconds'], 4)
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE steps SET state='completed',result_json=? "
                       "WHERE step_id=?", (b'{}', first['step_id']))
            db.execute("UPDATE workflows SET state='queued' WHERE workflow_id=?",
                       (self.workflow_id,)); db.commit()
        second = search_step('second', 2, first['input']['request']['search_id'],
                             [first['step_id']])
        appended = queue.append_step(self.workflow_id, second,
            self.node_id, self.user_id)
        self.assertEqual(len(appended['steps']), 2)
        self.assertEqual(appended['steps'][1]['input']['preview']['query'], 'second')
        self.assertEqual(appended['activation_digest'], activated['activation_digest'])
        with self.assertRaisesRegex(ValidationError, 'pending step'):
            queue.append_step(self.workflow_id, search_step('third', 3),
                              self.node_id, self.user_id)

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
        def uncertain(value, execution):
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
            'privacy': 'project', 'provenance': {'source': 'workflow'},
            'request': {'kind': 'test-publication'}})
        with self.assertRaisesRegex(ValidationError, 'output hash'):
            parse_plan(self.plan([output]), self.registry)


if __name__ == '__main__':
    unittest.main()
