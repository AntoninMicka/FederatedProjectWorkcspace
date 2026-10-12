# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Authorized shared adapter for the NotebookLM preview/plan/confirm workflow."""
from pathlib import Path
from uuid import uuid4

from spikes.notebooklm_project_import import NotebookLMProjectImport
from spikes.project_creation import CreationConflict, ProjectCreation, check
from spikes.projects import directory


class NotebookLMImportActions:
    """Resolve server paths or exact desktop capabilities before calling the importer."""

    def __init__(self, node_path, *, projects_root=None, desktop_capabilities=False):
        self.service = NotebookLMProjectImport(node_path)
        self.creator = ProjectCreation(node_path)
        self.projects_root = Path(projects_root) if projects_root is not None else None
        self.desktop_capabilities = desktop_capabilities
        self._archives = {}
        self._targets = {}
        self._plans = {}

    def register_archive(self, path):
        check(self.desktop_capabilities, 'Výběr archivu je dostupný pouze v desktopu.')
        path = Path(path)
        check(path.is_absolute() and path == path.resolve() and path.is_file(),
              'Vybraný archiv musí být běžný soubor bez symlinků.')
        token = str(uuid4())
        self._archives[token] = path
        return {'archive_capability': token, 'archive_label': path.name}

    def register_target(self, root, operation_id):
        check(self.desktop_capabilities, 'Výběr cíle je dostupný pouze v desktopu.')
        check(isinstance(operation_id, str), 'Neplatné ID importní operace.')
        root = Path(root)
        check(root.is_absolute() and root == root.resolve(),
              'Vybrané umístění musí být absolutní a nesmí vést přes symlink.')
        try:
            directory(root)
        except ValueError as exc:
            raise CreationConflict(str(exc)) from exc
        check(not list(root.iterdir()), 'Existující cílová složka musí být prázdná.')
        token = str(uuid4())
        self._targets[token] = (operation_id, root)
        return {'target_capability': token, 'target_label': str(root),
                'operation_id': operation_id}

    def _archive(self, archive_path, archive_capability):
        if archive_capability is not None:
            check(self.desktop_capabilities and archive_path is None
                  and isinstance(archive_capability, str),
                  'Neplatná capability NotebookLM archivu.')
            path = self._archives.get(archive_capability)
            check(path is not None, 'Capability NotebookLM archivu vypršela.')
            return path
        check(not self.desktop_capabilities and isinstance(archive_path, str)
              and bool(archive_path.strip()),
              'Serverový import vyžaduje cestu k archivu na tomto uzlu.')
        return Path(archive_path)

    def _target(self, operation_id, capability):
        if capability is not None:
            check(self.desktop_capabilities and isinstance(capability, str),
                  'Neplatná capability cíle NotebookLM importu.')
            selected = self._targets.get(capability)
            check(selected is not None and selected[0] == operation_id,
                  'Capability cíle nepatří této operaci nebo vypršela.')
            return selected[1]
        parent = self.projects_root or self.creator.default_projects_root()
        return parent / ('projekt-' + operation_id)

    def preview(self, request):
        check(isinstance(request, dict) and set(request) == {
            'archive_path', 'archive_capability'},
            'Neplatný požadavek na přehled NotebookLM archivu.')
        return self.service.preview(self._archive(
            request['archive_path'], request['archive_capability']))

    def plan(self, request):
        check(isinstance(request, dict) and set(request) == {
            'archive_path', 'archive_capability', 'selection_digest', 'privacy',
            'operation_id', 'target_capability'},
            'Neplatný požadavek na plán NotebookLM importu.')
        allowed = {'public', 'project', 'confidential'}
        if self.desktop_capabilities:
            allowed.add('local-only')
        check(request['privacy'] in allowed,
              'Zvolená privacy není na tomto uzlu povolena.')
        target = self._target(request['operation_id'], request['target_capability'])
        plan = self.service.plan(
            self._archive(request['archive_path'], request['archive_capability']),
            request['selection_digest'], target, request['privacy'], request['operation_id'])
        self._plans[request['operation_id']] = plan
        return plan

    def confirm(self, request, *, author_id=None):
        check(isinstance(request, dict) and set(request) == {
            'archive_path', 'archive_capability', 'plan'},
            'Neplatné potvrzení NotebookLM importu.')
        plan = request['plan']
        check(isinstance(plan, dict) and self._plans.get(plan.get('operation_id')) == plan,
              'Plán NotebookLM importu nebyl vydán tímto backendem nebo se změnil.')
        Path(plan['target_root']).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.service.confirm(
            self._archive(request['archive_path'], request['archive_capability']),
            plan, author_id=author_id)
