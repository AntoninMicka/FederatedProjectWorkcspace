# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared web/desktop control plane for one-shot personal replication."""
import fcntl
import os
import ssl
import subprocess
import threading
from uuid import uuid4

from spikes.administration import Administration, identifier
from spikes.project_replication import ReplicationConflict, ReplicationRejected, send
from spikes.network_backend import private_root
from spikes.projects import Projects
from spikes.transfer_outbox import (
    pending_transfer, replication_runtime, set_replication_runtime,
)


class ReplicationControl:
    def __init__(self, node, *, deployment):
        self.node = node
        self.deployment = deployment
        self.administration = Administration(node, deployment=deployment)

    def statuses(self, replications, node_id):
        runtime = replication_runtime(self.node)
        result = {}
        for replication in replications:
            replication_id = replication['spec']['id']
            if replication['revocation']:
                result[replication_id] = {'state': 'revoked'}
            elif not replication['authorized']:
                result[replication_id] = {'state': 'waiting'}
            elif not replication['enabled']:
                result[replication_id] = {'state': 'disabled'}
            else:
                result[replication_id] = runtime.get(replication_id, {'state': 'idle'})
            result[replication_id]['local_role'] = next(
                participant['role'] for participant in replication['spec']['nodes']
                if participant['node_id'] == node_id)
        return result

    def synchronize(self, replication_id):
        identifier(replication_id)
        root = private_root(self.node)
        fd = os.open(root / 'replication-control.lock',
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._synchronize(replication_id)

    def _synchronize(self, replication_id):
        authority = self.administration.active_replication(replication_id, 'primary')
        spec = authority['spec']
        remote_id = authority['remote']['node_id']
        saved = pending_transfer(self.node, spec['project_id'], remote_id)
        previous = replication_runtime(self.node, replication_id) or {}
        current = Projects(self.node).workspace(spec['project_id'], blocking=False).git.head()
        if saved:
            operation_id = saved['operation_id']
            expected_base = saved['context'].get('expected_base')
        else:
            if previous.get('last_head') == current:
                return set_replication_runtime(
                    self.node, replication_id, 'idle', last_head=current,
                    detail='Replica already matches the primary HEAD')
            operation_id = str(uuid4())
            expected_base = previous.get('last_head')
        set_replication_runtime(
            self.node, replication_id, 'pending', operation_id=operation_id,
            last_head=previous.get('last_head'))
        try:
            result = send(self.node, replication_id, operation_id, expected_base,
                          deployment=self.deployment)
        except ReplicationConflict as exc:
            set_replication_runtime(
                self.node, replication_id, 'conflict', operation_id=operation_id,
                last_head=previous.get('last_head'), detail=str(exc))
            raise
        except ReplicationRejected as exc:
            set_replication_runtime(
                self.node, replication_id, 'rejected', operation_id=operation_id,
                last_head=previous.get('last_head'), detail=str(exc))
            raise
        except (ConnectionError, TimeoutError, ssl.SSLError, OSError) as exc:
            set_replication_runtime(
                self.node, replication_id, 'offline', operation_id=operation_id,
                last_head=previous.get('last_head'), detail=type(exc).__name__)
            raise
        except (ValueError, subprocess.SubprocessError) as exc:
            set_replication_runtime(
                self.node, replication_id, 'error', operation_id=operation_id,
                last_head=previous.get('last_head'), detail=str(exc))
            raise
        return set_replication_runtime(
            self.node, replication_id, 'idle', operation_id=operation_id,
            last_head=result['head'], detail='Replication completed')

    def run_enabled(self):
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        state = self.administration.request(actor, {'action': 'list'})
        for replication in state['replications']:
            if (replication['active'] and not replication['revocation']
                    and replication['local_role'] == 'primary'):
                try:
                    self.synchronize(replication['spec']['id'])
                except Exception:
                    pass  # Durable status records the bounded retry outcome.


class ReplicationScheduler:
    """Periodically reconcile enabled primary grants without blocking the UI."""
    def __init__(self, node, *, deployment, interval=60):
        self.control = ReplicationControl(node, deployment=deployment)
        self.interval = interval
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(
            target=self._run, name='project-replication', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            self.control.run_enabled()
            self.stopping.wait(self.interval)

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=35)
            self.thread = None
