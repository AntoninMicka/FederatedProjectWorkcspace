# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Deadline-aware shutdown of periodic background workers (AUDIT-B2-T3, A10).

A worker is reported unclean, and its live thread reference is retained, when
it does not finish within the deadline. Abandoning it at process exit is a
crash in an unknown phase; each worker's own journal or replay owns recovery.
"""
import sys
import time


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
