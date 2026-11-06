# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Isolated direct RSS/Atom probe; JSON evidence only, never a Workspace writer."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import socket
import time
from urllib.parse import urljoin, urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

from spikes.metadata import require
from spikes.public_source import (HTTPResult, PublicSourceBinding, StaticHTMLAdapter,
                                  _robots_allowed, normalize_url, url_origin)
from spikes.source_collector import TextAdapter, public_url

SCHEMA = 'fpw-rss-pilot-v1'
MAX_BYTES = 512 * 1024
MAX_ITEMS = 500
ATOM = '{http://www.w3.org/2005/Atom}'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


class BoundedTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = self.count = 0

    def doctype(self, *args):
        raise ValueError('RSS pilot rejects DTD and entity declarations')

    def start(self, tag, attrs):
        self.depth += 1
        self.count += 1
        require(self.depth <= 32 and self.count <= 20000, 'XML structure exceeds pilot limits')
        return super().start(tag, attrs)

    def end(self, tag):
        result = super().end(tag)
        self.depth -= 1
        return result


def text(element, path):
    child = element.find(path)
    return ''.join(child.itertext()).strip() if child is not None else None


def publication(raw):
    if not raw:
        return None
    try:
        try:
            value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            value = parsedate_to_datetime(raw)
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(raw, feed_url):
    public_url(feed_url)
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'Feed exceeds pilot byte limit')
    # Decode first so UTF-16/32 cannot hide declaration bytes from the bounded parser.
    source = raw.decode('utf-8-sig')
    try:
        root = ET.fromstring(source, parser=ET.XMLParser(target=BoundedTree()))
    except ET.ParseError as exc:
        raise ValueError('Malformed RSS/Atom XML') from exc
    if root.tag == 'rss' and root.get('version') == '2.0':
        channel = root.find('channel')
        require(channel is not None, 'RSS channel is missing')
        title, items, prefix = text(channel, 'title'), channel.findall('item'), ''
    else:
        require(root.tag == ATOM + 'feed', 'Only RSS 2.0 and Atom 1.0 are supported')
        title, items, prefix = text(root, ATOM + 'title'), root.findall(ATOM + 'entry'), ATOM
    require(len(items) <= MAX_ITEMS, 'Feed item count exceeds pilot limit')
    entries = []
    for item in items:
        if prefix:
            links = [link for link in item.findall(ATOM + 'link')
                     if link.get('rel', 'alternate') == 'alternate' and link.get('href')]
            link = links[0].get('href') if links else None
            original_id = text(item, ATOM + 'id')
            author = text(item, ATOM + 'author/' + ATOM + 'name')
            date = text(item, ATOM + 'published')
            content = text(item, ATOM + 'content') or text(item, ATOM + 'summary')
        else:
            link, original_id = text(item, 'link'), text(item, 'guid')
            author = text(item, 'author') or text(item, '{http://purl.org/dc/elements/1.1/}creator')
            date = text(item, 'pubDate')
            content = text(item, 'description')
        if link:
            link = urljoin(feed_url, link)
            parsed = urlsplit(link)
            require(parsed.scheme in {'http', 'https'} and parsed.hostname and
                    not parsed.username and not parsed.password, 'Unsafe item link')
        entry = dict(original_id=original_id, url=link, title=text(item, prefix + 'title'),
                     author=author, published_at=publication(date), published_raw=date, content=content)
        require(original_id or link, 'Item needs a source identifier or link')
        # Content is inert external data; neither links nor embedded HTML are executed.
        entry['content_sha256'] = digest(entry)
        entries.append(entry)
    return dict(url=feed_url, title=title, entries=entries,
                raw_sha256=hashlib.sha256(raw).hexdigest())


def observe(feed, observed_at, previous=None):
    """Keep revision history across explicit JSON handoffs, without a runtime DB."""
    datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if previous is not None:
        require(previous.get('schema') == SCHEMA and previous.get('url') == feed['url'],
                'Previous observation belongs to another feed or schema')
    records = json.loads(json.dumps(previous['records'])) if previous else []
    aliases = {}
    for index, record in enumerate(records):
        for alias in record['aliases']:
            require(alias not in aliases, 'Ambiguous previous feed identities')
            aliases[alias] = index
    counts = dict(new=0, corrected=0, unchanged=0)
    for entry in feed['entries']:
        keys = (["id:" + entry['original_id']] if entry['original_id'] else [])
        if entry['url']:
            keys.append('url:' + entry['url'])
        matches = {aliases[key] for key in keys if key in aliases}
        require(len(matches) <= 1, 'Conflicting feed identifier and URL')
        if not matches:
            index = len(records)
            records.append(dict(id=digest([feed['url'], keys[0]]), aliases=[], revisions=[]))
            state = 'new'
        else:
            index = matches.pop()
            state = ('unchanged' if records[index]['revisions'][-1]['entry']['content_sha256']
                     == entry['content_sha256'] else 'corrected')
        record = records[index]
        for key in keys:
            if key not in record['aliases']:
                record['aliases'].append(key)
            aliases[key] = index
        if state != 'unchanged':
            record['revisions'].append(dict(observed_at=observed_at, entry=entry))
        counts[state] += 1
    result = dict(schema=SCHEMA, url=feed['url'], title=feed['title'], observed_at=observed_at,
                  raw_sha256=feed['raw_sha256'], counts=counts, records=records,
                  scope='isolated-pilot; no Workspace import, scheduler or LLM')
    require(len(json.dumps(result).encode()) <= 8 * 1024 * 1024, 'Pilot history exceeds limit')
    return result


def fetch(feed_url, *, transport=None):
    public_url(feed_url)
    binding = PublicSourceBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
        revision='rss-pilot-v1', adapter='static-html-v1', origins=[url_origin(feed_url)],
        user_agent='WorkspaceRSSPilot/0.1', auth='none', max_wire_bytes=MAX_BYTES,
        max_decoded_bytes=MAX_BYTES, max_text_chars=200000, max_compression_ratio=10,
        timeout_seconds=15))
    deadline = time.monotonic() + binding.timeout_seconds

    def get(url):
        result = (transport(url) if transport else StaticHTMLAdapter._get(
            url, binding, socket.getaddrinfo, deadline, time.monotonic))
        require(result.url == url and result.status == 200, 'RSS request failed; redirects/retries are not automatic')
        require(time.monotonic() < deadline and len(result.body) <= MAX_BYTES, 'RSS response exceeds limits')
        headers = StaticHTMLAdapter._headers(result.headers)
        if 'content-length' in headers:
            require(headers['content-length'].isdigit() and
                    int(headers['content-length']) == len(result.body), 'Incomplete RSS response')
        return HTTPResult(result.status, headers, result.body, result.url)

    robots = get(url_origin(feed_url) + '/robots.txt')
    require(robots.headers.get('content-type', '').split(';')[0].strip().lower() == 'text/plain',
            'RSS pilot requires text/plain robots preflight')
    robot_bytes = TextAdapter._decode(robots, binding.serialize())
    require(_robots_allowed(robot_bytes, urlsplit(feed_url).path, binding.user_agent), 'RSS path is disallowed by robots')
    target = get(feed_url)
    mime = target.headers.get('content-type', '').split(';')[0].strip().lower()
    require(mime in {'application/rss+xml', 'application/atom+xml', 'application/xml', 'text/xml'},
            'RSS pilot requires an XML response')
    require('no-store' not in target.headers.get('cache-control', '').lower(), 'Feed prohibits storing probe evidence')
    return TextAdapter._decode(target, binding.serialize())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Exact public HTTPS RSS/Atom URL')
    parser.add_argument('--input', type=Path, help='Parse saved XML instead of fetching')
    parser.add_argument('--previous', type=Path, help='Previous JSON observation for deduplication')
    args = parser.parse_args(argv)
    previous = None
    if args.previous:
        with args.previous.open('rb') as stream:
            raw_previous = stream.read(8 * 1024 * 1024 + 1)
        require(len(raw_previous) <= 8 * 1024 * 1024, 'Previous observation exceeds limit')
        previous = json.loads(raw_previous)
    if args.input:
        with args.input.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    else:
        raw = fetch(args.url)
    result = observe(parse_feed(raw, args.url), datetime.now(timezone.utc).isoformat(), previous)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
