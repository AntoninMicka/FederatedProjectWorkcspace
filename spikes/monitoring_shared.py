# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Logical activation and report outcomes in the existing signed pool exchange.

These records are shared decisions/results, never worker leases or journals.
"""
from copy import deepcopy
import json
import math
import re
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.metadata import require, uuid
from spikes.reporting_schema import encoded, fields, hex_id, moment, ref, PRIVACY, digest

KINDS = {'activation', 'report-outcome'}


def heads(rows, kind, identity):
    selected = [r for r in rows if r['kind'] == kind and r['value']['block_id' if kind == 'activation' else 'run_id'] == identity]
    parents = {p for r in selected for p in r['value']['previous']}
    return sorted((r for r in selected if r['id'] not in parents), key=lambda r:r['id'])


def validate(row):
    v = row['value']; kind = row['kind']
    if kind == 'activation':
        fields(v,'block_id block_ref enabled previous node_id event_id privacy')
        require(type(v['enabled']) is bool,'Invalid shared activation')
        uuid(v['event_id'])
    else:
        fields(v,'block_id block_ref run_id node_id previous privacy state intent result expires_at')
        uuid(v['run_id']);moment(v['expires_at'])
        require(v['state'] in {'review','published','failed','unknown'},'Invalid report outcome state')
        intent=v['intent']; result=v['result']
        require(isinstance(intent,dict) and set(intent) <= {'project_id','block','input_head','pools','searches','kind',
            'period_end','started_at','expires_at','reprocess_of','executor_node_id','unavailable_input_refs','report_inputs'},'Outcome contains operational state')
        require({'project_id','block','pools','kind','started_at','expires_at','executor_node_id'} <= set(intent),'Incomplete outcome intent')
        require(intent['project_id']==row['project_id'] and intent['kind']=='processing' and intent['block']['id']==v['block_id']
                and intent['executor_node_id']==v['node_id'] and intent['block']['ref']==v['block_ref'],'Outcome provenance differs')
        fields(intent['block'],'id privacy value ref')
        require(intent.get('searches',{})=={},'Outcome contains raw search results')
        from spikes.monitoring_report_inputs import validate_links
        validate_links(intent.get('report_inputs',[]),row['project_id'])
        for key in ('started_at','expires_at','period_end'):
            if key in intent:require(type(intent[key]) in {int,float} and math.isfinite(intent[key]),'Invalid outcome time')
        require(abs(moment(v['expires_at']).timestamp()-intent['expires_at'])<0.00001,'Outcome retention differs from frozen inputs')
        from spikes.monitoring_blocks import validate_block
        validate_block(intent['block']['value'])
        require(intent['block']['value']['kind']=='processing','Outcome requires processing')
        require(isinstance(intent['pools'],dict) and isinstance(result,dict),'Invalid outcome input references')
        for groups in intent['pools'].values():
            require(isinstance(groups,list),'Invalid outcome pools')
            for group in groups:
                fields(group,'key revisions')
                for revision in group['revisions']:
                    fields(revision,'revision item_entry');hex_id(revision['revision']);hex_id(revision['item_entry'])
        require(v['state'] in {'review','published'} or isinstance(result.get('error'),str),'Failed outcome needs a problem description')
        require(set(result) <= {'output','markdown','approval_digest','input_digest','protection','report_ref','replacement','error'},
                'Outcome result contains operational state')
        if v['state'] in {'review','published'}:
            require({link['task_id'] for link in intent.get('report_inputs',[])}==set(intent['block']['value']['config'].get('report_task_ids',[])),'Shared report input task coverage differs')
            require(isinstance(result.get('markdown'),str) and 0<len(result['markdown'].encode())<=1024*1024,'Invalid report outcome text')
            hex_id(result['approval_digest']);hex_id(result['input_digest'])
            refs=sorted((pool,r['item_entry']) for pool,groups in intent['pools'].items() for g in groups for r in g['revisions'])
            from spikes.monitoring_report_inputs import approval
            valid={approval(result['markdown'],refs,intent.get('report_inputs',[]))}
            if not intent.get('report_inputs'):valid.add(digest(result['markdown'].encode()))
            require(result['approval_digest'] in valid,'Shared report approval digest differs')
        if result.get('output') is not None:
            fields(result['output'],'title built_at');moment(result['output']['built_at'])
            require(isinstance(result['output']['title'],str) and 0<len(result['output']['title'])<=200,'Invalid outcome title')
        if result.get('protection') is not None:
            guard=result['protection']
            require(isinstance(guard,dict) and {'until','finalized','changed'}<=set(guard)<= {'until','finalized','changed','error','regenerated_run_id'},'Invalid shared protection')
            require(type(guard['until']) in {int,float} and math.isfinite(guard['until']) and type(guard['finalized']) is bool and type(guard['changed']) is bool,'Invalid shared protection state')
            if guard.get('error') is not None:require(isinstance(guard['error'],str) and len(guard['error'])<=1000,'Invalid shared protection error')
        if v['state']=='published':
            ref(result['report_ref'])
            from spikes.monitoring import ident
            require(result['report_ref']['project_id']==row['project_id'] and result['report_ref']['artifact_id']==ident(v['run_id'],'report'),'Published outcome identity differs')
        if result.get('error') is not None:
            require(isinstance(result['error'],str) and 0<len(result['error'])<=1000,'Invalid report error')
        require(PRIVACY[v['privacy']] >= PRIVACY[intent['block']['privacy']],'Outcome lowers block privacy')
    uuid(v['block_id']);uuid(v['node_id']);ref(v['block_ref'])
    require(v['block_ref']['project_id']==row['project_id'],'Shared definition project differs')
    require(v['privacy'] in PRIVACY,'Invalid shared privacy')
    require(isinstance(v['previous'],list) and len(v['previous'])<=128 and v['previous']==sorted(set(v['previous'])),'Invalid causal predecessors')
    for previous in v['previous']:hex_id(previous)


def validate_links(rows):
    # Activation ancestry is retained, so a partial/misbound causal update is rejected.
    for r in rows.values():
        if r['kind'] not in KINDS:continue
        for id_ in r['value']['previous']:
            parent=rows.get(id_)
            require(parent is not None or r['kind']=='report-outcome','Incomplete activation history')
            if parent:
                require(parent['kind']==r['kind'] and parent['value']['block_id']==r['value']['block_id'], 'Shared predecessor belongs to another block')
                if r['kind']=='report-outcome':
                    require(parent['value']['run_id']==r['value']['run_id'] and parent['value']['node_id']==r['value']['node_id'],'Outcome predecessor belongs to another execution')
                require(PRIVACY[r['value']['privacy']]>=PRIVACY[parent['value']['privacy']],'Shared revision lowers privacy')


def read_rows(db,pid):
    return [json.loads(r[0]) for r in db.execute("SELECT document FROM pool_entries WHERE project=? AND kind IN ('activation','report-outcome')",(pid,))]


def activation(rows,block_id):
    tips=heads(rows,'activation',block_id)
    if not tips:return None
    states={r['value']['enabled'] for r in tips}
    return dict(enabled=states=={True},activation_conflict=len(states)>1,activation_heads=[r['id'] for r in tips])


def store(db,pid,kind,value):
    from spikes.message_pools import entry,validate_entry
    row=entry(pid,kind,value);validate_entry(row,pid)
    db.execute('INSERT OR IGNORE INTO pool_entries VALUES(?,?,?,?)',(row['id'],pid,kind,encoded(row)))
    return row


def set_activation(db,pid,block,enabled,node_id):
    rows=read_rows(db,pid);tips=heads(rows,'activation',block['id'])
    row=store(db,pid,'activation',dict(block_id=block['id'],block_ref=block['ref'],enabled=enabled,
        previous=[r['id'] for r in tips],node_id=node_id,event_id=str(uuid4()),
        privacy=max([block['privacy']]+[r['value']['privacy'] for r in tips],key=lambda p:PRIVACY[p])))
    return activation(rows+[row],block['id'])


def binding(block, prior, state, now, consent):
    value=deepcopy(prior) if prior else dict(next_due=now,validators={},last_success=None,error=None)
    if prior and (prior.get('revision')!=block['ref']['artifact_id'] or prior.get('consent')!=consent):
        value['validators']={}
    value.update(state,revision=block['ref']['artifact_id'],consent=consent)
    if state['activation_conflict']:value['error']='Konflikt aktivace: vyberte znovu zapnutí nebo pozastavení.'
    elif (value.get('error') or '').startswith('Konflikt aktivace:'):value['error']=None
    return value


def safe_error(message):
    def url(match):
        try:
            p=urlsplit(match[0]);return p.scheme+'://'+(p.hostname or '')+p.path
        except ValueError:return '[adresa]'
    message=re.sub(r'https?://[^\s]+',url,str(message))
    message=re.sub(r'(?i)bearer\s+[^\s,;]+','Bearer [redacted]',message)
    pattern = r"""(?i)(["']?(?:api[_-]?key|(?:access[_-]?|api[_-]?)?token|password|authorization|client[_-]?secret)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)"""
    message=re.sub(pattern,r'\1[redacted]',message)
    return message[:1000] or 'Zprávu se nepodařilo zpracovat.'


def reference_intent(intent):
    value={k:deepcopy(intent[k]) for k in ('project_id','block','input_head','kind','period_end','started_at',
        'expires_at','reprocess_of','executor_node_id','unavailable_input_refs','report_inputs') if k in intent}
    value['block']={k:value['block'][k] for k in ('id','privacy','value','ref')}
    value['pools']={pool:[dict(key=g['key'],revisions=[dict(revision=r['revision'],item_entry=r['item_entry']) for r in g['revisions']])
        for g in groups] for pool,groups in intent.get('pools',{}).items()}
    value['searches']={}  # raw connector results and model manifests remain local
    return value


def share_outcome(db,pid,run_id,intent,result,state,node_id,*,_rows=None):
    if intent.get('kind')!='processing' or result is None:return
    from spikes.message_pools import stamp
    clean={k:deepcopy(result[k]) for k in ('output','markdown','approval_digest','input_digest','protection','report_ref','replacement','error') if k in result}
    if clean.get('error'):clean['error']=safe_error(clean['error'])
    if clean.get('protection',{}).get('error'):clean['protection']['error']=safe_error(clean['protection']['error'])
    frozen=reference_intent(intent);frozen.setdefault('executor_node_id',node_id)
    node_id=frozen['executor_node_id'];block=frozen['block']
    rows=read_rows(db,pid) if _rows is None else _rows
    tips=[r for r in heads(rows,'report-outcome',run_id) if r['value']['node_id']==node_id]
    if state!='published' and any(r['value']['state']=='published' for r in tips):return
    value=dict(block_id=block['id'],block_ref=block['ref'],run_id=run_id,node_id=node_id,previous=[r['id'] for r in tips],
        privacy=block['privacy'],state=state,intent=frozen,result=clean,expires_at=stamp(frozen['expires_at']))
    if len(tips)==1 and all(tips[0]['value'][k]==v for k,v in value.items() if k!='previous'):return
    row=store(db,pid,'report-outcome',value)
    if _rows is not None:_rows.append(row)


def job_time(job):
    intent=job['intent'];value=intent.get('started_at')
    if type(value) in {int,float}:return value
    received=intent.get('received_at')
    return moment(received).timestamp() if received else 0


def outcome_jobs(rows):
    jobs=[];by_run={}
    for row in rows:
        if row['kind']=='report-outcome':by_run.setdefault(row['value']['run_id'],[]).append(row)
    for run_id,events in sorted(by_run.items()):
        tips=heads(events,'report-outcome',run_id)
        if len(tips)!=1:
            # Keep contradictory results visible rather than choosing an executor.
            v=tips[0]['value'];jobs.append(dict(id=run_id,state='unknown',intent=v['intent'],
                result=dict(error='Více neslučitelných výsledků stejného běhu; původní historie je zachovaná.'),shared=True))
        else:
            v=tips[0]['value'];jobs.append(dict(id=run_id,state=v['state'],intent=deepcopy(v['intent']),result=deepcopy(v['result']),shared=True))
    return jobs
