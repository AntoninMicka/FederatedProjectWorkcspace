# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import io
import json
import os
import hmac
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
import zipfile

from spikes.artifacts import Artifacts, main_todo_id
from spikes.ide_bridge import IdeBridge, endpoint, desktop_bridge
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


class IdeBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.node = self.root / 'node.json'
        self.project = ProjectCreation(self.node).create('Bridge project', str(self.root / 'project'), str(uuid4()))['id']
        self.artifact = main_todo_id(self.project)
        self.head = Projects(self.node).open(self.project)['commit_id']
        self.body = '- [ ] [TASK-01] Implement feature\n- [ ] [TASK-02] Review\n'
        self.head = self.save(self.body)
        self.service = IdeBridge(self.node)

    def save(self, body, *, privacy='project', **extra):
        return Artifacts(self.node).save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Tasks', body=body,
            new=not any(a['id'] == self.artifact for a in Projects(self.node).open(self.project)['artifacts']),
            **extra), str(uuid4()), privacy=privacy)['commit_id']

    def create(self, **extra):
        return self.service.create(dict(project_id=self.project, expected_head=self.head,
            repository=str(self.root / 'project'), instructions='Use focused tests.', **extra),
            None, 'http://127.0.0.1:9999')

    def message(self, result):
        return dict(message_id=str(uuid4()), task_id='TASK-01', kind='completed', body='Verified tests.',
                    revision=result['revision'], repository_commit=self.head)

    def test_package_contains_scoped_pairing_and_no_project_write(self):
        result = self.create()
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['package_base64']))) as package:
            self.assertEqual(json.loads(package.read('extension/pairing.json')), result['pairing'])
            self.assertIn('extension.vsixmanifest', package.namelist())
            self.assertNotIn('FileSystemProvider', package.read('extension/extension.js').decode())
        self.assertNotIn(result['pairing']['token'], self.service.root.joinpath('bridge.sqlite').read_bytes().decode(errors='replace'))
        self.assertFalse(self.service.status(self.project)['sessions'][0]['revoked'])

    def test_retry_after_lost_response_and_collision_are_durable(self):
        created = self.create(); token = created['pairing']['token']
        session = self.service.session(token); message = self.message(created)
        request = dict(session_id=session['session_id'], messages=[message])
        first = self.service.exchange(session, request)
        restarted = IdeBridge(self.node)
        second = restarted.exchange(restarted.session(token), request)
        self.assertEqual(first['receipts'], second['receipts'])
        self.assertEqual('received', first['receipts'][0]['status'])
        self.assertEqual('pending-human-review', first['receipts'][0]['acceptance'])
        self.assertEqual(1, len(restarted.status(self.project)['sessions'][0]['messages']))
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        message['body'] = 'Changed under same ID'
        with self.assertRaisesRegex(ValidationError, 'different content'):
            restarted.exchange(session, request)

    def test_stale_messages_are_retained_without_accepting_completion(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        self.head = self.save(self.body + '- [ ] [TASK-03] Changed plan\n')
        response = self.service.exchange(session, dict(session_id=session['session_id'], messages=[self.message(created)]))
        self.assertTrue(response['stale'])
        self.assertEqual('stale', response['receipts'][0]['status'])
        self.assertFalse(Projects(self.node).open(self.project)['plan']['nodes'][0]['checked'])

    def test_partial_batch_recovery_does_not_duplicate_committed_prefix(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        first, second = self.message(created), self.message(created)
        bad = dict(second, task_id='FOREIGN')
        with self.assertRaises(ValidationError):
            self.service.exchange(session, dict(session_id=session['session_id'], messages=[first, bad]))
        self.assertEqual(1, len(self.service.status(self.project)['sessions'][0]['messages']))
        restarted = IdeBridge(self.node)
        result = restarted.exchange(restarted.session(created['pairing']['token']),
            dict(session_id=session['session_id'], messages=[first, second]))
        self.assertEqual(2, len(result['receipts']))
        self.assertEqual(2, len(restarted.status(self.project)['sessions'][0]['messages']))

    def test_wrong_scope_revision_and_revocation(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        message = self.message(created)
        for field, value in [('task_id', 'FOREIGN'), ('revision', '0' * 64), ('kind', 'execute')]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.service.exchange(session, dict(session_id=session['session_id'], messages=[dict(message, **{field: value})]))
        with self.assertRaises(ValidationError):
            self.service.exchange(session, dict(session_id=str(uuid4()), messages=[]))
        self.service.revoke(self.project, session['session_id'])
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.service.session(created['pairing']['token'])
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.service.exchange(session, dict(session_id=session['session_id'], messages=[message]))

    def test_local_only_export_and_git_state_location_fail_closed(self):
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head=self.head, title='Private', body='Private', new=True),
            str(uuid4()), privacy='local-only')['commit_id']
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            self.create()
        nested = IdeBridge(self.root / 'project' / 'node.json')
        with self.assertRaisesRegex(ValidationError, 'outside Git'):
            with nested.database():
                pass

    def test_endpoint_validation_and_unsafe_storage(self):
        for value in ['http://remote.example:9999', 'https://user:secret@host:443', 'https://host:443/path']:
            with self.subTest(value=value), self.assertRaises(ValidationError): endpoint(value)
        target = self.root / 'foreign'; target.mkdir()
        self.service.root.symlink_to(target)
        with self.assertRaises(ValidationError): self.create()

    def parent(self, name='Workstation'):
        created = self.service.connection_create({'name': name}, None, 'http://127.0.0.1:9999')
        return created, self.service.connection(created['pairing']['token'])

    def mapping(self, parent, **changes):
        return dict(dict(connection_id=parent['connection_id'], project_id=self.project,
            enabled=True, expected_head=self.head, repository='', editor_workspace='',
            instructions='Use focused tests.', expected_mapping=None), **changes)

    def test_extension_update_is_credential_free_and_preserves_project_state(self):
        created, parent = self.parent()
        request = dict(connection_id=parent['connection_id'], action='extension-update', download=False)
        metadata = self.service.connection_exchange(parent, request)
        self.assertEqual('federated-workspace.workspace-file-bridge', metadata['extension_id'])
        self.assertNotIn('package_base64', metadata)
        package = self.service.connection_exchange(parent, dict(request, download=True))
        raw = base64.b64decode(package['package_base64'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), package['sha256'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertNotIn('extension/pairing.json', archive.namelist())
            self.assertIn('extension/updater.js', archive.namelist())
            manifest = json.loads(archive.read('extension/package.json'))
            self.assertEqual(metadata['version'], manifest['version'])
        self.assertNotIn(created['pairing']['token'].encode(), raw)
        with self.assertRaises(ValidationError):
            self.service.connection_exchange(parent, dict(request, download='yes'))
        with self.assertRaises(ValidationError):
            self.service.connection_exchange(parent, dict(request, connection_id=str(uuid4())))
        self.service.connection_revoke(None, parent['connection_id'])
        with self.assertRaises(ValidationError): self.service.connection(created['pairing']['token'])
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for updater tests')
    def test_extension_updater_failure_paths(self):
        result = subprocess.run(['node', '--test', 'tests/ide_updater.test.js'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_workspace_connection_without_project_and_legacy_compatibility(self):
        created, parent = self.parent()
        self.assertEqual(2, created['pairing']['schema_version'])
        self.assertNotIn('project_id', created['pairing'])
        self.assertNotIn('repository', created['pairing'])
        catalog = self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='status'))
        self.assertEqual([], catalog['mappings'])
        self.assertEqual([self.project], [p['project_id'] for p in catalog['projects']])
        with self.assertRaises(ValidationError): self.service.session(created['pairing']['token'])
        legacy = self.create()
        self.assertEqual(self.project, self.service.session(legacy['pairing']['token'])['project_id'])
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    def test_mapping_can_be_created_by_ide_bound_and_replaced_without_losing_messages(self):
        created, parent = self.parent()
        request = self.mapping(parent)
        result = self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='map', mapping=request))
        self.assertEqual(result, self.service.configure_mapping(None, request))
        child = dict(session_id=result['session_id'], messages=[])
        with self.assertRaisesRegex(ValidationError, 'not bound'):
            self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='exchange', request=child))
        bind = dict(connection_id=parent['connection_id'], action='bind', session_id=result['session_id'],
                    repository=str(self.root/'project'), editor_workspace=str(self.root/'dev.code-workspace'))
        bound = self.service.connection_exchange(parent, bind)
        self.assertEqual(bound, self.service.connection_exchange(parent, bind))
        mappings = self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='status'))['mappings']
        self.assertTrue(mappings[0]['bound'])
        message = self.message(dict(revision=mappings[0]['revision']))
        child['messages'] = [message]
        first = self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='exchange', request=child))
        self.assertEqual('received', first['receipts'][0]['status'])
        updated = dict(request, repository='new-repository', expected_mapping=result['session_id'])
        second = self.service.configure_mapping(None, updated)
        self.assertNotEqual(result['session_id'], second['session_id'])
        with self.assertRaisesRegex(ValidationError, 'no longer active'):
            self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'], action='exchange', request=child))
        self.assertEqual(1, len(next(s for s in self.service.status(self.project)['sessions'] if s['session_id']==result['session_id'])['messages']))
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    def test_multiple_projects_have_independent_mappings(self):
        _, parent = self.parent(); first = self.service.configure_mapping(None, self.mapping(parent))
        other = ProjectCreation(self.node).create('Other project', str(self.root/'other'), str(uuid4()))['id']
        head = Projects(self.node).open(other)['commit_id']
        head = Artifacts(self.node).save(dict(project_id=other, artifact_id=main_todo_id(other),
            base_head=head, title='Tasks', body='- [ ] [TASK-01] Other task\n', new=True), str(uuid4()))['commit_id']
        second = self.service.configure_mapping(None, self.mapping(parent, project_id=other, expected_head=head))
        actor = {'id':None, 'node_role':'federation-admin'}
        self.assertEqual({first['session_id'],second['session_id']},
            {m['session_id'] for m in self.service.connection_mappings(parent['connection_id'],actor)})
        self.service.configure_mapping(None, self.mapping(parent, enabled=False, expected_mapping=first['session_id']))
        self.assertEqual([other], [m['project_id'] for m in self.service.connection_mappings(parent['connection_id'],actor)])
        with self.assertRaisesRegex(ValidationError, 'another account'):
            self.service.revoke(other,second['session_id'],actor={'id':str(uuid4()),'node_role':'member'})
        self.assertEqual(head,Projects(self.node).open(other)['commit_id'])

    def test_mapping_replacement_rolls_back_between_revoke_and_insert(self):
        _, parent = self.parent(); request = self.mapping(parent)
        first = self.service.configure_mapping(None, request)
        with self.service.database() as db:
            db.execute("CREATE TRIGGER abort_mapping BEFORE INSERT ON sessions BEGIN SELECT RAISE(ABORT, 'swap interrupted'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'interrupted'):
            self.service.configure_mapping(None, dict(request, repository='changed', expected_mapping=first['session_id']))
        restarted = IdeBridge(self.node)
        active = restarted.connection_mappings(parent['connection_id'], {'node_role':'federation-admin'})
        self.assertEqual([first['session_id']], [m['session_id'] for m in active])
        with restarted.database() as db:
            db.execute('DROP TRIGGER abort_mapping')
        second = restarted.configure_mapping(None, dict(request, repository='changed', expected_mapping=first['session_id']))
        self.assertNotEqual(first['session_id'], second['session_id'])

    def test_connection_and_mapping_revocation_wrong_owner_and_stale_settings(self):
        created, parent = self.parent(); _, other = self.parent('Other editor')
        request = self.mapping(parent); mapping = self.service.configure_mapping(None, request)
        with self.assertRaisesRegex(ValidationError, 'another connection'):
            self.service.connection_exchange(other, dict(connection_id=other['connection_id'], action='bind',
                session_id=mapping['session_id'], repository='repo', editor_workspace='editor'))
        with self.assertRaisesRegex(ValidationError, 'changed'):
            self.service.configure_mapping(None, dict(request, repository='wrong stale overwrite'))
        disabled = dict(request, enabled=False, expected_mapping=mapping['session_id'])
        self.assertEqual(self.service.configure_mapping(None, disabled), self.service.configure_mapping(None, disabled))
        self.service.connection_revoke(None, parent['connection_id'])
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.service.connection(created['pairing']['token'])
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            self.service.configure_mapping(None, dict(request, expected_mapping=None))
        stranger = {'id': str(uuid4()), 'node_role': 'member', 'memberships': {}}
        with self.assertRaisesRegex(ValidationError, 'another account'):
            self.service.managed_connection(stranger, other['connection_id'])
        self.assertEqual([], self.service.connections_status(stranger)['connections'])
        view = self.service.projects.open(self.project)
        with patch.object(self.service.projects, 'open', return_value=dict(view, read_only=True)):
            with self.assertRaisesRegex(ValidationError, 'read-only'):
                self.service.configure_mapping(None, self.mapping(other))

    def test_fresh_desktop_needs_no_node_and_new_credentials_are_published(self):
        from types import SimpleNamespace
        root = self.root / 'discovery'
        absent_node = self.root / 'missing-parent/node.json'
        with desktop_bridge(absent_node, SimpleNamespace(origin='http://127.0.0.1:12345'),
                            discovery_root=root):
            self.assertFalse(root.exists())
        server = SimpleNamespace(origin='http://127.0.0.1:12346')
        with desktop_bridge(self.node, server, discovery_root=root) as service:
            created = service.connection_create({'name': 'New'}, None, server.origin)
            descriptor = root / (created['connection_id'] + '.json')
            self.assertEqual(server.origin, json.loads(descriptor.read_text())['endpoint'])
            other_node = self.root / 'second.json'
            with desktop_bridge(other_node, SimpleNamespace(origin='http://127.0.0.1:12347'),
                                discovery_root=root):
                self.assertEqual(server.origin, json.loads(descriptor.read_text())['endpoint'])
        self.assertIsNone(server.ide_bridge_service)

    def test_discovery_rebuild_and_publish_failure_keep_credentials_and_mappings(self):
        created, parent = self.parent()
        mapping = self.service.configure_mapping(None, self.mapping(parent))
        root = self.root / 'discovery'
        self.service.discovery_root = root
        self.service.desktop_origin = 'http://127.0.0.1:12345'
        with patch('spikes.ide_bridge.os.replace', side_effect=OSError('crash before rename')):
            with self.assertRaisesRegex(OSError, 'crash'):
                self.service.publish_endpoints()
        self.assertEqual([], list(root.iterdir()))
        self.service.publish_endpoints()
        file = root / (parent['connection_id'] + '.json')
        first = json.loads(file.read_text())
        self.assertNotIn(created['pairing']['token'], file.read_text())
        self.assertEqual(0o600, file.stat().st_mode & 0o777)
        key = hashlib.sha256(created['pairing']['token'].encode()).digest()
        expected = hmac.new(key, (first['id'] + '\n' + first['endpoint']).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(expected, first['signature'])
        restarted = IdeBridge(self.node)
        restarted.discovery_root = root
        restarted.desktop_origin = 'http://127.0.0.1:12346'
        restarted.publish_endpoints()
        self.assertEqual(restarted.desktop_origin, json.loads(file.read_text())['endpoint'])
        self.assertEqual(mapping['session_id'], restarted.connection_mappings(parent['connection_id'],
            {'node_role': 'federation-admin'})[0]['session_id'])
        self.assertEqual(parent, restarted.connection(created['pairing']['token']))
        alias = self.root / 'alias'
        alias.symlink_to(root, target_is_directory=True)
        restarted.discovery_root = alias
        with self.assertRaises(ValueError):
            restarted.publish_endpoints()
        with zipfile.ZipFile(io.BytesIO(restarted.package())) as archive:
            self.assertNotIn('extension/pairing.json', archive.namelist())

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_real_transport_recovers_existing_mapping_after_desktop_port_change(self):
        created, parent = self.parent()  # issued by the old version, no discovery field
        mapping = self.service.configure_mapping(None, self.mapping(parent))
        bound = self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'],
            action='bind', session_id=mapping['session_id'], repository=str(self.root/'project'),
            editor_workspace=str(self.root/'project')))
        home = self.root / 'home'
        discovery = home / '.local/state/federated-workspace/ide-discovery'
        pairing = dict(created['pairing'], **bound)
        env = dict(os.environ, HOME=str(home))
        program = """
const fs = require('node:fs');
const bridge = require('./extensions/workspace-bridge/bridge');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
bridge.sync(input.mailbox, input.pairing, input.repo).then(result => {
  console.log(JSON.stringify({session: result.session_id, todo: result.snapshot.todo}));
}).catch(error => {console.error(error.message); process.exitCode = 1;});
"""
        def client():
            return subprocess.run(['node', '-e', program], input=json.dumps(dict(pairing=pairing,
                mailbox=str(self.root/'mailbox'), repo=str(self.root/'project'))),
                text=True, capture_output=True, timeout=20, env=env)
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as first:
            with desktop_bridge(self.node, first, discovery_root=discovery):
                first_origin = first.origin
                response = client()
                self.assertEqual(0, response.returncode, response.stderr)
        offline = client()
        self.assertNotEqual(0, offline.returncode)
        self.assertIn('ECONNREFUSED', offline.stderr)
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as second:
            with desktop_bridge(self.node, second, discovery_root=discovery) as service:
                self.assertNotEqual(first_origin, second.origin)
                response = client()
                self.assertEqual(0, response.returncode, response.stderr)
                self.assertEqual(mapping['session_id'], json.loads(response.stdout)['session'])
                self.assertIn('TASK-01', json.loads(response.stdout)['todo'])
                service.connection_revoke(None, parent['connection_id'])
                self.assertNotEqual(0, client().returncode)
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for extension transport tests')
    def test_extension_refreshes_assignment_and_recovers_lost_map_response(self):
        created, parent = self.parent()
        repository = str(self.root / 'project')
        mapping = self.service.configure_mapping(None, self.mapping(parent,
            repository=repository, editor_workspace=repository))
        self.service.connection_exchange(parent, dict(connection_id=parent['connection_id'],
            action='bind', session_id=mapping['session_id'], repository=repository,
            editor_workspace=repository))
        self.head = self.save(self.body + '- [ ] [TASK-03] New assignment\n')
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            config = dict(pairing=dict(created['pairing'], endpoint=server.origin),
                session=mapping['session_id'], repository=repository,
                storage=str(self.root / 'extension-storage'), head=self.head)
            fixture = self.root / 'refresh.json'
            fixture.write_text(json.dumps(config))
            result = subprocess.run(['node', 'tests/ide_bridge_refresh.cjs', str(fixture)],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        active = self.service.connection_mappings(parent['connection_id'], {'node_role': 'federation-admin'})
        self.assertEqual(1, len(active))
        self.assertEqual(self.head, active[0]['expected_head'])
        self.assertEqual(json.loads(result.stdout)['session'], active[0]['session_id'])
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for extension transport tests')
    def test_extension_files_recovery_and_transport(self):
        result = subprocess.run(['node', '--test', 'tests/ide_bridge.test.js'],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
