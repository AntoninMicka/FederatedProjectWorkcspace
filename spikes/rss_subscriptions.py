# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local reader subscriptions; atomic preferences, never project artifacts."""
import json
import os
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import xml.etree.ElementTree as ET

from spikes.journal import sync_dir
from spikes.metadata import require
from spikes.public_source import normalize_url
from spikes.rss_reader import BoundedTree
from spikes.sqlite_ownership import sqlite_connection

MAX_IMPORT = 512 * 1024
MAX_CHANNELS = 1000


def channel(value):
    require(isinstance(value, dict) and value.keys() == {'id', 'name', 'url', 'poll_seconds'}, 'Neplatná pole kanálu.')
    require(isinstance(value['id'], str) and 0 < len(value['id']) <= 100, 'Neplatné ID kanálu.')
    require(isinstance(value['name'], str) and 0 < len(value['name'].strip()) <= 300, 'Vyplňte název (nejvýše 300 znaků).')
    require(type(value['poll_seconds']) is int and 60 <= value['poll_seconds'] <= 604800, 'Perioda musí být 1 minuta až 7 dní.')
    return dict(value, name=value['name'].strip(), url=normalize_url(value['url']))


def preview(text, existing):
    require(isinstance(text, str) and len(text.encode()) <= MAX_IMPORT, 'Import je omezen na 512 KiB.')
    if text.lstrip().startswith('<'):
        try:
            root = ET.fromstring(text, parser=ET.XMLParser(target=BoundedTree()))
        except ET.ParseError as exc:
            raise ValueError('Neplatné XML/OPML.') from exc
        require(root.tag == 'opml' and root.find('body') is not None, 'Očekáván seznam odběrů OPML, nikoli RSS obsah.')
        rows = [dict(url=e.get('xmlUrl'), title=e.get('title') or e.get('text')) for e in root.iter('outline') if e.get('xmlUrl')]
    else:
        try: rows = json.loads(text)
        except ValueError as exc: raise ValueError('Neplatný JSON seznam odběrů.') from exc
        if isinstance(rows, dict): rows = rows.get('subscriptions')
        require(isinstance(rows, list), 'JSON musí být pole odběrů nebo objekt subscriptions.')
    require(len(rows) <= MAX_CHANNELS, 'Import obsahuje příliš mnoho odběrů (maximum 1000).')
    seen = {c['url'] for c in existing}; result, errors, duplicates = [], [], 0
    for index, row in enumerate(rows):
        try:
            require(isinstance(row, dict), 'Neplatný odběr.')
            url = row.get('url') or row.get('xmlUrl') or row.get('feedUrl') or row.get('feedId')
            if isinstance(url, str) and url.startswith('feed/'): url = url[5:]
            url = normalize_url(url)
            if url in seen: duplicates += 1; continue
            item = channel(dict(id=str(uuid5(NAMESPACE_URL, 'fpw-reader:'+url)),
                name=row.get('title') or row.get('name') or url, url=url, poll_seconds=900))
            result.append(item); seen.add(url)
        except (ValueError, TypeError):
            errors.append(dict(row=index+1, error='Neplatný název nebo URL; podporovány jsou veřejné HTTPS kanály bez přihlašovacích údajů.'))
    return dict(channels=result, duplicates=duplicates, errors=errors)


class Subscriptions:
    def __init__(self, node, defaults):
        self.path = Path(node).absolute().with_suffix('.rss-subscriptions.sqlite3')
        self.defaults = defaults

    def load(self):
        if not self.path.exists(): return 0, self.defaults
        require(not self.path.is_symlink(), 'Nastavení odběrů nesmí být symlink.')
        with sqlite_connection(f'{self.path.as_uri()}?mode=ro', uri=True, resource='Node preferences') as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='subscriptions'").fetchone()
            row = db.execute('SELECT revision,document FROM subscriptions WHERE id=1').fetchone() if exists else None
        if row is None: return 0, self.defaults
        return row[0], [channel(c) for c in json.loads(row[1])]

    def save(self, revision, channels, *, checkpoint=lambda: None):
        channels = [channel(c) for c in channels]
        require(len(channels) <= MAX_CHANNELS and len({c['id'] for c in channels}) == len(channels)
                and len({c['url'] for c in channels}) == len(channels), 'Duplicitní kanál nebo překročený limit 1000.')
        require(type(revision) is int and revision >= 0, 'Neplatná revize odběrů.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try: fd = os.open(self.path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        except FileExistsError: require(not self.path.is_symlink(), 'Nastavení odběrů nesmí být symlink.')
        else: os.close(fd)
        with sqlite_connection(self.path, resource='Node preferences') as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,document TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,document FROM subscriptions WHERE id=1').fetchone()
            current = row[0] if row else 0
            # Exact resubmission after a lost response is harmless.
            if row and json.loads(row[1]) == channels: return current
            require(current == revision, 'Odběry se změnily; obnovte přehled a zkontrolujte úpravu.')
            db.execute('INSERT OR REPLACE INTO subscriptions VALUES(1,?,?)', (current+1, json.dumps(channels,ensure_ascii=False)))
            checkpoint()
        sync_dir(self.path.parent)
        return current+1
