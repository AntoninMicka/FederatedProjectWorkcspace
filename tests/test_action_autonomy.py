# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier, Thread
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
                self.calls.append((name, value))
                if name == 'analysis':
                    return {'schema_version': 1, 'kind': 'analysis',
                        'project_id': self.project_id, 'project_commit': self.head,
                        'selection_sha256': value['selection_sha256']}
                if name == 'external':
                    return {'schema_version': 1, 'kind': 'external',
                        'approval_id': value['approval_id'], 'state': 'recorded'}
                if name == 'handoff':
                    return {'schema_version': 1, 'kind': 'handoff',
                        'workflow_id': value['workflow_id'], 'step_id': str(uuid4()),
                        'state': 'prepared', 'approval_digest': '5' * 64}
                return {'schema_version': 1, 'kind': 'artifact',
                    'project_id': self.project_id, 'artifact_id': str(uuid4()),
                    'commit_id': self.head, 'receipt_sha256': '6' * 64}
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

    def dynamic_plan(self, steps, *, max_steps=4, max_cost=4):
        return {'schema_version': 3, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.head,
            'mode': 'manual', 'privacy': 'project', 'countdown_seconds': 3,
            'policy': {'actions': [
                {'id': 'analysis.read-only', 'version': '1.0'}],
                'permissions': ['project-read'],
                'execution_boundaries': ['local-node']},
            'budget': {'max_steps': max_steps, 'max_cost_units': max_cost,
                       'max_seconds': 3600}, 'steps': steps}

    def complete_manual_step(self, queue, step):
        awaiting = self.advance(queue)
        self.assertEqual(awaiting['steps'][-1]['state'], 'awaiting-approval')
        queue.approve(self.workflow_id, step['step_id'], self.node_id, self.user_id)
        return self.advance(queue)

    def revision(self, workflow, kind, *, step=None, repeat_of=None,
                 budget=None, proposal_id=None):
        return {'schema_version': 1,
            'proposal_id': proposal_id or str(uuid4()),
            'workflow_id': self.workflow_id,
            'base_revision': workflow['plan_revision'],
            'base_plan_digest': workflow['plan_revisions'][-1]['plan_digest'],
            'kind': kind, 'reason': f'Test {kind}', 'step': step,
            'repeat_of': repeat_of, 'budget': budget or workflow['budget']}

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
             'research.analyze', 'research.compose-report', 'research.plan-next',
             'research.select-relevant', 'research.verify-evidence',
             'search.iterative-query', 'source.fetch-public',
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

    def test_typed_registry_validates_successors_outputs_and_policy_boundary(self):
        self.assertTrue(all(item['schema_version'] == 2
                            for item in self.registry.list()))
        selection = '1' * 64
        previous = {'action': {'id': 'analysis.read-only', 'version': '1.0'},
            'result': {'schema_version': 1, 'kind': 'analysis',
                'project_id': self.project_id, 'project_commit': self.head,
                'selection_sha256': selection}}
        following = self.step('analysis.read-only',
                              {'selection_sha256': selection})
        descriptor = self.registry.validate_transition([previous], following,
            available_preconditions={'project-head-current'},
            permissions={'project-read'}, allowed_privacy={'project'},
            allowed_boundaries={'local-node'})
        self.assertEqual(descriptor['execution_boundary'], 'local-node')

        missing = deepcopy(previous); del missing['result']['selection_sha256']
        with self.assertRaisesRegex(ValidationError, 'required output is missing'):
            self.registry.validate_transition([missing], following,
                available_preconditions={'project-head-current'},
                permissions={'project-read'}, allowed_privacy={'project'},
                allowed_boundaries={'local-node'})
        malformed = {'action': previous['action'], 'result': None}
        with self.assertRaisesRegex(ValidationError, 'transition predecessor'):
            self.registry.validate_transition([malformed], following,
                available_preconditions={'project-head-current'},
                permissions={'project-read'}, allowed_privacy={'project'},
                allowed_boundaries={'local-node'})

        artifact = {'action': {'id': 'artifact.create-local', 'version': '1.0'},
            'result': {'schema_version': 1, 'kind': 'artifact',
                'project_id': self.project_id, 'artifact_id': str(uuid4()),
                'commit_id': self.head, 'receipt_sha256': '2' * 64}}
        with self.assertRaisesRegex(ValidationError, 'not allowed'):
            self.registry.validate_transition([artifact], following,
                available_preconditions={'project-head-current'},
                permissions={'project-read'}, allowed_privacy={'project'},
                allowed_boundaries={'local-node'})

        external = self.step('query.external', {'approval_id': str(uuid4()),
            'preview_sha256': '3' * 64, 'privacy': 'public'}, privacy='public')
        with self.assertRaisesRegex(ValidationError, 'permissions'):
            self.registry.validate_transition([previous], external,
                available_preconditions={'external-preview-current'}, permissions=set(),
                allowed_privacy={'public'}, allowed_boundaries={'external-network'})
        with self.assertRaisesRegex(ValidationError, 'execution boundary'):
            self.registry.validate_transition([previous], external,
                available_preconditions={'external-preview-current'},
                permissions={'external-dispatch'}, allowed_privacy={'public'},
                allowed_boundaries={'local-node'})

    def test_typed_registry_rejects_bad_binding_and_handler_output(self):
        actions = self.registry.list()
        analysis = next(item for item in actions
                        if item['action_id'] == 'analysis.read-only')
        analysis['successors'][0]['bindings'][0]['output'] = 'project_id'
        with self.assertRaisesRegex(ValidationError, 'binding types differ'):
            ActionRegistry(actions)

        def incomplete(value, execution):
            return {'schema_version': 1, 'kind': 'analysis'}
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue({('analysis.read-only', '1.0'): incomplete})
        self.prepare_and_activate(queue, self.plan([step]))
        with self.assertRaisesRegex(ValidationError, 'output fields differ'):
            self.advance(queue)
        failed = queue.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((failed['state'], failed['steps'][0]['state']),
                         ('failed', 'failed'))

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
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], 5)
            self.assertIn('ui_seen_at', [row[1] for row in
                                        db.execute('PRAGMA table_info(workflows)')])
            self.assertIn('not_before', [row[1] for row in
                                        db.execute('PRAGMA table_info(steps)')])
            self.assertIn('activation_digest', [row[1] for row in
                db.execute('PRAGMA table_info(workflows)')])
            self.assertEqual([row[1] for row in
                db.execute('PRAGMA table_info(step_revisions)')],
                ['workflow_id', 'ordinal', 'revision', 'step_json', 'cancelled_at'])
            self.assertIn('plan_revision', [row[1] for row in
                                            db.execute('PRAGMA table_info(workflows)')])
            self.assertEqual([row[1] for row in
                db.execute('PRAGMA table_info(plan_revisions)')],
                ['workflow_id', 'revision', 'proposal_id', 'kind', 'reason',
                 'previous_plan_digest', 'plan_digest', 'plan_json',
                 'approval_digest', 'applied_at'])

    def test_version_four_nonempty_journal_migrates_with_initial_plan_revision(self):
        step = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        plan = self.plan([step]); raw = json.dumps(plan, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()
        plan_digest = digest(raw); created = '2026-10-24T10:00:00Z'
        descriptor = self.registry.resolve('analysis.read-only', '1.0')
        path = self.state / 'autonomy-queue.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''
                CREATE TABLE schema_info(version INTEGER NOT NULL);
                INSERT INTO schema_info VALUES(4);
                CREATE TABLE settings(global_paused INTEGER NOT NULL);
                INSERT INTO settings VALUES(0);
                CREATE TABLE workflows(workflow_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,project_id TEXT NOT NULL,plan_digest TEXT NOT NULL,
                    plan_json BLOB NOT NULL,state TEXT NOT NULL,ui_attached INTEGER NOT NULL,
                    ui_seen_at TEXT,spent_cost INTEGER NOT NULL,created_at TEXT NOT NULL,
                    activated_at TEXT,activation_digest TEXT,updated_at TEXT NOT NULL,error TEXT);
                CREATE TABLE steps(workflow_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                    step_id TEXT NOT NULL UNIQUE,action_id TEXT NOT NULL,
                    action_version TEXT NOT NULL,descriptor_digest TEXT NOT NULL,
                    state TEXT NOT NULL,approval_digest TEXT,not_before TEXT,
                    result_json BLOB,error TEXT,PRIMARY KEY(workflow_id,ordinal));
                CREATE TABLE step_revisions(workflow_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                    revision INTEGER NOT NULL,step_json BLOB NOT NULL,cancelled_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id,ordinal,revision));
            ''')
            db.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.workflow_id, self.node_id, self.user_id, self.project_id,
                 plan_digest, raw, 'proposed', 0, None, 0, created, None, None,
                 created, None))
            db.execute('INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (self.workflow_id, 0, step['step_id'], 'analysis.read-only', '1.0',
                 digest(descriptor), 'queued', None, None, None, None))
            db.commit()
        path.chmod(0o600)
        migrated = self.queue().get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((migrated['plan_revision'], len(migrated['plan_revisions'])),
                         (1, 1))
        self.assertEqual(migrated['plan_revisions'][0]['plan_digest'], plan_digest)

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

    def test_terminal_plan_from_older_registry_does_not_hide_current_workflows(self):
        queue = self.queue(); legacy_id = str(uuid4())
        valid = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        legacy = self.step('analysis.read-only', {'selection_sha256': '2' * 64})
        queue.prepare(self.plan([valid]), self.node_id, self.user_id)
        queue.prepare(self.plan([legacy], workflow_id=legacy_id),
                      self.node_id, self.user_id)
        with closing(sqlite3.connect(queue.path)) as db:
            raw = json.loads(bytes(db.execute(
                'SELECT plan_json FROM workflows WHERE workflow_id=?',
                (legacy_id,)).fetchone()[0]))
            raw['steps'][0]['input']['retired_field'] = True
            db.execute('UPDATE workflows SET plan_json=?,state=? WHERE workflow_id=?',
                (json.dumps(raw).encode(), 'failed', legacy_id))
            db.commit()
        listed = queue.list(self.node_id, self.user_id, self.project_id)
        self.assertEqual([item['workflow_id'] for item in listed['workflows']],
                         [self.workflow_id])
        self.assertEqual(listed['incompatible_workflows'], [{
            'workflow_id': legacy_id, 'state': 'failed',
            'updated_at': listed['incompatible_workflows'][0]['updated_at'],
            'error': 'Autonomy action inputs differ from registry'}])
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE workflows SET state='proposed' WHERE workflow_id=?",
                       (legacy_id,)); db.commit()
        with self.assertRaisesRegex(ValidationError,
                                    'Autonomy action inputs differ from registry'):
            queue.list(self.node_id, self.user_id, self.project_id)

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
        resumed = queue.resume(self.workflow_id, self.node_id, self.user_id)
        replayed = queue.resume(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((resumed['state'], replayed['state']), ('queued', 'queued'))
        self.assertEqual(resumed['updated_at'], replayed['updated_at'])
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
        edited = search_step('edited first', 1)
        edited['input']['request']['task_id'] = task_id
        edited['input']['preview']['task_id'] = task_id
        revised = queue.revise_pending_step(
            self.workflow_id, edited, self.node_id, self.user_id)
        self.assertEqual(revised['steps'][0]['input']['preview']['query'], 'edited first')
        self.assertEqual(revised['revisions'][0]['step']['step_id'], first['step_id'])
        self.assertEqual(revised['revisions'][0]['state'], 'cancelled')
        countdown = self.advance(queue)
        self.assertEqual(countdown['state'], 'countdown')
        with self.assertRaisesRegex(ValidationError, 'differs'):
            queue.send_now(self.workflow_id, edited['step_id'], self.node_id,
                           self.user_id, '0' * 64)
        released = queue.send_now(self.workflow_id, edited['step_id'], self.node_id,
                                  self.user_id,
                                  countdown['steps'][0]['dispatch_digest'])
        self.assertEqual(released['steps'][0]['not_before'], '1970-01-01T00:00:00Z')
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("UPDATE steps SET state='completed',result_json=? "
                       "WHERE step_id=?", (b'{}', edited['step_id']))
            db.execute("UPDATE workflows SET state='queued' WHERE workflow_id=?",
                       (self.workflow_id,)); db.commit()
        second = search_step('second', 2, edited['input']['request']['search_id'],
                             [edited['step_id']])
        appended = queue.append_step(self.workflow_id, second,
            self.node_id, self.user_id)
        self.assertEqual(len(appended['steps']), 2)
        self.assertEqual(appended['steps'][1]['input']['preview']['query'], 'second')
        self.assertEqual(appended['activation_digest'], activated['activation_digest'])
        with self.assertRaisesRegex(ValidationError, 'pending step'):
            queue.append_step(self.workflow_id, search_step('third', 3),
                              self.node_id, self.user_id)

    def test_dynamic_append_repeat_and_finish_keep_immutable_plan_history(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); active = self.prepare_and_activate(
            queue, self.dynamic_plan([first]))
        completed = self.complete_manual_step(queue, first)
        self.assertEqual(completed['steps'][0]['state'], 'completed')
        with self.assertRaisesRegex(ValidationError, 'awaits a revision'):
            self.advance(queue)

        second = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                           depends=[first['step_id']])
        appended = queue.propose_revision(self.revision(completed, 'append', step=second),
            self.node_id, self.user_id,
            available_preconditions={'project-head-current'})
        self.assertEqual((appended['plan_revision'], len(appended['steps'])), (2, 2))
        self.assertEqual(appended['revision_proposals'][-1]['state'], 'applied')
        completed = self.complete_manual_step(queue, second)

        repeated = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                             depends=[second['step_id']])
        repeated_projection = queue.propose_revision(self.revision(
            completed, 'repeat', step=repeated, repeat_of=second['step_id']),
            self.node_id, self.user_id,
            available_preconditions={'project-head-current'})
        self.assertEqual(repeated_projection['plan_revision'], 3)
        self.assertEqual(repeated_projection['plan_revisions'][-1]['kind'], 'repeat')
        completed = self.complete_manual_step(queue, repeated)

        finished = queue.propose_revision(self.revision(completed, 'finish'),
            self.node_id, self.user_id,
            available_preconditions={'project-head-current'})
        self.assertEqual((finished['state'], finished['plan_revision']), ('completed', 4))
        self.assertEqual([len(item['plan']['steps'])
                          for item in finished['plan_revisions']], [1, 2, 3, 3])
        self.assertEqual([item['state'] for item in finished['steps']],
                         ['completed', 'completed', 'completed'])
        self.assertEqual(active['activation_digest'], finished['activation_digest'])

    def test_budget_increase_requires_exact_live_confirmation_and_is_atomic(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(
            queue, self.dynamic_plan([first], max_steps=1, max_cost=1))
        completed = self.complete_manual_step(queue, first)
        second = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                           depends=[first['step_id']])
        expanded_budget = {'max_steps': 2, 'max_cost_units': 2,
                           'max_seconds': 3600}
        proposal = self.revision(completed, 'append', step=second,
                                 budget=expanded_budget)
        pending = queue.propose_revision(proposal, self.node_id, self.user_id,
            available_preconditions={'project-head-current'})
        self.assertEqual((pending['plan_revision'], len(pending['steps'])), (1, 1))
        stored = pending['revision_proposals'][-1]
        self.assertEqual(stored['state'], 'pending')
        with self.assertRaisesRegex(ValidationError, 'differs'):
            queue.confirm_revision(proposal['proposal_id'], self.node_id, self.user_id,
                '0' * 64, available_preconditions={'project-head-current'})

        restarted = self.queue()
        with self.assertRaisesRegex(ValidationError, 'live pending'):
            restarted.confirm_revision(proposal['proposal_id'], self.node_id,
                self.user_id, stored['approval_digest'],
                available_preconditions={'project-head-current'})
        restarted.attach_ui(self.workflow_id, self.node_id, self.user_id)
        confirmed = restarted.confirm_revision(proposal['proposal_id'], self.node_id,
            self.user_id, stored['approval_digest'],
            available_preconditions={'project-head-current'})
        self.assertEqual((confirmed['plan_revision'], confirmed['budget'],
                          len(confirmed['steps'])), (2, expanded_budget, 2))
        self.assertEqual(confirmed['plan_revisions'][-1]['approval_digest'],
                         stored['approval_digest'])

        stale = dict(proposal, proposal_id=str(uuid4()))
        with self.assertRaisesRegex(ValidationError, 'stale'):
            restarted.propose_revision(stale, self.node_id, self.user_id,
                available_preconditions={'project-head-current'})

    def test_revision_transaction_rolls_back_and_lost_response_is_idempotent(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(queue,
            self.dynamic_plan([first]))
        completed = self.complete_manual_step(queue, first)
        second = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                           depends=[first['step_id']])
        proposal = self.revision(completed, 'append', step=second)

        def before_commit(stage):
            if stage == 'before-revision-commit':
                raise RuntimeError('revision crash')
        with self.assertRaisesRegex(RuntimeError, 'revision crash'):
            queue.propose_revision(proposal, self.node_id, self.user_id,
                available_preconditions={'project-head-current'},
                checkpoint=before_commit)
        unchanged = self.queue().get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((unchanged['plan_revision'], len(unchanged['steps']),
                          unchanged['revision_proposals']), (1, 1, []))

        def after_commit(stage):
            if stage == 'revision-applied':
                raise RuntimeError('lost response')
        with self.assertRaisesRegex(RuntimeError, 'lost response'):
            queue.propose_revision(proposal, self.node_id, self.user_id,
                available_preconditions={'project-head-current'},
                checkpoint=after_commit)
        replayed = queue.propose_revision(proposal, self.node_id, self.user_id,
            available_preconditions={'project-head-current'})
        self.assertEqual((replayed['plan_revision'], len(replayed['steps'])), (2, 2))
        self.assertEqual(len(replayed['plan_revisions']), 2)

    def test_invalid_and_concurrent_revisions_fail_without_partial_history(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        queue = self.queue(); self.prepare_and_activate(queue,
            self.dynamic_plan([first]))
        completed = self.complete_manual_step(queue, first)

        forbidden = self.step('query.external', {'approval_id': str(uuid4()),
            'preview_sha256': '2' * 64, 'privacy': 'public'}, privacy='public',
            depends=[first['step_id']])
        with self.assertRaisesRegex(ValidationError, 'permissions|outside dynamic policy'):
            queue.propose_revision(self.revision(completed, 'append', step=forbidden),
                self.node_id, self.user_id,
                available_preconditions={'project-head-current',
                                         'external-preview-current'})
        unchanged = queue.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((unchanged['plan_revision'], unchanged['revision_proposals']),
                         (1, []))

        barrier = Barrier(2); outcomes = []
        def propose(value):
            contender = self.queue(); barrier.wait()
            try:
                projection = contender.propose_revision(value, self.node_id,
                    self.user_id, available_preconditions={'project-head-current'})
                outcomes.append(('applied', projection['plan_revision']))
            except ValidationError as exc:
                outcomes.append(('rejected', str(exc)))
        proposals = []
        for marker in ('1', '2'):
            step = self.step('analysis.read-only',
                {'selection_sha256': '1' * 64}, depends=[first['step_id']])
            proposals.append(self.revision(completed, 'append', step=step,
                proposal_id=str(uuid4())))
        threads = [Thread(target=propose, args=(value,)) for value in proposals]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual([item[0] for item in outcomes].count('applied'), 1)
        self.assertEqual([item[0] for item in outcomes].count('rejected'), 1)
        self.assertIn('stale', next(item[1] for item in outcomes
                                   if item[0] == 'rejected'))
        current = queue.get(self.workflow_id, self.node_id, self.user_id)
        self.assertEqual((current['plan_revision'], len(current['steps']),
                          len(current['plan_revisions'])), (2, 2, 2))

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
        with self.assertRaisesRegex(ValidationError, 'content_sha256'):
            parse_plan(self.plan([output]), self.registry)


if __name__ == '__main__':
    unittest.main()
