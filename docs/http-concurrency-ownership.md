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
history verification cost for new/incomplete requests still need separate investigation. This
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

## 10 November follow-up: completed replay

The validation above records the HTTP split delivered in source commit
`5cb6210`; it is not a new full-suite result for this follow-up.
The [ADR 0081 addendum](adr/0081-complete-project-data-sync.md) now specifies
the fast completed replay: authenticate the peer/signature, match the exact
durable canonical envelope and payload, then recheck live authority for the
incoming request and cached response without traversing historical Git objects.
The saved response must still be signed by the original local identity and
fit the current sharing scope, project registration and outgoing chat mappings.
No regenerated response or new publication is allowed on this path.

New/incomplete requests retain full history validation. Tests also verify
that rejected retries keep their journal record unchanged and that interrupted
ref/chat/pool publication recovers through the original operation.

After the last code/test change, the focused run passed **46 tests, OK,
one skipped** (the optional Qt UI scenario):

```sh
python3 -m unittest tests.test_federation_sync tests.test_sync_diagnostics tests.test_message_pool_sync tests.test_full_data_sync -v
```

This includes a real pinned HTTPS replay with byte-identical output and a
test guard that fails if any historical Git validation runs during replay.
The full suite was not repeated for this ongoing repair slice. Remaining
application-domain ownership work and ordinary local acceptance are still open;
this result does not authorize Omnia deployment or authoritative task completion.

## Follow-up: cost of a new receive, not just completed replay

A completed-replay optimization cannot remove the work of a first or incomplete
receive. An isolated profile of the Git part of the pending main-project request
found 93 commits and about 6.56 seconds for one complete history validation on
the local machine. The receive path repeated validation during application,
and response preparation traversed the same graph twice more.

The [ADR 0081 extension](adr/0081-complete-project-data-sync.md) now allows
one request-local validated Git graph to serve application and, when exactly
eligible, its response. It never replaces the first validation, a new request's
validation, live authorization, writer locks or CAS. A changed operation ID,
peer/fingerprint, scope, branch set or head prevents response reuse. Fresh chats
and pools retain their own validation and current-state export.

For a signed receive between two temporary nodes using the same 93-commit Git
history, measured core timings were:

| Local receive case | Full history passes | Seconds |
| --- | --- | --- |
| After removing duplicate application validation, before response reuse | 3 | 20.800 |
| Eligible response reusing the exact verified incoming graph | 1 | 7.616 |
| Exact completed replay | 0 | 0.034 |

The temporary nodes used test identities and the Git part only, without the
production chat payload or a network hop. These numbers do not measure Omnia
or prove that every divergent receive will fit an HTTP deadline. Different
local heads/branches/scopes still take the original complete export path.

After the final code/test change, the same four focused test modules listed
above passed **53 tests, OK, one skipped**. This includes real pinned HTTPS,
privacy, current chat authority, mismatching export scopes/heads/branches,
cross-operation refusal of validation reuse, and ref/index/chat/pool recovery.
The whole suite was not rerun during this ongoing repair slice.

### Authorized deployment and live verification

Authenticated inspection found that Omnia still ran a release without the
completed-replay optimization. After explicit approval of the prepared archive
(`be31156fe76d35ac443dc34347c2666e4540fc552d09f0d35fc1dde2d9a367b2`),
the application was updated and its service restarted. Readback verified the
exact code and preservation of the service unit, node identity, credentials,
TLS material and original completed operation record.

The original pending request was matched byte-for-byte against that completed
receiver record, then replayed once through the native controller. It completed
in 10.163 seconds and cleared the pending operation without replacing its ID.
This confirmed the old transfer, not the latest local project snapshot.

One subsequent standard transfer of the newer snapshot still timed out in
`wait-response` after 60.047 seconds in that phase (83.039 seconds overall).
Authenticated receiver inspection subsequently found its persisted inbound
intent but no response, and a failed observation at `receive-publication`:
315.002 seconds overall, 0.413 seconds in that final phase, `ValidationError`.
The preceding phases therefore consumed roughly 314.6 seconds; phase timing
alone does not attribute all of that time to Git validation. Read-only Git and
journal inspection found one modified tracked roadmap document (one removed
and one added line), no pending journal rows or active operation, no staged
sync refs, and the original HEAD. This satisfies the existing refusal condition
for a dirty destination; the content change is preserved pending human review.
The operation must not be discarded or automatically retried as a new one.
The live timeout is **not fixed**, despite successful deployment and
old-request recovery.

Separately, real catalog projections exposed a candidate-selection error:
the signed catalog contract uses `id`, while automatic/manual-all sync read
`project_id`. The local correction uses the existing catalog contract, with
tests exercising real signed catalog exchange and remote-only selection for
both same-team and same-company relationships. This correction was made after
the approved archive was frozen; it is not part of the deployed release.

The five focused modules (the four listed above plus
`tests.test_federation_catalog`) exercised 61 tests, with one optional Qt skip.
Three socket tests initially failed because the sandbox prohibited opening
loopback sockets; all three passed when rerun with that restriction lifted.
There were no remaining behavioral test failures. The full suite remains
unrun for this repair slice.

## Local edits in the conflict overview

The follow-up described in [ADR 0043](adr/0043-explicit-federated-conflict-resolution.md)
adds local uncommitted changes and last peer conflict reports to the shared
desktop/web conflict overview. It shows a bounded inert text diff, including a
small change in a roadmap larger than the diff-output budget. It neither
publishes local edits nor discards them. Unavailable/unsafe previews remain
visible as unavailable rather than claiming that no conflict exists.

Before historical verification, an authenticated new/incomplete receive now
rejects an unowned dirty destination with existing HTTP 409. The project journal
is checked under its nonblocking writer lock; interrupted publication keeps its
original recovery path. Completed replay still precedes this check. An HTTPS
test measured about 20 ms for receiver rejection and verifies the sender enters
`conflict` with its outbound operation retained. This is isolated test evidence,
not a new live Omnia acceptance or a bound for validating a clean 93-commit graph.

The focused run covered **80 tests, OK, one optional Qt skip**, including conflict
resolution, federation sync/catalog, diagnostics, pools, full-data recovery and
the shared web conflict endpoint. After the final diff-budget adjustment,
**16 conflict tests passed** again, including the large-roadmap case. A separate
real Qt/WebEngine smoke passed with an isolated native project and offline
transport, checking local/peer-only visibility, exact diff, inert HTML, blocked
merge publication, clean-state refresh and failed-read visibility.
The full suite was not run for this repair.

After explicit approval, archive
`63091c4951908e728759a3ccfff99c1ae7301260a2786194bfaa50ef45a1b222`
was installed on Omnia. Readback verified the exact three changed runtime
modules, active restarted service, unchanged unit/identity/credentials/TLS,
unchanged main-project HEAD and roadmap bytes, and retained saved requests.
The authenticated live conflict endpoint returned one local change with the
roadmap present and its text diff available, without an incoming history ref.
The desktop process was also verified to start from the active checkout after
the final runtime change. This confirms code activation and the live backend
conflict response; it does not claim that the user accepted a resolution or
that the local roadmap change was published/discarded. The original outbound
operation remained present in the desktop journal. After the ordinary scheduler
interval, read-only desktop-journal inspection confirmed `conflict` / `Peer
reported a content conflict` and the same pending operation ID
`dc97cb95-dcba-4c5c-a759-f4d2dbcc30b8`. No manual new operation or roadmap
resolution was introduced to obtain that result.
