# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import fcntl
from itertools import permutations
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_queue import TaskQueue, QueueOutcomeUnknown, adjacent_moves


BODY = '''- [ ] [TASK-A] A
- [ ] [TASK-B] B
  - depends_on: TASK-A
- [ ] [TASK-C] C
  - depends_on: TASK-B
- [ ] [TASK-D] D
  - depends_on: TASK-C, TASK-X
- [ ] [TASK-X] X
- [x] [TASK-DONE] Done
- [ ] [TASK-READY] Ready
  - depends_on: TASK-DONE
'''


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.node = self.root / 'node.json'
        self.pid = ProjectCreation(self.node).create('Queue', str(self.root / 'project'), str(uuid4()))['id']
        self.docs = Artifacts(self.node); self.owner = str(uuid4())
        self.head = self.save(BODY, new=True)
        self.service = TaskQueue(self.node)

    def save(self, body, new=False):
        head = Projects(self.node).repository(self.pid).head()
        return self.docs.save(dict(project_id=self.pid, artifact_id=main_todo_id(self.pid),
            base_head=head, title='Roadmap', body=body, new=new), str(uuid4()))['commit_id']

    def status(self, owner=None):
        return self.service.execute(dict(project_id=self.pid, action='status'), owner or self.owner)

    def act(self, action, task=None, view=None, **extra):
        view = view or self.status()
        request = dict(project_id=self.pid, action=action, expected_head=view['expected_head'], revision=view['revision'])
        if task is not None: request['task_id'] = task
        return self.service.execute(dict(request, **extra), self.owner)

    def test_chain_following_excludes_partial_dependencies_and_does_not_mutate_plan(self):
        self.assertEqual([], self.status()['following'])
        self.act('add', 'TASK-A'); self.assertEqual(['TASK-B'], self.status()['following'])
        self.act('add', 'TASK-B'); self.assertEqual(['TASK-C'], self.status()['following'])
        self.act('add', 'TASK-C'); self.assertNotIn('TASK-D', self.status()['following'])
        self.act('add', 'TASK-X'); self.assertIn('TASK-D', self.status()['following'])
        self.act('add', 'TASK-D'); self.act('add', 'TASK-READY')
        self.assertEqual(self.head, Projects(self.node).repository(self.pid).head())
        self.assertEqual(self.status()['task_ids'], TaskQueue(self.node).execute(dict(project_id=self.pid, action='status'), self.owner)['task_ids'])

    def test_duplicate_completed_and_blocked_rejected(self):
        for identifier in ['TASK-B', 'TASK-DONE', 'UNKNOWN']:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError): self.act('add', identifier)
        self.act('add', 'TASK-A')
        with self.assertRaises(ValueError): self.act('add', 'TASK-A')

    def test_cascade_preview_confirm_and_stale_queue(self):
        for identifier in ['TASK-A', 'TASK-B', 'TASK-C', 'TASK-X']: self.act('add', identifier)
        view = self.status(); preview = self.act('remove-preview', 'TASK-A', view)
        self.assertEqual(['TASK-A', 'TASK-B', 'TASK-C'], preview['removed_ids'])
        with self.assertRaises(ValueError): self.act('remove', 'TASK-A', preview_sha256='bad')
        self.act('add', 'TASK-READY')
        with self.assertRaises(ValueError): self.act('remove', 'TASK-A', view, preview_sha256=preview['preview_sha256'])
        preview = self.act('remove-preview', 'TASK-A')
        self.act('remove', 'TASK-A', preview_sha256=preview['preview_sha256'])
        self.assertEqual(['TASK-X', 'TASK-READY'], self.status()['task_ids'])

    def test_removing_completed_item_keeps_dependents_and_queue_valid(self):
        for identifier in ['TASK-A', 'TASK-B', 'TASK-C']: self.act('add', identifier)
        self.save(BODY.replace('- [ ] [TASK-A]', '- [x] [TASK-A]'))
        self.assertTrue(self.status()['issues'])
        preview = self.act('remove-preview', 'TASK-A')
        self.assertEqual(['TASK-A'], preview['removed_ids'])
        result = self.act('remove', 'TASK-A', preview_sha256=preview['preview_sha256'])
        self.assertEqual(['TASK-B', 'TASK-C'], result['task_ids'])
        self.assertTrue(result['valid'], result['issues'])

    def test_completed_item_stops_cascade_but_unmet_chain_still_cascades(self):
        for identifier in ['TASK-A', 'TASK-B', 'TASK-C']: self.act('add', identifier)
        self.save(BODY.replace('- [ ] [TASK-B]', '- [x] [TASK-B]'))
        # B is completed, so C keeps its prerequisite even though A's removal reaches B.
        self.assertEqual(['TASK-A', 'TASK-B'], self.act('remove-preview', 'TASK-A')['removed_ids'])
        self.assertEqual(['TASK-B'], self.act('remove-preview', 'TASK-B')['removed_ids'])

    def test_owner_and_project_isolation(self):
        self.act('add', 'TASK-A'); self.assertEqual([], self.status(str(uuid4()))['task_ids'])
        second = ProjectCreation(self.node).create('Second', str(self.root / 'second'), str(uuid4()))['id']
        # No roadmap must fail closed, rather than read another project's queue.
        with self.assertRaises(ValueError): self.service.execute(dict(project_id=second, action='status'), self.owner)
        self.assertEqual(['TASK-A'], self.status()['task_ids'])

    def test_changed_head_requires_explicit_revalidation(self):
        self.act('add', 'TASK-A'); old = self.status(); self.save(BODY + '\nA description.\n')
        self.assertTrue(self.status()['stale']); self.assertFalse(self.status()['valid'])
        with self.assertRaises(ValueError): self.act('add', 'TASK-X')
        with self.assertRaises(ValueError): self.act('revalidate', view=old)
        self.assertTrue(self.act('revalidate')['valid']); self.act('add', 'TASK-X')

    def test_new_dependency_invalidates_existing_order_and_remove_recovers(self):
        self.act('add', 'TASK-A'); self.act('add', 'TASK-B')
        self.save(BODY.replace('  - depends_on: TASK-A', '  - depends_on: TASK-A, TASK-X'))
        self.assertTrue(self.status()['issues'])
        with self.assertRaises(ValueError): self.act('revalidate')
        preview = self.act('remove-preview', 'TASK-B')
        self.assertTrue(self.act('remove', 'TASK-B', preview_sha256=preview['preview_sha256'])['valid'])

    def test_before_and_after_replace_failure_no_blind_retry(self):
        self.act('add', 'TASK-A'); prior = self.status()
        def stop(stage):
            if stage == 'queue-before-replace': raise OSError('power failure')
        request = dict(project_id=self.pid, action='add', task_id='TASK-X', expected_head=prior['expected_head'], revision=prior['revision'])
        with self.assertRaises(OSError): self.service.execute(request, self.owner, checkpoint=stop)
        self.assertEqual(prior, self.status())
        def after(stage):
            if stage == 'queue-after-replace': raise OSError('power failure')
        with self.assertRaises(QueueOutcomeUnknown): self.service.execute(request, self.owner, checkpoint=after)
        self.assertEqual(['TASK-A', 'TASK-X'], self.status()['task_ids'])
        with self.assertRaises(ValueError): self.service.execute(request, self.owner)
        self.assertFalse(list(self.service.root.glob('*.tmp')))

    def test_flag_crash_keeps_value_and_audit_together_and_rejects_replay(self):
        self.act('add', 'TASK-A'); prior = self.status()
        request = dict(project_id=self.pid, action='set-flag', task_id='TASK-A',
                       flag='held', value=True, expected_head=prior['expected_head'], revision=prior['revision'])
        def stop(stage):
            if stage == 'queue-before-replace': raise OSError('power failure')
        with self.assertRaises(OSError): self.service.execute(request, self.owner, checkpoint=stop)
        self.assertEqual(prior, self.status())
        def after(stage):
            if stage == 'queue-after-replace': raise OSError('power failure')
        with self.assertRaises(QueueOutcomeUnknown): self.service.execute(request, self.owner, checkpoint=after)
        recovered = self.status()
        self.assertTrue(recovered['items'][0]['held'])
        self.assertEqual((False, True, self.owner, recovered['revision']),
                         tuple(recovered['flag_audit'][-1][k] for k in ('old', 'new', 'actor_id', 'revision')))
        with self.assertRaises(ValueError): self.service.execute(request, self.owner)
        self.assertEqual(recovered, self.status())

    def test_directory_sync_failure_reports_unknown_and_existing_state_is_readable(self):
        prior = self.status()
        with patch('spikes.task_queue.sync_dir', side_effect=OSError('I/O')):
            with self.assertRaises(QueueOutcomeUnknown): self.act('add', 'TASK-A', prior)
        self.assertEqual(['TASK-A'], self.status()['task_ids'])

    def test_scope_file_corruption_symlink_and_concurrent_lock_fail_closed(self):
        self.act('add', 'TASK-A')
        path = next(self.service.root.glob('*.json')); original = path.read_bytes()
        with self.service._lock(self.pid, self.owner):
            with self.assertRaises(ValueError): self.status()
        data=json.loads(original);data['owner_id']=str(uuid4());path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.status()
        path.write_bytes(original); path.unlink(); target = self.root / 'other'; target.write_bytes(original);path.symlink_to(target)
        with self.assertRaises(OSError): self.status()

    def test_protocol_rejects_extra_fields_and_bool_revision(self):
        with self.assertRaises(ValueError): self.service.execute(dict(project_id=self.pid, action='status', owner_id=self.owner), self.owner)
        with self.assertRaises(ValueError): self.service.execute(dict(project_id=self.pid, action='add', task_id='TASK-A', revision=False, expected_head=self.head), self.owner)

    def test_move_independent_item_persists_and_noop_keeps_revision(self):
        for identifier in ['TASK-A', 'TASK-B', 'TASK-C', 'TASK-X', 'TASK-READY']:
            self.act('add', identifier)
        before = self.status()
        moved = self.act('move', 'TASK-X', target_index=0)
        self.assertEqual(['TASK-X', 'TASK-A', 'TASK-B', 'TASK-C', 'TASK-READY'], moved['task_ids'])
        self.assertEqual(before['revision'] + 1, moved['revision'])
        self.assertEqual(moved, TaskQueue(self.node).execute(dict(project_id=self.pid, action='status'), self.owner))
        self.assertEqual(moved, self.act('move', 'TASK-X', target_index=0))
        flags = {item['id']: item for item in moved['items']}
        self.assertFalse(flags['TASK-X']['can_move_up'])
        self.assertTrue(flags['TASK-A']['can_move_up'])
        self.assertFalse(flags['TASK-B']['can_move_up'])
        self.assertIn('TASK-A', flags['TASK-B']['move_up_reason'])
        self.assertFalse(flags['TASK-B']['can_move_down'])
        self.assertTrue(flags['TASK-C']['can_move_down'])
        self.assertFalse(flags['TASK-READY']['can_move_down'])
        self.assertEqual(self.head, Projects(self.node).repository(self.pid).head())

    def test_move_rejects_direct_and_transitive_order_violations_without_write(self):
        for identifier in ['TASK-A', 'TASK-B', 'TASK-C', 'TASK-X']:
            self.act('add', identifier)
        path = next(self.service.root.glob('*.json')); original = path.read_bytes()
        for identifier, target, blocked in [('TASK-B', 0, 'TASK-A'), ('TASK-C', 0, 'TASK-B'), ('TASK-A', 2, 'TASK-B')]:
            with self.subTest(identifier=identifier, target=target):
                with self.assertRaisesRegex(ValueError, blocked):
                    self.act('move', identifier, target_index=target)
                self.assertEqual(original, path.read_bytes())
        self.assertEqual(self.head, Projects(self.node).repository(self.pid).head())

    def test_move_rejects_invalid_requests_stale_revisions_and_read_only_scope(self):
        self.act('add', 'TASK-A'); self.act('add', 'TASK-X'); original = self.status()
        for target in [-1, 2, True, 0.0, '0', None]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.act('move', 'TASK-X', target_index=target)
        for identifier in ['UNKNOWN', 'TASK-C', 'TASK-DONE']:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.act('move', identifier, target_index=0)
        with self.assertRaises(ValueError): self.act('move', 'TASK-X', target_index=0, extra=True)
        view = Projects(self.node).open(self.pid)
        with patch.object(self.service.projects, 'open', return_value=dict(view, read_only=True)):
            with self.assertRaises(ValueError): self.act('move', 'TASK-X', target_index=0, view=original)
        with self.assertRaises(ValueError):
            self.service.execute(dict(project_id=self.pid, action='move', task_id='TASK-X', target_index=0,
                                      expected_head=self.head, revision=0), str(uuid4()))
        self.assertEqual(original, self.status())
        self.act('move', 'TASK-X', target_index=0)
        with self.assertRaises(ValueError): self.act('move', 'TASK-A', target_index=0, view=original)
        self.save(BODY + '\nChanged roadmap.\n')
        stale = self.status()
        self.assertTrue(stale['stale'])
        self.assertTrue(all(not item['can_move_up'] and not item['can_move_down'] for item in stale['items']))
        with self.assertRaises(ValueError): self.act('move', 'TASK-A', target_index=0)

    def test_move_invalid_graph_and_busy_lock_keep_saved_order(self):
        self.act('add', 'TASK-A'); self.act('add', 'TASK-X')
        path = next(self.service.root.glob('*.json')); before = path.read_bytes(); view = self.status()
        with self.service._lock(self.pid, self.owner):
            with self.assertRaises(ValueError): self.act('move', 'TASK-X', target_index=0, view=view)
        self.assertEqual(before, path.read_bytes())
        self.save(BODY.replace('- [ ] [TASK-A] A', '- [ ] [TASK-A] A\n  - depends_on: TASK-C'))
        with self.assertRaises(ValueError): self.act('move', 'TASK-X', target_index=0, view=view)
        self.assertEqual(before, path.read_bytes())

    def test_move_process_crashes_recover_old_or_new_order_and_reject_replay(self):
        self.act('add', 'TASK-A'); self.act('add', 'TASK-X')
        code = '''
import json,os,sys
from spikes.task_queue import TaskQueue
request=json.loads(sys.argv[3])
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
TaskQueue(sys.argv[1]).execute(request,sys.argv[2],checkpoint=stop)
'''
        for stage in ['queue-before-replace', 'queue-after-replace']:
            with self.subTest(stage=stage):
                prior = self.status()
                request = dict(project_id=self.pid, action='move', task_id='TASK-X', target_index=0,
                               expected_head=prior['expected_head'], revision=prior['revision'])
                result = subprocess.run([sys.executable, '-c', code, str(self.node), self.owner,
                                         json.dumps(request), stage], capture_output=True, timeout=20)
                self.assertEqual(73, result.returncode, result.stderr)
                recovered = TaskQueue(self.node).execute(dict(project_id=self.pid, action='status'), self.owner)
                self.assertTrue(recovered['valid'])
                self.assertEqual(['TASK-A', 'TASK-X'] if stage=='queue-before-replace' else ['TASK-X', 'TASK-A'], recovered['task_ids'])
                self.assertEqual(prior['revision'] + (stage=='queue-after-replace'), recovered['revision'])
                if stage=='queue-after-replace':
                    with self.assertRaises(ValueError): self.service.execute(request, self.owner)
                self.assertEqual(self.head, Projects(self.node).repository(self.pid).head())

    def test_move_fsync_failure_and_external_git_change_report_unknown(self):
        self.act('add', 'TASK-A'); self.act('add', 'TASK-X')
        before = self.status()
        with patch('spikes.task_queue.sync_dir', side_effect=OSError('sync failed')):
            with self.assertRaises(QueueOutcomeUnknown): self.act('move', 'TASK-X', target_index=0, view=before)
        self.assertEqual(['TASK-X', 'TASK-A'], self.status()['task_ids'])
        self.act('move', 'TASK-X', target_index=1)
        prior = self.status()
        def external_commit(stage):
            if stage == 'queue-after-replace':
                from spikes.storage import Git
                (self.root/'project'/'external.txt').write_text('External Git writer')
                Git(self.root/'project').commit('External commit during queue move')
        request = dict(project_id=self.pid, action='move', task_id='TASK-X', target_index=0,
                       expected_head=prior['expected_head'], revision=prior['revision'])
        with self.assertRaises(QueueOutcomeUnknown): self.service.execute(request, self.owner, checkpoint=external_commit)
        self.assertTrue(self.status()['stale'])
        with self.assertRaises(ValueError): self.service.execute(request, self.owner)


class QueueBrowserLogicTests(unittest.TestCase):
    def test_adjacent_move_controls_match_topological_order_for_all_legal_permutations(self):
        nodes = {id_: dict(id=id_, checked=False, depends_on=deps) for id_, deps in [
            ('TASK-A', []), ('TASK-B', ['TASK-A']), ('TASK-C', ['TASK-B']),
            ('TASK-X', []), ('TASK-READY', ['TASK-DONE'])]}
        nodes['TASK-DONE'] = dict(id='TASK-DONE', checked=True, depends_on=[])
        def valid(order):
            positions = {id_: index for index, id_ in enumerate(order)}
            return all(nodes[parent]['checked'] or positions[parent] < positions[id_]
                       for id_ in order for parent in nodes[id_]['depends_on'])
        for order in permutations([id_ for id_ in nodes if id_!='TASK-DONE']):
            if not valid(order): continue
            for position, id_ in enumerate(order):
                flags = adjacent_moves(order, position, nodes, True)
                for direction, offset in [('up', -1), ('down', 1)]:
                    target = position + offset
                    expected = False
                    if 0 <= target < len(order):
                        swapped = list(order); swapped[position], swapped[target] = swapped[target], swapped[position]
                        expected = valid(swapped)
                    with self.subTest(order=order, moved=id_, direction=direction):
                        self.assertEqual(expected, flags['can_move_'+direction])

    def test_confirmation_filters_and_unknown_do_not_retry(self):
        import shutil
        import subprocess
        from spikes.desktop_ui import JS
        if not shutil.which('node'): self.skipTest('Node required for shared browser logic')
        source = JS[JS.index('let taskPlanProjection=null,taskPlanSelection=null;'):JS.index('function showTaskPlanDetail(item)')]
        prelude = '''
const assert=require('assert');
const elements=new Map();
function element(){return {children:[],disabled:false,textContent:'',replaceChildren(){this.children=[];},append(...nodes){this.children.push(...nodes);},addEventListener(){}};}
const document={querySelector(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element};
let activeProject={id:'project',head:'head',readOnly:false};
let calls=[],response=null,reject=false,confirm=false;
const window={confirm(){return confirm;}};
function renderTaskPlan(){}
async function projectRequest(path,body){calls.push(body);if(reject)throw new Error('unknown');return response;}
'''
        checks = '''
(async()=>{
response={project_id:'project',expected_head:'head',valid:true,issues:[],revision:1,following:['TASK-B'],task_ids:['TASK-A'],items:[{id:'TASK-A',title:'A'}]};
await loadTaskQueue();assert(taskPlanMatches({id:'TASK-B'},'following'));assert(!taskPlanMatches({id:'TASK-X'},'following'));
taskQueueView.flag_audit=[{task_id:'TASK-A',old:false,new:true,actor_id:'reviewer',at:1,revision:1}];
renderTaskQueue();
let row=document.querySelector('#task-queue-list').children[0];
assert.equal(row.children[2].ariaLabel,'Pozastavit: TASK-A');
assert.match(row.children[4].children[1].textContent,/reviewer.*Ne → Ano/);
taskQueueView.valid=false;renderTaskQueue();assert(document.querySelector('#task-queue-list').children[0].children[2].disabled);
taskQueueView.valid=true;
response={removed_ids:['TASK-A','TASK-B'],preview_sha256:'digest'};
await changeTaskQueue('remove','TASK-A');assert.equal(calls.filter(c=>c.action==='remove').length,0);
response={project_id:'project',expected_head:'head',valid:true,issues:[],revision:2,following:[],task_ids:[],items:[]};confirm=true;
// Return a preview and a different final status.
let original=projectRequest;
projectRequest=async(path,body)=>{if(body.action==='remove-preview'){calls.push(body);return {removed_ids:['TASK-A'],preview_sha256:'digest'};}return original(path,body);};
await changeTaskQueue('remove','TASK-A');assert.equal(calls.filter(c=>c.action==='remove').length,1);assert.equal(calls.at(-1).preview_sha256,'digest');
reject=true;await changeTaskQueue('add','TASK-X');assert.equal(taskQueueView,null);assert(document.querySelector('#task-queue-status').textContent.includes('unknown'));
let count=calls.length;await changeTaskQueue('add','TASK-X');assert.equal(calls.length,count);
reject=false;taskQueueView={project_id:'project',expected_head:'head',valid:true,issues:[],revision:9,task_ids:['TASK-A'],items:[]};
let release,moveRequest;projectRequest=(path,body)=>{moveRequest=body;return new Promise(resolve=>{release=resolve;});};
const moving=changeTaskQueue('move','TASK-A',0);await Promise.resolve();assert.equal(moveRequest.target_index,0);assert.equal(moveRequest.revision,9);
activeProject={id:'other-project',head:'other-head'};taskQueueView=null;release(response);await moving;assert.equal(taskQueueView,null);
})().catch(e=>{console.error(e);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', prelude+source+checks], capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
