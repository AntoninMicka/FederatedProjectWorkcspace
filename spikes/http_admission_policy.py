# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exact HTTP admission domains, shared by the server and browser.

An independent lane requires an ownership audit, not a read-like route name.
Unknown routes and query variants keep the conservative application domain.
"""

# Each value identifies the exact request field containing the project scope.
# These handlers use request-local work or immutable startup service bindings
# and existing journal/CAS writers;
# they do not replace server.projects or initialize shared server services.
PROJECT_ROUTES = {
    '/v1/projects/open': None,
    '/v1/sources/import': 'source',
    '/v1/outputs/definitions': None,
    '/v1/presentations/open': None,
    '/v1/presentations/save': 'document',
    '/v1/presentations/export/preview': None,
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

# Provider configuration, lifecycle and dependent services retain one owner.
# Exact audited paths: no prefix classification occurs at request time.
PROVIDER_ROUTES = frozenset({
    '/v1/administration',
    '/v1/atlascloud/configure',
    '/v1/atlascloud/models',
    '/v1/atlascloud/remove',
    '/v1/atlascloud/status',
    '/v1/autonomy/activate',
    '/v1/autonomy/advance',
    '/v1/autonomy/approve',
    '/v1/autonomy/attach',
    '/v1/autonomy/cancel',
    '/v1/autonomy/detach',
    '/v1/autonomy/pause',
    '/v1/autonomy/pause-all',
    '/v1/autonomy/prepare',
    '/v1/autonomy/replace',
    '/v1/autonomy/research/draft',
    '/v1/autonomy/research/prepare',
    '/v1/autonomy/resume',
    '/v1/autonomy/resume-all',
    '/v1/autonomy/revision/confirm',
    '/v1/autonomy/revision/propose',
    '/v1/autonomy/search/edit',
    '/v1/autonomy/search/prepare',
    '/v1/autonomy/send-now',
    '/v1/autonomy/status',
    '/v1/backend-catalog/reset',
    '/v1/backend-catalog/status',
    '/v1/backend-metrics/configure',
    '/v1/backend-metrics/refresh',
    '/v1/backend-metrics/status',
    '/v1/chat/archive',
    '/v1/chat/assign',
    '/v1/chat/configure',
    '/v1/chat/delete/confirm',
    '/v1/chat/delete/preview',
    '/v1/chat/models',
    '/v1/chat/orchestration',
    '/v1/chat/output',
    '/v1/chat/preferences',
    '/v1/chat/response-language',
    '/v1/chat/send',
    '/v1/chat/send-stream',
    '/v1/chat/snapshot',
    '/v1/chat/status',
    '/v1/chat/test',
    '/v1/direct/configure',
    '/v1/direct/models',
    '/v1/direct/remove',
    '/v1/direct/status',
    '/v1/external/cancel',
    '/v1/external/configure',
    '/v1/external/confirm',
    '/v1/external/models',
    '/v1/external/preview',
    '/v1/external/propose',
    '/v1/external/request',
    '/v1/external/send',
    '/v1/external/send-stream',
    '/v1/external/status',
    '/v1/extraction/preview',
    '/v1/extraction/publish',
    '/v1/extraction/status',
    '/v1/google-drive/authorize',
    '/v1/google-drive/configure',
    '/v1/google-drive/confirm',
    '/v1/google-drive/preview',
    '/v1/google-drive/recover',
    '/v1/google-drive/status',
    '/v1/media/comfyui/configure',
    '/v1/media/confirm',
    '/v1/media/openai/configure',
    '/v1/media/preview',
    '/v1/media/publish',
    '/v1/media/status',
    '/v1/metadata-suggestions/preview',
    '/v1/metadata-suggestions/publish',
    '/v1/metadata-suggestions/status',
    '/v1/model-catalog/import',
    '/v1/model-catalog/knowledge',
    '/v1/model-selection/preferences',
    '/v1/model-selection/status',
    '/v1/node-telemetry/configure',
    '/v1/node-telemetry/run',
    '/v1/notebooklm/confirm',
    '/v1/notebooklm/plan',
    '/v1/notebooklm/preview',
    '/v1/projects/create/confirm',
    '/v1/projects/create/preview',
    '/v1/projects/delete/confirm',
    '/v1/projects/delete/preview',
    '/v1/projects/delete/purge/confirm',
    '/v1/projects/delete/purge/preview',
    '/v1/projects/delete/restore/confirm',
    '/v1/projects/delete/restore/preview',
    '/v1/projects/delete/trash',
    '/v1/projects/repair/check',
    '/v1/projects/repair/confirm',
    '/v1/projects/repair/preview',
    '/v1/projects/repair/receipt',
    '/v1/publication-cms/configure',
    '/v1/publication-cms/deployment/configure',
    '/v1/publication-cms/deployment/confirm',
    '/v1/publication-cms/deployment/preview',
    '/v1/publication-cms/deployment/status',
    '/v1/publication-cms/generate',
    '/v1/publication-cms/preview',
    '/v1/publication-cms/status',
    '/v1/search/configure',
    '/v1/search/status',
    '/v1/search/test',
    '/v1/summary/preview',
    '/v1/summary/publish',
    '/v1/summary/status',
    '/v1/tasks/artifact',
    '/v1/tasks/cancel',
    '/v1/tasks/external/cancel',
    '/v1/tasks/external/confirm',
    '/v1/tasks/external/preview',
    '/v1/tasks/file-edit/confirm',
    '/v1/tasks/file-edit/preview',
    '/v1/tasks/list',
    '/v1/tasks/presentation/confirm',
    '/v1/tasks/public-source/confirm',
    '/v1/tasks/public-source/preview',
    '/v1/tasks/public-source/result',
    '/v1/tasks/route',
    '/v1/tasks/route-stream',
    '/v1/tasks/search/confirm',
    '/v1/tasks/search/preview',
    '/v1/tasks/search/query',
    '/v1/workflows/creator/dispatch',
    '/v1/workflows/opponent/dispatch',
    '/v1/workflows/opponent/prepare',
    '/v1/workflows/prepare',
    '/v1/workflows/publish',
    '/v1/workflows/status',
})

# Listing administration has its own persistent registry/sync-store owners.
# Every mutation and unknown action conservatively retains the provider owner.
ACTION_LANES = {
    '/v1/administration': {'list': 'node_status'},
    # Catalog discovery and immutable extension packages do not own queue
    # publication/review state. Project/index and SQLite owners still apply.
    '/v1/ide-bridge/connection/exchange': {
        'status': 'ide_status', 'extension-update': 'ide_update',
    },
}

# Julia owns its worker/error maps and durable run journal independently of
# providers and monitoring. Keep all twelve HTTP operations serialized together;
# status/cancel/reconcile are not classified as pure reads.
JULIA_ROUTES = frozenset({
    '/v1/julia/cancel',
    '/v1/julia/definitions',
    '/v1/julia/editor/delete/confirm',
    '/v1/julia/editor/delete/preview',
    '/v1/julia/editor/open',
    '/v1/julia/editor/save',
    '/v1/julia/execute',
    '/v1/julia/output',
    '/v1/julia/preview',
    '/v1/julia/publish',
    '/v1/julia/reconcile',
    '/v1/julia/status',
})

# Monitoring lifecycle, publication and sidecar state keep one serialized owner.
# The manual public RSS cache has no project/monitoring state and owns its lane.
MONITORING_ROUTES = frozenset({
    '/v1/monitoring/block-compose',
    '/v1/monitoring/block-configure',
    '/v1/monitoring/block-process',
    '/v1/monitoring/block-publish',
    '/v1/monitoring/block-release',
    '/v1/monitoring/block-task-run',
    '/v1/monitoring/block-tick',
    '/v1/monitoring/blocks',
    '/v1/monitoring/blocks-save',
    '/v1/monitoring/block-delete',
    '/v1/monitoring/legacy-delete-preview',
    '/v1/monitoring/legacy-delete',
    '/v1/monitoring/cancel',
    '/v1/monitoring/correct',
    '/v1/monitoring/definition-save',
    '/v1/monitoring/definitions',
    '/v1/monitoring/filter-preview',
    '/v1/monitoring/finding-transition',
    '/v1/monitoring/migration-apply',
    '/v1/monitoring/migration-cancel',
    '/v1/monitoring/migration-inventory',
    '/v1/monitoring/migration-preview',
    '/v1/monitoring/migration-resume',
    '/v1/monitoring/pool-view',
    '/v1/monitoring/presentation',
    '/v1/monitoring/publish',
    '/v1/monitoring/retry',
    '/v1/monitoring/rss-configure',
    '/v1/monitoring/rss-reconcile',
    '/v1/monitoring/rss-status',
    '/v1/monitoring/rss-tick',
    '/v1/monitoring/run',
    '/v1/monitoring/save',
    '/v1/monitoring/synthesis-freshness',
    '/v1/monitoring/synthesis-run',
    '/v1/monitoring/synthesis-trace',
    '/v1/monitoring/view',
    '/v1/monitoring/output',
    '/v1/monitoring/workflow-run',
    '/v1/monitoring/workflow-save',
})
RSS_SOURCE_ROUTES = frozenset({
    '/v1/rss-sources/refresh',
    '/v1/rss-sources/view',
    '/v1/rss-sources/save',
    '/v1/rss-sources/import-preview',
})

# Bridge mappings, mailbox/review and queue publication share one owner.
IDE_QUEUE_ROUTES = frozenset({
    '/v1/ide-bridge/connection/create',
    '/v1/ide-bridge/connection/exchange',
    '/v1/ide-bridge/connection/map',
    '/v1/ide-bridge/connection/revoke',
    '/v1/ide-bridge/connections',
    '/v1/ide-bridge/create',
    '/v1/ide-bridge/exchange',
    '/v1/ide-bridge/review',
    '/v1/ide-bridge/revoke',
    '/v1/ide-bridge/status',
    '/v1/ide-queue/publish',
    '/v1/task-queue',
})

# Refinement reads can initialize/migrate proposals; decisions/apply share that
# same durable review lifecycle. Source references own no live project plan.
REFINEMENT_ROUTES = frozenset({
    '/v1/roadmap-refinement/list',
    '/v1/roadmap-refinement/detail',
    '/v1/roadmap-refinement/reconcile/preview',
    '/v1/roadmap-refinement/decide',
    '/v1/roadmap-refinement/decide-all',
    '/v1/roadmap-refinement/apply',
})
REFERENCE_ROUTES = frozenset({'/v1/document-patterns', '/v1/roadmap/graph'})

# Node preferences share mutable application-access state. Network transfers
# never own their control/status domain; native journals/flocks own correctness.
NODE_PREFERENCE_ROUTES = frozenset({
    '/v1/application-access', '/v1/counter', '/v1/gamepad/settings',
    '/v1/gamepad/status', '/v1/session', '/v1/user-profile',
})
FEDERATION_CONTROL_ROUTES = frozenset({
    '/v1/federation/content/cancel', '/v1/federation/content/reconcile',
    '/v1/federation/content/settings', '/v1/federation/content/start-all',
    '/v1/replications/status',
})
FEDERATION_TRANSFER_LANES = {
    '/v1/federation/catalog/reconcile': 'catalog_transfer',
    '/v1/replications/sync': 'replication_transfer',
    '/v1/federation/enroll': 'enrollment',
}

# These service domains acquire admission after authentication/body parsing.
SERVICE_ROUTES = (JULIA_ROUTES | MONITORING_ROUTES | RSS_SOURCE_ROUTES
                  | IDE_QUEUE_ROUTES | REFINEMENT_ROUTES | REFERENCE_ROUTES
                  | NODE_PREFERENCE_ROUTES | FEDERATION_CONTROL_ROUTES
                  | frozenset(FEDERATION_TRANSFER_LANES))

# Unknown paths retain conservative admission. Every declared JSON route now
# has an audited domain; this does not remove native serialization or recovery.
APPLICATION_ROUTES = frozenset()

STREAM_ROUTES = frozenset({
    '/v1/chat/send-stream', '/v1/tasks/route-stream', '/v1/external/send-stream',
})

ROUTE_LANES = {
    '/v1/diagnostics/status': 'diagnostics',
    '/v1/node-telemetry/status': 'telemetry',
    '/v1/chat/availability': 'availability',
    '/v1/tasks/run-control': 'availability',
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
    **dict.fromkeys(PROVIDER_ROUTES, 'provider'),
    **dict.fromkeys(JULIA_ROUTES, 'julia'),
    **dict.fromkeys(MONITORING_ROUTES, 'monitoring'),
    **dict.fromkeys(RSS_SOURCE_ROUTES, 'rss_sources'),
    **dict.fromkeys(IDE_QUEUE_ROUTES, 'ide_queue'),
    **dict.fromkeys(REFINEMENT_ROUTES, 'review'),
    **dict.fromkeys(REFERENCE_ROUTES, 'reference'),
    **dict.fromkeys(NODE_PREFERENCE_ROUTES, 'node_preferences'),
    **dict.fromkeys(FEDERATION_CONTROL_ROUTES, 'federation_control'),
    **FEDERATION_TRANSFER_LANES,
    **dict.fromkeys(APPLICATION_ROUTES, 'application'),
    # Peer protocols validate their own authentication/body before native writes.
    # Give each protocol bounded capacity without owning unrelated UI domains.
    '/v1/federation/probe': 'peer_probe',
    '/v1/federation/catalog': 'peer_catalog',
    '/v1/federation/content-state': 'peer_state',
    '/v1/federation/replicate': 'peer_replication',
}

LANES = tuple(sorted({'application', *ROUTE_LANES.values(),
                     *(lane for actions in ACTION_LANES.values() for lane in actions.values())} - {'project'}))


def request_lane(path, request=None):
    action = request.get('action') if isinstance(request, dict) else None
    if isinstance(action, str) and action in ACTION_LANES.get(path, {}):
        return ACTION_LANES[path][action] + '_lane'
    return ROUTE_LANES.get(path, 'application') + '_lane'


def validate_route_ownership(paths):
    missing = set(paths) - set(ROUTE_LANES)
    if missing:
        raise ValueError("HTTP routes require an ownership audit: " + ", ".join(sorted(missing)))
