# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Deadline-aware shutdown of periodic background workers (AUDIT-B2-T3, A10).

A worker is reported unclean, and its live thread reference is retained, when
it does not finish within the deadline. Abandoning it at process exit is a
crash in an unknown phase; each worker's own journal or replay owns recovery.
"""
import logging
import sqlite3
import subprocess
import sys
import time

from spikes.request_ownership import ProjectBusy

_log = logging.getLogger('spikes.background')
# Failure classes that synchronization services already record as durable
# peer or replication state (offline, rejected, conflict, busy, error).
EXPECTED = (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, ProjectBusy)


def report_failure(worker, exc, *, target=None, expected=()):
    """Log a background failure instead of swallowing it (AUDIT-B4-T1, B-ODD-01).

    Expected classes are logged at info: only the exception class, never its
    message, which may carry project data. Any other class is a programming or
    unknown error: a warning with traceback for local diagnostics (the
    traceback includes the message; the log stays on this node).
    """
    known = isinstance(exc, EXPECTED + tuple(expected))
    _log.log(logging.INFO if known else logging.WARNING,
             'background_failed worker=%s target=%s reason=%s',
             worker, target or '-', type(exc).__name__,
             exc_info=None if known else exc)
    return known


def drain(thread, timeout):
    """Join within timeout; return (clean, thread or None). Never drop a live thread."""
    if thread is None:
        return True, None
    thread.join(timeout=max(0, timeout))
    if thread.is_alive():
        return False, thread
    return True, None


def stop_all(*schedulers, timeout=None, log=sys.stderr):
    """Signal every scheduler first, then drain them against one shared deadline.

    The default deadline is the longest declared STOP_TIMEOUT, not their sum.
    Returns {thread name: clean}; unclean workers are also logged.
    """
    for scheduler in schedulers:
        scheduler.stopping.set()
    budget = max((s.STOP_TIMEOUT for s in schedulers), default=0) if timeout is None else timeout
    deadline = time.monotonic() + budget
    result = {}
    for scheduler in schedulers:
        name = getattr(scheduler, 'NAME', type(scheduler).__name__)
        result[name] = scheduler.stop(timeout=deadline - time.monotonic())
        if not result[name] and log is not None:
            print(f'background_worker_unclean worker={name} deadline_s={budget:g}', file=log, flush=True)
    return result
