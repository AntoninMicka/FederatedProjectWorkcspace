# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native-only LXC deployment dialog; remote commands never enter WebEngine."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
                               QLabel, QPlainTextEdit, QPushButton, QMessageBox)
from spikes.lxc_deployment import deploy


class DeploymentWorker(QThread):
    progress = Signal(str)
    failed = Signal(str)
    succeeded = Signal()

    def __init__(self, node, values, parent):
        super().__init__(parent)
        self.node, self.values = node, values

    def run(self):
        try:
            deploy(self.node, *self.values, self.progress.emit)
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class DeploymentDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node, self.worker = node, None
        self.setWindowTitle('Nasazení LXC uzlu'); self.resize(820, 650)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.host = QLineEdit(); self.host.setPlaceholderText('root@192.168.100.1')
        self.container = QLineEdit('workspace-m0')
        self.lan = QLineEdit('192.168.100.0/24')
        self.endpoint = QLineEdit(); self.endpoint.setPlaceholderText('HTTPS adresa desktopového backendu pro evidenci peeru')
        self.mode = QComboBox()
        for text, value in [('První instalace a propojení', 'install'), ('Aktualizovat pouze aplikaci', 'update'),
                            ('Obnovit přerušené nasazení', 'recover'), ('Resetovat stav — bez rollbacku', 'reset')]:
            self.mode.addItem(text, value)
        for title, field in [('SSH router', self.host), ('Kontejner', self.container), ('Privátní LAN', self.lan),
                             ('Adresa desktopového uzlu', self.endpoint), ('Operace', self.mode)]:
            form.addRow(title, field)
        layout.addLayout(form)
        notice = QLabel('Jedno SSH spojení; IP kontejneru se zjistí automaticky. Router musí mít Python 3.\n'
                        'SSH host key musí být předem důvěryhodný v known_hosts. Heslo se neukládá.\n'
                        'První instalace založí lokálního správce a schválí peery na obou uzlech.\n'
                        'Existující účty a důvěra se nepřepisují. Adresa desktopu musí být skutečný HTTPS backend;\n'
                        'lokální desktopový WebEngine server není síťový backend. Projektová synchronizace se nezapíná.')
        notice.setWordWrap(True); layout.addWidget(notice)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log)
        self.start = QPushButton('Zobrazit souhrn a spustit'); layout.addWidget(self.start)
        self.start.clicked.connect(self.launch)

    def launch(self):
        values = (self.host.text().strip(), self.container.text().strip(), self.lan.text().strip(),
                  self.endpoint.text().strip(), self.mode.currentData())
        summary = QMessageBox(self)
        summary.setWindowTitle('Potvrdit vzdálené změny')
        from PySide6.QtCore import Qt
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setText('Cíl: ' + values[0] + '\nKontejner: ' + values[1] + '\nLAN: ' + values[2] +
                        '\nOperace: ' + self.mode.currentText() + '\n\n'
                        'Instalace/aktualizace restartuje pouze web. První instalace vytvoří správce a oboustrannou důvěru.\n'
                        'Reset zahodí recovery snapshot a zastaví službu; není rollback. Pokračovat?')
        summary.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        summary.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if summary.exec() != QMessageBox.StandardButton.Yes:
            return
        self.start.setEnabled(False)
        for field in (self.host, self.container, self.lan, self.endpoint, self.mode):
            field.setEnabled(False)
        self.worker = DeploymentWorker(self.node, values, self)
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.failed.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(lambda: self.log.appendPlainText('Operace dokončena.'))
        self.worker.finished.connect(self.finished_operation)
        self.worker.start()

    def finished_operation(self):
        self.start.setEnabled(True)
        for field in (self.host, self.container, self.lan, self.endpoint, self.mode):
            field.setEnabled(True)

    def reject(self):
        if self.worker and self.worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
