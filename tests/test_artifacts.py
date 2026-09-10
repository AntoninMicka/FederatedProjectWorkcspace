"""Editor contract against real registered projects, Git, journal and native widgets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts, checklist_items, main_todo_id
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.storage import Git
from tests.fixtures import markdown, metadata


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.id = self.created['id']
        self.service = Artifacts(self.node)
        self.git = Git(self.root)

    def request(self, *, id_=None, body='- [ ] Úkol\n', title='Document', new=True):
        return dict(project_id=self.id, artifact_id=id_ or str(uuid4()), base_head=self.git.head(),
                    title=title, body=body, new=new)

    def test_create_edit_restart_main_todo_and_exact_metadata(self):
        id_ = main_todo_id(self.id)
        request = self.request(id_=id_, title='Hlavní TODO')
        receipt = self.service.save(request, str(uuid4()))
        self.assertEqual(receipt['commit_id'], self.git.head())
        files = self.git.snapshot(self.git.head()); entities = validate_snapshot(files)
        self.assertEqual(entities[id_]['author_id'], ProjectCreation(self.node).author_id())
        self.assertEqual(files[f'artifacts/{id_}/content.md'], request['body'].encode())
        self.assertEqual(set(files), {f'artifacts/{id_}/content.md', f'artifacts/{id_}/metadata.json'})
        created_at = entities[id_]['created_at']
        request = self.request(id_=id_, title='Moje úkoly', new=False, body='- [x] Úkol\n')
        self.service.save(request, str(uuid4()))
        view = Artifacts(self.node).open(self.id)
        self.assertEqual(view['main_todo_id'], id_)
        self.assertEqual(view['documents'][0]['body'], request['body'])
        self.assertEqual(view['documents'][0]['metadata']['created_at'], created_at)
        self.assertEqual(self.git.run('status', '--porcelain').stdout, '')
        with self.assertRaises(ValidationError):
            self.service.save(self.request(id_=id_), str(uuid4()))

    def test_sidebar_reads_committed_tree_without_recovering_or_writing(self):
        from spikes.workspace import PendingOperation
        from spikes.journal import snapshot
        self.assertIsNone(self.service.projects.open(self.id)['main_todo'])
        body = '- [ ] Parent\n  - [x] Child\n    * [ ] Grandchild\n- [X] Sibling\n```\n- [ ] Hidden\n```\n'
        request = self.request(id_=main_todo_id(self.id), body=body, title='Project tasks')
        self.service.save(request, str(uuid4()))
        before = snapshot(self.root); head = self.git.head()
        view = self.service.projects.open(self.id)
        todo = view['main_todo']
        self.assertEqual(todo['title'], 'Project tasks')
        self.assertEqual(todo['items'], [dict(title=title, depth=depth, checked=checked) for title, depth, checked in
                         [('Parent', 0, False), ('Child', 1, True), ('Grandchild', 2, False), ('Sibling', 0, True)]])
        self.assertEqual((todo['completed'], todo['total'], todo['truncated']), (2, 4, False))
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.git.head(), head)
        path = self.root / 'artifacts' / request['artifact_id'] / 'content.md'
        path.write_text('- [x] Uncommitted')
        self.assertEqual(self.service.projects.open(self.id), view)
        path.write_bytes(before[str(path.relative_to(self.root))])
        update = self.request(id_=request['artifact_id'], body='- [x] Updated', new=False)
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError): self.service.save(update, str(uuid4()), checkpoint=crash)
        with self.assertRaises(PendingOperation): self.service.projects.open(self.id)
        self.assertEqual(self.git.head(), head)
        self.assertEqual(snapshot(self.root), before)
        self.service.open(self.id)
        refreshed = self.service.projects.open(self.id)
        self.assertNotEqual(refreshed['commit_id'], head)
        self.assertEqual(refreshed['main_todo']['items'][0]['title'], 'Updated')

    def test_sidebar_empty_unsupported_and_bounded_projection(self):
        request = self.request(id_=main_todo_id(self.id), body='# Empty\n')
        self.service.save(request, str(uuid4()))
        self.assertEqual(self.service.projects.open(self.id)['main_todo']['total'], 0)
        update = self.request(id_=request['artifact_id'], body='- [ ] Item\n' * 1001, new=False)
        self.service.save(update, str(uuid4()))
        todo = self.service.projects.open(self.id)['main_todo']
        self.assertEqual((len(todo['items']), todo['total'], todo['truncated']), (1000, 1001, True))
        path = self.root / 'artifacts' / request['artifact_id'] / 'content.md'
        path.write_bytes(b'\xff'); self.git.commit('Unsupported UTF-8 document')
        self.assertEqual(self.service.projects.open(self.id)['main_todo']['status'], 'unsupported')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires actual WebEngine sidebar')
    def test_real_sidebar_tree_readonly_safe_text_and_restart(self):
        request = self.request(id_=main_todo_id(self.id), title='<img src=x onerror=alert(1)>',
                               body='- [ ] <img src=x onerror=alert(1)>\n  - [x] Child\n- [ ] Sibling\n')
        self.service.save(request, str(uuid4()))
        for body in (None, '- [x] Changed\n  - [ ] New child\n'):
            if body:
                self.service.save(self.request(id_=request['artifact_id'], body=body, new=False), str(uuid4()))
            head = self.git.head()
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node),
                                     '--smoke', '--smoke-project', self.id], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('rendered rows verified', result.stdout)
            self.assertEqual(self.git.head(), head)
            self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    def test_retry_receipt_binds_complete_request_even_after_later_commit(self):
        request, operation = self.request(), str(uuid4())
        receipt = self.service.save(request, operation)
        later = self.service.save(self.request(), str(uuid4()))
        self.assertEqual(self.service.save(request, operation), receipt)
        self.assertEqual(self.git.head(), later['commit_id'])
        for field, value in [('title', 'Other'), ('body', 'Other'), ('new', False),
                             ('artifact_id', str(uuid4())), ('base_head', later['commit_id'])]:
            with self.assertRaises(ValidationError):
                self.service.save(dict(request, **{field: value}), operation)
        self.assertEqual(self.git.head(), later['commit_id'])

    def test_stale_head_dirty_projection_invalid_input_and_unregistered_id(self):
        stale = self.request()
        self.service.save(self.request(), str(uuid4()))
        head = self.git.head()
        with self.assertRaises(ValidationError): self.service.save(stale, str(uuid4()))
        for field, value in [('project_id', str(uuid4())), ('title', ''), ('new', 'yes'),
                             ('artifact_id', '../file'), ('body', 'x' * (1024 * 1024 + 1))]:
            with self.assertRaises(ValidationError):
                self.service.save(dict(self.request(), **{field: value}), str(uuid4()))
        (self.root / 'foreign.txt').write_text('keep')
        with self.assertRaises(ValidationError): self.service.save(self.request(), str(uuid4()))
        self.assertEqual((self.root / 'foreign.txt').read_text(), 'keep')
        self.assertEqual(self.git.head(), head)
        self.assertIsNone(self.service.workspace(self.id).recover())

    def test_frontmatter_edit_preserves_provenance_privacy_relations_and_content(self):
        id_ = str(uuid4()); meta = metadata('Imported', id_)
        meta.update(privacy='confidential', provenance='external', tags=['keep'], description='Keep too')
        path = self.root / 'artifacts' / id_ / 'note.md'; path.parent.mkdir(parents=True)
        path.write_bytes(markdown(meta)); self.git.commit('Existing frontmatter')
        body = '# Title\n\n<img src="https://example.invalid/private">\n- [x] Done\n'
        self.service.save(self.request(id_=id_, body=body, title='Edited', new=False), str(uuid4()))
        doc = self.service.open(self.id)['documents'][0]
        self.assertEqual(doc['body'], body)
        self.assertEqual(doc['metadata'], dict(meta, title='Edited'))
        self.assertEqual(list(self.git.snapshot(self.git.head())), [f'artifacts/{id_}/note.md'])

    def test_process_crashes_and_native_open_recover_exactly_once(self):
        script = '''
import json, os, sys
from spikes.artifacts import Artifacts
request = json.loads(sys.argv[2])
def checkpoint(stage):
    if stage == sys.argv[4]: os._exit(73)
Artifacts(sys.argv[1]).save(request, sys.argv[3], checkpoint=checkpoint)
'''
        for stage in ('prepared', 'file:0', 'file:1', 'applied', 'files-applied', 'commit-created',
                      'commit-ready', 'ref-updated', 'committed', 'git-indexed', 'indexed', 'completed'):
            with self.subTest(stage=stage):
                request, operation = self.request(), str(uuid4())
                result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(request), operation, stage],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 73, result.stderr)
                view = Artifacts(self.node).open(self.id)
                receipt = self.service.save(request, operation)
                self.assertEqual(receipt['commit_id'], view['commit_id'])
                self.assertEqual(self.git.run('rev-list', '--count', request['base_head'] + '..HEAD').stdout.strip(), '1')
                self.assertEqual(next(d['body'] for d in view['documents'] if d['id'] == request['artifact_id']), request['body'])
                self.assertIsNone(self.service.workspace(self.id).recover())

    def test_pending_retry_and_foreign_edit_are_preserved(self):
        request, operation = self.request(), str(uuid4())
        def crash(stage):
            if stage == 'file:0': raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError): self.service.save(request, operation, checkpoint=crash)
        path = self.root / 'artifacts' / request['artifact_id'] / 'content.md'
        path.write_text('foreign edit')
        from spikes.journal import RecoveryConflict
        with self.assertRaises(RecoveryConflict): self.service.save(request, operation)
        self.assertEqual(path.read_text(), 'foreign edit')
        path.write_text(request['body'])
        receipt = self.service.save(request, operation)
        self.assertEqual(self.git.head(), receipt['commit_id'])

    def test_busy_deadline_and_missing_index(self):
        ws = self.service.workspace(self.id)
        with ws.journal.lock():
            with self.assertRaises(BlockingIOError): self.service.open(self.id)
        with self.assertRaises(TimeoutError): Artifacts(self.node, timeout=-1).open(self.id)
        self.service.save(self.request(), str(uuid4()))
        ws.index.path.unlink()
        self.assertEqual(len(self.service.open(self.id)['documents']), 1)

    def test_two_writers_cannot_create_two_main_todos(self):
        from concurrent.futures import ThreadPoolExecutor
        request = self.request(id_=main_todo_id(self.id))
        def save():
            try:
                return self.service.save(request, str(uuid4()))
            except (ValueError, BlockingIOError):
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: save(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.service.open(self.id)['documents']), 1)
        self.assertEqual(self.git.run('rev-list', '--count', request['base_head'] + '..HEAD').stdout.strip(), '1')

    def test_checklists_ignore_fences_preserve_unicode_and_offsets(self):
        body = '😀\n- [ ] A\n  * [X] B\n```md\n- [ ] Code\n```\n~~~\n+ [x] Also code\n~~~\n+ [x] C\n'
        items = checklist_items(body)
        self.assertEqual([x['title'] for x in items], ['A', 'B', 'C'])
        self.assertEqual([x['checked'] for x in items], [False, True, True])
        for entry in items:
            self.assertIn(body[entry['offset']], ' xX')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt widgets')
    def test_native_editor_checklist_save_reopen_and_todo_identity(self):
        script = '''
import sys, time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from spikes.desktop_editor import EditorDialog
from spikes.artifacts import Artifacts
app = QApplication([])
service = Artifacts(sys.argv[1])
original_save = service.save
lost = [True]
def save_with_lost_response(*args, **kwargs):
    receipt = original_save(*args, **kwargs)
    if lost[0]:
        lost[0] = False
        raise RuntimeError('Simulated lost response')
    return receipt
service.save = save_with_lost_response
def idle(dialog):
    deadline = time.monotonic() + 10
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert not dialog.busy, dialog.status.text()
for pass_ in range(2):
    dialog = EditorDialog(service, sys.argv[2], todo=True)
    dialog.show(); idle(dialog)
    assert dialog.current['id'] == dialog.view['main_todo_id']
    if pass_ == 0:
        dialog.body.setPlainText('😀\\n- [ ] A\\n```\\n- [ ] Hidden\\n```\\n')
        assert dialog.checks.count() == 1
        dialog.checks.item(0).setCheckState(Qt.CheckState.Checked)
        assert '- [x] A' in dialog.body.toPlainText()
        dialog.save_button.click(); idle(dialog)
        assert dialog.pending and dialog.body.isReadOnly()
        assert '- [x] A' in dialog.body.toPlainText()
        operation = dialog.pending[1]
        dialog.save_button.click(); idle(dialog)
        assert service.workspace(sys.argv[2]).receipt(operation) is not None
        assert dialog.status.text() == 'Uloženo do Gitu.', dialog.status.text()
        assert not dialog.dirty
    else:
        assert dialog.checks.item(0).checkState() == Qt.CheckState.Checked
        assert not dialog.dirty
    dialog.close(); app.processEvents()
print('native editor verified')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.node), self.id],
                                capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native editor verified', result.stdout)
