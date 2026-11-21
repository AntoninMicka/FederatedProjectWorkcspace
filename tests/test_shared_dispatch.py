# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B6-T1 (B-ODD-09): one desktop/web implementation of shared routes."""
import unittest
from http.client import HTTPMessage
from pathlib import Path
from unittest.mock import MagicMock

from spikes.backend_contract import BackendResponseError
from spikes.desktop_management import DesktopManagementHandler
from spikes.desktop_ui import DesktopHandler
from spikes.node_management_routes import ADMIN_PATHS, NodeManagementRoutes
from spikes.web_server import WebHandler

ADMIN = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
EDITOR = {'id': 'user-1', 'node_role': 'member', 'memberships': {'p1': 'editor'}}


def handler(cls, path, server, actor=None):
    value = object.__new__(cls)
    value.path, value.server, value.actor, value.replies = path, server, actor, []
    value.headers = HTTPMessage()
    # The web handler re-authenticates the account at dispatch time.
    server.administration.authenticate_readonly.return_value = actor
    value.reply = lambda code, payload: value.replies.append((code, payload))
    value.send_error = lambda code, *args: value.replies.append((code, None))
    return value


def web_server(admin=True):
    server = MagicMock()
    administration = MagicMock(unsafe=True)  # has a real assert_project_writable method
    administration.is_admin.side_effect = lambda actor: admin and actor is ADMIN
    administration.assert_project_writable.return_value = None
    server.administration = administration
    return server


class WorkflowScopeTests(unittest.TestCase):
    def test_desktop_and_web_call_one_implementation_with_their_scope(self):
        for cls, actor, scope in ((DesktopHandler, None, {'owner_id': None, 'allow_local_only': True}),
                                  (WebHandler, EDITOR, {'owner_id': 'user-1', 'allow_local_only': False})):
            with self.subTest(handler=cls.__name__):
                server = web_server()
                service = server.role_workflow_service
                service.prepare.return_value = {'workflow_id': 'w1'}
                service.get.return_value = {'project_id': 'p1'}
                service.dispatch_creator.return_value = {'state': 'done'}
                value = handler(cls, '/v1/workflows/prepare', server, actor)
                value.dispatch({'project_id': 'p1', 'goal': 'x'})
                self.assertEqual(value.replies, [(200, {'workflow_id': 'w1'})])
                service.prepare.assert_called_once_with({'project_id': 'p1', 'goal': 'x'}, **scope)
                value = handler(cls, '/v1/workflows/creator/dispatch', server, actor)
                value.dispatch({'workflow_id': 'w1', 'project_id': 'p1', 'approval_digest': 'd'})
                self.assertEqual(value.replies, [(200, {'state': 'done'})])
                service.dispatch_creator.assert_called_once_with('w1', 'd', **scope)

    def test_workflow_of_another_project_is_refused_with_403_on_both(self):
        for cls, actor in ((DesktopHandler, None), (WebHandler, EDITOR)):
            with self.subTest(handler=cls.__name__):
                server = web_server()
                server.role_workflow_service.get.return_value = {'project_id': 'other'}
                value = handler(cls, '/v1/workflows/opponent/prepare', server, actor)
                value.dispatch({'workflow_id': 'w1', 'project_id': 'p1'})
                self.assertEqual(value.replies, [(403, None)])
                server.role_workflow_service.prepare_opponent.assert_not_called()

    def test_web_keeps_its_write_guard_before_shared_dispatch(self):
        server = web_server()
        reader = {'id': 'user-2', 'node_role': 'member', 'memberships': {'p1': 'reader'}}
        value = handler(WebHandler, '/v1/workflows/prepare', server, reader)
        value.dispatch({'project_id': 'p1'})
        self.assertEqual(value.replies, [(403, None)])
        server.role_workflow_service.prepare.assert_not_called()

    def test_desktop_reports_workflow_errors_as_workflow_errors(self):
        server = web_server()
        server.role_workflow_service.prepare.side_effect = ValueError('detail')
        value = handler(DesktopHandler, '/v1/workflows/prepare', server)
        value.dispatch({'project_id': 'p1'})
        self.assertEqual(value.replies[0][0], 422)
        self.assertIn('Workflow požadavek nelze provést', value.replies[0][1]['error'])
        server.role_workflow_service.prepare.side_effect = BackendResponseError('bad')
        value = handler(DesktopHandler, '/v1/workflows/prepare', server)
        value.dispatch({'project_id': 'p1'})
        self.assertEqual(value.replies, [(502, {'error': 'Workflow backend nevrátil platný výsledek.'})])


class MediaScopeTests(unittest.TestCase):
    def test_media_runs_belong_to_the_request_owner(self):
        for cls, actor, owner in ((DesktopHandler, None, None), (WebHandler, EDITOR, 'user-1')):
            with self.subTest(handler=cls.__name__):
                server = web_server()
                server.media_service.preview.return_value = {'approval': 'a'}
                value = handler(cls, '/v1/media/preview', server, actor)
                value.dispatch({'project_id': 'p1'})
                self.assertEqual(value.replies, [(200, {'approval': 'a'})])
                server.media_service.preview.assert_called_once_with({'project_id': 'p1'}, owner_id=owner)
                server.media_service.status.return_value = {'bindings': {}}
                value = handler(cls, '/v1/media/status', server, actor)
                value.dispatch({})
                server.media_service.status.assert_called_once_with(owner_id=owner)

    def test_desktop_reports_image_errors_as_image_errors(self):
        server = web_server()
        server.media_service.confirm.side_effect = ValueError('detail')
        value = handler(DesktopHandler, '/v1/media/confirm', server)
        value.dispatch({'project_id': 'p1'})
        self.assertEqual(value.replies[0][0], 422)
        self.assertIn('Obrazový požadavek nelze provést', value.replies[0][1]['error'])


class NodeManagementTests(unittest.TestCase):
    def test_desktop_and_web_share_the_management_routes(self):
        for cls in (DesktopManagementHandler, WebHandler):
            self.assertTrue(issubclass(cls, NodeManagementRoutes), cls.__name__)
            self.assertTrue(ADMIN_PATHS <= cls.post_paths, cls.__name__)
        for module in ('spikes/desktop_management.py', 'spikes/web_server.py'):
            source = Path(module).read_text()
            for duplicate in ('account_metrics_status', 'ContentSyncControl', 'ReplicationControl(',
                              'CatalogControl('):
                self.assertNotIn(duplicate, source, (module, duplicate))

    def test_both_deployments_reply_from_one_implementation(self):
        for cls, actor, deployment in ((DesktopManagementHandler, None, 'desktop'),
                                       (WebHandler, ADMIN, 'web')):
            with self.subTest(handler=cls.__name__):
                server = web_server()
                server.administration.deployment = deployment
                server.chat_service.account_metrics_status.return_value = {'report': None}
                value = handler(cls, '/v1/backend-metrics/status', server, actor)
                value.dispatch({})
                self.assertEqual(value.replies, [(200, {'report': None})])

    def test_web_requires_a_node_administrator(self):
        for path in sorted(ADMIN_PATHS):
            with self.subTest(path=path):
                server = web_server()
                value = handler(WebHandler, path, server, EDITOR)
                value.dispatch({})
                self.assertEqual(value.replies, [(403, None)])
                server.chat_service.account_metrics_status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
