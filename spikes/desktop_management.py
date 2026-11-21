# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native single-OS-user administration, using the existing process token."""
import sqlite3
from spikes.request_ownership import ProjectBusy
import os
import subprocess

from spikes.desktop_ui import ASSETS as BASE_ASSETS, DesktopHandler, HTML, CSS, JS
from spikes.administration import AccessDenied
from spikes.project_creation import ProjectCreation
from spikes.node_management_routes import ADMIN_PATHS, NodeManagementRoutes, administration_view

DESKTOP_BOOTSTRAP = '''document.body.dataset.runtime='desktop';
for(const id of ['settings-cms-tab','settings-access-tab','settings-profile-tab','settings-federation-tab',
 'backend-metrics','backend-metrics-indicator','openai-resource-provider','presenter-fullscreen',
 'federation-tab','resource-runtime-policy'])document.getElementById(id).hidden=false;
document.querySelector('[data-settings-item="settings-profile-tab"]').hidden=false;
document.querySelector('[data-settings-item="settings-access-tab"]').hidden=false;
document.getElementById('project-location-controls').hidden=false;
document.getElementById('open-notebooklm-import').hidden=false;
document.getElementById('sidebar-register-project').hidden=false;
'''

# HTML and CSS are exactly the same assets served by the browser deployment.
# The bootstrap only declares capabilities of this trusted single-user node.
ASSETS = {**BASE_ASSETS,
          '/': ('text/html; charset=utf-8', HTML),
          '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', DESKTOP_BOOTSTRAP + JS)}


def node_admin():
    """The trusted local desktop acts as the node administrator."""
    return {'id': None, 'node_role': 'federation-admin', 'memberships': {}}


class DesktopManagementHandler(NodeManagementRoutes, DesktopHandler):
    reserve_ui_worker = True
    assets = ASSETS

    def do_GET(self):
        if self.path in self.assets:
            self.server.describe_request(self.request, 'ui-assets', 'serving')
            return self._do_GET()
        return super().do_GET()

    post_paths = DesktopHandler.post_paths | {'/v1/administration', '/v1/federation/enroll'} | ADMIN_PATHS

    def dispatch(self, request):
        if self.path == '/v1/federation/enroll':
            if (not isinstance(request, dict)
                    or set(request) != {'operation_id', 'server_node_id',
                                        'access_key'}):
                return self.send_error(400)
            try:
                from spikes.federation_enrollment import enroll
                result = enroll(
                    self.server.administration.node, request['server_node_id'],
                    request['access_key'], operation_id=request['operation_id'])
                result['projects'] = self.server.projects.catalog()
                return self.reply(200, result)
            except AccessDenied:
                return self.reply(403, {'error': 'Server přihlášení klienta odmítl.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Přihlášení k serveru se nepodařilo. Ověřte TLS, účet a identitu uzlu.'})
        if self.path in ADMIN_PATHS:
            return self.dispatch_node_management(request, node_admin())
        if self.path != '/v1/administration':
            return super().dispatch(request)
        try:
            administration = self.server.administration
            if not os.path.lexists(administration.node) and administration.repo.exists():
                return self.reply(422, {'error': 'Chybí původní node.json. Obnovte jej ze zálohy; identitu existující federace nelze nahradit.'})
            ProjectCreation(administration.node).initialize_node()
            return self.reply(200, administration_view(self.server, node_admin(), request))
        except AccessDenied:
            return self.reply(403, {'error': 'Operace není povolena nebo se změnil registr. Načtěte správu znovu.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(422, {'error': 'Správa není dostupná. Ověřte konfiguraci uzlu a uložené údaje.'})
