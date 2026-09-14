# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit native UI for the first public-project Git transfer."""
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
                               QPushButton, QPlainTextEdit, QMessageBox, QLabel)
from spikes.desktop_network import NetworkWorker
from spikes.deployment_targets import DeploymentTargets
from spikes.git_transfer import transfer
from spikes.projects import Projects


class TransferDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node, self.worker, self.pending = node, None, None
        self.setWindowTitle('Přenést veřejný projekt do LXC'); self.resize(800, 570)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.projects = QComboBox(); self.targets = QComboBox(); self.ca = QLineEdit()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        try:
            for project in Projects(node).catalog():
                if project['available']:
                    self.projects.addItem(project['title'], project['id'])
            for target in DeploymentTargets(node).load():
                self.targets.addItem(target['container'] + ' — ' + target['endpoint'], target)
        except Exception as exc:
            self.log.appendPlainText(str(exc))
        form.addRow('Projekt desktopu', self.projects); form.addRow('Cílový LXC uzel', self.targets)
        form.addRow('Důvěryhodná veřejná CA LXC', self.ca); layout.addLayout(form)
        notice = QLabel('První přenos nativním Gitem bez hooků/merge. Cíl musí být nový projekt.\n'
                        'Celá historie musí mít pouze public entity a klasifikované projektové soubory.\n'
                        'Project/confidential/local-only i ve starém commitu přenos zastaví.\n'
                        'Commit messages a projektové názvy se přenášejí také; před potvrzením posuďte jejich zveřejnění.\n'
                        'Neproběhne automatická reklasifikace ani přenos credentials/indexu/journalu.\n'
                        'Nejprve aktualizujte LXC na vydání s touto funkcí.')
        notice.setWordWrap(True); layout.addWidget(notice)
        self.start = QPushButton('Potvrdit a přenést'); layout.addWidget(self.start); layout.addWidget(self.log)
        self.targets.currentIndexChanged.connect(self.target_changed); self.target_changed()
        self.start.clicked.connect(self.launch)

    def target_changed(self, *_):
        target = self.targets.currentData()
        if target:
            root = Path(self.node).absolute().parent / ('.' + Path(self.node).name + '.network')
            self.ca.setText(str(root / (target['node_id'] + '-ca.pem')))

    def launch(self):
        if self.worker and self.worker.isRunning():
            return
        if self.pending is None:
            target = self.targets.currentData(); project = self.projects.currentData(); ca = self.ca.text().strip()
            if not target or not project or not ca:
                self.log.appendPlainText('Vyberte projekt, LXC a jeho veřejnou CA.'); return
            confirmation = QMessageBox(self)
            confirmation.setWindowTitle('Potvrdit přenos celé veřejné historie')
            confirmation.setTextFormat(Qt.TextFormat.PlainText)
            confirmation.setText('Projekt: ' + self.projects.currentText() + '\nLXC: ' + target['container'] +
                                 '\nSSH: ' + target['host'] + '\n\n'
                                 'Přenést celou historii veřejného projektu a zaregistrovat nový projekt na LXC?\n'
                                 'Existující projekt se nepřepíše. Metadata autorů a zprávy commitů jsou součástí historie.')
            confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if confirmation.exec() != QMessageBox.StandardButton.Yes:
                return
            self.pending = (target, project, str(uuid4()), ca)
        for widget in (self.projects, self.targets, self.ca, self.start):
            widget.setEnabled(False)
        self.log.appendPlainText('Ověřuji historii a přenáším nativní Git bundle…')
        self.worker = NetworkWorker(lambda: transfer(self.node, *self.pending), self)
        self.worker.done.connect(self.log.appendPlainText)
        self.worker.finished.connect(lambda: (self.start.setEnabled(True), self.start.setText('Zopakovat stejnou operaci')))
        self.worker.start()

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
