# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded disposable history validator; never a project writer or authority."""
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from spikes.git_budget import (DEFAULT_GIT_BUDGET, GitDeadlineExceeded,
                               check_deadline, effective_deadline, git_budget)
from spikes.metadata import ValidationError, require
from spikes.request_ownership import ProjectBusy

_capacity = threading.BoundedSemaphore(1)
_root = Path(__file__).resolve().parents[1]
_popen = subprocess.Popen


def _stop(process):
    """Reap the validator AND its Git children before deleting temporary input."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def validate_histories(git, heads, project_id, allowed_privacy):
    """Keep CPU-heavy Python validation outside HTTP threads, without queueing."""
    if not _capacity.acquire(blocking=False):
        raise ProjectBusy('History validation capacity is occupied', resource='history-validation')
    process = None
    try:
        deadline = effective_deadline(git.deadline)
        if deadline is None:
            deadline = time.monotonic() + DEFAULT_GIT_BUDGET
        check_deadline(deadline)
        request = dict(repo=str(git.root.absolute()), heads=list(heads),
                       project_id=project_id, privacy=sorted(allowed_privacy), deadline=deadline)
        # Use the active immutable application source, independent of cwd,
        # PYTHONPATH, user site-packages or inherited Git configuration.
        command = [sys.executable, '-I', '-c',
                   'import sys,runpy;sys.path.insert(0,' + repr(str(_root)) + ');'
                   'runpy.run_module("spikes.history_validation",run_name="__main__")']
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('GIT_', 'PYTHON'))}
        try:
            process = _popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        except OSError as exc:
            raise ProjectBusy('History validator could not start',
                              resource='history-validation') from exc
        try:
            out, _ = process.communicate(json.dumps(request).encode(),
                                         timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise GitDeadlineExceeded('History validator exceeded its deadline') from exc
        check_deadline(deadline)
        if process.returncode != 0 or len(out) > 4096:
            raise ProjectBusy('History validator failed', resource='history-validation')
        try:
            result = json.loads(out)
            require(isinstance(result, dict) and set(result) == {'outcome', 'message'},
                    'Invalid validator response')
            require(isinstance(result['message'], str) and len(result['message']) <= 1000,
                    'Invalid validator response')
        except (ValueError, TypeError) as exc:
            raise ProjectBusy('History validator response unavailable',
                              resource='history-validation') from exc
        if result['outcome'] == 'deadline':
            raise GitDeadlineExceeded('History validator exceeded its deadline')
        if result['outcome'] == 'invalid':
            raise ValidationError(result['message'])
        if result['outcome'] != 'ok':
            raise ProjectBusy('History validator failed', resource='history-validation')
    finally:
        if process is not None:
            # Even if the Python worker exited, an interrupted Git grandchild
            # can remain in its group. Never leave it using temporary inputs.
            _stop(process)
        _capacity.release()


def _validate(request):
    from spikes.administration import identifier
    from spikes.git_transfer import validate_history
    from spikes.storage import Git
    require(isinstance(request, dict) and set(request) == {
        'repo', 'heads', 'project_id', 'privacy', 'deadline'}, 'Invalid validation request')
    identifier(request['project_id'])
    heads, deadline = request['heads'], request['deadline']
    require(isinstance(heads, list) and 0 < len(heads) <= 64
            and all(isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head)
                    for head in heads), 'Invalid validation heads')
    require(type(deadline) in (int, float) and math.isfinite(deadline),
            'Invalid validation deadline')
    require(isinstance(request['privacy'], list)
            and request['privacy'] and all(isinstance(v, str) for v in request['privacy']),
            'Invalid validation privacy')
    check_deadline(deadline)
    git = Git(Path(request['repo']), deadline=deadline)
    with git_budget(min(DEFAULT_GIT_BUDGET, deadline - time.monotonic())):
        # Every selected branch is checked, including shared ancestors. No
        # authorization/validation result survives this disposable process.
        for head in heads:
            validate_history(git, head, request['project_id'], frozenset(request['privacy']))


def main():
    try:
        if hasattr(os, 'nice'):
            os.nice(10)
        raw = sys.stdin.buffer.read(16385)
        require(len(raw) <= 16384, 'Validation request too large')
        _validate(json.loads(raw))
        result = dict(outcome='ok', message='')
    except GitDeadlineExceeded:
        result = dict(outcome='deadline', message='')
    except ValueError as exc:
        result = dict(outcome='invalid', message=str(exc)[:1000])
    except Exception:
        result = dict(outcome='failed', message='')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
