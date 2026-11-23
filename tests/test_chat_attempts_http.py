# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4
from unittest.mock import patch
from tests import test_web_server as fixtures


class ChatAttemptHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WebTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        code, data, _ = self.f.create_project('Submission recovery')
        self.assertEqual(code, 200, data); self.pid = json.loads(data)['id']

    def request(self, path, body, headers=None):
        code, data, _ = self.f.request(path=path, body=json.dumps(body), headers=headers)
        return code, json.loads(data)

    def test_prevalidation_rejection_keeps_prompt_and_safe_diagnostic_without_a_model(self):
        prompt = 'Rozsáhlé české zadání\n' * 1800
        task = str(uuid4())
        request = dict(project_id=self.pid, task_id=task, content=prompt, privacy='project')
        code, error = self.request('/v1/tasks/route', request)
        self.assertEqual(code, 422, error)
        self.assertEqual(error['request_id'], task); self.assertTrue(error['prompt_saved'])
        code, value = self.request('/v1/tasks/list', dict(project_id=self.pid))
        self.assertEqual(code, 200, value); self.assertEqual(value['outcomes'], [])
        summary = value['attempts'][0]
        self.assertEqual(summary['state'], 'failed'); self.assertNotIn('content', summary)
        self.assertEqual(summary['diagnostic']['exception_type'], 'ValidationError')
        self.assertEqual(summary['diagnostic']['module'], 'chat_service.py')
        code, restored = self.request('/v1/tasks/list', dict(project_id=self.pid, attempt_id=task))
        self.assertEqual(code, 200, restored)
        self.assertEqual(restored['attempts'][0]['content'], prompt)

    def test_capture_failure_prevents_dispatch_and_does_not_claim_prompt_is_saved(self):
        with patch('spikes.chat_attempts.ChatAttempts.begin', side_effect=OSError('disk unavailable')):
            with patch.object(self.f.server.chat_service, 'task_route') as native:
                code, error = self.request('/v1/tasks/route', dict(project_id=self.pid,
                    task_id=str(uuid4()), content='Keep in composer', privacy='project'))
                self.assertEqual(code, 422, error); native.assert_not_called()
                self.assertEqual(error['outcome'], 'not-started')
                self.assertNotIn('prompt_saved', error)

    def test_privacy_conflict_has_same_actionable_payload_in_http_and_stream(self):
        from spikes.task_file_edit import FileEditPrivacyConflict
        target = str(uuid4())
        conflict = FileEditPrivacyConflict(target, 'project', 'confidential')
        for path in ['/v1/tasks/route', '/v1/tasks/route-stream']:
            with self.subTest(path=path), patch.object(self.f.server.chat_service,
                    'task_route', side_effect=conflict):
                code, raw, _ = self.f.request(path=path, body=json.dumps(dict(
                    project_id=self.pid, task_id=str(uuid4()), run_id=str(uuid4()), content='Update target', privacy='project')))
                if path.endswith('-stream'):
                    self.assertEqual(code, 200)
                    result = next(item for item in map(json.loads, raw.decode().splitlines()) if item['type']=='error')
                else:
                    self.assertEqual(code, 422); result = json.loads(raw)
                self.assertEqual(result['diagnostic'], conflict.code)
                self.assertEqual(result['privacy_conflict'], conflict.details)
                self.assertEqual(result['outcome'], 'not-started')
                self.assertIn('Důvěrné', result['error'])

    def test_authenticated_member_cannot_read_another_users_failed_prompt(self):
        owner_task = str(uuid4())
        self.request('/v1/tasks/route', dict(project_id=self.pid, task_id=owner_task,
                     content='PRIVATE OWNER INPUT', privacy='project'))
        _, state = self.request('/v1/administration', dict(action='list'))
        _, state = self.request('/v1/administration', dict(action='create-user',
            expected_commit=state['commit_id'], name='Other user', node_role='member'))
        user = state['users'][0]; headers={'Authorization':'Bearer '+state['access_key']}
        self.request('/v1/administration', dict(action='update-user', expected_commit=state['commit_id'],
            user_id=user['id'], active=True, node_role='member', memberships={self.pid:'editor'}))
        code, data = self.request('/v1/tasks/list', dict(project_id=self.pid, attempt_id=owner_task), headers)
        self.assertEqual(code, 200, data)
        self.assertEqual(data['attempts'], []); self.assertNotIn('PRIVATE OWNER INPUT', json.dumps(data))
