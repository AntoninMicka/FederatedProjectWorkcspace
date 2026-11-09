# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded process-local sync observations; never transport or recovery authority."""
from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
import logging
from pathlib import Path
import threading
import time
from uuid import UUID


_current = ContextVar('sync_diagnostic', default=None)
_lock = threading.Lock()
_latest = OrderedDict()
_log = logging.getLogger(__name__)
LIMIT = 64


def observations(node):
    root = str(Path(node).absolute())
    with _lock:
        keys = [key for key in _latest if key[0] == root]
    return [{'peer_id': peer, 'project_id': project, 'diagnostic': value}
            for _, peer, project in keys
            if (value := snapshot(node, peer, project)) is not None]


def phase(name):
    record = _current.get()
    if record is not None:
        with _lock:
            record['phase'] = name
            record['phase_started'] = time.monotonic()


def snapshot(node, peer, project):
    key = (str(Path(node).absolute()), peer, project)
    with _lock:
        record = _latest.get(key)
        if record is None:
            return None
        now = record.get('finished', time.monotonic())
        return {'phase': record['phase'], 'state': record['state'],
                'elapsed_ms': round((now - record['started']) * 1000),
                'phase_elapsed_ms': round((now - record['phase_started']) * 1000),
                'error_type': record.get('error_type')}


def observed(function):
    @wraps(function)
    def run(first, peer_id, project_id, *args, **kwargs):
        # Control.synchronize and the direct transport share one observation.
        if _current.get() is not None:
            return function(first, peer_id, project_id, *args, **kwargs)
        node = getattr(first, 'node', first)
        key = (str(Path(node).absolute()), peer_id, project_id)
        now = time.monotonic()
        record = dict(phase='prepare', state='running', started=now, phase_started=now)
        with _lock:
            _latest[key] = record
            _latest.move_to_end(key)
            while len(_latest) > LIMIT:
                _latest.popitem(last=False)
        token = _current.set(record)
        try:
            result = function(first, peer_id, project_id, *args, **kwargs)
        except Exception as exc:
            with _lock:
                record.update(state='failed', error_type=type(exc).__name__,
                              finished=time.monotonic())
            # Exception text, paths, endpoints, headers and payloads are excluded.
            _log.warning('sync_failed phase=%s error_type=%s elapsed_ms=%d',
                         record['phase'], record['error_type'],
                         round((record['finished'] - now) * 1000))
            raise
        else:
            with _lock:
                record.update(state='finished', finished=time.monotonic())
            return result
        finally:
            _current.reset(token)
    return run


def received(function):
    """Observe valid-shaped inbound identities without retaining untrusted bytes."""
    @wraps(function)
    def run(receiver, envelope, payload, *args, **kwargs):
        try:
            exchange = envelope['exchange']
            peer, project = exchange['source_node_id'], exchange['project_id']
            if str(UUID(peer)) != peer or str(UUID(project)) != project:
                raise ValueError('Noncanonical identity')
        except (KeyError, TypeError, ValueError, AttributeError):
            return function(receiver, envelope, payload, *args, **kwargs)

        @observed
        def invoke(node, peer_id, project_id):
            phase('receive-verify')
            return function(receiver, envelope, payload, *args, **kwargs)
        return invoke(receiver.node, peer, project)
    return run
