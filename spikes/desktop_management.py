# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native single-OS-user administration, using the existing process token."""
import sqlite3
import os
import subprocess

from spikes.desktop_ui import ASSETS as BASE_ASSETS, DesktopHandler, HTML, CSS, JS
from spikes.administration import AccessDenied
from spikes.project_creation import ProjectCreation

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


class DesktopManagementHandler(DesktopHandler):
    assets = ASSETS
    post_paths = DesktopHandler.post_paths | {'/v1/administration',
        '/v1/federation/enroll',
        '/v1/federation/catalog/reconcile',
        '/v1/federation/content/reconcile',
        '/v1/federation/content/cancel',
        '/v1/federation/content/start-all',
        '/v1/federation/content/settings',
        '/v1/replications/status', '/v1/replications/sync',
        '/v1/backend-metrics/status', '/v1/backend-metrics/configure',
        '/v1/backend-metrics/refresh'}

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
        if self.path == '/v1/federation/catalog/reconcile':
            if not isinstance(request, dict) or set(request) != {'peer_id'}:
                return self.send_error(400)
            try:
                from spikes.federation_catalog import CatalogControl
                control = CatalogControl(
                    self.server.administration.node, deployment='desktop')
                control.synchronize(request['peer_id'])
                return self.reply(200, control.view())
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Katalog projektů se nepodařilo přenést; bezpečný stav je uložen pro opakování.'})
        if self.path in {'/v1/federation/content/reconcile',
                          '/v1/federation/content/cancel',
                          '/v1/federation/content/start-all',
                          '/v1/federation/content/settings'}:
            try:
                from spikes.federation_sync import ContentSyncControl
                control = ContentSyncControl(
                    self.server.administration.node, deployment='desktop')
                if self.path.endswith('/start-all'):
                    if request != {}: return self.send_error(400)
                    return self.reply(200, {
                        'batch': control.start_all(),
                        'content_sync_settings': control.settings(),
                        'content_sync_statuses': control.statuses()})
                if self.path.endswith('/settings'):
                    if (not isinstance(request, dict) or set(request) != {
                            'automatic_enabled', 'expected_revision'}):
                        return self.send_error(400)
                    settings = control.configure(**request)
                    return self.reply(200, {
                        'content_sync_settings': settings,
                        'content_sync_statuses': control.statuses()})
                if (not isinstance(request, dict)
                        or set(request) != {'peer_id', 'project_id'}):
                    return self.send_error(400)
                changed = (control.cancel(request['peer_id'], request['project_id'])
                           if self.path.endswith('/cancel') else
                           control.start(request['peer_id'], request['project_id']))
                return self.reply(200, {'changed': changed,
                                        'content_sync_statuses': control.statuses()})
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Obsah projektu se nepodařilo synchronizovat; bezpečný stav je uložen pro opakování.'})
        if self.path in {'/v1/replications/status', '/v1/replications/sync'}:
            actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
            try:
                from spikes.replication_control import ReplicationControl
                control = ReplicationControl(
                    self.server.administration.node, deployment='desktop')
                state = self.server.administration.request(actor, {'action': 'list'})
                if self.path == '/v1/replications/sync':
                    if (not isinstance(request, dict)
                            or set(request) != {'replication_id'}):
                        return self.send_error(400)
                    control.synchronize(request['replication_id'])
                    state = self.server.administration.request(actor, {'action': 'list'})
                return self.reply(200, {'statuses': control.statuses(
                    state['replications'], state['node_id'])})
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Synchronizaci se nepodařilo dokončit; '
                                               'aktuální stav je uložen pro bezpečné opakování.'})
        if self.path.startswith('/v1/backend-metrics/'):
            try:
                if self.path == '/v1/backend-metrics/status' and request == {}:
                    return self.reply(200, self.server.chat_service.account_metrics_status())
                if self.path == '/v1/backend-metrics/configure' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.configure_account_metrics(request))
                if self.path == '/v1/backend-metrics/refresh' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.refresh_account_metrics(request))
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error):
                return self.reply(422, {'error': 'Účetní přehled nelze načíst nebo uložit. '
                                       'Ověřte administrátorský klíč a lokální stav.'})
        if self.path != '/v1/administration':
            return super().dispatch(request)
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        try:
            administration = self.server.administration
            if not os.path.lexists(administration.node) and administration.repo.exists():
                return self.reply(422, {'error': 'Chybí původní node.json. Obnovte jej ze zálohy; identitu existující federace nelze nahradit.'})
            ProjectCreation(administration.node).initialize_node()
            result = self.server.administration.request(actor, request)
            result['projects'] = self.server.projects.catalog()
            from spikes.replication_control import ReplicationControl
            result['replication_statuses'] = ReplicationControl(
                administration.node, deployment='desktop').statuses(
                    result['replications'], result['node_id'])
            from spikes.federation_catalog import CatalogControl
            result.update(CatalogControl(
                administration.node, deployment='desktop').view())
            from spikes.federation_sync import ContentSyncControl
            result['content_sync_statuses'] = ContentSyncControl(
                administration.node, deployment='desktop').statuses()
            result['content_sync_settings'] = ContentSyncControl(
                administration.node, deployment='desktop').settings()
            return self.reply(200, result)
        except AccessDenied:
            return self.reply(403, {'error': 'Operace není povolena nebo se změnil registr. Načtěte správu znovu.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(422, {'error': 'Správa není dostupná. Ověřte konfiguraci uzlu a uložené údaje.'})
