# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import subprocess
import sys
from uuid import uuid4
import unittest
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.chat_service import ChatService
from spikes.metadata import validate_snapshot
from spikes.ollama_backend import OllamaAdapter
from spikes.projects import Projects
from spikes.task_outcomes import TaskOutcomes
from spikes.task_plan import ExplicitTaskPlan
from tests import test_chat_service as fixtures
from tests.fixtures import ENTITY


class FileEditTests(unittest.TestCase):
    setUp = fixtures.ChatServiceTests.setUp
    request = fixtures.ChatServiceTests.request
    pin_run_choice = fixtures.ChatServiceTests.pin_run_choice
    route_request = fixtures.ChatServiceTests.route_request

    def create_document(self, body='Original body\n', *, privacy='project'):
        id_ = str(uuid4())
        Artifacts(self.node_path).save(dict(project_id=ENTITY, artifact_id=id_, new=True,
            base_head=self.git.head(), title='Selected document', body=body), str(uuid4()), privacy=privacy)
        return id_

    def generate(self, target=None, **changes):
        target = target or self.create_document()
        request = self.route_request(output_kind='file-edit', selected_artifact_ids=[target], **changes)
        request['task_plan']['target_artifact_id'] = target
        calls = []
        def transport(binding, raw):
            calls.append(json.loads(raw))
            return {'model': binding.model, 'response': json.dumps(dict(schema_version=1,
                kind='artifact-draft', artifact_kind='document', title='Model tries to rename', content='Proposed body\n'))}
        service = ChatService(self.node_path, Projects(self.node_path), state_dir=self.chat_state,
                              adapter_factory=lambda runs: OllamaAdapter(runs, transport=transport))
        return service, request, calls

    def preview(self, service, request, replacement='Proposed body\n'):
        return service.task_preview_file_edit(dict(project_id=ENTITY, task_id=request['task_id'], body=replacement))

    def confirmation(self, preview):
        return dict(preview['confirmation'], operation_id=str(uuid4()))

    def test_generation_binds_manifest_target_without_writing_and_confirmation_updates_only_it(self):
        service, request, calls = self.generate(); before = self.git.head()
        routed = service.task_route(request)
        self.assertEqual(before, self.git.head())
        self.assertIn(request['task_plan']['target_artifact_id'], calls[0]['prompt'])
        self.assertEqual('Selected document', routed['projection']['outcome']['title'])
        preview = self.preview(service, request, 'Edited by user\n')
        self.assertIn('-Original body', preview['diff']); self.assertIn('+Edited by user', preview['diff'])
        confirmation = self.confirmation(preview)
        result = service.task_confirm_file_edit(confirmation)
        self.assertEqual('completed', result['state'])
        self.assertEqual(request['task_plan']['target_artifact_id'], result['outcome']['artifact_id'])
        self.assertEqual(result, service.task_confirm_file_edit(confirmation))
        head = self.git.head(); self.assertNotEqual(before, head)
        self.assertEqual([f'artifacts/{confirmation["artifact_id"]}/content.md',
                          f'artifacts/{confirmation["artifact_id"]}/metadata.json'],
                         self.git.run('diff', '--name-only', before, head).stdout.splitlines())
        entities = validate_snapshot(self.git.snapshot(head))
        self.assertEqual('llm-transformed', entities[confirmation['artifact_id']]['provenance'])
        self.assertEqual('Selected document', entities[confirmation['artifact_id']]['title'])
        self.assertEqual('Edited by user\n', self.git.snapshot(head)[f'artifacts/{confirmation["artifact_id"]}/content.md'].decode())

    def test_modified_payload_wrong_target_and_generic_create_are_rejected(self):
        service, request, _ = self.generate(); service.task_route(request); before = self.git.head()
        confirmation = self.confirmation(self.preview(service, request))
        for changes in [dict(approved=False), dict(body='Unreviewed body'), dict(artifact_id=str(uuid4())),
                        dict(base_head='a'*40), dict(approval_digest='0'*64), dict(extra=True)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.task_confirm_file_edit(confirmation|changes)
        with self.assertRaises(ValueError):
            service.task_publish_artifact(dict(task_id=request['task_id'], artifact_id=str(uuid4()), operation_id=str(uuid4())))
        self.assertEqual(before, self.git.head())
        result = service.task_cancel(dict(task_id=request['task_id']))
        self.assertEqual('cancelled', result['state']); self.assertEqual(before, self.git.head())

    def test_target_must_be_selected_supported_writable_and_not_downgrade_context(self):
        service, request, calls = self.generate()
        foreign = str(uuid4())
        with self.assertRaises(ValueError): ExplicitTaskPlan.parse(request['task_plan']).validate_request_selections(artifact_ids=[foreign], message_ids=[])
        with patch.object(service.projects, 'replication', return_value={'role':'read-only-replica'}):
            with self.assertRaises(ValueError): service.task_route(request)
        with self.assertRaises(ValueError): service.task_route(request|{'privacy':'confidential'})
        self.assertEqual([], calls)
        from spikes.presentation_documents import encode_deck, new_deck
        target = self.create_document(encode_deck(new_deck()))
        another, routed, invocations = self.generate(target)
        with self.assertRaises(ValueError): another.task_route(routed)
        self.assertEqual([], invocations)

    def test_stale_target_and_revoked_permissions_do_not_write(self):
        service, request, _ = self.generate(); service.task_route(request)
        confirmation = self.confirmation(self.preview(service, request))
        self.create_document('Unrelated newer commit')
        head = self.git.head()
        with self.assertRaises(ValueError): service.task_confirm_file_edit(confirmation)
        self.assertEqual(head, self.git.head())
        owner = service._identity()[1]
        with service.as_user(owner, project_ids=[ENTITY], writable_project_ids=[]):
            with self.assertRaises(ValueError): self.preview(service, request)
        with service.as_user(str(uuid4()), project_ids=[ENTITY], writable_project_ids=[ENTITY]):
            with self.assertRaises(ValueError): self.preview(service, request)

    def test_lost_reply_resumes_exact_operation_without_second_commit(self):
        service, request, _ = self.generate(); service.task_route(request)
        confirmation = self.confirmation(self.preview(service, request))
        def stop(stage):
            if stage=='file-edit-before-outcome': raise RuntimeError('lost reply')
        with self.assertRaises(RuntimeError): service.task_confirm_file_edit(confirmation, checkpoint=stop)
        committed = self.git.head()
        restarted = ChatService(self.node_path, Projects(self.node_path), state_dir=self.chat_state)
        pending = self.preview(restarted, request)
        self.assertTrue(pending['pending_confirmation']); self.assertEqual(confirmation, pending['confirmation'])
        with self.assertRaises(ValueError): restarted.task_cancel(dict(task_id=request['task_id']))
        result = restarted.task_confirm_file_edit(confirmation)
        self.assertEqual('completed', result['state']); self.assertEqual(committed, self.git.head())

    def test_cancelling_bound_but_unwritten_approval_prevents_late_write(self):
        service, request, _ = self.generate(); service.task_route(request)
        confirmation = self.confirmation(self.preview(service, request)); before = self.git.head()
        def stop(stage):
            if stage=='file-edit-approval-bound': service.task_cancel(dict(task_id=request['task_id']))
        with self.assertRaises(ValueError): service.task_confirm_file_edit(confirmation, checkpoint=stop)
        self.assertEqual(before, self.git.head())
        node, user = service._identity()
        self.assertEqual('cancelled', TaskOutcomes(self.chat_state).get(request['task_id'], node, user)['state'])

    def test_process_crashes_resume_across_approval_journal_commit_and_outcome(self):
        code = '''
import json,os,sys
from spikes.chat_service import ChatService
from spikes.projects import Projects
service=ChatService(sys.argv[1],Projects(sys.argv[1]),state_dir=sys.argv[2])
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
service.task_confirm_file_edit(json.loads(sys.argv[3]),checkpoint=stop)
'''
        for stage in ['file-edit-approval-bound', 'prepared', 'files-applied', 'ref-updated', 'file-edit-before-outcome']:
            with self.subTest(stage=stage):
                service, request, _ = self.generate(); service.task_route(request)
                confirmation = self.confirmation(self.preview(service, request)); before = self.git.head()
                result = subprocess.run([sys.executable, '-c', code, str(self.node_path), str(self.chat_state),
                                         json.dumps(confirmation), stage], capture_output=True, timeout=30)
                self.assertEqual(73, result.returncode, result.stderr)
                restarted = ChatService(self.node_path, Projects(self.node_path), state_dir=self.chat_state)
                completed = restarted.task_confirm_file_edit(confirmation)
                self.assertEqual('completed', completed['state'])
                self.assertEqual('1', self.git.run('rev-list', '--count', before+'..HEAD').stdout.strip())
                self.assertEqual('', self.git.run('status', '--porcelain').stdout)
                self.assertEqual(completed, restarted.task_confirm_file_edit(confirmation))

    def test_invalid_roadmap_rejected_by_preview_and_native_transformation_writer(self):
        from spikes.markdown_documents import main_todo_id
        target = main_todo_id(ENTITY)
        original = '- [ ] [TASK-A] A\n- [ ] [TASK-B] B\n  - depends_on: TASK-A\n'
        Artifacts(self.node_path).save(dict(project_id=ENTITY, artifact_id=target, base_head=self.git.head(),
            title='Roadmap', body=original, new=True), str(uuid4()))
        service, request, _ = self.generate(target); service.task_route(request)
        bad = original.replace('[TASK-A] A', '[TASK-A] A\n  - depends_on: TASK-B')
        before = self.git.head()
        with self.assertRaises(ValueError): self.preview(service, request, bad)
        with self.assertRaises(ValueError):
            Artifacts(self.node_path).save(dict(project_id=ENTITY, artifact_id=target, base_head=before,
                title='Roadmap', body=bad, new=False), str(uuid4()),
                transformation={key:str(uuid4()) for key in ('task_id','run_id','manifest_id')})
        self.assertEqual(before, self.git.head()); self.assertEqual('', self.git.run('status','--porcelain').stdout)

    def test_missing_and_non_markdown_targets_fail_before_model_dispatch(self):
        service, request, calls = self.generate(str(uuid4()))
        with self.assertRaises(ValueError): service.task_route(request)
        self.assertEqual([], calls)
        target = self.create_document(); directory=self.root/'artifacts'/target
        metadata=json.loads((directory/'metadata.json').read_text());metadata['file']='content.txt'
        (directory/'metadata.json').write_text(json.dumps(metadata));(directory/'content.md').rename(directory/'content.txt')
        self.git.commit('Unsupported text target fixture')
        service, request, calls = self.generate(target)
        with self.assertRaises(ValueError): service.task_route(request)
        self.assertEqual([], calls)

