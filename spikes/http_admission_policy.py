# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exact HTTP admission domains, shared by the server and browser.

An independent lane requires an ownership audit, not a read-like route name.
Unknown routes and query variants keep the conservative application domain.
"""

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
}

LANES = tuple(sorted({'application', *ROUTE_LANES.values()}))


def request_lane(path):
    return ROUTE_LANES.get(path, 'application') + '_lane'
