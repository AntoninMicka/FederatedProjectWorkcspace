# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from unittest.mock import patch
from threading import Event
import time

from spikes.roadmap_refinement_tui import ProjectSelector, RefinementTUI, draw, run


class FakeService:
    project_id = '00000000-0000-0000-0000-000000000001'

    def __init__(self):
        self.rows = [dict(
            proposal_id='00000000-0000-0000-0000-000000000002',
            proposal=dict(decision='attach', document_id='doc', target_id='TASK-01',
                          confidence='high', reason='reason'),
            state='pending', expected_head='a' * 40, created_at='now', receipt=None)]
        self.scans = []
        self.applies = []

    def list(self):
        return [dict(row, proposal=dict(row['proposal'])) for row in self.rows]

    def review_context(self, row):
        return dict(project_title='Project', source_title='Readable evidence title',
                    source_path='artifacts/doc/evidence.md', source_excerpt='# Evidence\nContext.',
                    target=dict(id='TASK-01', title='Readable target title', type='task'))

    def decide(self, proposal_id, decision):
        self.rows[0]['state'] = 'accepted' if decision == 'accept' else 'rejected'
        return self.rows[0]

    def scan(self, *, limit):
        self.scans.append(limit)
        return {'created': [], 'remaining': 3}

    def apply(self, operation_id):
        self.applies.append(operation_id)
        self.rows[0]['state'] = 'applied'
        return {'operation_id': operation_id}


class RefinementTUITests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.ui = RefinementTUI(
            self.service, scan_limit=7,
            operation_factory=lambda: '00000000-0000-0000-0000-000000000003',
            background=lambda target: target())

    def test_review_uses_existing_service_and_refreshes_state(self):
        self.assertEqual(self.ui.context()['source_title'], 'Readable evidence title')
        self.assertTrue(self.ui.handle(ord('a')))
        self.assertEqual(self.ui.current()['state'], 'accepted')
        self.assertEqual(self.service.applies, [])

    def test_apply_requires_second_explicit_confirmation(self):
        self.ui.handle(ord('a'))
        self.ui.handle(ord('p'))
        self.assertTrue(self.ui.confirm_apply)
        self.assertEqual(self.service.applies, [])
        self.ui.handle(ord('n'))
        self.assertEqual(self.service.applies, [])
        self.ui.handle(ord('p'))
        self.ui.handle(ord('y'))
        self.assertEqual(self.service.applies,
                         ['00000000-0000-0000-0000-000000000003'])
        self.assertEqual(self.ui.current()['state'], 'applied')

    def test_scan_is_explicit_and_bounded(self):
        self.assertEqual(self.service.scans, [])
        self.ui.handle(ord('s'))
        self.assertEqual(self.service.scans, [7])
        self.assertIn('zbyva 3', self.ui.message)

    def test_real_background_scan_keeps_ui_responsive_and_blocks_early_quit(self):
        started, release = Event(), Event()
        service = FakeService()
        original = service.scan
        def blocked(*, limit):
            started.set(); release.wait(2)
            return original(limit=limit)
        service.scan = blocked
        ui = RefinementTUI(service, scan_limit=4)
        ui.handle(ord('s'))
        self.assertTrue(started.wait(1))
        self.assertTrue(ui.scanning)
        self.assertTrue(ui.handle(ord('q')))
        self.assertIn('stale bezi', ui.message)
        release.set()
        deadline = time.monotonic() + 2
        while not ui.poll() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(ui.scanning)
        self.assertEqual(service.scans, [4])

    def test_quit_does_not_change_queue(self):
        self.assertFalse(self.ui.handle(ord('q')))
        self.assertEqual(self.ui.current()['state'], 'pending')

    def test_table_pages_and_detail_scroll_have_separate_focus(self):
        for number in range(100, 124):
            row = dict(self.service.rows[0])
            row['proposal_id'] = f'00000000-0000-0000-0000-{number:012d}'
            self.service.rows.append(row)
        self.ui.refresh()
        self.ui.table_page = 6
        self.ui.handle(__import__('curses').KEY_NPAGE)
        self.assertEqual(self.ui.selected, 6)
        self.ui.handle(9)
        self.ui.handle(__import__('curses').KEY_NPAGE)
        self.assertEqual(self.ui.selected, 6)
        self.assertEqual(self.ui.detail_offset, 8)
        self.ui.handle(__import__('curses').KEY_END)
        self.assertEqual(self.ui.selected, 24)
        self.ui.handle(__import__('curses').KEY_HOME)
        self.assertEqual(self.ui.selected, 0)

    def test_hide_decided_filters_rows_but_keeps_accepted_apply_visible_to_service(self):
        rejected = dict(self.service.rows[0],
                        proposal_id='00000000-0000-0000-0000-000000000004', state='rejected')
        dismissed = dict(self.service.rows[0],
                         proposal_id='00000000-0000-0000-0000-000000000005', state='dismissed')
        self.service.rows.extend((rejected, dismissed))
        self.ui.refresh()
        self.ui.handle(ord('h'))
        self.assertTrue(self.ui.hide_decided)
        self.assertEqual([row['state'] for row in self.ui.rows], ['pending'])
        self.ui.handle(ord('a'))
        self.assertEqual(self.ui.rows, [])
        self.ui.handle(ord('p'))
        self.assertTrue(self.ui.confirm_apply)
        self.ui.handle(ord('n'))
        self.ui.handle(ord('h'))
        self.assertEqual(len(self.ui.rows), 3)

    def test_unsupported_cursor_visibility_does_not_block_startup(self):
        class Screen:
            def keypad(self, enabled): pass
            def erase(self): pass
            def getmaxyx(self): return (24, 100)
            def addnstr(self, *args): pass
            def refresh(self): pass
            def timeout(self, milliseconds): pass
            def getch(self): return ord('q')
        with patch('spikes.roadmap_refinement_tui.curses.curs_set',
                   side_effect=__import__('curses').error):
            result = run(Screen(), self.service)
        self.assertEqual(result.current()['state'], 'pending')

    def test_render_never_sends_embedded_controls_to_curses_cells(self):
        self.service.rows[0]['proposal']['reason'] = 'first\nsecond\tcolumn\rthird'
        def context(row):
            return dict(project_title='Project\nInjected',
                        source_title='Long title\nthat used to move the cursor',
                        source_path='artifacts/doc/content.md',
                        source_excerpt='line one\nline two\tvalue',
                        target=dict(id='TASK-01', title='Target\nName', type='task'))
        self.service.review_context = context
        ui = RefinementTUI(self.service, background=lambda target: target())
        class Screen:
            def __init__(self): self.values = []
            def erase(self): pass
            def getmaxyx(self): return (28, 120)
            def addnstr(self, y, x, value, width, attr=0): self.values.append(value)
            def refresh(self): pass
        screen = Screen(); draw(screen, ui)
        self.assertTrue(screen.values)
        self.assertTrue(all(not any(ord(char) < 32 or ord(char) == 127 for char in value)
                            for value in screen.values))

    def test_project_selector_uses_title_and_refuses_unavailable_project(self):
        projects = [
            dict(id='00000000-0000-0000-0000-000000000010', title='Unavailable',
                 available=False),
            dict(id='00000000-0000-0000-0000-000000000011', title='Roadmap',
                 available=True),
        ]
        selector = ProjectSelector(projects)
        self.assertIsNone(selector.handle(10))
        self.assertIn('neni lokalne dostupny', selector.message)
        selector.handle(ord('j'))
        self.assertEqual(selector.handle(10), projects[1]['id'])
        self.assertEqual(ProjectSelector(projects).handle(ord('q')), 'quit')


if __name__ == '__main__':
    unittest.main()
