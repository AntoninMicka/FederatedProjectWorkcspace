# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Manual public-feed cache, independent of project data and monitoring."""
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
from spikes.metadata import require
from spikes.public_source import PublicSourceError
from spikes.rss_reader import fetch, observe, parse_feed

CHANNELS = ({'id': 'ct24-editorial', 'name': 'ČT24 — Výběr redakce',
             'url': 'https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313'},)
_CREATION_LOCK = threading.Lock()


class RSSSources:
    def __init__(self, *, channels=CHANNELS, fetcher=fetch, clock=time.monotonic):
        self.channels = deepcopy(channels)
        self.fetcher, self.clock = fetcher, clock
        self.lock, self.refresh_lock = threading.Lock(), threading.Lock()
        self.cache = {c['id']: dict(observation=None, error=None, state='unloaded', attempted=None)
                      for c in self.channels}

    def view(self):
        with self.lock:
            channels, entries = [], []
            for channel in self.channels:
                cached = self.cache[channel['id']]
                observation = cached['observation']
                channels.append(dict(channel, state=cached['state'], error=cached['error'],
                    checked_at=observation['observed_at'] if observation else None,
                    counts=observation['counts'] if observation else None))
                if observation:
                    for record in observation['records']:
                        revision = record['revisions'][-1]
                        entries.append(dict(revision['entry'], id=record['id'],
                            channel_id=channel['id'], channel_name=channel['name'],
                            observed_at=revision['observed_at'], revisions=len(record['revisions'])))
            entries.sort(key=lambda e: (e['published_at'] or e['observed_at'], e['id']), reverse=True)
            return deepcopy(dict(channels=channels, entries=entries))

    def refresh(self, channel_id):
        require(channel_id == 'all' or channel_id in self.cache, 'Neznámý kanál.')
        require(self.refresh_lock.acquire(blocking=False), 'Načítání již probíhá. Obnovte přehled.')
        try:
            for channel in self.channels:
                if channel_id not in {'all', channel['id']}:
                    continue
                with self.lock:
                    cached = self.cache[channel['id']]
                    require(cached['attempted'] is None or self.clock() - cached['attempted'] >= 30,
                            'Další načtení kanálu je možné po 30 sekundách.')
                    cached['attempted'] = self.clock()
                    cached['state'] = 'loading'
                    previous = cached['observation']
                try:
                    raw = self.fetcher(channel['url'])
                    observation = observe(parse_feed(raw, channel['url']),
                        datetime.now(timezone.utc).isoformat(), previous)
                except (ValueError, OSError, PublicSourceError) as exc:
                    with self.lock:
                        cached['state'] = 'unknown' if getattr(exc, 'state', '') == 'unknown' else 'failed'
                        cached['error'] = str(exc)
                else:
                    with self.lock:
                        cached.update(observation=observation, state='ready', error=None)
            return self.view()
        finally:
            self.refresh_lock.release()


def sources_for(server):
    with _CREATION_LOCK:
        if not hasattr(server, 'rss_sources'):
            server.rss_sources = RSSSources()
        return server.rss_sources
