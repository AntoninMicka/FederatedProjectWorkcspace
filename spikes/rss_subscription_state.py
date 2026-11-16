# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Causal reader preferences in the existing subscriptions transaction."""
from contextlib import contextmanager
import json
import os
import stat
from uuid import uuid4,uuid5,NAMESPACE_URL

from spikes.metadata import require,uuid
from spikes.federation_accounts import canonical
from spikes.reporting_schema import digest
from spikes.rss_subscriptions import Subscriptions,channel,MAX_CHANNELS
from spikes.sqlite_ownership import sqlite_connection
from spikes.journal import sync_dir

MAX_EVENTS=10000
MAX_BYTES=2*1024*1024


def store(node):
    from spikes.rss_sources import CHANNELS
    return Subscriptions(node,[dict(c,poll_seconds=c.get('poll_seconds',900)) for c in CHANNELS])


def value(c):
    c=channel(c)
    return {k:c[k] for k in ('name','url','poll_seconds')}


def event(url,parents,v,actor):
    body=dict(url=url,parents=sorted(parents),value=v,actor=actor)
    return dict(body,id=digest(canonical(body)))


def checked(events):
    require(isinstance(events,list) and len(events)<=MAX_EVENTS and len(canonical(events))<=MAX_BYTES,'RSS history exceeds limit')
    result={}
    from spikes.public_source import normalize_url
    for e in events:
        require(isinstance(e,dict) and set(e)=={'id','url','parents','value','actor'},'Invalid RSS revision')
        uuid(e['actor']);require(normalize_url(e['url'])==e['url'],'Invalid RSS URL')
        require(isinstance(e['parents'],list) and all(isinstance(p,str) for p in e['parents'])
                and len(e['parents'])<=MAX_EVENTS and e['parents']==sorted(set(e['parents'])),'Invalid RSS parents')
        if e['value'] is not None:
            require(isinstance(e['value'],dict) and set(e['value'])=={'name','url','poll_seconds'},'Invalid RSS value')
            require(value(dict(e['value'],id='wire'))==e['value'] and e['value']['url']==e['url'],'Invalid RSS value')
        require(event(e['url'],e['parents'],e['value'],e['actor'])==e,'RSS revision digest differs')
        require(e['id'] not in result,'Duplicate RSS revision');result[e['id']]=e
    for e in events:
        require(all(p in result and result[p]['url']==e['url'] for p in e['parents']),'Missing RSS ancestor')
    # Hashes bind parents; additionally require an acyclic causal graph.
    from collections import deque
    degree={id_:len(e['parents']) for id_,e in result.items()};children={id_:[] for id_ in result}
    for id_,e in result.items():
        for parent in e['parents']:children[parent].append(id_)
    ready=deque(id_ for id_,n in degree.items() if not n);done=0
    while ready:
        id_=ready.popleft();done+=1
        for child in children[id_]:
            degree[child]-=1
            if not degree[child]:ready.append(child)
    require(done==len(result),'Cyclic RSS history')
    return result


def tips(events):
    parents={p for e in events.values() for p in e['parents']};by_url={}
    for id_,e in events.items():
        if id_ not in parents:by_url.setdefault(e['url'],[]).append(e)
    return by_url


def ensure(db,node,channels):
    db.execute('CREATE TABLE IF NOT EXISTS rss_sync_meta(id INTEGER PRIMARY KEY,version INTEGER NOT NULL,actor TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS rss_sync_events(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
    db.execute("CREATE TABLE IF NOT EXISTS rss_sync_peers(id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,state TEXT NOT NULL,detail TEXT NOT NULL,sent TEXT NOT NULL DEFAULT '',remote TEXT NOT NULL DEFAULT '')")
    row=db.execute('SELECT version,actor FROM rss_sync_meta WHERE id=1').fetchone()
    if not row:
        actor=str(uuid4())
        if node.exists():actor=json.loads(node.read_text())['id'];uuid(actor)
        db.execute('INSERT INTO rss_sync_meta VALUES(1,1,?)',(actor,))
        for c in channels:
            e=event(c['url'],[],value(c),str(uuid5(NAMESPACE_URL,'fpw-rss-seed')))
            db.execute('INSERT OR IGNORE INTO rss_sync_events VALUES(?,?)',(e['id'],canonical(e).decode()))
        return actor
    require(row[0]==1,'Unsupported RSS synchronization schema');uuid(row[1])
    if node.exists():require(row[1]==json.loads(node.read_text())['id'],'RSS preference owner changed; recovery required')
    return row[1]


def events_in(db):
    return checked([json.loads(r[0]) for r in db.execute('SELECT document FROM rss_sync_events ORDER BY id')])


def record_local(db,node,old,new):
    actor=ensure(db,node,old);existing=events_in(db);current=tips(existing)
    before={c['url']:value(c) for c in old};after={c['url']:value(c) for c in new}
    for url in sorted(before.keys()|after.keys()):
        if before.get(url)==after.get(url):continue
        e=event(url,[e['id'] for e in current.get(url,[])],after.get(url),actor)
        db.execute('INSERT OR IGNORE INTO rss_sync_events VALUES(?,?)',(e['id'],canonical(e).decode()))
    events_in(db)


@contextmanager
def writing(node):
    s=store(node);s.path.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(s.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    except FileExistsError:require(not s.path.is_symlink(),'Unsafe RSS preferences')
    else:os.close(fd)
    info=s.path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
            and not info.st_mode&0o077,'Unsafe RSS preferences')
    with sqlite_connection(s.path,resource='Node preferences') as db:
        db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,document TEXT NOT NULL)')
        row=db.execute('SELECT revision,document FROM subscriptions WHERE id=1').fetchone()
        channels=json.loads(row[1]) if row else s.defaults
        ensure(db,s.node,channels)
        yield db,s,row[0] if row else 0,channels
    sync_dir(s.path.parent)


def view(node):
    s=store(node)
    if not s.path.exists():return dict(peers=[],conflicts=[])
    require(not s.path.is_symlink(),'Unsafe RSS preferences')
    with sqlite_connection(s.path.as_uri()+'?mode=ro',uri=True,resource='Node preferences') as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rss_sync_meta'").fetchone():return dict(peers=[],conflicts=[])
        ensure_version=db.execute('SELECT version FROM rss_sync_meta WHERE id=1').fetchone()
        require(ensure_version==(1,),'Unsupported RSS synchronization schema')
        peers=[dict(id=r[0],enabled=bool(r[1]),state=r[2],detail=r[3]) for r in db.execute('SELECT id,enabled,state,detail FROM rss_sync_peers ORDER BY id')]
        conflicts=[]
        for url,versions in tips(events_in(db)).items():
            if len({canonical(e['value']) for e in versions})>1:
                conflicts.append(dict(url=url,versions=sorted(versions,key=lambda e:e['id'])))
        return dict(peers=peers,conflicts=conflicts)


def configure(node,peer,enabled,*,expected_enabled=None):
    uuid(peer);require(type(enabled) is bool,'Invalid RSS sharing choice')
    with writing(node) as (db,s,rev,channels):
        if expected_enabled is not None:
            require(type(expected_enabled) is bool,'Invalid previous RSS sharing choice')
            row=db.execute('SELECT enabled FROM rss_sync_peers WHERE id=?',(peer,)).fetchone()
            current=bool(row[0]) if row else False
            require(current==expected_enabled or current==enabled,'RSS sharing choice changed; refresh settings')
        db.execute('INSERT INTO rss_sync_peers(id,enabled,state,detail) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled',
                   (peer,int(enabled),'idle',''))


def enabled(node,peer):
    return any(p['id']==peer and p['enabled'] for p in view(node)['peers'])


def export(node,peer):
    require(enabled(node,peer),'RSS sharing is not enabled for this peer')
    with writing(node) as (db,s,rev,channels):return list(events_in(db).values())


def progress(node,peer,*,sent=None,remote=None,state='idle',detail=''):
    with writing(node) as (db,s,rev,channels):
        require(db.execute('SELECT enabled FROM rss_sync_peers WHERE id=?',(peer,)).fetchone()==(1,),'RSS sharing disabled')
        db.execute('UPDATE rss_sync_peers SET state=?,detail=? WHERE id=?',(state,detail,peer))
        for key,v in (('sent',sent),('remote',remote)):
            if v is not None:db.execute('UPDATE rss_sync_peers SET '+key+'=? WHERE id=?',(v,peer))


def fingerprints(node,peer):
    with writing(node) as (db,s,rev,channels):
        return db.execute('SELECT sent,remote FROM rss_sync_peers WHERE id=?',(peer,)).fetchone() or ('','')


def materialize(db,revision,channels,*,force_revision=False):
    current={c['url']:c for c in channels};merged=[]
    for url,versions in sorted(tips(events_in(db)).items()):
        distinct={canonical(e['value']) for e in versions}
        if len(distinct)>1:
            if url in current:merged.append(current[url])
            continue
        v=versions[0]['value']
        if v is not None:
            merged.append(channel(dict(v,id=current.get(url,{}).get('id') or str(uuid5(NAMESPACE_URL,'fpw-reader:'+url)))))
    require(len(merged)<=MAX_CHANNELS and len({c['id'] for c in merged})==len(merged),'Merged RSS subscriptions exceed limits or duplicate identities')
    if force_revision or sorted(merged,key=lambda c:c['url'])!=sorted(channels,key=lambda c:c['url']):
        db.execute('INSERT OR REPLACE INTO subscriptions VALUES(1,?,?)',(revision+1,json.dumps(merged,ensure_ascii=False)))


def apply(node,peer,incoming,*,checkpoint=lambda stage:None):
    checked(incoming)
    with writing(node) as (db,s,rev,channels):
        require(db.execute('SELECT enabled FROM rss_sync_peers WHERE id=?',(peer,)).fetchone()==(1,),'RSS sharing disabled')
        combined=events_in(db);changed=any(e['id'] not in combined for e in incoming)
        combined.update({e['id']:e for e in incoming});checked(list(combined.values()))
        for e in incoming:db.execute('INSERT OR IGNORE INTO rss_sync_events VALUES(?,?)',(e['id'],canonical(e).decode()))
        checkpoint('events-staged');materialize(db,rev,channels,force_revision=changed);checkpoint('subscriptions-staged')
        db.execute("UPDATE rss_sync_peers SET state='idle',detail='' WHERE id=?",(peer,))
    checkpoint('committed')


def resolve(node,url,chosen,expected,expected_tips):
    require(type(expected) is int and expected>=0,'Invalid RSS review revision')
    with writing(node) as (db,s,rev,channels):
        require(rev==expected,'RSS preferences changed; refresh conflict review')
        versions=tips(events_in(db)).get(url,[])
        require(isinstance(expected_tips,list) and sorted(expected_tips)==sorted(e['id'] for e in versions),'Conflict revisions changed; refresh review')
        selected=next((e for e in versions if e['id']==chosen),None)
        require(selected and len({canonical(e['value']) for e in versions})>1,'Conflict changed; refresh review')
        actor=db.execute('SELECT actor FROM rss_sync_meta WHERE id=1').fetchone()[0]
        e=event(url,[v['id'] for v in versions],selected['value'],actor)
        db.execute('INSERT INTO rss_sync_events VALUES(?,?)',(e['id'],canonical(e).decode()))
        materialize(db,rev,channels,force_revision=True)
