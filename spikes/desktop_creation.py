"""Native Qt creation dialog/controller: never accepts commands from JavaScript."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QLineEdit, QPushButton, QLabel, QVBoxLayout)

from spikes.project_creation import CreationConflict


class CreationDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Nový projekt')
        self.resize(600, 240)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(200)
        self.root = QLineEdit(str(Path.home() / 'novy-projekt'))
        form.addRow('Název projektu', self.title)
        form.addRow('Nová složka projektu', self.root)
        layout.addLayout(form)
        browse = QPushButton('Vybrat nadřazenou složku…')
        def choose():
            folder = QFileDialog.getExistingDirectory(self, 'Nadřazená složka', str(Path.home()))
            if folder:
                self.root.setText(str(Path(folder) / (Path(self.root.text()).name or 'novy-projekt')))
        browse.clicked.connect(choose)
        layout.addWidget(browse)
        layout.addWidget(QLabel('Cílová složka ještě nesmí existovat. Lokální stav bude uložen vedle ní.'))
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
            self.error.setText('Vyplňte název a absolutní cestu nové složky.')
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
        toolbar.setMovable(False)
        self.button = QPushButton('Nový projekt…')
        self.resume = QPushButton('Dokončit přerušené vytvoření')
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
        dialog = CreationDialog(self.window)
        # Test-only input fills the real native widgets and submits their Save action.
        if self.smoke:
            title, root = self.smoke
            self.smoke = None
            dialog.title.setText(title)
            dialog.root.setText(root)
            QTimer.singleShot(0, dialog.validate)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        title, root = dialog.title.text(), dialog.root.text()
        dialog.deleteLater()
        if accepted:
            operation_id = str(uuid4())
            self.start(lambda: self.service.create(title, root, operation_id))

    def recover(self):
        if not self.busy:
            self.start(self.service.recover)

    def start(self, action):
        self.busy = True
        self.button.setEnabled(False)
        self.resume.setEnabled(False)
        self.status.setText('  Připravuji projekt…')
        worker = CreationWorker(action, self.window)
        self.workers.append(worker)
        def success(receipt):
            self.status.setText('  Projekt připraven.' if receipt else '')
            self.resume.setVisible(False)
            self.succeeded(receipt)
        def failure(message):
            self.status.setText('  Vytvoření nebylo dokončeno.')
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
