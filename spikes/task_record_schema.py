# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Git-backed task annotations; these records never carry task completion state."""
import json
import re
import base64
from spikes.metadata import require, uuid, timestamp, parse_json, UnsupportedVersion

SCHEMA = 'fpw-task-record-v1'
PRIVACY = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
INLINE = re.compile(r'(?m)^[ \t]*> <!-- fpw-task-record-data:([A-Za-z0-9+/=]+) -->\r?$')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names.split()), 'Invalid task record fields')


def validate(value):
    fields(value, 'schema id context events outputs revisions privacy')
    require(value['schema'] == SCHEMA, 'Unsupported task record')
    uuid(value['id']); context=value['context']
    fields(context, 'work_session_id definition_pin project_id task_id node_id user_id selected_checklist')
    for key in ('work_session_id','project_id','node_id','user_id'): uuid(context[key])
    require(isinstance(context['task_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*',context['task_id']), 'Invalid task ID')
    selected=context['selected_checklist'];require(selected is None or type(selected) is int and selected>=0,'Invalid original checklist context')
    pin=context['definition_pin'];fields(pin,'project_commit plan_revision source fragment_sha256')
    fields(pin['source'],'artifact_id path');uuid(pin['source']['artifact_id'])
    require(isinstance(pin['source']['path'],str) and pin['source']['path'].startswith('artifacts/'+pin['source']['artifact_id']+'/'),'Invalid definition source')
    require(isinstance(pin['fragment_sha256'],str) and re.fullmatch(r'[0-9a-f]{64}',pin['fragment_sha256']),'Invalid definition digest')
    require(isinstance(pin['project_commit'],str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',pin['project_commit']), 'Invalid definition commit')
    require(isinstance(value['privacy'],str) and value['privacy'] in PRIVACY,'Invalid record privacy')
    require(isinstance(value['events'],list) and 1<=len(value['events'])<=50,'Invalid event group')
    ids=[]
    for event in value['events']:
        fields(event,'event_id operation_id kind outcome author_id created_at request_references result_references selected_checklist')
        point=event['selected_checklist'];require(point is None or type(point) is int and point>=0,'Invalid event checklist context')
        for key in ('event_id','operation_id','author_id'):uuid(event[key])
        require(isinstance(event['outcome'],str) and event['outcome'] in {'succeeded','failed','unknown'},'Invalid activity outcome')
        require(isinstance(event['kind'],str) and isinstance(event['created_at'],(int,float)),'Invalid activity identity')
        require(isinstance(event['request_references'],list) and isinstance(event['result_references'],list),'Invalid activity references')
        ids.append(event['event_id'])
    require(len(ids)==len(set(ids)),'Duplicate event')
    require(isinstance(value['outputs'],list) and len(value['outputs'])<=100,'Invalid record outputs')
    for output in value['outputs']:
        fields(output,'project_id artifact_id commit_id path sha256 privacy title')
        require(isinstance(output['title'],str) and 0<len(output['title'])<=200,'Invalid output title')
        for key in ('project_id','artifact_id'):uuid(output[key])
        require(isinstance(output['commit_id'],str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',output['commit_id']),'Invalid output commit')
        require(isinstance(output['path'],str) and output['path'].startswith('artifacts/'+output['artifact_id']+'/') and '..' not in output['path'].split('/'),'Invalid output path')
        require(isinstance(output['sha256'],str) and re.fullmatch(r'[0-9a-f]{64}',output['sha256']),'Invalid output digest')
        require(isinstance(output['privacy'],str) and output['privacy'] in PRIVACY and PRIVACY[value['privacy']]>=PRIVACY[output['privacy']],'Record privacy is too low')
    require(isinstance(value['revisions'],list) and 1<=len(value['revisions'])<=200,'Invalid record history')
    for revision in value['revisions']:
        fields(revision,'comment selected_checklist author_id created_at')
        require(isinstance(revision['comment'],str) and len(revision['comment'])<=4000 and '\0' not in revision['comment'],'Invalid record comment')
        selected=revision['selected_checklist'];require(selected is None or type(selected) is int and selected>=0,'Invalid checklist context')
        uuid(revision['author_id']);timestamp(revision['created_at'])
    return value


def records(files, entities):
    result={};events=set()
    for identifier,meta in entities.items():
        if meta['kind']=='source':continue
        tagged=SCHEMA in meta.get('tags',[])
        if not tagged and meta.get('file')!='task-work.json':continue
        require(meta.get('file')=='task-work.json','Task record requires task-work.json')
        raw=files[f'artifacts/{identifier}/task-work.json'];value=parse_json(raw,maximum=1024*1024)
        schema=value.get('schema') if isinstance(value,dict) else None
        if schema != SCHEMA:
            raise UnsupportedVersion('task-record',None,(1,))
        validate(value)
        require(raw==encoded(value) and value['id']==identifier and meta['privacy']==value['privacy'],'Task record metadata differs')
        require(meta['author_id']==value['revisions'][0]['author_id'] and meta['created_at']==value['revisions'][0]['created_at'],'Task record author differs')
        for event in value['events']:
            require(event['event_id'] not in events,'Activity already belongs to another record')
            events.add(event['event_id'])
        result[identifier]=value
    # New records are self-contained in the owning task's text. Legacy JSON
    # artifacts remain readable, but no longer have to exist for new records.
    from spikes.plan_item_editor import item_span
    inline_ids=set()
    for identifier, meta in entities.items():
        if meta['kind'] != 'document' or not meta.get('file', '').endswith('.md'): continue
        path='artifacts/'+identifier+'/'+meta['file']
        raw=files[path]
        # Unrelated documents and imported source bytes need not be UTF-8.
        if b'fpw-task-record-data:' not in raw: continue
        body=raw.decode('utf-8')
        for match in INLINE.finditer(body):
            value=parse_json(base64.b64decode(match[1],validate=True),maximum=1024*1024)
            validate(value)
            require(value['id'] not in inline_ids,'Duplicate inline task record')
            inline_ids.add(value['id'])
            require(value['context']['definition_pin']['source']['artifact_id']==identifier,
                'Task record belongs to another document')
            start,end=item_span(body,value['context']['task_id'])
            require(start<=match.start()<match.end()<=end,'Task record belongs to another task')
            require(PRIVACY[meta['privacy']]>=PRIVACY[value['privacy']],'Task text privacy is too low')
            prior=result.get(value['id'])
            if prior:
                require({k:v for k,v in prior.items() if k!='revisions'}=={k:v for k,v in value.items() if k!='revisions'}
                    and value['revisions'][:len(prior['revisions'])]==prior['revisions'], 'Task record history differs')
                for event in prior['events']: events.remove(event['event_id'])
            for event in value['events']:
                require(event['event_id'] not in events,'Activity already belongs to another record')
                events.add(event['event_id'])
            result[value['id']]=value
    return result


def transition(before_files,after_files,before,after):
    old=records(before_files,before);new=records(after_files,after)
    for identifier,prior in old.items():
        current=new.get(identifier);require(current is not None,'Task record history cannot be removed')
        require({k:v for k,v in prior.items() if k!='revisions'}=={k:v for k,v in current.items() if k!='revisions'},'Task record provenance is immutable')
        require(current['revisions'][:len(prior['revisions'])]==prior['revisions'],'Task record corrections must preserve history')
