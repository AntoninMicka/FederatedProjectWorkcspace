# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Desktop assets/policy are mandatory; a real Qt smoke is explicitly opt-in."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

from spikes.desktop import request_policy
from spikes.desktop_ui import DesktopHandler, JS
from spikes.local_api import running_api
from tests import test_local_api


class DesktopTests(unittest.TestCase):
    def test_prompt_switches_to_chat_only_when_submitted(self):
        input_handler = JS.split("draft.addEventListener('input',()=>{", 1)[1].split('});', 1)[0]
        submit_handler = JS.split("document.querySelector('#chat-composer').addEventListener('submit',async event=>{", 1)[1].split('});', 1)[0]
        self.assertNotIn('selectMainTab', input_handler)
        self.assertIn('selectMainTab(mainTabs[1])', submit_handler)

    def test_chat_ui_uses_authenticated_api_and_explicit_message_selection(self):
        self.assertIn("projectRequest('/v1/chat/status',{})", JS)
        self.assertIn("projectRequest('/v1/chat/configure',binding)", JS)
        self.assertIn("projectRequest('/v1/chat/send',pendingChatRequest,210000)", JS)
        self.assertIn("selected_message_ids:(activeThread?.messages || []).map", JS)
        self.assertIn("activeThread=null;pendingChatRequest=null", JS)
        self.assertIn("querySelector('#chat-new-thread').addEventListener", JS)
        self.assertIn("pendingChatRequest=null;renderChat(null)", JS)
        self.assertIn("projectRequest('/v1/chat/assign'", JS)
        self.assertIn("projectRequest('/v1/chat/snapshot'", JS)
        self.assertIn("projectRequest('/v1/chat/output'", JS)

    def test_chat_progress_stays_with_prompt(self):
        from spikes.desktop_ui import HTML
        composer = HTML.split('<form id="chat-composer">', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="chat-operation-status"', composer)
        self.assertIn("chatOperationStatus.textContent='Odesílám…'", JS)
        self.assertIn("chatOperationStatus.textContent='Model přemýšlí…'", JS)

    def test_summary_ui_uses_explicit_selection_preview_and_confirmation(self):
        from spikes.desktop_ui import HTML
        self.assertIn('id="summary-tab"', HTML)
        self.assertIn('id="summary-artifact-list"', HTML)
        self.assertIn("projectRequest('/v1/summary/preview',pendingSummaryRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/summary/publish',pendingSummaryPublish)", JS)
        self.assertIn("selection={kind:'artifacts',artifact_ids:ids}", JS)
        self.assertIn("selection={kind:'messages'", JS)
        self.assertIn("item.textContent=heading?heading[2]:line", JS)
        self.assertNotIn('summaryPreviewElement.innerHTML', JS)

    def test_credentials_are_restricted_to_exact_api_and_initiator(self):
        origin = 'http://127.0.0.1:1234'
        self.assertEqual(request_policy(origin + '/', '', 'GET', origin), 'allow')
        self.assertEqual(request_policy(origin + '/app.js', origin, 'GET', origin), 'allow')
        self.assertEqual(request_policy(origin + '/v1/counter', origin + '/', 'POST', origin), 'authenticate')
        for url, initiator, method in [
            (origin + '/v1/counter', '', 'POST'),
            (origin + '/v1/counter', 'http://evil.example', 'POST'),
            (origin + '/v1/counter', origin, 'GET'),
            (origin + '/v1/counter?x=1', origin, 'POST'),
            ('http://127.0.0.1:1235/v1/counter', origin, 'POST'),
            ('http://user@127.0.0.1:1234/v1/counter', origin, 'POST'),
            ('https://evil.example/', origin, 'GET'),
            (origin + '/#create-main-todo', origin, 'GET'),
            (origin + '/native/main-todo', origin, 'POST'),
            ('file:///etc/passwd', origin, 'GET'),
            ('data:text/html,test', origin, 'GET'),
        ]:
            with self.subTest(url=url, initiator=initiator):
                self.assertEqual(request_policy(url, initiator, method, origin), 'block')

    def test_assets_do_not_bootstrap_token_and_api_still_requires_auth(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            for path in ('/', '/app.js', '/app.css'):
                response = driver.request(server, method='GET', path=path, headers={'Authorization': None})
                self.assertTrue(response.startswith(b'HTTP/1.0 200'))
                self.assertIn(b"frame-ancestors 'none'", response)
                self.assertNotIn(server.token.encode(), response)
                self.assertNotIn(b'Access-Control-Allow-Origin', response)
            driver.rejected(server, headers={'Authorization': None})
            driver.rejected(server, method='GET', path='/', headers={'Host': 'evil.example'})
            for path in ('/../requirements.txt', '/?token=x', '/favicon.ico'):
                driver.rejected(server, method='GET', path=path)
            endpoint = server.server_address
        with self.assertRaises(OSError):
            socket.create_connection(endpoint, timeout=1)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Set M0_DESKTOP_TEST=1 for real Qt/WebEngine smoke')
    def test_real_webengine_click_close_and_restart(self):
        for _ in range(2):
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke'],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                    text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('authenticated fetch, value=1', result.stdout)
            self.assertIn('backend stopped', result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_renderer_crash_exits_with_failure(self):
        result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke', '--smoke-crash'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=25)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn('backend stopped', result.stdout)
