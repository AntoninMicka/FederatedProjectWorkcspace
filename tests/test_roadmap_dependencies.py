# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from unittest.mock import patch
import shutil
import subprocess
from uuid import uuid4

from spikes.markdown_documents import main_todo_id
from spikes.projects import Projects
from spikes.desktop_ui import DesktopHandler, JS
from spikes.local_api import running_api
from spikes.context_builder import ContextBuilder
from spikes.roadmap_dependencies import SCHEMA, MODE, validate, focus_input
from spikes.roadmap_refinement import RoadmapRefinement
from spikes.roadmap_refinement_tui import RefinementTUI
from spikes.task_graph import project_task_graph
from spikes.metadata import validate_snapshot
from spikes.ollama_backend import OllamaAdapter
from tests import test_roadmap_refinement as refinement_tests
from tests import test_local_api


class DependencyScanTests(unittest.TestCase):
    def setUp(self):
        refinement_tests.RoadmapRefinementTests.setUp(self)
        self.phrase = 'TASK-02 provides the validated input required by TASK-01.'
        files = self.git.snapshot(self.git.head())
        path = f'artifacts/{main_todo_id(self.project_id)}/content.md'
        body = files[path].decode().replace('      - type: task\n',
                                          '      - type: task\n      - ' + self.phrase + '\n')
        self.docs.save(dict(project_id=self.project_id, artifact_id=main_todo_id(self.project_id),
                           base_head=self.git.head(), title='Roadmap', body=body, new=False), str(uuid4()))
        self.head = self.git.head()
        self.response = self.proposal()

    def proposal(self, focus='TASK-01', target='TASK-02'):
        return dict(schema=SCHEMA, focus_id=focus, decision='propose', reason='Input prerequisite.',
                    edges=[dict(target_id=target, evidence_id='0', quote=self.phrase,
                                reason='The input must exist before execution.')])

    def scan(self, focus='TASK-01'):
        return self.service.scan(dependencies_only=True, focus_ids=[focus])

    def row(self, result):
        return self.service.get(result['created'][0])

    def accept(self):
        row = self.row(self.scan())
        self.assertEqual(row['state'], 'pending', row)
        self.service.decide(row['proposal_id'], 'accept')
        return row

    def test_scan_is_focused_durable_and_does_not_mutate_roadmap(self):
        result = self.scan(); row = self.row(result)
        self.assertEqual(row['mode'], MODE)
        self.assertEqual(self.git.head(), self.head)
        self.assertEqual(row['input']['focus']['id'], 'TASK-01')
        self.assertGreater(result['remaining'], 0)
        self.assertFalse(result['complete'])
        self.assertEqual(self.scan()['created'], [])
        detail = self.service.review_detail(row['proposal_id'])
        self.assertIn(self.phrase, detail['context']['source_excerpt'])
        self.assertEqual(detail['row']['proposal']['changes'][0]['target_id'], 'TASK-02')
        public = next(r for r in self.service.review_list() if r['proposal_id'] == row['proposal_id'])
        self.assertEqual(public['risk'], 'high')
        self.assertEqual(public['impact'], 'mutation')

    def test_wrong_focus_unknown_target_and_wrong_quote_fail_closed(self):
        for field, value in [('focus_id', 'TASK-02'), ('target_id', 'TASK-99'),
                             ('quote', 'This invented source quote is not present.')]:
            with self.subTest(field=field):
                files = self.git.snapshot(self.head)
                graph = project_task_graph(files, validate_snapshot(files), self.project_id, self.head)
                frozen = focus_input(next(t for t in graph['nodes'] if t['id'] == 'TASK-01'),
                                     graph, files, validate_snapshot(files))
                response = self.proposal()
                if field == 'focus_id': response[field] = value
                else: response['edges'][0][field] = value
                with self.assertRaises(ValueError): validate(json.dumps(response), frozen)
        self.response['focus_id'] = 'TASK-02'
        row = self.row(self.scan())
        self.assertEqual(row['state'], 'failed')
        self.assertIn('focus differs', row['proposal']['error'])
        self.assertEqual(self.scan()['created'], [])

    def test_duplicate_edge_and_self_edge_are_rejected(self):
        self.response['edges'].append(dict(self.response['edges'][0]))
        self.assertEqual(self.row(self.scan())['state'], 'failed')
        self.response = self.proposal(focus='TASK-02', target='TASK-02')
        self.assertEqual(self.row(self.scan('TASK-02'))['state'], 'failed')

    def test_needs_context_is_not_accepted_or_counted_as_complete(self):
        self.response.update(decision='needs-context', edges=[])
        result = self.scan(); row = self.row(result)
        self.assertEqual(row['state'], 'needs-context')
        self.assertFalse(result['complete'])
        self.assertEqual(self.service.review_detail(row['proposal_id'])['row']['state'], 'needs-context')
        with self.assertRaises(ValueError): self.service.decide(row['proposal_id'], 'accept')

    def test_no_change_review_does_not_create_a_project_commit(self):
        self.response.update(decision='no-change', edges=[])
        row = self.row(self.scan()); self.service.decide(row['proposal_id'], 'accept')
        preview = self.service.reconciliation_preview([row['proposal_id']])
        result = self.service.apply(str(uuid4()), preview['preview_sha256'], [row['proposal_id']])
        self.assertEqual(result['receipt']['state'], 'evidence-only')
        self.assertEqual(self.git.head(), self.head)

    def test_unstarted_intent_freezes_review_and_can_be_cancelled(self):
        row = self.accept(); ids = [row['proposal_id']]
        preview = self.service.reconciliation_preview(ids); operation = str(uuid4())
        def stop(stage):
            if stage == 'dependency-intent': raise RuntimeError('stop before native journal')
        with self.assertRaises(RuntimeError):
            self.service.apply(operation, preview['preview_sha256'], ids, checkpoint=stop)
        with self.assertRaisesRegex(ValueError, 'pending apply'):
            self.service.decide(row['proposal_id'], 'reset')
        with self.assertRaisesRegex(ValueError, 'pending apply'):
            self.service.decide_many(ids, 'reset')
        with self.assertRaisesRegex(ValueError, 'pending apply'):
            self.service.apply(str(uuid4()), preview['preview_sha256'], ids)
        self.assertEqual(self.service.cancel_dependency_apply(operation)['state'], 'cancelled')
        self.service.decide(row['proposal_id'], 'reset')
        self.assertEqual(self.git.head(), self.head)
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.service.apply(operation, preview['preview_sha256'], ids)

    def test_native_started_intent_requires_recovery_not_cancellation(self):
        row = self.accept(); ids = [row['proposal_id']]
        preview = self.service.reconciliation_preview(ids); operation = str(uuid4())
        def stop(stage):
            if stage == 'dependency-native-receipt': raise RuntimeError('stop after commit')
        with self.assertRaises(RuntimeError):
            self.service.apply(operation, preview['preview_sha256'], ids, checkpoint=stop)
        with self.assertRaisesRegex(ValueError, 'Native apply has started'):
            self.service.cancel_dependency_apply(operation)
        detail = self.service.review_detail(row['proposal_id'])
        self.assertEqual(detail['context']['pending_apply']['operation_id'], operation)
        self.service.apply(operation, preview['preview_sha256'], ids)
        self.assertEqual(self.service.get(row['proposal_id'])['state'], 'applied')

    def test_unrelated_native_operation_id_does_not_leave_review_frozen(self):
        row = self.accept(); ids = [row['proposal_id']]
        preview = self.service.reconciliation_preview(ids)
        workspace = Projects(self.node).workspace(self.project_id)
        with workspace.journal.connect() as db:
            operation = db.execute('SELECT id FROM operations WHERE done=1 LIMIT 1').fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'different native request'):
            self.service.apply(operation, preview['preview_sha256'], ids)
        self.service.decide(row['proposal_id'], 'reset')
        self.assertEqual(self.service.get(row['proposal_id'])['state'], 'pending')

    def test_tui_requires_diff_confirmation_and_can_recover_an_existing_intent(self):
        row = self.accept()
        ui = RefinementTUI(self.service, dependencies_only=True)
        ui.handle(ord('p'))
        self.assertTrue(ui.confirm_apply)
        self.assertIn('depends_on: TASK-02', ui.apply_preview['diff'])
        self.assertEqual(self.git.head(), self.head)
        operation = ui.apply_operation; preview = ui.apply_preview
        def stop(stage):
            if stage == 'dependency-native-receipt': raise RuntimeError('lost outcome')
        with self.assertRaises(RuntimeError):
            self.service.apply(operation, preview['preview_sha256'], preview['proposal_ids'], checkpoint=stop)
        resumed = RefinementTUI(self.service)
        resumed.handle(ord('p'))
        self.assertEqual(resumed.apply_operation, operation)
        resumed.handle(ord('y'))
        self.assertEqual(self.service.get(row['proposal_id'])['state'], 'applied')
        self.assertEqual(int(self.git.run('rev-list', '--count', self.head + '..HEAD').stdout), 1)

    def test_http_review_and_preview_then_apply_use_the_native_service(self):
        row = self.row(self.scan()); identifier = row['proposal_id']
        driver = test_local_api.LocalAPITests()
        with patch('spikes.roadmap_refinement.RoadmapRefinement', return_value=self.service), \
                running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            def request(action, **fields):
                raw = driver.request(server, path='/v1/roadmap-refinement/' + action,
                                     body=json.dumps(dict(project_id=self.project_id, **fields)).encode())
                self.assertTrue(raw.startswith(b'HTTP/1.0 200'), raw)
                return json.loads(raw.split(b'\r\n\r\n', 1)[1])
            detail = request('detail', proposal_id=identifier)
            self.assertIn(self.phrase, detail['context']['source_excerpt'])
            driver.rejected(server, path='/v1/roadmap-refinement/decide', headers={'Authorization': None},
                            body=json.dumps(dict(project_id=self.project_id, proposal_id=identifier, decision='accept')).encode())
            request('decide', proposal_id=identifier, decision='accept')
            preview = request('reconcile/preview', proposal_ids=[identifier])
            request('apply', operation_id=str(uuid4()), preview_sha256=preview['preview_sha256'], proposal_ids=[identifier])
            self.assertEqual(self.service.get(identifier)['state'], 'applied')

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_review_ui_recovers_the_original_operation_without_new_preview(self):
        row = self.accept(); ids = [row['proposal_id']]
        preview = self.service.reconciliation_preview(ids); operation = str(uuid4())
        def stop(stage):
            if stage == 'dependency-native-receipt': raise RuntimeError('lost outcome')
        with self.assertRaises(RuntimeError):
            self.service.apply(operation, preview['preview_sha256'], ids, checkpoint=stop)
        detail = self.service.review_detail(row['proposal_id'])
        fn = JS[JS.index('function renderRoadmapReviewDetail('):JS.index('async function selectRoadmapReview(')]
        script = r'''
const assert=require('node:assert/strict'),elements=new Map(),calls=[];
function el(){return {textContent:'',hidden:true,disabled:false,append(){},replaceChildren(){}};}
const document={querySelector(id){if(!elements.has(id))elements.set(id,el());return elements.get(id);},createElement:el};
const roadmapReviewDetail={querySelector:document.querySelector},activeProject={id:'project'},window={confirm:()=>true};
const updateRoadmapReviewActions=()=>{},openRegisteredProject=async()=>{},openRoadmapReview=()=>{},roadmapReviewStatus=el();
async function projectRequest(path,body){calls.push({path,body});}
''' + fn + '\nrenderRoadmapReviewDetail(' + json.dumps(detail) + ');\n' + r'''
const button=document.querySelector('#roadmap-review-recover');assert.equal(button.hidden,false);
button.onclick().then(()=>{assert.equal(calls.length,1);assert.equal(calls[0].path,'/v1/roadmap-refinement/apply');
assert.equal(calls[0].body.operation_id,OPERATION);assert.deepEqual(calls[0].body.proposal_ids,IDS);
assert.equal(calls[0].body.preview_sha256,DIGEST);});
'''.replace('OPERATION', json.dumps(operation)).replace('IDS', json.dumps(ids)).replace('DIGEST', json.dumps(preview['preview_sha256']))
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_head_before_native_apply_preserves_roadmap(self):
        row = self.accept(); ids = [row['proposal_id']]
        preview = self.service.reconciliation_preview(ids)
        self.docs.save(dict(project_id=self.project_id, artifact_id=str(uuid4()),
                           base_head=self.git.head(), title='New document', body='Unrelated change', new=True), str(uuid4()))
        current = self.git.head()
        with self.assertRaises(ValueError): self.service.apply(str(uuid4()), preview['preview_sha256'], ids)
        self.assertEqual(self.git.head(), current)

    def test_head_change_during_context_preparation_prevents_dispatch(self):
        original = ContextBuilder.prepare; dispatched = []
        factory = self.service.adapter_factory
        def changed(builder, **kwargs):
            self.docs.save(dict(project_id=self.project_id, artifact_id=str(uuid4()),
                base_head=self.git.head(), title='Concurrent document', body='Changed HEAD', new=True), str(uuid4()))
            return original(builder, **kwargs)
        def observed(runs):
            dispatched.append(True); return factory(runs)
        self.service.adapter_factory = observed
        with patch.object(ContextBuilder, 'prepare', changed):
            result = self.scan()
        self.assertTrue(result['stale'])
        self.assertEqual(self.row(result)['state'], 'failed')
        self.assertEqual(dispatched, [])

    def test_explicit_preview_native_apply_and_lost_response_retry(self):
        row = self.accept(); preview = self.service.reconciliation_preview([row['proposal_id']])
        self.assertEqual(preview['blockers'], [])
        self.assertIn('depends_on: TASK-02', preview['diff'])
        operation = str(uuid4())
        with self.assertRaises(ValueError): self.service.apply(operation, proposal_ids=[row['proposal_id']])
        result = self.service.apply(operation, preview['preview_sha256'], [row['proposal_id']])
        self.assertNotEqual(self.head, self.git.head())
        count = self.git.run('rev-list', '--count', 'HEAD').stdout
        retry = self.service.apply(operation, preview['preview_sha256'], [row['proposal_id']])
        self.assertEqual(result, retry)
        self.assertEqual(count, self.git.run('rev-list', '--count', 'HEAD').stdout)
        with self.assertRaises(ValueError): self.service.apply(operation, '0' * 64, [row['proposal_id']])

    def test_recovery_after_intent_native_checkpoints_and_outcome(self):
        row = self.accept(); preview = self.service.reconciliation_preview([row['proposal_id']])
        operation = str(uuid4())
        hit = set()
        for stage in ['dependency-intent', 'files-applied', 'committed',
                      'dependency-native-receipt', 'dependency-outcome']:
            def crash(current):
                if current == stage:
                    hit.add(stage)
                    raise RuntimeError('simulated crash')
            try:
                self.service.apply(operation, preview['preview_sha256'], [row['proposal_id']], checkpoint=crash)
            except RuntimeError:
                self.service = RoadmapRefinement(self.node, self.project_id, state_dir=self.state)
        result = self.service.apply(operation, preview['preview_sha256'], [row['proposal_id']])
        self.assertEqual(self.git.head(), result['receipt']['commit_id'])
        self.assertEqual(self.service.get(row['proposal_id'])['state'], 'applied')
        self.assertEqual(int(self.git.run('rev-list', '--count', self.head + '..HEAD').stdout), 1)
        self.assertEqual(hit, {'dependency-intent', 'files-applied', 'committed',
                               'dependency-native-receipt', 'dependency-outcome'})

    def test_combined_cycle_is_blocked_before_any_project_write(self):
        one = self.accept()
        self.response = self.proposal('TASK-02', 'TASK-01')
        two = self.row(self.scan('TASK-02')); self.service.decide(two['proposal_id'], 'accept')
        ids = [one['proposal_id'], two['proposal_id']]
        preview = self.service.reconciliation_preview(ids)
        self.assertTrue(preview['blockers'])
        with self.assertRaises(ValueError): self.service.apply(str(uuid4()), preview['preview_sha256'], ids)
        self.assertEqual(self.git.head(), self.head)

    def test_batch_dependency_does_not_read_child_dependency_metadata(self):
        files = self.git.snapshot(self.head)
        path = f'artifacts/{main_todo_id(self.project_id)}/content.md'
        body = files[path].decode().replace('      - ' + self.phrase,
                '      - depends_on: MILESTONE-02\n      - ' + self.phrase, 1)
        body += '\n- [ ] [MILESTONE-02] Independent input\n  - type: milestone\n'
        self.docs.save(dict(project_id=self.project_id, artifact_id=main_todo_id(self.project_id),
                           base_head=self.git.head(), title='Roadmap', body=body, new=False), str(uuid4()))
        # Exercise the same typed writer used by accepted dependency proposals.
        from spikes.roadmap_refinement import _deep_change
        files = self.git.snapshot(self.git.head()); before = validate_snapshot(files)
        changed = _deep_change(files, before, self.project_id, self.git.head(),
            dict(kind='add-dependency', node_id='BATCH-01', target_id='MILESTONE-02',
                 title=None, node_type=None, parent_id=None, checked=None, reason='Shared input'))
        graph = project_task_graph(changed, before, self.project_id, self.git.head())
        nodes = {t['id']: t for t in graph['nodes']}
        self.assertEqual(nodes['BATCH-01']['depends_on'], ['MILESTONE-02'])
        self.assertEqual(nodes['TASK-01']['depends_on'], ['MILESTONE-02'])

    def test_frontmatter_and_crlf_bytes_are_preserved_by_reviewed_apply(self):
        aid = main_todo_id(self.project_id); prefix = f'artifacts/{aid}/'
        files = self.git.snapshot(self.git.head())
        meta = json.loads(files[prefix + 'metadata.json']); meta.pop('file')
        header = b'---\r\n' + json.dumps(meta).encode() + b'\r\n---\r\n'
        raw = header + files[prefix + 'content.md'].replace(b'\n', b'\r\n')
        root = self.base / 'project'
        (root / (prefix + 'metadata.json')).unlink()
        (root / (prefix + 'content.md')).write_bytes(raw)
        self.git.commit('Frontmatter CRLF fixture')
        row = self.accept(); preview = self.service.reconciliation_preview([row['proposal_id']])
        self.service.apply(str(uuid4()), preview['preview_sha256'], [row['proposal_id']])
        result = self.git.snapshot(self.git.head())[prefix + 'content.md']
        self.assertTrue(result.startswith(header))
        self.assertEqual(result.replace(b'      - depends_on: TASK-02\r\n', b'', 1), raw)

    def test_linked_plan_changes_only_the_original_definition_file(self):
        aid = str(uuid4())
        self.docs.save(dict(project_id=self.project_id, artifact_id=aid, base_head=self.git.head(),
            title='Tasks', body='<!-- fpw-plan-document: definitions/v1 -->\n'
            '- [ ] [TASK-01] Work\n  - type: task\n  - ' + self.phrase
            + '\n- [ ] [TASK-02] Later work\n  - type: task\n', new=True), str(uuid4()))
        root_id = main_todo_id(self.project_id)
        self.docs.save(dict(project_id=self.project_id, artifact_id=root_id, base_head=self.git.head(),
            title='Roadmap', body='<!-- fpw-plan-profile: software-development/v1 -->\n'
            '- [ ] [MILESTONE-M1] First milestone\n  - type: milestone\n'
            f'  - [ ] [BATCH-01] [Feature](artifacts/{aid}/content.md)\n    - type: batch\n', new=False), str(uuid4()))
        before = self.git.snapshot(self.git.head())
        row = self.accept(); preview = self.service.reconciliation_preview([row['proposal_id']])
        self.assertEqual(preview['changed_files'], [f'artifacts/{aid}/content.md'])
        self.service.apply(str(uuid4()), preview['preview_sha256'], [row['proposal_id']])
        after = self.git.snapshot(self.git.head())
        self.assertEqual(before[f'artifacts/{root_id}/content.md'], after[f'artifacts/{root_id}/content.md'])

    def test_stale_preview_and_tampered_frozen_evidence_are_blocked(self):
        row = self.accept(); preview = self.service.reconciliation_preview([row['proposal_id']])
        with self.service._connect() as db, db:
            frozen = row['input']; frozen['evidence'][0]['text'] += '\nforged'
            db.execute('UPDATE proposals SET input_json=? WHERE id=?',
                       (json.dumps(frozen), row['proposal_id']))
        self.assertTrue(self.service.reconciliation_preview([row['proposal_id']])['blockers'])
        with self.assertRaises(ValueError): self.service.apply(str(uuid4()), preview['preview_sha256'], [row['proposal_id']])
        self.assertEqual(self.git.head(), self.head)

    def test_interrupted_dispatch_becomes_unknown_without_retry_and_old_queue_survives(self):
        self.service.scan()  # Existing detached mode may fail, but is retained.
        old = {r['proposal_id'] for r in self.service.list()}
        def factory(runs):
            def fail(binding, raw): raise TimeoutError('after dispatch')
            return OllamaAdapter(runs, transport=fail)
        self.service.adapter_factory = factory
        result = self.scan(); row = self.row(result)
        self.assertEqual(row['state'], 'unknown')
        with self.service._connect() as db, db:
            db.execute("UPDATE proposals SET state='running' WHERE id=?", (row['proposal_id'],))
        self.assertEqual(self.scan()['created'], [])
        self.assertEqual(self.service.get(row['proposal_id'])['state'], 'unknown')
        self.assertTrue(old <= {r['proposal_id'] for r in self.service.list()})
        other = RoadmapRefinement(self.node, str(uuid4()), state_dir=self.state)
        self.assertEqual(other.list(), [])

    def test_modes_and_unknown_focus_cannot_be_mixed(self):
        for request in [dict(dependencies_only=True, deep_check=True),
                        dict(dependencies_only=True, forget_previous=True),
                        dict(dependencies_only=True, focus_ids=['FAKE-01']),
                        dict(focus_ids=['TASK-01'])]:
            with self.assertRaises(ValueError): self.service.scan(**request)
