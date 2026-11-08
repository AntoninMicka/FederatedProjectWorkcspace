# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import unittest
from uuid import uuid4

from tests import test_federation_sync as sync_fixture
from tests.test_monitoring_blocks import blocks, response
from spikes.monitoring import Monitoring
from spikes.composable_monitoring import ComposableMonitoring
from spikes.projects import Projects
from spikes.federation_sync import _prepare, _apply, SyncReceiver
from spikes.message_pools import MessagePools
from spikes.metadata import ValidationError


class PoolSyncTests(unittest.TestCase):
    def setUp(self):
        self.f=sync_fixture.FederationSyncTests('test_initial_import_and_fast_forward_work_in_both_directions')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.services=[ComposableMonitoring(Monitoring(n,Projects(n),clock=lambda:1794160000),
            fetcher=lambda *a,**kw:response()) for n in self.f.nodes]
        self.specs=blocks(self.f.nodes[0]);self.pid=self.f.project_id
        s=self.services[0];head=s.monitoring.projects.repository(self.pid).head()
        s.blocks.save(self.pid,head,self.specs,str(uuid4()))
        self.f.exchange(0,1)

    def test_signed_bidirectional_pool_sync_converges_redundant_intake_without_grants(self):
        # Receiving definitions never activates either node.
        self.assertIsNone(self.services[1].catalog(self.pid)['blocks'][0]['runtime'])
        for s in self.services:
            s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        head=self.services[0].monitoring.projects.repository(self.pid).head()
        self.f.exchange(0,1);self.f.exchange(1,0)
        a,b=[s.pools.export(self.pid) for s in self.services]
        self.assertEqual(a,b)
        view=self.services[0].pools.view(self.pid,self.specs[1]['id'])
        self.assertEqual(len(view),1);self.assertEqual(len(view[0]['revisions']),1)
        self.assertEqual(len(view[0]['observations']),2)
        self.assertEqual(self.services[0].monitoring.projects.repository(self.pid).head(),head)
        self.f.exchange(0,1)
        self.assertEqual(self.services[1].pools.export(self.pid),b)

    def test_sidecar_tampering_is_rejected_before_application(self):
        s=self.services[0];s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        env,payload,*_=_prepare(self.f.services[0],self.f.node_ids[1],self.pid,str(uuid4()),[],force_bundle=True)
        self.assertEqual(env['exchange']['schema_version'],3)
        with self.assertRaisesRegex(ValidationError,'digest'):
            SyncReceiver(self.f.nodes[1],self.f.services[1]).receive(env,payload[:-1]+b' ')
        self.assertEqual(self.services[1].pools.export(self.pid),[])

    def test_pool_crash_in_signed_exchange_rolls_forward_once(self):
        s=self.services[0];s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        env,payload,*_=_prepare(self.f.services[0],self.f.node_ids[1],self.pid,str(uuid4()),[],force_bundle=True)
        def crash(stage):
            if stage=='pool-inserted':raise RuntimeError('pool crash')
        receiver=SyncReceiver(self.f.nodes[1],self.f.services[1])
        with self.assertRaisesRegex(RuntimeError,'pool crash'):receiver.receive(env,payload,crash)
        self.assertEqual(self.services[1].pools.export(self.pid),[])
        receiver.receive(env,payload);receiver.receive(env,payload)
        self.assertEqual(s.pools.export(self.pid),self.services[1].pools.export(self.pid))
