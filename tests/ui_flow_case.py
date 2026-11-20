# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared set-up of behavioural UI flow tests (AUDIT-B7-T1).

Each test gets a fresh node with one project, loopback fakes of Ollama and
SearXNG and a headless page on the real desktop UI and backend.
"""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from spikes.chat_service import ChatService
from spikes.project_creation import ProjectCreation
from tests.browser_harness import BrowserPage, FakeApi, require_browser
from tests.fake_providers import FakeOllama, FakeSearXNG

__all__ = ['UiFlowCase', 'require_browser', 'FakeApi']


def final_evaluation(answer='Měď stojí 9 USD.', **changes):
    value = {'schema_version': 1, 'assessment': 'final', 'answer': answer, 'rationale': 'r',
             'used_source_ids': [], 'limitations': [], 'follow_up_queries': []}
    value.update(changes)
    return value


def search_request(query='cena mědi LME', purpose='Zjistit cenu'):
    return {'schema_version': 1, 'kind': 'web-search-request', 'purpose': purpose, 'query': query}


class UiFlowCase(unittest.TestCase):
    """``self.start(...)`` opens the page; the project is already registered."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='fpw-ui-')))
        self.node = directory / 'node.json'
        self.project_id = ProjectCreation(self.node).create(
            'Projekt v prohlížeči', str(directory / 'project'), str(uuid4()))['id']

    def start(self, *, answers=(), results=(), api=None, configure_ollama=True,
              configure_search=True):
        self.ollama = self.stack.enter_context(FakeOllama(answers=answers))
        self.searx = self.stack.enter_context(FakeSearXNG(results=results))

        def chat_service(node, projects):
            service = ChatService(node, projects)
            if configure_ollama:
                service.configure(dict(schema_version=1, binding_id=str(uuid4()), revision='one',
                    adapter='ollama', boundary='same-node', endpoint=self.ollama.endpoint,
                    model=self.ollama.model, target_id='local-process'))
            if configure_search:
                service.configure_search(self.search_binding())
            return service
        self.page = self.stack.enter_context(
            BrowserPage(api or FakeApi(), node=self.node, chat_service=chat_service))
        self.page.wait_idle()
        return self.page

    def search_binding(self, **changes):
        value = {'schema_version': 1, 'binding_id': str(uuid4()), 'revision': 'search-one',
                 'adapter': 'searxng', 'boundary': 'same-node', 'endpoint': self.searx.endpoint,
                 'target_id': 'local-process', 'result_limit': 3, 'timeout_seconds': 15}
        value.update(changes)
        return value

    # -- user actions ---------------------------------------------------------
    def open_project_chat(self):
        page = self.page
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        page.click('#chat-tab')
        page.wait_js("document.querySelector('#chat-run-adapter option[value=\"ollama\"]')",
                     'the Ollama offer in the run selector')
        page.wait_idle()
        page.fill('#chat-run-adapter', 'ollama')
        page.fill('#chat-run-model', 'aggregate:ollama/' + self.ollama.model)

    def submit_prompt(self, text, *, action='answer'):
        page = self.page
        page.fill('#task-action', action)
        page.fill('#chat-draft', text)
        before = len(page.api.requests)
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait(lambda: any(item['path'].startswith('/v1/tasks/route')
                              for item in page.api.requests[before:]), 'the prompt to be sent')
        page.wait_js("!['','Odesílám…'].includes(document.querySelector('#chat-operation-status').textContent)",
                     'the prompt to finish')
        page.wait_idle()
        return page.api.requests[before:]

    def assert_prompt_status(self, expected, sent):
        """Status after a prompt; on failure show what the route request returned."""
        actual = self.page.text('#chat-operation-status')
        if actual != expected:
            route = [item for item in sent if item['path'].startswith('/v1/tasks/route')]
            detail = [(self.page.status(item), self.page.response_json(item)) for item in route]
            self.fail(f'{actual!r} != {expected!r}; route responses: {detail}')

    def click_text(self, text, scope='#chat-messages'):
        found = self.page.evaluate(f"""(()=>{{const button=[...document.querySelectorAll(
          {json.dumps(scope + ' button')})].find(b=>b.textContent.trim()==={json.dumps(text)});
          if(!button)return false;button.click();return true;}})()""")
        self.assertTrue(found, f'Button {text!r} not found in {scope}')

    def buttons(self, scope='#chat-messages'):
        return self.page.evaluate(
            f"[...document.querySelectorAll({json.dumps(scope + ' button')})].map(b=>b.textContent.trim())")

    def requests(self, path, since=0):
        return [item for item in self.page.api.requests[since:] if item['path'] == path]

    def assert_no_page_errors(self):
        self.assertEqual(self.page.exceptions, [], 'Uncaught page exceptions')
