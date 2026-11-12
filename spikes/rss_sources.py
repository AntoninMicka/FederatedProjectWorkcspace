# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Manual public-feed cache, independent of project data and monitoring."""
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
from spikes.request_ownership import ProjectBusy, bounded_process_lock, bounded_project_wait
from spikes.metadata import require
from spikes.public_source import PublicSourceError
from spikes.rss_reader import fetch, observe, parse_feed
from spikes.source_connectors import CONNECTORS, SourceContext, RSSConnector, connector_catalog, batch

CHANNELS = ({'id': 'ct24-editorial', 'name': 'ČT24 — Výběr redakce',
             'url': 'https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313'},)
_CREATION_LOCK = threading.Lock()


class RSSSources:
    def __init__(self, *, channels=CHANNELS, fetcher=fetch, clock=time.monotonic, node=None):
        self.channels = [dict(c, poll_seconds=c.get('poll_seconds',900)) for c in deepcopy(channels)]
        from spikes.rss_subscriptions import Subscriptions
        self.store = Subscriptions(node, self.channels) if node is not None else None
        self.revision = 0
        if self.store is not None: self.revision, self.channels = self.store.load()
        require(all(channel.get('connector', 'rss-atom') in CONNECTORS for channel in self.channels), 'Unknown source connector')
        self.fetcher, self.clock = fetcher, clock
        self.lock, self.refresh_lock = threading.Lock(), threading.Lock()
        self.cache = {c['id']: dict(observation=None, error=None, state='unloaded', attempted=None)
                      for c in self.channels}
        for channel in self.channels:
            kind=channel.get('connector','rss-atom')
            if kind!='rss-atom':
                self.cache[channel['id']].update(state='unavailable',error=CONNECTORS[kind]().describe()['availability']['reason'])

    def _reload_locked(self):
        if self.store is None:return
        revision,channels=self.store.load()
        if revision==self.revision:return
        old={c['id']:c for c in self.channels}
        self.cache={c['id']:(self.cache[c['id']] if c['id'] in old and old[c['id']]['url']==c['url'] else
                    dict(observation=None,error=None,state='unloaded',attempted=None)) for c in channels}
        self.channels,self.revision=channels,revision

    def view(self):
        with bounded_process_lock(self.lock, resource='RSS cache'):
            self._reload_locked()
            channels, entries, items = [], [], []
            for channel in self.channels:
                cached = self.cache[channel['id']]
                observation = cached['observation']
                channels.append(dict(channel, state=cached['state'], error=cached['error'],
                    checked_at=observation['observed_at'] if observation else None,
                    due=cached['attempted'] is None or self.clock()-cached['attempted'] >= channel['poll_seconds'],
                    counts=observation['counts'] if observation else None))
                if observation:
                    for record in observation['records']:
                        revision = record['revisions'][-1]
                        context = SourceContext(channel['id'], channel['url'], record['revisions'][0]['observed_at'],
                            'public', 'node-memory-until-backend-restart', channel=channel['name'])
                        normalized = RSSConnector().normalize_entry(revision['entry'], context, revision.get('raw_sha256'))
                        items.append(normalized)
                        entries.append(dict(revision['entry'], title=normalized['title'], url=normalized['url'],
                            author=normalized['author'], published_at=normalized['published_at'], id=record['id'],
                            channel_id=channel['id'], channel_name=channel['name'],
                            observed_at=revision['observed_at'], revisions=len(record['revisions'])))
            entries.sort(key=lambda e: (e['published_at'] or e['observed_at'], e['id']), reverse=True)
            return deepcopy(dict(revision=self.revision, channels=channels, entries=entries, items=items, connectors=connector_catalog()))

    def save(self, revision, edits):
        from spikes.rss_subscriptions import channel
        require(isinstance(edits, list) and 1 <= len(edits) <= 1000, 'Vyberte 1 až 1000 kanálů.')
        edits = [channel(c) for c in edits]
        require(len({c['id'] for c in edits}) == len(edits), 'Duplicitní ID kanálu.')
        with bounded_process_lock(self.refresh_lock, resource='RSS refresh'), bounded_process_lock(self.lock, resource='RSS cache'):
            self._reload_locked()
            require(revision == self.revision or all(c in self.channels for c in edits), 'Odběry se změnily; obnovte přehled.')
            merged = {c['id']: c for c in self.channels}; merged.update({c['id']:c for c in edits})
            values = list(merged.values())
            require(len({c['url'] for c in values}) == len(values), 'Tato URL již má vlastní kanál.')
            new_revision = self.store.save(revision, values) if self.store else self.revision+1
            for c in edits:
                old = next((old for old in self.channels if old['id']==c['id']), None)
                if old is None or old['url'] != c['url']:
                    self.cache[c['id']] = dict(observation=None,error=None,state='unloaded',attempted=None)
            self.channels, self.revision = values, new_revision
        return self.view()

    def refresh(self, channel_id, *, due_only=False):
        with bounded_process_lock(self.lock,resource='RSS cache'):self._reload_locked()
        require(channel_id == 'all' or channel_id in self.cache, 'Neznámý kanál.')
        require(channel_id != 'all' or len(self.channels)<=8, 'Více než osm kanálů načítejte jednotlivě.')
        if not self.refresh_lock.acquire(blocking=False):
            if bounded_project_wait.get():
                raise ProjectBusy('RSS refresh is busy')
            require(False, 'Načítání již probíhá. Obnovte přehled.')
        try:
            for channel in self.channels:
                if channel_id not in {'all', channel['id']}:
                    continue
                kind = channel.get('connector', 'rss-atom')
                if kind != 'rss-atom':
                    with bounded_process_lock(self.lock, resource='RSS cache'):
                        self.cache[channel['id']].update(state='unavailable', error=CONNECTORS[kind]().describe()['availability']['reason'])
                    continue
                with bounded_process_lock(self.lock, resource='RSS cache'):
                    cached = self.cache[channel['id']]
                    if due_only and cached['attempted'] is not None and self.clock()-cached['attempted'] < channel['poll_seconds']: continue
                    require(cached['attempted'] is None or self.clock() - cached['attempted'] >= 30,
                            'Další načtení kanálu je možné po 30 sekundách.')
                    cached['attempted'] = self.clock()
                    cached['state'] = 'loading'
                    previous = cached['observation']
                try:
                    raw = self.fetcher(channel['url'])
                    observed_at=datetime.now(timezone.utc).isoformat()
                    feed=parse_feed(raw, channel['url'])
                    context=SourceContext(channel['id'],channel['url'],observed_at,'public',
                        'node-memory-until-backend-restart',channel=channel['name'])
                    batch('rss-atom',[RSSConnector().normalize_entry(entry,context,feed['raw_sha256']) for entry in feed['entries']])
                    observation = observe(feed,observed_at,previous)
                except (ValueError, OSError, PublicSourceError) as exc:
                    with bounded_process_lock(self.lock, resource='RSS cache'):
                        cached['state'] = 'unknown' if getattr(exc, 'state', '') == 'unknown' else 'failed'
                        cached['error'] = str(exc)
                else:
                    with bounded_process_lock(self.lock, resource='RSS cache'):
                        cached.update(observation=observation, state='ready', error=None)
            return self.view()
        finally:
            self.refresh_lock.release()


def sources_for(server):
    with bounded_process_lock(_CREATION_LOCK, resource='RSS service initialization'):
        if not hasattr(server, 'rss_sources'):
            server.rss_sources = RSSSources(node=server.projects.node_path)
        return server.rss_sources
