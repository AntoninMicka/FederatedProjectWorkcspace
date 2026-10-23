# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Federated divergence resolution stays preview-first and publishes one merge commit."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.artifacts import Artifacts
from spikes.conflict_resolution import ConflictResolution
from spikes.markdown_documents import document
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import StaleIndex
from tests.fixtures import encoded, metadata


class ConflictResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'
        self.root = self.base / 'project'
        self.project = ProjectCreation(self.node).create(
            'Project', str(self.root), str(uuid4()))['id']
        self.artifact = str(uuid4())
        self.artifacts = Artifacts(self.node)
        self.ws = Projects(self.node).workspace(self.project)
        self.git = self.ws.git
        created = self.artifacts.save({
            'project_id': self.project, 'artifact_id': self.artifact,
            'base_head': self.git.head(), 'title': 'Úkoly',
            'body': '- [ ] Původní stav\n', 'new': True,
        }, str(uuid4()))
        self.start = created['commit_id']
        self.local = self.artifacts.save({
            'project_id': self.project, 'artifact_id': self.artifact,
            'base_head': self.start, 'title': 'Úkoly',
            'body': '- [ ] Místní změna\n', 'new': False,
        }, str(uuid4()))['commit_id']
        base_files = self.git.snapshot(self.start)
        item = document(base_files, validate_snapshot(base_files), self.artifact)
        self.path = item['path']
        self.assertIsNotNone(item['sidecar'])
        self.git.run('switch', '-c', 'peer', self.start)
        (self.root / self.path).write_text('- [ ] Protější změna\n')
        self.peer = self.git.commit('Peer change')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.peer_id = str(uuid4()); self.exchange = str(uuid4())
        self.ref = (f'refs/federation/incoming/{self.peer_id}/'
                    f'{self.exchange}/main')
        self.git.run('update-ref', self.ref, self.peer, '0' * 40)
        self.administration = Administration(self.node)
        self.actor = {'id': None, 'node_role': 'federation-admin',
                      'memberships': {self.project: 'project-admin'}}
        state = self.administration.request(self.actor, {'action': 'list'})
        state = self.administration.request(self.actor, {
            'action': 'add-peer-relationship',
            'expected_commit': state['commit_id'],
            'relationship_type': 'p2p', 'sharing_level': 'same-team',
            'node_id': self.peer_id, 'name': 'Peer',
            'endpoint': 'https://127.0.0.1:8443', 'fingerprint': 'a' * 64})
        self.administration.request(self.actor, {
            'action': 'update-peer', 'expected_commit': state['commit_id'],
            'node_id': self.peer_id, 'name': 'Peer',
            'endpoint': 'https://127.0.0.1:8443', 'trust': 'approved',
            'sharing_level': 'same-team'})
        self.service = ConflictResolution(self.node)

    def admin_change(self, **request):
        state = self.administration.request(self.actor, {'action': 'list'})
        return self.administration.request(
            self.actor, dict(expected_commit=state['commit_id'], **request))

    def state(self):
        with closing(sqlite3.connect(self.ws.journal.database)) as db:
            operations = db.execute(
                'SELECT record,done FROM operations ORDER BY id').fetchall()
            pending = db.execute('SELECT * FROM pending ORDER BY path').fetchall()
        return (self.git.head(), self.git.run('write-tree').stdout,
                self.git.run('status', '--porcelain', '--untracked-files=all').stdout,
                self.git.run('for-each-ref', '--format=%(refname) %(objectname)',
                             'refs/federation/incoming/').stdout,
                operations, pending, self.ws.index.path.read_bytes())

    def preview(self):
        return self.service.preview(self.project, self.local, self.ref)

    def request(self, view, *, choice='manual'):
        resolutions = []
        for item in view['files']:
            if item['path'] == self.path:
                row = {'path': item['path'], 'choice': choice}
                if choice == 'manual':
                    row['text'] = '- [ ] Místní změna\n- [ ] Protější změna\n'
                resolutions.append(row)
            else:
                resolutions.append({'path': item['path'], 'choice':
                                    'ours' if item['conflict'] else 'auto'})
        return {key: view[key] for key in (
            'project_id', 'expected_head', 'incoming_ref', 'incoming_head',
            'base', 'preview_sha256')} | {'resolutions': resolutions}

    def test_list_and_preview_are_head_bound_and_do_not_touch_project_state(self):
        before = self.state()
        listed = self.service.list(self.project, self.local)
        self.assertEqual(len(listed['conflicts']), 1)
        self.assertEqual(listed['conflicts'][0]['ref'], self.ref)
        view = self.preview()
        row = next(item for item in view['files'] if item['path'] == self.path)
        self.assertTrue(row['conflict']); self.assertTrue(row['editable'])
        self.assertIn('Místní', row['ours']); self.assertIn('Protější', row['theirs'])
        self.assertIn('<<<<<<<', row['result'])
        self.assertEqual(self.state(), before)
        with self.assertRaises((ValidationError, StaleIndex)):
            self.service.preview(self.project, self.start, self.ref)

    def test_confirm_publishes_one_valid_two_parent_commit_and_is_idempotent(self):
        view = self.preview(); request = self.request(view); operation = str(uuid4())
        receipt = self.service.confirm(request, operation)
        merged = receipt['commit_id']
        self.assertEqual(self.git.head(), merged)
        self.assertEqual(self.git.run('show', '-s', '--format=%P', merged).stdout.split(),
                         [self.local, self.peer])
        files = self.git.snapshot(merged); validate_snapshot(files)
        self.assertEqual(files[self.path],
                         '- [ ] Místní změna\n- [ ] Protější změna\n'.encode())
        self.assertEqual(self.ws.index.read_projection(self.git)['commit_id'], merged)
        self.assertEqual(self.service.list(self.project, merged)['conflicts'], [])
        self.assertEqual(self.service.confirm(request, operation)['commit_id'], merged)

    def test_unresolved_auto_is_rejected_and_ref_update_crash_rolls_forward(self):
        view = self.preview()
        with self.assertRaisesRegex(ValidationError, 'explicit resolution'):
            self.service.confirm(self.request(view, choice='auto'), str(uuid4()))
        operation = str(uuid4()); request = self.request(view)
        def crash(stage):
            if stage == 'ref-updated':
                raise RuntimeError('crash')
        with self.assertRaisesRegex(RuntimeError, 'crash'):
            self.service.confirm(request, operation, checkpoint=crash)
        published = self.git.head()
        self.assertEqual(self.git.run('show', '-s', '--format=%P', published).stdout.split(),
                         [self.local, self.peer])
        receipt = self.service.confirm(request, operation)
        self.assertEqual(receipt['commit_id'], published)
        with closing(sqlite3.connect(self.ws.journal.database)) as db:
            self.assertFalse(db.execute('SELECT 1 FROM pending').fetchone())
            self.assertEqual(db.execute(
                'SELECT done FROM operations WHERE id=?', (operation,)).fetchone(), (1,))

    def test_revoked_or_narrowed_authority_rejects_preview_and_stale_confirm(self):
        view = self.preview(); request = self.request(view)
        self.admin_change(
            action='update-peer', node_id=self.peer_id, name='Peer',
            endpoint='https://127.0.0.1:8443', trust='approved',
            sharing_level='same-company')
        with self.assertRaises(AccessDenied):
            self.preview()
        self.admin_change(
            action='set-project-share', peer_id=self.peer_id,
            project_id=self.project, enabled=True,
            branch_mode='selected-only', branches=['refs/heads/main'],
            include_patches=False)
        with self.assertRaisesRegex(ValidationError, 'preview changed'):
            self.service.confirm(request, str(uuid4()))
        narrowed = self.preview()
        self.admin_change(
            action='set-project-share', peer_id=self.peer_id,
            project_id=self.project, enabled=True,
            branch_mode='selected-only', branches=['refs/heads/other'],
            include_patches=False)
        with self.assertRaises(AccessDenied):
            self.service.confirm(self.request(narrowed), str(uuid4()))

    def test_project_level_change_is_rejected_instead_of_silently_dropped(self):
        self.git.run('switch', 'peer')
        project_file = self.root / 'project.json'
        project = json.loads(project_file.read_text())
        project['title'] = 'Changed'
        project_file.write_text(json.dumps(project, sort_keys=True) + '\n')
        changed = self.git.commit('Unsupported project change')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, changed, self.peer)
        with self.assertRaisesRegex(
                ValidationError, 'unsupported project files'):
            self.preview()

    def test_clean_divergence_can_use_git_auto_result(self):
        self.git.run('switch', '-c', 'peer-clean', self.start)
        added = str(uuid4())
        added_path = f'artifacts/{added}/blob.bin'
        target = self.root / added_path; target.parent.mkdir()
        added_data = b'\x00\xffpeer binary'
        target.write_bytes(added_data)
        added_metadata = metadata(title='Peer addition', entity_id=added,
                                  file='blob.bin')
        added_metadata.update(kind='source', provenance='external')
        (target.parent / 'metadata.json').write_bytes(encoded(added_metadata))
        peer = self.git.commit('Independent peer addition')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, peer, self.peer)
        view = self.preview()
        self.assertFalse(any(item['conflict'] for item in view['files']))
        binary = next(item for item in view['files']
                      if item['path'] == added_path)
        self.assertFalse(binary['editable'])
        self.assertTrue(binary['result_exists'])
        self.assertIsNone(binary['result'])
        receipt = self.service.confirm(
            self.request(view, choice='auto'), str(uuid4()))
        self.assertEqual(self.git.snapshot(receipt['commit_id'])[added_path],
                         added_data)

    def test_change_delete_can_explicitly_keep_local_artifact(self):
        self.git.run('switch', '-c', 'peer-delete', self.start)
        self.git.run('rm', '-r', f'artifacts/{self.artifact}')
        peer = self.git.commit('Delete peer artifact')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, peer, self.peer)
        view = self.preview()
        self.assertTrue(any(item['status'] == 'change/delete'
                            for item in view['files']))
        request = self.request(view)
        request['resolutions'] = [
            {'path': item['path'], 'choice': 'ours'} for item in view['files']]
        merged = self.service.confirm(request, str(uuid4()))['commit_id']
        self.assertEqual(self.git.snapshot(merged)[self.path],
                         '- [ ] Místní změna\n'.encode())

    def test_rename_update_is_identified_and_invalid_sidecar_fails_closed(self):
        self.git.run('switch', '-c', 'peer-rename', self.start)
        renamed = self.path.rsplit('/', 1)[0] + '/renamed.md'
        self.git.run('mv', self.path, renamed)
        sidecar = self.root / f'artifacts/{self.artifact}/metadata.json'
        peer_metadata = json.loads(sidecar.read_text())
        peer_metadata['file'] = 'renamed.md'
        sidecar.write_text(json.dumps(peer_metadata, sort_keys=True) + '\n')
        peer = self.git.commit('Rename peer document')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, peer, self.peer)
        view = self.preview()
        renamed_rows = [item for item in view['files']
                        if item['status'] == 'rename/update']
        self.assertTrue(renamed_rows)
        self.assertTrue(any(item['renamed_path'] for item in renamed_rows))

        # A manual result may be textually valid while breaking the sidecar
        # contract; whole-snapshot validation must reject it before CAS.
        request = self.request(view)
        sidecar_row = next(row for row in request['resolutions']
                           if row['path'].endswith('/metadata.json'))
        sidecar_row.update(choice='manual', text='{}\n')
        with self.assertRaises(ValidationError):
            self.service.confirm(request, str(uuid4()))

    def test_network_preview_rejects_incoming_local_only_data(self):
        self.git.run('switch', 'peer')
        sidecar = self.root / f'artifacts/{self.artifact}/metadata.json'
        peer_metadata = json.loads(sidecar.read_text())
        peer_metadata['privacy'] = 'local-only'
        sidecar.write_text(json.dumps(peer_metadata, sort_keys=True) + '\n')
        peer = self.git.commit('Peer local-only change')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, peer, self.peer)
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            ConflictResolution(self.node, network=True).preview(
                self.project, self.local, self.ref)

    def test_manual_sidecar_cannot_publish_a_dangling_relationship(self):
        sidecar = self.root / f'artifacts/{self.artifact}/metadata.json'
        local_metadata = json.loads(sidecar.read_text())
        local_metadata['title'] = 'Local title'
        sidecar.write_text(json.dumps(local_metadata, sort_keys=True) + '\n')
        self.local = self.git.commit('Local metadata')

        self.git.run('switch', 'peer')
        peer_metadata = json.loads(sidecar.read_text())
        peer_metadata['title'] = 'Peer title'
        sidecar.write_text(json.dumps(peer_metadata, sort_keys=True) + '\n')
        peer = self.git.commit('Peer metadata')
        self.git.run('switch', 'main')
        self.git.run('read-tree', '--reset', '-u', self.local)
        self.git.run('update-ref', self.ref, peer, self.peer)

        view = self.preview(); request = self.request(view)
        sidecar_item = next(item for item in view['files']
                            if item['path'].endswith('/metadata.json'))
        invalid = json.loads(sidecar_item['ours'])
        invalid['relations'] = [{'type': 'depends-on',
                                 'target_id': str(uuid4())}]
        sidecar_row = next(row for row in request['resolutions']
                           if row['path'] == sidecar_item['path'])
        sidecar_row.update(choice='manual',
                           text=json.dumps(invalid, sort_keys=True) + '\n')
        with self.assertRaisesRegex(ValidationError, 'Dangling relation'):
            self.service.confirm(request, str(uuid4()))


if __name__ == '__main__':
    unittest.main()
