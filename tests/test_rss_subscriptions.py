# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from spikes.rss_subscriptions import Subscriptions, preview
from spikes.rss_sources import RSSSources
from tests.test_rss_pilot import rss


def item(url='https://example.org/rss', name='News'):
    return dict(id='news',name=name,url=url,poll_seconds=120)


class SubscriptionTests(unittest.TestCase):
    def test_opml_folders_dedup_errors_and_json_reader_export(self):
        text='''<opml version="2.0"><body><outline text="Folder"><outline text="News" xmlUrl="https://example.org/rss"/><outline xmlUrl="https://example.org/rss"/><outline xmlUrl="http://old.example/rss"/></outline></body></opml>'''
        result=preview(text,[])
        self.assertEqual(len(result['channels']),1)
        self.assertEqual(result['channels'][0]['name'],'News')
        self.assertEqual(result['duplicates'],1);self.assertEqual(len(result['errors']),1)
        again=preview(json.dumps([{'title':'News','feedId':'feed/https://example.org/rss'}]),[])
        self.assertEqual(result['channels'],again['channels'])
        self.assertEqual(preview(text,result['channels'])['duplicates'],2)
        for raw in ('<rss/>','<!DOCTYPE opml [<!ENTITY x "oops">]><opml><body/></opml>', '{bad', 'x'*524289):
            with self.assertRaises(ValueError):preview(raw,[])

    def test_durable_atomic_save_cas_rollback_and_exact_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Subscriptions(Path(tmp)/'node.json',[])
            self.assertEqual(store.load(),(0,[]));self.assertFalse(store.path.exists())
            self.assertEqual(store.save(0,[item()]),1)
            self.assertEqual(store.save(0,[item()]),1)
            with self.assertRaises(ValueError):store.save(0,[item(name='Changed')])
            def crash():raise RuntimeError('crash before commit')
            with self.assertRaises(RuntimeError):store.save(1,[item(name='Changed')],checkpoint=crash)
            self.assertEqual(Subscriptions(Path(tmp)/'node.json',[]).load(),(1,[item()]))
            with self.assertRaises(ValueError):store.save(1,[item(),dict(item(),id='duplicate')])

    def test_service_edit_restart_period_and_url_change_clear_cached_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            node=Path(tmp)/'node.json';now=[0];calls=[]
            def fetch(url):calls.append(url);return rss('article')
            service=RSSSources(channels=[],node=node,fetcher=fetch,clock=lambda:now[0])
            service.save(0,[item()]);service.refresh('all',due_only=True)
            self.assertEqual(len(calls),1)
            now[0]=119;service.refresh('all',due_only=True);self.assertEqual(len(calls),1)
            now[0]=120;service.refresh('all',due_only=True);self.assertEqual(len(calls),2)
            service.save(1,[item(url='https://example.org/new')])
            self.assertEqual(service.view()['entries'],[])
            restored=RSSSources(channels=[],node=node)
            self.assertEqual(restored.view()['channels'][0]['url'],'https://example.org/new')
            self.assertEqual(restored.view()['revision'],2)
            self.assertFalse(restored.view()['entries'])
