# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Subsequent source revisions preserve local work and require exact review."""
import json
import io
from contextlib import redirect_stdout
import unittest
from uuid import uuid4

from spikes.markdown_documents import main_todo_id
from spikes.projects import Projects
from spikes.roadmap_bundle import project_files
from spikes.roadmap_importer import RoadmapImporter
from spikes.roadmap_source_update import RoadmapSourceUpdate
from spikes.storage import Git
from tests.fixtures import encoded, metadata
from tests import test_roadmap_importer as importer_tests
from tests.test_roadmap_mapping import MappingFixture
from scripts.roadmap_source_update import main as update_cli


class SourceUpdateTests(MappingFixture, unittest.TestCase):
    def setUp(self):
        op, blobs, bundle, self.node, roots, _, host, review, _ = importer_tests.RoadmapImporterTests.import_fixture(self)
        RoadmapImporter(self.node).apply(bundle, review, op['bundle_sha256'], source_roots=roots.values())
        self.project = host['project_id']
        self.git = Projects(self.node).repository(self.project)
        self.baseline = self.git.head()
        self.files = project_files(host, blobs)
        self.root_path = f'artifacts/{main_todo_id(self.project)}/content.md'
        self.source = Git(roots['federated-workspace'])
        (self.source.root / 'TODO.md').write_text('# New source revision\n')
        self.revision = self.source.commit('New source revision')
        self.service = RoadmapSourceUpdate(self.node)

    def request(self, incoming=None):
        return dict(project_id=self.project, baseline_commit=self.baseline,
                    expected_head=self.git.head(), source_root=self.source.root,
                    source_revision=self.revision, managed_paths=list(self.files),
                    incoming_files=incoming if incoming is not None else
                    self.files | {self.root_path: self.files[self.root_path] + b'\nNew source note.\n'})

    def apply(self, request, *, decisions=None, checkpoint=lambda stage: None, operation=None):
        preview = self.service.preview(**request, decisions=decisions)
        receipt = self.service.apply(**request, decisions=decisions,
            operation_id=operation or str(uuid4()), expected_preview_sha256=preview['preview_sha256'],
            checkpoint=checkpoint)
        return preview, receipt

    def test_new_revision_preserves_local_edits_and_unlisted_artifacts_and_replays(self):
        local = self.files[self.root_path] + b'\nLocal edit retained.\n'
        (self.git.root / self.root_path).write_bytes(local)
        identifier = str(uuid4()); path = f'artifacts/{identifier}/content.md'
        folder = self.git.root / 'artifacts' / identifier; folder.mkdir()
        (folder / 'content.md').write_bytes(b'Unlisted local document.\n')
        (folder / 'metadata.json').write_bytes(encoded(metadata('Unlisted', identifier, file='content.md')))
        self.git.commit('Local work')
        incoming = dict(self.files)
        meta_path = self.root_path.rsplit('/', 1)[0] + '/metadata.json'
        meta = json.loads(incoming[meta_path]); meta['title'] = 'Renamed source heading'
        incoming[meta_path] = encoded(meta)
        request = self.request(incoming); operation = str(uuid4())
        preview, receipt = self.apply(request, operation=operation)
        self.assertTrue(preview['ready'])
        after = self.git.snapshot(self.git.head())
        self.assertEqual(after[self.root_path], local)
        self.assertEqual(after[path], b'Unlisted local document.\n')
        self.assertEqual(json.loads(after[meta_path])['id'], main_todo_id(self.project))
        second = self.service.apply(**request, operation_id=operation,
                                   expected_preview_sha256=preview['preview_sha256'])
        self.assertEqual(receipt, second)
        self.assertEqual(self.git.run('rev-list', '--count', request['expected_head']+'..HEAD').stdout.strip(), '1')

    def test_conflict_cannot_overwrite_local_content_without_exact_review(self):
        local = self.files[self.root_path] + b'\nManual change.\n'
        (self.git.root / self.root_path).write_bytes(local)
        self.git.commit('Manual change')
        request = self.request(); before = self.git.head()
        preview = self.service.preview(**request)
        self.assertFalse(preview['ready']); self.assertIn(self.root_path, preview['unresolved'])
        with self.assertRaisesRegex(ValueError, 'Resolve source update'):
            self.service.apply(**request, operation_id=str(uuid4()),
                               expected_preview_sha256=preview['preview_sha256'])
        self.assertEqual(self.git.head(), before)
        accepted = self.service.preview(**request, decisions={self.root_path: 'source'})
        with self.assertRaisesRegex(ValueError, 'confirmation differs'):
            self.service.apply(**request, operation_id=str(uuid4()),
                expected_preview_sha256=preview['preview_sha256'], decisions={self.root_path: 'source'})
        self.service.apply(**request, operation_id=str(uuid4()),
            expected_preview_sha256=accepted['preview_sha256'], decisions={self.root_path: 'source'})
        self.assertEqual(self.git.snapshot(self.git.head())[self.root_path], request['incoming_files'][self.root_path])
        self.assertEqual(self.git.snapshot(before)[self.root_path], local)

    def test_removal_and_rename_require_review_and_preserve_stable_artifact_id(self):
        identifier = str(uuid4()); prefix = f'artifacts/{identifier}/'
        folder = self.git.root / 'artifacts' / identifier; folder.mkdir()
        old_path, new_path, meta_path = prefix+'old.md', prefix+'renamed.md', prefix+'metadata.json'
        raw = b'Document bytes.\n'
        meta = metadata('Original', identifier, file='old.md')
        (folder/'old.md').write_bytes(raw); (folder/'metadata.json').write_bytes(encoded(meta))
        self.baseline = self.git.commit('Previously imported document')
        self.files.update({old_path: raw, meta_path: encoded(meta)})
        incoming = dict(self.files); incoming.pop(old_path)
        incoming[new_path] = raw
        incoming[meta_path] = encoded(meta | {'file': 'renamed.md', 'title': 'Renamed'})
        request = self.request(incoming)
        preview = self.service.preview(**request)
        self.assertEqual(preview['unresolved'], [old_path]); self.assertFalse(preview['ready'])
        self.apply(request, decisions={old_path: 'source'})
        after = self.git.snapshot(self.git.head())
        self.assertNotIn(old_path, after); self.assertEqual(after[new_path], raw)
        self.assertEqual(json.loads(after[meta_path])['id'], identifier)
        self.baseline = self.git.head(); self.files = {path: after[path] for path in incoming}
        incoming = {path: content for path, content in self.files.items() if not path.startswith(prefix)}
        request = self.request(incoming)
        preview = self.service.preview(**request)
        self.assertEqual(set(preview['unresolved']), {new_path, meta_path})
        self.apply(request, decisions={new_path: 'source', meta_path: 'source'})
        self.assertFalse(any(path.startswith(prefix) for path in self.git.snapshot(self.git.head())))

    def test_invalid_candidate_immutable_source_and_stale_head_are_rejected(self):
        incoming = dict(self.files)
        source_path = next(path for path in incoming if path.endswith('/metadata.json')
                           and json.loads(incoming[path])['kind'] == 'source')
        source_meta = json.loads(incoming[source_path])
        content_path = source_path.rsplit('/', 1)[0] + '/' + source_meta['file']
        incoming[content_path] += b'changed'
        preview = self.service.preview(**self.request(incoming))
        self.assertFalse(preview['ready']); self.assertIn('Source content differs', preview['validation_error'])
        request = self.request()
        self.git.run('commit', '--allow-empty', '-m', 'Concurrent change')
        with self.assertRaisesRegex(ValueError, 'Project changed before source update'):
            self.service.preview(**request)

    def test_crash_recovery_and_lost_reply_return_one_receipt(self):
        for boundary in ('prepared', 'ref-updated', 'index-published', 'completed'):
            with self.subTest(boundary=boundary):
                request = self.request(self.files | {
                    self.root_path: self.files[self.root_path] + ('\nSource ' + boundary + '\n').encode()})
                operation = str(uuid4()); decisions = {self.root_path: 'source'}
                preview = self.service.preview(**request, decisions=decisions)
                with self.assertRaisesRegex(RuntimeError, 'power loss'):
                    self.service.apply(**request, decisions=decisions, operation_id=operation,
                        expected_preview_sha256=preview['preview_sha256'],
                        checkpoint=lambda stage: (_ for _ in ()).throw(RuntimeError('power loss'))
                        if stage == boundary else None)
                receipt = self.service.apply(**request, decisions=decisions, operation_id=operation,
                                            expected_preview_sha256=preview['preview_sha256'])
                self.assertEqual(receipt['commit_id'], self.git.head())
                self.assertEqual(self.git.run('rev-list', '--count', request['expected_head']+'..HEAD').stdout.strip(), '1')
                with self.assertRaisesRegex(ValueError, 'different request'):
                    self.service.apply(**request, decisions=decisions, operation_id=operation,
                                       expected_preview_sha256='0'*64)

    def test_dirty_projection_and_changed_preview_cannot_write(self):
        request = self.request(); preview = self.service.preview(**request)
        (self.git.root / self.root_path).write_bytes(b'Uncommitted work\n')
        with self.assertRaisesRegex(ValueError, 'Clean worktree'):
            self.service.apply(**request, operation_id=str(uuid4()),
                               expected_preview_sha256=preview['preview_sha256'])
        self.assertEqual(self.git.head(), request['expected_head'])
        (self.git.root / self.root_path).write_bytes(self.files[self.root_path])
        request['incoming_files'][self.root_path] += b'Changed after review\n'
        with self.assertRaisesRegex(ValueError, 'confirmation differs'):
            self.service.apply(**request, operation_id=str(uuid4()),
                               expected_preview_sha256=preview['preview_sha256'])

    def test_unknown_decisions_partial_artifacts_paths_and_unpinned_revision_fail_closed(self):
        for override in ({'source_revision': 'HEAD'}, {'managed_paths': [self.root_path]},
                         {'managed_paths': ['../../etc/passwd']},
                         {'incoming_files': {'registries/tasks/x.json': b'{}'}}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.service.preview(**(self.request() | override))
        with self.assertRaisesRegex(ValueError, 'Invalid source review decision'):
            self.service.preview(**self.request(), decisions={'unknown': 'source'})

    def test_invalid_task_graph_is_visible_and_never_applied(self):
        request = self.request(self.files | {self.root_path: self.files[self.root_path] * 2})
        preview = self.service.preview(**request)
        self.assertFalse(preview['ready']); self.assertTrue(preview['validation_error'])
        with self.assertRaisesRegex(ValueError, 'Resolve source update review'):
            self.service.apply(**request, operation_id=str(uuid4()),
                               expected_preview_sha256=preview['preview_sha256'])
        self.assertEqual(self.git.head(), request['expected_head'])

    def test_cli_previews_then_applies_only_with_explicit_digest_and_operation(self):
        request = self.request(); preview = self.service.preview(**request)
        path = self.source.root.parent/'source-update-request.json'
        path.write_text(json.dumps(preview['request']))
        arguments = ['--node', str(self.node), '--request', str(path)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(update_cli(arguments + ['preview']), 0)
        self.assertEqual(json.loads(output.getvalue()), preview)
        self.assertEqual(self.git.head(), request['expected_head'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(update_cli(arguments + ['apply', '--operation-id', str(uuid4()),
                '--expected-preview-sha256', preview['preview_sha256']]), 0)
        self.assertNotEqual(self.git.head(), request['expected_head'])


if __name__ == '__main__':
    unittest.main()
