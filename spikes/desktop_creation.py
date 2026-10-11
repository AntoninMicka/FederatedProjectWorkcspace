# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Native worker/controller for node operations and startup recovery."""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from spikes.project_creation import CreationConflict


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
        except ValueError as exc:
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
        toolbar = window.addToolBar('Projekty')
        self.toolbar = toolbar
        toolbar.setMovable(False)
        self.resume = QPushButton('Dokončit přerušenou operaci projektu')
        self.resume.setVisible(False)
        self.status = QLabel('')
        toolbar.addWidget(self.resume)
        toolbar.addWidget(self.status)
        self.resume.clicked.connect(self.recover)

    def recover(self):
        if not self.busy:
            self.start(self.service.recover)

    def start(self, action):
        self.busy = True
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
            self.resume.setEnabled(True)
        worker.succeeded.connect(success)
        worker.failed.connect(failure)
        worker.finished.connect(finished)
        worker.start()

    def wait(self):
        for worker in self.workers:
            worker.wait()
