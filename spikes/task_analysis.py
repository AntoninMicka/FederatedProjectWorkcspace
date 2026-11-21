# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit, reviewable task input carried by the existing prompt and Context Manifest."""
import hashlib
import json

from spikes.metadata import require,validate_snapshot

SCHEMA='fpw-task-work-input-v1'
BEGIN='--- '+SCHEMA+' ---'
END='--- konec zadání úkolu ---'
PRIVACY={'public':0,'project':1,'confidential':2,'local-only':3}


def build(work,context):
    pid=context['project_id'];work._authorize(pid)
    current=work._model(pid,context['task_id'])
    git=work.projects.repository(pid);pin=context['definition_pin']
    files=git.snapshot(pin['project_commit']);entities=validate_snapshot(files)
    original=work._pin(files,pid,context['task_id'],pin['project_commit'])
    require(original['pin']==pin,'Připnuté zadání neodpovídá původní relaci.')
    require(original['signature']==current['signature'],'Zadání úkolu se změnilo; nejprve obnovte pracovní kontext.')
    selected=context['selected_checklist'];task=original['task']
    require(selected is None or type(selected) is int and 0<=selected<len(task['checklist']),'Vybraný bod není v původním zadání.')
    privacy=max(entities[pin['source']['artifact_id']]['privacy'],
        validate_snapshot(git.snapshot(current['pin']['project_commit']))[current['pin']['source']['artifact_id']]['privacy'],key=PRIVACY.get)
    data=dict(schema=SCHEMA,project_id=pid,task_id=context['task_id'],work_session_id=context['work_session_id'],
        definition_pin=pin,selected_checklist=selected,title=task['title'],description=task['description'],
        checklist=task['checklist'])
    text=BEGIN+'\n'+json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n'+END
    require(len(text)<=12000,'Zadání je příliš dlouhé pro návrh zprávy; vyberte menší podklad.')
    return dict(schema=SCHEMA,text=text,sha256=hashlib.sha256(text.encode()).hexdigest(),privacy=privacy,
        project_id=pid,task_id=context['task_id'],work_session_id=context['work_session_id'])


def validate_input(activities,event_id,request,declared):
    with activities.work._db() as db:
        row=db.execute('SELECT doc FROM operations WHERE id=? AND user_id=?',(event_id,activities.work.user_id)).fetchone()
        require(row is not None,'Činnost není dostupná.')
        event=json.loads(row['doc'])
    context=build(activities.work,event['context'])
    require(isinstance(request.get('content'),str) and context['sha256']==declared and context['text'] in request['content'],
        'Zadání úkolu nebo vybraný checklist se změnily; znovu připravte analýzu.')
    require(request.get('project_id')==context['project_id'],'Analýza patří do projektu původního úkolu.')
    require(isinstance(request.get('privacy'),str) and request['privacy'] in PRIVACY and PRIVACY[request['privacy']]>=PRIVACY[context['privacy']],
        'Zpráva nesmí snížit soukromí předaného zadání úkolu.')
    with activities.work._db(write=True) as db:
        current=json.loads(db.execute('SELECT doc FROM operations WHERE id=? AND user_id=?',(event_id,activities.work.user_id)).fetchone()['doc'])
        prior=current.get('task_input')
        proof=dict(schema=SCHEMA,sha256=declared,privacy=context['privacy'])
        require(prior is None or prior==proof,'Předaný kontext původního běhu se změnil.')
        current['task_input']=proof
        activities.work._save_operation(db,event_id,current)
