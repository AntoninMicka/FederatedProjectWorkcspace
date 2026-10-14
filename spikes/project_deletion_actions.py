# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared preview/confirm adapter for project removal and trash lifecycle."""
import hmac

from spikes.metadata import require, uuid
from spikes.project_deletion import ProjectDeletion, digest


class ProjectDeletionActions:
    def __init__(self, node_path):
        self.service = ProjectDeletion(node_path)
        self._previews = {}

    def _issue(self, kind, plan):
        key = (kind, plan.get('project_id'), plan.get('operation_id'))
        self._previews[key] = plan
        return plan

    def _consume(self, kind, plan):
        require(isinstance(plan, dict), 'Neplatný potvrzený náhled.')
        key = (kind, plan.get('project_id'), plan.get('operation_id'))
        issued = self._previews.get(key)
        require(issued == plan and isinstance(plan.get('preview_sha256'), str),
                'Náhled nebyl vydán tímto backendem nebo se změnil.')
        unsigned = dict(plan); supplied = unsigned.pop('preview_sha256')
        require(hmac.compare_digest(supplied, digest(unsigned)),
                'Digest náhledu se změnil.')

    def preview(self, request):
        require(isinstance(request, dict) and set(request) == {'project_id', 'mode'},
                'Neplatný požadavek na náhled odstranění.')
        return self._issue('delete', self.service.preview(**request))

    def confirm(self, request):
        require(isinstance(request, dict) and set(request) == {'preview', 'operation_id'},
                'Neplatné potvrzení odstranění.')
        uuid(request['operation_id']); self._consume('delete', request['preview'])
        return self.service.confirm(request['preview'], request['operation_id'])

    def trash(self):
        return {'projects': self.service.trash()}

    def restore_preview(self, request):
        require(isinstance(request, dict) and set(request) == {'operation_id'},
                'Neplatný požadavek na náhled obnovy.')
        return self._issue('restore', self.service.restore_preview(request['operation_id']))

    def restore_confirm(self, request):
        require(isinstance(request, dict) and set(request) == {'preview', 'operation_id'},
                'Neplatné potvrzení obnovy.')
        uuid(request['operation_id']); self._consume('restore', request['preview'])
        return self.service.restore(request['preview']['operation_id'], request['operation_id'])

    def purge_preview(self, request):
        require(isinstance(request, dict) and set(request) == {'operation_id'},
                'Neplatný požadavek na náhled definitivního výmazu.')
        return self._issue('purge', self.service.purge_preview(request['operation_id']))

    def purge_confirm(self, request):
        require(isinstance(request, dict) and set(request) == {'preview', 'operation_id'},
                'Neplatné potvrzení definitivního výmazu.')
        uuid(request['operation_id']); self._consume('purge', request['preview'])
        return self.service.purge(request['preview'], request['operation_id'])
