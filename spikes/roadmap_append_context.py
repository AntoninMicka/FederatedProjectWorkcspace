# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit append-only projection of one selected roadmap; no generated task content."""
import hashlib
import json
import re
import unicodedata

from spikes.markdown_documents import document
from spikes.metadata import require
from spikes.task_graph import project_task_graph

SCHEMA = 'fpw-roadmap-append-context-v1'


def requests_new_tasks(text):
    plain=''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))
    return bool(re.match(r'^\s*(?:vytvor|dopln|pridej|create|add)\s+(?:(?:nove|novy|nova|new)\s+)?(?:ukol\w*|tasks?)\b',plain))


def build(files, entities, project_id, head, target, run_id):
    graph=project_task_graph(files,entities,project_id,head)
    if graph['status']!='ready' or graph.get('profile')!='software-development/v1':return None
    nodes=[n for n in graph['nodes'] if n.get('source',{}).get('artifact_id')==target]
    roots=[n for n in nodes if n['type']=='milestone']
    parent=next((n for n in roots if n['id']=='MILESTONE-DEV'),None)
    if parent is None and len(roots)==1:parent=roots[0]
    if parent is None:return None
    doc=document(files,entities,target);lines=doc['body'].splitlines(keepends=True)
    index=next((i for i,l in enumerate(lines) if re.match(r'^- \[[ xX]\] \['+re.escape(parent['id'])+r'\]',l)),None)
    if index is None:return None
    end=index+1
    while end<len(lines) and re.match(r'^  - type: milestone\s*$',lines[end]):end+=1
    anchor=''.join(lines[index:end])
    if not anchor or len(anchor)>1024 or doc['body'].count(anchor)!=1:return None
    prefix='NEW-'+run_id.replace('-','').upper()
    require(not any(n['id'].startswith(prefix) for n in graph['nodes']),'Append ID namespace already used')
    nearby=[dict(id=n['id'],title=n['title']) for n in nodes if n.get('parent_id')==parent['id'] and n['type']=='batch'][:12]
    scope=dict(schema=SCHEMA,mode='append-only',target_artifact_id=target,parent_id=parent['id'],id_prefix=prefix,
               insertion_anchor=anchor,profile=graph['profile'],nearby_batches=nearby,
               omitted='Other document bodies and historical descriptions are not provided. Existing tasks must remain unchanged.')
    payload=json.dumps(scope,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    metadata=dict(schema=SCHEMA,parent_id=parent['id'],id_prefix=prefix,
        anchor_sha256=hashlib.sha256(anchor.encode()).hexdigest(),source_sha256=hashlib.sha256(files[doc['path']]).hexdigest(),
        source_bytes=len(files[doc['path']]),projection_sha256=hashlib.sha256(payload).hexdigest(),projection_bytes=len(payload))
    return dict(payload=payload,metadata=metadata,anchor=anchor,graph=graph)


def instruction():
    return ('The selected roadmap is supplied as an explicit append-only projection, not its complete body. '
            'Use insertion_anchor from that source EXACTLY as the single before value. '
            'The single after value must start with the identical insertion_anchor and then append one new '
            'unchecked batch and exactly the tasks requested by the User edit request. '
            'Use the supplied id_prefix for ALL new IDs, for example id_prefix-BATCH and id_prefix-T1. '
            'The batch belongs under parent_id and uses two-space indentation; its task children use four-space '
            'indentation. Put type: batch four spaces below the milestone, and type: task six spaces below it. '
            'Do not copy nearby batch titles or historical descriptions. Do not change existing tasks. '
            'The complete original document will be validated after application; only new task content is requested.')


def validate(projection, edits, after_graph):
    require(len(edits)==1 and edits[0]['before']==projection['anchor'] and
            edits[0]['after'].startswith(projection['anchor']), 'Append patch must preserve its exact insertion anchor')
    old={n['id']:n for n in projection['graph']['nodes']};new={n['id']:n for n in after_graph['nodes']}
    require(old.keys()<=new.keys(),'Append patch removed existing tasks')
    for id_,node in old.items():
        require(all(node.get(k)==new[id_].get(k) for k in ['title','type','checked','parent_id','depends_on','description']),
                'Append patch changed an existing task')
    added=[n for id_,n in new.items() if id_ not in old]
    batches=[n for n in added if n['type']=='batch'];tasks=[n for n in added if n['type']=='task']
    scope=projection['metadata']
    require(len(batches)==1 and tasks and len(added)==len(tasks)+1 and
            batches[0].get('parent_id')==scope['parent_id'] and
            all(n.get('parent_id')==batches[0]['id'] for n in tasks) and
            all(not n['checked'] and n['id'].startswith(scope['id_prefix']) for n in added),
            'Append patch must add one new batch with its new unchecked tasks only')
