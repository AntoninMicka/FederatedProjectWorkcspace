# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""MON-08-06: analytical reports consume fully synchronized, frozen evidence."""
import json
import unittest
from unittest.mock import patch

from tests import test_full_data_sync as federation_fixtures
from tests import test_synthesis_analysis as analysis_fixtures
from tests import test_monitoring_synthesis as synthesis_fixtures
from tests.test_monitoring_definitions import definition
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.monitoring_synthesis import WatchSynthesis, windows
from spikes.reporting_scheduler import calendar_period


class FederatedSynthesisTests(unittest.TestCase):
    save=synthesis_fixtures.SynthesisTests.save
    publish_evidence_week=analysis_fixtures.NativeAnalysisTests.publish_evidence_week

    def setUp(self):
        self.sync=federation_fixtures.FullDataSyncTests('test_whole_report_and_raw_evidence_roundtrip_without_connector_or_local_journals')
        self.sync.setUp();self.addCleanup(self.sync.doCleanups)
        self.f=self.sync.f
        self.model=MonitoringDefinitions(self.f.node)
        self.service=WatchSynthesis(self.f.node)
        self.month=calendar_period('2025-10-01T00:00:00+02:00','monthly','Europe/Prague','iso-calendar-v1')

    def issue_remote(self,service,watch,period):
        result=service.execute(self.f.project,watch['definition_ref'],period)
        self.assertEqual(result['state'],'review')
        run_id=result['run']['run_id'];preview=service.scheduler.preview(run_id)
        value=preview['request']['records'][0]['value']
        ledger_pin=value['analysis_ref']
        workspace=service.reporting.artifacts.workspace(self.f.project)
        ledger=json.loads(workspace.git.snapshot(ledger_pin['commit_id'])[ledger_pin['path']])
        self.assertEqual(ledger['unique_events'],1)
        self.assertEqual(ledger['events'][0]['claims'][0]['trend'],'progress')
        self.assertTrue(ledger['gaps'])
        self.assertEqual(ledger['events'][0]['current_date']['precision'],'unknown')
        self.assertEqual(value['reproducibility'],'limited-inputs')
        issued=service.publish(run_id,preview['approval_digest'],confirm=True)
        return issued['workspace_receipt']['snapshot'],ledger

    def test_remote_month_and_annual_preserve_one_event_original_proof_and_missing_periods(self):
        weekly=definition('Federated weekly evidence','weekly');weekly['schedule']['start']='2025-01-01'
        weekly['report'].update(mode='deterministic',formats=['markdown'],required_sections=['# Přehled','## Omezení'])
        weekly['inputs'][0]['policy']=dict(window='ending-in-period',approval='captured',missing='allow-incomplete')
        week=self.save(weekly)
        monthly=definition('Monthly analysis of stored evidence','monthly',upstream=week['watch_id'])
        monthly['schedule']['start']='2025-01-01'
        monthly['placement']=dict(mode='node',node_id=self.sync.node_ids[1],capabilities=[])
        monthly['report']['analysis']=dict(revision='month-1',input_level='weekly',target=None,
            case_studies=[dict(ref=self.f.policy,status='ongoing',note='Explicitly ongoing, never inferred complete')])
        monthly['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete')
        month=self.save(monthly)
        annual=definition('Annual analysis through monthly evidence','annual',upstream=month['watch_id'])
        annual['schedule']['start']='2025-01-01'
        annual['placement']=dict(mode='node',node_id=self.sync.node_ids[1],capabilities=[])
        annual['report']['analysis']=dict(revision='annual-1',input_level='monthly',target=None,case_studies=[])
        annual['inputs'][0]['policy']=dict(window='ending-in-period',approval='issued',missing='allow-incomplete')
        year=self.save(annual)
        periods=windows(weekly['schedule'],self.month,'ending-in-period')
        event,assessment,first=self.publish_evidence_week(week,periods[0])
        event,assessment,second=self.publish_evidence_week(week,periods[1],event,assessment,3)
        original_event=self.f.record(event)['entity_id']
        source_head=self.f.git.head()
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('Only stored evidence')):
            self.sync.exchange(0,1)
            remote=WatchSynthesis(self.sync.nodes[1])
            self.assertEqual(remote.reporting.read(self.f.project)['commit_id'],source_head)
            issued_month,month_ledger=self.issue_remote(remote,month,self.month)
            self.assertEqual({r['artifact_id'] for r in month_ledger['events'][0]['reported_in']},
                             {first['artifact_id'],second['artifact_id']})
            period=calendar_period('2025-01-01T00:00:00+01:00','annual','Europe/Prague','iso-calendar-v1')
            issued_year,year_ledger=self.issue_remote(remote,year,period)
            self.assertEqual(year_ledger['input_levels'][0]['kind'],'monthly')
            self.assertEqual(year_ledger['case_studies'][0]['status'],'ongoing')
            self.assertTrue(any(pin['artifact_id']==event['artifact_id'] for pin in year_ledger['evidence_refs']))
            self.sync.exchange(1,0)
        # The fixture's original native request handle has a bounded deadline.
        # A new read after the long multi-node operation needs its own handle,
        # just as a fresh API request does; do not extend product timeouts.
        self.f.ws=self.f.service.artifacts.workspace(self.f.project)
        self.f.git=self.f.ws.git
        for pin in (issued_month,issued_year):
            record=self.f.record(pin)
            ledger_pin=record['value']['analysis_ref']
            ledger=json.loads(self.f.git.snapshot(ledger_pin['commit_id'])[ledger_pin['path']])
            self.assertEqual(ledger['unique_events'],1)
            trace=self.service.trace(self.f.project,pin)
            self.assertTrue(any(n['ref']['artifact_id']==event['artifact_id'] for n in trace['nodes']))
            self.assertFalse(self.service.freshness(self.f.project,pin)['potentially_stale'])
        self.assertEqual(year_ledger['events'][0]['event_id'],original_event)
