# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exact HTTP admission domains, shared by the server and browser.

An independent lane requires an ownership audit, not a read-like route name.
Unknown routes and query variants keep the conservative application domain.
"""

# Each value identifies the exact request field containing the project scope.
# These handlers use request-local services and existing journal/CAS writers;
# they do not replace server.projects or initialize shared server services.
PROJECT_ROUTES = {
    '/v1/projects/open': None,
    '/v1/artifacts/preview': None,
    '/v1/artifacts/history/list': None,
    '/v1/artifacts/history/compare': None,
    '/v1/projects/conflicts/list': None,
    '/v1/projects/conflicts/preview': None,
    '/v1/projects/conflicts/confirm': 'resolution',
    '/v1/projects/conflicts/local-preview': None,
    '/v1/projects/conflicts/local-confirm': 'preview',
    '/v1/artifacts/editor/open': None,
    '/v1/artifacts/editor/save': 'document',
    '/v1/artifacts/editor/validate-plan': None,
    '/v1/artifacts/editor/plan-item/open': None,
    '/v1/artifacts/editor/plan-item/delete/preview': None,
    '/v1/artifacts/editor/plan-item/save': 'item',
    '/v1/artifacts/editor/plan-item/create': 'item',
    '/v1/artifacts/editor/plan-item/dependencies': 'item',
    '/v1/artifacts/editor/plan-item/delete': 'item',
    '/v1/artifacts/delete/preview': None,
    '/v1/artifacts/delete/confirm': None,
    '/v1/artifacts/git/status': None,
    '/v1/artifacts/git/preview': None,
    '/v1/artifacts/git/stage': 'request',
    '/v1/artifacts/git/commit': 'preview',
}

ROUTE_LANES = {
    '/v1/diagnostics/status': 'diagnostics',
    '/v1/node-telemetry/status': 'telemetry',
    '/v1/chat/availability': 'availability',
    '/v1/tasks/run-control': 'availability',
    '/v1/roadmap-refinement/list': 'review',
    '/v1/roadmap-refinement/detail': 'review',
    '/v1/roadmap-refinement/reconcile/preview': 'review',
    # Immutable committed Git snapshots and atomically published registration.
    '/v1/projects': 'catalog',
    # All HTTP owners of the selected deck, public state and session identity.
    # This is a serialized mutating domain, not a read-only exemption.
    '/v1/presentations/use': 'presentation',
    '/v1/presentation/status': 'presentation',
    '/v1/presentation/control': 'presentation',
    '/v1/presentation/public': 'presentation',
    # Keep inbound requests serialized, including replay check -> publication
    # -> durable response. Project publication still owns its journal lock.
    '/v1/federation/content-sync': 'content_sync',
    **dict.fromkeys(PROJECT_ROUTES, 'project'),
}

LANES = tuple(sorted({'application', *ROUTE_LANES.values()} - {'project'}))


def request_lane(path):
    return ROUTE_LANES.get(path, 'application') + '_lane'
