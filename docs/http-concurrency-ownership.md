<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# HTTP concurrency: ownership and recovery audit

Local continuation of [the 9 November handoff](../HANDOFF_HTTP_CONCURRENCY.txt).
Source baseline: `a36b68c7d36afd9d16cc6a141d5bc3b6e39256d6`,
`feature/rss-direct-pilot`. The two changes described as uncommitted in that
historical handoff are present in this baseline. This document records source
design and evidence, not a second Workspace plan or human acceptance.

The synchronized host project is `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
repository `https://github.com/AntoninMicka/FederatedProjectWorkcspace.git`,
export revision `5e9de351ac5e6ec033066a10eba2309fbbaf57cc1a3f9799478c172cd6025a39`,
Workspace commit `f4a7f0618906d0e7b874bd2c283069a6854c3d43`.
Readback reported `stale=false`, synchronized at `2026-11-09T22:27:27.181Z`.
The user explicitly continued the HTTP repair on this existing source branch.
This does not reopen the historically accepted `OPS-WEB-CONCURRENCY-01` batch
or accept the currently open MON-08 work.

## Ownership inventory and implemented boundary

The exact route table in
[`http_admission_policy.py`](../spikes/http_admission_policy.py) is shared by
HTTP handlers and the generated browser admission script. Query variants and
unknown endpoints use the conservative application domain; no classification
by suffix such as `status`, `view` or `preview` is permitted.

| Domain | Exact operations | Owners and effects |
| --- | --- | --- |
| Catalog | `/v1/projects`, including `details=true` | `Projects.list/catalog` read registered configuration and committed Git metadata; catalog pins each project's HEAD, validates it and checks HEAD again. It can return an unavailable row on concurrent change. It does not initialize Workspace, journal or index. Web account authentication uses `authenticate_readonly`; project membership filtering remains mandatory. This is not an atomic snapshot across all projects. |
| Presentation | `/v1/presentation/status`, `/control`, `/public`, `/v1/presentations/use` | One serialized owner for selected deck, session deck/identity and public state. Even the public poll assigns process state. `status` can start or finish a session; control can record a shown slide. Session persistence uses existing SQLite transactions; finishing a session publishes through Workspace. These are **not** generally read-only routes. |
| Content receive | `/v1/federation/content-sync` | Dedicated serialized HTTP lane; `SyncReceiver` also owns a nonblocking node-local receive `flock` over validation, inbound replay check, publication and persisted response. The latter protects direct callers and separate listeners, including `ProbeHandler`, which dispatches peer protocols directly. The outbound lifecycle uses its existing **different** lock so a node can receive while awaiting its peer. |
| Existing independent domains | Exact telemetry, diagnostics, availability/control and roadmap review routes in the table | Preserve existing authorization, read-only schema checks, process locks and domain contracts. Their previous assignment is unchanged. |
| Application fallback | Every remaining route, including provider dispatch/streams, project writes/open, node administration, monitoring, imports, configuration and recovery | Retains serialized HTTP admission until its shared state is audited. This change does **not** claim that removing this last shared lane is safe. |

Concrete hazards found during the audit:

- `Projects.workspace()` constructs `Workspace`, initializing its journal/index;
  calling `open` is not the same as reading catalog metadata.
  `Workspace._read_locked()` can also rebuild a stale index while reading.
- `ChatService.status()` calls `ThreadLifecycle.recover_pending()` and opens
  mutable stores. It cannot simply be declared a parallel read.
- `ContentSyncControl.statuses()` initializes the sync schema and can persist
  `cancelled` for an interrupted manual task. Its `settings()` also opens the
  schema-initializing connection.
- Normal web `Administration.authenticate()` can bootstrap/migrate the registry
  under `Administration.locked()`. The audited catalog/presentation routes now
  use the existing read-only authentication path instead.
- Browser locks alone do not protect native clients or peer receivers. A
  receiver's replay/publication ownership must exist below the HTTP adapter.

The fallback still contains several different owners; existing locks are
evidence to reuse, not proof that every entry can immediately run independently:

| Remaining route group | Persistent/process ownership that must be preserved |
| --- | --- |
| Project open, artifact/editor/plan/history and publication | Workspace journal `writer.lock`, operation receipts, Git HEAD/CAS and index projection. Reads may initialize or repair the projection. |
| Administration, enrollment, project create/delete/restore and registration | Administration registry `flock` and credential transactions; ProjectCreation's separate node creation lock, intents and registration publication. Deletion/restore must retain their existing lifecycle. |
| Chat, backend configuration, provider streams and task/workflow runs | `ChatService` request identity uses `ContextVar`; backend configuration and stream controls have their own locks. `ChatThreads` uses SQLite transactions, including `BEGIN IMMEDIATE`; status also invokes lifecycle recovery. A request may wait on a provider while retaining HTTP ownership. The locks do not alone prove that the entire route family can be split. |
| Task queue and IDE handoff | TaskQueue locks by project/account and coordinates Workspace journal access. IDE queue mutations reuse that lock and SQLite immediate transactions; packet identity, revision and human review guards remain necessary. |
| Monitoring, RSS, definitions, pools and report publication | Monitoring has process/collector ownership in addition to Reporting/Workspace and sidecar journals. Schedulers already run outside the HTTP lane, so removing the HTTP lane cannot replace their coordination. |
| Manual federation catalog/replication operations | Some reconcile routes perform network work inline. Content reconcile/start uses existing manual workers and a durable sync journal, but its state/settings readers can write. These routes have not been reclassified as read-only or moved to a new job system. |
| Source/NotebookLM/Google Drive imports and remaining tools/configuration | Keep their present application admission. Staging, remote access and confirm/recover may span several stores; a preview-like route name is insufficient to infer ownership. |

All HTTP response objects, sockets and streams remain owned by their original
worker. No job executor, detached response writer, unbounded queue, retry or
additional worker capacity is introduced. Contention in the same domain remains
a bounded pre-dispatch `503`; independent domains can progress. Browser queues
remain bounded at 64 requests per page/domain, and origin-wide Web Locks hold
ownership until response EOF. Unsupported browsers retain per-page queuing.

## Persistent boundaries and recovery

The durable contracts remain those in
[ADR 0003](adr/0003-coordinated-operation.md),
[ADR 0050](adr/0050-bounded-http-monitor-concurrency.md),
[ADR 0081](adr/0081-complete-project-data-sync.md) and
[ADR 0082](adr/0082-composable-monitoring-and-message-pools.md).
The HTTP domains and receive lock do not replace the project writer lock,
semantic validation, privacy/identity checks, Git CAS or any journal.

| Interruption boundary | Expected recovery |
| --- | --- |
| Before domain admission, or receive ownership unavailable | No domain dispatch. HTTP `503` is a known refusal, not a new operation or permission to change operation ID. |
| Receive lock acquired, before durable inbound request | The kernel releases `flock` on process death. An empty lock file may remain; its presence is not a pending operation. No lock-file contents are recovery authority. |
| Inbound request persisted, before or during publication | Replay the same signed envelope/payload and stable ID through existing sync recovery. A timeout/disconnection is not proof of failure or permission for a fresh write. |
| Project Git commit/ref published, before index or other stores/response | Existing Workspace and cross-store sync journals roll forward from the same request. Do not overwrite divergent local edits; retain incoming history for review. |
| Durable response persisted, before HTTP EOF | Exact replay returns the saved response. The receive owner is held until persistence completes; the HTTP worker still owns response delivery. |
| Presentation state/control or session persistence | A process crash discards volatile display state. Existing SQLite/session and Workspace publication recovery remains authoritative; an HTTP lock is not evidence of publication. |
| Server shutdown | Existing admission closure, bounded worker drain and deadline-as-crash behavior remain unchanged. Lock release never triggers replay. |

The new receive file is mode 0600 under the existing validated node-private
network directory, opened with `O_NOFOLLOW` and checked for ownership, type,
permissions and a single link. It contains no credential or request payload.
No node-private path or arbitrary URL/query is exported in diagnostics; only
literal declared operation names are retained.

## Reuse and verification

**Adapt:** existing bounded HTTP admission, browser stream draining/Web Locks,
`flock` ownership pattern, read-only authentication and catalog snapshots.
**Reuse:** project Workspace/journal/CAS, sync intent/replay, session persistence
and shutdown. Public/private reuse inventories do not identify a required
external component. **Reject:** a second writer/job journal, global unlock,
timeout/worker inflation, guessed read-only routes and automatic retries.

Behavioral coverage includes independent TLS UI/catalog/presenter/telemetry and
diagnostic requests while a controlled operation owns its lane; same-domain
refusal without dispatch; two browser contexts sharing Web Locks until EOF;
actual Qt/WebEngine pages sharing one origin; distinct receiver instances;
validation failure and replay; interrupted ref/chat publication recovery; and
a real signed HTTPS exchange whose verification is paused while UI requests
and a genuine project edit run. The latter must preserve both divergent heads.

The controlled-delay HTTP tests substitute only the slow protocol/handler
body; the signed-exchange test exercises actual validation and publication.
Neither automated evidence nor an offscreen Qt run proves acceptance in the
user's running desktop. Remaining application-domain contention and the
38-second history verification cost still need separate investigation. This
is an audited split of specific owners, not a claim that every route is now
parallel or that Omnia synchronization is accepted. Remote deployment remains
outside this change.

Reproduction commands (Linux with project dependencies):

```sh
python3 -m unittest tests.test_local_api tests.test_http_ui_admission tests.test_web_server tests.test_federation_sync tests.test_presentation_sessions tests.test_presentation_documents tests.test_presentation_editor -v
QT_QPA_PLATFORM=offscreen M0_DESKTOP_TEST=1 python3 -m unittest tests.test_http_ui_admission.UIAdmissionTests.test_real_webengine_two_pages_use_origin_wide_admission -v
python3 -m unittest discover -s tests -v
git diff --check
```

The offscreen test uses real Qt/WebEngine and a temporary loopback server. It
does not disable Chromium's sandbox, use the user's profile, or start a provider.
Environments that prohibit local sockets must grant that test capability;
`PermissionError` at socket construction is not evidence of an API regression.

Recorded validation of this source change:

- The first sequential full run executed 1,842 tests with 56 skips and found
  one obsolete desktop assertion: it expected catalog requests to be refused
  while the application lane was occupied. The test now verifies catalog
  availability **and** refusal of an actual application-domain request; its
  focused rerun passed.
- After that final test change, all four existing `scripts/test_shards.py`
  shards passed in isolated temporary Git checkouts containing the current
  working source bytes. The inventory covered all 162 top-level test modules
  exactly once. Results: 482/428/461/471 tests, with 9/14/23/10 skips,
  respectively; total **1,842 tests, OK, 56 skipped**.
- The separate real Qt/WebEngine two-page admission test passed with
  `QT_QPA_PLATFORM=offscreen` and `M0_DESKTOP_TEST=1`.
- Documentation links and `git diff --check` passed. No source commit, remote
  deployment or authoritative Workspace acceptance was performed.
