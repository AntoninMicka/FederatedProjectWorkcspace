# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native source picker; original bytes never enter a mutating web endpoint."""
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QPlainTextEdit,
                               QPushButton, QFileDialog, QLabel, QMessageBox)
from spikes.desktop_editor import EditorWorker
from spikes.source_import import Sources, request_from_file


class ImportDialog(QDialog):
    saved = Signal(str)

    def __init__(self, node, project_id, parent=None):
        super().__init__(parent)
        self.service, self.project_id = Sources(node), project_id
        self.worker, self.busy, self.view, self.pending = None, False, None, None
        self.setWindowTitle('Import zdroje'); self.resize(760, 590)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.path = QLineEdit(); self.path.setReadOnly(True)
        self.browse = QPushButton('Vybrat soubor…')
        self.title = QLineEdit(); self.title.setMaxLength(200)
        self.description = QPlainTextEdit(); self.description.setMaximumHeight(110)
        self.tags = QPlainTextEdit(); self.tags.setMaximumHeight(75)
        self.source_created_at = QLineEdit()
        self.source_created_at.setPlaceholderText('např. 2024-05-10T14:30:00Z')
        self.source_created_at.setMaxLength(27)
        self.privacy = QComboBox()
        for text, value in [('Projektové', 'project'), ('Důvěrné', 'confidential'), ('Pouze lokální', 'local-only'), ('Veřejné', 'public')]:
            self.privacy.addItem(text, value)
        for label, widget in [('Zdrojový soubor', self.path), ('', self.browse), ('Název', self.title),
                              ('Popis', self.description), ('Štítky — jeden na řádek', self.tags),
                              ('Doložený čas vzniku zdroje (UTC)', self.source_created_at),
                              ('Privacy', self.privacy)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        note = QLabel('Původní bajty se zachovají beze změny; metadata se uloží vedle souboru.\n'
                      'Markdown, PNG, JPEG a PDF do 16 MiB. Náhled má samostatný limit 4 MiB.\n'
                      'Čas importu se uloží automaticky. Čas vzniku zdroje je samostatný, volitelný údaj;\n'
                      'vyplňte jej jen pokud jej zdroj dokládá — může být starší než import.\n'
                      'Zdroj není editovatelný dokument. Nová verze se importuje jako nový zdroj.\n'
                      'Pouze lokální obsah není dostupný přes web a brání přenosu projektu.')
        note.setWordWrap(True); layout.addWidget(note)
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.save = QPushButton('Potvrdit a importovat'); layout.addWidget(self.save)
        self.reload = QPushButton('Znovu načíst a obnovit připravenou operaci'); layout.addWidget(self.reload)
        self.browse.clicked.connect(self.pick); self.save.clicked.connect(self.import_file); self.reload.clicked.connect(self.load)
        self.load()

    def controls(self):
        editable = not self.busy and self.pending is None and self.view is not None
        for widget in (self.browse, self.title, self.description, self.tags,
                       self.source_created_at, self.privacy):
            widget.setEnabled(editable)
        self.save.setEnabled(not self.busy and (self.pending is not None or (editable and bool(self.path.text()))))
        self.save.setText('Zopakovat stejný import' if self.pending else 'Potvrdit a importovat')
        self.reload.setEnabled(not self.busy)

    def run_action(self, action, done):
        self.busy = True; self.controls(); self.status.setText('Pracuji…')
        self.worker = EditorWorker(action, self)
        self.worker.succeeded.connect(done)
        self.worker.failed.connect(lambda message: self.status.setText('Operace nebyla dokončena: ' + message +
                                  '\nPřipravený import lze zopakovat; načtení dokončí již připravený journal, není rollback.'))
        self.worker.finished.connect(self.operation_finished)
        self.worker.start()

    def operation_finished(self):
        self.busy = False; self.controls()

    def load(self):
        if self.busy:
            return
        if self.pending:
            message = QMessageBox(self); message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText('Načtení obnoví již připravený zápis. Nejde o jeho zrušení.\n'
                            'Před novým importem zkontrolujte seznam zdrojů, aby nevznikla duplicita. Pokračovat?')
            message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            message.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if message.exec() != QMessageBox.StandardButton.Yes:
                return
        def loaded(view):
            recovering = self.pending is not None
            self.view, self.pending = view, None
            if recovering:
                self.path.clear(); self.saved.emit(self.project_id)
            self.status.setText('Projekt načten. Vyberte zdroj; do potvrzení se nic neimportuje.')
        self.run_action(lambda: self.service.open(self.project_id), loaded)

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Vyberte původní zdroj', '', 'Zdroje (*.md *.png *.jpg *.jpeg *.pdf)')
        if path:
            self.path.setText(path)
            if not self.title.text():
                self.title.setText(Path(path).stem)
            self.controls()

    def import_file(self):
        if self.busy or not self.view:
            return
        if self.pending is None:
            try:
                request = request_from_file(self.project_id, self.view['commit_id'], self.path.text(), self.title.text(),
                                            self.description.toPlainText(),
                                            [tag.strip() for tag in self.tags.toPlainText().splitlines() if tag.strip()],
                                            self.privacy.currentData(),
                                            source_created_at=self.source_created_at.text().strip() or None)
            except Exception as exc:
                self.status.setText(str(exc)); return
            message = QMessageBox(self); message.setWindowTitle('Potvrdit import původních bajtů')
            message.setTextFormat(Qt.TextFormat.PlainText)
            creation = request['source_created_at'] or 'neuveden — nebude odhadnut'
            message.setText('Soubor: ' + request['filename'] + '\nPrivacy: ' + request['privacy'] +
                            '\nDoložený čas vzniku zdroje: ' + creation +
                            '\nSHA-256: ' + request['sha256'] + '\n\nImportovat jako nový zdroj s vlastními metadaty?')
            message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            message.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if message.exec() != QMessageBox.StandardButton.Yes:
                return
            self.pending = (request, str(uuid4()))
        request, operation = self.pending
        def imported(receipt):
            self.pending = None; self.path.clear(); self.source_created_at.clear()
            self.view = dict(self.view, commit_id=receipt['commit_id'])
            self.status.setText('Zdroj importován beze změny původních bajtů. Najdete jej v Podkladech.\n'
                                'SHA-256: ' + request['sha256'])
            self.saved.emit(self.project_id)
        self.run_action(lambda: self.service.import_source(request, operation), imported)

    def reject(self):
        if self.busy:
            return
        if self.pending:
            self.status.setText('Nejprve zopakujte import nebo načtěte projekt a obnovte připravený zápis.'); return
        super().reject()

    def closeEvent(self, event):
        if self.busy or self.pending:
            event.ignore()
        else:
            event.accept()
