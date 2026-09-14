# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native settings and diagnostics for the opt-in desktop network listener."""
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
                               QCheckBox, QPushButton, QPlainTextEdit, QLabel, QMessageBox)

from spikes.administration import Administration
from spikes.deployment_targets import DeploymentTargets, address_candidates
from spikes.federation_probe import check_peer
from spikes.lxc_setup import ACTOR
from spikes.network_backend import private_root


class NetworkWorker(QThread):
    done = Signal(str)

    def __init__(self, action, parent):
        super().__init__(parent); self.action = action

    def run(self):
        try:
            self.done.emit(self.action())
        except Exception as exc:
            self.done.emit('Operace selhala: ' + str(exc))


class NetworkDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend, self.worker = backend, None
        self.setWindowTitle('Síťový backend a spojení'); self.resize(820, 680)
        layout = QVBoxLayout(self); form = QFormLayout()
        config = backend.config or {}
        self.enabled = QCheckBox('Povolit HTTPS backend při běhu desktopu')
        self.enabled.setChecked(config.get('enabled', False))
        self.bind = QComboBox(); self.bind.setEditable(True)
        for endpoint in address_candidates():
            self.bind.addItem(urlsplit(endpoint).hostname)
        if config.get('bind'):
            self.bind.setEditText(config['bind'])
        self.port = QLineEdit(str(config.get('port', 8443)))
        self.lan = QLineEdit(config.get('lan', '192.168.100.0/24'))
        self.cert = QLineEdit(config.get('cert', '')); self.key = QLineEdit(config.get('key', ''))
        self.ca = QLineEdit(config.get('ca', ''))
        self.generate = QCheckBox('Vytvořit lokální CA a TLS certifikát pro zvolenou IP')
        self.generate.setChecked(not bool(config))
        for title, field in [('Backend', self.enabled), ('Naslouchací IPv4', self.bind), ('Port', self.port),
                             ('Povolená LAN klientů', self.lan), ('TLS certifikát', self.cert),
                             ('TLS soukromý klíč', self.key), ('Veřejná CA', self.ca), ('Nové TLS', self.generate)]:
            form.addRow(title, field)
        layout.addLayout(form)
        notice = QLabel('Backend sdílí identitu desktopu a běží v jeho procesu. Vystavuje pouze podepsaný test spojení,\n'
                        'nikoli projekty, účty nebo synchronizaci. Vygenerování nového TLS mění CA důvěru.\n'
                        'Firewall se nemění; povolte spojení sami pouze v důvěryhodné LAN.')
        notice.setWordWrap(True); layout.addWidget(notice)
        self.apply = QPushButton('Použít a uložit nastavení'); layout.addWidget(self.apply)
        self.targets = QComboBox()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        try:
            for target in DeploymentTargets(backend.node).load():
                self.targets.addItem(target['container'] + ' — ' + target['endpoint'], target)
        except Exception as exc:
            self.log.appendPlainText(str(exc))
        self.peer_ca = QLineEdit(); self.peer_ca.setPlaceholderText('Veřejná CA LXC; po novém deployi se doplní automaticky')
        test_form = QFormLayout(); test_form.addRow('Protější uzel', self.targets); test_form.addRow('CA protějšího uzlu', self.peer_ca)
        layout.addLayout(test_form)
        self.test = QPushButton('Ověřit HTTPS a identitu protějšího uzlu'); layout.addWidget(self.test)
        self.both = QPushButton('Ověřit oba směry a nastavit desktopovou CA/adresu na LXC…')
        layout.addWidget(self.both)
        layout.addWidget(self.log)
        self.targets.currentIndexChanged.connect(self.target_changed)
        self.target_changed()
        self.apply.clicked.connect(self.configure); self.test.clicked.connect(self.check)
        self.both.clicked.connect(self.check_bilateral)
        self.log.appendPlainText('Aktivní backend: ' + (backend.endpoint or 'vypnutý'))

    def target_changed(self, *_):
        target = self.targets.currentData()
        if target:
            root = Path(self.backend.node).absolute().parent / ('.' + Path(self.backend.node).name + '.network')
            path = root / (target['node_id'] + '-ca.pem')
            self.peer_ca.setText(str(path) if path.is_file() else '')

    def run_action(self, action):
        if self.worker and self.worker.isRunning():
            return
        self.apply.setEnabled(False); self.test.setEnabled(False); self.both.setEnabled(False)
        self.worker = NetworkWorker(action, self)
        self.worker.done.connect(self.log.appendPlainText)
        self.worker.finished.connect(lambda: (self.apply.setEnabled(True), self.test.setEnabled(True), self.both.setEnabled(True)))
        self.worker.start()

    def configure(self):
        try:
            config = dict(bind=self.bind.currentText().strip(), port=int(self.port.text()), lan=self.lan.text().strip(),
                          cert=self.cert.text().strip(), key=self.key.text().strip(), ca=self.ca.text().strip(),
                          enabled=self.enabled.isChecked())
            self.backend.validate(config)
            generate = self.generate.isChecked() and config['enabled']
        except Exception as exc:
            self.log.appendPlainText(str(exc)); return
        def action():
            candidate = self.backend.generate(config['bind'], config['port'], config['lan']) if generate else config
            self.backend.configure(candidate)
            return ('Backend: ' + (self.backend.endpoint or 'vypnutý') + '\nVeřejná CA: ' + candidate['ca'] +
                    '\nPři změně adresy upravte také evidenci desktopového peeru na LXC. Test neprovádí synchronizaci.')
        self.run_action(action)

    def check(self):
        target = self.targets.currentData(); ca = self.peer_ca.text().strip()
        if not target or not ca:
            self.log.appendPlainText('Vyberte zapamatovaný uzel a jeho důvěryhodnou veřejnou CA.'); return
        def action():
            view = Administration(self.backend.node, deployment='desktop').request(ACTOR, {'action': 'list'})
            peer = next((p for p in view['peers'] if p['id'] == target['node_id']), None)
            if not peer or peer['trust'] != 'approved' or peer['fingerprint'] != target['fingerprint']:
                raise ValueError('Uzel není schválený s původním pinem. Nejdříve vyřešte jeho důvěru ve správě.')
            return check_peer(peer['endpoint'], ca, peer['id'], peer['fingerprint'])
        self.run_action(action)

    def check_bilateral(self):
        if self.worker and self.worker.isRunning():
            return
        target = self.targets.currentData(); ca = self.peer_ca.text().strip()
        if not target or not ca or not self.backend.endpoint:
            self.log.appendPlainText('Vyberte LXC a jeho CA a zapněte desktopový HTTPS backend.'); return
        from PySide6.QtCore import Qt
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle('Potvrdit SSH test a veřejnou CA')
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setText('Router: ' + target['host'] + '\nKontejner: ' + target['container'] +
                             '\nDesktop: ' + self.backend.endpoint + '\n\n'
                             'Přenést pouze veřejnou CA desktopu do LXC a aktualizovat adresu již schváleného peeru?\n'
                             'Použije se jedno SSH spojení. Identity, práva, soukromé klíče ani firewall se nemění.\n'
                             'Při chybě testu mohou CA/adresa již zůstat aktualizované. Pokračovat?')
        confirmation.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirmation.exec() != QMessageBox.StandardButton.Yes:
            return
        from spikes.peer_diagnostics import check_both
        self.run_action(lambda: check_both(self.backend, target, ca))

    def reject(self):
        if not self.worker or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()
