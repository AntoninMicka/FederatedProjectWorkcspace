# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Real process crashes, Git, registration and native desktop creation."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.configuration import parse_node, parse_project, read_config
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.project_creation import CreationConflict, ProjectCreation, STAGES, default_node_path
from spikes.projects import Projects
from spikes.storage import Git
from tests import test_local_api


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native creation ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'New project'
        self.service = ProjectCreation(self.node)
        self.operation = str(uuid4())

    def create(self, **kwargs):
        return self.service.create('První projekt', self.root, self.operation, **kwargs)

    def record(self):
        with closing(sqlite3.connect(self.service.database)) as db:
            row = db.execute('SELECT record FROM creations WHERE id=?', (self.operation,)).fetchone()
        return json.loads(row[0])
    def check_created(self, receipt):
        node = parse_node(read_config(self.node), location=self.node)
        self.assertEqual(len(node['projects']), 1)
        binding = node['projects'][0]
        self.assertEqual(binding['project_id'], receipt['id'])
        self.assertEqual(binding['root'], str(self.root))
        meta = parse_project(read_config(self.root / 'project.json'))
        self.assertEqual(meta['id'], receipt['id'])
        self.assertEqual(meta['title'], 'První projekt')
        git = Git(self.root)
        self.assertEqual(git.head(), receipt['commit_id'])
        self.assertEqual(git.run('rev-list', '--count', 'HEAD').stdout.strip(), '1')
        self.assertEqual(git.run('ls-tree', '-r', '--name-only', 'HEAD').stdout, 'project.json\n')
        view = Projects(self.node).open(receipt['id'])
        self.assertEqual(view['artifacts'], [])
        self.assertEqual(view['commit_id'], receipt['commit_id'])
        self.assertEqual(self.node.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(binding['state_dir']).stat().st_mode & 0o777, 0o700)
        return node, meta

    def _existing_git_project(self, root, title='Legacy project', project_id=None):
        root.mkdir()
        project_id = project_id or str(uuid4())
        project_json = {
            'schema_version': 1,
            'id': project_id,
            'title': title,
            'created_at': '2026-01-01T00:00:00Z',
            'author_id': str(uuid4()),
        }
        payload = (json.dumps(project_json, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        (root / 'project.json').write_bytes(payload)
        git = Git(root)
        git.run('init', '--template=', '--initial-branch=main')
        (root / '.git').chmod(0o700)
        git.run('add', '--', 'project.json')
        git.run('commit', '-m', 'Import legacy project')
        return project_json

    def check_registered(self, root, receipt):
        node = parse_node(read_config(self.node), location=self.node)
        self.assertEqual(len(node['projects']), 1)
        binding = node['projects'][0]
        self.assertEqual(binding['project_id'], receipt['id'])
        self.assertEqual(binding['root'], str(root))
        result = parse_project(read_config(root / 'project.json'))
        self.assertEqual(result['id'], receipt['id'])
        self.assertEqual(result['title'], receipt['title'])
        git = Git(root)
        self.assertEqual(git.head(), receipt['commit_id'])
        self.assertEqual(Path(binding['state_dir']).stat().st_mode & 0o777, 0o700)
        return node, result

    def test_register_existing_git_project(self):
        root = self.base / 'existing-project'
        meta = self._existing_git_project(root)
        receipt = self.service.register(root, self.operation)
        self.assertEqual(receipt['id'], meta['id'])
        self.assertEqual(receipt['title'], meta['title'])
        self.assertEqual(receipt['commit_id'], Git(root).head())
        self.check_registered(root, receipt)

    def test_register_is_idempotent_for_same_operation(self):
        root = self.base / 'existing-project'
        meta = self._existing_git_project(root)
        first = self.service.register(root, self.operation)
        second = self.service.register(root, self.operation)
        self.assertEqual(first, second)
        self.assertEqual(len(Projects(self.node).list()), 1)
        self.check_registered(root, first)
        with self.assertRaises(CreationConflict):
            ProjectCreation(self.node).register(root, str(uuid4()))

    def test_register_blocks_duplicate_project_id(self):
        first_root = self.base / 'existing-first'
        first_meta = self._existing_git_project(first_root, title='First')
        first = self.service.register(first_root, self.operation)
        self.assertEqual(first['id'], first_meta['id'])
        self.check_registered(first_root, first)
        second_root = self.base / 'existing-second'
        self._existing_git_project(second_root, title='Second', project_id=first_meta['id'])
        with self.assertRaises(CreationConflict):
            self.service.register(second_root, str(uuid4()))
        self.assertEqual(len(Projects(self.node).list()), 1)


    def test_create_restart_receipt_and_two_projects(self):
        receipt = self.create()
        node, meta = self.check_created(receipt)
        self.assertEqual(ProjectCreation(self.node).create('První projekt', self.root, self.operation), receipt)
        self.assertIsNone(ProjectCreation(self.node).recover())
        other = self.service.create('Druhý projekt', self.base / 'second', str(uuid4()))
        second = parse_project(read_config(self.base / 'second' / 'project.json'))
        self.assertNotEqual(other['id'], receipt['id'])
        self.assertEqual(second['author_id'], meta['author_id'])
        self.assertNotEqual(meta['author_id'], node['id'])
        self.assertEqual(len(Projects(self.node).list()), 2)
        self.assertEqual(parse_node(read_config(self.node), location=self.node)['id'], node['id'])
        with self.assertRaises(CreationConflict):
            self.service.create('Changed request', self.root, self.operation)

    def test_crash_at_every_boundary_resumes_without_duplicate_commit(self):
        for stage in STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(dir=self.base) as case:
                parent = Path(case)
                node, root = parent / 'node.json', parent / 'project'
                op = str(uuid4())
                code = '''import os,sys
from spikes.project_creation import ProjectCreation
ProjectCreation(sys.argv[1]).create('První projekt', sys.argv[2], sys.argv[3],
 checkpoint=lambda stage: os._exit(78) if stage == sys.argv[4] else None)
'''
                run = subprocess.run([sys.executable, '-c', code, str(node), str(root), op, stage],
                                     capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 78, run.stdout + run.stderr)
                service = ProjectCreation(node)
                result = service.recover()
                replay = service.create('První projekt', root, op)
                if result is not None:
                    self.assertEqual(result, replay)
                self.assertEqual(Git(root).run('rev-list', '--count', 'HEAD').stdout.strip(), '1')
                self.assertEqual(Projects(node).open(replay['id'])['commit_id'], replay['commit_id'])
                self.assertEqual(len(Projects(node).list()), 1)
                self.assertIsNone(service.recover())
                self.assertEqual(list(parent.glob('.workspace-create-*')), [])

    def interrupt(self, at):
        def stop(stage):
            if stage == at:
                raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):
            self.create(checkpoint=stop)

    def test_unpublished_git_rebuild_has_same_commit(self):
        self.interrupt('built')
        repo = Path(self.record()['stage']) / 'repo'
        expected = Git(repo).head()
        (repo / '.git' / 'index.lock').write_bytes(b'interrupted own staging')
        receipt = self.service.recover()
        self.assertEqual(receipt['commit_id'], expected)
        self.check_created(receipt)

    def test_existing_targets_and_duplicate_registered_root_are_preserved(self):
        self.root.mkdir()
        sentinel = self.root / 'keep'; sentinel.write_bytes(b'existing')
        with self.assertRaises(CreationConflict): self.create()
        self.assertEqual(sentinel.read_bytes(), b'existing')
        self.assertFalse((self.root / '.git').exists())
        sentinel.unlink(); self.root.rmdir()
        node = dict(schema_version=1, id=str(uuid4()), name='Existing', projects=[
            dict(project_id=str(uuid4()), root=str(self.root), state_dir=str(self.base / 'old-state'))])
        self.node.write_text(json.dumps(node)); self.node.chmod(0o600)
        original = self.node.read_bytes()
        with self.assertRaises(ValueError): self.create()
        self.assertEqual(self.node.read_bytes(), original)
        self.assertFalse(self.root.exists())

    def test_foreign_empty_target_is_not_replaced_during_publication(self):
        self.interrupt('ready')
        self.root.mkdir()
        inode = self.root.stat().st_ino
        with self.assertRaises(OSError): self.service.recover()
        self.assertEqual(self.root.stat().st_ino, inode)
        self.assertEqual(list(self.root.iterdir()), [])
        self.root.rmdir()
        self.check_created(self.service.recover())

    def test_foreign_node_and_project_edits_stop_recovery(self):
        self.interrupt('indexed')
        node = dict(schema_version=1, id=str(uuid4()), name='Foreign', projects=[])
        self.node.write_text(json.dumps(node)); self.node.chmod(0o600)
        original = self.node.read_bytes()
        with self.assertRaises(CreationConflict): self.service.recover()
        self.assertEqual(self.node.read_bytes(), original)
        self.node.unlink()
        (self.root / 'keep.txt').write_bytes(b'foreign work')
        with self.assertRaises(CreationConflict): self.service.recover()
        self.assertEqual((self.root / 'keep.txt').read_bytes(), b'foreign work')
        self.assertFalse(self.node.exists())

    def test_existing_node_fields_survive_and_atomic_publish_failure_retries(self):
        node = dict(schema_version=1, id=str(uuid4()), name='My node', projects=[],
                    identity_credential_ref='credential:existing-key')
        self.node.write_text(json.dumps(node)); self.node.chmod(0o600)
        original = self.node.read_bytes()
        with patch('spikes.project_creation.os.replace', side_effect=OSError('write failure')):
            with self.assertRaises(OSError): self.create()
        self.assertEqual(self.node.read_bytes(), original)
        receipt = self.service.recover()
        created, _ = self.check_created(receipt)
        self.assertEqual(created['id'], node['id'])
        self.assertEqual(created['name'], node['name'])
        self.assertEqual(created['identity_credential_ref'], node['identity_credential_ref'])

    def test_busy_pending_timeout_and_invalid_input(self):
        with self.service._locked():
            with self.assertRaises(CreationConflict): self.create()
        self.service.timeout = 0
        with self.assertRaises(TimeoutError): self.create()
        record = self.record()
        with self.assertRaises(CreationConflict):
            ProjectCreation(self.node).create('Other', self.base / 'other', str(uuid4()))
        result = ProjectCreation(self.node).recover()
        self.assertEqual(result['id'], record['meta']['id'])
        self.check_created(result)
        for title in ('', ' ', 'x'*201, 'bad\nname'):
            with self.assertRaises(CreationConflict):
                self.service.create(title, self.base / 'another', str(uuid4()))

    def test_symlink_paths_and_unsupported_node_leave_inputs_unchanged(self):
        actual = self.base / 'actual'; actual.mkdir(mode=0o700)
        alias = self.base / 'alias'; alias.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(CreationConflict):
            self.service.create('Title', alias / 'project', self.operation)
        self.assertEqual(list(actual.iterdir()), [])
        self.node.write_text('{"schema_version": 99}'); self.node.chmod(0o600)
        with self.assertRaises(ValueError): self.create()
        self.assertFalse(self.service.runtime.exists())
        self.assertEqual(self.node.read_text(), '{"schema_version": 99}')

    def test_default_path_is_lazy_and_http_cannot_create(self):
        with patch.dict(os.environ, XDG_STATE_HOME=str(self.base / 'local')):
            path = default_node_path()
            self.assertEqual(path, self.base / 'local/federated-workspace/node.json')
            self.assertEqual(Projects(path).list(), [])
            self.assertIsNone(ProjectCreation(path).recover())
            self.assertFalse(path.parent.exists())
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            driver.rejected(server, path='/v1/projects/create', body=json.dumps(
                dict(title='Title', root=str(self.root), operation_id=self.operation)).encode())
        self.assertFalse(self.root.exists())
        self.assertFalse(self.node.exists())

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_native_dialog_creates_opens_and_reopens_after_restart(self):
        run = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node),
                              '--smoke', '--smoke-create', str(self.root)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        id_ = Projects(self.node).list()[0]['id']
        self.assertIn('desktop smoke: created=' + id_, run.stdout)
        before = Projects(self.node).open(id_)
        run = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node),
                              '--smoke', '--smoke-project', id_], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(Projects(self.node).open(id_), before)
        self.assertEqual(Git(self.root).run('rev-list', '--count', 'HEAD').stdout.strip(), '1')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_normal_desktop_start_recovers_and_opens_pending_creation(self):
        self.interrupt('ready')
        code = '''import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from spikes.desktop_creation import CreationController
from spikes.desktop import main
start = CreationController.start
def observed(self, action):
    succeeded = self.succeeded
    def ready(receipt):
        succeeded(receipt)
        if receipt is None:
            QApplication.instance().exit(6)
            return
        timer = QTimer(self.window)
        def checked(value):
            if value and not self.busy:
                timer.stop()
                print('native startup recovery opened', flush=True)
                self.window.close()
        timer.timeout.connect(lambda: self.window.centralWidget().page().runJavaScript(
            "!document.querySelector('#project-view').hidden && document.querySelector('#project-title').textContent==='První projekt'", 0, checked))
        timer.start(100)
        self.monitor = timer
    self.succeeded = ready
    QTimer.singleShot(12000, lambda: QApplication.instance().exit(7))
    start(self, action)
CreationController.start = observed
sys.argv = ['desktop', '--node', sys.argv[1]]
raise SystemExit(main())
'''
        run = subprocess.run([sys.executable, '-c', code, str(self.node)],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('native startup recovery opened', run.stdout)
        receipt = self.service.create('První projekt', self.root, self.operation)
        self.check_created(receipt)
