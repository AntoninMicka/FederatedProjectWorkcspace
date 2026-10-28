# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One-shot curses review UI for roadmap refinement proposals."""
import curses
import textwrap
from uuid import uuid4


HELP = 'j/k nebo sipky: vyber | s: scan | a: accept | r: reject | p: apply | q: konec'


def _lines(value, width):
    return textwrap.wrap(str(value), max(8, width), replace_whitespace=False) or ['']


class RefinementTUI:
    """Small interaction controller; durable state remains in the service."""
    def __init__(self, service, *, scan_limit=5, operation_factory=None):
        self.service = service
        self.scan_limit = scan_limit
        self.operation_factory = operation_factory or (lambda: str(uuid4()))
        self.rows = []
        self.selected = 0
        self.confirm_apply = False
        self.message = ''
        self.refresh()

    def refresh(self):
        self.rows = self.service.list()
        self.selected = min(self.selected, max(0, len(self.rows) - 1))

    def current(self):
        return self.rows[self.selected] if self.rows else None

    def handle(self, key):
        if key in (ord('q'), 27):
            return False
        if self.confirm_apply:
            self.confirm_apply = False
            if key in (ord('y'), ord('Y')):
                try:
                    result = self.service.apply(self.operation_factory())
                    self.message = 'Apply dokoncen: ' + result['operation_id']
                except Exception as exc:
                    self.message = 'Apply selhal: ' + str(exc)
                self.refresh()
            else:
                self.message = 'Apply zrusen.'
            return True
        if key in (ord('j'), curses.KEY_DOWN):
            self.selected = min(self.selected + 1, max(0, len(self.rows) - 1))
        elif key in (ord('k'), curses.KEY_UP):
            self.selected = max(0, self.selected - 1)
        elif key == ord('s'):
            self.message = 'Ollama scan bezi; projekt se nemeni...'
            try:
                result = self.service.scan(limit=self.scan_limit)
                self.message = ('Scan: nove ' + str(len(result['created'])) +
                                ', zbyva ' + str(result['remaining']))
            except Exception as exc:
                self.message = 'Scan selhal: ' + str(exc)
            self.refresh()
        elif key in (ord('a'), ord('r')):
            row = self.current()
            if not row or row['state'] != 'pending':
                self.message = 'Vybrany navrh neni pending.'
            else:
                decision = 'accept' if key == ord('a') else 'reject'
                try:
                    self.service.decide(row['proposal_id'], decision)
                    self.message = 'Navrh ' + ('prijat.' if decision == 'accept' else 'zamitnut.')
                except Exception as exc:
                    self.message = 'Rozhodnuti selhalo: ' + str(exc)
                self.refresh()
        elif key == ord('p'):
            accepted = sum(row['state'] == 'accepted' for row in self.rows)
            if accepted:
                self.confirm_apply = True
                self.message = f'Zapsat {accepted} prijatych navrhu? y = ano, jina klavesa = ne'
            else:
                self.message = 'Neni zadny accepted navrh.'
        return True


def _put(screen, y, x, value, width, attr=0):
    if y < 0 or width <= 0:
        return
    try:
        screen.addnstr(y, x, value, width, attr)
    except curses.error:
        pass


def draw(screen, ui):
    screen.erase()
    height, width = screen.getmaxyx()
    _put(screen, 0, 0, 'Roadmap refinement — ' + ui.service.project_id, width - 1, curses.A_BOLD)
    _put(screen, 1, 0, HELP, width - 1)
    _put(screen, 2, 0, ui.message, width - 1, curses.A_REVERSE if ui.confirm_apply else 0)
    if height < 12 or width < 60:
        _put(screen, 4, 0, 'Terminal musi mit alespon 60x12.', width - 1)
        screen.refresh()
        return
    split = max(28, min(48, width // 2))
    visible = height - 5
    start = max(0, min(ui.selected - visible // 2, max(0, len(ui.rows) - visible)))
    for position, row in enumerate(ui.rows[start:start + visible], start=start):
        proposal = row['proposal']
        decision = proposal.get('decision', proposal.get('outcome', ''))
        target = proposal.get('target_id') or '-'
        label = f"{position + 1:>3} {row['state']:<9} {decision:<13} {target}"
        _put(screen, 4 + position - start, 0, label, split - 1,
             curses.A_REVERSE if position == ui.selected else 0)
    row = ui.current()
    if row:
        proposal = row['proposal']
        detail = [
            'Proposal: ' + row['proposal_id'],
            'Stav: ' + row['state'],
            'HEAD: ' + row['expected_head'],
            'Dokument: ' + str(proposal.get('document_id', '-')),
            'Cil: ' + str(proposal.get('target_id', '-')),
            'Confidence: ' + str(proposal.get('confidence', '-')),
            '',
            proposal.get('reason') or proposal.get('error') or '',
        ]
        y = 4
        for value in detail:
            for line in _lines(value, width - split - 2):
                if y >= height - 1:
                    break
                _put(screen, y, split + 1, line, width - split - 2)
                y += 1
    else:
        _put(screen, 4, split + 1, 'Queue je prazdna; s spusti scan.', width - split - 2)
    screen.refresh()


def run(screen, service, *, scan_limit=5):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    ui = RefinementTUI(service, scan_limit=scan_limit)
    active = True
    while active:
        draw(screen, ui)
        active = ui.handle(screen.getch())
    return ui


def launch(service, *, scan_limit=5):
    return curses.wrapper(run, service, scan_limit=scan_limit)
