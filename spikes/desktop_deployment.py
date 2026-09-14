# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native-only LXC deployment dialog; remote commands never enter WebEngine."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
                               QLabel, QPlainTextEdit, QPushButton, QMessageBox)
from spikes.lxc_deployment import deploy
from spikes.deployment_targets import DeploymentTargets, address_candidates


class DeploymentWorker(QThread):
    progress = Signal(str)
    failed = Signal(str)
    succeeded = Signal()

    def __init__(self, node, values, parent):
        super().__init__(parent)
        self.node, self.values = node, values

    def run(self):
        try:
            store = DeploymentTargets(self.node)
            remembered = next((t for t in store.load() if (t['host'], t['container']) == self.values[:2]), None)
            result = deploy(self.node, *self.values, self.progress.emit, remembered=remembered)
            if result:
                try:
                    store.remember(result)
                    self.progress.emit('Deployment target remembered locally; no credentials saved.')
                except Exception as exc:
                    self.progress.emit('Remote operation completed, but saving preferences failed: ' + str(exc))
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class DeploymentDialog(QDialog):
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node, self.worker = node, None
        self.setWindowTitle('Nasazení LXC uzlu'); self.resize(820, 650)
        layout = QVBoxLayout(self); form = QFormLayout()
        self.targets = QComboBox(); self.targets.addItem('Nový / ručně zadaný uzel', None)
        self.preferences_error = None
        try:
            for target in DeploymentTargets(node).load():
                self.targets.addItem(target['container'] + ' — ' + target['host'] + ' — ' + target['endpoint'], target)
        except Exception as exc:
            self.preferences_error = str(exc)
        form.addRow('Zapamatovaný uzel', self.targets)
        self.host = QLineEdit(); self.host.setPlaceholderText('root@192.168.100.1')
        self.container = QLineEdit('workspace-m0')
        self.lan = QLineEdit('192.168.100.0/24')
        self.endpoint = QComboBox(); self.endpoint.setEditable(True); self.endpoint.addItem('')
        for candidate in address_candidates():
            self.endpoint.addItem(candidate)
        self.endpoint.lineEdit().setPlaceholderText('Vyberte vlastní IP a ověřte HTTPS port backendu')
        self.mode = QComboBox()
        for text, value in [('První instalace a propojení', 'install'), ('Aktualizovat pouze aplikaci', 'update'),
                            ('Obnovit přerušené nasazení', 'recover'), ('Resetovat stav — bez rollbacku', 'reset'),
                            ('Aktualizovat adresu kontejneru', 'address')]:
            self.mode.addItem(text, value)
        for title, field in [('SSH router', self.host), ('Kontejner', self.container), ('Privátní LAN', self.lan),
                             ('Adresa desktopového uzlu', self.endpoint), ('Operace', self.mode)]:
            form.addRow(title, field)
        layout.addLayout(form)
        notice = QLabel('Jedno SSH spojení; IP kontejneru se zjistí automaticky. Router musí mít Python 3.\n'
                        'SSH host key musí být předem důvěryhodný v known_hosts. Heslo se neukládá.\n'
                        'První instalace založí lokálního správce a schválí peery na obou uzlech.\n'
                        'Existující účty a důvěra se nepřepisují. Adresa desktopu musí být skutečný HTTPS backend;\n'
                        'lokální desktopový WebEngine server není síťový backend. Projektová synchronizace se nezapíná.\n'
                        'Nabídka vlastních IP používá návrh portu 8443; dostupnost backendu tím není ověřena.')
        notice.setWordWrap(True); layout.addWidget(notice)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log)
        if self.preferences_error:
            self.log.appendPlainText('Zapamatované uzly nelze načíst: ' + self.preferences_error)
        self.targets.currentIndexChanged.connect(self.select_target)
        self.start = QPushButton('Zobrazit souhrn a spustit'); layout.addWidget(self.start)
        self.start.clicked.connect(self.launch)

    def launch(self):
        values = (self.host.text().strip(), self.container.text().strip(), self.lan.text().strip(),
                  self.endpoint.currentText().strip(), self.mode.currentData())
        summary = QMessageBox(self)
        summary.setWindowTitle('Potvrdit vzdálené změny')
        from PySide6.QtCore import Qt
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setText('Cíl: ' + values[0] + '\nKontejner: ' + values[1] + '\nLAN: ' + values[2] +
                        '\nOperace: ' + self.mode.currentText() + '\n\n'
                        'Instalace/aktualizace restartuje pouze web. První instalace vytvoří správce a oboustrannou důvěru.\n'
                        'Změna adresy ověří IP/TLS/identitu a upraví desktopový peer bez instalace softwaru.\n'
                        'Reset zahodí recovery snapshot a zastaví službu; není rollback. Pokračovat?')
        summary.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        summary.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if summary.exec() != QMessageBox.StandardButton.Yes:
            return
        self.start.setEnabled(False)
        for field in (self.targets, self.host, self.container, self.lan, self.endpoint, self.mode):
            field.setEnabled(False)
        self.worker = DeploymentWorker(self.node, values, self)
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.failed.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(lambda: self.log.appendPlainText('Operace dokončena.'))
        self.worker.finished.connect(self.finished_operation)
        self.worker.start()

    def finished_operation(self):
        self.start.setEnabled(True)
        for field in (self.targets, self.host, self.container, self.lan, self.endpoint, self.mode):
            field.setEnabled(True)

    def select_target(self, index):
        target = self.targets.itemData(index)
        if target:
            self.host.setText(target['host']); self.container.setText(target['container'])
            self.lan.setText(target['lan']); self.endpoint.setEditText(target['desktop_endpoint'])
            self.mode.setCurrentIndex(self.mode.findData('update'))
            self.log.appendPlainText('Zapamatovaná adresa kontejneru: ' + target['endpoint'])

    def reject(self):
        if self.worker and self.worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
