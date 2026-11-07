# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Recurring RSS collection over the existing run journal and Workspace writer."""
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
import stat
import time
from uuid import uuid4

from spikes.metadata import require,uuid,validate_snapshot
from spikes.monitoring import ident
from spikes.reporting import Reporting,operation_uuid,pinned
from spikes.reporting_schema import digest,encoded,fields,records
from spikes.reporting_scheduler import ReportingScheduler
from spikes.rss_reader import fetch_response,parse_feed,observe,checked_validators,SCHEMA as OBSERVATION
from spikes.rss_reader import RSSUnavailable
from spikes.public_source import url_origin
from spikes.source_collector import SourceCollector,public_url
from spikes.source_connectors import RSSConnector,SourceContext,batch


class RSSMonitoring:
    def __init__(self,node,*,clock=time.time,fetcher=fetch_response,scheduler=None):
        self.node=node;self.clock=clock;self.fetcher=fetcher;self.reporting=Reporting(node)
        self.scheduler=scheduler or ReportingScheduler(node,clock=clock)
        self.collector=SourceCollector(node,clock=clock)

    def stamp(self):return self.scheduler.stamp()

    def _origin_backoff(self,url,until=None):
        with self.collector.locked() as runs:
            with runs.connect() as db:
                if until is not None:
                    db.execute('INSERT INTO collector_backoff VALUES(?,?) ON CONFLICT(origin) DO UPDATE SET until=MAX(until,excluded.until)',(url_origin(url),until));db.commit()
                row=db.execute('SELECT until FROM collector_backoff WHERE origin=?',(url_origin(url),)).fetchone()
        return row[0] if row else 0

    def _definition(self,config,ws=None,files=None,entities=None,*,grant=True):
        ws=ws or self.reporting.artifacts.workspace(config['project_id']);ws._writable()
        if files is None:files=ws.git.snapshot(ws.git.head());entities=validate_snapshot(files)
        rs=records(files,entities);row=rs.get(config['definition_ref']['artifact_id'])
        require(row is not None and row['type']=='WatchDefinition' and row['entity_id']==config['watch_id'],'RSS definition is missing')
        require(not any(any(p['artifact_id']==row['revision_id'] for p in r['previous']) for r in rs.values()),'RSS definition has been superseded')
        require(row['value']['active'] and row['privacy']!='local-only','RSS definition is paused or local-only')
        require(pinned(config['project_id'],config['definition_ref']['commit_id'],row['revision_id'],
            ws.git.snapshot(config['definition_ref']['commit_id']),entities)==config['definition_ref'],'RSS definition pin differs')
        inputs=[i for i in row['value']['inputs'] if i['id']==config['input_id']]
        require(len(inputs)==1 and inputs[0]['kind']=='external' and inputs[0]['connector']=='rss-atom','Expected RSS input')
        require(row['value']['placement']['mode']=='local','Remote RSS placement is not connected')
        if grant:
            require(self.scheduler.watch_granted(config['project_id'],config['watch_id'],digest(encoded(row['value']))),'RSS approval was revoked')
            with self.scheduler.db() as db:
                binding=db.execute('SELECT document FROM rss_bindings WHERE key=?',(config['key'],)).fetchone()
            require(binding and json.loads(binding[0])['enabled'],'RSS collection was paused')
        return ws,row,inputs[0]

    def configure(self,request,*,confirm=False):
        fields(request,'project_id watch_id input_id definition_ref enabled mode')
        require(confirm is True and type(request['enabled']) is bool,'Explicit RSS configuration confirmation is required')
        require(request['mode'] in {'capture-only','queue-all'},'Unknown RSS collection mode')
        for key in ('project_id','watch_id','input_id'):uuid(request[key])
        config=deepcopy(request);key='/'.join(config[k] for k in ('project_id','watch_id','input_id'))
        if not request['enabled']:
            self.reporting.artifacts.workspace(request['project_id'])._writable()
            with self.scheduler.db() as db:
                old=db.execute('SELECT document FROM rss_bindings WHERE key=?',(key,)).fetchone()
                require(old is not None,'RSS binding does not exist')
                paused=json.loads(old[0]);paused['enabled']=False
                db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(paused),key))
            return paused
        _,row,input_=self._definition(config,grant=False)
        public_url(input_['locator'])
        SourceContext(config['input_id'],input_['locator'],self.stamp(),row['privacy'],input_['access']['retention']).validate()
        config.update(key=key,url=input_['locator'],interval=input_['poll']['seconds'],privacy=row['privacy'])
        with self.scheduler.db() as db:
            old=db.execute('SELECT document FROM rss_bindings WHERE key=?',(key,)).fetchone()
            prior=json.loads(old[0]) if old else None
            same=prior and all(prior[k]==config[k] for k in ('mode','url','interval')) and prior['definition_ref']['artifact_id']==config['definition_ref']['artifact_id']
            pending=db.execute("SELECT id FROM rss_polls WHERE binding=? AND state IN ('prepared','dispatching','fetched','publishing','unknown')",(key,)).fetchone()
            require(not config['enabled'] or not pending or same,'Resolve the previous RSS poll before changing its configuration')
            config.update(next_due=prior['next_due'] if same else self.clock(),validators=prior['validators'] if same else {},
                          last_success=prior['last_success'] if prior else None,last_error=None)
            db.execute('INSERT OR REPLACE INTO rss_bindings VALUES(?,?)',(key,encoded(config)))
            db.execute('INSERT OR REPLACE INTO watch_grants VALUES(?,?,?)',(config['project_id'],config['watch_id'],digest(encoded(row['value']))))
        return config

    @contextmanager
    def locked(self):
        path=self.scheduler.root/'rss-worker.lock'
        fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077,'Unsafe RSS worker lock')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:yield False;return
            yield True
        finally:os.close(fd)

    def _set(self,poll_id,state,**values):
        require(set(values)<={'result','plan','receipt'},'Invalid RSS poll update')
        with self.scheduler.db() as db:
            db.execute('UPDATE rss_polls SET state=?'+''.join(','+k+'=?' for k in values)+' WHERE id=?',
                       (state,*(encoded(v) for v in values.values()),poll_id))

    def _finish(self,poll_id,config,response,receipt=None,*,error=None,delay=None):
        with self.scheduler.db() as db:
            current=json.loads(db.execute('SELECT document FROM rss_bindings WHERE key=?',(config['key'],)).fetchone()[0])
            current['last_error']=error;current['next_due']=self.clock()+max(config['interval'],delay or 0)
            if error is None:
                current.update(validators=response['validators'],last_success=self.stamp())
            saved=db.execute('SELECT result,plan FROM rss_polls WHERE id=?',(poll_id,)).fetchone()
            result_summary=dict(status=response.get('status'),finished_at=self.stamp(),error=error)
            if saved[0]:
                result_summary.update(json.loads(saved[0]) or {});raw=result_summary.pop('raw',None)
                if raw is not None:result_summary['raw_sha256']=digest(base64.b64decode(raw,validate=True))
            plan_summary=dict(sha256=digest(saved[1])) if saved[1] else None
            db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(current),config['key']))
            db.execute('UPDATE rss_polls SET state=?,receipt=?,result=?,plan=? WHERE id=?',
                ('failed' if error else 'completed',encoded(receipt),encoded(result_summary),encoded(plan_summary),poll_id))

    def _plan(self,poll_id,config,response):
        ws,row,input_=self._definition(config);ws.recover();head=ws.git.head()
        files=ws.git.snapshot(head);entities=validate_snapshot(files);rs=records(files,entities)
        parents={p['artifact_id'] for r in rs.values() for p in r['previous']}
        tips={r['entity_id']:r for r in rs.values() if r['type']=='SourceFinding' and r['revision_id'] not in parents
              and r['value']['input_id']==config['input_id'] and r['value']['item']['source_locator']==config['url']}
        # Findings from another watch must not become this watch's processing queue.
        tips={key:r for key,r in tips.items() if rs[r['value']['definition_ref']['artifact_id']]['entity_id']==config['watch_id']}
        prior=dict(schema=OBSERVATION,url=config['url'],records=[dict(id=key,aliases=r['value']['aliases'],revisions=[
            dict(observed_at=r['value']['item']['discovered_at'],entry=dict(content_sha256=r['value']['entry_sha256']))]) for key,r in tips.items()])
        raw=base64.b64decode(response['raw'],validate=True);feed=parse_feed(raw,config['url'])
        observed=observe(feed,response['fetched_at'],prior);specs=[]
        for record in observed['records']:
            old=tips.get(record['id']);new_revisions=len(record['revisions'])-(1 if old else 0)
            require(new_revisions<=1,'Conflicting duplicate item identities in one feed')
            if not new_revisions:continue
            entry=record['revisions'][-1]['entry']
            ctx=SourceContext(config['input_id'],config['url'],record['revisions'][0]['observed_at'],config['privacy'],
                              input_['access']['retention'],channel=feed['title'])
            normalized=RSSConnector().normalize_entry(entry,ctx,feed['raw_sha256'])
            selected=config['mode']=='queue-all'
            policy=dict(mode=config['mode'],definition_rules=row['value']['selection'])
            value=dict(schema='fpw-reporting-finding-v1',definition_ref=config['definition_ref'],input_id=config['input_id'],
                item=normalized,aliases=record['aliases'],entry_sha256=entry['content_sha256'],stage='pending' if selected else 'captured',
                selection=dict(decision='selected' if selected else 'not-evaluated',reason='Explicit include-all policy' if selected else 'Captured without semantic filtering',
                    filter_revision='include-all-v1' if selected else 'capture-only-v1',filter_sha256=digest(encoded(policy))),
                change_reason='Corrected source item' if old else 'New source item',raw_ref=None)
            entity=old['entity_id'] if old else ident(config['watch_id'],config['input_id']+config['url']+record['id'])
            specs.append(dict(type='SourceFinding',value=value,entity_id=entity,privacy=config['privacy'],
                previous=[pinned(config['project_id'],head,old['revision_id'],files,entities)] if old else []))
        batch('rss-atom',[s['value']['item'] for s in specs])
        return dict(request=dict(project_id=config['project_id'],base_head=head,records=specs),
            operation_id=ident(poll_id,'publication'),capture=dict(raw=response['raw'],url=config['url'],
                definition_ref=config['definition_ref'],input_id=config['input_id'],mime=response.get('content_type')))

    def _publish(self,poll_id,config,response,plan,checkpoint):
        if plan is None:
            plan=self._plan(poll_id,config,response);self._set(poll_id,'publishing',plan=plan)
            checkpoint('rss-plan')
        receipt=None
        if plan['request']['records']:
            ws=self.reporting.artifacts.workspace(config['project_id']);ws.recover()
            receipt=self.reporting.apply(plan['request'],plan['operation_id'],_source_capture=plan['capture'],
                _capture_guard=lambda ws,files,entities:self._definition(config,ws,files,entities),checkpoint=checkpoint)
        checkpoint('rss-published')
        self._finish(poll_id,config,response,receipt)
        checkpoint('rss-completed')

    def tick(self,project_id=None,*,checkpoint=lambda stage:None):
        with self.locked() as acquired:
            if not acquired:return
            with self.scheduler.db() as db:
                # The process lock proves no live RSS dispatch owns these rows.
                db.execute("UPDATE rss_polls SET state='unknown' WHERE state='dispatching'")
                configs=[json.loads(r[0]) for r in db.execute('SELECT document FROM rss_bindings')]
            for config in configs:
                if (project_id and config['project_id']!=project_id) or not config['enabled']:continue
                with self.scheduler.db() as db:
                    poll=db.execute("SELECT id,state,document,result,plan FROM rss_polls WHERE binding=? AND state IN ('prepared','fetched','publishing','unknown') ORDER BY rowid LIMIT 1",(config['key'],)).fetchone()
                    if poll is None and config['next_due']<=self.clock():
                        poll_id=str(uuid4());intent=deepcopy(config)
                        db.execute('INSERT INTO rss_polls VALUES(?,?,?,?,NULL,NULL,NULL)',(poll_id,config['key'],'prepared',encoded(intent)))
                        poll=(poll_id,'prepared',encoded(intent),None,None)
                if poll is None or poll[1]=='unknown':continue
                poll_id,state,intent,result,plan=poll;config=json.loads(intent)
                if state=='prepared':
                    checkpoint('rss-prepared')
                    try:
                        self._definition(config)
                        until=self._origin_backoff(config['url'])
                        if until>self.clock():
                            error=RSSUnavailable('Origin backoff is active');error.retry_after=str(int(until-self.clock())+1);raise error
                        self._set(poll_id,'dispatching');checkpoint('rss-dispatching')
                        response=self.fetcher(config['url'],validators=config['validators'])
                        require(response['status'] in {200,304},'RSS fetch failed')
                        checked_validators(response['validators'])
                        if response['status']==304:
                            require(config['validators'],'Unexpected initial RSS 304')
                            self._finish(poll_id,config,response);continue
                        require(isinstance(response['raw'],bytes) and 0<len(response['raw'])<=512*1024,'RSS result exceeds limit')
                        response=dict(response,raw=base64.b64encode(response['raw']).decode(),fetched_at=self.stamp())
                        self._set(poll_id,'fetched',result=response);checkpoint('rss-fetched')
                    except (ValueError,OSError,RuntimeError) as exc:
                        if getattr(exc,'state',None)=='unknown' or isinstance(exc,TimeoutError):
                            self._set(poll_id,'unknown',result=dict(error=str(exc)))
                            with self.scheduler.db() as db:
                                current=json.loads(db.execute('SELECT document FROM rss_bindings WHERE key=?',(config['key'],)).fetchone()[0])
                                current['last_error']='Unknown RSS dispatch: '+str(exc)
                                db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(current),config['key']))
                        else:
                            delay=0;retry=getattr(exc,'retry_after',None)
                            if isinstance(exc,RSSUnavailable):delay=60
                            if retry:
                                try:delay=int(retry) if retry.isdigit() else parsedate_to_datetime(retry).timestamp()-self.clock()
                                except (ValueError,TypeError,OverflowError):delay=86400
                                delay=max(60,delay)
                            if isinstance(exc,RSSUnavailable):self._origin_backoff(config['url'],self.clock()+delay)
                            self._finish(poll_id,config,{},error=str(exc),delay=delay)
                        continue
                else:response=json.loads(result)
                try:self._publish(poll_id,config,response,json.loads(plan) if plan else None,checkpoint)
                except (ValueError,OSError,RuntimeError) as exc:
                    # Keep the immutable publication intent for recovery; never GET again.
                    with self.scheduler.db() as db:
                        state=db.execute('SELECT state FROM rss_polls WHERE id=?',(poll_id,)).fetchone()[0]
                        current=json.loads(db.execute('SELECT document FROM rss_bindings WHERE key=?',(config['key'],)).fetchone()[0])
                        current['last_error']='RSS publication pending: '+str(exc)
                        db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(current),config['key']))
                    if state=='fetched':self._finish(poll_id,config,{},error='RSS normalization failed: '+str(exc))

    def status(self,project_id):
        data=self.reporting.read(project_id)
        parents={p['artifact_id'] for r in data['records'] for p in r['previous']}
        findings=[r for r in data['records'] if r['type']=='SourceFinding' and r['revision_id'] not in parents]
        with self.scheduler.db() as db:
            bindings=[json.loads(r[0]) for r in db.execute('SELECT document FROM rss_bindings') if json.loads(r[0])['project_id']==project_id]
            keys={b['key'] for b in bindings}
            polls=[dict(id=r[0],state=r[1],binding=r[2],error=(json.loads(r[3]) or {}).get('error') if r[3] else None)
                   for r in db.execute('SELECT id,state,binding,result FROM rss_polls') if r[2] in keys]
        public_bindings=[{k:v for k,v in b.items() if k!='validators'} for b in bindings]
        return dict(project_id=project_id,commit_id=data['commit_id'],bindings=public_bindings,polls=polls,findings=findings)

    def reconcile(self,project_id,poll_id,*,confirm=False):
        require(confirm is True,'Explicit RSS reconciliation is required')
        ws=self.reporting.artifacts.workspace(project_id);ws._writable()
        with self.locked() as acquired:
            require(acquired,'RSS worker is busy')
            with self.scheduler.db() as db:
                row=db.execute('SELECT binding,state,document,plan,result FROM rss_polls WHERE id=?',(poll_id,)).fetchone()
            require(row and row[1] in {'unknown','publishing'} and json.loads(row[2])['project_id']==project_id,'RSS poll is unavailable for reconciliation')
            if row[1]=='publishing':
                plan=json.loads(row[3]);ws.recover();receipt=ws.receipt(plan['operation_id'])
                if receipt is not None:
                    self._finish(poll_id,json.loads(row[2]),json.loads(row[4]),receipt)
                    return dict(poll_id=poll_id,state='completed')
                with ws.journal.lock(),ws.journal.connect() as db:
                    require(db.execute('SELECT 1 FROM operations WHERE id=?',(plan['operation_id'],)).fetchone() is None,
                            'Existing Workspace publication requires recovery')
            with self.scheduler.db() as db:
                config=json.loads(db.execute('SELECT document FROM rss_bindings WHERE key=?',(row[0],)).fetchone()[0])
                config.update(next_due=self.clock()+config['interval'],last_error='Previous poll explicitly abandoned after reconciliation')
                db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(config),row[0]))
                db.execute("UPDATE rss_polls SET state='cancelled' WHERE id=?",(poll_id,))
            return dict(poll_id=poll_id,state='cancelled')

    def transition(self,project_id,finding_ref,stage,reason,operation_id,*,confirm=False):
        require(confirm is True and isinstance(reason,str) and reason.strip(),'Explicit finding transition reason is required')
        from spikes.source_collector import SourceCollector
        ws=self.reporting.artifacts.workspace(project_id);ws._writable();ws.recover();head=ws.git.head()
        receipt=ws.receipt(operation_id)
        if receipt is not None:
            revision=operation_uuid(operation_id,'record:0')
            saved=json.loads(ws.git.snapshot(receipt['commit_id'])[f'artifacts/{revision}/record.json'])
            require(saved['type']=='SourceFinding' and saved['previous']==[finding_ref] and
                    saved['value']['stage']==stage and saved['value']['change_reason']==reason and
                    saved['value']['selection']['filter_revision']=='manual-transition-v1',
                    'Operation belongs to another finding transition')
            return receipt
        files=ws.git.snapshot(head);entities=validate_snapshot(files)
        raw,_=SourceCollector.resolve(ws,project_id,finding_ref,files,entities);record=json.loads(raw)
        require(record['type']=='SourceFinding','Expected an RSS finding')
        allowed={'captured':{'selected','pending','discarded'},'selected':{'pending','discarded'},
            'pending':{'processed','discarded','failed','unknown'},'failed':{'pending','discarded'},'unknown':{'pending','discarded'}}
        value=deepcopy(record['value']);require(stage in allowed.get(value['stage'],set()),'Invalid finding state transition')
        value.update(stage=stage,change_reason=reason)
        decision='discarded' if stage=='discarded' else 'selected'
        value['selection']=dict(decision=decision,reason=reason,filter_revision='manual-transition-v1',filter_sha256=digest(encoded(dict(stage=stage,reason=reason))))
        if 'at' in value['raw_ref']:
            value['raw_ref']={k:v for k,v in value['raw_ref'].items() if k!='at'}|dict(project_id=project_id,commit_id=finding_ref['commit_id'])
        return self.reporting.apply(dict(project_id=project_id,base_head=head,records=[dict(type='SourceFinding',value=value,
            entity_id=record['entity_id'],previous=[finding_ref],privacy=record['privacy'])]),operation_id)
