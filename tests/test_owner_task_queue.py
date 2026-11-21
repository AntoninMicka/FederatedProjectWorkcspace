# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
import json
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.owner_task_queue import OwnerTaskQueue
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_queue import TaskQueue, QueueOutcomeUnknown, canonical
from tests import test_task_queue as fixtures


class OwnerQueueTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TaskQueueTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.node, self.owner, self.pid = f.node, f.owner, f.pid
        self.service = OwnerTaskQueue(self.node)
        self.other = ProjectCreation(self.node).create('Second project', str(f.root/'second'), str(uuid4()))['id']
        Artifacts(self.node).save(dict(project_id=self.other, artifact_id=main_todo_id(self.other),
            base_head=Projects(self.node).plan_view(self.other)['commit_id'], title='Tasks',
            body='- [ ] [TASK-A] Same ID, other project\n- [ ] [TASK-X] Independent\n', new=True), str(uuid4()))

    def add(self, pid, task):
        q = TaskQueue(self.node); v = q.execute(dict(project_id=pid, action='status'), self.owner)
        return q.execute(dict(project_id=pid, action='add', task_id=task,
                              revision=v['revision'], expected_head=v['expected_head']), self.owner)

    def status(self, **kwargs):
        return self.service.status(self.owner, **kwargs)

    def move(self, pid, task, target, view=None, **kwargs):
        view = view or self.status()
        item = next(i for i in view['items'] if i['id']==task and i['project_id']==pid)
        return self.service.move(dict(action='move', project_id=pid, task_id=task, target_index=target,
            revision=view['revision'], view_revision=view['view_revision'], expected_head=item['expected_head']), self.owner, **kwargs)

    def refs(self, view):
        return [(i['project_id'],i['id']) for i in view['items']]

    def test_interleaving_same_ids_reload_and_project_projection(self):
        self.add(self.pid,'TASK-A');self.add(self.pid,'TASK-X');self.add(self.other,'TASK-A')
        view=self.move(self.other,'TASK-A',1)
        self.assertEqual(self.refs(view),[(self.pid,'TASK-A'),(self.other,'TASK-A'),(self.pid,'TASK-X')])
        q=TaskQueue(self.node)
        before=q.execute(dict(project_id=self.pid,action='status'),self.owner)
        view=self.move(self.pid,'TASK-X',0)
        self.assertEqual(self.refs(OwnerTaskQueue(self.node).status(self.owner)),self.refs(view))
        after=q.execute(dict(project_id=self.pid,action='status'),self.owner)
        self.assertEqual(after['task_ids'],['TASK-X','TASK-A'])
        self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual(after['expected_head'],before['expected_head'])
        self.assertEqual(q.execute(dict(project_id=self.other,action='status'),self.owner)['task_ids'],['TASK-A'])

    def test_dependencies_stale_noop_and_invalid_index(self):
        self.add(self.pid,'TASK-A');self.add(self.pid,'TASK-B');self.add(self.other,'TASK-A')
        old=self.status()
        with self.assertRaisesRegex(ValueError,'předpoklad'):self.move(self.pid,'TASK-B',0,old)
        self.assertEqual(self.status()['revision'],old['revision'])
        self.assertEqual(self.move(self.pid,'TASK-A',0)['revision'],old['revision'])
        self.move(self.other,'TASK-A',0)
        with self.assertRaisesRegex(ValueError,'Fronta se změnila'):self.move(self.pid,'TASK-A',1,old)
        with self.assertRaises(ValueError):self.move(self.pid,'TASK-A',True)
        with self.assertRaises(ValueError):self.move(self.pid,'TASK-A',999)
        self.fixture.save('- [ ] [TASK-A] Changed\n- [ ] [TASK-B] B\n  - depends_on: TASK-A\n')
        with self.assertRaisesRegex(ValueError,'Roadmapa se změnila'):self.move(self.pid,'TASK-A',1,self.status_before_head(old))

    def status_before_head(self, old):
        # Keep current owner revision but an old project snapshot.
        current=self.status()
        return dict(old,revision=current['revision'],view_revision=current['view_revision'])

    def test_scope_permissions_and_other_owner_isolation(self):
        self.add(self.pid,'TASK-A');self.add(self.other,'TASK-A');self.add(self.pid,'TASK-X')
        allowed=lambda pid:pid==self.pid
        view=self.status(can_read=allowed,can_write=lambda pid:False)
        self.assertTrue(all(i['project_id']==self.pid and i['read_only'] for i in view['items']))
        self.assertEqual(self.service.status(str(uuid4()))['items'],[])
        with self.assertRaises(ValueError):self.move(self.pid,'TASK-A',1,view,can_read=allowed,can_write=lambda pid:False)
        self.move(self.pid,'TASK-X',0,self.status(can_read=allowed),can_read=allowed)
        self.assertEqual(self.refs(self.status()),[(self.pid,'TASK-X'),(self.other,'TASK-A'),(self.pid,'TASK-A')])

    def test_legacy_files_imported_together_once_without_modifying_sources(self):
        states=[]
        for pid in (self.pid,self.other):
            head=Projects(self.node).plan_view(pid)['commit_id']
            states.append(dict(schema=1,project_id=pid,owner_id=self.owner,revision=4,
                project_head=head,task_ids=['TASK-A'],held_task_ids=['TASK-A'],flag_audit=[]))
        with self.service._lock(None,self.owner) as path:
            for state in states:
                legacy=self.service.root/(hashlib.sha256(canonical([state['project_id'],self.owner])).hexdigest()+'.json')
                legacy.write_bytes(canonical(state));legacy.chmod(0o600)
            self.assertFalse(path.exists())
        view=self.status();self.assertEqual(len(view['items']),2);self.assertTrue(all(i['held'] for i in view['items']))
        with self.service._lock(None,self.owner) as path:self.assertFalse(path.exists())
        self.move(self.other,'TASK-A',0,view)
        for state in states:
            legacy=self.service.root/(hashlib.sha256(canonical([state['project_id'],self.owner])).hexdigest()+'.json')
            self.assertEqual(json.loads(legacy.read_bytes()),state)
        # Old files can never reintroduce removed refs after the owner snapshot exists.
        q=TaskQueue(self.node);v=q.execute(dict(project_id=self.pid,action='status'),self.owner)
        preview=q.execute(dict(project_id=self.pid,action='remove-single-preview',task_id='TASK-A',revision=v['revision'],expected_head=v['expected_head']),self.owner)
        q.execute(dict(project_id=self.pid,action='remove-single',task_id='TASK-A',revision=v['revision'],expected_head=v['expected_head'],preview_sha256=preview['preview_sha256']),self.owner)
        self.assertEqual(self.refs(self.status()),[(self.other,'TASK-A')])

    def test_atomic_move_boundaries_and_fsync_unknown(self):
        self.add(self.pid,'TASK-A');self.add(self.other,'TASK-A');before=self.status()
        def fail(stage):
            if stage=='queue-before-replace':raise OSError('before')
        with self.assertRaises(OSError):self.move(self.other,'TASK-A',0,before,checkpoint=fail)
        self.assertEqual(self.refs(self.status()),self.refs(before))
        def after(stage):
            if stage=='queue-after-replace':raise OSError('after')
        with self.assertRaises(QueueOutcomeUnknown):self.move(self.other,'TASK-A',0,before,checkpoint=after)
        current=self.status();self.assertEqual(self.refs(current),list(reversed(self.refs(before))))
        self.assertEqual(current['revision'],before['revision']+1)
        with patch('spikes.task_queue.sync_dir',side_effect=OSError('fsync')):
            with self.assertRaises(QueueOutcomeUnknown):self.move(self.pid,'TASK-A',0,current)
        self.assertEqual(self.refs(self.status()),self.refs(before))

    def test_project_mutations_merge_without_losing_interleaved_other_refs(self):
        self.add(self.pid,'TASK-A');self.add(self.other,'TASK-A');self.add(self.pid,'TASK-X')
        self.add(self.other,'TASK-X')
        view=self.move(self.other,'TASK-X',1)
        old=[ref for ref in self.refs(view) if ref[0]==self.other]
        q=TaskQueue(self.node);v=q.execute(dict(project_id=self.pid,action='status'),self.owner)
        q.execute(dict(project_id=self.pid,action='move',task_id='TASK-X',target_index=0,revision=v['revision'],expected_head=v['expected_head']),self.owner)
        self.assertEqual([r for r in self.refs(self.status()) if r[0]==self.other],old)
        self.assertEqual([r[1] for r in self.refs(self.status()) if r[0]==self.pid],['TASK-X','TASK-A'])

    def test_owner_lock_serializes_different_projects_and_scope_change_rejects_move(self):
        self.add(self.pid,'TASK-A');self.add(self.other,'TASK-A')
        before=self.status()
        with self.service._lock(self.pid,self.owner):
            with self.assertRaises(ValueError):self.add(self.other,'TASK-X')
        with self.assertRaisesRegex(ValueError,'rozsah'):
            self.move(self.pid,'TASK-A',0,before,can_read=lambda pid:pid==self.pid)
        self.assertEqual(self.refs(self.status()),self.refs(before))

    def test_unavailable_project_does_not_block_independent_project_and_is_not_disclosed(self):
        self.add(self.pid,'TASK-A');self.add(self.pid,'TASK-X');self.add(self.other,'TASK-A')
        original=self.service.projects.plan_view
        def unavailable(pid):
            if pid==self.other:raise ValueError('private details')
            return original(pid)
        with patch.object(self.service.projects,'plan_view',side_effect=unavailable):
            view=self.status()
            self.assertEqual(len(view['items']),2)
            self.assertTrue(view['issues'])
            self.assertNotIn('private details',str(view))
            result=self.move(self.pid,'TASK-X',0,view)
            self.assertEqual([i['id'] for i in result['items']],['TASK-X','TASK-A'])
        self.assertEqual(self.refs(self.status())[-1],(self.other,'TASK-A'))
