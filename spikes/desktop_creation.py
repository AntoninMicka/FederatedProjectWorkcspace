# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Native worker/controller for node operations and startup recovery."""

from PySide6.QtCore import QThread, Signal

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
    def __init__(self, window, service, succeeded, failed, status_changed=None):
        self.window, self.service = window, service
        self.succeeded, self.failed = succeeded, failed
        self.status_changed = status_changed or (lambda _message, _can_retry: None)
        self.workers = []
        self.busy = False

    def recover(self):
        if not self.busy:
            self.start(self.service.recover)

    def start(self, action):
        self.busy = True
        self.status_changed('Provádím operaci projektu…', False)
        worker = CreationWorker(action, self.window)
        self.workers.append(worker)
        def success(receipt):
            self.status_changed('Operace projektu byla dokončena.' if receipt else '', False)
            self.succeeded(receipt)
        def failure(message):
            self.status_changed('Operace projektu nebyla dokončena.', True)
            self.failed(message)
        def finished():
            self.busy = False
        worker.succeeded.connect(success)
        worker.failed.connect(failure)
        worker.finished.connect(finished)
        worker.start()

    def wait(self):
        for worker in self.workers:
            worker.wait()
