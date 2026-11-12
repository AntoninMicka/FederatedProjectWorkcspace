# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Ephemeral HTTP ownership; persistent journals remain the write authority."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import fcntl
import time


bounded_project_wait = ContextVar('bounded_project_wait', default=False)


BUSY_RESOURCES = frozenset({
    'unknown', 'incoming-capacity', 'outbound-capacity', 'project-journal',
    'project-index', 'sync-journal', 'node-registry', 'node-operations',
    'project-admission', 'process-owner', 'native-owner', 'sqlite',
    'snapshot-changed', 'pending-publication', 'git-budget', 'history-validation',
    'execution-capacity',
})
_RESOURCE_LABELS = {
    'Project journal': 'project-journal', 'Project index': 'project-index',
    'Content synchronization journal': 'sync-journal',
    'Node registry': 'node-registry',
}


def safe_busy_resource(value):
    return value if isinstance(value, str) and value in BUSY_RESOURCES else 'unknown'


def busy_resource_for(label, default):
    return _RESOURCE_LABELS.get(label, default) if isinstance(label, str) else default


class ProjectBusy(Exception):
    """A project writer is busy; no automatic retry is implied."""
    def __init__(self, message, *, outcome='unknown', resource='unknown'):
        super().__init__(message)
        self.outcome = outcome
        self.busy_resource = safe_busy_resource(resource)


def bounded_flock(handle, mode, *, resource):
    """Keep native locking unchanged; never park an HTTP worker on a flock."""
    bounded = bounded_project_wait.get()
    try:
        fcntl.flock(handle, mode | (fcntl.LOCK_NB if bounded else 0))
    except BlockingIOError as exc:
        if bounded:
            raise ProjectBusy(resource + ' is busy', resource=busy_resource_for(resource, 'native-owner')) from exc
        raise


@contextmanager
def bounded_process_lock(lock, *, resource):
    """Retain reentrancy and ownership while bounding HTTP contention."""
    acquired = (lock.acquire(timeout=0.1) if bounded_project_wait.get()
                else lock.acquire())
    if not acquired:
        raise ProjectBusy(resource + ' is busy', resource=busy_resource_for(resource, 'process-owner'))
    try:
        yield
    finally:
        lock.release()


class ProjectLanes:
    """One bounded owner per active project, with no retained idle keys."""
    def __init__(self):
        self.guard = threading.Lock()
        self.entries = {}

    @contextmanager
    def acquire(self, project_id, timeout):
        with self.guard:
            entry = self.entries.setdefault(project_id, [threading.Lock(), 0])
            entry[1] += 1
        acquired = False
        try:
            acquired = entry[0].acquire(timeout=timeout)
            if not acquired:
                raise ProjectBusy('Project HTTP owner is busy', outcome='not-started', resource='project-admission')
            yield
        finally:
            if acquired:
                entry[0].release()
            with self.guard:
                entry[1] -= 1
                if not entry[1]:
                    del self.entries[project_id]


class ConcurrentReadLane:
    """Bounded reader capacity, without a queue of waiting HTTP workers."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.guard = threading.Lock()
        self.active = 0

    def acquire(self, blocking=True, timeout=-1):
        with self.guard:
            if self.active >= self.capacity:
                return False
            self.active += 1
            return True

    def release(self):
        with self.guard:
            if not self.active:
                raise RuntimeError('release idle read lane')
            self.active -= 1

    def locked(self):
        with self.guard:
            return self.active >= self.capacity


class BoundedWaitingLane:
    """One owner and one waiting HTTP worker; newcomers cannot pass the waiter."""
    def __init__(self):
        self.condition = threading.Condition()
        self.active = False
        self.waiting = False
        self.closed = False

    def acquire(self, blocking=True, timeout=-1):
        with self.condition:
            if self.closed:
                return False
            if not self.active and not self.waiting:
                self.active = True
                return True
            if not blocking or self.waiting:
                return False
            deadline = None if timeout < 0 else time.monotonic() + timeout
            self.waiting = True
            try:
                while self.active and not self.closed:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self.condition.wait(remaining)
                if self.closed or (deadline is not None and time.monotonic() >= deadline):
                    return False
                self.active = True
                return True
            finally:
                self.waiting = False

    def release(self):
        with self.condition:
            if not self.active:
                raise RuntimeError('release unlocked lane')
            self.active = False
            self.condition.notify_all()

    def locked(self):
        with self.condition:
            return self.active

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


@contextmanager
def bounded_project_requests():
    token = bounded_project_wait.set(True)
    try:
        yield
    finally:
        bounded_project_wait.reset(token)
