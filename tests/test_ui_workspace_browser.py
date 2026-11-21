# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Workspace navigation, documents and resources in a real browser (AUDIT-B7-T1).

Replaces the workspace part of the source-text assertions of
``test_chat_ui_uses_authenticated_api_and_explicit_message_selection``.
"""
from uuid import uuid4

from spikes.project_creation import ProjectCreation
from tests.ui_flow_case import UiFlowCase, require_browser

SIDEBAR_LABELS = ['Projekty', 'Chaty', 'Úkoly', 'Plán', 'Podklady', 'Zdroje', 'Nástroje', 'Výstupy',
                  'Manuály', 'Nastavení', 'Federace']
PROJECT_TABS = ('todo-tab', 'plan-tab', 'artifacts-tab', 'tools-tab', 'presentations-tab')


@require_browser
class SidebarTests(UiFlowCase):
    def tab_state(self):
        return self.page.evaluate(f"""Object.fromEntries({list(PROJECT_TABS)!r}.map(id=>
          [id,document.getElementById(id).disabled]))""")

    def test_sidebar_offers_project_tools_only_with_an_open_project(self):
        page = self.start(configure_search=False)
        labels = page.evaluate("[...document.querySelectorAll('#sidebar-tabs button')].filter(b=>!b.hidden)"
                               ".map(b=>b.getAttribute('aria-label'))")
        self.assertEqual(labels, SIDEBAR_LABELS)
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#sidebar-tabs .sidebar-tab-label')]"
                                       ".map(x=>x.getAttribute('role'))"), ['tooltip'] * len(SIDEBAR_LABELS))
        self.assertEqual(set(self.tab_state().values()), {True})
        for always in ('projects-tab', 'chats-tab', 'manuals-tab', 'settings-sidebar-tab', 'federation-tab'):
            self.assertFalse(page.evaluate(f"document.getElementById('{always}').disabled"), always)
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        self.assertEqual(set(self.tab_state().values()), {False})

    def test_compact_sidebar_toggles_and_escape_closes_its_menu(self):
        page = self.start(configure_search=False)
        self.assertEqual(page.evaluate("document.querySelector('#sidebar-layout-toggle').getAttribute('aria-pressed')"),
                         'false')
        page.click('#sidebar-layout-toggle')
        state = page.evaluate("""({pressed:document.querySelector('#sidebar-layout-toggle').getAttribute('aria-pressed'),
          compact:document.querySelector('aside').classList.contains('sidebar-compact'),
          width:document.querySelector('aside').getBoundingClientRect().width})""")
        self.assertEqual((state['pressed'], state['compact']), ('true', True))
        self.assertAlmostEqual(state['width'], 70, delta=2)
        page.evaluate("document.querySelector('aside').classList.add('sidebar-menu-open')")
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        self.assertFalse(page.evaluate("document.querySelector('aside').classList.contains('sidebar-menu-open')"))
        self.assertIsNone(page.evaluate("localStorage.length?localStorage.key(0):null"),
                          'Layout state is not persisted in the browser')

    def test_project_actions_come_before_the_list(self):
        page = self.start(configure_search=False)
        order = page.evaluate("""(()=>{const ids=['sidebar-create-project','sidebar-import-project',
          'sidebar-project-trash','sidebar-register-project','sidebar-project-list'];
          const nodes=ids.map(id=>document.getElementById(id));
          return nodes.every((node,index)=>index===0||nodes[index-1].compareDocumentPosition(node)&Node.DOCUMENT_POSITION_FOLLOWING);
        })()""")
        self.assertTrue(order)
        labels = page.evaluate("[...document.querySelectorAll('.sidebar-project-primary-actions button')]"
                               ".filter(b=>!b.hidden).map(b=>b.getAttribute('aria-label'))")
        self.assertEqual(labels[:4], ['Nový projekt', 'Importovat projekt', 'Zavřít projekt', 'Koš projektů'])

    def test_dashboard_loads_each_project_in_dashboard_scope(self):
        other = ProjectCreation(self.node).create('Druhý projekt', str(self.node.parent / 'other'), str(uuid4()))['id']
        page = self.start(configure_search=False)
        scopes = {item['body']['project_id']: item['body'].get('scope')
                  for item in self.requests('/v1/projects/open')}
        self.assertEqual(scopes, {self.project_id: 'dashboard', other: 'dashboard'})
        self.assertTrue(page.visible('#dashboard-grid'))
        for panel in ('dashboard-calendar', 'dashboard-tasks', 'dashboard-mail', 'dashboard-trash'):
            self.assertTrue(page.visible(f'#{panel}'), panel)


@require_browser
class ResourceMonitorTests(UiFlowCase):
    def test_monitor_dialog_shows_six_resources_from_node_telemetry(self):
        page = self.start(configure_search=False)
        groups = {item['body'].get('group') for item in self.requests('/v1/node-telemetry/status')}
        self.assertTrue({'all', 'capacity'} <= groups, groups)
        rows = page.evaluate("[...document.querySelectorAll('.resource-mini-row')].map(x=>x.textContent.trim())")
        self.assertEqual([row[:len(name)] for row, name in zip(rows, ['CPU', 'GPU', 'RAM', 'VRAM', 'DISK', 'NET'])],
                         ['CPU', 'GPU', 'RAM', 'VRAM', 'DISK', 'NET'])
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(len(row) > 3 for row in rows), 'Every resource shows a value or "neznámé"')
        page.click('#resource-monitor-open')
        self.assertTrue(page.evaluate("document.querySelector('#resource-monitor-dialog').open"))
        self.assertIn('živý vzorek tohoto workspace uzlu', page.text('#resource-monitor-dialog'))


@require_browser
class DocumentTests(UiFlowCase):
    def open_project(self):
        page = self.start(configure_search=False)
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        return page

    def save_document(self, title, body, *, new):
        page = self.page
        form = '#artifact-editor-form'
        page.fill(f'{form} [name=title]', title)
        page.fill(f'{form} [name=body]', body)
        before = len(page.api.requests)
        page.evaluate(f"document.querySelector('{form}').requestSubmit()")
        page.wait(lambda: self.requests('/v1/artifacts/editor/save', before), 'save')
        page.wait_idle()
        saved = self.requests('/v1/artifacts/editor/save', before)[0]
        self.assertEqual(page.status(saved), 200)
        self.assertEqual(saved['body']['document']['new'], new)
        return saved['body']['document']['artifact_id']

    def test_document_is_created_edited_and_compared_in_history(self):
        page = self.open_project()
        page.click('#new-document')
        page.wait_js("!document.querySelector('#artifact-editor-view').hidden", 'editor')
        self.assertEqual(page.text('#artifact-editor-status'), 'Dokument vznikne až po uložení.')
        page.fill('#artifact-editor-form [name=filename]', 'zapis.md')
        artifact = self.save_document('Zápis', 'První verze', new=True)
        page.evaluate(f"openArtifactEditor(currentArtifacts.find(item=>item.id==={artifact!r}))")
        page.wait_js("document.querySelector('#artifact-editor-status').textContent==='Uložená verze je připravena k úpravě.'",
                     'saved document')
        self.save_document('Zápis', '<img src=x onerror=window.__pwned=1>Druhá verze', new=False)
        page.evaluate(f"(async()=>{{await openPreview({artifact!r});await openHistory();}})()")
        page.wait_js("!document.querySelector('#history-compare').disabled", 'history')
        versions = page.evaluate("document.querySelectorAll('#history-newer option').length")
        self.assertGreaterEqual(versions, 2)
        page.click('#history-compare')
        page.wait_js("document.querySelector('#history-status').textContent==='Uložená verze · pouze pro čtení.'",
                     'comparison')
        self.assertIn('Druhá verze', page.text('#history-body'))
        self.assertIn('<img', page.text('#history-body'))
        self.assertEqual(page.evaluate("document.querySelectorAll('#history-view img').length"), 0)
        self.assertIsNone(page.evaluate('window.__pwned ?? null'))
        self.assertIn('První verze', page.text('#history-diff'))

    def test_document_deletion_needs_a_reviewed_preview(self):
        page = self.open_project()
        page.click('#new-document')
        page.fill('#artifact-editor-form [name=filename]', 'smazat.md')
        artifact = self.save_document('Ke smazání', 'Obsah', new=True)
        self.click_text('Připravit smazání', '#sidebar-artifact-list')
        page.wait_js("!document.querySelector('#artifact-delete-preview').hidden", 'deletion preview')
        preview = self.requests('/v1/artifacts/delete/preview')[0]['body']
        self.assertEqual(preview['artifact_id'], artifact)
        self.assertTrue(page.evaluate("document.querySelector('#artifact-delete-run').disabled"))
        page.click('#artifact-delete-confirm')
        page.click('#artifact-delete-run')
        page.wait(lambda: self.requests('/v1/artifacts/delete/confirm'), 'delete')
        page.wait_idle()
        confirm = self.requests('/v1/artifacts/delete/confirm')[0]['body']
        self.assertEqual(confirm['artifact_id'], artifact)
        self.assertRegex(confirm['preview_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(page.status(self.requests('/v1/artifacts/delete/confirm')[0]), 200)
        self.assertNotIn(artifact, page.evaluate('currentArtifacts.map(item=>item.id)'))

    def test_main_todo_opens_the_structured_plan_editor(self):
        page = self.open_project()
        page.evaluate('openMainTodoEditor()')
        page.wait_js("!document.querySelector('#artifact-editor-view').hidden", 'editor')
        page.wait_idle()
        self.assertTrue(page.visible('#task-plan-editor'))
        self.assertTrue(page.evaluate("Boolean(document.querySelector('[data-task-pattern=\"task-plan.batch-file\"]'))"))
        self.assertIn('[MILESTONE-01]', page.evaluate("document.querySelector('#artifact-editor-form [name=body]').value"))


@require_browser
class SourceImportTests(UiFlowCase):
    def test_file_is_imported_into_the_project_in_one_request(self):
        page = self.start(configure_search=False)
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        page.evaluate('openSourceImport()')
        page.wait_js("!document.querySelector('#source-import-view').hidden", 'import view')
        page.evaluate("""(()=>{const input=document.querySelector('#source-import-form [name=file]');
          const data=new DataTransfer();data.items.add(new File(['# Zdroj'],'zdroj.md',{type:'text/markdown'}));
          input.files=data.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        self.assertEqual(page.evaluate("document.querySelector('#source-import-form [name=title]').value"), 'zdroj')
        page.evaluate("document.querySelector('#source-import-form').requestSubmit()")
        page.settle()
        self.assertEqual(self.requests('/v1/sources/import'), [], 'The import needs the explicit confirmation')
        page.click('#source-import-form [name=confirmed]')
        page.evaluate("document.querySelector('#source-import-form').requestSubmit()")
        page.wait(lambda: self.requests('/v1/sources/import'), 'import')
        page.wait_idle()
        sent = self.requests('/v1/sources/import')
        self.assertEqual(len(sent), 1)
        self.assertEqual(page.status(sent[0]), 200)
        self.assertEqual(sent[0]['body']['source']['project_id'], self.project_id)
        self.assertIn('zdroj', page.evaluate('currentArtifacts.map(item=>item.title)'))
