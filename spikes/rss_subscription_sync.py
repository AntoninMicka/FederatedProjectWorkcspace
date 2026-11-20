# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit, signed node-to-node RSS preference exchange; no article fetches."""
import json
from pathlib import Path
import ssl
import sqlite3
import subprocess

from spikes.administration import Administration,AccessDenied
from spikes.background_workers import report_failure
from spikes.peer_transport import RSS_EXCHANGE_TIMEOUT,private_peer_endpoint
from spikes.federation_accounts import canonical
from spikes.federation_catalog import _authority
from spikes.http_deadline import DeadlineHTTPSConnection
from spikes.http_request_budget import RequestReadTimeout
from spikes.metadata import require,uuid,parse_json
from spikes.network_backend import private_root
from spikes.project_replication import _signature,_verify
from spikes.reporting_schema import digest
from spikes import rss_subscription_state as state

PATH='/v1/federation/rss-subscriptions'
CONTENT_TYPE='application/vnd.federated-workspace.rss-subscriptions-v1+json'
MAX_BODY=state.MAX_BYTES+128*1024
PURPOSE='rss-reader-subscriptions-v1'


def authority(service,peer_id):
    local,peer,shares,commit=_authority(service,peer_id)
    if peer['sharing_level'] not in {'same-team','same-company'} or not state.enabled(service.node,peer_id):
        raise AccessDenied('RSS preferences require explicit sharing on both nodes')
    return local,peer


def validate(p):
    require(isinstance(p,dict) and set(p)=={'purpose','source','recipient','inventory','known_remote','events','need_full'},'Invalid RSS exchange')
    require(p['purpose']==PURPOSE,'Unsupported RSS exchange');uuid(p['source']);uuid(p['recipient'])
    require(p['source']!=p['recipient'] and type(p['need_full']) is bool,'Invalid RSS exchange target')
    for k in ('inventory','known_remote'):
        require(isinstance(p[k],str) and (k=='known_remote' and p[k]=='' or len(p[k])==64 and all(c in '0123456789abcdef' for c in p[k])),'Invalid RSS inventory')
    if p['events'] is not None:
        state.checked(p['events']);require(digest(canonical(p['events']))==p['inventory'],'RSS inventory digest differs')
    return p


def prepare(service,peer_id,*,full=False):
    local,peer=authority(service,peer_id);events=state.export(service.node,peer_id)
    sent,remote=state.fingerprints(service.node,peer_id);inventory=digest(canonical(events))
    p=dict(purpose=PURPOSE,source=local,recipient=peer_id,inventory=inventory,
           known_remote=remote,events=events if full or inventory!=sent else None,need_full=False)
    return _signature(service.root,p,local,'rss'),peer


def verified(service,envelope):
    require(isinstance(envelope,dict) and isinstance(envelope.get('rss'),dict),'Missing RSS exchange')
    candidate=envelope['rss'];uuid(candidate.get('source'));uuid(candidate.get('recipient'))
    local,peer=authority(service,candidate['source'])
    require(candidate['recipient']==local and envelope.get('signer_node_id')==peer['id'],'Wrong RSS recipient')
    try:
        verified_payload=_verify(envelope,peer['fingerprint'],'rss')
    except subprocess.SubprocessError as exc:
        raise AccessDenied('RSS signature rejected') from exc
    p=validate(verified_payload['rss'])
    return p,peer


def receive(service,envelope,*,checkpoint=lambda stage:None):
    p,peer=verified(service,envelope)
    if p['events'] is not None:
        authority(service,peer['id'])
        state.apply(service.node,peer['id'],p['events'],checkpoint=checkpoint)
        state.progress(service.node,peer['id'],remote=p['inventory'])
    _,known_sender=state.fingerprints(service.node,peer['id'])
    events=state.export(service.node,peer['id']);inventory=digest(canonical(events))
    local,_=authority(service,peer['id'])
    reply=dict(purpose=PURPOSE,source=local,recipient=peer['id'],inventory=inventory,
        known_remote=p['inventory'],events=events if inventory!=p['known_remote'] else None,
        need_full=p['events'] is None and known_sender!=p['inventory'])
    return _signature(service.root,reply,local,'rss')


def exchange(node,peer,envelope,ca=None):
    parsed,address=private_peer_endpoint(peer['endpoint'],invalid='Invalid RSS peer endpoint',
                                         private='RSS peer requires a private IP address')
    context=ssl.create_default_context(cafile=str(ca or private_root(node)/(peer['id']+'-ca.pem')))
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    connection=DeadlineHTTPSConnection(str(address),parsed.port or 443,context=context,timeout=RSS_EXCHANGE_TIMEOUT)
    response=None
    try:
        raw=canonical(envelope);require(len(raw)<=MAX_BODY,'RSS exchange exceeds limit')
        connection.request('POST',PATH,body=raw,headers={'Content-Type':CONTENT_TYPE,'Host':parsed.netloc})
        response=connection.getresponse();raw=response.read(MAX_BODY+1);connection.check_deadline()
        require(len(raw)<=MAX_BODY,'RSS response exceeds limit')
        if response.status!=200:raise AccessDenied('Peer rejected RSS preference synchronization')
        return parse_json(raw,MAX_BODY)
    finally:
        if response is not None:response.close()
        connection.close()


def synchronize(node,peer_id,*,deployment='desktop',ca=None,full=False,transport=None):
    service=Administration(node,deployment=deployment)
    try:
        request,peer=prepare(service,peer_id,full=full)
        response=(transport(peer,request) if transport else exchange(node,peer,request,ca))
        p,current=verified(service,response)
        require(current['fingerprint']==peer['fingerprint'] and p['source']==peer_id,'RSS peer changed')
        require(p['known_remote']==request['rss']['inventory'],'RSS acknowledgement differs')
        if p['events'] is not None:state.apply(node,peer_id,p['events'])
        elif p['inventory']!=state.fingerprints(node,peer_id)[1]:
            raise ValueError('RSS peer omitted unknown inventory')
        state.progress(node,peer_id,sent='' if p['need_full'] else request['rss']['inventory'],
            remote=p['inventory'],state='pending' if p['need_full'] else 'conflict' if state.view(node)['conflicts'] else 'idle')
    except Exception as exc:
        try:state.progress(node,peer_id,state='error',detail=type(exc).__name__)
        except (ValueError,OSError,sqlite3.Error):pass
        raise
    return state.view(node)


def run_automatic(node,*,deployment):
    for p in state.view(node)['peers']:
        if p['enabled']:
            try:synchronize(node,p['id'],deployment=deployment)
            except Exception as exc:report_failure('rss-preference-sync',exc,target=p['id'])  # state recorded by synchronize()


def reply(handler):
    if (handler.single('Host')!=handler.local_authority or handler.headers.get_all('Origin',[])
        or handler.headers.get_all('Authorization',[]) or handler.headers.get_all('Transfer-Encoding')
        or handler.headers.get_all('Expect') or handler.single('Content-Type')!=CONTENT_TYPE):
        return handler.send_error(403)
    length=handler.single('Content-Length')
    if length is None or not length.isascii() or not length.isdecimal() or len(length)>len(str(MAX_BODY)) or not 2<=int(length)<=MAX_BODY:
        return handler.send_error(413)
    try:
        raw=handler.rfile.read(int(length));require(len(raw)==int(length),'Incomplete RSS exchange')
        result=receive(handler.server.administration,parse_json(raw,MAX_BODY))
        return handler.reply(200,result)
    except RequestReadTimeout:raise
    except AccessDenied:return handler.reply(403,{'error':'RSS preference sharing is not authorized'})
    except (ValueError,OSError,sqlite3.Error):return handler.reply(422,{'error':'RSS preference exchange rejected'})
