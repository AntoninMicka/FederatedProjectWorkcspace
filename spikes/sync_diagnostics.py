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

from spikes.request_ownership import safe_busy_resource

PUBLICATION_PHASES = ('receive-publication-pools', 'receive-publication-git',
                      'receive-publication-chats', 'receive-publication-pool-apply')
PEER_PHASES = frozenset({'receive-verify', 'receive-replay', 'receive-check-destination',
    'receive-verify-history', 'receive-publication', 'receive-prepare-response',
    *PUBLICATION_PHASES})


def safe_peer_phase(value):
    return value if isinstance(value, str) and value in PEER_PHASES else None


def current_phase():
    record = _current.get()
    return record.get('phase') if record is not None else None


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
            for _, peer, project, direction in keys
            if (value := snapshot(node, peer, project, direction=direction)) is not None]


def peer_progress(name):
    """Record the peer's phase reported by a heartbeat (fixed names only)."""
    record = _current.get()
    value = safe_peer_phase(name)
    if record is not None and value is not None:
        with _lock:
            record['peer_phase'] = value


SLOW_MS = 30000   # half the sender's content sync deadline


def phase(name):
    record = _current.get()
    if record is not None:
        with _lock:
            now = time.monotonic()
            _close_phase(record, now)
            record['phase'] = name
            record['phase_started'] = now


def _close_phase(record, now):
    # Phase names are fixed constants; durations carry no payload data.
    record.setdefault('durations', []).append(
        (record['phase'], round((now - record['phase_started']) * 1000)))


def _durations(record):
    return ','.join(f'{name}:{ms}' for name, ms in record.get('durations', ())) or 'none'


def snapshot(node, peer, project, *, direction=None):
    prefix = (str(Path(node).absolute()), peer, project)
    with _lock:
        if direction is None:
            keys = [key for key in _latest if key[:3] == prefix]
            record = _latest.get(keys[-1]) if keys else None
        else:
            record = _latest.get((*prefix, direction))
        if record is None:
            return None
        now = record.get('finished', time.monotonic())
        result = {'phase': record['phase'], 'state': record['state'],
                'direction': record['direction'],
                'elapsed_ms': round((now - record['started']) * 1000),
                'phase_elapsed_ms': round((now - record['phase_started']) * 1000),
                'error_type': record.get('error_type')}
        for field in ('busy_resource', 'peer_phase'):
            if field in record: result[field] = record[field]
        return result


def observed(function=None, *, direction='outbound'):
    if function is None:
        return lambda target: observed(target, direction=direction)
    if direction not in {'inbound', 'outbound'}:
        raise ValueError('Invalid sync diagnostic direction')
    @wraps(function)
    def run(first, peer_id, project_id, *args, **kwargs):
        # Control.synchronize and the direct transport share one observation.
        node = getattr(first, 'node', first)
        key = (str(Path(node).absolute()), peer_id, project_id, direction)
        current = _current.get()
        if current is not None and current['_key'] == key:
            return function(first, peer_id, project_id, *args, **kwargs)
        now = time.monotonic()
        record = dict(phase='prepare', state='running', started=now, phase_started=now,
                      direction=direction, _key=key)
        with _lock:
            _latest[key] = record
            _latest.move_to_end(key)
            while len(_latest) > LIMIT:
                _latest.popitem(last=False)
        token = _current.set(record)
        try:
            result = function(first, peer_id, project_id, *args, **kwargs)
        except Exception as exc:
            resource = safe_busy_resource(getattr(exc, 'busy_resource', None))
            peer_phase = safe_peer_phase(getattr(exc, 'peer_phase', None))
            with _lock:
                if resource != 'unknown': record['busy_resource'] = resource
                if peer_phase is not None and direction == 'outbound': record['peer_phase'] = peer_phase
                record.update(state='failed', error_type=type(exc).__name__,
                              finished=time.monotonic())
                _close_phase(record, record['finished'])
            # Exception text, paths, endpoints, headers and payloads are excluded.
            _log.warning('sync_failed phase=%s error_type=%s elapsed_ms=%d busy_resource=%s '
                         'peer_phase=%s phases=%s',
                         record['phase'], record['error_type'],
                         round((record['finished'] - now) * 1000), resource,
                         peer_phase or 'unknown', _durations(record))
            raise
        else:
            with _lock:
                record.update(state='finished', finished=time.monotonic())
                _close_phase(record, record['finished'])
            elapsed = round((record['finished'] - now) * 1000)
            if elapsed >= SLOW_MS:
                _log.warning('sync_slow direction=%s elapsed_ms=%d phases=%s',
                             direction, elapsed, _durations(record))
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

        @observed(direction='inbound')
        def invoke(node, peer_id, project_id):
            phase('receive-verify')
            return function(receiver, envelope, payload, *args, **kwargs)
        return invoke(receiver.node, peer, project)
    return run
