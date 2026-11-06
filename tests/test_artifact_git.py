# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from pathlib import Path
import unittest
from uuid import uuid4
from spikes.artifact_git import ArtifactGit,digest
from spikes.artifacts import Artifacts
from spikes.metadata import ValidationError
from spikes.projects import Projects
from spikes.workspace import Workspace
from tests import test_plan_draft as fixtures

class ArtifactGitTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PlanDraftTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.node=self.f.node;self.pid=self.f.pid;self.aid=self.f.aid;self.git=self.f.git;self.path=self.f.path
        self.service=ArtifactGit(self.node)

    def stage(self,body=None,checkpoint=lambda stage:None):
        if body is not None:self.path.write_text(body)
        state=self.service.status(self.pid,self.aid,self.git.head())
        request={k:state[k] for k in ['project_id','artifact_id','base_head','working_sha256']}
        op=str(uuid4());self.service.stage(request,op,checkpoint=checkpoint)
        return request,op

    def commit(self,op=None,checkpoint=lambda stage:None):
        review=self.service.preview(self.pid,self.aid,self.git.head())
        return self.service.commit(review['preview'],review['approval_digest'],'Update selected file',op or str(uuid4()),confirm=True,checkpoint=checkpoint)

    def test_only_selected_staged_file_commits_and_newer_working_edits_and_other_staging_survive(self):
        other=str(uuid4());Artifacts(self.node).save(dict(project_id=self.pid,artifact_id=other,base_head=self.git.head(),title='Other',body='base',new=True),str(uuid4()))
        other_path='artifacts/'+other+'/content.md';other_file=self.f.project_root/other_path
        other_file.write_text('foreign staged');self.git.run('add','--',other_path);other_file.write_text('foreign unstaged')
        first=fixtures.BODY+'      - First staged revision.\n';self.stage(first)
        index_tree=self.git.run('write-tree').stdout.strip()
        newer=first+'      - Newer working revision.\n';self.path.write_text(newer)
        review=self.service.preview(self.pid,self.aid,self.git.head());op=str(uuid4())
        receipt=self.service.commit(review['preview'],review['approval_digest'],'Selected only',op,confirm=True)
        self.assertEqual(self.git.snapshot(receipt['commit_id'])[review['preview']['path']],first.encode())
        self.assertEqual(self.git.snapshot(receipt['commit_id'])[other_path],b'base')
        self.assertEqual(self.path.read_text(),newer);self.assertEqual(other_file.read_text(),'foreign unstaged')
        self.assertEqual(self.git.run('show',':'+other_path).stdout,'foreign staged')
        self.assertEqual(self.git.run('write-tree').stdout.strip(),index_tree)
        self.assertEqual(self.service.commit(review['preview'],review['approval_digest'],'Selected only',op,confirm=True)['commit_id'],receipt['commit_id'])
        self.assertEqual(Projects(self.node).open(self.pid)['commit_id'],receipt['commit_id'])

    def test_stage_allows_incomplete_plan_commit_rejects_it_without_head_change(self):
        head=self.git.head();self.stage(fixtures.PARTIAL)
        self.assertEqual(self.git.head(),head)
        with self.assertRaisesRegex(ValidationError,'Roadmap'):self.service.preview(self.pid,self.aid,head)
        self.assertEqual(self.path.read_text(),fixtures.PARTIAL)
        self.assertEqual(self.git.head(),head)

    def test_stage_receipt_replay_does_not_restash_newer_working_bytes(self):
        first=fixtures.BODY+'      - First.\n';request,op=self.stage(first)
        self.path.write_text(first+'      - Later.\n')
        self.service.stage(request,op)
        self.assertEqual(self.git.run('show',':'+str(self.path.relative_to(self.f.project_root))).stdout,first)

    def test_changed_working_and_changed_stage_and_network_fail_closed(self):
        self.path.write_text(fixtures.BODY+'      - First.\n')
        state=self.service.status(self.pid,self.aid,self.git.head());request={k:state[k] for k in ['project_id','artifact_id','base_head','working_sha256']}
        self.path.write_text(fixtures.BODY+'      - Changed.\n')
        with self.assertRaisesRegex(ValidationError,'changed since preview'):self.service.stage(request,str(uuid4()))
        self.stage();review=self.service.preview(self.pid,self.aid,self.git.head())
        self.stage(fixtures.BODY+'      - Changed stage.\n')
        with self.assertRaisesRegex(ValidationError,'review again'):self.service.commit(review['preview'],review['approval_digest'],'Test',str(uuid4()),confirm=True)
        with self.assertRaisesRegex(ValidationError,'local desktop'):ArtifactGit(self.node,network=True).status(self.pid,self.aid,self.git.head())

    def test_stage_recovers_every_boundary_without_touching_working_bytes(self):
        for boundary in ['stage-prepared','stage-indexed','stage-completed']:
            with self.subTest(boundary=boundary):
                self.path.write_text(fixtures.BODY+'      - '+boundary+'\n')
                state=self.service.status(self.pid,self.aid,self.git.head());request={k:state[k] for k in ['project_id','artifact_id','base_head','working_sha256']};op=str(uuid4())
                def crash(stage):
                    if stage==boundary:raise RuntimeError('crash')
                with self.assertRaises(RuntimeError):self.service.stage(request,op,checkpoint=crash)
                before=self.path.read_bytes();self.service.stage(request,op)
                self.assertEqual(self.path.read_bytes(),before)

    def test_commit_recovers_boundary_without_duplicate_commit_or_discarding_newer_edit(self):
        for boundary in ['prepared','files-applied','commit-created','commit-ready','before-ref','ref-updated','committed','git-indexed','indexed','completed']:
            with self.subTest(boundary=boundary):
                body=fixtures.BODY+'      - '+boundary+'\n';self.stage(body)
                review=self.service.preview(self.pid,self.aid,self.git.head());op=str(uuid4())
                newer=body+'      - Newer edit.\n';self.path.write_text(newer)
                def crash(stage):
                    if stage==boundary:raise RuntimeError('crash')
                with self.assertRaises(RuntimeError):self.service.commit(review['preview'],review['approval_digest'],'Recover '+boundary,op,confirm=True,checkpoint=crash)
                receipt=self.service.commit(review['preview'],review['approval_digest'],'Recover '+boundary,op,confirm=True)
                self.assertEqual(self.git.head(),receipt['commit_id']);self.assertEqual(self.path.read_text(),newer)
                self.assertEqual(self.git.snapshot(receipt['commit_id'])[review['preview']['path']],body.encode())
