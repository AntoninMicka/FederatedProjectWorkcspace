<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# HTTP blocking boundaries: source audit

Source continuation from `5535535`, `feature/rss-direct-pilot`, 10 November 2026.
This is a technical ownership inventory, not a second Workspace task queue.
The canonical mapping remains project `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
repository `https://github.com/AntoninMicka/FederatedProjectWorkcspace.git`,
export revision `5e9de351ac5e6ec033066a10eba2309fbbaf57cc1a3f9799478c172cd6025a39`.
Bridge readback was fresh at `2026-11-10T09:59:57.277Z`.
The user reports deploying the prior slice without improved responsiveness;
its live deployment and end-to-end behavior were not remeasured in this audit.

A source-wide call scan supplies candidates, not proof of blocking: names such
as `join`, `connect` and `run` also describe string and application operations.
The following boundaries were checked against their implementation. Remaining
rows explicitly distinguish finite local limits from an end-to-end deadline.
No row claims all possible runtime stalls have been eliminated.

| Boundary and owners | Actual waiting contract and present evidence |
| --- | --- |
| HTTP worker admission, `local_api.py` | Fixed worker slots, nonblocking rejection, same worker owns its socket. No pool increase in this repair. Saturation can still reject an otherwise independent route. |
| Application lane and stream handlers, `local_api.py`, `desktop_ui.py` | Same-domain HTTP admission waits at most 100 ms in the production reserve-UI configuration, but the admitted owner holds the lane for the whole operation. The follow-up provider domain moves streams together with configuration/recovery/lifecycle conflicts out of the application lane. Remaining application operations and the exact administration list action can progress. The provider domain itself remains serialized; no finer per-thread run ownership is claimed. |
| Project admission, `request_ownership.py` | Exact audited route scopes, up to 100 ms admission wait, idle keys removed. Request-local project journal acquisition is nonblocking. Reads may still initialize or repair an index under that owner. |
| Browser queue and Web Locks, `http_ui_admission.py` | Total page queue capacity 64, exact project scope and owner held until EOF. A removable FIFO and one five-second pre-dispatch budget now bound both page-local and origin Web Lock waiting. Expired entries cannot dispatch later. Active transport ownership still lasts until EOF/failure; this is not a network execution deadline and cancellation never implies an automatic retry. |
| Administration, `administration.py` | Exclusive registry admission was already bounded in request context. The read-only shared flock was still blocking, including authentication. It now uses the same bounded acquisition. Startup/bootstrap stays outside the request context. The provider follow-up also moves all web authentication, HTTP registry listing and project-role queries onto shared registry snapshots after startup, avoiding exclusive-reader collisions. |
| Other persistent file owners | The remaining blocking acquisitions in Git transfer, Google Drive import, deployment preferences, CMS publication/deployment, replication and project relocation now use `bounded_flock`. Inside HTTP they raise a typed busy outcome instead of parking a worker. Outside the context they retain the original native locking behavior. Existing explicitly nonblocking collectors/creation/repair/queue owners retain their own contracts. |
| Outbound sync coordinator, `federation_sync.py` | Previously waited indefinitely on the one-node outbound flock before checking cancellation. Now checks cancellation first, validates the owned lock file and attempts nonblocking acquisition. Capacity remains one. Collision records `busy` and preserves the exact outbound envelope and operation ID. The coordinator also enters bounded ownership context for nested registry/transfer locks. |
| Inbound sync coordinator, `federation_sync.py` | Dedicated HTTP lane and nonblocking native receive owner, including direct/native receiver calls. Still serializes receives per node. Native journal/registry collisions become 503, not 422. History verification can remain expensive; the replay shortcut applies only to an already persisted completed response. |
| SQLite stores, including `thread_lifecycle.py`, `chat_threads.py`, provider journals | Transactions retain their native ownership and finite connection timeouts, commonly 2/30/60 seconds depending on the store. These are individual busy waits, not a common request budget. Schema initialization, recovery and repeated transactions still need separate audit before moving their HTTP routes. No WAL/schema migration or blanket timeout reduction is made here. |
| Git and history validation, `storage.py`, `git_transfer.py`, `workspace.py` | A Git subprocess has at most 30 seconds, reduced by an optional caller deadline. Multiple commands and full semantic/history validation are not thereby bounded to 30 seconds in total. Project view cache avoids only previously validated exact-HEAD work under its existing checks. |
| Provider I/O, `ollama_backend.py`, `atlascloud_backend.py`, `direct_provider.py` | Connection/first-token/read limits exist. An inactivity timeout is not proof of an absolute deadline across connection, headers and a trickling body. Dispatch uncertainty must remain unknown, with no automatic re-dispatch. |
| Task stream controls, `task_stream.py` | Soft deadline 180 seconds, hard deadline 360 seconds or 1800 after explicit extension; cancellation interrupts an attached socket. Socket attach timing, callback/output lock ordering and the watchdog writer require dedicated stream ownership review. A 225-second shutdown deadline can end an extended run as a crash. |
| Chat process state and recovery, `chat_service.py`, `thread_lifecycle.py` | Request identity is scoped with ContextVar. Backend configuration and task control have process RLocks. The six configuration/reset lock scopes now use bounded HTTP acquisition while preserving native reentrancy; their protected work still needs its own budget. Chat status performs lifecycle recovery and initializes stores; it is not a pure read. Splitting streams from these operations needs native run/configuration/lifecycle ownership, not a second HTTP writer. |
| Shutdown and native tools, `local_api.py`, `lxc_deployment.py` | Worker drain is bounded in the HTTP server. Native interactive SSH has an intentional human-authentication wait; it is not ordinary UI request admission. Unqualified thread joins and subprocess/pipe waits need evaluation in their actual callers rather than automatic replacement. |

## Stream errors after headers

Typed busy outcomes can occur after a stream sent HTTP 200. The common HTTP
adapter now tracks whether headers have been sent. For the three declared
NDJSON stream routes, a late busy outcome produces a terminal error frame with
status 503, `outcome=unknown` and `retry=same-operation`; it never writes a second
HTTP response. Other already-started responses close rather than claiming a new
status. The original response worker remains the writer. No provider request
is automatically repeated or declared rolled back.

## Persistent boundaries

The authoritative contracts remain ADR 0003, 0050 and 0081. Before file-owner
acquisition, an operation may have initialized its private directory; it does
not gain permission to modify the protected state. If an earlier stage already
persisted an intent, a later busy response remains unknown and must use that
same operation's recovery. After Git publication or remote dispatch, failure to
obtain another owner never authorizes another commit/dispatch or deleting the
journal. Kernel ownership is released on close/process death. This slice adds
no journal schema, task scheduler, automatic retries or persistent queue.

## Verification of the file/process ownership slice

- 159 targeted HTTP, sync, administration, creation, import, CMS, replication,
  deployment and task-stream tests passed (3 optional skips) before the final
  outbound-context and backend-process-lock additions.
- 164 backend configuration/catalog/provider and ownership tests passed after
  the backend RLock change.
- Final 70 sync, ownership, browser-admission and task-stream tests passed with
  real Qt/WebEngine enabled, including shared/exclusive collision, cancellation,
  unchanged outbound payload, native reentrancy and terminal NDJSON busy frames.
  These runs overlap; their counts are not an aggregate test total.
- The optional fork-chat Qt check originally read evidence before asynchronous
  navigation finished. The identical failure was reproduced from unchanged
  HEAD in an isolated source archive. The check now waits for navigation before
  evaluating its refresh evidence; the final real Qt run passed.
- Compilation and `git diff --check` passed. The full suite has not run. Actual
  real-profile acceptance and any new Omnia deployment remain separate.

The existing global fallback and the unreviewed elapsed-time boundaries in the
inventory remain open. Finite or nonblocking acquisition does not prove an
admitted operation finishes quickly, and no end-to-end performance improvement
is claimed from these isolated checks.

The provider-domain follow-up is documented in `http-concurrency-ownership.md`.
Its complete registered-route inventory is enforced at production startup;
SQLite and elapsed-time deadline rows above remain open.

### Federated transport deadline follow-up

Content-sync, catalog and replication now share one monotonic budget per HTTPS
exchange (60/15/30 seconds respectively), including connect, TLS, upload,
headers and body. See `http-concurrency-ownership.md` for recovery boundaries.
Slow continuous responses no longer extend these three transport waits.
Provider/hostname DNS, incoming slow bodies and non-network work remain open;
this does not close the broader elapsed-time inventory.

### Project-open SQLite follow-up

Project journal/index connections and the read-only sync-conflict query now
use zero SQLite busy timeout inside bounded request context and map only
BUSY/LOCKED to typed busy. Native timeout policies and transaction recovery
remain unchanged. Tests exercise HTTP 503 with independent project progress,
commit-time rollback and recovery after Git publication. This supersedes the
SQLite row for these paths only: other stores, SQL execution, disk latency and
initialization/repair during project reads remain open.

### Initialized project-read follow-up

Open, plan-view and preview now attach existing owned journal/current index
state without repeated bootstrap. Native initialization/legacy rebuild remains
for missing/recognized older state. They still use journal ownership and can
repair stale indexes, so their routes remain serialized. Desktop HTTP open and
plan-view now share the existing web 30-second project Git budget from
registration through view/draft work, with expiry checked before returning.
CPU/disk calls and ancillary registry Git work are not preempted; complete
history-validation deadlines and remaining stores are still open.

### Transfer-history budget follow-up

Native history validation, export, content-sync bundle preparation/isolated
verification and replica bundle verification now share a 60-second budget per
phase. Existing/new Git wrappers and multiple branches inherit the earlier
scope/explicit deadline; subprocesses still have at most 30 seconds each.
Receiver timeout is transient 503, preserving the original pending request.
This closes repeated per-command/branch timeout resets in these phases, not
whole-request elapsed time, preemptive CPU/disk cancellation, other Git workflows
or the remaining global application lane.
