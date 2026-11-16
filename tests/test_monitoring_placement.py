# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""A synchronized executor remains the same machine, including on its own node."""
import unittest
from uuid import uuid4

from tests import test_full_data_sync as fixtures
from tests.test_monitoring_definitions import definition
from spikes.metadata import ValidationError
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.rss_monitoring import RSSMonitoring
from spikes.reporting_schema import digest, encoded
from tests.test_rss_pilot import rss


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.sync=fixtures.FullDataSyncTests('test_whole_report_and_raw_evidence_roundtrip_without_connector_or_local_journals')
        self.sync.setUp();self.addCleanup(self.sync.doCleanups)
        self.f=self.sync.f

    def save(self,value):
        return MonitoringDefinitions(self.f.node).save(dict(project_id=self.f.project,
            base_head=self.f.git.head(),watch_id=str(uuid4()),previous=[],privacy='project',
            definition=value),str(uuid4()))

    def test_recipient_recognizes_itself_and_sender_cannot_activate_remote_rss(self):
        value=definition()
        value['placement']=dict(mode='node',node_id=self.sync.node_ids[1],capabilities=[])
        saved=self.save(value);self.sync.exchange(0,1)
        config=dict(project_id=self.f.project,watch_id=saved['watch_id'],
                    input_id=value['inputs'][0]['id'],definition_ref=saved['definition_ref'],
                    enabled=True,mode='queue-all')
        for index,expected in ((0,False),(1,True)):
            row=MonitoringDefinitions(self.sync.nodes[index]).read(self.f.project)['definitions'][0]
            self.assertEqual(row['definition']['placement'],value['placement'])
            self.assertEqual(row['execution_local'],expected)
        calls=[]
        def fetcher(url,*,validators):
            calls.append(url)
            return dict(status=200,raw=rss(),validators={})
        remote=RSSMonitoring(self.sync.nodes[1],fetcher=fetcher)
        binding=remote.configure(config,confirm=True)
        local=RSSMonitoring(self.sync.nodes[0],fetcher=lambda *a,**k:self.fail('Remote RSS fetched'))
        with self.assertRaisesRegex(ValidationError,'Remote RSS'):
            local.configure(config,confirm=True)
        # Simulate an old active sender binding, including an otherwise valid grant.
        with local.scheduler.db() as db:
            db.execute('INSERT INTO rss_bindings VALUES(?,?)',(binding['key'],encoded(binding)))
            db.execute('INSERT INTO watch_grants VALUES(?,?,?)',
                       (self.f.project,saved['watch_id'],digest(encoded(value))))
        local.tick(self.f.project)
        self.assertIn('Remote RSS',local.status(self.f.project)['bindings'][0]['last_error'])
        remote.tick(self.f.project)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(remote.status(self.f.project)['findings']),1)

    def test_explicit_local_save_is_pinned_once_and_never_reinterpreted_on_sync(self):
        self.save(definition());self.sync.exchange(0,1)
        for index,expected in ((0,True),(1,False)):
            row=MonitoringDefinitions(self.sync.nodes[index]).read(self.f.project)['definitions'][0]
            self.assertEqual(row['definition']['placement']['node_id'],self.sync.node_ids[0])
            self.assertEqual(row['definition']['placement']['mode'],'node')
            self.assertEqual(row['execution_local'],expected)

    def test_imported_legacy_local_is_readable_but_cannot_activate_on_either_node(self):
        value=definition();identity=str(uuid4())
        self.f.service.apply(dict(project_id=self.f.project,base_head=self.f.git.head(),records=[
            dict(type='WatchDefinition',entity_id=identity,previous=[],privacy='project',value=value)]),str(uuid4()))
        self.sync.exchange(0,1)
        for node in self.sync.nodes:
            row=MonitoringDefinitions(node).read(self.f.project)['definitions'][0]
            self.assertTrue(row['placement_review_required']);self.assertFalse(row['execution_local'])
            with self.assertRaisesRegex(ValidationError,'ambiguous'):
                RSSMonitoring(node).configure(dict(project_id=self.f.project,watch_id=identity,
                    input_id=value['inputs'][0]['id'],definition_ref=row['definition_ref'],
                    enabled=True,mode='queue-all'),confirm=True)
