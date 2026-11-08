# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable non-Git message collections; set-union sync, never database copying."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sqlite3
import stat
from pathlib import Path
import time

from spikes.metadata import require, uuid
from spikes.reporting_schema import digest, encoded, fields, moment, hex_id
from spikes.reporting_scheduler import ReportingScheduler
from spikes.source_connectors import validate_item

MAX_PAYLOAD = 8*1024*1024


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def revision(item):
    # Transport hashes, importing clocks and observers cannot split one revision.
    return digest(encoded({k: item[k] for k in ('id', 'url', 'original_id', 'title', 'author',
                                               'published_at', 'content', 'content_sha256', 'source_locator', 'channel', 'privacy', 'retention')}))


def entry(project_id, kind, value):
    return dict(id=digest(encoded([project_id, kind, value])), project_id=project_id,
                kind=kind, value=value)


def validate_entry(row, project_id):
    fields(row, 'id project_id kind value'); uuid(project_id)
    require(row['project_id'] == project_id, 'Pool project mismatch'); hex_id(row['id'])
    v = row['value']; kind = row['kind']
    if kind == 'item':
        fields(v, 'revision item'); validate_item(dict(v['item'], discovered_at=stamp(0)))
        require(v['item']['discovered_at'] is None, 'Observation time belongs to observation')
        require(v['revision'] == revision(v['item']), 'Pool content revision mismatch')
        # Observations, not item identity, carry node clocks and raw feed hashes.
        require(v['item']['imported_at'] is None and v['item']['provenance']['raw_sha256'] is None,
                'Pool item must have transport-independent provenance')
    elif kind == 'membership':
        fields(v, 'pool_id item_entry filter_id filter_revision selected_at expires_at reason privacy')
        uuid(v['pool_id']); uuid(v['filter_id']); uuid(v['filter_revision']); hex_id(v['item_entry'])
        require(moment(v['selected_at']) < moment(v['expires_at']), 'Invalid pool membership lifetime')
        require((moment(v['expires_at'])-moment(v['selected_at'])).total_seconds() <= 3650*86400,
                'Pool membership lifetime exceeds limit')
        require(v['privacy'] in {'public', 'project', 'confidential', 'local-only'}, 'Invalid membership privacy')
        require(isinstance(v['reason'], str) and 0 < len(v['reason']) <= 4000, 'Invalid filter reason')
    elif kind == 'observation':
        fields(v, 'item_entry node_id observed_at raw_sha256 expires_at')
        hex_id(v['item_entry']); moment(v['observed_at']); moment(v['expires_at'])
        if v['node_id'] is not None: uuid(v['node_id'])
        if v['raw_sha256'] is not None: hex_id(v['raw_sha256'])
    else:
        require(False, 'Unknown pool entry kind')
    require(row == entry(project_id, kind, v), 'Pool entry digest mismatch')
    return row


class MessagePools:
    def __init__(self, node, *, clock=time.time, scheduler=None):
        self.scheduler = scheduler or ReportingScheduler(node, clock=clock)
        self.clock = clock
        self.root = self.scheduler.root / 'message-pools'
        creating = not self.root.exists()
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and self.root.resolve() == self.root and
                info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'Unsafe pool root')
        self.path = self.root / 'pools.sqlite'
        require(creating or self.path.is_file(), 'Message pool database is missing; recovery required')
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600) if creating else None
        if fd is not None: os.close(fd)
        with self.db(initialize=creating) as db:
            if creating:
                for sql in '''
                CREATE TABLE IF NOT EXISTS pool_entries(
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL, document BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS pool_project ON pool_entries(project,kind);
                CREATE TABLE IF NOT EXISTS block_bindings(
                    project TEXT NOT NULL, source TEXT NOT NULL, document BLOB NOT NULL,
                    PRIMARY KEY(project,source));
                CREATE TABLE IF NOT EXISTS block_jobs(
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, state TEXT NOT NULL,
                    document BLOB NOT NULL, result BLOB);
                '''.split(';'):
                    if sql.strip(): db.execute(sql)
        from spikes.journal import sync_dir
        sync_dir(self.root); sync_dir(self.root.parent)

    @contextmanager
    def db(self, *, initialize=False):
        info = self.path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, 'Unsafe pool database')
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL'); db.execute('PRAGMA secure_delete=ON')
            db.execute('BEGIN IMMEDIATE')
            if initialize:
                db.execute('CREATE TABLE pool_schema(version INTEGER NOT NULL, node TEXT NOT NULL)')
                db.execute('INSERT INTO pool_schema VALUES(1,?)', (self.scheduler.owner[0],))
            require(db.execute('SELECT version,node FROM pool_schema').fetchall() ==
                    [(1, self.scheduler.owner[0])], 'Unknown pool schema or owner')
            if not initialize:
                expected = {'pool_schema': ['version','node'],
                    'pool_entries': ['id','project','kind','document'],
                    'block_bindings': ['project','source','document'],
                    'block_jobs': ['id','project','state','document','result']}
                require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == set(expected), 'Unknown pool tables')
                for table, columns in expected.items():
                    require([r[1] for r in db.execute('PRAGMA table_info('+table+')')] == columns, 'Unknown pool columns')
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()

    def _cleanup(self, db, project_id):
        rows = [json.loads(r[0]) for r in db.execute(
            'SELECT document FROM pool_entries WHERE project=?', (project_id,))]
        now = self.clock()
        alive = [r for r in rows if r['kind'] == 'membership' and
                 moment(r['value']['expires_at']).timestamp() > now]
        refs = {r['value']['item_entry'] for r in alive}
        keep = {r['id'] for r in alive} | refs | {r['id'] for r in rows if
            r['kind'] == 'observation' and r['value']['item_entry'] in refs and
            moment(r['value']['expires_at']).timestamp() > now}
        db.executemany('DELETE FROM pool_entries WHERE id=?', [(r['id'],) for r in rows if r['id'] not in keep])
        # Frozen runs are also bounded managed copies; never resurrect expired input.
        for id_, raw in db.execute('SELECT id,document FROM block_jobs WHERE project=?', (project_id,)).fetchall():
            value = json.loads(raw)
            state = db.execute('SELECT state FROM block_jobs WHERE id=?', (id_,)).fetchone()[0]
            if value.get('expires_at', now+1) <= now and state not in {'dispatching', 'unknown'}:
                db.execute('DELETE FROM block_jobs WHERE id=?', (id_,))
            elif value.get('expires_at', now+1) <= now and 'expired' not in value:
                minimal = {k: value[k] for k in ('kind','source_id','source_ref','project_id','started_at') if k in value}
                minimal['expired'] = True
                db.execute("UPDATE block_jobs SET state='unknown',document=?,result=NULL WHERE id=?", (encoded(minimal),id_))

    def _merge(self, db, project_id, rows, *, checkpoint=lambda stage: None):
        require(isinstance(rows, list) and len(rows) <= 20000 and len(encoded(rows)) <= MAX_PAYLOAD,
                'Pool sync exceeds bounded payload; split the transfer')
        for row in rows: validate_entry(row, project_id)
        require(len({r['id'] for r in rows}) == len(rows), 'Duplicate pool sync entry')
        known = {r[0]: json.loads(r[1]) for r in db.execute(
            'SELECT id,document FROM pool_entries WHERE project=?', (project_id,))}
        all_ = dict(known, **{r['id']: r for r in rows})
        for row in rows:
            v = row['value']
            if row['kind'] in {'membership', 'observation'}:
                require(v['item_entry'] in all_ and all_[v['item_entry']]['kind'] == 'item',
                        'Pool reference is incomplete')
                if row['kind'] == 'membership':
                    from spikes.reporting_schema import PRIVACY
                    item = all_[v['item_entry']]['value']['item']
                    require(PRIVACY[v['privacy']] >= PRIVACY[item['privacy']], 'Membership lowers item privacy')
            require(row['id'] not in known or known[row['id']] == row, 'Conflicting immutable pool entry')
        for row in rows:
            db.execute('INSERT OR IGNORE INTO pool_entries VALUES(?,?,?,?)',
                       (row['id'], project_id, row['kind'], encoded(row)))
        checkpoint('pool-inserted')
        self._cleanup(db, project_id)

    def merge(self, project_id, rows, *, checkpoint=lambda stage: None):
        with self.db() as db:
            self._merge(db, project_id, rows, checkpoint=checkpoint)
        checkpoint('pool-committed')

    def export(self, project_id, *, transferable=False):
        with self.db() as db:
            self._cleanup(db, project_id)
            rows = [json.loads(r[0]) for r in db.execute(
                'SELECT document FROM pool_entries WHERE project=? ORDER BY id', (project_id,))]
        if transferable:
            # local-only membership can share an item with less restrictive pools:
            # only independently permitted memberships and their inputs leave.
            members = [r for r in rows if r['kind'] == 'membership' and r['value']['privacy'] != 'local-only']
            refs = {r['value']['item_entry'] for r in members}
            rows = [r for r in rows if r in members or
                    r['kind'] == 'item' and r['id'] in refs or
                    r['kind'] == 'observation' and r['value']['item_entry'] in refs]
            require(all(r['value']['item']['privacy'] != 'local-only' for r in rows if r['kind'] == 'item'),
                    'Local-only pool item cannot be synchronized')
        if transferable:
            require(len(encoded(rows)) <= MAX_PAYLOAD, 'Pool export exceeds transfer limit')
        return rows

    def view(self, project_id, pool_id, *, since=None):
        uuid(pool_id)
        rows = self.export(project_id); by_id = {r['id']: r for r in rows}; grouped = {}
        for row in rows:
            if row['kind'] != 'membership' or row['value']['pool_id'] != pool_id: continue
            v = row['value']; item = by_id[v['item_entry']]['value']['item']
            if since is not None and moment(v['selected_at']).timestamp() < since: continue
            key = item['url'] or item['id']
            group = grouped.setdefault(key, dict(key=key, revisions={}, contributions=[], observations=[]))
            rev = by_id[v['item_entry']]['value']['revision']
            group['revisions'][rev] = dict(item=item, item_entry=v['item_entry'], revision=rev)
            group['contributions'].append(dict(v, membership_id=row['id']))
        for group in grouped.values():
            refs = {r['item_entry'] for r in group['revisions'].values()}
            group['observations'] = [r['value'] for r in rows if
                r['kind'] == 'observation' and r['value']['item_entry'] in refs]
            group['revisions'] = sorted(group['revisions'].values(), key=lambda r: r['revision'])
            for r in group['revisions']:
                times = [o['observed_at'] for o in group['observations'] if o['item_entry'] == r['item_entry']]
                r['item'] = dict(r['item'], discovered_at=min(times) if times else None)
            group['concurrent_versions'] = len(group['revisions']) > 1
        return sorted(grouped.values(), key=lambda r: r['key'])
