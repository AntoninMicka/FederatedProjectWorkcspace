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

This first inventory describes the initial slice. Later sections record the
project, bounded-resource and provider-domain follow-ups that supersede it.

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

## Omnia idle-work investigation, 10 November

Live read-only diagnostics of the deployed conflict release found about
1.2 GB available RAM and 146 GB free disk. The backend's lifetime CPU average
was about 83% of one core. Two HTTP snapshots five seconds apart showed the
same `/v1/monitoring/view` holding `application_lane` at 9.449 and 14.634 seconds.
Independent sync requests recorded 4.3–21.3 seconds overall, mainly in
`receive-prepare-response`. Moving sync admission did not eliminate CPU work.

Two sources of avoidable work were confirmed in code:

- Monitoring polled every 15 seconds even when its panel was hidden, and could
  enqueue another refresh while an earlier one was still running. Automatic
  refresh now requires a visible panel and document, no dirty/pending editor,
  and no outstanding monitoring read. Explicit post-save reads remain fresh;
  an older pre-save response cannot replace their result.
- Unchanged Git inventories were exported and fully validated before their
  bundles were discarded. The exact known-inventory comparison now omits that
  export under the original writer lock; new heads/branches and any Git bytes
  actually transferred retain full validation (ADR 0081 addendum).

An isolated two-node fixture with 20 added commits measured full preparation
at 1.068 seconds versus 0.043 seconds for an unchanged inventory (zero Git
payload bytes). These are local timings, not an Omnia performance guarantee.
The global application lane and remaining implicit-writing read routes are
unchanged; this repair does not claim a complete HTTP ownership replacement.

Verification after the final runtime change: **85 focused tests passed, one
optional Qt scenario skipped**, covering federation sync/catalog, diagnostics,
pool/full-data recovery, monitoring and asynchronous polling behavior. Two
existing real Qt/WebEngine monitoring scenarios also passed with isolated
temporary nodes, including editing/saving and review/publication. The full
suite was not run for this repair. Archive
`6cad07d2b52ddaa898befef634e6b65bd80eb9aaafe921a670bda3fc769bca98`
was explicitly approved for a separate application-only deployment.

Deployment readback verified the exact four runtime modules, restarted active
service, unchanged unit/identity/credentials/TLS, main HEAD and roadmap bytes,
and retained saved requests. The live conflict endpoint still returned the
preserved roadmap diff. Service CPU accounting over approximately five-second
samples measured **124.9% of one core before** and **23.5% immediately after**
the update. Only diagnostics requests were present in the latter HTTP samples.
These short windows straddle a restart and different request activity; they
are not a controlled steady-state UI benchmark or human acceptance. Existing
web pages must reload their JavaScript to adopt the monitoring polling change.

The user subsequently reported that project opening/switching was still slow.
That feedback is a failed UI acceptance of the first performance repair,
despite the lower short-window CPU sample. Isolated profiling of a native
clone of the main project found 66 Git subprocesses and five snapshot reads
for an empty monitoring overview, plus 60 Git subprocesses for project opening.
The browser also awaited monitoring, Julia definitions/status, roadmap review
and chat before finishing the project landing.

The project-opening follow-up batches the existing 20-entry history read:
object IDs/types/sizes are checked in one bounded `cat-file --batch-check`,
then one NUL-delimited `git log --no-walk=unsorted` reads the verified commits
in their original order. The 64 KiB commit limit, truncation, exact HEAD,
privacy, project/index validation and writer-lock boundaries stay intact.
The isolated opening profile used 22 Git subprocesses after this change.

The project overview no longer awaits hidden monitoring, Julia, roadmap-review
or chat loads. Existing navigation requests them on entry to the relevant
section; delayed Julia results are discarded if the active project changes.
Conflict-summary and task-queue reads retain their independent behavior.
This does not optimize the internals of the monitoring view itself and must
not be described as resolving every application-lane contention case.

Project/Workspace tests passed **33 scenarios, two optional Qt skips**. Four
real Qt monitoring/blocks/migration scenarios passed after explicitly opening
the monitoring section. An isolated real Qt smoke checks the project landing
and on-demand entry points; the local-conflict smoke also passed. The broader
navigation smoke exposed a stale TODO destination expectation; identical
failure was reproduced with the unchanged HEAD before correcting that test
expectation to the existing preview-tab behavior.
The corrected smoke then passed all ten navigation destinations and its
save/discard/cancel checks. The project-opening follow-up was separately
approved as archive
`60edcdcf11f508989e07c777f8651213504575cdcc533147de3ba27e4cbd5518`.

That archive was deployed and the five runtime module hashes, active restart,
unit/identity/credentials/TLS, saved requests, main HEAD and local roadmap bytes
were verified unchanged as intended. Authenticated `/v1/projects/open` returned
HTTP 200 with the same HEAD, 1,098,624 response bytes, 353 artifacts and 20
history entries: one pre-update sample took 6.313 seconds, one post-update
sample 4.009 seconds. These are single measurements around a restart, not a
controlled average. The short post-update CPU sample was 19.7% of one core.
The live conflict endpoint still returned the local roadmap diff. The actual
opening response in that single loopback sample took roughly four seconds;
this excludes browser admission, network transfer, decoding and rendering.
The user subsequently rejected the deployment: switching takes substantially
longer and can fail to complete. It is not accepted as a performance fix.

The next source change preserves the currently opened project until its
replacement response succeeds, and makes a switch failure visible. Previously
the project was cleared before the response and the error could remain hidden.
`workspaceLastProjectOpen` records request, render and paint durations, including
browser admission timing, to distinguish a backend sample from actual switching.
Opening also defers the task queue, conflict details and graph until needed.
An exact-HEAD process cache retains validated views under the checks documented
in ADR 0022; compact, negotiated gzip reduces project-opening response transfer.
These changes require separate deployment and live acceptance.

Local file conflicts additionally gain explicit reviewed keep/commit and
restore-with-journal-backup actions. They reuse the existing Stage/Commit and
journal recovery paths; crash boundaries and the limited web permission are
documented in ADR 0043. No choice has been executed on the real roadmap.

## Follow-up: project ownership rather than global HTTP serialization

The 10 November continuation starts from source `5e9856f` on the same branch.
The bridge reports the same canonical project/repository/export revision with
`stale=false`, synchronized at `2026-11-10T09:02:46.804Z`. The user explicitly
requested continued removal of the global application lock; no task acceptance
or Workspace plan change is inferred.

The exact `PROJECT_ROUTES` table now moves 24 audited routes out of the
application fallback, including both reads with initialization effects and
project writes. Their HTTP lock is keyed by canonical project UUID after
successful authentication and bounded body parsing. Existing project journal,
semantic validation, privacy, receipts and Git CAS remain authoritative.
The table specifies nested scope fields for editor, conflict and Stage/Commit
requests; the browser uses the same scopes. Each project owns its response until
EOF, while other projects and the existing node lane may progress.

Every HTTP project journal acquisition is nonblocking through request-local
context, including the desktop's formerly blocking default. This prevents
workers accumulating behind a journal after removing HTTP serialization.
Unknown publication outcomes preserve the original request identity. Native
background workflows retain their previous locking unless they are incoming
sync receivers. The complete crash contract is in the 10 November ADR 0050
addendum. This is an additional completed ownership slice, not completion of
all of stage A: stream/configuration/shared-service ownership and a migration
of all remaining routes still require audit. The receive lane remains serialized
per node; this change does not introduce concurrent inbound exchanges per project.

Live read-only inspection found completed responses on Omnia even for locally
pending operations. It also found `BlockingIOError` at destination checking and
response preparation, previously mapped to HTTP 422 and permanent rejection.
The source now maps these collisions to 503 and stores transient sender state
`busy`; an isolated signed HTTPS scenario verifies the same saved operation ID
is reused and completed after the collision clears. No live pending envelope
was deleted, replaced, or replayed by this diagnostic inspection.

The node registry flock also uses bounded acquisition in request context, so a
project's write guard cannot reintroduce an unlimited HTTP wait on node state.
Web and desktop initialize/migrate administration before their listener starts.
Outside request context registry locking retains its native behavior.

Verification of this follow-up: 175 targeted HTTP, signed sync, administration,
journal, artifact and repair tests passed (11 optional skips). An additional
94 project/Workspace/web ownership checks passed (10 optional skips) before the
final registry-lock adjustment. Five browser-admission checks passed, including
real Qt/WebEngine origin-wide admission. The native Qt conflict scenario then
passed while both application and content-receive HTTP lanes were held: project
opening, restore, commit, lost response and same-ID retry all completed through
the actual browser admission wrapper and native API. The project-switch Qt
scenario also passed. `git diff --check` and compilation passed. The full suite
has not run; there is no claim of completed stage A or live Omnia acceptance.

## Provider ownership and administration listing, 10 November continuation

Source baseline `4b50226` on the same branch had a clean working tree. The
canonical project/repository/export mapping was verified again; bridge state
was fresh at `2026-11-10T10:16:07.359Z`. This is continued implementation of the
user's HTTP repair, not acceptance or an authoritative planning change.

The exact policy now classifies all 258 registered desktop/management/web JSON
routes, plus the four existing peer protocol paths. Of the registered routes,
136 retain a common provider owner, 86 retain application ownership, 24 use
project ownership and the other 12 keep existing independent domains. The
provider owner includes chat/task/external streams and their real conflicts:
backend configuration/reset/catalogs, chat lifecycle recovery and assignment,
workflow/autonomy/summary/extraction/media/CMS, and destructive project/node
administration. This preserves their previous HTTP ordering instead of allowing
configuration or lifecycle recovery to race an in-flight run. Google Drive and
project creation/repair/deletion remain conservatively in this domain until a
finer audit of shared lifecycle state. Provider capacity is one, with no
additional workers, detached socket writer, retry or second persistent writer.

The other application owners retain their existing serialization and native
project/SQLite/flock contracts: monitoring/collection/RSS, Julia, source/IDE
transfer and planning, presentation documents and node preferences. They no
longer wait behind a provider stream. Monitoring's frozen binding reads and
native scheduler already run outside HTTP serialization; their own persistence
and authority checks remain required and are not replaced by a route lane.

`/v1/administration` with the exact action `list` gets a node-status owner after
authentication and bounded body parsing. Its aggregate can initialize stores and
record interrupted sync status, so it is not called a pure read. The persistent
administration flock and separate sync/catalog stores still own those effects.
Every mutation, malformed or unknown action keeps provider ownership. Browser
classification reads the same exact action map; thus listing is not queued behind
stream EOF by origin-wide Web Locks. Backend configuration/recovery intentionally
remain serialized with the provider, not classified as independent reads.

The three streams also acquire HTTP ownership after authentication and bounded
body parsing. Web authentication uses the existing read-only registry path.
Diagnostics add a project UUID only when it is a canonical valid declared value;
no payload, token or arbitrary URL is recorded. Task stop/extend keeps its
existing availability owner and can interrupt the provider socket while the
provider lane is held.

Both production entrypoints validate the registered route inventory before
serving. A newly registered JSON route without an exact classification fails
startup; it cannot silently run alongside the provider through an unreviewed
fallback. Unknown incoming URLs/query variants still fail normal route/security
validation and never enter domain dispatch.

The persistent crash boundaries remain ADR 0003/0050/0081 and the existing run
journals: pre-admission refusal does not create a run; dispatch uncertainty keeps
its original run ID and is not an automatic retry; shutdown can still end a run
as a crash. Existing disconnect, cancellation and terminal NDJSON error paths
are preserved. This does not complete the remaining SQLite, browser elapsed-time,
network deadline or shared application-domain audits.

### Registry read ownership found by the real browser checks

The first broad real-Qt run exposed a real collision: authentication and project
role lookups still used exclusive bootstrap-capable registry reads while the
new node-status aggregate ran independently. This could make ordinary opening
return `resource busy`. Web account authentication now always uses the existing
read-only registry reader; HTTP registry listing and project replication-role
lookups use the same shared snapshot, carrying the exact registry commit under
the shared lock. Native callers outside bounded request context keep their
previous bootstrap/migration behavior. Account credentials are checked again at
domain dispatch after body parsing/admission; an account revoked during that
interval cannot continue with the cached pre-admission actor.

Startup now prepares the existing federation signing identity under the registry
owner before accepting readers. It uses the same atomic private-key/public-marker
creation as before, not key rotation. Existing bytes and fingerprints must match.
A crash before key publication leaves no published identity; after key publication,
startup derives the marker from that same key. A missing private key with an
existing marker or a mismatched marker fails closed. HTTP listing uses explicit
noninitializing identity reads and never recreates a missing identity or marker.
There is no new persistent format, credential reset or live identity change in
this source repair.

Two remaining Qt navigation failures were reproduced identically in an isolated
archive of unchanged `4b50226`: IDE clicked a hidden settings item before async
settings navigation finished; Julia waited for an eagerly loaded tool catalog
before navigating to the now on-demand tools tab. The test flows now wait for
those navigation boundaries. The native IDE install/map/download/revoke, Julia
pattern/draft and project-plan browser checks subsequently passed together.

The shared request snapshot is also reused by mapping-action and active
replication checks, chat mapping counts, catalog/content authority snapshots and
probe identity reads. This prevents the settings aggregate from re-entering an
exclusive bootstrap path through one of its helper queries. Native readers
outside bounded request/coordinator context intentionally keep the old bootstrap
contract; background owners not using that context remain part of the later audit.

### Final verification of the provider slice

A single final targeted run passed **293 tests**, with `M0_DESKTOP_TEST=1`,
including real Qt/WebEngine, HTTP/TLS, browser Web Locks, task streams,
project ownership, chat/backend configuration, administration/signing identity,
signed content sync and replication. The additional direct catalog/network-probe
run passed **11 tests**. The selected modules were `test_local_api`,
`test_http_ui_admission`, `test_task_stream`, `test_web_server`,
`test_project_http_ownership`, `test_chat_service`, `test_backend_catalog`,
`test_administration`, `test_federation_accounts`, `test_federation_sync`,
`test_project_replication`, then `test_federation_catalog` and
`test_desktop_network`.

The earlier intermittent project-plan Qt failure was traced to selecting the
first random artifact UUID and expecting the two-node “Rozhraní” subgraph even
when “Jádro” was first. The captured trace showed the one-node “Jádro” selection
and a matching queue/HEAD, not a lost navigation. Selecting the intended named
subgraph passed three consecutive native Qt runs and the final regression.

Compilation of the changed runtime modules and `git diff --check` passed.
The full suite has not run; the wider HTTP ownership batch is not complete.
These changes remain local and have not been deployed to Omnia in this turn.
No source commit, push, Workspace acceptance or live end-to-end speed claim is
inferred from the tests.

## Bounded browser admission, continuation from `4e6dabb`

The working tree was clean at the start of this slice. The saved canonical
project/repository mapping and export revision were read back, but bridge state
was `stale=true, waiting_review=true`, last synchronized at
`2026-11-10T11:45:57.847Z`. The user explicitly instructed continuing this same
HTTP repair from the available context because synchronization was failing.
This does not mark the export fresh, complete review, activate a different
Workspace task or change the authoritative plan.

Browser admission now has one five-second elapsed budget covering both its
page-local queue and origin-wide Web Lock acquisition. Capacity remains 64
active/queued requests across the page, with the existing exact route/action/
project classification. The deadline starts at the call, not after reaching
the front of the queue. A monotonic dispatch-time check also refuses an expired
entry when a hidden page's timer was throttled. Only the classification fields
needed for project/action ownership are decoded; unrelated large request bodies
are passed through without a redundant JSON parse.

The former promise-tail chain is replaced by a removable FIFO. Expired/cancelled
waiters leave the queue and free their counted capacity without retaining a
chain behind an indefinitely open stream. Surviving entries retain order.
Cancelling Web Lock acquisition uses its own AbortController; it never cancels
a held lock or silently falls back to uncoordinated dispatch. A late callback
checks the entry again and cannot resurrect an expired request.

The uncertainty boundary is invoking the original fetch transport, not proof
that the peer received any bytes. Before that call, timeout, cancellation,
capacity rejection or lock acquisition failure report `phase=admission`,
`outcome=not-started`, `dispatched=false`. This describes this attempt; an older
attempt of the same operation might already exist remotely. Caller cancellation
after transport invocation is conservatively `outcome=unknown`. Its error does
not release an active owner: the existing response clone must reach EOF or
transport failure. The five-second timer is cleared before fetch starts; it is
not a provider execution limit or a total network deadline.

No request body, operation/run ID, approval digest or original transport signal
is rewritten. There is no automatic resend. Explicit retry retains the caller's
original payload and operation identity. Caller cancellation reasons remain
available as `cause`; the admission error itself carries the stage/outcome.
`projectRequest` preserves this classification instead of converting all
TimeoutError/AbortError values to unknown. Incomplete JSON/NDJSON responses stay
unknown (status 408 in the client), so existing pending-run handling retains the
original identity. Stream error frames preserve backend outcome/retry fields.
No terminal stream result is fabricated from a partial body.

Persistent formats and authorities remain unchanged under ADR 0050/0081. A
cancelled queued attempt made no transport call. A disconnect after dispatch
is not rollback; the backend journal, receipts, semantic validation and Git CAS
remain the recovery authority. Browser ownership never substitutes for them.

Validation: a final targeted run passed **99 tests** with real Qt/WebEngine
enabled, covering admission, task streams, web/TLS, local API and project
ownership. The new two-page Qt scenario held an origin Web Lock beyond the real
five-second budget: the waiting write never reached the backend, diagnostics
continued and an explicit retry sent its original ID exactly once. Virtual-clock
checks cover repeated expiration of 63 waiters behind an open body, cancellation,
late timer/lock callbacks, dispatch uncertainty, unchanged payloads and retained
ownership after caller abort. Client checks cover incomplete JSON and missing
terminal NDJSON results. Compilation and `git diff --check` passed. The full suite
has not run; live Omnia performance/acceptance and total network deadlines remain
separate. No deployment or source commit was performed in this slice.

The final admission-boundary check passed all **11 admission tests**, including
real Qt, after moving the full-queue rejection ahead of request-body decoding.
This avoids expensive parsing for an attempt that cannot be admitted. These
11 tests overlap the 99-test run; they are not an additional distinct total.

## Total deadlines for federated HTTPS transport

Continuation from source `c7deb8d` on the same branch. The export remains stale
and awaiting review; the user explicitly authorized continuing this repair
from the available source. No planning state or acceptance is changed.

`DeadlineHTTPSConnection` adapts stdlib HTTP parsing and verified TLS for the
existing literal IPv4 peers. The existing 60-second content-sync, 15-second
catalog and 30-second replication budgets now cover TCP connect, TLS handshake,
upload, HTTP headers and response body together. Every raw response read uses
the remaining monotonic budget, including chunked responses; trickling bytes
cannot restart it. Numeric socket connect avoids DNS. There is no watchdog,
background transport worker, automatic retry or protocol change. Native socket
file ownership preserves HTTP/1.0 response bodies after connection auto-close;
responses and connections are explicitly closed on failure.

Crash boundaries and recovery remain those of ADR 0081 and the native
replication journal: before dispatch no remote result is established; after
any dispatch a timeout can mean the peer committed but the response was lost.
It does not authorize deleting pending intent, generating a replacement ID or
reapplying a completed operation. The sender retains its exact signed envelope,
bundle and operation ID; a subsequent explicit attempt uses native durable
replay and receipt validation. Local publication still uses journal/Git CAS.
TLS CA pinning, hostname verification and existing size/policy checks remain.

This bounds transport I/O, not Git verification, subprocesses, CPU work or the
whole synchronization job. Provider transports using hostnames and DNS remain
outside this slice, as do server-side slow request-body deadlines. This is local
implementation evidence, not Omnia deployment or end-to-end acceptance.

Verification: the targeted HTTP-deadline, content-sync, catalog and replication
run passed 74 tests (one optional skip). After adding the TLS address mismatch
case and final durable-replay assertions, all 10 selected deadline/recovery
tests passed. These runs overlap. Real loopback TLS tests cover slow headers,
fixed-length/chunked bodies, stalled handshake/upload, CA/SAN refusal and
HTTP/1.0 body ownership; a deterministic clock checks cumulative connect/TLS
budgets. The native sync test preserves the exact outbound bytes through
lost-response timeout and busy admission, then clears the intent only after
successful receipt and retains one inbound operation. Compilation and
`git diff --check` passed. The full suite has not run.

## SQLite ownership on the project-open path

Continuation from `8a18117`, same branch and user-authorized source continuation
with the previously recorded stale export. The user reports improved live
responsiveness; this is not acceptance of the remaining concurrency work.

The project journal, all project-index connections (initialization, reads and
rebuild) and the read-only content-sync conflict-status query now adapt the
existing `bounded_project_requests` context. In that context SQLite busy timeout
is zero: an occupied database cannot repeatedly park an HTTP worker. Native
callers retain their previous timeouts (journal/conflict query 2 seconds, index
5 seconds). The adapter translates only SQLite BUSY/LOCKED primary and extended
error codes to `ProjectBusy`; schema, corruption and other SQL errors keep their
original meaning. The existing HTTP adapter produces 503/same-operation and
preserves unknown outcomes. There is no sleep, automatic retry or new writer.

Transaction and crash boundaries remain ADR 0003: failures before publication
roll back the current uncommitted SQLite transaction. Earlier explicit journal
commits and filesystem/Git publication stay durable. In particular, index
contention after Git publication leaves the same unfinished journal operation;
recovery rebuilds the projection and completes its receipt without a second
commit. Commit-time SQLite contention also rolls back uncommitted changes and
closes the connection before returning busy. The adapter does not clear intent
or infer that the overall request never started. Conflict-status contention
cannot silently produce an empty conflict list; after release the original
conflict remains visible through project open.

This slice removes SQLite lock sleeping at these specific boundaries, not SQL
execution time, disk/fsync latency or a whole-request deadline. Project reads
still acquire their journal owner and may initialize/rebuild state; they are
not reclassified as pure reads. Other node/provider SQLite stores and native
background callers remain to be audited. No WAL, schema, migration or persistent
format change is introduced. This source change has not been deployed here.

Final verification: 129 targeted SQLite ownership, HTTP project ownership,
project reads, storage/projection, journal, Workspace and federation-sync tests
passed (3 optional skips). Real lock collisions cover journal/index open and
conflict visibility, SQLite shared-cache extended LOCKED, commit-time rollback,
independent project progress and recovery after Git publication. Existing
process-crash recovery tests ran in this selection. Compilation and
`git diff --check` passed; the full suite and live deployment have not run.
