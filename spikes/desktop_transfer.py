# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Session-only native transfer controller behind the shared federation form."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal

from spikes.deployment_targets import DeploymentTargets
from spikes.git_transfer import transfer
from spikes.projects import Projects
from spikes.transfer_outbox import pending_operation


class TransferWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.done.emit(True, self.action())
        except Exception as exc:
            self.done.emit(False, 'Operace selhala: ' + str(exc))


class FederationTransfer(QObject):
    """Keep SSH/Git work native while exposing only bounded form data to WebEngine."""

    def __init__(self, node, *, configuration_callback=None, progress_callback=None,
                 finished_callback=None, parent=None):
        super().__init__(parent)
        self.node = node
        self.configuration_callback = configuration_callback or (lambda _configuration: None)
        self.progress_callback = progress_callback or (lambda _message: None)
        self.finished_callback = finished_callback or (lambda _success, _message: None)
        self.worker = None
        self.token = None
        self.projects = []
        self.targets = []
        self.pending = None
        self.pending_selection = None

    def open(self):
        if self.worker and self.worker.isRunning():
            self.progress_callback('Přenos právě probíhá; stránku nelze opustit.')
            return
        self.projects = [item for item in Projects(self.node).catalog() if item['available']]
        self.targets = DeploymentTargets(self.node).load()
        self.token = str(uuid4())
        self.pending = None
        self.pending_selection = None
        root = Path(self.node).absolute().parent / ('.' + Path(self.node).name + '.network')
        targets = []
        for index, target in enumerate(self.targets):
            targets.append({
                'index': index,
                'label': target['container'] + ' — ' + target['endpoint'],
                'container': target['container'],
                'host': target['host'],
                'ca': str(root / (target['node_id'] + '-ca.pem')),
            })
        self.configuration_callback({
            'token': self.token,
            'projects': [{'index': index, 'id': item['id'], 'title': item['title']}
                         for index, item in enumerate(self.projects)],
            'targets': targets,
        })

    def _selection(self, request):
        if (not isinstance(request, dict)
                or set(request) != {'token', 'project', 'target', 'ca', 'confirmed'}
                or request.get('token') != self.token
                or request.get('confirmed') is not True
                or not isinstance(request.get('project'), int)
                or isinstance(request.get('project'), bool)
                or not isinstance(request.get('target'), int)
                or isinstance(request.get('target'), bool)
                or not isinstance(request.get('ca'), str)
                or not request['ca'] or len(request['ca']) > 4096 or '\0' in request['ca']
                or not 0 <= request['project'] < len(self.projects)
                or not 0 <= request['target'] < len(self.targets)):
            raise ValueError('Výběr přenosu už neodpovídá aktuálnímu formuláři.')
        current_projects = [item for item in Projects(self.node).catalog() if item['available']]
        current_targets = DeploymentTargets(self.node).load()
        if current_projects != self.projects or current_targets != self.targets:
            raise ValueError('Seznam projektů nebo federačních uzlů se změnil; načtěte stránku znovu.')
        return self.projects[request['project']], self.targets[request['target']]

    def start(self, request):
        if self.worker and self.worker.isRunning():
            return
        project, target = self._selection(request)
        selection = (project['id'], target['node_id'], request['ca'])
        if self.pending_selection is not None and selection != self.pending_selection:
            raise ValueError('Opakování musí použít stejný projekt, uzel a veřejnou CA.')
        if self.pending is None:
            self.pending = pending_operation(self.node, project['id'], target['node_id']) or str(uuid4())
            self.pending_selection = selection
        values = (target, project['id'], self.pending, request['ca'])
        self.progress_callback('Ověřuji veřejnou historii a přenáším nativní Git bundle…')
        self.worker = TransferWorker(lambda: transfer(self.node, *values), self)
        self.worker.done.connect(self.finished_callback)
        self.worker.start()

    def wait(self):
        if self.worker:
            self.worker.wait()
