# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Google Drive per-file selection, staging and atomic publication tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from spikes.configuration import parse_node, read_config
from spikes.google_drive_import import (FOLDER, SCOPE, DriveAccessError,
                                        GoogleDriveImport, MAX_EXPORT)
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.source_import import Sources
from spikes.storage import Git


class FakeDrive:
    def __init__(self):
        self.items = {}
        self.content = {}
        self.children_by_folder = {}
        self.downloads = []
        self.revoked = False

    def exchange(self, client_id, client_secret, code, verifier, redirect_uri):
        if self.revoked: raise DriveAccessError('revoked')
        return {'access_token': 'access', 'refresh_token': 'refresh',
                'expires_in': 3600, 'scope': SCOPE, 'token_type': 'Bearer'}

    def refresh(self, client_id, client_secret, refresh_token):
        if self.revoked: raise DriveAccessError('revoked')
        return {'access_token': 'refreshed', 'expires_in': 3600}

    def metadata(self, token, file_id):
        if self.revoked: raise DriveAccessError('revoked')
        return dict(self.items[file_id])

    def children(self, token, folder_id, page_token=None):
        if self.revoked: raise DriveAccessError('revoked')
        return {'files': [dict(self.items[item])
                          for item in self.children_by_folder.get(folder_id, [])]}

    def download(self, token, file_id, *, export_mime_type=None):
        if self.revoked: raise DriveAccessError('revoked')
        self.downloads.append((file_id, export_mime_type))
        return self.content[file_id]

    def add(self, file_id, name, mime, raw=b'', version='1', parent=None):
        import hashlib
        view_host = ('docs.google.com' if mime.startswith('application/vnd.google-apps.')
                     and mime != FOLDER else 'drive.google.com')
        item = {'id': file_id, 'name': name, 'mimeType': mime,
                'createdTime': '2025-01-02T03:04:05.123Z',
                'modifiedTime': '2025-01-03T03:04:05.123Z', 'version': version,
                'webViewLink': 'https://' + view_host + '/file/d/' + file_id,
                'capabilities': {'canDownload': mime != FOLDER}, 'trashed': False}
        if parent: item['parents'] = [parent]
        if mime != FOLDER and not mime.startswith('application/vnd.google-apps.'):
            item.update(size=str(len(raw)), md5Checksum=hashlib.md5(
                raw, usedforsecurity=False).hexdigest())
        self.items[file_id] = item; self.content[file_id] = raw
        if parent: self.children_by_folder.setdefault(parent, []).append(file_id)


class GoogleDriveImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='drive import ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'
        self.created = ProjectCreation(self.node).create(
            'Drive project', self.base / 'project', str(uuid4()))
        self.project_id = self.created['id']; self.actor = str(uuid4())
        self.fake = FakeDrive(); self.service = GoogleDriveImport(
            self.node, transport=self.fake)
        self.service.configure('client-id-1234567890.apps.googleusercontent.com',
                               'client-secret-value')

    def select(self, ids, *, head=None):
        started = self.service.authorize(self.actor, {
            'project_id': self.project_id,
            'expected_head': head or Projects(self.node).open(self.project_id)['commit_id'],
            'privacy': 'project'}, 'http://127.0.0.1:12345/')
        query = parse_qs(urlsplit(started['authorization_url']).query)
        self.assertEqual(query['scope'], [SCOPE])
        self.assertEqual(query['trigger_onepick'], ['true'])
        self.service.callback(query['state'][0], 'authorization-code', ','.join(ids))
        return started['selection_id']

    def project_root(self):
        return Path(parse_node(read_config(self.node), location=self.node)['projects'][0]['root'])

    def test_redirect_contract_rejects_web_path_for_desktop_loopback(self):
        request = {'project_id': self.project_id,
                   'expected_head': Projects(self.node).open(self.project_id)['commit_id'],
                   'privacy': 'project'}
        with self.assertRaisesRegex(ValueError, 'callback'):
            self.service.authorize(self.actor, request,
                                   'http://127.0.0.1:12345/oauth/google-drive/callback')

    def test_raw_and_native_export_publish_atomically_with_provenance(self):
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'# Notes\n')
        self.fake.add('doc1', 'Proposal', 'application/vnd.google-apps.document',
                      b'%PDF-1.7\nexported')
        selection = self.select(['raw1', 'doc1'])
        pending = self.service.status(self.actor)['pending_selection']
        self.assertEqual(pending['selection_id'], selection)
        self.assertEqual(pending['project_id'], self.project_id)
        response = self.service.preview(self.actor, selection)
        plan = response['plan']
        self.assertEqual(plan['file_count'], 2)
        self.assertEqual(plan['scope'], SCOPE)
        self.assertFalse(plan['writes_to_drive'])
        operation = str(uuid4()); before = Git(self.project_root()).head()
        receipt = self.service.confirm(self.actor, plan, operation)
        self.assertEqual(receipt, self.service.confirm(self.actor, plan, operation))
        self.assertEqual(receipt['file_count'], 2)
        self.assertNotEqual(before, receipt['commit_id'])
        self.assertEqual(len(Git(self.project_root()).run(
            'rev-list', before + '..' + receipt['commit_id']).stdout.splitlines()), 1)
        for artifact_id in receipt['artifact_ids']:
            meta = json.loads((self.project_root() / 'artifacts' / artifact_id
                               / 'metadata.json').read_text())
            self.assertEqual(meta['import']['importer']['name'], 'google-drive-import')
            self.assertIn('source_mime_type', meta['import'])
            self.assertNotEqual(meta['created_at'], meta['import']['source_created_at'])
        self.assertEqual(self.fake.downloads,
                         [('raw1', None), ('doc1', 'application/pdf')])

    def test_untrusted_view_link_is_rejected_without_project_change(self):
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'ok')
        self.fake.items['raw1']['webViewLink'] = 'https://drive.google.com.evil.test/file/raw1'
        before = Projects(self.node).open(self.project_id)['commit_id']
        with self.assertRaisesRegex(ValueError, 'neplatný odkaz'):
            self.service.preview(self.actor, self.select(['raw1']))
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'], before)

    def test_folder_is_bounded_and_changed_revision_fails_before_download(self):
        self.fake.add('folder1', 'Folder', FOLDER)
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'ok', parent='folder1')
        selection = self.select(['folder1']); plan = self.service.preview(
            self.actor, selection)['plan']
        self.fake.items['raw1']['version'] = '2'
        with self.assertRaisesRegex(ValueError, 'změnily'):
            self.service.confirm(self.actor, plan, str(uuid4()))
        self.assertEqual(self.fake.downloads, [])
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'],
                         self.created['commit_id'])

    def test_revoked_access_and_stale_head_do_not_publish(self):
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'ok')
        selection = self.select(['raw1']); plan = self.service.preview(
            self.actor, selection)['plan']
        self.fake.revoked = True
        with self.assertRaises(DriveAccessError):
            self.service.confirm(self.actor, plan, str(uuid4()))
        self.fake.revoked = False
        source = {'project_id': self.project_id, 'artifact_id': str(uuid4()),
            'base_head': self.created['commit_id'], 'filename': 'local.md',
            'title': 'Local', 'description': '', 'tags': [], 'privacy': 'project',
            'created_at': '2026-10-14T10:00:00Z', 'content': 'bG9jYWw=',
            'sha256': '25bf8e1a2393f1106a17a7ea1b7fbeff5a3f5d18944fa0fc56b3a4d6e4f1a0f7',
            'source_url': None, 'source_author': None, 'source_created_at': None,
            'source_revision': None}
        # Use the supported builder so the exact digest is correct.
        from spikes.source_import import request_from_bytes
        source = request_from_bytes(self.project_id, self.created['commit_id'],
            'local.md', b'local', 'Local', '', [], 'project')
        Sources(self.node).import_source(source, str(uuid4()))
        with self.assertRaisesRegex(ValueError, 'Projekt se změnil'):
            self.service.confirm(self.actor, plan, str(uuid4()))

    def test_completed_revision_blocks_duplicate_and_new_revision_supersedes(self):
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'one', version='1')
        first_plan = self.service.preview(self.actor, self.select(['raw1']))['plan']
        first = self.service.confirm(self.actor, first_plan, str(uuid4()))
        duplicate = self.service.preview(self.actor, self.select(['raw1']))['plan']
        self.assertTrue(duplicate['blockers'])
        with self.assertRaisesRegex(ValueError, 'blokující'):
            self.service.confirm(self.actor, duplicate, str(uuid4()))

        self.fake.items['raw1']['version'] = '2'; self.fake.items['raw1']['size'] = '3'
        self.fake.content['raw1'] = b'two'
        import hashlib
        self.fake.items['raw1']['md5Checksum'] = hashlib.md5(
            b'two', usedforsecurity=False).hexdigest()
        revised = self.service.preview(self.actor, self.select(['raw1']))['plan']
        self.assertEqual(revised['files'][0]['supersedes'], first['artifact_ids'][0])
        second = self.service.confirm(self.actor, revised, str(uuid4()))
        meta = json.loads((self.project_root() / 'artifacts' / second['artifact_ids'][0]
                           / 'metadata.json').read_text())
        self.assertEqual(meta['relations'][0]['target_id'], first['artifact_ids'][0])

    def test_downloaded_staging_recovers_without_second_download(self):
        self.fake.add('raw1', 'notes.md', 'text/markdown', b'recover')
        plan = self.service.preview(self.actor, self.select(['raw1']))['plan']
        operation = str(uuid4()); original = Sources.import_sources
        with patch.object(Sources, 'import_sources', side_effect=RuntimeError('stop')):
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                self.service.confirm(self.actor, plan, operation)
        self.assertEqual(len(self.fake.downloads), 1)
        with patch.object(Sources, 'import_sources', original):
            receipt = self.service.recover(self.actor)
        self.assertEqual(receipt['operation_id'], operation)
        self.assertEqual(len(self.fake.downloads), 1)

    def test_native_export_limit_fails_without_project_publication(self):
        self.fake.add('doc1', 'Large', 'application/vnd.google-apps.document',
                      b'x' * (MAX_EXPORT + 1))
        plan = self.service.preview(self.actor, self.select(['doc1']))['plan']
        before = Projects(self.node).open(self.project_id)['commit_id']
        with self.assertRaisesRegex(ValueError, '10 MiB'):
            self.service.confirm(self.actor, plan, str(uuid4()))
        self.assertEqual(Projects(self.node).open(self.project_id)['commit_id'], before)
        self.assertTrue(self.service.status(self.actor)['pending_import'])


if __name__ == '__main__':
    unittest.main()
