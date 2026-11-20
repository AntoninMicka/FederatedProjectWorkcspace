# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Web variant login in a real browser over TLS (AUDIT-B7-T1).

Regression: AUDIT-B6-T1 removed ``#presentation-editor`` while the web
bootstrap still hid it, so the bootstrap threw before the login handler was
registered. The form then submitted natively, the server answered "request
rejected" and the access key ended up in the URL.
"""
import re
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from spikes.project_creation import ProjectCreation
from tests.browser_harness import BrowserPage, require_browser


def missing_bootstrap_elements():
    """IDs that a runtime bootstrap touches but the shared page does not contain."""
    from spikes.desktop_management import DESKTOP_BOOTSTRAP
    from spikes.desktop_ui import HTML, JS
    from spikes.web_server import WEB_JS
    ids = set(re.findall(r'id="([\w-]+)"', HTML))
    result = {}
    for name, script in (('web', WEB_JS[:len(WEB_JS) - len(JS)]), ('desktop', DESKTOP_BOOTSTRAP)):
        refs = set(re.findall(r"querySelector\('#([\w-]+)'\)", script))
        refs |= set(re.findall(r"getElementById\('([\w-]+)'\)", script))
        for listed in re.findall(r"for\(const id of \[([^\]]*)\]", script):
            refs |= set(re.findall(r"'([\w-]+)'", listed))
        result[name] = sorted(refs - ids)
    return result


class BootstrapContractTests(unittest.TestCase):
    def test_bootstraps_only_touch_existing_elements(self):
        self.assertEqual(missing_bootstrap_elements(), {'web': [], 'desktop': []})

    def test_web_page_forbids_native_form_submission(self):
        # A broken script must never send the access key as a form navigation.
        source = Path('spikes/web_server.py').read_text()
        self.assertIn("form-action 'none'", source)
        self.assertNotIn("form-action 'self'", source)


@require_browser
class WebLoginTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='fpw-web-')
        self.addCleanup(directory.cleanup)
        self.node = Path(directory.name) / 'node.json'
        ProjectCreation(self.node).create('Webový projekt', str(self.node.parent / 'project'), str(uuid4()))
        self.page = BrowserPage(node=self.node, web=True)
        self.page.__enter__()
        self.addCleanup(self.page.__exit__, None, None, None)
        self.page.wait_idle()

    def login(self, key):
        page = self.page
        page.fill('#access-key', key)
        page.evaluate("document.querySelector('#login-form').requestSubmit()")
        page.wait_js("document.body.classList.contains('authenticated')||"
                     "document.querySelector('#login-status').textContent", 'login result')
        page.wait_idle()

    def test_access_key_logs_in_and_loads_projects(self):
        page = self.page
        self.assertEqual(page.exceptions, [], 'The web bootstrap must run without errors')
        self.assertEqual(page.evaluate('document.body.dataset.runtime'), 'server')
        self.login(page.access_key)
        self.assertTrue(page.evaluate("document.body.classList.contains('authenticated')"))
        sent = {item['path']: item for item in page.api.requests if 'path' in item}
        for path in ('/v1/projects', '/v1/session'):
            self.assertTrue(sent[path]['authenticated'], path)
            self.assertEqual(page.status(sent[path]), 200, path)
        self.assertIn('Webový projekt', page.text('#sidebar-project-list'))
        self.assertFalse(page.evaluate("document.querySelector('#federation-tab').hidden"),
                         'The administrator key unlocks node administration')
        self.assertEqual([item for item in page.api.requests if 'navigation' in item], [])
        self.assertEqual(page.evaluate('location.search'), '')

    def test_wrong_key_is_refused_without_leaving_the_page(self):
        page = self.page
        self.login('x' * 43)
        self.assertEqual(page.text('#login-status'), 'Přihlášení se nezdařilo.')
        self.assertFalse(page.evaluate("document.body.classList.contains('authenticated')"))
        self.assertEqual(page.evaluate('location.search'), '', 'The key never goes into the URL')
        self.assertEqual([item for item in page.api.requests if 'navigation' in item], [])
        self.assertEqual(page.exceptions, [])
