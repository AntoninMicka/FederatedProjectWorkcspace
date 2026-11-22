# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Concise, privacy-aware task-text projections of validated work records."""
import re

from spikes.markdown_documents import document
from spikes.metadata import require, validate_snapshot
from spikes.plan_item_editor import item_span
from spikes.task_graph import project_task_graph
from spikes.task_record_schema import PRIVACY, records


def text(value):
    value=' '.join(value.split())[:240]
    return re.sub(r'([\\`*_{}\[\]()<>!|])',r'\\\1',value)


def note(record, privacy):
    revision=record['revisions'][-1]
    summary=text(revision['comment']) if PRIVACY[record['privacy']]<=PRIVACY[privacy] else 'Připojen záznam práce'
    links=list(dict.fromkeys('['+text(o['title'])+']('+o['path']+')' for o in record['outputs']
        if o['project_id']==record['context']['project_id'] and PRIVACY[o['privacy']]<=PRIVACY[privacy]))
    return ('Záznam práce — '+record['revisions'][0]['created_at'][:10]+': '+(summary or 'Připojen záznam práce')+
        ('; výstupy: '+', '.join(links) if links else '')+'. <!-- fpw-task-record:'+record['id']+' -->')


def changes(files, pid, head, record):
    entities=validate_snapshot(files)
    graph=project_task_graph(files,entities,pid,head)
    task=next(t for t in graph['nodes'] if t['id']==record['context']['task_id'])
    doc=document(files,entities,task['source']['artifact_id'])
    start,end=item_span(doc['body'],task['id']);block=doc['body'][start:end]
    newline='\r\n' if '\r\n' in block else '\n'
    indent=re.match(r'[ \t]*',block)[0]+'  '
    marker='<!-- fpw-task-record:'+record['id']+' -->'
    lines=block.splitlines(keepends=True)
    replacement=indent+'- '+note(record,entities[doc['id']]['privacy'])+newline
    existing=next((i for i,line in enumerate(lines) if marker in line),None)
    if existing is None:
        if lines and not lines[-1].endswith(('\n','\r')):lines[-1]+=newline
        lines.append(replacement)
    else:
        prior=records(files,entities).get(record['id'])
        allowed={note(record,entities[doc['id']]['privacy'])}
        if prior:allowed.add(note(prior,entities[doc['id']]['privacy']))
        require(lines[existing].strip().removeprefix('- ') in allowed,
            'Řádek záznamu byl ručně změněn; zachovejte jeho text a vyřešte konflikt.')
        lines[existing]=replacement
    body=doc['body'][:start]+''.join(lines)+doc['body'][end:]
    raw=files[doc['path']];prefix=raw[:-len(doc['body'].encode())] if doc['body'] else raw
    return {doc['path']:prefix+body.encode()}


def definition_description(files, entities, task, pid):
    """Only exact projections of real records are administrative, never arbitrary markers."""
    privacy=entities[task['source']['artifact_id']]['privacy']
    known={note(record,privacy) for record in records(files,entities).values()
        if record['context']['task_id']==task['id'] and record['context']['project_id']==pid}
    return '\n'.join(line for line in task['description'].splitlines() if line.strip().removeprefix('- ') not in known)
