# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from spikes.rss_sources import RSSSources
from tests.test_rss_pilot import rss
from tests import test_web_server as fixtures

CHANNELS = ({'id': 'one', 'name': 'One', 'url': 'https://example.test/one'},
            {'id': 'two', 'name': 'Two', 'url': 'https://example.test/two'})


class RSSSourcesTests(unittest.TestCase):
    def test_aggregation_dedup_and_failed_refresh_preserve_previous_content(self):
        now = [0]
        service = RSSSources(channels=CHANNELS, fetcher=lambda url: rss(url), clock=lambda: now[0])
        self.assertFalse(service.view()['entries'])
        first = service.refresh('all')
        self.assertEqual(len(first['entries']), 2)
        self.assertEqual({e['channel_id'] for e in first['entries']}, {'one', 'two'})
        first['entries'][0]['title'] = 'foreign mutation'
        self.assertNotEqual(service.view()['entries'][0]['title'], 'foreign mutation')
        with self.assertRaisesRegex(ValueError, '30 sekund'):
            service.refresh('all')
        now[0] = 31
        second = service.refresh('one')
        self.assertEqual(second['channels'][0]['counts']['unchanged'], 1)
        def failure(url): raise OSError('offline')
        service.fetcher = failure; now[0] = 62
        failed = service.refresh('one')
        self.assertEqual(len(failed['entries']), 2)
        self.assertEqual(failed['channels'][0]['state'], 'failed')
        self.assertEqual(failed['channels'][0]['checked_at'], second['channels'][0]['checked_at'])
        self.assertEqual(failed['channels'][0]['error'], 'offline')

    def test_browser_cannot_choose_arbitrary_urls_and_parallel_fetch_is_rejected(self):
        service = RSSSources(channels=CHANNELS, fetcher=lambda url: self.fail('unexpected fetch'))
        with self.assertRaisesRegex(ValueError, 'Neznámý'):
            service.refresh('https://evil.test/feed')
        service.refresh_lock.acquire()
        with self.assertRaisesRegex(ValueError, 'probíhá'):
            service.refresh('all')
        service.refresh_lock.release()


class RSSSourcesHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WebTests('test_dns_hostname_validation_is_fail_closed')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.server.rss_sources = RSSSources(channels=CHANNELS, fetcher=lambda url: rss(url))

    def call(self, action, value, headers=None):
        return self.f.request(path='/v1/rss-sources/'+action, body=json.dumps(value), headers=headers)

    def test_authenticated_global_view_and_admin_only_network_refresh(self):
        code, raw, _ = self.call('view', {})
        self.assertEqual(code, 200, raw)
        self.assertEqual(len(json.loads(raw)['channels']), 2)
        self.assertTrue(any(c['availability']['state']=='unavailable' for c in json.loads(raw)['connectors']))
        code, raw, _ = self.call('refresh', {'channel_id': 'all'})
        self.assertEqual(code, 200, raw)
        self.assertEqual(len(json.loads(raw)['entries']), 2)
        self.assertEqual(len(json.loads(raw)['items']),2)
        # Bootstrap the fixture node identity for its administration registry.
        code, raw, _ = self.f.create_project('RBAC fixture')
        self.assertEqual(code, 200, raw)
        def admin(value):
            code, raw, _ = self.f.request(path='/v1/administration', body=json.dumps(value))
            self.assertEqual(code, 200, raw); return json.loads(raw)
        state = admin({'action': 'list'})
        state = admin({'action': 'create-user', 'expected_commit': state['commit_id'],
                       'name': 'Reader', 'node_role': 'member'})
        headers = {'Authorization': 'Bearer '+state['access_key']}
        code, raw, _ = self.call('view', {}, headers)
        self.assertEqual(code, 200, raw)
        self.assertFalse(json.loads(raw)['can_refresh'])
        self.assertEqual(self.call('refresh', {'channel_id': 'all'}, headers)[0], 403)
        self.assertEqual(self.call('view', {}, {'Authorization': 'Bearer invalid'})[0], 401)

    def test_exact_http_request_shape(self):
        for action, value in [('view', {'url': 'https://evil.test'}),
                              ('refresh', {'channel_id': 'one', 'url': 'https://evil.test'})]:
            self.assertEqual(self.call(action, value)[0], 400)
        self.assertEqual(self.call('refresh', {'channel_id': 'missing'})[0], 422)
