# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Internal coordinator ledger, not an execution grant or dispatch API.

ADR 0080: the authenticated agreement/worker layer must validate authority
before calling this primitive. Nothing here starts a connector or a model.
All transitions share ReportingScheduler's owner checks and FULL transaction.
"""
from copy import deepcopy
import json
import math

from spikes.metadata import require, uuid
from spikes.reporting_schema import digest, encoded, fields, hex_id


def logical_key(value):
    fields(value, 'project_id project_ref watch_id input_id effect_kind slot')
    for name in ('project_id', 'watch_id', 'input_id'):
        uuid(value[name])
    for name in ('project_ref', 'slot'):
        require(isinstance(value[name], str) and 0 < len(value[name]) <= 512,
                'Invalid logical effect scope')
    require(value['effect_kind'] in {'rss.fetch', 'model.generate'}, 'Invalid effect kind')
    return digest(encoded(value))


class ExecutionJournal:
    def __init__(self, scheduler):
        self.scheduler = scheduler

    @staticmethod
    def _read(db, effect_id):
        hex_id(effect_id)
        row = db.execute('SELECT document FROM execution_effects WHERE id=?', (effect_id,)).fetchone()
        require(row is not None, 'Unknown execution effect')
        return json.loads(row[0])

    @staticmethod
    def _save(db, record):
        db.execute('UPDATE execution_effects SET document=? WHERE id=?',
                   (encoded(record), record['effect_id']))

    def get(self, effect_id):
        with self.scheduler.db() as db:
            return self._read(db, effect_id)

    def _deadline(self, deadline):
        require(type(deadline) in {int, float} and math.isfinite(deadline) and
                self.scheduler.now() < deadline <= self.scheduler.now() + 3600,
                'Begin deadline must be within one hour')

    def reserve(self, key, intent, assignment, begin_deadline):
        effect_id = logical_key(key)
        fields(assignment, 'agreement_id agreement_revision coordinator_epoch executor_node_id assignment_revision')
        uuid(assignment['agreement_id']);uuid(assignment['executor_node_id'])
        for name in ('agreement_revision', 'coordinator_epoch', 'assignment_revision'):
            require(type(assignment[name]) is int and assignment[name] > 0, 'Invalid assignment revision')
        require(isinstance(intent, dict) and len(encoded(intent)) <= 1024 * 1024,
                'Invalid or oversized execution intent')
        intent_hash = digest(encoded(intent))
        stream = digest(encoded({k: v for k, v in key.items() if k != 'slot'}))
        with self.scheduler.db() as db:
            row = db.execute('SELECT document FROM execution_effects WHERE id=?', (effect_id,)).fetchone()
            if row is not None:
                existing = json.loads(row[0])
                require(existing['intent_sha256'] == intent_hash and existing['assignment'] == assignment,
                        'Logical effect already pinned; revision cannot bypass original reservation')
                return existing
            self._deadline(begin_deadline)
            for row in db.execute('SELECT document FROM execution_effects WHERE stream=?', (stream,)):
                require(json.loads(row[0])['state'] == 'completed', 'Previous effect blocks this stream')
            record = dict(effect_id=effect_id, key=deepcopy(key), intent=deepcopy(intent),
                          intent_sha256=intent_hash, assignment=deepcopy(assignment), fence=1,
                          begin_deadline=begin_deadline, state='reserved', result=None,
                          history=[dict(event='reserved', at=self.scheduler.stamp(), fence=1,
                                        assignment=deepcopy(assignment))])
            db.execute('INSERT INTO execution_effects VALUES(?,?,?)', (effect_id, stream, encoded(record)))
        return record

    @staticmethod
    def _guard(record, executor_node_id, fence, intent_sha256):
        require(type(fence) is int and fence == record['fence'] and
                executor_node_id == record['assignment']['executor_node_id'] and
                intent_sha256 == record['intent_sha256'], 'Stale or mismatched execution ticket')

    def begin(self, effect_id, executor_node_id, fence, intent_sha256):
        """Commit before dispatch. Repeated begin is observation, never permission to retry."""
        with self.scheduler.db() as db:
            record = self._read(db, effect_id)
            self._guard(record, executor_node_id, fence, intent_sha256)
            require(record['state'] == 'reserved', 'Effect already begun; reconcile original effect')
            require(self.scheduler.now() < record['begin_deadline'], 'Execution ticket expired before begin')
            record['state'] = 'begun'
            record['history'].append(dict(event='begun', at=self.scheduler.stamp(), fence=fence))
            self._save(db, record)
        return record

    def unknown(self, effect_id, executor_node_id, fence, intent_sha256):
        with self.scheduler.db() as db:
            record = self._read(db, effect_id)
            self._guard(record, executor_node_id, fence, intent_sha256)
            require(record['state'] in {'begun', 'unknown'}, 'Only dispatched effects can become unknown')
            if record['state'] != 'unknown':
                record['state'] = 'unknown'
                record['history'].append(dict(event='unknown', at=self.scheduler.stamp(), fence=fence))
                self._save(db, record)
        return record

    def result(self, effect_id, executor_node_id, fence, intent_sha256, descriptor):
        """Persist a descriptor without claiming a Workspace import or completed run."""
        fields(descriptor, 'payload_sha256 backend_effect_id')
        hex_id(descriptor['payload_sha256'])
        require(isinstance(descriptor['backend_effect_id'], str) and
                0 < len(descriptor['backend_effect_id']) <= 256, 'Invalid backend effect ID')
        with self.scheduler.db() as db:
            record = self._read(db, effect_id)
            self._guard(record, executor_node_id, fence, intent_sha256)
            require(record['state'] in {'begun', 'unknown', 'result-awaiting-import'}, 'Effect has not begun')
            if record['state'] == 'result-awaiting-import':
                require(record['result'] == descriptor, 'Result cannot be replaced')
            else:
                record['state'] = 'result-awaiting-import';record['result'] = deepcopy(descriptor)
                record['history'].append(dict(event='result', at=self.scheduler.stamp(), fence=fence))
                self._save(db, record)
        return record

    def reassign_unstarted(self, effect_id, executor_node_id, fence, intent_sha256,
                          *, new_executor_node_id, begin_deadline, confirmed=False):
        """Only an unstarted reservation can move without backend no-effect reconciliation.

        Unknown/begun takeover intentionally has no API until authenticated
        backend reconciliation is integrated; an operator boolean is insufficient.
        """
        require(confirmed is True, 'Explicit reassignment confirmation required')
        uuid(new_executor_node_id);self._deadline(begin_deadline)
        with self.scheduler.db() as db:
            record = self._read(db, effect_id)
            self._guard(record, executor_node_id, fence, intent_sha256)
            require(record['state'] == 'reserved', 'Dispatched effect requires backend reconciliation')
            record['fence'] += 1
            record['assignment']['assignment_revision'] += 1
            record['assignment']['executor_node_id'] = new_executor_node_id
            record['begin_deadline'] = begin_deadline
            record['history'].append(dict(event='reassigned', at=self.scheduler.stamp(),
                                          fence=record['fence'], assignment=deepcopy(record['assignment'])))
            self._save(db, record)
        return record
