# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native two-step NotebookLM Takeout project import dialog."""
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QPlainTextEdit)


class NotebookLMImportDialog(QDialog):
    def __init__(self, parent, service, default_parent):
        super().__init__(parent)
        self.service, self.plan = service, None
        self.setWindowTitle('Importovat projekt z NotebookLM')
        self.resize(720, 620)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.archive = QLineEdit(); self.root = QLineEdit(str(Path(default_parent) / 'notebooklm-import'))
        self.notebook = QComboBox(); self.notebook.setEnabled(False)
        self.privacy = QComboBox()
        self.privacy.addItem('V rámci projektu', 'project')
        self.privacy.addItem('Důvěrné', 'confidential')
        self.privacy.addItem('Jen na tomto počítači', 'local-only')
        self.privacy.addItem('Veřejné', 'public')
        form.addRow('Google Takeout TGZ', self.archive)
        form.addRow('Notebook', self.notebook)
        form.addRow('Cílová složka projektu', self.root)
        form.addRow('Soukromí', self.privacy); layout.addLayout(form)
        choose = QPushButton('Vybrat TGZ…')
        choose.clicked.connect(self.choose_archive); layout.addWidget(choose)
        load = QPushButton('Načíst bezpečný přehled')
        load.clicked.connect(self.load_preview); layout.addWidget(load)
        choose_root = QPushButton('Vybrat nadřazenou složku…')
        choose_root.clicked.connect(self.choose_root); layout.addWidget(choose_root)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setPlaceholderText('Nejprve načtěte archiv. HTML se nespouští a před potvrzením se nic nezapisuje.')
        layout.addWidget(self.preview)
        self.confirm = QCheckBox('Potvrzuji přesný notebook, cílovou cestu, privacy a uvedená omezení.')
        self.confirm.setEnabled(False); layout.addWidget(self.confirm)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.save = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save.setText('Připravit přesný plán')
        self.buttons.accepted.connect(self.validate); self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def choose_archive(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Google Takeout TGZ', '', 'TGZ (*.tgz *.tar.gz)')
        if path:
            self.archive.setText(path); self.plan = None

    def choose_root(self):
        parent = QFileDialog.getExistingDirectory(self, 'Nadřazená složka projektu',
                                                   str(Path(self.root.text()).parent))
        if parent:
            self.root.setText(str(Path(parent) / (Path(self.root.text()).name or 'notebooklm-import')))
            self.plan = None

    def load_preview(self):
        try:
            result = self.service.preview(self.archive.text().strip())
            self.notebook.clear()
            for item in result['notebooks']:
                label = (f'{item["title"]} · {len(item["sources"])} zdrojů · '
                         f'{len(item["artifacts"])} výstupů · {len(item["chats"])} chatů')
                self.notebook.addItem(label, item['selection_digest'])
                if not item['importable']:
                    self.notebook.model().item(self.notebook.count() - 1).setEnabled(False)
            self.notebook.setEnabled(True); self.plan = None
            self.preview.setPlainText(json.dumps({
                'edice': 'Personal NotebookLM / Google Takeout',
                'notebooky': len(result['notebooks']),
                'sha256_archivu': result['archive_sha256']}, ensure_ascii=False, indent=2))
            self.error.setText('Vyberte právě jeden notebook a připravte plán.')
        except Exception as exc:
            self.error.setText(str(exc)); self.notebook.setEnabled(False); self.plan = None

    def signature(self):
        return (self.archive.text().strip(), self.notebook.currentData(), self.root.text().strip(),
                self.privacy.currentData())

    def validate(self):
        try:
            signature = self.signature()
            if not all(signature) or not Path(signature[2]).is_absolute():
                raise ValueError('Vyberte archiv, notebook, absolutní cílovou cestu a privacy.')
            if self.plan is None or self.plan.get('_dialog_signature') != list(signature):
                plan = self.service.plan(*signature[:2], signature[2], signature[3], str(uuid4()))
                plan['_dialog_signature'] = list(signature)
                self.plan = plan
                shown = {key: plan[key] for key in ('format', 'title', 'target_root', 'privacy',
                                                     'archive_sha256', 'selection_digest',
                                                     'warnings', 'existing_imports', 'request_digest')}
                shown['artifact_count'] = len(plan['artifacts'])
                self.preview.setPlainText(json.dumps(shown, ensure_ascii=False, indent=2))
                self.confirm.setChecked(False); self.confirm.setEnabled(True)
                self.save.setText('Vytvořit a otevřít projekt'); self.error.setText('')
                return
            if not self.confirm.isChecked():
                raise ValueError('Nejprve potvrďte zobrazený plán.')
            self.plan.pop('_dialog_signature', None)
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))
