# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Native Qt creation dialog/controller: never accepts commands from JavaScript."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QLineEdit, QPushButton, QLabel, QVBoxLayout, QCheckBox)

from spikes.project_creation import CreationConflict


class CreationDialog(QDialog):
    def __init__(self, parent, default_parent):
        super().__init__(parent)
        self.setWindowTitle('Nový projekt')
        self.resize(600, 240)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(200)
        self.root = QLineEdit(str(Path(default_parent) / 'novy-projekt'))
        form.addRow('Název projektu', self.title)
        form.addRow('Složka projektu', self.root)
        layout.addLayout(form)
        browse = QPushButton('Vybrat nadřazenou složku…')
        def choose():
            folder = QFileDialog.getExistingDirectory(self, 'Nadřazená složka', str(default_parent))
            if folder:
                self.root.setText(str(Path(folder) / (Path(self.root.text()).name or 'novy-projekt')))
        browse.clicked.connect(choose)
        layout.addWidget(browse)
        self.remember = QCheckBox('Použít tuto nadřazenou složku jako výchozí')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        layout.addWidget(QLabel('Cílová složka může být nová nebo existující prázdná. Lokální stav bude uložen vedle ní.'))
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Vytvořit a otevřít')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Zrušit')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.title.setFocus()

    def validate(self):
        if not self.title.text().strip() or not Path(self.root.text()).is_absolute():
            self.error.setText('Vyplňte název a absolutní cestu složky projektu.')
            return
        self.accept()


class CreationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.succeeded.emit(self.action())
        except CreationConflict as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('Operaci nelze dokončit. Ověřte cestu, práva a dostupné místo. '
                             'Připravená operace zůstává zachována; při dalším spuštění se obnoví.')


class CreationController:
    def __init__(self, window, service, succeeded, failed):
        self.window, self.service = window, service
        self.succeeded, self.failed = succeeded, failed
        self.workers = []
        self.busy = False
        self.smoke = None
        toolbar = window.addToolBar('Projekty')
        self.toolbar = toolbar
        toolbar.setMovable(False)
        self.button = QPushButton('Nový projekt…')
        self.resume = QPushButton('Dokončit přerušenou operaci projektu')
        self.resume.setVisible(False)
        self.status = QLabel('')
        toolbar.addWidget(self.button)
        toolbar.addWidget(self.resume)
        toolbar.addWidget(self.status)
        self.button.clicked.connect(self.dialog)
        self.resume.clicked.connect(self.recover)

    def dialog(self):
        if self.busy:
            return
        dialog = CreationDialog(self.window, self.service.default_projects_root())
        # Test-only input fills the real native widgets and submits their Save action.
        if self.smoke:
            title, root = self.smoke
            self.smoke = None
            dialog.title.setText(title)
            dialog.root.setText(root)
            QTimer.singleShot(0, dialog.validate)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        title, root, remember = dialog.title.text(), dialog.root.text(), dialog.remember.isChecked()
        dialog.deleteLater()
        if accepted:
            operation_id = str(uuid4())
            self.start(lambda: self.service.create(title, root, operation_id, remember_parent=remember))

    def recover(self):
        if not self.busy:
            self.start(self.service.recover)

    def start(self, action):
        self.busy = True
        self.button.setEnabled(False)
        self.resume.setEnabled(False)
        self.status.setText('  Provádím operaci projektu…')
        worker = CreationWorker(action, self.window)
        self.workers.append(worker)
        def success(receipt):
            self.status.setText('  Operace projektu dokončena.' if receipt else '')
            self.resume.setVisible(False)
            self.succeeded(receipt)
        def failure(message):
            self.status.setText('  Operace projektu nebyla dokončena.')
            self.resume.setVisible(True)
            self.failed(message)
        def finished():
            self.busy = False
            self.button.setEnabled(True)
            self.resume.setEnabled(True)
        worker.succeeded.connect(success)
        worker.failed.connect(failure)
        worker.finished.connect(finished)
        worker.start()

    def wait(self):
        for worker in self.workers:
            worker.wait()
