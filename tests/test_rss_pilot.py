# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.rss_pilot import MAX_BYTES, fetch, observe, parse_feed
from spikes.public_source import HTTPResult

URL = 'https://example.test/feed.xml'
NOW = '2026-11-06T17:00:00Z'


def rss(title='First', identifier='one', date=''):
    return ('<rss version="2.0"><channel><title>News</title><item>'
            f'<guid>{identifier}</guid><title>{title}</title><link>https://example.test/article</link>'
            f'<pubDate>{date}</pubDate><description>&lt;b&gt;inert&lt;/b&gt;</description>'
            '</item></channel></rss>').encode()


class RSSPilotTests(unittest.TestCase):
    def test_replay_restart_correction_and_temporarily_absent_item(self):
        first = observe(parse_feed(rss(), URL), NOW)
        restarted = json.loads(json.dumps(first))
        same = observe(parse_feed(rss(), URL), NOW, restarted)
        self.assertEqual(same['counts'], dict(new=0, corrected=0, unchanged=1))
        empty = parse_feed(b'<rss version="2.0"><channel><title>News</title></channel></rss>', URL)
        missed = observe(empty, NOW, same)
        returned = observe(parse_feed(rss(), URL), NOW, missed)
        self.assertEqual(returned['counts']['unchanged'], 1)
        corrected = observe(parse_feed(rss('Corrected'), URL), NOW, returned)
        self.assertEqual(corrected['counts'], dict(new=0, corrected=1, unchanged=0))
        self.assertEqual(len(corrected['records']), 1)
        self.assertEqual(len(corrected['records'][0]['revisions']), 2)
        self.assertEqual(first['records'][0]['revisions'][0]['entry']['title'], 'First')

    def test_changed_identifier_with_same_link_keeps_identity(self):
        first = observe(parse_feed(rss(), URL), NOW)
        second = observe(parse_feed(rss(identifier='replacement'), URL), NOW, first)
        self.assertEqual(second['counts']['corrected'], 1)
        self.assertEqual(second['records'][0]['id'], first['records'][0]['id'])

    def test_publication_is_distinct_from_observation_and_html_is_inert(self):
        entry = parse_feed(rss(), URL)['entries'][0]
        self.assertIsNone(entry['published_at'])
        self.assertEqual(entry['content'], '<b>inert</b>')
        dated = parse_feed(rss(date='Fri, 06 Nov 2026 16:00:00 +0100'), URL)['entries'][0]
        self.assertEqual(dated['published_at'], '2026-11-06T15:00:00Z')
        self.assertIsNone(parse_feed(rss(date='unknown'), URL)['entries'][0]['published_at'])

    def test_atom_published_does_not_fall_back_to_updated(self):
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
        <entry><id>urn:entry:1</id><title>One</title><updated>2026-11-06T16:00:00Z</updated>
        <link href="/one"/><author><name>Alice</name></author></entry></feed>'''
        entry = parse_feed(raw, URL)['entries'][0]
        self.assertEqual(entry['author'], 'Alice')
        self.assertEqual(entry['url'], 'https://example.test/one')
        self.assertIsNone(entry['published_at'])

    def test_rejects_dtd_malformed_oversized_deep_and_unsafe_xml(self):
        for raw in [b'<!DOCTYPE rss [<!ENTITY x "expanded">]><rss version="2.0"/>',
                    b'<broken', b'<html/>', b'x' * (MAX_BYTES + 1),
                    ('<a>' * 33 + '</a>' * 33).encode(),
                    rss().replace(b'https://example.test/article', b'javascript:alert(1)')]:
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse_feed(raw, URL)

    def test_previous_cannot_cross_feed_boundary(self):
        first = observe(parse_feed(rss(), URL), NOW)
        with self.assertRaisesRegex(ValueError, 'another feed'):
            observe(parse_feed(rss(), 'https://example.test/other'), NOW, first)

    def test_fetch_uses_robots_and_exact_feed_without_following_item_links(self):
        calls = []
        def transport(url):
            calls.append(url)
            return HTTPResult(200, {'content-type': 'text/plain' if url.endswith('robots.txt') else 'text/xml'},
                              b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else rss(), url)
        self.assertEqual(fetch(URL, transport=transport), rss())
        self.assertEqual(calls, ['https://example.test/robots.txt', URL])

    def test_fetch_rejects_blocked_redirect_wrong_mime_and_truncated_response(self):
        for kind in ['blocked', 'redirect', 'mime', 'truncated', 'overloaded']:
            calls = []
            def transport(url):
                calls.append(url)
                if url.endswith('robots.txt'):
                    body = b'User-agent: *\nDisallow: /' if kind == 'blocked' else b'User-agent: *\nAllow: /'
                    return HTTPResult(200, {'content-type': 'text/plain'}, body, url)
                headers = {'content-type': 'text/html' if kind == 'mime' else 'text/xml'}
                if kind == 'truncated': headers['content-length'] = '10000'
                return HTTPResult(302 if kind == 'redirect' else 503 if kind == 'overloaded' else 200,
                                  headers, rss(), url)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                fetch(URL, transport=transport)
            self.assertLessEqual(len(calls), 2)

    def test_fetch_rejects_trailing_gzip_members(self):
        def transport(url):
            if url.endswith('robots.txt'):
                return HTTPResult(200, {'content-type': 'text/plain'}, b'User-agent: *\nAllow: /', url)
            return HTTPResult(200, {'content-type': 'text/xml', 'content-encoding': 'gzip'},
                              gzip.compress(rss()) + gzip.compress(b'extra'), url)
        with self.assertRaisesRegex(ValueError, 'complete gzip'):
            fetch(URL, transport=transport)

    def test_real_cli_saved_xml_and_previous_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            xml = folder / 'feed.xml'; xml.write_bytes(rss())
            command = [sys.executable, '-m', 'scripts.rss_pilot', URL, '--input', str(xml)]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            previous = folder / 'first.json'; previous.write_text(first.stdout)
            second = subprocess.run(command + ['--previous', str(previous)], check=True,
                                    capture_output=True, text=True)
            self.assertEqual(json.loads(second.stdout)['counts']['new'], 0)
            self.assertEqual(json.loads(second.stdout)['counts']['unchanged'], 1)


if __name__ == '__main__':
    unittest.main()
