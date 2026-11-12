# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import http.client
from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import ssl
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes import rss_subscription_state as state
from spikes import rss_subscription_sync as sync
from spikes.rss_subscriptions import Subscriptions
from spikes.rss_sources import RSSSources
from spikes.federation_accounts import canonical
from spikes.web_server import WebHandler
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from tests import test_federation_catalog as fixtures


def channel(name='News',url='https://example.org/rss',id_='local'):
    return dict(id=id_,name=name,url=url,poll_seconds=900)


class ReaderStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.nodes=[Path(self.tmp.name)/str(i)/'node.json' for i in range(2)]
        self.ids=[str(uuid4()),str(uuid4())]
        for node,id_ in zip(self.nodes,self.ids):
            node.parent.mkdir();node.write_text(json.dumps(dict(id=id_)))
            Subscriptions(node,[]).save(0,[])
        for i in range(2):state.configure(self.nodes[i],self.ids[1-i],True)

    def save(self,i,channels):
        s=state.store(self.nodes[i]);r,_=s.load();return s.save(r,channels)

    def transfer(self,a,b,**kwargs):
        state.apply(self.nodes[b],self.ids[a],state.export(self.nodes[a],self.ids[b]),**kwargs)

    def values(self,i):return [state.value(c) for c in state.store(self.nodes[i]).load()[1]]

    def test_additions_url_dedup_and_restart_do_not_fetch_or_copy_caches(self):
        self.save(0,[channel()]);self.save(1,[channel(id_='other'),channel('Second','https://example.org/second','second')])
        self.transfer(0,1);self.transfer(1,0)
        self.assertEqual(self.values(0),self.values(1));self.assertEqual(len(self.values(0)),2)
        service=RSSSources(node=self.nodes[0],fetcher=lambda u:self.fail('No receive activation'))
        self.assertFalse(service.view()['entries']);self.assertTrue(all(c['state']=='unloaded' for c in service.view()['channels']))

    def test_concurrent_edits_are_preserved_until_exact_review_resolution(self):
        self.save(0,[channel()]);self.transfer(0,1)
        a=state.store(self.nodes[0]).load()[1];b=state.store(self.nodes[1]).load()[1]
        a[0]['name']='Desktop';b[0]['name']='Other node'
        self.save(0,a);self.save(1,b);self.transfer(0,1);self.transfer(1,0)
        conflict=state.view(self.nodes[0])['conflicts'][0]
        self.assertEqual(len(conflict['versions']),2)
        self.assertEqual(self.values(0)[0]['name'],'Desktop');self.assertEqual(self.values(1)[0]['name'],'Other node')
        rev,_=state.store(self.nodes[0]).load()
        with self.assertRaisesRegex(ValueError,'revisions changed'):
            state.resolve(self.nodes[0],conflict['url'],conflict['versions'][0]['id'],rev,[])
        selected=next(v for v in conflict['versions'] if v['value']['name']=='Desktop')
        state.resolve(self.nodes[0],conflict['url'],selected['id'],rev,[v['id'] for v in conflict['versions']])
        self.transfer(0,1);self.assertFalse(state.view(self.nodes[1])['conflicts']);self.assertEqual(self.values(0),self.values(1))

    def test_tombstone_replay_does_not_resurrect_removed_subscription(self):
        self.save(0,[channel()]);old=state.export(self.nodes[0],self.ids[1]);self.transfer(0,1)
        self.save(0,[]);self.transfer(0,1)
        state.apply(self.nodes[1],self.ids[0],old);self.assertEqual(self.values(1),[])

    def test_atomic_rollback_exact_replay_and_lost_commit_ack(self):
        self.save(0,[channel()]);before=state.store(self.nodes[1]).load()
        def crash(stage):
            if stage=='subscriptions-staged':raise RuntimeError('power loss')
        with self.assertRaises(RuntimeError):self.transfer(0,1,checkpoint=crash)
        self.assertEqual(state.store(self.nodes[1]).load(),before)
        def after(stage):
            if stage=='committed':raise RuntimeError('lost acknowledgement')
        with self.assertRaises(RuntimeError):self.transfer(0,1,checkpoint=after)
        accepted=state.store(self.nodes[1]).load();self.transfer(0,1)
        self.assertEqual(state.store(self.nodes[1]).load(),accepted)

    def test_running_reader_reloads_remote_settings_and_stale_editor_cannot_overwrite(self):
        self.save(0,[channel()]);self.transfer(0,1)
        reader=RSSSources(node=self.nodes[1],fetcher=lambda u:self.fail('No implicit GET'))
        old=reader.view();edited=state.store(self.nodes[0]).load()[1];edited[0]['poll_seconds']=120
        self.save(0,edited);self.transfer(0,1)
        self.assertEqual(reader.view()['channels'][0]['poll_seconds'],120)
        draft=dict(old['channels'][0]);draft={k:draft[k] for k in ('id','name','url','poll_seconds')};draft['name']='Old draft'
        with self.assertRaises(ValueError):reader.save(old['revision'],[draft])

    def test_incoming_conflict_invalidates_an_open_editor_even_when_visible_value_stays_local(self):
        self.save(0,[channel()]);self.transfer(0,1)
        a=state.store(self.nodes[0]).load()[1];a[0]['name']='Desktop';self.save(0,a)
        reader=RSSSources(node=self.nodes[0]);old=reader.view()
        b=state.store(self.nodes[1]).load()[1];b[0]['name']='Remote';self.save(1,b);self.transfer(1,0)
        self.assertEqual(self.values(0)[0]['name'],'Desktop')
        draft={k:old['channels'][0][k] for k in ('id','name','url','poll_seconds')};draft['name']='Unreviewed edit'
        with self.assertRaises(ValueError):reader.save(old['revision'],[draft])
        self.assertEqual(len(state.view(self.nodes[0])['conflicts']),1)

    def test_invalid_history_and_disabled_peer_are_rejected_without_partial_write(self):
        self.save(0,[channel()]);events=state.export(self.nodes[0],self.ids[1])
        bad=deepcopy(events);bad[0]['value']['name']='tampered'
        with self.assertRaises(ValueError):state.apply(self.nodes[1],self.ids[0],bad)
        self.assertEqual(self.values(1),[])
        state.configure(self.nodes[1],self.ids[0],False)
        with self.assertRaises(ValueError):self.transfer(0,1)

    def test_stale_sharing_choice_cannot_undo_a_newer_enable(self):
        with self.assertRaisesRegex(ValueError,'choice changed'):
            state.configure(self.nodes[0],self.ids[1],False,expected_enabled=False)
        self.assertTrue(state.enabled(self.nodes[0],self.ids[1]))

    def test_process_crash_rolls_back_or_replays_the_same_causal_history(self):
        self.save(0,[channel()]);original=state.store(self.nodes[1]).load()
        script='''
import os,sys
from pathlib import Path
from spikes import rss_subscription_state as s
a,b=Path(sys.argv[1]),Path(sys.argv[2]);peer_a,peer_b=sys.argv[3:5]
def checkpoint(stage):
 if stage==sys.argv[5]:os._exit(73)
s.apply(b,peer_a,s.export(a,peer_b),checkpoint=checkpoint)
'''
        for stage in ('events-staged','subscriptions-staged','committed'):
            r=subprocess.run([sys.executable,'-c',script,str(self.nodes[0]),str(self.nodes[1]),*self.ids,stage],capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,73,r.stdout+r.stderr)
            if stage!='committed':self.assertEqual(state.store(self.nodes[1]).load(),original)
        accepted=state.store(self.nodes[1]).load();self.transfer(0,1)
        self.assertEqual(state.store(self.nodes[1]).load(),accepted)


class ReaderSignedSyncTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.FederationCatalogTests('test_signed_exchange_stores_only_remote_project_identity_and_title')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        for i in range(2):state.configure(self.f.nodes[i],self.f.node_ids[1-i],True)

    def transfer(self,i=0):
        return sync.synchronize(self.f.nodes[i],self.f.node_ids[1-i],deployment='web',
            transport=lambda peer,envelope:sync.receive(self.f.services[1-i],envelope))

    def test_signed_roundtrip_automatic_fingerprints_and_no_cross_project_payload(self):
        store=state.store(self.f.nodes[0]);rev,channels=store.load();store.save(rev,channels+[channel()])
        self.transfer();self.transfer(1);self.transfer()
        envelope,_=sync.prepare(self.f.services[0],self.f.node_ids[1])
        self.assertIsNone(envelope['rss']['events'])
        self.assertEqual([state.value(c) for c in state.store(self.f.nodes[0]).load()[1]],
                         [state.value(c) for c in state.store(self.f.nodes[1]).load()[1]])
        self.assertNotIn('project_id',canonical(envelope).decode());self.assertNotIn('content',canonical(envelope).decode())

    def test_both_opt_ins_signature_recipient_and_current_peer_trust(self):
        e,_=sync.prepare(self.f.services[0],self.f.node_ids[1],full=True)
        bad=deepcopy(e);bad['rss']['events'][0]['value']['name']='Tampered'
        with self.assertRaises(ValueError):sync.receive(self.f.services[1],bad)
        state.configure(self.f.nodes[1],self.f.node_ids[0],False)
        with self.assertRaises(ValueError):sync.receive(self.f.services[1],e)
        state.configure(self.f.nodes[1],self.f.node_ids[0],True)
        self.f.connect('external')
        with self.assertRaises(ValueError):sync.receive(self.f.services[1],e)

    def test_signed_replay_after_receiver_commit_is_idempotent(self):
        e,_=sync.prepare(self.f.services[0],self.f.node_ids[1],full=True)
        def crash(stage):
            if stage=='committed':raise RuntimeError('disconnect')
        with self.assertRaises(RuntimeError):sync.receive(self.f.services[1],e,checkpoint=crash)
        before=state.store(self.f.nodes[1]).load();sync.receive(self.f.services[1],e)
        self.assertEqual(before,state.store(self.f.nodes[1]).load())

    def test_http_peer_route_checks_host_and_returns_signed_reply(self):
        server=HTTPServer(('127.0.0.1',0),WebHandler);server.node=self.f.nodes[1];server.administration=self.f.services[1];server.hostname=None
        thread=threading.Thread(target=server.serve_forever);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        e,_=sync.prepare(self.f.services[0],self.f.node_ids[1],full=True)
        c=http.client.HTTPConnection(*server.server_address,timeout=5)
        try:
            c.request('POST',sync.PATH,canonical(e),{'Content-Type':sync.CONTENT_TYPE})
            r=c.getresponse();body=r.read();self.assertEqual(r.status,200,body)
            self.assertEqual(sync.verified(self.f.services[0],json.loads(body))[0]['source'],self.f.node_ids[1])
        finally:c.close()
        for raw,headers,expected in ((canonical(e),{'Origin':'https://other.example'},403),
                                     (b'{"rss":{},"rss":{}}',{},422)):
            c=http.client.HTTPConnection(*server.server_address,timeout=5)
            try:
                c.request('POST',sync.PATH,raw,{'Content-Type':sync.CONTENT_TYPE,**headers})
                r=c.getresponse();body=r.read();self.assertEqual(r.status,expected,body)
            finally:c.close()

    def test_slow_manual_exchange_does_not_block_reader_view(self):
        entered=threading.Event();release=threading.Event();results=[]
        def blocked(*a,**kw):
            entered.set()
            if not release.wait(5):raise AssertionError('Transfer was not released')
        def post(server,path,body):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                c.request('POST',path,json.dumps(body),{'Content-Type':'application/json','Authorization':'Bearer '+server.token})
                r=c.getresponse();r.read();return r.status
            finally:c.close()
        with running_api('http',handler=DesktopHandler,projects=Projects(self.f.nodes[0])) as server:
            server.administration=self.f.services[0]
            with patch('spikes.rss_subscription_sync.synchronize',side_effect=blocked):
                worker=threading.Thread(target=lambda:results.append(post(server,'/v1/rss-sources/sync',{'peer_id':self.f.node_ids[1]})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(post(server,'/v1/rss-sources/view',{}),200)
                finally:release.set();worker.join(6)
                self.assertEqual(results,[200])

    def test_real_https_exchange_requires_the_saved_ca(self):
        certificates=[]
        for label in ('server','wrong-ca'):
            cert=self.f.root/(label+'.pem');key=self.f.root/(label+'.key')
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
                '-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,capture_output=True)
            certificates.append((cert,key))
        server=HTTPServer(('127.0.0.1',0),WebHandler);server.node=self.f.nodes[1];server.administration=self.f.services[1];server.hostname=None
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(*map(str,certificates[0]))
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        self.f.change(0,action='update-peer',node_id=self.f.node_ids[1],name='Peer',
            endpoint='https://127.0.0.1:'+str(server.server_port),trust='approved',sharing_level='same-team')
        with self.assertRaises(ssl.SSLError):
            sync.synchronize(self.f.nodes[0],self.f.node_ids[1],deployment='web',ca=certificates[1][0],full=True)
        sync.synchronize(self.f.nodes[0],self.f.node_ids[1],deployment='web',ca=certificates[0][0],full=True)
        self.assertEqual(state.view(self.f.nodes[0])['peers'][0]['state'],'idle')

    def test_existing_background_scheduler_runs_only_explicit_rss_peers(self):
        from spikes.federation_catalog import CatalogScheduler
        scheduler=CatalogScheduler(self.f.nodes[0],deployment='web',interval=60)
        entered=threading.Event();calls=[]
        def rss(node,peer_id,**kwargs):calls.append((node,peer_id,kwargs));entered.set()
        state.configure(self.f.nodes[0],str(uuid4()),False)
        with patch.object(scheduler.control,'run_automatic'),patch('spikes.rss_subscription_sync.synchronize',side_effect=rss):
            scheduler.start()
            try:self.assertTrue(entered.wait(2))
            finally:scheduler.stop()
        self.assertEqual(calls,[(self.f.nodes[0],self.f.node_ids[1],{'deployment':'web'})])
