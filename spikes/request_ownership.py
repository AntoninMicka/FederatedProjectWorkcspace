# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Ephemeral HTTP ownership; persistent journals remain the write authority."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading


bounded_project_wait = ContextVar('bounded_project_wait', default=False)


class ProjectBusy(Exception):
    """A project writer is busy; no automatic retry is implied."""
    def __init__(self, message, *, outcome='unknown'):
        super().__init__(message)
        self.outcome = outcome


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
                raise ProjectBusy('Project HTTP owner is busy', outcome='not-started')
            yield
        finally:
            if acquired:
                entry[0].release()
            with self.guard:
                entry[1] -= 1
                if not entry[1]:
                    del self.entries[project_id]


@contextmanager
def bounded_project_requests():
    token = bounded_project_wait.set(True)
    try:
        yield
    finally:
        bounded_project_wait.reset(token)
