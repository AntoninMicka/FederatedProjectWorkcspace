# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Cooperative elapsed budget shared by nested local Git validation work."""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import subprocess
import time


DEFAULT_GIT_BUDGET = 60
_current_deadline = ContextVar('git_operation_deadline', default=None)


class GitDeadlineExceeded(TimeoutError):
    """Validation did not finish; this is not evidence of invalid peer content."""


def effective_deadline(deadline=None):
    current = _current_deadline.get()
    if current is None:
        return deadline
    return current if deadline is None else min(current, deadline)


def check_deadline(deadline=None):
    deadline = effective_deadline(deadline)
    if deadline is not None and time.monotonic() >= deadline:
        raise GitDeadlineExceeded('Git operation deadline exceeded')


@contextmanager
def git_budget(seconds=None):
    """Nested scopes never extend their caller; ownership and recovery stay native."""
    seconds = DEFAULT_GIT_BUDGET if seconds is None else seconds
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('Expected a positive finite Git budget')
    token = _current_deadline.set(effective_deadline(time.monotonic() + seconds))
    try:
        check_deadline()
        try:
            yield
        except subprocess.TimeoutExpired as exc:
            raise GitDeadlineExceeded('Git subprocess timed out') from exc
        check_deadline()
    finally:
        _current_deadline.reset(token)
