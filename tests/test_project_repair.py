# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only project Check & Repair diagnostics."""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.configuration import parse_node, read_config
from spikes.project_creation import ProjectCreation
from spikes.project_repair import ProjectDiagnostics, ProjectRepairActions
from spikes.desktop_ui import DesktopHandler, HTML, JS
from spikes.local_api import running_api
from spikes.projects import Projects
from spikes.storage import Git
from spikes.workspace import Workspace
from tests import test_local_api
from tests.fixtures import ENTITY, encoded, markdown, metadata


def filesystem_snapshot(*roots):
    result = {}
    for root in roots:
        root = Path(root)
        if not os.path.lexists(root):
            result[str(root)] = None
            continue
        paths = [root]
        if root.is_dir() and not root.is_symlink():
            paths.extend(sorted(root.rglob('*')))
        for path in paths:
            info = path.lstat()
            row = [info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                   info.st_nlink, info.st_size, info.st_mtime_ns]
            if stat.S_ISREG(info.st_mode):
                row.append(hashlib.sha256(path.read_bytes()).hexdigest())
            elif stat.S_ISLNK(info.st_mode):
                row.append(os.readlink(path))
            result[str(path)] = row
    return result


class ProjectDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project repair ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.created = ProjectCreation(self.node).create(
            'Repair fixture', self.root, str(uuid4()))
        self.project_id = self.created['id']
        binding = parse_node(read_config(self.node), location=self.node)['projects'][0]
        self.state = Path(binding['state_dir'])
        self.service = ProjectDiagnostics(self.node)

    @staticmethod
    def codes(report):
        return {item['code'] for item in report['findings']}

    def test_healthy_check_is_stable_and_changes_no_filesystem_bytes_or_metadata(self):
        before = filesystem_snapshot(self.node, self.root, self.state)
        objects = Git(self.root).run('count-objects', '-v').stdout
        first = self.service.check(self.project_id)
        second = self.service.check(self.project_id)
        self.assertEqual(first['status'], 'healthy')
        self.assertEqual(first['findings'], [])
        self.assertEqual(first['check_token'], second['check_token'])
        self.assertEqual(filesystem_snapshot(self.node, self.root, self.state), before)
        self.assertEqual(Git(self.root).run('count-objects', '-v').stdout, objects)

    def test_missing_index_is_repairable_but_check_does_not_create_it(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        before = filesystem_snapshot(self.node, self.root, self.state)
        result = self.service.check(self.project_id)
        self.assertEqual(result['status'], 'repairable')
        self.assertEqual(self.codes(result), {'index-missing'})
        self.assertEqual(result['findings'][0]['action'], 'rebuild-index')
        self.assertFalse(index.exists())
        self.assertEqual(filesystem_snapshot(self.node, self.root, self.state), before)

    def test_stale_diverged_legacy_unsupported_and_invalid_indexes_are_distinct(self):
        index = self.state / 'index.sqlite'
        artifact = self.root / 'artifacts' / ENTITY / 'content.md'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(markdown(metadata('Changed', ENTITY)))
        Git(self.root).commit('Change project')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-stale'})
        self.assertEqual(result['status'], 'repairable')

        # Return to a current index, then forge its rows without changing HEAD.
        from spikes.storage import Index
        Index(index).rebuild(Git(self.root))
        with closing(sqlite3.connect(index)) as db, db:
            db.execute("UPDATE entities SET title='Forged'")
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-diverged'})
        self.assertEqual(result['status'], 'manual')

        index.unlink()
        with closing(sqlite3.connect(index)) as db, db:
            db.execute('CREATE TABLE state(singleton INTEGER PRIMARY KEY,commit_id TEXT NOT NULL)')
            db.execute('CREATE TABLE entities(id TEXT PRIMARY KEY,title TEXT NOT NULL)')
        index.chmod(0o600)
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-legacy'})
        self.assertEqual(result['status'], 'repairable')

        with closing(sqlite3.connect(index)) as db, db:
            db.execute('ALTER TABLE entities ADD COLUMN unexpected TEXT')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-invalid'})

        with closing(sqlite3.connect(index)) as db, db:
            db.execute('PRAGMA user_version=77')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-unsupported'})
        self.assertEqual(result['status'], 'manual')

        index.write_bytes(b'not sqlite')
        before = index.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'index-invalid'})
        self.assertEqual(index.read_bytes(), before)

    def test_journal_intents_are_repairable_and_corruption_is_manual(self):
        journal = self.state / 'journal.sqlite'
        operation = str(uuid4())
        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('INSERT INTO operations VALUES (?,?,0)',
                       (operation, json.dumps({'operation_id': operation})))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-operation-active'})
        self.assertEqual(result['findings'][0]['action'], 'resume-operation')

        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('DELETE FROM operations WHERE done=0')
            db.execute('INSERT INTO pending VALUES (?,?,?)',
                       (f'artifacts/{ENTITY}/content.md', None, b'pending'))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-pending'})
        self.assertEqual(result['status'], 'repairable')

        journal.write_bytes(b'broken journal')
        before = journal.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'journal-invalid'})
        self.assertEqual(result['status'], 'manual')
        self.assertEqual(journal.read_bytes(), before)

    def test_journal_recovery_conflict_is_manual_and_preserves_intent(self):
        journal = self.state / 'journal.sqlite'
        relative = f'artifacts/{ENTITY}/document.md'
        after = markdown(metadata('Recovered', ENTITY))
        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('INSERT INTO pending VALUES (?,?,?)',
                       (relative, b'expected previous bytes', after))
        before = journal.read_bytes()

        result = self.service.check(self.project_id)

        self.assertEqual(self.codes(result), {'journal-recovery-conflict'})
        self.assertEqual(result['status'], 'manual')
        self.assertEqual(journal.read_bytes(), before)
        with closing(sqlite3.connect(journal)) as db:
            self.assertEqual(db.execute('SELECT path,before,after FROM pending').fetchone(),
                             (relative, b'expected previous bytes', after))

    def test_project_configuration_snapshot_and_git_states_have_stable_codes(self):
        config = self.root / 'project.json'
        current = json.loads(config.read_text())
        config.write_bytes(encoded(dict(current, title='Uncommitted')))
        result = self.service.check(self.project_id)
        self.assertIn('project-worktree-mismatch', self.codes(result))
        self.assertIn('git-dirty', self.codes(result))
        self.assertEqual(result['status'], 'manual')

        config.write_bytes(encoded(dict(current, id=str(uuid4()))))
        Git(self.root).commit('Wrong project ID')
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'project-id-mismatch'})
        self.assertEqual(result['status'], 'manual')

        config.write_bytes(encoded(current)); Git(self.root).commit('Restore config')
        artifact = self.root / 'artifacts' / ENTITY / 'content.md'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'invalid metadata'); Git(self.root).commit('Invalid snapshot')
        result = self.service.check(self.project_id)
        self.assertIn('project-snapshot-invalid', self.codes(result))

    def test_missing_unsafe_and_busy_layers_fail_closed_without_paths(self):
        moved = self.base / 'moved'
        self.root.rename(moved)
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'root-missing'})
        self.assertEqual(result['findings'][0]['action'], 'repair-location')
        self.assertNotIn(str(self.base), json.dumps(result))
        moved.rename(self.root)

        self.root.chmod(0o777)
        result = self.service.check(self.project_id)
        self.assertIn('root-unsafe', self.codes(result))
        self.root.chmod(0o755)

        lock = self.state / 'writer.lock'
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.service.check(self.project_id)
        self.assertIn('writer-busy', self.codes(result))
        self.assertEqual(result['status'], 'retry')

    def test_registration_and_concurrent_change_fail_closed(self):
        self.node.write_bytes(b'{bad')
        before = self.node.read_bytes()
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'registration-invalid'})
        self.assertNotIn('{bad', json.dumps(result))
        self.assertEqual(self.node.read_bytes(), before)

        # A changing observation invalidates every partial finding.
        self.node.write_bytes(encoded({'schema_version': 1, 'id': str(uuid4()),
            'name': 'Node', 'projects': []}))
        with patch.object(self.service, '_fingerprint',
                          side_effect=[{'version': 1}, {'version': 2}]):
            result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'state-changed'})
        self.assertEqual(result['status'], 'retry')

    def test_duplicate_registration_and_unsafe_state_entry_are_specific(self):
        node = parse_node(read_config(self.node), location=self.node)
        node['projects'].append(dict(node['projects'][0]))
        self.node.write_bytes(encoded(node))
        result = self.service.check(self.project_id)
        self.assertEqual(self.codes(result), {'registration-duplicate'})

        node['projects'].pop(); self.node.write_bytes(encoded(node))
        unsafe = self.state / 'foreign-directory'; unsafe.mkdir()
        result = self.service.check(self.project_id)
        self.assertIn('state-unsafe', self.codes(result))
        self.assertEqual(result['status'], 'manual')

    def test_remaining_registration_filesystem_git_project_and_journal_codes(self):
        self.assertEqual(self.codes(self.service.check(str(uuid4()))),
                         {'registration-missing'})

        def fixture(name):
            node = self.base / f'{name}.json'
            root = self.base / name
            created = ProjectCreation(node).create(name, root, str(uuid4()))
            binding = parse_node(read_config(node), location=node)['projects'][0]
            return (ProjectDiagnostics(node), created['id'], root,
                    Path(binding['state_dir']))

        service, project_id, root, state = fixture('state-missing')
        state.rename(self.base / 'removed-state')
        self.assertEqual(self.codes(service.check(project_id)), {'state-missing'})

        service, project_id, root, state = fixture('filesystem-mismatch')
        with patch.object(service, '_same_filesystem', return_value=False):
            self.assertEqual(self.codes(service.check(project_id)),
                             {'state-filesystem-mismatch'})

        service, project_id, root, state = fixture('journal-missing')
        (state / 'journal.sqlite').unlink()
        self.assertEqual(self.codes(service.check(project_id)), {'journal-missing'})

        service, project_id, root, state = fixture('journal-owner')
        with closing(sqlite3.connect(state / 'journal.sqlite')) as db, db:
            db.execute('UPDATE owner SET root=?', (str(self.base / 'foreign'),))
        self.assertEqual(self.codes(service.check(project_id)),
                         {'journal-owner-mismatch'})

        service, project_id, root, state = fixture('git-invalid')
        (root / '.git').rename(root / '.git-away')
        self.assertEqual(self.codes(service.check(project_id)), {'git-invalid-root'})

        service, project_id, root, state = fixture('git-bare')
        Git(root).run('config', 'core.bare', 'true')
        self.assertEqual(self.codes(service.check(project_id)), {'git-bare'})

        service, project_id, root, state = fixture('git-head')
        Git(root).run('update-ref', '-d', 'refs/heads/main')
        self.assertEqual(self.codes(service.check(project_id)),
                         {'git-head-missing', 'git-dirty'})

        service, project_id, root, state = fixture('git-detached')
        Git(root).run('checkout', '--detach')
        self.assertEqual(self.codes(service.check(project_id)), {'git-detached'})

        service, project_id, root, state = fixture('git-operation')
        (root / '.git' / 'MERGE_HEAD').write_text(Git(root).head() + '\n')
        self.assertEqual(self.codes(service.check(project_id)), {'git-operation-active'})

        service, project_id, root, state = fixture('config-missing')
        (root / 'project.json').unlink(); Git(root).commit('Remove project config')
        self.assertEqual(self.codes(service.check(project_id)),
                         {'project-config-missing'})

        service, project_id, root, state = fixture('config-invalid')
        (root / 'project.json').write_bytes(b'not json')
        Git(root).commit('Invalidate project config')
        self.assertEqual(self.codes(service.check(project_id)),
                         {'project-config-invalid'})


class ProjectRepairActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project repair actions ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        created = ProjectCreation(self.node).create(
            'Repair fixture', self.root, str(uuid4()))
        self.project_id = created['id']
        binding = parse_node(read_config(self.node), location=self.node)['projects'][0]
        self.state = Path(binding['state_dir'])
        self.actions = ProjectRepairActions(self.node)

    def plan(self, action):
        report = self.actions.diagnostics.check(self.project_id)
        return self.actions.preview({
            'project_id': self.project_id,
            'action': action,
            'operation_id': str(uuid4()),
            'check_token': report['check_token'],
        })

    def test_rebuild_preview_is_read_only_and_confirm_retry_has_one_receipt(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        before = filesystem_snapshot(self.node, self.root, self.state)
        plan = self.plan('rebuild-index')
        self.assertEqual(filesystem_snapshot(self.node, self.root, self.state), before)
        self.assertEqual(plan['layer'], 'index')
        self.assertNotIn(str(self.base), json.dumps(plan))

        first = self.actions.confirm(plan)
        second = self.actions.confirm(plan)
        self.assertEqual(first, second)
        self.assertEqual(first['receipt']['action'], 'rebuild-index')
        self.assertEqual(first['report']['status'], 'healthy')
        self.assertEqual(ProjectRepairActions(self.node).receipt(
            self.project_id, plan['operation_id']), first['receipt'])
        with closing(sqlite3.connect(self.state / 'journal.sqlite')) as db:
            self.assertEqual(db.execute(
                'SELECT count(*) FROM operations WHERE id=? AND done=1',
                (plan['operation_id'],)).fetchone(), (1,))

    def test_changed_state_and_tampered_plan_are_rejected_before_effect(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        plan = self.plan('rebuild-index')
        changed = dict(plan, effect='Jiný účinek')
        with self.assertRaises(ValueError):
            self.actions.confirm(changed)
        self.assertFalse(index.exists())

        (self.root / 'foreign.txt').write_text('user work')
        with self.assertRaisesRegex(ValueError, 'changed after preview'):
            self.actions.confirm(plan)
        self.assertFalse(index.exists())

    def test_rebuild_lost_response_is_reconciled_without_second_effect(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        plan = self.plan('rebuild-index')

        def lost(stage):
            if stage == 'effect-completed':
                raise RuntimeError('lost response')

        with self.assertRaisesRegex(RuntimeError, 'lost response'):
            self.actions.confirm(plan, checkpoint=lost)
        first_bytes = index.read_bytes()
        result = self.actions.confirm(plan)
        self.assertTrue(result['receipt']['reconciled'])
        self.assertEqual(result['report']['status'], 'healthy')
        self.assertEqual(index.read_bytes(), first_bytes)

    def test_rebuild_checkpoint_failures_leave_atomic_projection_and_allow_fresh_retry(self):
        artifact = self.root / 'artifacts' / ENTITY / 'content.md'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(markdown(metadata('Changed', ENTITY)))
        Git(self.root).commit('Make index stale')
        index = self.state / 'index.sqlite'
        old_bytes = index.read_bytes()

        for stage in ('index-cleared', 'index-entities', 'index-relations', 'index-state'):
            with self.subTest(stage=stage):
                plan = self.plan('rebuild-index')

                def interrupted(current):
                    if current == stage:
                        raise RuntimeError(stage)

                with self.assertRaisesRegex(RuntimeError, stage):
                    self.actions.confirm(plan, checkpoint=interrupted)
                self.assertEqual(index.read_bytes(), old_bytes)
                self.assertEqual(self.actions.diagnostics.check(self.project_id)['status'],
                                 'repairable')

        fresh = self.plan('rebuild-index')
        self.assertEqual(self.actions.confirm(fresh)['report']['status'], 'healthy')

    def test_rebuild_published_checkpoint_reconciles_same_request(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        plan = self.plan('rebuild-index')

        def interrupted(stage):
            if stage == 'index-published':
                raise RuntimeError(stage)

        with self.assertRaisesRegex(RuntimeError, 'index-published'):
            self.actions.confirm(plan, checkpoint=interrupted)
        published = index.read_bytes()
        result = self.actions.confirm(plan)
        self.assertTrue(result['receipt']['reconciled'])
        self.assertEqual(result['report']['status'], 'healthy')
        self.assertEqual(index.read_bytes(), published)

    def test_confirm_respects_busy_writer_lock_without_effect(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        plan = self.plan('rebuild-index')
        fd = os.open(self.state / 'writer.lock', os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.actions.confirm(plan)
        self.assertFalse(index.exists())

    def test_standalone_journal_recovery_stores_receipt_with_clear(self):
        journal = self.state / 'journal.sqlite'
        relative = f'artifacts/{ENTITY}/document.md'
        content = markdown(metadata('Recovered', ENTITY))
        with closing(sqlite3.connect(journal)) as db, db:
            db.execute('INSERT INTO pending VALUES (?,?,?)',
                       (relative, None, content))
        plan = self.plan('resume-operation')
        self.assertIsNone(plan['intent_operation_id'])

        def lost(stage):
            if stage == 'completed':
                raise RuntimeError('lost response')

        with self.assertRaisesRegex(RuntimeError, 'lost response'):
            self.actions.confirm(plan, checkpoint=lost)
        self.assertEqual((self.root / relative).read_bytes(), content)
        durable = ProjectRepairActions(self.node).receipt(
            self.project_id, plan['operation_id'])
        self.assertIsNotNone(durable)
        result = self.actions.confirm(plan)
        self.assertEqual(result['receipt'], durable)
        self.assertEqual(result['receipt']['action'], 'resume-operation')
        self.assertFalse(result['receipt']['reconciled'])
        self.assertEqual(result['report']['status'], 'manual')

    def test_workspace_recovery_lost_response_uses_exact_completed_intent(self):
        relative = f'artifacts/{ENTITY}/document.md'
        intent = str(uuid4())

        def stop(stage):
            if stage == 'prepared':
                raise RuntimeError('prepared')

        workspace = Workspace(self.root, self.state)
        with self.assertRaisesRegex(RuntimeError, 'prepared'):
            workspace.transact(intent, {'fixture': True},
                lambda _: ({relative: markdown(metadata('Recovered', ENTITY))},
                           'Repair Test', 'repair@example.invalid', 'Recover fixture'),
                checkpoint=stop)
        plan = self.plan('resume-operation')
        self.assertEqual(plan['intent_operation_id'], intent)

        def lost(stage):
            if stage == 'completed':
                raise RuntimeError('lost response')

        with self.assertRaisesRegex(RuntimeError, 'lost response'):
            self.actions.confirm(plan, checkpoint=lost)
        result = self.actions.confirm(plan)
        self.assertTrue(result['receipt']['reconciled'])
        self.assertEqual(result['receipt']['intent_operation_id'], intent)
        self.assertEqual(result['report']['status'], 'healthy')
        self.assertEqual(Git(self.root).run('rev-list', '--count', 'HEAD').stdout.strip(), '2')

    def test_authenticated_desktop_api_keeps_check_preview_confirm_and_receipt_separate(self):
        driver = test_local_api.LocalAPITests()
        index = self.state / 'index.sqlite'; index.unlink()
        with running_api('http', handler=DesktopHandler,
                         projects=Projects(self.node)) as server:
            server.project_repair_actions = ProjectRepairActions(self.node)
            check_body = json.dumps({'project_id': self.project_id}).encode()
            driver.rejected(server, path='/v1/projects/repair/check',
                            body=check_body, headers={'Authorization': None})
            response = driver.request(server, path='/v1/projects/repair/check',
                                      body=check_body)
            self.assertIn(b' 200 ', response.split(b'\r\n')[0])
            report = json.loads(response.split(b'\r\n\r\n', 1)[1])
            operation = str(uuid4())
            preview = {'project_id': self.project_id, 'action': 'rebuild-index',
                       'operation_id': operation,
                       'check_token': report['check_token']}
            response = driver.request(server, path='/v1/projects/repair/preview',
                                      body=json.dumps(preview).encode())
            plan = json.loads(response.split(b'\r\n\r\n', 1)[1])
            response = driver.request(server, path='/v1/projects/repair/confirm',
                                      body=json.dumps({'plan': plan}).encode())
            result = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertEqual(result['report']['status'], 'healthy')
            response = driver.request(server, path='/v1/projects/repair/receipt',
                body=json.dumps({'project_id': self.project_id,
                                 'operation_id': operation}).encode())
            durable = json.loads(response.split(b'\r\n\r\n', 1)[1])['receipt']
            self.assertEqual(durable, result['receipt'])
            self.assertNotIn(str(self.base), json.dumps(
                {'report': report, 'plan': plan, 'result': result}))

    def test_shared_ui_has_layered_report_and_unavailable_project_entry(self):
        self.assertIn('id="project-repair-view" hidden', HTML)
        self.assertIn('id="project-repair-findings"', HTML)
        self.assertIn("label:'Zkontrolovat projekt…'", JS)
        self.assertIn("projectRequest('/v1/projects/repair/check'", JS)
        self.assertIn("projectRequest('/v1/projects/repair/preview'", JS)
        self.assertIn("projectRequest('/v1/projects/repair/confirm'", JS)
        self.assertIn("if(!item.available)actions.splice", JS)
        self.assertNotIn('innerHTML=', JS)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1',
                         'Requires real Qt/WebEngine')
    def test_real_desktop_repair_menu_preview_confirmation_and_result(self):
        index = self.state / 'index.sqlite'
        index.unlink()
        run = subprocess.run(
            [sys.executable, '-m', 'spikes.desktop', '--node', str(self.node),
             '--smoke', '--smoke-repair', self.project_id],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('project=' + self.project_id + ', repair UI verified', run.stdout)
        self.assertIn('desktop smoke: backend stopped', run.stdout)
        self.assertTrue(index.exists())
        self.assertEqual(ProjectDiagnostics(self.node).check(self.project_id)['status'],
                         'healthy')


if __name__ == '__main__':
    unittest.main()
