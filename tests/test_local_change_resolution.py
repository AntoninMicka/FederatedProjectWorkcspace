# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
import sqlite3
import unittest
from contextlib import closing
from uuid import uuid4

from spikes.artifact_git import ArtifactGit, canonical, digest
from spikes.local_change_resolution import LocalChangeResolution
from spikes.metadata import ValidationError
from spikes.journal import RecoveryConflict
from tests import test_conflict_resolution as fixture


class LocalChangeResolutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ConflictResolutionTests('test_list_and_preview_are_head_bound_and_do_not_touch_project_state')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.service = LocalChangeResolution(self.f.node, network=True)
        self.target = self.f.root / self.f.path
        self.raw = b'Uncommitted reviewed edit\n'; self.target.write_bytes(self.raw)

    def preview(self, choice):
        return self.service.local_preview(self.f.project, self.f.local, self.f.path, choice)

    def confirm(self, value, operation=None, **kwargs):
        return self.service.local_confirm(**value, operation_id=operation or str(uuid4()),
            message='Resolve reviewed local edit', confirm=True, **kwargs)

    def test_both_previews_are_read_only_and_generic_web_stage_stays_forbidden(self):
        before = self.f.state()
        for choice in ('keep', 'restore'):
            value = self.preview(choice)
            self.assertEqual(value['preview']['working_sha256'], digest(self.raw))
        self.assertEqual(self.f.state(), before)
        with self.assertRaisesRegex(ValidationError, 'local desktop actions'):
            ArtifactGit(self.f.node, network=True).stage(dict(project_id=self.f.project,
                artifact_id=self.f.artifact, base_head=self.f.local, working_sha256=digest(self.raw)), str(uuid4()))

    def test_keep_publishes_one_native_commit_and_replay_preserves_later_working_edit(self):
        value = self.preview('keep'); operation = str(uuid4())
        result = self.confirm(value, operation)
        self.assertNotEqual(result['commit_id'], self.f.local)
        self.assertEqual(self.f.git.snapshot(result['commit_id'])[self.f.path], self.raw)
        self.target.write_bytes(b'Later uncommitted edit\n')
        self.assertEqual(self.confirm(value, operation), result)
        self.assertEqual(self.target.read_bytes(), b'Later uncommitted edit\n')

    def test_restore_preserves_backup_and_head_and_replay_does_not_overwrite_new_edit(self):
        value = self.preview('restore'); operation = str(uuid4())
        result = self.confirm(value, operation)
        self.assertEqual(self.f.git.head(), self.f.local)
        self.assertEqual(self.target.read_bytes(), self.f.git.snapshot(self.f.local)[self.f.path])
        with closing(sqlite3.connect(self.f.ws.journal.database)) as db:
            record, done = db.execute('SELECT record,done FROM operations WHERE id=?', (operation,)).fetchone()
        self.assertEqual(done, 1)
        self.assertEqual(base64.b64decode(json.loads(record)['backup_base64']), self.raw)
        self.target.write_bytes(b'New unrelated working version\n')
        self.assertEqual(self.confirm(value, operation), result)
        self.assertEqual(self.target.read_bytes(), b'New unrelated working version\n')

    def test_changed_working_file_and_forged_preview_are_rejected_without_writes(self):
        for choice in ('keep', 'restore'):
            self.target.write_bytes(self.raw); value = self.preview(choice)
            self.target.write_bytes(b'Changed after preview\n'); before = self.f.state()
            with self.assertRaisesRegex(ValidationError, 'changed'):
                self.confirm(value)
            self.assertEqual(self.f.state(), before)
        self.target.write_bytes(self.raw); value = self.preview('keep')
        value['preview']['commit_preview']['project_id'] = str(uuid4())
        value['approval_digest'] = digest(canonical(value['preview']))
        with self.assertRaisesRegex(ValidationError, 'differs'):
            self.confirm(value)

    def test_restore_crash_rolls_forward_and_intervening_edit_is_preserved(self):
        for crash_stage in ('working-restore-prepared', 'file:0'):
            with self.subTest(stage=crash_stage):
                self.target.write_bytes(self.raw); value = self.preview('restore'); operation = str(uuid4())
                def crash(stage):
                    if stage == crash_stage: raise RuntimeError('injected exit')
                with self.assertRaises(RuntimeError): self.confirm(value, operation, checkpoint=crash)
                self.target.write_bytes(b'Intervening user edit\n')
                with self.assertRaises(RecoveryConflict): self.confirm(value, operation)
                self.assertEqual(self.target.read_bytes(), b'Intervening user edit\n')
                self.target.write_bytes(self.raw)
                self.f.ws.recover()
                self.assertEqual(self.confirm(value, operation)['commit_id'], self.f.local)

    def test_keep_crash_after_publication_recovers_same_commit(self):
        value = self.preview('keep'); operation = str(uuid4())
        def crash(stage):
            if stage == 'ref-updated': raise RuntimeError('injected exit')
        with self.assertRaises(RuntimeError): self.confirm(value, operation, checkpoint=crash)
        published = self.f.git.head()
        self.assertEqual(self.confirm(value, operation)['commit_id'], published)
        self.assertEqual(self.f.git.snapshot(published)[self.f.path], self.raw)

    def test_keep_stage_crash_binds_full_decision_and_preserves_newer_working_bytes(self):
        value = self.preview('keep'); operation = str(uuid4())
        def crash(stage):
            if stage == 'stage-prepared': raise RuntimeError('injected exit')
        with self.assertRaises(RuntimeError): self.confirm(value, operation, checkpoint=crash)
        with self.assertRaisesRegex(ValidationError, 'different request'):
            self.service.local_confirm(**value, operation_id=operation, message='Changed intent', confirm=True)
        self.target.write_bytes(b'Newer working edit\n')
        result = self.confirm(value, operation)
        self.assertEqual(self.f.git.snapshot(result['commit_id'])[self.f.path], self.raw)
        self.assertEqual(self.target.read_bytes(), b'Newer working edit\n')

    def test_existing_project_repair_can_resume_interrupted_working_restore(self):
        from spikes.project_repair import ProjectRepairActions
        value = self.preview('restore'); operation = str(uuid4())
        def crash(stage):
            if stage == 'file:0': raise RuntimeError('injected exit')
        with self.assertRaises(RuntimeError): self.confirm(value, operation, checkpoint=crash)
        actions = ProjectRepairActions(self.f.node)
        report = actions.diagnostics.check(self.f.project)
        plan = actions.preview(dict(project_id=self.f.project, action='resume-operation',
            operation_id=str(uuid4()), check_token=report['check_token']))
        result = actions.confirm(plan)
        self.assertEqual(result['report']['status'], 'healthy')
        self.assertEqual(self.confirm(value, operation)['commit_id'], self.f.local)
