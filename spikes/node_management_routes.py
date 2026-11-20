# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node management routes shared by the desktop and web handlers (AUDIT-B6-T1).

Before B-ODD-09 the desktop management handler and the web handler each kept a
copy of these routes. The copies differed only in the deployment name, the
acting identity and the web administrator check. The deployment and node path
now come from ``server.administration``; a handler supplies the actor and,
on the web, checks that the account is a node administrator before calling.

``/v1/federation/enroll`` is not shared on purpose: the desktop enrolls as a
client, while the web server accepts a client's enrollment.
"""
import sqlite3

from spikes.request_ownership import ProjectBusy

from spikes.administration import AccessDenied

CATALOG_PATHS = frozenset({'/v1/federation/catalog/reconcile'})
CONTENT_PATHS = frozenset({
    '/v1/federation/content/reconcile', '/v1/federation/content/cancel',
    '/v1/federation/content/start-all', '/v1/federation/content/settings'})
REPLICATION_PATHS = frozenset({'/v1/replications/status', '/v1/replications/sync'})
METRICS_PATHS = frozenset({
    '/v1/backend-metrics/status', '/v1/backend-metrics/configure',
    '/v1/backend-metrics/refresh'})
# Routes that only a node administrator may call on the web.
ADMIN_PATHS = CATALOG_PATHS | CONTENT_PATHS | REPLICATION_PATHS | METRICS_PATHS
SHARED_PATHS = ADMIN_PATHS | {'/v1/administration'}


def administration_view(server, actor, request):
    """Run one administration request and attach the node's federation state."""
    administration = server.administration
    node, deployment = administration.node, administration.deployment
    result = administration.request(actor, request)
    result['projects'] = server.projects.catalog()
    from spikes.replication_control import ReplicationControl
    result['replication_statuses'] = ReplicationControl(node, deployment=deployment).statuses(
        result['replications'], result['node_id'])
    from spikes.federation_catalog import CatalogControl
    result.update(CatalogControl(node, deployment=deployment).view())
    from spikes.federation_sync import ContentSyncControl
    content = ContentSyncControl(node, deployment=deployment)
    result['content_sync_statuses'] = content.statuses()
    result['content_sync_settings'] = content.settings()
    return result


class NodeManagementRoutes:
    """Mixin for a request handler with ``server.administration``."""

    def dispatch_node_management(self, request, actor):
        """Reply to one of ADMIN_PATHS; the caller checks the path first."""
        administration = self.server.administration
        node, deployment = administration.node, administration.deployment
        if self.path in CATALOG_PATHS:
            if not isinstance(request, dict) or set(request) != {'peer_id'}:
                return self.send_error(400)
            try:
                from spikes.federation_catalog import CatalogControl
                control = CatalogControl(node, deployment=deployment)
                control.synchronize(request['peer_id'])
                return self.reply(200, control.view())
            except AccessDenied:
                return self.send_error(403)
            except ProjectBusy:
                raise
            except Exception:
                return self.reply(409, {'error': 'Katalog projektů se nepodařilo přenést; '
                                                 'bezpečný stav je uložen pro opakování.'})
        if self.path in CONTENT_PATHS:
            try:
                from spikes.federation_sync import ContentSyncControl
                control = ContentSyncControl(node, deployment=deployment)
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
            except ProjectBusy:
                raise
            except Exception:
                return self.reply(409, {'error': 'Obsah projektu se nepodařilo synchronizovat; '
                                                 'bezpečný stav je uložen pro opakování.'})
        if self.path in REPLICATION_PATHS:
            try:
                from spikes.replication_control import ReplicationControl
                control = ReplicationControl(node, deployment=deployment)
                state = administration.request(actor, {'action': 'list'})
                if self.path == '/v1/replications/sync':
                    if (not isinstance(request, dict)
                            or set(request) != {'replication_id'}):
                        return self.send_error(400)
                    control.synchronize(request['replication_id'])
                    state = administration.request(actor, {'action': 'list'})
                return self.reply(200, {'statuses': control.statuses(
                    state['replications'], state['node_id'])})
            except AccessDenied:
                return self.send_error(403)
            except ProjectBusy:
                raise
            except Exception:
                return self.reply(409, {'error': 'Synchronizaci se nepodařilo dokončit; '
                                                 'aktuální stav je uložen pro bezpečné opakování.'})
        if self.path in METRICS_PATHS:
            try:
                service = self.server.chat_service
                if self.path == '/v1/backend-metrics/status' and request == {}:
                    return self.reply(200, service.account_metrics_status())
                if self.path == '/v1/backend-metrics/configure' and isinstance(request, dict):
                    return self.reply(200, service.configure_account_metrics(request))
                if self.path == '/v1/backend-metrics/refresh' and isinstance(request, dict):
                    return self.reply(200, service.refresh_account_metrics(request))
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error):
                return self.reply(422, {'error': 'Účetní přehled nelze načíst nebo uložit. '
                                                 'Ověřte administrátorský klíč a lokální stav.'})
        raise ValueError('Not a shared node management route: ' + self.path)
