# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import http.client
import io
import os
import json
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile
import threading
import tarfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from spikes.web_server import make_server, secret, validate_hostname, WEB_HTML, WEB_CSS, WEB_JS
from spikes.desktop_ui import HTML as SHARED_HTML, CSS as SHARED_CSS, JS as SHARED_JS
from spikes.projects import Projects
from spikes.artifacts import Artifacts, main_todo_id
from tests import test_projects
from tests.fixtures import markdown, metadata, ENTITY
from spikes.source_import import Sources, request_from_bytes
from spikes.configuration import parse_node, read_config
from tests.test_notebooklm_import import valid_members


class WebTests(unittest.TestCase):
    def test_dns_hostname_validation_is_fail_closed(self):
        self.assertEqual(validate_hostname('Workspace.Cacke.Internal'),
                         'workspace.cacke.internal')
        for hostname in ('workspace', '192.168.100.20', '*.cacke.internal',
                         'bad..cacke.internal'):
            with self.subTest(hostname=hostname), self.assertRaises(ValueError):
                validate_hostname(hostname)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cert, self.key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(self.key), '-out', str(self.cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1'],
                       check=True, capture_output=True)
        self.token = secrets.token_urlsafe(32)
        self.token_file = self.root/'token'
        self.token_file.write_text(self.token); self.token_file.chmod(0o600)
        self.server = make_server('127.0.0.1', 0, '192.168.100.0/24', self.cert, self.key,
                                  self.token_file, self.root/'node.json',
                                  hostname='workspace.cacke.internal')
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        self.authority = f'127.0.0.1:{self.server.server_port}'
        self.dns_authority = f'workspace.cacke.internal:{self.server.server_port}'
        self.context = ssl.create_default_context(cafile=self.cert)

    def stop(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()

    def request(self, method='POST', path='/v1/projects', body='{}', headers=None):
        conn = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                          context=self.context, timeout=5)
        h = {'Content-Type': 'application/json', 'Authorization': 'Bearer '+self.token}
        h.update(headers or {})
        conn.request(method, path, body=body if method == 'POST' else None, headers=h)
        result = conn.getresponse()
        code, data, response_headers = result.status, result.read(), dict(result.getheaders())
        conn.close()
        return code, data, response_headers

    def create_project(self, title, operation_id=None, headers=None):
        operation_id = operation_id or str(uuid4())
        code, data, _ = self.request(path='/v1/projects/create/preview', headers=headers,
            body=json.dumps({'title': title, 'operation_id': operation_id,
                             'location_capability': None, 'remember_parent': False}))
        if code != 200:
            return code, data, {}
        return self.request(path='/v1/projects/create/confirm', headers=headers,
                            body=json.dumps({'plan': json.loads(data)}))

    def test_telemetry_uses_separate_lane_and_authority_is_request_local(self):
        self.server.application_lane.acquire()
        try:
            code, data, _ = self.request(path='/v1/node-telemetry/status',
                                         body=json.dumps({'group': 'activity'}))
        finally:
            self.server.application_lane.release()
        self.assertEqual(200, code, data)
        self.assertEqual('activity', json.loads(data)['system']['group'])
        self.assertFalse(hasattr(self.server, 'authority'))

    def test_admin_project_removal_routes_require_preview_and_restore_from_trash(self):
        code, data, _ = self.create_project('Disposable project')
        self.assertEqual(code, 200, data)
        created = json.loads(data)
        code, data, _ = self.request(path='/v1/projects/delete/preview', body=json.dumps({
            'project_id': created['id'], 'mode': 'trash'}))
        self.assertEqual(code, 200, data)
        preview = json.loads(data)
        self.assertEqual(preview['blockers'], [])
        operation = str(uuid4())
        code, data, _ = self.request(path='/v1/projects/delete/confirm', body=json.dumps({
            'preview': preview, 'operation_id': operation}))
        self.assertEqual(code, 200, data)
        self.assertTrue(json.loads(data)['unregistered'])
        code, data, _ = self.request(path='/v1/projects', body=json.dumps({'details': True}))
        self.assertEqual(json.loads(data)['projects'], [])
        code, data, _ = self.request(path='/v1/projects/delete/trash', body='{}')
        self.assertEqual(code, 200, data)
        self.assertEqual(json.loads(data)['projects'][0]['operation_id'], operation)
        code, data, _ = self.request(path='/v1/projects/delete/restore/preview',
            body=json.dumps({'operation_id': operation}))
        self.assertEqual(code, 200, data)
        restore_preview = json.loads(data)
        code, data, _ = self.request(path='/v1/projects/delete/restore/confirm', body=json.dumps({
            'preview': restore_preview, 'operation_id': str(uuid4())}))
        self.assertEqual(code, 200, data)
        self.assertTrue(json.loads(data)['restored'])
        code, data, _ = self.request(path='/v1/projects', body=json.dumps({'details': True}))
        self.assertEqual(json.loads(data)['projects'][0]['id'], created['id'])

    def test_project_repair_capability_is_not_exposed_by_network_handler(self):
        project_id = str(uuid4())
        for suffix, body in (
                ('check', {'project_id': project_id}),
                ('preview', {'project_id': project_id}),
                ('confirm', {'plan': {}}),
                ('receipt', {'project_id': project_id, 'operation_id': str(uuid4())})):
            code, data, _ = self.request(path='/v1/projects/repair/' + suffix,
                                         body=json.dumps(body))
            self.assertEqual(code, 404, data)
        self.assertFalse(hasattr(self.server, 'project_repair_actions'))

    def notebook_archive(self):
        path = self.root / 'notebooklm.tgz'
        with tarfile.open(path, 'w:gz') as bundle:
            for member_name, raw in valid_members().items():
                info = tarfile.TarInfo(member_name); info.size = len(raw); info.mode = 0o600
                bundle.addfile(info, io.BytesIO(raw))
        return path

    def test_https_auth_origin_host_routes_and_no_token_bootstrap(self):
        self.assertEqual(self.request()[0], 200)
        for headers, code in [({'Authorization':''},401), ({'Authorization':'Bearer bad'},401),
                              ({'Origin':'https://evil.invalid'},403), ({'Host':'evil.invalid'},403),
                              ({'Sec-Fetch-Site':'cross-site'},403)]:
            self.assertEqual(self.request(headers=headers)[0], code)
        self.assertEqual(self.request(headers={'Origin':'https://'+self.authority})[0],200)
        self.assertEqual(self.request(headers={'Host':self.dns_authority,
            'Origin':'https://'+self.dns_authority})[0], 200)
        self.assertEqual(self.request(headers={'Host':self.dns_authority,
            'Origin':'https://'+self.authority})[0], 403)
        self.assertEqual(self.request('GET', '/', headers={'Host':self.dns_authority})[0], 200)
        self.assertEqual(self.request(path='/v1/projects/create/preview', body='{}')[0], 422)
        code, data, _ = self.create_project('Nový projekt')
        self.assertEqual(code, 200)
        created = json.loads(data)
        code, catalog, _ = self.request(body='{"details":true}')
        self.assertEqual(code, 200)
        self.assertIn(created['id'], [p['id'] for p in json.loads(catalog)['projects']])
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':created['id']}))[0], 200)
        code, data, _ = self.request(path='/v1/workflows/status',
            body=json.dumps({'project_id': created['id']}))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data), {'workflows': []})
        code, data, _ = self.request(path='/v1/autonomy/status',
            body=json.dumps({'project_id': created['id']}))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)['workflows'], [])
        local_plan = {'schema_version': 1, 'workflow_id': str(uuid4()),
            'project_id': created['id'],
            'expected_head': self.server.projects.workspace(
                created['id'], blocking=False).git.head(),
            'mode': 'manual', 'privacy': 'local-only',
            'budget': {'max_steps': 1, 'max_cost_units': 1,
                       'max_seconds': 60},
            'steps': [{'step_id': str(uuid4()),
                'action': {'id': 'analysis.read-only', 'version': '1.0'},
                'privacy': 'local-only', 'cost_units': 1, 'depends_on': [],
                'input': {'selection_sha256': '1' * 64}}]}
        self.server.autonomy_service.prepare(local_plan)
        code, data, _ = self.request(path='/v1/autonomy/status',
            body=json.dumps({'project_id': created['id']}))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)['workflows'], [])
        code, data, _ = self.request(path='/v1/autonomy/prepare',
                                     body=json.dumps(local_plan))
        self.assertEqual(code, 422)
        self.assertIn('local-only', json.loads(data)['error'])
        for path in ('/', '/app.js', '/app.css'):
            code, data, headers = self.request('GET',path)
            self.assertEqual(code,200)
            self.assertNotIn(self.token.encode(),data)
            self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('GET','/../node.json')[0],404)
        self.assertNotIn('localStorage', WEB_JS)
        self.assertFalse(WEB_JS.endswith('loadProjects();\n'))
        self.assertEqual(WEB_HTML, SHARED_HTML)
        self.assertEqual(WEB_CSS, SHARED_CSS)
        self.assertTrue(WEB_JS.endswith(SHARED_JS))
        self.assertIn("document.body.dataset.runtime='server'", WEB_JS)
        self.assertIn('window.workspaceAutoStart=false', WEB_JS)
        self.assertIn('id="settings-users-tab"', WEB_HTML)
        self.assertIn('id="settings-cms-tab"', WEB_HTML)
        self.assertIn('id="settings-profile-tab" type="button" role="tab" aria-selected="false" aria-controls="settings-profile-panel" tabindex="-1" hidden', WEB_HTML)
        self.assertIn('data-settings-item="settings-profile-tab" hidden', WEB_HTML)
        self.assertNotIn("querySelector('#settings-profile-tab').hidden=false", WEB_JS)
        self.assertIn('id="presenter-fullscreen" type="button" hidden disabled', WEB_HTML)
        self.assertNotIn("querySelector('#presenter-fullscreen').hidden=false", WEB_JS)
        self.assertIn('id="federation-tab" role="tab" aria-label="Federace"', WEB_HTML)
        self.assertIn('id="federation-tab" role="tab" aria-label="Federace" aria-controls="sidebar-federation" aria-selected="false" tabindex="-1" hidden', WEB_HTML)
        self.assertIn("querySelector('#federation-tab').hidden=!admin", WEB_JS)
        self.assertIn("!['desktop','server'].includes(document.body.dataset.runtime)", WEB_JS)
        self.assertIn("querySelector('#open-federation-network').closest('li').hidden=true", WEB_JS)
        self.assertIn("querySelector('#open-federation-deployment').closest('li').hidden=true", WEB_JS)
        register = WEB_HTML.split('id="sidebar-register-project"', 1)[1].split('</button>', 1)[0]
        self.assertIn('hidden', register)
        self.assertNotIn("getElementById('sidebar-register-project').hidden=false", WEB_JS)
        self.assertIn('id="administration" class="settings-card" hidden', WEB_HTML)
        self.assertNotIn('<dialog id="administration"', WEB_HTML)
        self.assertIn('id="admin-peer-editor"', WEB_HTML)
        self.assertIn('id="admin-user-editor"', WEB_HTML)
        self.assertIn('id="admin-user-confirm-dialog"', WEB_HTML)
        self.assertIn('id="admin-user-add"', WEB_HTML)
        self.assertNotIn('id="admin-user-create"', WEB_HTML)
        self.assertIn('id="admin-peer-add"', WEB_HTML)
        self.assertIn('id="admin-peer-edit" type="button" disabled', WEB_HTML)
        self.assertIn('id="admin-peer-enroll" type="button" hidden disabled', WEB_HTML)
        self.assertIn('id="admin-peer-enroll-form"', WEB_HTML)
        self.assertIn('id="admin-peer-remove" class="danger" type="button" disabled', WEB_HTML)
        self.assertIn('name="sharing_level"', WEB_HTML)
        self.assertIn('id="admin-project-shares"', WEB_HTML)
        self.assertNotIn('id="admin-remote-projects"', WEB_HTML)
        self.assertIn("localExists&&remoteExists?'Sync':localExists?'Push':'Pull'", WEB_JS)
        self.assertIn('id="admin-project-share-dialog"', WEB_HTML)
        self.assertNotIn("insertBefore(document.querySelector('#admin-project-sharing')", WEB_JS)
        self.assertIn("action:'set-project-share'", WEB_JS)
        self.assertIn("'/v1/federation/catalog/reconcile'", WEB_JS)
        self.assertIn("peer.sharing_level==='external'", WEB_JS)
        self.assertIn('.admin-share-matrix thead{display:none}', WEB_CSS)
        self.assertIn('P2P — server ↔ server', WEB_HTML)
        self.assertIn("action:'convert-peer'", WEB_JS)
        self.assertIn("action:'add-peer-relationship'", WEB_JS)
        self.assertIn("'/v1/federation/enroll'", WEB_JS)
        self.assertIn('Dynamická adresa klienta', WEB_JS)
        self.assertIn('id="admin-federation-transition" hidden', WEB_HTML)
        self.assertIn("action:'update-peer'", WEB_JS)
        self.assertIn('id="admin-replication-create"', WEB_HTML)
        self.assertIn('id="admin-replications"', WEB_HTML)
        self.assertIn("fetch('/v1/replications/sync'", WEB_JS)
        self.assertIn('id="project-read-only"', WEB_HTML)
        self.assertIn("activeProject.readOnly", WEB_JS)
        self.assertIn("querySelector('#settings-users-tab').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('[data-settings-item=\"settings-users-tab\"]').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#settings-cms-tab').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#settings-access-tab').hidden=!admin", WEB_JS)
        self.assertIn('id="application-access-form"', WEB_HTML)
        self.assertIn("projectRequest('/v1/application-access',{action:'status'})", WEB_JS)
        self.assertIn("querySelector('#settings-federation-tab').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('[data-settings-item=\"settings-federation-tab\"]').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#backend-metrics-indicator').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#openai-resource-provider').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#resource-runtime-policy').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#model-catalog-import').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#model-catalog-knowledge').readOnly=!admin", WEB_JS)
        self.assertIn("querySelector('#atlascloud-backend-form').hidden=!admin", WEB_JS)
        self.assertIn("'/v1/node-telemetry/status'", WEB_JS)
        self.assertIn("'/v1/node-telemetry/configure'", WEB_JS)
        self.assertIn("'/v1/node-telemetry/run'", WEB_JS)
        self.assertIn("querySelector('#sidebar-create-project').hidden=!admin", WEB_JS)
        self.assertIn('await loadProjects();if(admin)await loadBackendMetrics()', WEB_JS)
        self.assertIn('id="workflow-tab"', WEB_HTML)
        self.assertIn('Projekt z archivu (NotebookLM notebook)', WEB_HTML)
        self.assertIn('id="notebooklm-selection"', WEB_HTML)
        self.assertIn('id="open-notebooklm-import"', WEB_HTML)
        self.assertIn('<div id="notebooklm-import-view" hidden>', WEB_HTML)
        self.assertIn('id="notebooklm-destination"', WEB_HTML)
        self.assertIn('notebookImportButton.hidden=!admin', WEB_JS)
        self.assertEqual(WEB_HTML.count('id="source-import-form"'), 1)
        self.assertIn('<div id="source-import-view" hidden>', WEB_HTML)
        self.assertIn('id="open-source-import"', WEB_HTML)
        self.assertIn('id="history-view" hidden', WEB_HTML)
        self.assertIn('id="outputs-overview-tab" role="tab"', WEB_HTML)
        self.assertIn('id="outputs-overview-panel" role="tabpanel"', WEB_HTML)
        self.assertIn('id="outputs-overview-list"', WEB_HTML)
        self.assertIn("querySelector('#outputs-overview-tab').hidden=false", WEB_JS)
        self.assertIn("document.body.dataset.runtime==='server'){openOutputsOverview()", WEB_JS)
        self.assertIn("projectRequest('/v1/outputs/definitions'", WEB_JS)
        self.assertNotIn("querySelector('#presentations-tab').hidden=true", WEB_JS)
        self.assertIn("projectRequest('/v1/artifacts/history/list'", WEB_JS)
        self.assertIn("projectRequest('/v1/artifacts/history/compare'", WEB_JS)
        self.assertIn('id="artifact-editor-view" hidden', WEB_HTML)
        self.assertIn('id="new-document"', WEB_HTML)
        self.assertIn("projectRequest('/v1/artifacts/editor/save',{operation_id:artifactEditorAttempt.operation_id,document:artifactEditorAttempt.document}", WEB_JS)
        self.assertIn('new:Boolean(artifactEditorItem.new)', WEB_JS)
        self.assertIn('function openMainTodoEditor()', WEB_JS)
        self.assertIn("window.addEventListener('beforeunload'", WEB_JS)
        self.assertIn('id="project-create-preview"', WEB_HTML)
        self.assertIn("projectRequest('/v1/projects/create/preview'", WEB_JS)
        self.assertIn("projectRequest('/v1/projects/create/confirm'", WEB_JS)
        self.assertNotIn("fetch('/v1/projects/create'", WEB_JS)
        self.assertIn("querySelector('#source-import-local-only').disabled=true", WEB_JS)
        self.assertNotIn('web-source-import', WEB_HTML)
        self.assertIn("projectRequest('/v1/workflows/prepare'", WEB_JS)
        self.assertIn('id="autonomy-queue"', WEB_HTML)
        self.assertIn("autonomyRequest('/v1/autonomy/advance'", WEB_JS)
        self.assertEqual(self.request(path='/v1/backend-metrics/status')[0], 200)
        self.assertEqual(self.request(path='/v1/user-profile', body='{"action":"load"}')[0], 503)

    def test_application_access_requires_preview_and_persists_node_local_policy(self):
        code, data, _ = self.request(path='/v1/application-access',
                                     body=json.dumps({'action': 'status'}))
        self.assertEqual(200, code, data)
        status = json.loads(data)
        self.assertEqual({'mode': 'private-network', 'allowed': []}, status['settings'])
        self.assertEqual('192.168.100.0/24', status['private_network'])
        self.assertEqual('127.0.0.1', status['client_address'])

        settings = {'mode': 'allowlist', 'allowed': ['203.0.113.10', '10.20.0.0/16']}
        code, data, _ = self.request(path='/v1/application-access', body=json.dumps({
            'action': 'preview', 'settings': settings}))
        self.assertEqual(200, code, data)
        plan = json.loads(data)['plan']
        self.assertTrue(plan['current_client_allowed'])  # loopback is never locked out
        self.assertEqual(settings, plan['settings'])
        code, data, _ = self.request(path='/v1/application-access', body=json.dumps({
            'action': 'confirm', 'plan': plan, 'confirmed_disconnect': False}))
        self.assertEqual(200, code, data)
        self.assertEqual(settings, json.loads(data)['settings'])
        self.assertEqual(settings, self.server.application_access.load())

        code, data, _ = self.request(path='/v1/application-access', body=json.dumps({
            'action': 'preview', 'settings': {'mode': 'allowlist', 'allowed': ['host.local']}}))
        self.assertEqual(422, code)
        self.assertIn('IP', json.loads(data)['error'])

    def test_google_drive_https_configuration_picker_callback_and_privacy(self):
        _, data, _ = self.create_project('Drive HTTPS')
        project = json.loads(data)['id']; view = Projects(self.root/'node.json').open(project)
        code, data, _ = self.request(path='/v1/google-drive/status')
        self.assertEqual(code, 200); self.assertFalse(json.loads(data)['configured'])
        code, data, _ = self.request(path='/v1/google-drive/configure', body=json.dumps({
            'client_id':'client-id-1234567890.apps.googleusercontent.com',
            'client_secret':'client-secret-value'}))
        self.assertEqual(code, 200, data); self.assertNotIn(b'client-secret-value', data)
        authorize = {'project_id':project, 'expected_head':view['commit_id'], 'privacy':'project'}
        code, data, _ = self.request(path='/v1/google-drive/authorize', body=json.dumps(authorize))
        self.assertEqual(code, 200, data); started = json.loads(data)
        parsed = urlsplit(started['authorization_url']); query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, 'accounts.google.com')
        self.assertEqual(query['scope'], ['https://www.googleapis.com/auth/drive.file'])
        self.assertEqual(query['redirect_uri'], [
            'https://' + self.authority + '/oauth/google-drive/callback'])
        authorize['privacy'] = 'local-only'
        self.assertEqual(self.request(path='/v1/google-drive/authorize',
                                     body=json.dumps(authorize))[0], 403)
        callback = '/oauth/google-drive/callback?' + urlencode({
            'state':query['state'][0], 'code':'code', 'picked_file_ids':'file-id',
            'iss':'https://accounts.google.com',
            'scope':'https://www.googleapis.com/auth/drive.file'})
        with patch.object(self.server.google_drive_import, 'callback',
                          return_value={'status':'selected'}) as called:
            code, data, headers = self.request('GET', callback)
            self.assertEqual(code, 200); self.assertIn('Vraťte se'.encode(), data)
            self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
            called.assert_called_once()

    def test_inherited_feature_routes_have_complete_web_runtime_wiring(self):
        self.assertEqual(self.create_project('Runtime wiring')[0], 200)
        shared = self.server.chat_service.state_dir
        services = (
            ('summary', self.server.summary_service),
            ('extraction', self.server.extraction_service),
            ('metadata-suggestions', self.server.metadata_suggestion_service),
        )
        for name, service in services:
            self.assertEqual(service.state_dir, shared)
            self.assertEqual(service.chat_state_dir, shared)
            code, data, _ = self.request(path=f'/v1/{name}/status', body='{}')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(data)['tasks'], [])
            for action in ('preview', 'publish'):
                with self.subTest(service=name, action=action), patch.object(
                        service, action, return_value={'service': name, 'action': action}):
                    code, data, _ = self.request(
                        path=f'/v1/{name}/{action}', body='{}')
                    self.assertEqual(code, 200)
                    self.assertEqual(json.loads(data), {'service': name, 'action': action})

    def test_mobile_layout_has_accessible_drawer_and_bounded_priority_flows(self):
        self.assertIn('id="mobile-sidebar-toggle" type="button" aria-controls="workspace-sidebar"', WEB_HTML)
        self.assertIn('id="mobile-sidebar-backdrop" type="button" aria-label="Zavřít navigaci"', WEB_HTML)
        self.assertIn('id="workspace-sidebar" aria-label="Navigace pracovního prostoru"', WEB_HTML)
        self.assertIn('id="sidebar-layout-toggle" type="button" aria-pressed="false"', WEB_HTML)
        self.assertNotIn('Na tomto uzlu', WEB_HTML)
        self.assertNotIn('Zkušební verze', WEB_HTML)
        self.assertIn("window.matchMedia('(max-width:640px)')", WEB_JS)
        self.assertIn("workspaceSidebar.inert=mobileViewport.matches&&!open", WEB_JS)
        self.assertIn("event.key!=='Escape'", WEB_JS)
        self.assertIn("document.body.classList.contains('mobile-sidebar-open')", WEB_JS)
        self.assertIn("const visible=mainTabs.filter(item=>!item.hidden)", WEB_JS)
        self.assertIn("const visible=sidebarTabs.filter(item=>!item.hidden&&!item.disabled)", WEB_JS)
        self.assertIn("#open-notebooklm-import,#sidebar-create-project,#sidebar-register-project,#resource-monitor-open", WEB_JS)
        self.assertIn(".sidebar-list-main,.sidebar-item-menu-items button,#chat-new-thread')){closeMobileSidebar();closeCompactSidebarMenu();}",
                      WEB_JS)
        self.assertIn('id="chats-tab"', WEB_HTML)
        self.assertIn("querySelector('#outputs-overview-tab').hidden=false", WEB_JS)
        self.assertIn('.outputs-overview-grid{display:grid', WEB_CSS)
        self.assertIn('.presentation-editor-workspace,.outputs-overview-grid{grid-template-columns:1fr}', WEB_CSS)
        self.assertIn('id="sidebar-chat-tree" role="tree"', WEB_HTML)
        self.assertIn('class="sidebar-chat-primary-actions"', WEB_HTML)
        self.assertIn("items.className='sidebar-item-menu-items sidebar-chat-menu-items'", WEB_JS)
        self.assertIn("item.setAttribute('role','menuitem')", WEB_JS)
        self.assertNotIn('id="back-projects"', WEB_HTML)
        self.assertIn('grid-template-columns:51px minmax(0,1fr)', WEB_CSS)
        self.assertIn('.sidebar-tab-icon{width:22px;height:22px', WEB_CSS)
        self.assertIn('#sidebar-tabs button:hover .sidebar-tab-label,#sidebar-tabs button:focus-visible .sidebar-tab-label', WEB_CSS)
        self.assertIn('#resource-monitor-dialog::backdrop', WEB_CSS)
        self.assertIn('aside.sidebar-compact{width:70px', WEB_CSS)
        self.assertNotIn('localStorage', WEB_JS)
        self.assertIn('#sidebar-layout-toggle{display:none}', WEB_CSS)
        self.assertIn('overflow-y:auto;overscroll-behavior:contain', WEB_CSS)
        self.assertIn('@media(max-width:640px)', WEB_CSS)
        self.assertIn('max-width:calc(100vw - 48px)', WEB_CSS)
        self.assertIn('grid-template-columns:minmax(0,1fr)', WEB_CSS)
        self.assertIn('overflow-x:auto;overscroll-behavior-x:contain', WEB_CSS)
        self.assertIn('body[data-runtime="server"]:not(.authenticated)>#mobile-sidebar-toggle', WEB_CSS)
        self.assertIn('#notebooklm-preview{max-height:50vh;max-width:100%', WEB_CSS)

    def test_individual_keys_membership_rotation_and_revocation_over_https(self):
        from uuid import uuid4
        _, data, _ = self.create_project('Restricted')
        project = json.loads(data)['id']
        def admin(request):
            return self.request(path='/v1/administration', body=json.dumps(request))
        code, data, _ = admin({'action':'list'})
        self.assertEqual(code, 200)
        state = json.loads(data)
        code, data, _ = admin({'action':'create-user', 'expected_commit':state['commit_id'], 'name':'Reader', 'node_role':'member'})
        self.assertEqual(code, 200)
        state = json.loads(data); key = state['access_key']; user = state['users'][0]
        headers = {'Authorization':'Bearer '+key}
        self.assertEqual(json.loads(self.request(headers=headers)[1])['projects'], [])
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':project}), headers=headers)[0], 403)
        history_request = {'project_id':project, 'artifact_id':str(uuid4()), 'expected_head':'0'*40}
        self.assertEqual(self.request(path='/v1/artifacts/history/list', body=json.dumps(history_request), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/artifacts/editor/open', body=json.dumps(history_request), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/outputs/definitions', body=json.dumps({
            'project_id':project, 'expected_head':'0'*40}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/administration', body='{"action":"list"}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/chat/test', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/chat/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/atlascloud/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/atlascloud/models', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/atlascloud/remove', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/search/test', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/search/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/model-catalog/import', body='{}',
                                      headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/backend-catalog/reset', body='{}',
                                      headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/model-selection/preferences', body='{}',
                                      headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/tasks/search/preview', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/tasks/search/confirm', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/backend-metrics/status', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/application-access',
                                      body='{"action":"status"}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/media/openai/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/publication-cms/status', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/external/request',
            body=json.dumps({'run_id':str(uuid4())}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/external/send-stream',
            body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/chat/send-stream',
            body=json.dumps({'project_id': project}), headers=headers)[0], 403)
        self.assertEqual(self.create_project('Denied', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/projects/delete/preview', body=json.dumps({
            'project_id': project, 'mode': 'trash'}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/notebooklm/preview',
            body='{"archive_path":"/tmp/denied.tgz","archive_capability":null}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/google-drive/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/google-drive/authorize', body=json.dumps({
            'project_id':project, 'expected_head':'0'*40, 'privacy':'project'}), headers=headers)[0], 403)
        code, data, _ = admin({'action':'update-user', 'expected_commit':state['commit_id'], 'user_id':user['id'],
                              'active':True, 'node_role':'member', 'memberships':{project:'reader'}})
        self.assertEqual(code, 200); state = json.loads(data)
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':project}), headers=headers)[0], 200)
        self.assertEqual(self.request(path='/v1/artifacts/history/list', body=json.dumps(history_request), headers=headers)[0], 409)
        self.assertEqual(self.request(path='/v1/artifacts/editor/open', body=json.dumps(history_request), headers=headers)[0], 409)
        view = Projects(self.root/'node.json').open(project)
        self.assertEqual(self.request(path='/v1/outputs/definitions', body=json.dumps({
            'project_id':project, 'expected_head':view['commit_id']}), headers=headers)[0], 200)
        self.assertEqual(self.request(path='/v1/outputs/definitions', body=json.dumps({
            'project_id':project, 'expected_head':'0'*40}), headers=headers)[0], 409)
        self.assertEqual(self.request(path='/v1/artifacts/editor/save', body=json.dumps({
            'operation_id':str(uuid4()), 'document':{'project_id':project}}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/artifacts/delete/confirm', body=json.dumps({
            'project_id':project}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/media/preview', body=json.dumps({
            'project_id': project}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/workflows/status', body=json.dumps({
            'project_id': project}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/autonomy/status', body=json.dumps({
            'project_id': project}), headers=headers)[0], 403)
        source = request_from_bytes(project, view['commit_id'], 'reader.md', b'denied', 'Denied', '', [], 'project')
        self.assertEqual(self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}), headers=headers)[0], 403)
        code, data, _ = admin({'action':'rotate-key', 'expected_commit':state['commit_id'], 'user_id':user['id']})
        self.assertEqual(code, 200); state=json.loads(data)
        self.assertEqual(self.request(headers=headers)[0],401)
        headers={'Authorization':'Bearer '+state['access_key']}
        self.assertEqual(self.request(headers=headers)[0],200)
        code, _, _ = admin({'action':'update-user', 'expected_commit':state['commit_id'], 'user_id':user['id'],
                           'active':False, 'node_role':'member', 'memberships':{project:'reader'}})
        self.assertEqual(code,200)
        self.assertEqual(self.request(headers=headers)[0],401)

    def test_shared_history_routes_list_and_compare_committed_document(self):
        _, data, _ = self.create_project('History')
        project = json.loads(data)['id']
        artifacts = Artifacts(self.root/'node.json'); view = Projects(self.root/'node.json').open(project)
        artifact = main_todo_id(project)
        first = artifacts.save(dict(project_id=project, artifact_id=artifact,
            base_head=view['commit_id'], title='Tasks', body='- [ ] One\n', new=True), str(uuid4()))['commit_id']
        second = artifacts.save(dict(project_id=project, artifact_id=artifact,
            base_head=first, title='Tasks', body='- [x] One\n', new=False), str(uuid4()))['commit_id']
        request = {'project_id':project, 'artifact_id':artifact, 'expected_head':second}
        code, data, _ = self.request(path='/v1/artifacts/history/list', body=json.dumps(request))
        self.assertEqual(code, 200); rows = json.loads(data)['versions']
        self.assertEqual([row['commit_id'] for row in rows], [second, first])
        request.update(older=first, newer=second)
        code, data, _ = self.request(path='/v1/artifacts/history/compare', body=json.dumps(request))
        self.assertEqual(code, 200); result = json.loads(data)
        self.assertEqual(result['after']['body'], '- [x] One\n')
        self.assertIn('+- [x] One', result['diff'])
        editor_request = {'project_id':project, 'artifact_id':artifact, 'expected_head':second}
        code, data, _ = self.request(path='/v1/artifacts/editor/open', body=json.dumps(editor_request))
        self.assertEqual(code, 200); opened = json.loads(data)
        document = dict(project_id=project, artifact_id=artifact, base_head=second,
            title='Renamed', body='- [x] Edited\n', new=False, filename='renamed.md',
            metadata={'description':'Edited', 'tags':['web']})
        code, data, _ = self.request(path='/v1/artifacts/editor/save', body=json.dumps({
            'operation_id':str(uuid4()), 'document':document}))
        self.assertEqual(code, 200); edited_head = json.loads(data)['commit_id']
        created = str(uuid4())
        code, data, _ = self.request(path='/v1/artifacts/editor/save', body=json.dumps({
            'operation_id':str(uuid4()), 'document':dict(project_id=project,
                artifact_id=created, base_head=edited_head, title='New web document',
                body='# New\n', new=True, filename='new.md', metadata={})}))
        self.assertEqual(code, 200); edited_head = json.loads(data)['commit_id']
        self.assertIn(created, {item['id'] for item in Projects(self.root/'node.json').open(project)['artifacts']})
        code, data, _ = self.request(path='/v1/artifacts/delete/preview', body=json.dumps({
            'project_id':project, 'artifact_id':artifact, 'expected_head':edited_head}))
        self.assertEqual(code, 200); deletion = json.loads(data)
        code, data, _ = self.request(path='/v1/artifacts/delete/confirm', body=json.dumps({
            'project_id':project, 'artifact_id':artifact, 'base_head':edited_head,
            'preview_sha256':deletion['preview_sha256'], 'operation_id':str(uuid4())}))
        self.assertEqual(code, 200)
        self.assertEqual({item['id'] for item in Projects(self.root/'node.json').open(project)['artifacts']},
                         {created})

    def test_shared_conflict_routes_preview_and_publish_two_parent_merge(self):
        _, data, _ = self.create_project('Conflict')
        project = json.loads(data)['id']; node = self.root / 'node.json'
        artifacts = Artifacts(node); initial = Projects(node).open(project)['commit_id']
        artifact = str(uuid4())
        base = artifacts.save(dict(project_id=project, artifact_id=artifact,
            base_head=initial, title='Document', body='base\n', new=True),
            str(uuid4()))['commit_id']
        local = artifacts.save(dict(project_id=project, artifact_id=artifact,
            base_head=base, title='Document', body='local\n', new=False),
            str(uuid4()))['commit_id']
        workspace = Projects(node).workspace(project); git = workspace.git
        content = next(path for path in git.snapshot(base)
                       if path.startswith(f'artifacts/{artifact}/') and path.endswith('.md'))
        git.run('switch', '-c', 'peer', base)
        (workspace.git.root / content).write_text('peer\n')
        peer = git.commit('Peer conflict')
        git.run('switch', 'main'); git.run('read-tree', '--reset', '-u', local)
        peer_id = str(uuid4())
        incoming = (f'refs/federation/incoming/{peer_id}/{uuid4()}/main')
        git.run('update-ref', incoming, peer, '0' * 40)
        actor = {'id': None, 'node_role': 'federation-admin',
                 'memberships': {project: 'project-admin'}}
        state = self.server.administration.request(actor, {'action': 'list'})
        state = self.server.administration.request(actor, {
            'action': 'add-peer-relationship',
            'expected_commit': state['commit_id'],
            'relationship_type': 'p2p', 'sharing_level': 'same-team',
            'node_id': peer_id, 'name': 'Peer',
            'endpoint': 'https://127.0.0.1:8443', 'fingerprint': 'a' * 64})
        self.server.administration.request(actor, {
            'action': 'update-peer', 'expected_commit': state['commit_id'],
            'node_id': peer_id, 'name': 'Peer',
            'endpoint': 'https://127.0.0.1:8443', 'trust': 'approved',
            'sharing_level': 'same-team'})

        request = {'project_id': project, 'expected_head': local}
        code, data, _ = self.request(path='/v1/projects/conflicts/list',
                                     body=json.dumps(request))
        self.assertEqual(code, 200); self.assertEqual(
            json.loads(data)['conflicts'][0]['ref'], incoming)
        request['incoming_ref'] = incoming
        code, data, _ = self.request(path='/v1/projects/conflicts/preview',
                                     body=json.dumps(request))
        self.assertEqual(code, 200); preview = json.loads(data)
        resolutions = []
        for item in preview['files']:
            row = {'path': item['path'], 'choice':
                   'manual' if item['path'] == content else
                   ('ours' if item['conflict'] else 'auto')}
            if row['choice'] == 'manual': row['text'] = 'local\npeer\n'
            resolutions.append(row)
        resolution = {key: preview[key] for key in (
            'project_id', 'expected_head', 'incoming_ref', 'incoming_head',
            'base', 'preview_sha256')} | {'resolutions': resolutions}
        code, data, _ = self.request(path='/v1/projects/conflicts/confirm',
            body=json.dumps({'operation_id': str(uuid4()),
                             'resolution': resolution}))
        self.assertEqual(code, 200); merged = json.loads(data)['commit_id']
        self.assertEqual(git.run('show', '-s', '--format=%P', merged).stdout.split(),
                         [local, peer])
        self.assertEqual(git.snapshot(merged)[content], b'local\npeer\n')

    def test_create_retries_have_one_receipt_and_project(self):
        from uuid import uuid4
        operation=str(uuid4())
        code,data,_=self.request(path='/v1/projects/create/preview',body=json.dumps({
            'title':'Retry','operation_id':operation,'location_capability':None,
            'remember_parent':False}))
        self.assertEqual(code,200);body=json.dumps({'plan':json.loads(data)})
        first=self.request(path='/v1/projects/create/confirm',body=body)
        second=self.request(path='/v1/projects/create/confirm',body=body)
        self.assertEqual(first[0],200);self.assertEqual(second[0],200)
        self.assertEqual(json.loads(first[1]),json.loads(second[1]))
        self.assertEqual(len(json.loads(self.request()[1])['projects']),1)

    def test_admin_previews_plans_and_confirms_server_local_notebooklm_export(self):
        archive = self.notebook_archive()
        code, data, _ = self.request(path='/v1/notebooklm/preview',
                                     body=json.dumps({'archive_path': str(archive),
                                                      'archive_capability': None}))
        self.assertEqual(200, code)
        preview = json.loads(data)
        operation = str(uuid4())
        request = {'archive_path': str(archive), 'archive_capability': None,
                   'selection_digest': preview['notebooks'][0]['selection_digest'],
                   'privacy': 'confidential', 'operation_id': operation,
                   'target_capability': None}
        code, data, _ = self.request(path='/v1/notebooklm/plan', body=json.dumps(request))
        self.assertEqual(200, code)
        plan = json.loads(data)
        self.assertEqual('confidential', plan['privacy'])
        self.assertIn(str(self.root / 'projects'), plan['target_root'])
        body = json.dumps({'archive_path': str(archive), 'archive_capability': None,
                           'plan': plan})
        first = self.request(path='/v1/notebooklm/confirm', body=body)
        second = self.request(path='/v1/notebooklm/confirm', body=body)
        self.assertEqual(200, first[0]); self.assertEqual(first, second)
        receipt = json.loads(first[1])
        self.assertEqual(plan['project_id'], receipt['id'])
        self.assertEqual(6, len(Projects(self.root / 'node.json').open(receipt['id'])['artifacts']))

    def test_web_notebooklm_api_rejects_desktop_capabilities_and_local_only(self):
        archive = self.notebook_archive()
        self.assertEqual(422, self.request(path='/v1/notebooklm/preview', body=json.dumps({
            'archive_path': None, 'archive_capability': str(uuid4())}))[0])
        code, data, _ = self.request(path='/v1/notebooklm/preview', body=json.dumps({
            'archive_path': str(archive), 'archive_capability': None}))
        self.assertEqual(200, code)
        preview = json.loads(data)
        request = {'archive_path': str(archive), 'archive_capability': None,
            'selection_digest': preview['notebooks'][0]['selection_digest'],
            'privacy': 'local-only', 'operation_id': str(uuid4()),
            'target_capability': None}
        self.assertEqual(422, self.request(path='/v1/notebooklm/plan',
                                           body=json.dumps(request))[0])

    def test_web_import_preserves_bytes_and_retries_one_operation(self):
        from uuid import uuid4
        _, data, _ = self.create_project('Web import')
        project = json.loads(data)
        raw = b'# Evidence\n' + b'x' * 70000
        source = request_from_bytes(project['id'], project['commit_id'], 'evidence.md', raw,
                                    'Evidence', '', ['web'], 'project')
        body = json.dumps({'operation_id': str(uuid4()), 'source': source})
        first = self.request(path='/v1/sources/import', body=body)
        second = self.request(path='/v1/sources/import', body=body)
        self.assertEqual(first[0], 200); self.assertEqual(second[0], 200)
        self.assertEqual(json.loads(first[1]), json.loads(second[1]))
        opened = Sources(self.root/'node.json').open(project['id'])
        self.assertEqual(len(opened['sources']), 1)
        project_root = Path(parse_node(read_config(self.root/'node.json'),
                                       location=self.root/'node.json')['projects'][0]['root'])
        imported = json.loads((project_root/'artifacts'/source['artifact_id']/'metadata.json').read_text())
        self.assertEqual(imported['import']['importer']['name'], 'workspace-web-import')
        self.assertEqual((project_root/'artifacts'/source['artifact_id']/'evidence.md').read_bytes(), raw)

    def test_web_import_rejects_local_only(self):
        from uuid import uuid4
        _, data, _ = self.create_project('Privacy')
        project = json.loads(data)
        source = request_from_bytes(project['id'], project['commit_id'], 'private.md', b'private',
                                    'Private', '', [], 'local-only')
        code, _, _ = self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}))
        self.assertEqual(code, 422)
        self.assertEqual(Sources(self.root/'node.json').open(project['id'])['sources'], [])

    def test_router_entry_redirects_to_live_https_and_rejects_bad_certificate(self):
        import ipaddress
        from http.server import HTTPServer
        from unittest.mock import patch, Mock
        from scripts.router_entry import EntryHandler
        entry = HTTPServer(('127.0.0.1', 0), EntryHandler)
        entry.target = ('workspace-m0', ipaddress.ip_network('127.0.0.0/8'),
                        self.server.server_port, str(self.cert))
        thread = threading.Thread(target=entry.serve_forever); thread.start()
        try:
            def info(args, **kwargs):
                return Mock(stdout='RUNNING' if args[-1]=='-sH' else '127.0.0.1')
            with patch('scripts.router_entry.subprocess.run', side_effect=info):
                for ca, expected in [(str(self.cert),302), (str(self.root/'missing-ca'),503)]:
                    entry.target = (*entry.target[:3], ca)
                    conn = http.client.HTTPConnection(*entry.server_address, timeout=10)
                    conn.request('GET','/federated-workspace/')
                    response = conn.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertEqual(response.getheader('Cache-Control'),'no-store')
                    if expected == 302:
                        self.assertEqual(response.getheader('Location'),'https://'+self.authority+'/')
                    else:
                        self.assertIsNone(response.getheader('Location'))
                    response.read(); conn.close()
        finally:
            entry.shutdown(); thread.join(); entry.server_close()

    def test_secret_permissions_symlink_and_invalid_keys(self):
        self.token_file.chmod(0o644)
        with self.assertRaises(ValueError): secret(self.token_file)
        self.token_file.chmod(0o600)
        link = self.root/'link'; link.symlink_to(self.token_file)
        with self.assertRaises(ValueError): secret(link)
        self.token_file.write_text('short')
        with self.assertRaises(ValueError): secret(self.token_file)

    def test_bad_tls_client_does_not_prevent_following_request(self):
        import socket
        with socket.create_connection(('127.0.0.1',self.server.server_port)) as sock:
            sock.sendall(b'GET / HTTP/1.0\r\n\r\n')
        self.assertEqual(self.request()[0],200)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_shared_editor_creates_document_todo_and_guards_draft(self):
        _, data, _ = self.create_project('Shared editor')
        project = json.loads(data)
        import sys
        code = r"""
import json, os, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
app=QApplication([]);view=QWebEngineView();phase=0;ticks=0
view.page().certificateError.connect(lambda error:error.acceptCertificate())
key=os.environ['WORKSPACE_SMOKE_KEY']
def run(script): view.page().runJavaScript(script)
def finish(message,code=1): print(message);app.exit(code)
def result(value):
 global phase
 if isinstance(value,str) and value.startswith('FAIL:'): finish(value);return
 if value!='ready': return
 if phase==0:
  phase=1;run("document.querySelector('#access-key').value="+json.dumps(key)+";document.querySelector('#login-form').requestSubmit();")
 elif phase==1:
  phase=2;run("document.querySelector('.project-card').click();")
 elif phase==2:
  phase=3;run("document.querySelector('#new-document').click();artifactEditorForm.elements.title.value='Sdílený dokument';artifactEditorForm.elements.body.value='# Obsah\\n';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));artifactEditorForm.requestSubmit();")
 elif phase==3:
  phase=4;run("document.querySelector('#todo-tab').click();document.querySelector('#create-main-todo').click();artifactEditorForm.elements.body.value='# Hlavní seznam úkolů\\n\\n- [ ] Ověřit editor\\n';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));artifactEditorForm.requestSubmit();")
 elif phase==4:
  phase=5;run("document.querySelector('#new-document').click();artifactEditorForm.elements.title.value='Rozepsáno';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));window.confirm=()=>false;document.querySelector('#artifact-editor-close').click();")
 elif phase==5:
  phase=6;run("window.confirm=()=>true;document.querySelector('#artifact-editor-close').click();")
 elif phase==6: finish('shared editor smoke: document, TODO and draft guard OK',0)
def poll():
 global ticks
 ticks+=1
 if ticks>350: finish('shared editor smoke timeout at phase '+str(phase));return
 checks={
 0:"document.querySelector('#login-form')&&!document.body.classList.contains('authenticated')?'ready':'waiting'",
 1:"document.body.classList.contains('authenticated')&&document.querySelector('.project-card')?'ready':'waiting'",
 2:"!document.querySelector('#project-view').hidden?'ready':'waiting'",
 3:"(()=>{if(currentArtifacts.some(item=>item.title==='Sdílený dokument'))return'ready';const s=document.querySelector('#artifact-editor-status').textContent;return s&&s!=='Ukládám dokument…'?'FAIL: '+s:'waiting'})()",
 4:"document.querySelector('#todo-tree').textContent.includes('Ověřit editor')?'ready':'waiting'",
 5:"!artifactEditorView.hidden&&artifactEditorForm.elements.title.value==='Rozepsáno'?'ready':'FAIL: dirty draft was discarded'",
 6:"artifactEditorView.hidden?'ready':'waiting'"}
 view.page().runJavaScript(checks[phase],result)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
view.load(QUrl(os.environ['WORKSPACE_SMOKE_URL']));view.show();sys.exit(app.exec())
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(
            os.environ, WORKSPACE_SMOKE_KEY=self.token,
            WORKSPACE_SMOKE_URL='https://'+self.authority+'/'),
            capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('shared editor smoke: document, TODO and draft guard OK', result.stdout)
        opened = Projects(self.root/'node.json').open(project['id'])
        self.assertEqual({item['title'] for item in opened['artifacts']},
                         {'Sdílený dokument', 'Hlavní seznam úkolů'})
        self.assertEqual(opened['main_todo']['items'][0]['title'], 'Ověřit editor')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_browser_login_catalog_and_logout(self):
        import sys
        # Accept only the ephemeral test certificate, never a production TLS policy.
        code = r"""
import json, os, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
app=QApplication([]); view=QWebEngineView(); view.resize(1000,750)
view.page().certificateError.connect(lambda error:error.acceptCertificate())
phase=0; ticks=0
key=os.environ['WORKSPACE_SMOKE_KEY']
def result(value):
 global phase
 if phase==0 and value=='ready':
  phase=1
  view.page().runJavaScript("document.querySelector('#access-key').value="+json.dumps(key)+";document.querySelector('#login-form').requestSubmit();")
 elif phase==1 and value=='loaded':
  phase=2
  view.page().runJavaScript("document.querySelector('#logout').click();")
 elif phase==2 and value=='ready':
  print('web smoke: login, catalog and logout OK');app.exit(0)
def poll():
 global ticks
 ticks+=1
 if ticks>150: app.exit(1);return
 view.page().runJavaScript("document.querySelector('#login-form') ? (document.body.classList.contains('authenticated') ? (document.querySelector('#project-status').textContent==='Zatím nemáte žádný projekt.' && !document.querySelector('#backend-metrics-indicator').hidden?'loaded':'waiting') : 'ready') : 'waiting'",result)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
view.load(QUrl(os.environ['WORKSPACE_SMOKE_URL']));view.show()
sys.exit(app.exec())
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ,
            WORKSPACE_SMOKE_KEY=self.token, WORKSPACE_SMOKE_URL='https://'+self.authority+'/'),
            capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('web smoke: login, catalog and logout OK', result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_mobile_browser_import_catalog_preview_and_keyboard_drawer(self):
        title = 'Český projekt s velmi dlouhým názvem ' + 'bez-mezer-' * 14
        _, data, _ = self.create_project(title)
        project = json.loads(data)
        source = request_from_bytes(project['id'], project['commit_id'], 'mobile.md',
                                    b'# Mobilni nahled\nBezpecny text.', 'Mobilní podklad',
                                    'Dlouhý popis pro telefon', ['mobile'], 'project')
        code, _, _ = self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}))
        self.assertEqual(code, 200)
        archive = self.notebook_archive()
        import sys
        code = r"""
import json, os, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
app=QApplication([]);view=QWebEngineView();view.resize(390,844)
view.page().certificateError.connect(lambda error:error.acceptCertificate())
phase=0;ticks=0;key=os.environ['WORKSPACE_SMOKE_KEY'];archive=os.environ['WORKSPACE_NOTEBOOK_ARCHIVE']
def run(script): view.page().runJavaScript(script)
def finish(message,code=1): print(message);app.exit(code)
def result(value):
 global phase
 if isinstance(value,str) and value.startswith('FAIL:'): finish(value);return
 if value!='ready': return
 if phase==0:
  phase=1;run("document.querySelector('#access-key').value="+json.dumps(key)+";document.querySelector('#login-form').requestSubmit();")
 elif phase==1:
  phase=2;run("document.querySelector('#open-notebooklm-import').click();document.querySelector('#notebooklm-archive').value="+json.dumps(archive)+";document.querySelector('#notebooklm-load').click();")
 elif phase==2:
  phase=3;run("document.querySelector('#notebooklm-plan').click();")
 elif phase==3:
  phase=4;run("const c=document.querySelector('#notebooklm-confirm');c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('.project-card').click();")
 elif phase==4:
  phase=5;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==5:
  phase=6;run("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));")
 elif phase==6:
  phase=7;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==7:
  phase=8;run("document.querySelector('#sidebar-artifact-list button').click();")
 elif phase==8:
  phase=9;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==9:
  phase=10;run("document.querySelector('#logout').click();")
 elif phase==10: finish('mobile web smoke: import plan, catalog, keyboard drawer and preview OK',0)
def poll():
 global ticks
 ticks+=1
 if ticks>450: finish('mobile web smoke timeout at phase '+str(phase));return
 checks={
 0:"document.querySelector('#login-form')&&!document.body.classList.contains('authenticated')?'ready':'waiting'",
 1:"(()=>{if(!document.body.classList.contains('authenticated')||document.querySelectorAll('.project-card').length!==1)return'waiting';if(innerWidth!==390)return'FAIL: wrong viewport '+innerWidth;if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: home overflow';const b=document.querySelector('#mobile-sidebar-toggle');if(getComputedStyle(b).display==='none'||parseFloat(getComputedStyle(b).minHeight)<44)return'FAIL: touch target';return'ready'})()",
 2:"!document.querySelector('#notebooklm-import-view').hidden&&document.querySelector('#notebooklm-selection')&&!document.querySelector('#notebooklm-selection').disabled?'ready':'waiting'",
 3:"(()=>{const row=document.querySelector('#notebooklm-confirm-row'),destination=document.querySelector('#notebooklm-destination');if(row.hidden)return'waiting';if(!destination.textContent.startsWith('/'))return'FAIL: target path missing';if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: import overflow';return'ready'})()",
 4:"(()=>{if(document.querySelector('#project-view').hidden||!document.querySelector('#sidebar-artifact-list button'))return'waiting';const form=document.querySelector('#chat-composer'),action=document.querySelector('#task-action'),submit=document.querySelector('#chat-submit'),control=document.querySelector('label[for=chat-mode]'),label=control.querySelector('span'),currentPrompt=document.querySelector('#task-source-current-prompt'),output=document.querySelector('#task-output-kind');if(form.hidden)return'FAIL: prompt hidden';if(document.querySelector('#prompt-widget-toggle')||document.querySelector('#task-search-editor'))return'FAIL: obsolete prompt control';renderProjectHistory({entries:Array.from({length:8},(_,i)=>({subject:'Změna '+i,date:'2026-10-21T00:00:00Z',author:'Test',commit_id:String(i).padStart(8,'0')})),truncated:false});renderProjectOverview({status:'ready',items:Array.from({length:8},(_,i)=>({title:'Úkol '+i,checked:false,depth:0})),completed:0,total:8,truncated:false});const history=document.querySelector('#project-overview-history-list'),tasks=document.querySelector('#project-overview-task-list'),historyCard=document.querySelector('.project-overview-history'),taskCard=document.querySelector('.project-overview-tasks');if(history.children.length!==5||tasks.children.length!==5)return'FAIL: mobile overview limit';if(getComputedStyle(history).overflowY!=='visible'||getComputedStyle(tasks).overflowY!=='visible'||getComputedStyle(historyCard).overflowY!=='visible'||getComputedStyle(taskCard).overflowY!=='visible')return'FAIL: nested mobile overview scroll';action.value='search';action.dispatchEvent(new Event('change',{bubbles:true}));if(currentPrompt.hidden||output.value!=='conversation'||!output.disabled)return'FAIL: search contract';if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: prompt overflow';const formRect=form.getBoundingClientRect(),submitRect=submit.getBoundingClientRect(),controlRect=control.getBoundingClientRect(),labelRect=label.getBoundingClientRect();if(controlRect.height<44||labelRect.top<controlRect.top||labelRect.bottom>controlRect.bottom)return'FAIL: embedded label geometry';if(submitRect.left<formRect.left||submitRect.right>formRect.right+1||submitRect.width<44||submitRect.height<44)return'FAIL: prompt submit geometry '+JSON.stringify({form:[formRect.left,formRect.right],submit:[submitRect.left,submitRect.right,submitRect.width,submitRect.height]});action.value='answer';action.dispatchEvent(new Event('change',{bubbles:true}));return'ready'})()",
 5:"(()=>{const b=document.querySelector('#mobile-sidebar-toggle'),s=document.querySelector('#workspace-sidebar');if(b.getAttribute('aria-expanded')!=='true')return'waiting';if(s.inert)return'FAIL: open drawer inert';return'ready'})()",
 6:"(()=>{const b=document.querySelector('#mobile-sidebar-toggle'),s=document.querySelector('#workspace-sidebar');if(b.getAttribute('aria-expanded')!=='false')return'waiting';if(!s.inert)return'FAIL: closed drawer focusable';if(document.activeElement!==b)return'FAIL: drawer focus not restored';return'ready'})()",
 7:"document.querySelector('#mobile-sidebar-toggle').getAttribute('aria-expanded')==='true'?'ready':'waiting'",
 8:"(()=>{if(document.querySelector('#preview-title').textContent!=='Mobilní podklad')return'waiting';const currentFile=document.querySelector('#task-source-current-file');if(currentFile.hidden||!currentFile.textContent.includes('Mobilní podklad'))return'FAIL: current file input missing';if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: preview overflow';const s=document.querySelector('#workspace-sidebar');if(!s.inert)return'FAIL: selected drawer focusable';return'ready'})()",
 9:"document.querySelector('#mobile-sidebar-toggle').getAttribute('aria-expanded')==='true'?'ready':'waiting'",
 10:"document.querySelector('#login-form')&&!document.body.classList.contains('authenticated')?'ready':'waiting'"}
 view.page().runJavaScript(checks[phase],result)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
view.load(QUrl(os.environ['WORKSPACE_SMOKE_URL']));view.show();sys.exit(app.exec())
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(
            os.environ, WORKSPACE_SMOKE_KEY=self.token,
            WORKSPACE_SMOKE_URL='https://'+self.authority+'/',
            WORKSPACE_NOTEBOOK_ARCHIVE=str(archive)), capture_output=True, text=True,
            timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('mobile web smoke: import plan, catalog, keyboard drawer and preview OK', result.stdout)


class NetworkPrivacyTests(unittest.TestCase):
    def test_local_only_catalog_open_and_preview_with_real_git(self):
        fixture = test_projects.ProjectTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        projects = Projects(fixture.node_path, network=True)
        self.assertTrue(projects.catalog()[0]['available'])
        self.assertEqual(projects.open(ENTITY)['id'],ENTITY)
        meta = metadata(); meta['privacy']='local-only'
        (fixture.gits[0].root/'artifacts'/ENTITY/'note.md').write_bytes(markdown(meta))
        head = fixture.gits[0].commit('Local only')
        self.assertNotIn(ENTITY, str(projects.catalog()))
        self.assertNotIn(ENTITY, str(projects.list()))
        with self.assertRaises(ValueError): projects.open(ENTITY)
        with self.assertRaises(ValueError): projects.preview(ENTITY,ENTITY,head)
        # The native/local boundary retains access.
        self.assertEqual(fixture.projects.open(ENTITY)['id'],ENTITY)

class BootstrapTests(unittest.TestCase):
    def test_repeated_initialization_preserves_identity_key_and_registration(self):
        from spikes.web_bootstrap import initialize
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            initialize(root)
            before={p.name:p.read_bytes() for p in root.iterdir()}
            initialize(root)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            for p in root.iterdir(): self.assertEqual(p.stat().st_mode & 0o777,0o600)
            (root/'access-key').write_text('corrupt')
            with self.assertRaises(ValueError): initialize(root)
            self.assertEqual((root/'access-key').read_text(),'corrupt')
