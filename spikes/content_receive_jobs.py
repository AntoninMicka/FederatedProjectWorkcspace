# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Content sync receive as a background job with a heartbeat stream (AUDIT-B7-T1).

The receiver's work (history validation, publication, durable response) no
longer has to fit into the sender's single HTTP deadline. The HTTP handler
starts the existing ``SyncReceiver.receive`` in a background thread and
streams heartbeat frames until the job finishes. A dropped connection does not
stop the job; the sender's retry of the same operation attaches to it, or,
once finished, is answered by the existing durable inbound replay.

No new persistent state exists here. The registry is only an in-memory
execution handle; the content sync journal (``inbound``) stays the recovery
authority, exactly as for the synchronous path (ADR 0042).

Stream format (``STREAM_TYPE``): newline-terminated JSON frames. Heartbeats
carry only a fixed peer phase and elapsed time. The terminal frame is either
``{"type": "result", "length": N}`` followed by N bytes of the ordinary
content sync response body, or ``{"type": "error", "status": ...}``.
"""
import hashlib
import json
import threading
import time

from spikes.metadata import require
from spikes.request_ownership import safe_busy_resource
from spikes.sync_diagnostics import safe_peer_phase

STREAM_TYPE = 'application/vnd.federated-workspace.content-sync-stream-v1'
# The same frames carry the content state answer (automatic change check).
STATE_STREAM_TYPE = 'application/vnd.federated-workspace.content-state-stream-v1'
HEARTBEAT_INTERVAL = 5          # seconds between heartbeat frames
FINISHED_TTL = 120              # a successful job's result stays attachable this long
MAX_FRAME = 4096                # every JSON frame line, terminal result header included
JOB_STATES = ('running', 'finished', 'failed')


class _Job:
    def __init__(self, key, digest, target, phase_source):
        self.key, self.digest, self.phase_source = key, digest, phase_source
        self.started = time.monotonic()
        self.done = threading.Event()
        self.finished_at = None
        self.result = None      # raw response body on success
        self.error = None       # terminal error frame on failure
        self.thread = threading.Thread(target=self._run, args=(target,),
                                       name='content-receive-job', daemon=True)

    def _run(self, target):
        try:
            self.result = target()
        except BaseException as exc:  # noqa: BLE001 - the frame never carries exception text
            self.error = error_frame(exc)
        finally:
            self.finished_at = time.monotonic()
            self.done.set()

    def heartbeat(self):
        return {'type': 'heartbeat', 'peer_phase': safe_peer_phase(self.phase_source()),
                'elapsed_ms': round((time.monotonic() - self.started) * 1000)}


class ReceiveJobs:
    """At most one running receive per node; finished jobs expire after FINISHED_TTL."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}

    def start_or_attach(self, node, operation_id, body, target, phase_source=lambda: None):
        """Return the job for this exact request, starting it when none exists.

        A different running request on the same node is refused as busy, the
        same answer the synchronous receiver gives for a held inbound lock.
        """
        digest = hashlib.sha256(body).hexdigest()
        node_key = str(node)
        key = (node_key, operation_id)
        with self._lock:
            self._expire()
            job = self._jobs.get(key)
            if job is not None and job.digest != digest:
                raise ValueError('Content sync operation ID belongs to another request')
            if job is not None and not (job.done.is_set() and job.error is not None):
                return job  # running, or finished with a result to hand over
            # A failed attempt (busy, rejected, conflict) is never re-served:
            # the retry runs the receive again, as the synchronous path does.
            if any(other.key[0] == node_key and not other.done.is_set()
                   for other in self._jobs.values()):
                from spikes.federation_sync import SyncBusy
                raise SyncBusy('Content receiver is busy', resource='incoming-capacity')
            job = _Job(key, digest, target, phase_source)
            self._jobs[key] = job
            job.thread.start()
            return job

    def _expire(self):
        now = time.monotonic()
        for key in [key for key, job in self._jobs.items()
                    if job.done.is_set() and now - job.finished_at > FINISHED_TTL]:
            del self._jobs[key]

    def running(self):
        with self._lock:
            return [job for job in self._jobs.values() if not job.done.is_set()]

    def drain(self, timeout):
        """Wait for running jobs within timeout; True when none is left.

        An unfinished job is then interrupted with the process, which is the
        same crash boundary as a killed synchronous receiver (journal recovery).
        """
        deadline = time.monotonic() + max(0, timeout)
        for job in self.running():
            job.done.wait(max(0, deadline - time.monotonic()))
        return not self.running()


JOBS = ReceiveJobs()
# A separate registry: a running content receive must not make the state
# answer busy, and the reverse. One state answer per node at a time.
STATE_JOBS = ReceiveJobs()


def error_frame(exc):
    from spikes.federation_sync import SyncBusy, SyncConflict
    from spikes.git_budget import GitDeadlineExceeded
    from spikes.request_ownership import ProjectBusy
    if isinstance(exc, (SyncBusy, ProjectBusy, GitDeadlineExceeded)):
        return {'type': 'error', 'status': 503, 'error': 'Content receiver is busy',
                'busy_resource': safe_busy_resource(getattr(
                    exc, 'busy_resource',
                    'git-budget' if isinstance(exc, GitDeadlineExceeded) else None)),
                'peer_phase': safe_peer_phase(getattr(exc, 'peer_phase', None))}
    if isinstance(exc, SyncConflict):
        return {'type': 'error', 'status': 409,
                'error': 'Content sync requires a conflict decision'}
    return {'type': 'error', 'status': 422, 'error': 'Content sync request rejected'}


def frame(value):
    raw = json.dumps(value, separators=(',', ':')).encode('ascii') + b'\n'
    require(len(raw) <= MAX_FRAME, 'Content sync frame exceeds limit')
    return raw


def stream(job, write, *, interval=None):
    """Write heartbeats until the job ends, then its terminal frame.

    Raises OSError when the sender went away; the job keeps running.
    """
    interval = HEARTBEAT_INTERVAL if interval is None else interval
    write(frame(job.heartbeat()))
    while not job.done.wait(interval):
        write(frame(job.heartbeat()))
    if job.error is not None:
        write(frame(job.error))
    else:
        write(frame({'type': 'result', 'length': len(job.result)}) + job.result)


def read_frames(readline, read, *, on_heartbeat=lambda frame: None, cancelled=lambda: False):
    """Sender side: consume heartbeats and return ('result', body) or ('error', frame)."""
    while True:
        line = readline(MAX_FRAME + 1)
        if not line.endswith(b'\n') and len(line) <= MAX_FRAME:
            # The peer stopped answering mid-stream; its job may still finish
            # and the next attempt of the same operation attaches or replays.
            raise TimeoutError('Peer closed the content sync stream')
        require(len(line) <= MAX_FRAME, 'Content sync frame exceeds limit')
        value = json.loads(line)
        require(isinstance(value, dict) and value.get('type') in {'heartbeat', 'result', 'error'},
                'Invalid content sync stream frame')
        if value['type'] == 'heartbeat':
            on_heartbeat(value)
            if cancelled():
                from spikes.federation_sync import SyncCancelled
                raise SyncCancelled('Content sync cancelled while the peer was working')
            continue
        if value['type'] == 'error':
            require(value.get('status') in {409, 422, 503}, 'Invalid content sync error frame')
            return 'error', value
        length = value.get('length')
        from spikes.federation_sync import MAX_BODY
        require(type(length) is int and 4 < length <= MAX_BODY, 'Invalid content sync result size')
        body = read(length)
        if len(body) != length:
            raise TimeoutError('Peer closed the content sync stream before the result')
        return 'result', body
