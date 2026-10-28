# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One-shot curses review UI for roadmap refinement proposals."""
import curses
import textwrap
from uuid import uuid4


HELP = ('j/k nebo sipky: vyber | PgUp/PgDn: detail | s: scan | '
        'a: prijmout | r: zamitnout | p: zapsat | q: konec')


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
        self.detail_offset = 0
        self.contexts = {}
        self.refresh()

    def refresh(self):
        self.rows = self.service.list()
        self.selected = min(self.selected, max(0, len(self.rows) - 1))
        active = {row['proposal_id'] for row in self.rows}
        self.contexts = {key: value for key, value in self.contexts.items() if key in active}
        for row in self.rows:
            if row['proposal_id'] not in self.contexts:
                try:
                    self.contexts[row['proposal_id']] = self.service.review_context(row)
                except Exception as exc:
                    self.contexts[row['proposal_id']] = {'context_error': str(exc)}

    def current(self):
        return self.rows[self.selected] if self.rows else None

    def context(self):
        row = self.current()
        if not row:
            return {}
        key = row['proposal_id']
        if key not in self.contexts:
            try:
                self.contexts[key] = self.service.review_context(row)
            except Exception as exc:
                self.contexts[key] = {'context_error': str(exc)}
        return self.contexts[key]

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
            self.detail_offset = 0
        elif key in (ord('k'), curses.KEY_UP):
            self.selected = max(0, self.selected - 1)
            self.detail_offset = 0
        elif key == curses.KEY_NPAGE:
            self.detail_offset += 8
        elif key == curses.KEY_PPAGE:
            self.detail_offset = max(0, self.detail_offset - 8)
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
    split = max(38, min(64, width * 45 // 100))
    visible = height - 7
    _put(screen, 4, 0, '#   STAV      NAVRH          ZDROJ  ->  CIL', split - 1, curses.A_BOLD)
    _put(screen, 5, 0, '-' * (split - 1), split - 1)
    start = max(0, min(ui.selected - visible // 2, max(0, len(ui.rows) - visible)))
    for position, row in enumerate(ui.rows[start:start + visible], start=start):
        proposal = row['proposal']
        decision = proposal.get('decision', proposal.get('outcome', ''))
        target = proposal.get('target_id') or '-'
        context = ui.contexts.get(row['proposal_id'], {})
        source = context.get('source_title') or row.get('document_id', '-')[:8]
        label = f"{position + 1:>3} {row['state']:<9} {decision:<13} {source} -> {target}"
        _put(screen, 6 + position - start, 0, label, split - 1,
             curses.A_REVERSE if position == ui.selected else 0)
    row = ui.current()
    if row:
        proposal = row['proposal']
        context = ui.context()
        target = context.get('target') or {}
        decision = proposal.get('decision')
        if decision == 'attach':
            effect = ('Presune odkaz ze sekce neprirazenych podkladu pod vybrany cil. '
                      'Obsah zdrojoveho souboru se nemeni.')
            action = 'PRIPOJIT PODKLAD K EXISTUJICIMU CILI'
        elif decision == 'keep-detached':
            effect = 'Ponecha podklad samostatne; do projektove roadmapy se nic nezapise.'
            action = 'PONECHAT JAKO SAMOSTATNY PODKLAD'
        else:
            effect = 'Navrh nelze aplikovat; jde o diagnosticky stav modeloveho behu.'
            action = 'BEZ APLIKOVATELNE ZMENY'
        source_title = context.get('source_title', row.get('document_id', '-'))
        target_label = '-'
        if proposal.get('target_id'):
            target_label = proposal['target_id']
            if target:
                target_label += ' — ' + target['title'] + ' (' + target['type'] + ')'
        detail = [
            context.get('project_title', ui.service.project_id),
            'STAV: ' + row['state'] + '    JISTOTA: ' + str(proposal.get('confidence', '-')),
            '',
            'NAVRH: ' + action,
            'ODKUD: ' + source_title,
            'SOUBOR: ' + context.get('source_path', '-'),
            'KAM: ' + target_label,
            'DOPAD: ' + effect,
            '',
            'ODUVODNENI MODELU:',
            proposal.get('reason') or proposal.get('error') or '-',
            '',
            'NAHLED ZDROJOVEHO TEXTU:',
            context.get('source_excerpt') or context.get('context_error') or '-',
            '',
            'AUDIT: proposal ' + row['proposal_id'],
            'HEAD: ' + row['expected_head'],
        ]
        rendered = []
        for value in detail:
            for line in _lines(value, width - split - 2):
                rendered.append(line)
        max_offset = max(0, len(rendered) - (height - 5))
        ui.detail_offset = min(ui.detail_offset, max_offset)
        y = 4
        for line in rendered[ui.detail_offset:ui.detail_offset + height - 5]:
            _put(screen, y, split + 1, line, width - split - 2)
            y += 1
        if max_offset:
            _put(screen, height - 1, split + 1,
                 f'Detail {ui.detail_offset + 1}-{min(len(rendered), ui.detail_offset + height - 5)} '
                 f'z {len(rendered)} (PgUp/PgDn)', width - split - 2, curses.A_BOLD)
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
