# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.notebooklm_import import NotebookLMTakeout, PARSER_REVISION, preview_takeout
from spikes.notebooklm_project_import import NotebookLMProjectImport
from spikes.project_creation import ProjectCreation, STAGES
from spikes.projects import Projects
from spikes.storage import Git


ROOT = 'Takeout/NotebookLM/Demo notebook'
STAMP = '2026-10-08T03:01:03.123456Z'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def notebook_metadata():
    return encoded({'title': 'Demo notebook', 'emoji': '📓', 'metadata': {
        'createTime': STAMP, 'isShared': False, 'lastViewed': STAMP}})


def source_metadata(source_type='SOURCE_CONTENT_TYPE_GOOGLE_DOC', extra=None):
    metadata = {'originalSourceContentType': source_type,
                'revisionData': {'dateAdded': STAMP},
                'sourceAddedTimestamp': STAMP}
    if source_type == 'SOURCE_CONTENT_TYPE_GOOGLE_DOC':
        metadata['googleDocsMetadata'] = {'documentId': 'doc-id', 'revisionId': 'revision-id'}
    if extra:
        metadata.update(extra)
    return encoded({'title': 'Source title', 'metadata': metadata})


def artifact_metadata():
    return encoded({
        'sources': [{'sourceId': {'id': '12345678-1234-4123-8123-123456789abc'},
                     'sourceContentType': 'SOURCE_CONTENT_TYPE_GOOGLE_DOC'}],
        'status': 'ARTIFACT_STATUS_READY',
        'tailoredReport': {'generationOptions': {'language': 'cs'}},
        'title': 'Report', 'type': 'ARTIFACT_TYPE_TAILORED_REPORT'})


def valid_members():
    return {
        f'{ROOT}/Demo notebook metadata.json': notebook_metadata(),
        f'{ROOT}/Sources/Source metadata.json': source_metadata(),
        f'{ROOT}/Sources/Source.html': b'<html><body>source</body></html>',
        f'{ROOT}/Artifacts/Report metadata.json': artifact_metadata(),
        f'{ROOT}/Artifacts/Report.md': b'# Generated report\n',
        f'{ROOT}/Chat History/chat.html': b'USER:<p>Hello</p>MODEL:<p>Hi</p>',
        f'{ROOT}/Discovered Sources/discovered.json': encoded({
            'createdAt': STAMP, 'discoverSourcesJob': {'query': 'example'},
            'lastUpdateTime': STAMP}),
    }


class NotebookLMTakeoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='notebooklm takeout ')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def archive(self, members=None, special=None, name='takeout.tgz'):
        path = self.base / name
        with tarfile.open(path, 'w:gz') as bundle:
            for member_name, raw in (members or valid_members()).items():
                info = tarfile.TarInfo(member_name)
                info.size = len(raw)
                info.mode = 0o600
                bundle.addfile(info, io.BytesIO(raw))
            if special:
                bundle.addfile(special)
        return path

    def test_valid_personal_takeout_preview_is_content_free_and_stable(self):
        path = self.archive()
        preview = preview_takeout(path)
        self.assertEqual(PARSER_REVISION, preview['format'])
        self.assertEqual(1, len(preview['notebooks']))
        notebook = preview['notebooks'][0]
        self.assertTrue(notebook['importable'])
        self.assertEqual('Demo notebook', notebook['title'])
        self.assertEqual(1, len(notebook['sources']))
        self.assertEqual('SOURCE_CONTENT_TYPE_GOOGLE_DOC', notebook['sources'][0]['source_type'])
        self.assertEqual(1, notebook['chats'][0]['user_messages'])
        self.assertEqual(1, notebook['chats'][0]['model_messages'])
        self.assertEqual(64, len(notebook['selection_digest']))
        self.assertNotIn('doc-id', json.dumps(preview, ensure_ascii=False))
        self.assertNotIn('Hello', json.dumps(preview, ensure_ascii=False))
        materialized = NotebookLMTakeout(path).materialize(
            preview['archive_sha256'], notebook['selection_digest'])
        self.assertEqual(set(valid_members()), set(materialized['members']))

    def test_materialization_rejects_changed_archive_and_selection(self):
        path = self.archive()
        preview = preview_takeout(path)
        selection = preview['notebooks'][0]['selection_digest']
        with self.assertRaisesRegex(ValidationError, 'changed since preview'):
            NotebookLMTakeout(path).materialize('0' * 64, selection)
        with self.assertRaisesRegex(ValidationError, 'missing or ambiguous'):
            NotebookLMTakeout(path).materialize(preview['archive_sha256'], '0' * 64)

    def test_unknown_category_is_reported_and_blocks_import(self):
        members = valid_members()
        members[f'{ROOT}/Notes/note.txt'] = b'note'
        notebook = preview_takeout(self.archive(members))['notebooks'][0]
        self.assertFalse(notebook['importable'])
        self.assertEqual([{'category': 'Notes', 'count': 1}], notebook['unsupported'])

    def test_unknown_source_metadata_field_fails_closed(self):
        members = valid_members()
        members[f'{ROOT}/Sources/Source metadata.json'] = source_metadata(extra={'newField': True})
        with self.assertRaisesRegex(ValidationError, 'Unsupported NotebookLM source metadata'):
            preview_takeout(self.archive(members))

    def test_traversal_path_is_rejected(self):
        members = valid_members()
        members['Takeout/NotebookLM/../escape.txt'] = b'bad'
        with self.assertRaisesRegex(ValidationError, 'Unsafe Takeout member path'):
            preview_takeout(self.archive(members))

    def test_symlink_is_rejected(self):
        link = tarfile.TarInfo(f'{ROOT}/Sources/link.html')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/passwd'
        with self.assertRaisesRegex(ValidationError, 'non-regular member'):
            preview_takeout(self.archive(special=link))

    def test_duplicate_and_case_colliding_paths_are_rejected(self):
        members = valid_members()
        duplicate = tarfile.TarInfo(f'{ROOT}/Sources/source.html')
        duplicate.size = 0
        with self.assertRaisesRegex(ValidationError, 'duplicate or case-colliding'):
            preview_takeout(self.archive(members, duplicate))

    def test_nested_archive_is_rejected(self):
        members = valid_members()
        members[f'{ROOT}/Sources/bundle.zip'] = b'PK\x03\x04'
        with self.assertRaisesRegex(ValidationError, 'Nested archives'):
            preview_takeout(self.archive(members))

    def test_orphan_content_is_rejected(self):
        members = valid_members()
        members[f'{ROOT}/Sources/Orphan.html'] = b'orphan'
        with self.assertRaisesRegex(ValidationError, 'orphan content'):
            preview_takeout(self.archive(members))

    def test_script_in_chat_is_rejected(self):
        members = valid_members()
        members[f'{ROOT}/Chat History/chat.html'] = b'USER:<p>x</p><script>bad()</script>'
        with self.assertRaisesRegex(ValidationError, 'Unsupported NotebookLM chat structure'):
            preview_takeout(self.archive(members))

    def test_broken_gzip_is_rejected(self):
        path = self.base / 'broken.tgz'
        path.write_bytes(b'not a gzip archive')
        with self.assertRaisesRegex(ValueError, 'Invalid Takeout TGZ'):
            preview_takeout(path)

    def test_input_symlink_is_rejected(self):
        target = self.archive()
        link = self.base / 'takeout-link.tgz'
        link.symlink_to(target)
        with self.assertRaisesRegex(ValidationError, 'must not contain symlinks'):
            preview_takeout(link)


class NotebookLMProjectImportTests(unittest.TestCase):
    archive = NotebookLMTakeoutTests.archive

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='notebooklm project import ')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'
        self.target = self.base / 'Imported notebook'
        self.service = NotebookLMProjectImport(self.node)
        self.operation = str(uuid4())
        self.archive_path = self.archive()
        preview = self.service.preview(self.archive_path)
        self.plan = self.service.plan(
            self.archive_path, preview['notebooks'][0]['selection_digest'],
            self.target, 'confidential', self.operation,
            imported_at='2026-10-08T04:00:00.000000Z')

    def test_confirm_creates_one_project_commit_with_exact_export_bytes(self):
        receipt = self.service.confirm(self.archive_path, self.plan)
        self.assertEqual(self.plan['project_id'], receipt['id'])
        git = Git(self.target)
        self.assertEqual('1', git.run('rev-list', '--count', 'HEAD').stdout.strip())
        snapshot = git.snapshot('HEAD')
        self.assertEqual(12, len(snapshot))
        entities = Projects(self.node).open(receipt['id'])['artifacts']
        self.assertEqual(6, len(entities))
        source = next(item for item in self.plan['artifacts'] if item['role'] == 'source')
        self.assertEqual(valid_members()[source['content_path']],
                         snapshot[f"artifacts/{source['id']}/source.html"])
        envelope = next(item for item in self.plan['artifacts'] if item['role'] == 'export-metadata')
        raw = snapshot[f"artifacts/{envelope['id']}/export-metadata.json"]
        records = json.loads(raw)['records']
        source_meta = next(item for item in records if item['path'].endswith('/Source metadata.json'))
        self.assertEqual(valid_members()[source_meta['path']], base64.b64decode(source_meta['base64']))
        self.assertEqual(receipt, self.service.confirm(self.archive_path, self.plan))
        duplicate = self.service.plan(
            self.archive_path, self.plan['selection_digest'], self.base / 'second import',
            'confidential', str(uuid4()), imported_at='2026-10-08T04:05:00.000000Z')
        self.assertEqual([{'project_id': receipt['id'], 'title': 'Demo notebook'}],
                         duplicate['existing_imports'])

    def test_changed_plan_and_archive_fail_before_project_publication(self):
        changed = dict(self.plan, privacy='public')
        with self.assertRaisesRegex(ValidationError, 'changed after preview'):
            self.service.confirm(self.archive_path, changed)
        members = valid_members(); members[f'{ROOT}/Sources/Source.html'] = b'changed'
        changed_archive = self.archive(members, name='changed.tgz')
        with self.assertRaisesRegex(ValidationError, 'changed since preview'):
            self.service.confirm(changed_archive, self.plan)
        self.assertFalse(self.target.exists())

    def test_plan_selects_one_project_from_archive_with_multiple_projects(self):
        members = valid_members()
        second_root = 'Takeout/NotebookLM/Second project'
        second = {path.replace(ROOT, second_root): raw for path, raw in members.items()}
        second[f'{second_root}/Demo notebook metadata.json'] = encoded({
            'title': 'Second project', 'emoji': '📘', 'metadata': {
                'createTime': STAMP, 'isShared': False, 'lastViewed': STAMP}})
        members.update(second)
        archive = self.archive(members, name='multiple-projects.tgz')
        preview = self.service.preview(archive)
        self.assertEqual(['Demo notebook', 'Second project'],
                         sorted(item['title'] for item in preview['notebooks']))
        selected = next(item for item in preview['notebooks'] if item['title'] == 'Second project')
        plan = self.service.plan(
            archive, selected['selection_digest'], self.base / 'second project target',
            'project', str(uuid4()), imported_at='2026-10-08T04:00:00.000000Z')
        self.assertEqual('Second project', plan['title'])
        self.assertEqual(selected['selection_digest'], plan['selection_digest'])

    def test_crash_before_build_recovers_same_seed_without_archive(self):
        with self.assertRaises(RuntimeError):
            self.service.confirm(
                self.archive_path, self.plan,
                checkpoint=lambda stage: (_ for _ in ()).throw(RuntimeError('stop'))
                if stage == 'prepared' else None)
        self.archive_path.unlink()
        receipt = self.service.confirm(self.archive_path, self.plan)
        self.assertEqual(self.plan['project_id'], receipt['id'])
        self.assertEqual('1', Git(self.target).run('rev-list', '--count', 'HEAD').stdout.strip())

    def test_every_durable_boundary_recovers_without_duplicate_project_or_commit(self):
        for stage in STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(
                    prefix='notebooklm boundary ') as temporary:
                root = Path(temporary)
                fixture = object.__new__(NotebookLMTakeoutTests); fixture.base = root
                archive = NotebookLMTakeoutTests.archive(fixture)
                service = NotebookLMProjectImport(root / 'node.json')
                preview = service.preview(archive)
                plan = service.plan(
                    archive, preview['notebooks'][0]['selection_digest'], root / 'project',
                    'project', str(uuid4()), imported_at='2026-10-08T04:00:00.000000Z')
                with self.assertRaises(RuntimeError):
                    service.confirm(
                        archive, plan,
                        checkpoint=lambda current: (_ for _ in ()).throw(RuntimeError('stop'))
                        if current == stage else None)
                recovered = ProjectCreation(root / 'node.json').recover()
                replay = service.confirm(archive, plan)
                if recovered is not None:
                    self.assertEqual(recovered, replay)
                self.assertEqual('1', Git(root / 'project').run(
                    'rev-list', '--count', 'HEAD').stdout.strip())
                self.assertEqual(1, len(Projects(root / 'node.json').list()))

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1',
                         'Requires real Qt widgets')
    def test_native_dialog_requires_preview_plan_and_explicit_confirmation(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from spikes.desktop_notebooklm_import import NotebookLMImportDialog
        app = QApplication.instance() or QApplication([])
        dialog = NotebookLMImportDialog(None, self.service, self.base)
        dialog.archive.setText(str(self.archive_path)); dialog.root.setText(str(self.target))
        dialog.load_preview()
        self.assertTrue(dialog.notebook.isEnabled())
        self.assertEqual(1, dialog.notebook.count())
        dialog.validate()
        self.assertIsNotNone(dialog.plan)
        self.assertEqual(QDialog.DialogCode.Rejected, dialog.result())
        dialog.confirm.setChecked(True); dialog.validate()
        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        dialog.deleteLater(); app.processEvents()


@unittest.skipUnless(os.environ.get('NOTEBOOKLM_TAKEOUT_SAMPLE'),
                     'Set NOTEBOOKLM_TAKEOUT_SAMPLE to a private Takeout TGZ')
class ActualNotebookLMTakeoutTests(unittest.TestCase):
    def test_private_sample_is_structurally_importable(self):
        preview = preview_takeout(os.environ['NOTEBOOKLM_TAKEOUT_SAMPLE'])
        self.assertGreater(len(preview['notebooks']), 0)
        self.assertTrue(all(item['importable'] for item in preview['notebooks']))

    def test_largest_private_notebook_imports_and_reopens(self):
        archive = os.environ['NOTEBOOKLM_TAKEOUT_SAMPLE']
        with tempfile.TemporaryDirectory(prefix='notebooklm actual acceptance ') as temporary:
            root = Path(temporary); service = NotebookLMProjectImport(root / 'node.json')
            preview = service.preview(archive)
            chosen = max(preview['notebooks'], key=lambda item: item['declared_bytes'])
            plan = service.plan(archive, chosen['selection_digest'], root / 'project',
                                'confidential', str(uuid4()),
                                imported_at='2026-10-08T04:00:00.000000Z')
            receipt = service.confirm(archive, plan)
            reopened = Projects(root / 'node.json').open(receipt['id'])
            self.assertEqual(receipt['commit_id'], reopened['commit_id'])
            self.assertEqual(len(plan['artifacts']), len(reopened['artifacts']))
            formats = {
                Projects(root / 'node.json').preview(
                    receipt['id'], item['id'], receipt['commit_id'])['format']
                for item in reopened['artifacts']
            }
            self.assertIn('markdown', formats)
            self.assertEqual('1', Git(root / 'project').run(
                'rev-list', '--count', 'HEAD').stdout.strip())
            self.assertEqual(receipt, service.confirm(archive, plan))


if __name__ == '__main__':
    unittest.main()
