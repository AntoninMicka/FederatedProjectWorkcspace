# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Native history viewer with no editor writes or HTML rendering."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
                               QPlainTextEdit, QPushButton, QTabWidget)

from spikes.artifact_history import ArtifactHistory, metadata_text
from spikes.desktop_editor import EditorWorker


class HistoryDialog(QDialog):
    def __init__(self, node_path, project_id, artifact_id, head, parent=None):
        super().__init__(parent)
        self.service = ArtifactHistory(node_path)
        self.args = (project_id, artifact_id, head)
        self.busy, self.workers = False, []
        self.setWindowTitle('Historie dokumentu · pouze pro čtení')
        self.resize(1000, 740)
        layout = QVBoxLayout(self)
        self.status = QLabel(); self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True); layout.addWidget(self.status)
        choices = QHBoxLayout()
        self.older, self.newer = QComboBox(), QComboBox()
        for widget in (self.older, self.newer):
            widget.setMinimumContentsLength(18)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for label, widget in [('Starší / výchozí verze', self.older), ('Zobrazená verze', self.newer)]:
            choices.addWidget(QLabel(label)); choices.addWidget(widget, 1)
        layout.addLayout(choices)
        self.compare_button = QPushButton('Zobrazit a porovnat')
        layout.addWidget(self.compare_button)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.body, self.metadata, self.diff, self.info = (QPlainTextEdit() for _ in range(4))
        for name, widget in [('Obsah zobrazené verze', self.body), ('Technické údaje', self.metadata),
                             ('Rozdíl uložených souborů', self.diff), ('Záznam uložení', self.info)]:
            widget.setReadOnly(True)
            widget.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            self.tabs.addTab(widget, name)
        self.compare_button.clicked.connect(self.compare)
        self.older.currentIndexChanged.connect(self.clear)
        self.newer.currentIndexChanged.connect(self.clear)
        self.start(lambda: self.service.list(*self.args), self.loaded)

    def controls(self):
        enabled = not self.busy
        self.older.setEnabled(enabled); self.newer.setEnabled(enabled)
        self.compare_button.setEnabled(enabled and self.older.currentData() is not None and self.newer.currentData() is not None)

    def clear(self, *_):
        for widget in (self.body, self.metadata, self.diff, self.info):
            widget.clear()

    def start(self, action, success):
        self.busy = True; self.clear(); self.controls(); self.status.setText('Načítám historii…')
        worker = EditorWorker(action, self); self.workers.append(worker)
        worker.succeeded.connect(success)
        worker.failed.connect(lambda message: self.status.setText('Historii nelze zobrazit: ' + message))
        def finished():
            self.busy = False; self.controls()
        worker.finished.connect(finished); worker.start()

    def loaded(self, result):
        self.versions = result['versions']
        self.older.clear(); self.newer.clear()
        for row in self.versions:
            suffix = ' · neplatná/nepodporovaná verze' if not row['available'] else (' · smazáno' if row['deleted'] else '')
            summary = row['message'].splitlines()[0] if row['message'] else '(bez zprávy)'
            label = f"{row['commit_id'][:10]} · {row['date']} · {row['author']} · {summary[:100]}{suffix}"
            for widget in (self.older, self.newer):
                widget.addItem(label, row)
        self.newer.setCurrentIndex(0)
        self.older.setCurrentIndex(min(1, len(self.versions) - 1))
        self.status.setText('Vyberte verze a klikněte na Zobrazit a porovnat.' +
                            (' Zobrazeno nejnovějších 100 záznamů.' if result['truncated'] else ''))

    def compare(self):
        old, new = self.older.currentData(), self.newer.currentData()
        if self.busy or old is None or new is None:
            return
        if not old['available'] or not new['available']:
            self.clear(); self.status.setText('Vybraná verze neprošla validací nebo není podporovaný Markdown.'); return
        def shown(result):
            version = result['after']
            self.body.setPlainText(version['body'] if version else 'Dokument v této verzi neexistuje.')
            self.metadata.setPlainText(metadata_text(version))
            self.diff.setPlainText(result['diff'] or 'Vybrané verze nemají rozdíly v souborech dokumentu.')
            self.info.setPlainText(f"{new['commit_id']}\n{new['date']}\n{new['author']} <{new['email']}>\n\n{new['message']}")
            self.status.setText('Uložená verze · pouze pro čtení. Rozepsaný text editoru zůstává zachovaný.')
        self.start(lambda: self.service.compare(*self.args, old['commit_id'], new['commit_id']), shown)

    def reject(self):
        if not self.busy:
            for worker in self.workers: worker.wait()
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            for worker in self.workers: worker.wait()
            event.accept()
