# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from datetime import datetime
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata import ValidationError, require
from spikes.monitoring import Monitoring
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.projects import Projects
from spikes.reporting import Reporting
from spikes.reporting_schema import digest, encoded, period as validate_period
from spikes.reporting_scheduler import ReportingScheduler, calendar_period
from tests import test_reporting as fixtures


def definition(title='Daily collection', kind='daily', *, upstream=None):
    input_ = (dict(id=str(uuid4()), kind='watch', watch_id=upstream) if upstream else
              dict(id=str(uuid4()), kind='external', connector='rss-atom',
                   locator='https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313',
                   poll=dict(seconds=900), access=dict(reviewed=True, capture_allowed=True,
                       terms='Synthetic test authorization', retention='Synthetic test retention')))
    return dict(schema='fpw-reporting-watch-v1', title=title, goal='Track evidence and change',
        scope=dict(entities=[], categories=[], geographies=[], tags=['test']), active=True,
        schedule=dict(kind=kind, timezone='Europe/Prague', start='2026-03-01'), inputs=[input_],
        selection=dict(revision='1', instructions='Select relevant findings'),
        evaluation=dict(revision='1', instructions='Separate evidence from assertions'),
        report=dict(mode='collect-only' if upstream is None else 'deterministic',
                    instructions='Collect findings' if upstream is None else 'Summarize published inputs',
                    formats=['findings'] if upstream is None else ['markdown'], language='cs',
                    required_sections=[] if upstream is None else ['# Přehled', '## Omezení']),
        placement=dict(mode='local', node_id=None, capabilities=[]))


class WatchCalendarTests(unittest.TestCase):
    def test_daily_calendar_respects_spring_and_autumn_dst(self):
        for start, seconds in [('2026-03-29T00:00:00+01:00', 23*3600),
                               ('2026-10-25T00:00:00+02:00', 25*3600)]:
            value = calendar_period(start, 'daily', 'Europe/Prague', 'iso-calendar-v1')
            delta = datetime.fromisoformat(value['end_utc'].replace('Z', '+00:00')) - datetime.fromisoformat(value['start_utc'].replace('Z', '+00:00'))
            self.assertEqual(delta.total_seconds(), seconds)
            bad = deepcopy(value); bad['kind'] = 'weekly'
            with self.assertRaises(ValidationError): validate_period(bad)


class MonitoringDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.service = MonitoringDefinitions(self.f.node)
        self.pid = self.f.project

    def request(self, value, identity=None, previous=None, privacy='project'):
        return dict(project_id=self.pid, base_head=self.f.git.head(), watch_id=identity or str(uuid4()),
                    previous=previous or [], privacy=privacy, definition=deepcopy(value))

    def save(self, value, identity=None, previous=None, privacy='project'):
        return self.service.save(self.request(value, identity, previous, privacy), str(uuid4()))

    def chain(self):
        daily = self.save(definition())
        weekly = self.save(definition('Weekly summary', 'weekly', upstream=daily['watch_id']))
        monthly = self.save(definition('Monthly synthesis', 'monthly', upstream=weekly['watch_id']))
        return daily, weekly, monthly

    def test_three_independent_watches_default_to_published_upstream_reports(self):
        daily, weekly, monthly = self.chain()
        rows = self.service.read(self.pid)['definitions']
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['definition']['schedule']['kind'] for r in rows}, {'daily', 'weekly', 'monthly'})
        for row in rows:
            self.assertEqual(row['runtime_state'], 'not-connected')
            item = row['definition']['inputs'][0]
            if item['kind'] == 'watch':
                self.assertEqual(item['take'], 'reports'); self.assertFalse(item['include_drafts'])
        monitoring = Monitoring(self.f.node, Projects(self.f.node))
        self.assertEqual(monitoring.view(self.pid)['definitions'], rows)
        self.assertEqual(monitoring.watches(*monitoring._data(self.pid)[2:4]), [])

    def test_poll_change_preserves_report_schedule_and_old_definition_bytes(self):
        initial = self.save(definition())
        row = self.service.read(self.pid)['definitions'][0]
        value = deepcopy(row['definition']); value['inputs'][0]['poll']['seconds'] = 1800
        updated = self.save(value, initial['watch_id'], [initial['definition_ref']])
        self.assertNotEqual(initial['definition_ref']['artifact_id'], updated['definition_ref']['artifact_id'])
        self.assertEqual(self.service.read(self.pid)['definitions'][0]['definition']['schedule'], row['definition']['schedule'])
        pin = initial['definition_ref']
        old = self.f.git.snapshot(pin['commit_id'])[pin['path']]
        self.assertEqual(digest(old), pin['sha256'])
        self.assertEqual(json.loads(old)['value']['inputs'][0]['poll']['seconds'], 900)

    def test_saved_run_freezes_definition_rules_and_upstream_revision(self):
        daily, weekly, _ = self.chain()
        period = calendar_period('2026-03-23T00:00:00+01:00', 'weekly', 'Europe/Prague', 'iso-calendar-v1')
        run_id = str(uuid4())
        run = self.service.prepare_run(self.pid, weekly['definition_ref'], period, run_id)
        self.assertEqual(run['state'], 'prepared')
        frozen = deepcopy(run)
        rules_raw = self.f.git.snapshot(run['rules_ref']['commit_id'])[run['rules_ref']['path']]
        rules = json.loads(rules_raw)
        self.assertEqual(rules['input_definitions'][0]['definition_ref']['artifact_id'], daily['definition_ref']['artifact_id'])
        rows = self.service.read(self.pid)['definitions']
        weekly_row = next(r for r in rows if r['watch_id'] == weekly['watch_id'])
        value = deepcopy(weekly_row['definition']); value['evaluation']['revision'] = '2'
        value['evaluation']['instructions'] = 'Revised methodology'
        revised = self.save(value, weekly['watch_id'], [weekly['definition_ref']])
        self.assertEqual(ReportingScheduler(self.f.node).get(run_id), frozen)
        self.assertEqual(self.service.prepare_run(self.pid, weekly['definition_ref'], period, run_id), frozen)
        self.assertEqual(self.f.git.snapshot(run['rules_ref']['commit_id'])[run['rules_ref']['path']], rules_raw)
        with self.assertRaisesRegex(ValidationError, 'superseded'):
            self.service.prepare_run(self.pid, weekly['definition_ref'], period, str(uuid4()))
        new = self.service.prepare_run(self.pid, revised['definition_ref'], period, str(uuid4()))
        self.assertNotEqual(new['task_ref']['artifact_id'], run['task_ref']['artifact_id'])
        self.assertNotEqual(new['rules_ref'], run['rules_ref'])

    def test_run_replay_does_not_create_artifacts_and_changed_intent_is_rejected(self):
        daily, weekly, _ = self.chain()
        period = calendar_period('2026-03-23T00:00:00+01:00', 'weekly', 'Europe/Prague', 'iso-calendar-v1')
        run_id = str(uuid4()); first = self.service.prepare_run(self.pid, weekly['definition_ref'], period, run_id)
        head = self.f.git.head()
        self.assertEqual(self.service.prepare_run(self.pid, weekly['definition_ref'], period, run_id), first)
        self.assertEqual(self.f.git.head(), head)
        with self.assertRaisesRegex(ValidationError, 'another watch intent'):
            self.service.prepare_run(self.pid, daily['definition_ref'], period, run_id)

    def test_interruption_before_run_reservation_reuses_materialization_receipts(self):
        _, weekly, _ = self.chain()
        period = calendar_period('2026-03-23T00:00:00+01:00', 'weekly', 'Europe/Prague', 'iso-calendar-v1')
        run_id = str(uuid4())
        with patch.object(ReportingScheduler, 'enqueue', side_effect=OSError('interrupted before reservation')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.service.prepare_run(self.pid, weekly['definition_ref'], period, run_id)
        head = self.f.git.head()
        resumed = MonitoringDefinitions(self.f.node).prepare_run(self.pid, weekly['definition_ref'], period, run_id)
        self.assertEqual(resumed['state'], 'prepared')
        self.assertEqual(self.f.git.head(), head)

    def test_readonly_guard_prevents_definition_write(self):
        request = self.request(definition()); head = self.f.git.head()
        readonly = self.f.ws
        readonly.write_guard = lambda: require(False, 'read-only project')
        with patch.object(self.service.reporting.artifacts, 'workspace', return_value=readonly):
            with self.assertRaisesRegex(ValidationError, 'read-only'):
                self.service.save(request, str(uuid4()))
        self.assertEqual(self.f.git.head(), head)

    def test_cycles_missing_targets_self_links_and_privacy_are_rejected_before_commit(self):
        daily, weekly, monthly = self.chain()
        current = self.f.git.head()
        cyclic = definition('Cycle', upstream=monthly['watch_id'])
        with self.assertRaisesRegex(ValidationError, 'Cyclic'):
            self.save(cyclic, daily['watch_id'], [daily['definition_ref']])
        for target in [str(uuid4()), daily['watch_id']]:
            value = definition('Invalid link', upstream=target)
            with self.assertRaises(ValidationError):
                self.save(value, daily['watch_id'], [daily['definition_ref']])
        with self.assertRaisesRegex(ValidationError, 'privacy'):
            self.save(definition('Public consumer', upstream=weekly['watch_id']), privacy='public')
        self.assertEqual(self.f.git.head(), current)
        self.assertEqual(self.f.git.run('status', '--porcelain').stdout, '')

    def test_invalid_active_definitions_are_not_persisted(self):
        cases = []
        for path, value in [('inputs', []), ('active', 'true'), ('unknown', 'field')]:
            draft = definition(); draft[path] = value; cases.append(draft)
        draft = definition(); draft['inputs'][0]['poll']['seconds'] = 0; cases.append(draft)
        draft = definition(); draft['inputs'][0]['access']['reviewed'] = False; cases.append(draft)
        draft = definition(); draft['schedule']['timezone'] = 'missing/zone'; cases.append(draft)
        draft = definition(); draft['report']['mode'] = 'llm'; cases.append(draft)
        draft = definition(); draft['placement']['mode'] = 'node'; cases.append(draft)
        draft = definition(); draft['inputs'][0]['credentials'] = 'forbidden'; cases.append(draft)
        head = self.f.git.head()
        for value in cases:
            with self.subTest(value=value), self.assertRaises((ValidationError, ValueError)):
                self.save(value)
            self.assertEqual(self.f.git.head(), head)

    def test_local_only_external_network_and_unrequested_drafts_fail_closed(self):
        with self.assertRaisesRegex(ValidationError, 'Local-only'):
            self.save(definition(), privacy='local-only')
        daily = self.save(definition())
        value = definition('Explicit drafts', 'weekly', upstream=daily['watch_id'])
        value['inputs'][0].update(take='reports', include_drafts=True)
        saved = self.save(value)
        row = next(r for r in self.service.read(self.pid)['definitions'] if r['watch_id'] == saved['watch_id'])
        self.assertTrue(row['definition']['inputs'][0]['include_drafts'])
        value['inputs'][0]['take'] = 'findings'
        with self.assertRaisesRegex(ValidationError, 'Draft'):
            self.save(value)

    def test_stale_head_and_same_operation_replay(self):
        request = self.request(definition()); operation = str(uuid4())
        first = self.service.save(request, operation)
        head = self.f.git.head()
        self.assertEqual(self.service.save(request, operation), first)
        self.assertEqual(self.f.git.head(), head)
        request['watch_id'] = str(uuid4())
        with self.assertRaisesRegex(ValidationError, 'changed|Project'):
            self.service.save(request, str(uuid4()))

    def test_generic_reporting_writer_cannot_bypass_watch_graph_validation(self):
        value = definition('Missing', upstream=str(uuid4()))
        value['inputs'][0].update(take='reports', include_drafts=False)
        with self.assertRaisesRegex(ValidationError, 'target is missing'):
            Reporting(self.f.node).apply(dict(project_id=self.pid, base_head=self.f.git.head(), records=[
                dict(type='WatchDefinition', entity_id=str(uuid4()), previous=[], privacy='project', value=value)]), str(uuid4()))

    def test_collection_and_remote_configuration_do_not_silently_dispatch(self):
        daily = self.save(definition())
        p = calendar_period('2026-03-23T00:00:00+01:00', 'daily', 'Europe/Prague', 'iso-calendar-v1')
        with self.assertRaisesRegex(ValidationError, 'connector runtime'):
            self.service.prepare_run(self.pid, daily['definition_ref'], p, str(uuid4()))
        value = definition('Remote', 'daily', upstream=daily['watch_id'])
        value['placement'] = dict(mode='node', node_id=str(uuid4()), capabilities=[])
        remote = self.save(value)
        with self.assertRaisesRegex(ValidationError, 'Remote'):
            self.service.prepare_run(self.pid, remote['definition_ref'], p, str(uuid4()))

    def test_process_crash_replays_one_definition_revision(self):
        script = '''
import json,os,sys
from spikes.monitoring_definitions import MonitoringDefinitions
def checkpoint(stage):
 if stage==sys.argv[4]:os._exit(73)
MonitoringDefinitions(sys.argv[1]).save(json.load(open(sys.argv[2])),sys.argv[3],checkpoint=checkpoint)
'''
        for stage in ['prepared', 'files-applied', 'before-ref', 'ref-updated', 'indexed', 'completed']:
            with self.subTest(stage=stage):
                request = self.request(definition('Crash '+stage)); operation = str(uuid4())
                path = self.f.base / 'watch-request.json'; path.write_bytes(encoded(request))
                count = int(self.f.git.run('rev-list', '--count', 'HEAD').stdout)
                result = subprocess.run([sys.executable, '-c', script, str(self.f.node), str(path), operation, stage],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.f.ws.recover()
                saved = self.service.save(request, operation)
                self.assertEqual(self.f.git.head(), saved['receipt']['commit_id'])
                self.assertEqual(int(self.f.git.run('rev-list', '--count', 'HEAD').stdout), count+1)
                self.assertEqual(self.f.git.run('status', '--porcelain').stdout, '')
