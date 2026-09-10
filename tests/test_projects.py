"""Registered reads exercise real Git/SQLite, HTTP authorization and optional Qt."""
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from spikes.desktop import request_policy
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.metadata import ValidationError
from spikes.projects import Projects
from spikes.storage import Git, StaleIndex
from spikes.workspace import PendingOperation, Workspace
from tests.fixtures import AUTHOR, ENTITY, OTHER, encoded, markdown, metadata
from tests.test_configuration import project
from tests import test_local_api


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project reads ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node_path = self.base / 'node.json'
        self.node = dict(schema_version=1, id=AUTHOR, name='Local', projects=[])
        self.gits = []
        for id_, title in [(ENTITY, '<img src=x onerror=alert(1)>'), (OTHER, 'Druhý projekt')]:
            root, state = self.base / id_, self.base / (id_ + '-state')
            root.mkdir(mode=0o755); state.mkdir(mode=0o700)
            git = Git(root); git.run('init', '--initial-branch=main')
            (root / '.git').chmod(0o755)
            (root / 'project.json').write_bytes(encoded(dict(project(), id=id_, title=title)))
            artifact = root / 'artifacts' / id_
            artifact.mkdir(parents=True)
            (artifact / 'note.md').write_bytes(markdown(metadata(title, id_)))
            git.commit('Existing project')
            self.node['projects'].append(dict(project_id=id_, root=str(root), state_dir=str(state)))
            self.gits.append(git)
        self.save_node()
        self.projects = Projects(self.node_path)

    def save_node(self):
        self.node_path.write_bytes(encoded(self.node))

    def state(self, i=0):
        return Path(self.node['projects'][i]['state_dir'])

    def test_catalog_labels_are_committed_and_do_not_initialize_state(self):
        rows = self.projects.catalog()
        self.assertEqual([r['id'] for r in rows], [ENTITY, OTHER])
        self.assertEqual(rows[0]['title'], '<img src=x onerror=alert(1)>')
        self.assertTrue(all(r['available'] for r in rows))
        self.assertEqual(list(self.state().iterdir()), [])
        self.assertEqual(list(self.state(1).iterdir()), [])
        # An invalid registration must not suppress other projects or leak its path.
        (self.gits[0].root / 'project.json').write_bytes(b'bad')
        rows = self.projects.catalog()
        self.assertFalse(rows[0]['available'])
        self.assertEqual(rows[0]['title'], 'Nedostupný projekt')
        self.assertTrue(rows[1]['available'])
        self.assertNotIn(str(self.base), str(rows))
        self.assertEqual(list(self.state().iterdir()), [])

    def test_two_projects_restart_missing_and_stale_index(self):
        self.assertEqual(self.projects.list(), [{'id': ENTITY}, {'id': OTHER}])
        for i, id_ in enumerate((ENTITY, OTHER)):
            result = self.projects.open(id_)
            self.assertEqual(result['commit_id'], self.gits[i].head())
            self.assertEqual(result['artifacts'], [dict(id=id_, title=result['title'])])
            self.assertEqual(self.gits[i].run('status', '--porcelain').stdout, '')
            self.assertEqual(Projects(self.node_path).open(id_), result)
            (self.state(i) / 'index.sqlite').unlink()
            self.assertEqual(self.projects.open(id_), result)
        path = self.gits[0].root / 'artifacts' / ENTITY / 'note.md'
        path.write_bytes(markdown(metadata('New committed title')))
        head = self.gits[0].commit('Change artifact')
        path.write_bytes(markdown(metadata('Uncommitted draft')))
        result = self.projects.open(ENTITY)
        self.assertEqual(result['commit_id'], head)
        self.assertEqual(result['artifacts'][0]['title'], 'New committed title')
        self.assertEqual(self.projects.open(OTHER)['artifacts'][0]['title'], 'Druhý projekt')

    def test_invalid_registration_and_config_do_not_initialize_state(self):
        original = deepcopy(self.node)
        for changes in [dict(project_id=AUTHOR), dict(root=str(self.base / 'missing')),
                        dict(state_dir=str(self.gits[0].root / 'state'))]:
            self.node = deepcopy(original)
            self.node['projects'][0].update(changes); self.save_node()
            with self.assertRaises((ValueError, OSError)):
                self.projects.open(self.node['projects'][0]['project_id'])
            self.assertEqual(list(Path(original['projects'][0]['state_dir']).iterdir()), [])
        self.node = original; self.save_node()
        config = self.gits[0].root / 'project.json'
        for value in [dict(project(), id=OTHER), dict(project(), schema_version=2)]:
            config.write_bytes(encoded(value)); self.gits[0].commit('Invalid config')
            with self.assertRaises(ValidationError): self.projects.open(ENTITY)
            self.assertEqual(list(self.state().iterdir()), [])
        config.write_bytes(encoded(project())); self.gits[0].commit('Valid config')
        config.write_bytes(encoded(dict(project(), title='Uncommitted')))
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)
        self.assertEqual(list(self.state().iterdir()), [])

    def test_unsafe_state_files_and_root_alias_are_rejected(self):
        target = self.base / 'sentinel'; target.write_bytes(b'untouched')
        link = self.state() / 'index.sqlite'; link.symlink_to(target)
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)
        self.assertEqual(target.read_bytes(), b'untouched'); link.unlink()
        os.link(target, link)
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)
        link.unlink()
        alias = self.base / 'alias'; alias.symlink_to(self.gits[0].root, target_is_directory=True)
        self.node['projects'][0]['root'] = str(alias); self.save_node()
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)

    def test_pending_is_not_recovered_and_corrupt_index_is_not_served(self):
        self.projects.open(ENTITY)
        ws = Workspace(self.gits[0].root, self.state())
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('simulated interruption')
        with self.assertRaises(RuntimeError):
            ws.apply({f'artifacts/{ENTITY}/note.md': markdown(metadata('Pending'))},
                     author_name='Test', author_email='test@example.invalid', message='Pending', checkpoint=crash)
        before = self.gits[0].head()
        with self.assertRaises(PendingOperation): self.projects.open(ENTITY)
        self.assertEqual(self.gits[0].head(), before)
        ws.recover()
        with closing(sqlite3.connect(self.state() / 'index.sqlite')) as db, db:
            db.execute("UPDATE entities SET title='Forged'")
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)
        (self.state() / 'index.sqlite').unlink()
        self.assertEqual(self.projects.open(ENTITY)['artifacts'][0]['title'], 'Pending')

    def test_interrupted_initialization_and_rebuild_can_be_retried(self):
        with patch('spikes.workspace.Index', side_effect=RuntimeError('before index initialization')):
            with self.assertRaises(RuntimeError): self.projects.open(ENTITY)
        self.assertTrue((self.state() / 'journal.sqlite').exists())
        previous = self.projects.open(ENTITY)
        path = self.gits[0].root / 'artifacts' / ENTITY / 'note.md'
        path.write_bytes(markdown(metadata('New title')))
        head = self.gits[0].commit('Updated')
        with closing(sqlite3.connect(self.state() / 'index.sqlite')) as db, db:
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON entities BEGIN SELECT RAISE(ABORT, 'interrupted'); END")
        with self.assertRaises(sqlite3.Error): self.projects.open(ENTITY)
        with closing(sqlite3.connect(self.state() / 'index.sqlite')) as db, db:
            self.assertEqual(db.execute('SELECT commit_id FROM state').fetchone()[0], previous['commit_id'])
            self.assertEqual(db.execute('SELECT title FROM entities').fetchone()[0], previous['title'])
            db.execute('DROP TRIGGER fail_insert')
        self.assertEqual(self.projects.open(ENTITY)['commit_id'], head)
        self.assertEqual(self.gits[0].run('status', '--porcelain').stdout, '')

    def test_empty_catalog_and_empty_project(self):
        self.assertEqual(Projects().list(), [])
        with self.assertRaises(ValidationError): Projects().open(ENTITY)
        artifact = self.gits[0].root / 'artifacts' / ENTITY / 'note.md'
        artifact.unlink(); self.gits[0].commit('Remove artifact')
        self.assertEqual(self.projects.open(ENTITY)['artifacts'], [])

    def test_launcher_resolves_node_relative_to_caller(self):
        repo = Path(__file__).resolve().parents[1]
        launcher_dir = self.base / 'launcher'; launcher_dir.mkdir()
        launcher = launcher_dir / 'run.sh'; launcher.write_bytes((repo / 'run.sh').read_bytes())
        launcher.chmod(0o755)
        binaries = self.base / 'bin'; binaries.mkdir()
        python = binaries / 'python3'
        python.write_text('#!/bin/sh\nif [ "$1" = -m ]; then printf "%s\\n" "$@"; fi\n')
        python.chmod(0o755)
        env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'])
        result = subprocess.run([str(launcher), 'desktop', '--node', 'node.json'], cwd=self.base,
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['-m', 'spikes.desktop', '--node', str(self.node_path)])
        result = subprocess.run([str(launcher), 'desktop', '--node'], cwd=self.base,
                                env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_invalid_commit_never_returns_old_rows_and_head_change_is_rejected(self):
        previous = self.projects.open(ENTITY)
        path = self.gits[0].root / 'artifacts' / ENTITY / 'note.md'
        path.write_bytes(b'no metadata'); self.gits[0].commit('Invalid artifact')
        with self.assertRaises(ValidationError): self.projects.open(ENTITY)
        with closing(sqlite3.connect(self.state() / 'index.sqlite')) as db:
            self.assertEqual(db.execute('SELECT commit_id FROM state').fetchone()[0], previous['commit_id'])
        self.gits[0].run('reset', '--hard', previous['commit_id'])
        ws = Workspace(self.gits[0].root, self.state())
        with patch.object(ws.git, 'head', side_effect=[previous['commit_id'], previous['commit_id'], 'changed']):
            with self.assertRaises(StaleIndex): ws.read_project(ENTITY)

    def test_real_api_auth_validation_and_no_path_access(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler, projects=self.projects) as server:
            for path, body in [('/v1/projects', b'{}'), ('/v1/projects', b'{"details":true}'), ('/v1/projects/open', encoded(dict(project_id=ENTITY)))]:
                driver.rejected(server, path=path, body=body, headers={'Authorization': None})
                driver.rejected(server, path=path, body=body, headers={'Origin': 'http://evil.example'})
                response = driver.request(server, path=path, body=body)
                self.assertIn(b' 200 ', response.split(b'\r\n')[0])
                self.assertNotIn(str(self.base).encode(), response)
                self.assertEqual(request_policy(server.origin+path, server.origin, 'POST', server.origin), 'authenticate')
                self.assertEqual(request_policy(server.origin+path, '', 'POST', server.origin), 'block')
            for body in [encoded(dict(project_id=AUTHOR)), encoded(dict(root=str(self.gits[0].root))),
                         encoded(dict(project_id=ENTITY, extra=True)), b'[]']:
                driver.rejected(server, path='/v1/projects/open', body=body)
            self.node_path.write_bytes(b'{"secret": INVALID}')
            response = driver.request(server, path='/v1/projects', body=b'{}')
            self.assertIn(b' 422 ', response.split(b'\r\n')[0]); self.assertNotIn(b'INVALID', response)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires actual sidebar tabs')
    def test_sidebar_tabs_include_sources_and_empty_project_without_writes(self):
        root = self.gits[0].root
        folder = root / 'artifacts' / OTHER; folder.mkdir()
        meta = metadata('<img src=x onerror=alert(1)> PDF source', OTHER)
        meta.update(kind='source', provenance='external', file='source.pdf')
        (folder / 'metadata.json').write_bytes(encoded(meta))
        (folder / 'source.pdf').write_bytes(b'%PDF-1.7\x00\xff')
        self.gits[0].commit('Add binary source')
        (self.gits[1].root / 'artifacts' / OTHER / 'note.md').unlink()
        self.gits[1].commit('Empty second project')
        self.assertEqual(len(self.projects.open(ENTITY)['artifacts']), 2)
        self.assertEqual(self.projects.open(OTHER)['artifacts'], [])
        for id_, git in zip((ENTITY, OTHER), self.gits):
            head = git.head()
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node_path),
                                     '--smoke', '--smoke-project', id_], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('rendered rows verified', result.stdout)
            self.assertEqual(git.head(), head)
            self.assertEqual(git.run('status', '--porcelain').stdout, '')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_desktop_projects_restart_and_untrusted_titles(self):
        for id_ in (ENTITY, OTHER, ENTITY):
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--node', str(self.node_path),
                                     '--smoke', '--smoke-project', id_], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('project=' + id_ + ', rendered rows verified', result.stdout)
            self.assertIn('backend stopped', result.stdout)
        for git in self.gits:
            self.assertEqual(git.run('status', '--porcelain').stdout, '')
