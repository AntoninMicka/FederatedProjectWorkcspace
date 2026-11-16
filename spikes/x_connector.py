# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit paid X API reads; node-local subscriptions, reservations and recovery.

No automatic dispatch, remote activation, scraping or provider fallback.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import time
from urllib.parse import urlencode
from uuid import uuid4

from spikes.journal import sync_dir
from spikes.metadata import require, uuid
from spikes.reporting_schema import encoded, digest, fields
from spikes.sqlite_ownership import sqlite_connection

MAX_BYTES=512*1024
MAX_REQUESTS=10000
PRICE_REVIEW='2026-11-16'
DOCS='https://docs.x.com/x-api/getting-started/pricing'


class XReadError(ValueError):
    pass


class XUnknown(XReadError):
    pass


def numeric_id(value):
    require(isinstance(value,str) and re.fullmatch(r'[0-9]{1,19}',value),'X requires a numeric account/post ID')
    return value


def validate_subscription(value):
    fields(value,'id name kind value enabled retention_days terms lookback_hours')
    uuid(value['id']);require(value['kind'] in {'account','recent-search'},'Unsupported X source kind')
    require(type(value['enabled']) is bool,'Invalid X subscription activation')
    for key,limit in [('name',200),('value',512),('terms',4000)]:
        require(isinstance(value[key],str) and 0<len(value[key].strip())<=limit and not any(ord(c)<32 for c in value[key]),'Invalid X '+key)
    if value['kind']=='account':numeric_id(value['value'])
    require(type(value['retention_days']) is int and 1<=value['retention_days']<=30,'X retention must be 1..30 days')
    require(type(value['lookback_hours']) is int and 1<=value['lookback_hours']<=167,'X initial lookback must be 1..167 hours')
    return value


def subscription_digest(sub):
    return digest(encoded({key:sub[key] for key in ('kind','value','retention_days','terms','lookback_hours')}))


def post_aliases(item):
    aliases={item['original_id']}
    origin=item['provenance']['origin']
    if origin.startswith('x-api-post:'):aliases.update(re.findall(r'[0-9]{1,19}',origin))
    return aliases


def matches_post(item,blocked):
    return item.get('connector')=='x-twitter' and bool(post_aliases(item)&blocked)


def normalize(payload,context):
    from spikes.source_connectors import item,batch,utc
    context.validate()
    require(isinstance(payload,dict) and not payload.get('errors'),'X returned partial/error data; not a complete successful read')
    posts=payload.get('data',[]);require(type(payload.get('meta',{}).get('result_count')) is int and payload['meta']['result_count']==len(posts),'Invalid X result count');require(isinstance(posts,list) and len(posts)<=100,'Invalid X post batch')
    items=[]
    for post in posts:
        require(isinstance(post,dict) and not post.get('withheld'),'X content is withheld/unavailable; no text imported')
        post_id=numeric_id(post.get('id'));history=post.get('edit_history_post_ids',post.get('edit_history_tweet_ids',[post_id]))
        require(isinstance(history,list) and history and len(history)<=20,'Invalid X edit history')
        for id_ in history:numeric_id(id_)
        require(post_id in history,'X edit history omits the returned post')
        content=post.get('text');require(isinstance(content,str) and 0<len(content)<=131072,'Invalid X post text')
        published=post.get('created_at')
        if published is not None:utc(published)
        author=post.get('author_id')
        if author is not None:numeric_id(author)
        normalized=item('x-twitter',context,original_id=history[0],url='https://x.com/i/web/status/'+history[0],
            author=author,published_at=published,content=content,raw_sha256=digest(encoded(post)))
        normalized['provenance']['origin']='x-api-post:'+post_id+';edit-history:'+','.join(history)
        items.append(normalized)
    return batch('x-twitter',items)


def request_page(path,parameters,token):
    """Fixed TLS origin; no redirects, cookies, user lookup or HTTP retries."""
    connection=http.client.HTTPSConnection('api.x.com',timeout=20,context=ssl.create_default_context())
    try:
        connection.request('GET',path+'?'+urlencode(parameters),headers={'Authorization':'Bearer '+token,'Accept':'application/json','Accept-Encoding':'identity'})
        response=connection.getresponse()
        raw=response.read(MAX_BYTES+1)
        require(len(raw)<=MAX_BYTES,'X response exceeds 512 KiB')
        require(not response.getheader('Content-Encoding') or response.getheader('Content-Encoding')=='identity','Unexpected X content encoding')
        if response.status!=200:
            # Never include response body, headers or request credentials in errors.
            if response.status==429:raise XReadError('X API rate limit (429); wait and start a new explicit read')
            if response.status in {401,402,403}:raise XReadError('X API access/credits unavailable (HTTP '+str(response.status)+')')
            raise XReadError('X API read failed (HTTP '+str(response.status)+')')
        require(response.getheader('Content-Type','').split(';')[0].strip()=='application/json','Unexpected X content type')
        return json.loads(raw)
    finally:connection.close()


class XService:
    def __init__(self,node,*,clock=time.time,transport=request_page):
        self.node=Path(node).absolute();self.clock=clock;self.transport=transport
        self.root=self.node.parent/('.'+self.node.name+'.x-api');self.path=self.root/'state.sqlite'

    def _owned(self,path,directory=False):
        info=path.lstat()
        require(path.resolve()==path and info.st_uid==os.getuid() and not info.st_mode&0o077 and
                (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink==1),'Unsafe X local state')

    @contextmanager
    def db(self,*,create=False,write=False):
        if create:
            self.root.mkdir(mode=0o700,exist_ok=True);self._owned(self.root,True)
            if not self.path.exists():
                fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd)
        self._owned(self.root,True);self._owned(self.path)
        url=str(self.path) if write else self.path.as_uri()+'?mode=ro'
        with sqlite_connection(url,uri=not write,resource='X API journal',timeout=1) as db:
            if write:
                db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA secure_delete=ON');db.execute('BEGIN IMMEDIATE')
                if create:
                    db.execute('CREATE TABLE IF NOT EXISTS tombstones(id TEXT PRIMARY KEY)')
                    db.execute('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),document TEXT NOT NULL)')
                    db.execute('CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,document TEXT NOT NULL,cursor TEXT,cursor_at REAL)')
                    db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,month TEXT,signature TEXT,state TEXT,reserved INTEGER,expires REAL,document TEXT,result TEXT)')
            else:db.execute('BEGIN')
            yield db

    def _settings(self,db):
        row=db.execute('SELECT document FROM settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else dict(enabled=False,credential_id=None,monthly_budget_micro_usd=0,post_price_micro_usd=5000,max_results=10,max_pages=1,price_review=PRICE_REVIEW)

    def _revision(self,db):
        return digest(encoded([self._settings(db),[json.loads(r[0]) for r in db.execute('SELECT document FROM subscriptions ORDER BY id')]]))

    def view(self):
        if not self.path.exists():
            return dict(configured=False,revision=None,settings=None,subscriptions=[],requests=[],pricing_url=DOCS,untested=True)
        self.purge()
        with self.db() as db:
            config=self._settings(db);month=datetime.fromtimestamp(self.clock(),timezone.utc).strftime('%Y-%m')
            reserved=db.execute('SELECT COALESCE(SUM(reserved),0) FROM requests WHERE month=?',(month,)).fetchone()[0]
            subscriptions=[dict(json.loads(r[0]),fingerprint=subscription_digest(json.loads(r[0]))) for r in db.execute('SELECT document FROM subscriptions ORDER BY id')]
            runs=[dict(id=r[0],state=r[1],reserved_micro_usd=r[2],expires_at=r[3],imported=bool(r[4]),subscription=r[5]) for r in db.execute("SELECT id,state,reserved,expires,json_extract(document,'$.acknowledged'),json_extract(document,'$.subscription.name') FROM requests ORDER BY rowid DESC LIMIT 30")]
            public={k:v for k,v in config.items() if k!='credential_id'}
            public['has_token']=bool(config['credential_id'])
            return dict(configured=True,revision=self._revision(db),settings=public,subscriptions=subscriptions,requests=runs,
                reserved_micro_usd=reserved,budget_month=month,pricing_url=DOCS,untested=True)

    def save(self,expected_revision,settings,subscriptions,*,token=None):
        fields(settings,'enabled monthly_budget_micro_usd post_price_micro_usd max_results max_pages price_review')
        require(type(settings['enabled']) is bool,'Invalid X enable state')
        for key,low,high in [('monthly_budget_micro_usd',1,1000000000),('post_price_micro_usd',1,1000000),('max_results',10,100),('max_pages',1,5)]:
            require(type(settings[key]) is int and low<=settings[key]<=high,'Invalid X '+key)
        require(isinstance(settings['price_review'],str) and re.fullmatch(r'\d{4}-\d\d-\d\d',settings['price_review']),'Confirm the pricing review date')
        require(isinstance(subscriptions,list) and len(subscriptions)<=128,'Too many X subscriptions')
        for subscription in subscriptions:validate_subscription(subscription)
        require(len({s['id'] for s in subscriptions})==len(subscriptions),'Duplicate X subscription')
        credential=None
        if token is not None:
            require(isinstance(token,str) and 10<=len(token)<=8192 and re.fullmatch(r'[A-Za-z0-9._~+/%=-]+',token),'Invalid X bearer token')
            self.root.mkdir(mode=0o700,exist_ok=True);self._owned(self.root,True)
            credential=str(uuid4());path=self.root/('credential-'+credential)
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(token.encode());stream.flush();os.fsync(stream.fileno())
            sync_dir(self.root)
        with self.db(create=True,write=True) as db:
            has_config=db.execute('SELECT 1 FROM settings').fetchone() is not None
            valid_revision=expected_revision==self._revision(db) if has_config else expected_revision in {None,self._revision(db)}
            require(valid_revision,'X settings changed; refresh before saving')
            old=self._settings(db);config=dict(settings,credential_id=credential or old['credential_id'])
            require(not config['enabled'] or config['credential_id'],'Configure an X bearer token before enabling paid reads')
            db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(encoded(config),))
            prior={r[0]:json.loads(r[1]) for r in db.execute('SELECT id,document FROM subscriptions')}
            for sub in subscriptions:
                existing=prior.pop(sub['id'],None)
                if existing and (existing['kind'],existing['value'],existing['lookback_hours'])!=(sub['kind'],sub['value'],sub['lookback_hours']):
                    require(not db.execute("SELECT 1 FROM requests WHERE state IN ('prepared','dispatching','unknown') AND json_extract(document,'$.subscription.id')=?",(sub['id'],)).fetchone(),'Unresolved X read belongs to this subscription')
                    db.execute('DELETE FROM subscriptions WHERE id=?',(sub['id'],))
                db.execute('INSERT INTO subscriptions(id,document) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',(sub['id'],encoded(sub)))
            for id_ in prior:db.execute('DELETE FROM subscriptions WHERE id=?',(id_,))
        return self.view()

    def _token(self,id_):
        uuid(id_);path=self.root/('credential-'+id_);self._owned(path)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:raw=os.read(fd,8193)
        finally:os.close(fd)
        require(10<=len(raw)<=8192,'Invalid stored X bearer token')
        token=raw.decode('ascii');require(re.fullmatch(r'[A-Za-z0-9._~+/%=-]+',token),'Invalid stored X bearer token')
        return token

    def collect(self,subscription_id,operation_id,context,*,confirm):
        """Reserve maximum cost before dispatch; same operation never auto-replays HTTP."""
        uuid(subscription_id);uuid(operation_id);context.validate()
        require(confirm is True and context.privacy!='local-only','Explicit paid-read consent and transferable source context are required')
        require(self.path.exists(),'X API is not configured')
        now=self.clock();month=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m')
        signature=digest(encoded([subscription_id,context.__dict__]))
        with self.db(write=True) as db:
            # Purge staged text, retaining intent, cost and operation tombstones.
            db.execute('UPDATE requests SET result=NULL WHERE expires<=?',(now,))
            row=db.execute('SELECT signature,state,result FROM requests WHERE id=?',(operation_id,)).fetchone()
            if row:
                require(row[0]==signature,'X operation belongs to a different request')
                if row[1]=='completed':
                    require(row[2] is not None,'X staged result expired; no automatic paid replay')
                    return json.loads(row[2])
                if row[1]=='prepared':raise XUnknown('X request was prepared before interruption; use a new explicit operation')
                raise XUnknown('X result '+row[1]+'; no automatic paid replay')
            config=self._settings(db);require(config['enabled'],'Paid X reads are disabled')
            subrow=db.execute('SELECT document,cursor,cursor_at FROM subscriptions WHERE id=?',(subscription_id,)).fetchone()
            require(subrow,'X subscription does not exist');sub=json.loads(subrow[0]);validate_subscription(sub)
            require(sub['enabled'],'X subscription is paused')
            require(context.locator=='x:'+subscription_id+':'+subscription_digest(sub),'X subscription changed; update the project source before a paid read')
            require(not db.execute("SELECT 1 FROM requests WHERE (state IN ('prepared','dispatching') OR (state='completed' AND COALESCE(json_extract(document,'$.acknowledged'),0)=0)) AND json_extract(document,'$.subscription.id')=?",(subscription_id,)).fetchone(),'Another X read is unresolved; inspect its status')
            require(subrow[2] is None or now-subrow[2]<7*86400,'X cursor coverage is older than 7 days; configure a new explicit subscription/window')
            reserve=config['max_results']*config['max_pages']*config['post_price_micro_usd']
            spent=db.execute('SELECT COALESCE(SUM(reserved),0) FROM requests WHERE month=?',(month,)).fetchone()[0]
            require(spent+reserve<=config['monthly_budget_micro_usd'],'X monthly local reservation budget would be exceeded')
            require(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]<MAX_REQUESTS,'X journal capacity reached; retain receipts before maintenance')
            intent=dict(subscription=sub,config={k:v for k,v in config.items() if k!='credential_id'},context=context.__dict__,cursor=subrow[1],window_end=now-30,window_start=subrow[2] if subrow[2] is not None else now-30-sub['lookback_hours']*3600)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)',(operation_id,month,signature,'prepared',reserve,now+min(sub['retention_days'],1)*86400,encoded(intent)))
        # Token is fetched before changing the durable state to dispatching.
        token=self._token(config['credential_id'])
        with self.db(write=True) as db:
            require(self._settings(db)==config,'X settings changed before dispatch')
            active=db.execute('SELECT document FROM subscriptions WHERE id=?',(subscription_id,)).fetchone()
            require(active and json.loads(active[0])==sub,'X subscription changed before dispatch')
            changed=db.execute("UPDATE requests SET state='dispatching' WHERE id=? AND state='prepared'",(operation_id,))
            require(changed.rowcount==1,'X dispatch state changed')
        try:
            pages=[];next_token=None;latest=subrow[1];next_history=set()
            for page in range(config['max_pages']):
                params={'max_results':config['max_results'],'post.fields':'created_at,edit_controls,withheld','end_time':datetime.fromtimestamp(intent['window_end'],timezone.utc).isoformat().replace('+00:00','Z')}
                if not subrow[1]:params['start_time']=datetime.fromtimestamp(intent['window_start'],timezone.utc).isoformat().replace('+00:00','Z')
                if sub['kind']=='account':path='/2/users/'+numeric_id(sub['value'])+'/tweets'
                else:path='/2/tweets/search/recent';params['query']=sub['value']
                if subrow[1]:params['since_id']=numeric_id(subrow[1])
                if next_token:params['pagination_token' if sub['kind']=='account' else 'next_token']=next_token
                payload=self.transport(path,params,token)
                from spikes.source_connectors import batch
                page_batch=normalize(payload,context);pages.extend(page_batch['items'])
                ids=[p.get('id') for p in payload.get('data',[])]
                if ids:latest=str(max([int(numeric_id(id_)) for id_ in ids]+([int(latest)] if latest else [])))
                next_token=payload.get('meta',{}).get('next_token')
                if not next_token:break
                require(isinstance(next_token,str) and 0<len(next_token)<=4096 and next_token not in next_history,'Invalid X pagination token')
                next_history.add(next_token)
            # Reaching the configured page ceiling is not a complete period.
            require(not next_token,'X page limit reached; incomplete read, cursor was not advanced')
            result=batch('x-twitter',pages)
            with self.db(write=True) as db:
                blocked={r[0] for r in db.execute('SELECT id FROM tombstones')}
                require(not any(matches_post(i,blocked) for i in result['items']),'X read contains locally withdrawn posts')
                changed=db.execute("UPDATE requests SET state='completed',result=? WHERE id=? AND state='dispatching'",(encoded(result),operation_id))
                require(changed.rowcount==1,'X read was closed before its result was accepted')
                intent['next_cursor']=latest;intent['acknowledged']=False
                db.execute('UPDATE requests SET document=? WHERE id=?',(encoded(intent),operation_id))
            return result
        except Exception as exc:
            state='failed' if isinstance(exc,(XReadError,ValueError)) else 'unknown'
            with self.db(write=True) as db:db.execute("UPDATE requests SET state=?,result=NULL WHERE id=? AND state='dispatching'",(state,operation_id))
            raise XReadError(str(exc) if isinstance(exc,XReadError) else 'X API read failed or is incomplete; reservation retained, no fallback') from None

    def operation_state(self,operation_id):
        if not self.path.exists():return None
        with self.db() as db:
            row=db.execute('SELECT state FROM requests WHERE id=?',(operation_id,)).fetchone()
            return row[0] if row else None

    def acknowledge(self,operation_id):
        uuid(operation_id)
        with self.db(write=True) as db:
            row=db.execute('SELECT state,document FROM requests WHERE id=?',(operation_id,)).fetchone()
            require(row and row[0]=='completed','X input read is not complete')
            intent=json.loads(row[1])
            if intent.get('acknowledged'):return
            sub=intent['subscription'];current=db.execute('SELECT document FROM subscriptions WHERE id=?',(sub['id'],)).fetchone()
            if current and json.loads(current[0])==sub:
                db.execute('UPDATE subscriptions SET cursor=?,cursor_at=? WHERE id=?',(intent.get('next_cursor'),intent['window_end'],sub['id']))
            intent['acknowledged']=True;db.execute('UPDATE requests SET document=? WHERE id=?',(encoded(intent),operation_id))

    def blocked_ids(self):
        if not self.path.exists():return set()
        with self.db() as db:return {r[0] for r in db.execute('SELECT id FROM tombstones')}

    def forget(self,post_id,*,confirm):
        numeric_id(post_id);require(confirm is True,'Confirm removing this X post from local staging and pools')
        with self.db(create=True,write=True) as db:db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(post_id,))
        self.purge()
        return dict(post_id=post_id,scope='this-node-raw-staging-and-pools',derived_reports_require_review=True)

    def purge(self):
        if not self.path.exists():return
        with self.db(write=True) as db:
            db.execute('UPDATE requests SET result=NULL WHERE expires<=? AND result IS NOT NULL',(self.clock(),))
            blocked={r[0] for r in db.execute('SELECT id FROM tombstones')}
            if blocked:
                for id_,raw in db.execute('SELECT id,result FROM requests WHERE result IS NOT NULL').fetchall():
                    result=json.loads(raw);removed=[i for i in result['items'] if matches_post(i,blocked)]
                    if removed:
                        for item in removed:
                            for alias in post_aliases(item):db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(alias,))
                        db.execute("UPDATE requests SET state='unavailable',result=NULL WHERE id=?",(id_,))
        blocked=self.blocked_ids()
        from spikes.message_pools import MessagePools
        root=self.node.parent/('.'+self.node.name+'.reporting-runs')/'message-pools'
        if not blocked or not root.exists():return
        pools=MessagePools(self.node)
        with pools.db() as db:
            rows=db.execute("SELECT id,project,document FROM pool_entries WHERE kind='item' AND json_extract(document,'$.value.item.connector')='x-twitter'").fetchall()
            for id_,pid,raw in rows:
                if matches_post(json.loads(raw)['value']['item'],blocked):
                    db.execute("DELETE FROM pool_entries WHERE project=? AND kind IN ('membership','observation') AND json_extract(document,'$.value.item_entry')=?",(pid,id_))
                    db.execute('DELETE FROM pool_entries WHERE project=? AND id=?',(pid,id_))

    def close_unknown(self,operation_id,*,confirm):
        require(confirm is True,'Confirm leaving the result unknown and preserving its reserved cost');uuid(operation_id)
        with self.db(write=True) as db:
            row=db.execute('SELECT state,document FROM requests WHERE id=?',(operation_id,)).fetchone()
            require(row and (row[0] in {'prepared','dispatching'} or row[0]=='completed' and not json.loads(row[1]).get('acknowledged')),'Only an unresolved X read can be closed')
            db.execute("UPDATE requests SET state='unknown',result=NULL WHERE id=?",(operation_id,))
        return self.view()
