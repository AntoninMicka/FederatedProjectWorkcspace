# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded, untrusted examples for explicit monitoring design, not intake."""
import socket
import time
from uuid import uuid4

from spikes.metadata import require
from spikes.public_source import (PublicSourceBinding, StaticHTMLAdapter,
    _robots_allowed, project_document, url_origin)
from spikes.reporting_schema import digest
from spikes.rss_reader import parse_feed
from spikes.source_connectors import RSSConnector, SourceContext


def read_article(url):
    """Reuse public-reader DNS/TLS/robots/size boundaries; retain no staging."""
    origin = url_origin(url)
    binding = PublicSourceBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
        revision='monitoring-design-v1', adapter='static-html-v1', origins=[origin],
        user_agent='WorkspaceMonitoringDesign/0.1', auth='none', max_wire_bytes=512*1024,
        max_decoded_bytes=512*1024, max_text_chars=64000, max_compression_ratio=10,
        timeout_seconds=5))
    deadline = time.monotonic()+5
    def get(target):
        result = StaticHTMLAdapter._get(target,binding,socket.getaddrinfo,deadline,time.monotonic)
        require(result.url == target, 'Article URL changed')
        length=result.headers.get('content-length')
        require(length is None or length.isdigit() and int(length)==len(result.body), 'Incomplete article response')
        require('no-store' not in result.headers.get('cache-control','').lower(), 'Article forbids retention')
        return result
    robots = get(origin+'/robots.txt')
    require(robots.status == 200 or 400 <= robots.status < 500 and robots.status != 429,
            'Article robots unavailable')
    if robots.status == 200:
        from urllib.parse import urlsplit
        require(_robots_allowed(StaticHTMLAdapter._decode(robots,binding.serialize()),
                urlsplit(url).path or '/',binding.user_agent), 'Article robots disallow access')
    result = get(url)
    require(result.status == 200, 'Article is unavailable or requires a separate redirect approval')
    mime = result.headers.get('content-type','')
    require(mime.split(';')[0].strip().lower() in {'text/html','text/plain'}, 'Unsupported article type')
    text, projection = project_document(StaticHTMLAdapter._decode(result,binding.serialize()),mime,64000)
    return dict(text=text[:8000],title=projection.get('title'),raw_sha256=digest(result.body),
                projected_sha256=digest(text.encode()),truncated=len(text)>8000)


def collect(source, feed_fetcher, observed_at, *, article_fetcher=None):
    article_fetcher = article_fetcher or read_article
    c = source['value']['config']
    response = feed_fetcher(c['locator'],validators={})
    require(response['status'] == 200, 'Design requires a full feed sample')
    feed = parse_feed(response['raw'],c['locator'])
    context = SourceContext(source['id'],c['locator'],observed_at,source['privacy'],
                            c['retention'],channel=source['value']['title'])
    # No relevance prefilter: it could hide precisely the false negatives being diagnosed.
    entries = feed['entries'][:8]
    items = RSSConnector().normalize(dict(raw=response['raw'],url=c['locator']),context)['items'][:8]
    candidates = []
    for e, item in zip(entries,items):
        candidate = dict(item_id=item['id'],url=e['url'],title=e['title'],
            published_at=e['published_at'],feed_text=(e['content'] or '')[:4000],
            feed_text_truncated=len(e['content'] or '')>4000,
            categories=e.get('categories',[]),article=dict(state='not-sampled'))
        candidates.append(candidate)
    for candidate in candidates[:2]:
        url = candidate['url']
        try:
            same_origin = bool(url) and url_origin(url) == url_origin(c['locator'])
        except ValueError:
            same_origin = False
        if not same_origin:
            candidate['article']=dict(state='different-origin-or-missing-url');continue
        try:
            candidate['article']=dict(state='available',**article_fetcher(url))
        except Exception as exc:
            # No credential, redirect or alternate-source fallback, no unbounded retries.
            candidate['article']=dict(state='unavailable',error_type=type(exc).__name__)
    evidence = dict(source_id=source['id'],source_ref=source['ref'],locator=c['locator'],
        observed_at=observed_at,feed_sha256=feed['raw_sha256'],feed_items=len(feed['entries']),
        sampled_items=len(candidates),sampling='first-eight-feed-entries-two-same-origin-pages',
        coverage='current-feed-window-only; not a historical archive',
        runtime_fields=['title','content','author','url','channel'],
        categories_scope='design evidence only; categories are not runtime filter fields',
        candidates=candidates)
    return evidence,items
