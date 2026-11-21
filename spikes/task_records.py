# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed task annotations over existing local intents and Workspace transactions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid5

from spikes.artifact_preview import preview
from spikes.metadata import require, uuid, validate_snapshot
from spikes.task_activities import TaskActivities
from spikes.task_work import canonical, digest
from spikes.task_record_schema import SCHEMA, PRIVACY, encoded, records, validate, fields


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def offer(event):
    names={'artifact-save':'Uložení dokumentu','artifact-delete':'Odstranění dokumentu','source-import':'Import podkladu','conversation-turn':'Konverzace','llm-task':'Zpracování úlohy modelem','llm-run':'Modelový běh','search-run':'Vyhledávání','file-stage':'Uložení rozpracované změny','file-commit':'Commit souboru','artifact-publish':'Uložení výsledku'}
    description=names.get(event['kind'],'Práce ve Workspace')
    if event['outcome']!='succeeded':description+=' — neúspěšné' if event['outcome']=='failed' else ' — výsledek není potvrzen'
    return event.get('offer',dict(state='pending',revision=0,comment=description,
        selected_checklist=event['context']['selected_checklist']))


class TaskRecords:
    def __init__(self,work):
        self.work=work;self.activities=TaskActivities(work)

    def snapshot(self,pid,*,write=True):
        if write:self.work._authorize(pid)
        else:require(self.work.can_read(pid),'Právo číst výsledek bylo odebráno.')
        view=self.work.projects.plan_view(pid);require(not write or not view.get('read_only'),'Projekt je pouze pro čtení.')
        git=self.work.projects.repository(pid);files=git.snapshot(view['commit_id']);entities=validate_snapshot(files)
        require(git.head()==view['commit_id'],'Projekt se změnil; obnovte kontext.')
        if self.work.network:require(all(m['privacy']!='local-only' for m in entities.values()),'Project contains local-only data')
        return git,view['commit_id'],files,entities

    def for_session(self,handle,session_id):
        with self.work._db() as db:
            self.work._window(db,handle);session=self.work._session(db,session_id,handle['window_id'])
            rows=db.execute('SELECT id,doc FROM operations WHERE user_id=? AND window_id=?',
                (self.work.user_id,handle['window_id'])).fetchall()
        _,head,files,entities=self.snapshot(session['project_id'])
        values=[dict(value,record_revision=len(value['revisions']),validated_head=head)
            for value in records(files,entities).values() if value['context']['project_id']==session['project_id']
            and value['context']['task_id']==session['task_id'] and self.readable(value)]
        pending=[]
        for row in rows:
            op=json.loads(row['doc'])
            if op.get('record_type')=='task-record-publish' and op['state']=='prepared' and op['record']['context']['work_session_id']==session_id:
                pending.append(dict(operation_id=row['id'],state='prepared'))
        return sorted(values,key=lambda r:(r['revisions'][0]['created_at'],r['id'])),pending

    def readable(self,record):
        return (not self.work.network or record['privacy']!='local-only') and all(
            self.activities._readable(o['project_id']) for o in record['outputs'])

    def events(self,request):
        events={e['event_id']:e for e in self.activities.for_session(request,request['work_session_id'])}
        ids=request['event_ids'];revisions=request['offer_revisions']
        require(isinstance(ids,list) and 1<=len(ids)<=50 and all(isinstance(i,str) for i in ids) and len(set(ids))==len(ids),'Vyberte činnosti k připojení.')
        require(isinstance(revisions,list) and len(revisions)==len(ids),'Invalid offer revisions')
        result=[]
        for identifier,revision in zip(ids,revisions):
            uuid(identifier);require(identifier in events,'Činnost již není dostupná.')
            event=events[identifier];state=offer(event)
            require(type(revision) is int and state['revision']==revision,'Nabídka se změnila; obnovte kontext.')
            require(state['state']!='confirmed' and not state.get('pending_operation_id'),'Činnost již byla připojena nebo čeká na obnovu.')
            result.append(event)
        require(all({k:v for k,v in e['context'].items() if k!='selected_checklist'}=={k:v for k,v in result[0]['context'].items() if k!='selected_checklist'} for e in result),'Seskupte činnosti se stejným původním kontextem.')
        self.comment(request,result[0]['context'])
        return result

    def comment(self,request,context):
        require(isinstance(request['comment'],str) and len(request['comment'])<=4000 and '\0' not in request['comment'],'Invalid comment')
        model=self.work._model(context['project_id'],context['task_id'])
        git=self.work.projects.repository(context['project_id']);pin=context['definition_pin']
        original=self.work._pin(git.snapshot(pin['project_commit']),context['project_id'],context['task_id'],pin['project_commit'])
        selected=request['selected_checklist']
        require(selected is None or type(selected) is int and 0<=selected<len(original['task']['checklist']),'Invalid original checklist selection')
        return model

    def outputs(self,events):
        result=[]
        for event in events:
            if event['outcome']!='succeeded':continue
            refs=event['result_references']
            projects=list(dict.fromkeys(r['project_id'] for r in refs if 'project_id' in r))
            pid=event['target_project_id'] or (projects[0] if len(projects)==1 else event['context']['project_id'])
            require(self.activities._readable(pid),'Výsledek již není dostupný.')
            git,head,_,_=self.snapshot(pid,write=False)
            # The native journal/diff identifies outputs. Request input refs are
            # provenance, never a substitute for a written result identity.
            ws=self.work.projects.workspace(pid,for_snapshot=True)
            receipt=ws.receipt(event['operation_id'])
            commits=list(dict.fromkeys(r['commit_id'] for r in refs if 'commit_id' in r))
            commits+=list(dict.fromkeys(r['project_commit'] for r in refs if 'artifact_id' in r and 'project_commit' in r))
            if receipt and receipt.get('commit_id') and receipt['commit_id'] not in commits:commits.append(receipt['commit_id'])
            for commit in dict.fromkeys(commits):
                require(git.run('merge-base','--is-ancestor',commit,head,check=False).returncode==0,'Výsledek není v historii projektu.')
                before=(receipt.get('base_head') if receipt and receipt.get('commit_id')==commit else None)
                if not before:before=git.run('rev-parse',commit+'^').stdout.strip()
                changed=git.run('diff','--name-only',before,commit,'--','artifacts/').stdout.splitlines()
                aids=list(dict.fromkeys(path.split('/')[1] for path in changed if len(path.split('/'))==3))
                files=git.snapshot(commit);entities=validate_snapshot(files)
                previous_files=None
                for aid in aids:
                    output_commit=commit;output_files=files;meta=entities.get(aid)
                    if meta is None:
                        if previous_files is None:previous_files=git.snapshot(before)
                        meta=validate_snapshot(previous_files).get(aid);output_files=previous_files;output_commit=before
                    if meta is None:continue
                    prefix='artifacts/'+aid+'/'
                    path=prefix+meta['file'] if 'file' in meta else next(p for p in output_files if p.startswith(prefix))
                    output=dict(project_id=pid,artifact_id=aid,commit_id=output_commit,path=path,
                        sha256=hashlib.sha256(output_files[path]).hexdigest(),privacy=meta['privacy'],title=meta['title'])
                    if output not in result:result.append(output)
        require(len(result)<=100,'Příliš mnoho výsledků v jednom záznamu.')
        return result

    def _save_offers(self,db,events,request,state,**extra):
        for event in events:
            row=self.work._operation(db,event['event_id'],request['window_id']);current=json.loads(row['doc'])
            require(offer(current)['revision']==offer(event)['revision'],'Nabídka se mezitím změnila.')
            current['offer']=dict(state=state,revision=offer(event)['revision']+1,comment=request['comment'],
                selected_checklist=request['selected_checklist'],event_ids=request['event_ids'],**extra)
            self.work._save_operation(db,event['event_id'],current)

    def execute(self,request,*,checkpoint=lambda stage:None):
        require(isinstance(request,dict),'Invalid record request')
        common='action window_id window_token';action=request.get('action')
        extra={
            'record-offer':'operation_id work_session_id event_ids offer_revisions comment selected_checklist state',
            'record-publish':'operation_id work_session_id event_ids offer_revisions comment selected_checklist expected_head privacy',
            'record-amend':'operation_id work_session_id record_id record_revision comment selected_checklist expected_head',
            'record-recover':'operation_id','record-cancel':'operation_id',
            'record-output':'project_id record_id output_index version page'}
        require(isinstance(action,str) and action in extra,'Invalid task record action');fields(request,common+' '+extra[action])
        with self.work._db() as db:self.work._window(db,request)
        if action=='record-output':return self.output(request)
        uuid(request['operation_id'])
        body={k:v for k,v in request.items() if k!='window_token'}
        with self.work._operation_lock(request['operation_id']):
            with self.work._db() as db:row=self.work._operation(db,request['operation_id'],request['window_id'])
            if row:
                op=json.loads(row['doc']);require(op.get('record_type') in {'task-record-publish','task-record-offer'},'Operation belongs to another action')
                if action not in {'record-recover','record-cancel'}:require(row['request']==canonical(body),'Operation request differs')
            else:
                require(action not in {'record-recover','record-cancel'},'Unknown record operation')
                op=self.prepare(request,body,checkpoint)
            if action=='record-cancel':self.cancel(request,op)
            elif op['record_type']=='task-record-publish' and op['state']=='prepared':self.run(request,op,checkpoint)
        result=self.work.status(request)
        with self.work._db() as db:op=json.loads(self.work._operation(db,request['operation_id'],request['window_id'])['doc'])
        result['operation']=dict(operation_id=request['operation_id'],state=op['state'],result=op.get('result'))
        return result

    def prepare(self,request,body,checkpoint):
        with self.work._db() as db:session=self.work._session(db,request['work_session_id'],request['window_id'])
        if request['action']!='record-amend':self.comment(request, {k:session[k] for k in ('project_id','task_id','definition_pin')})
        pid=session['project_id'];git,head,files,entities=self.snapshot(pid)
        events=[]
        if request['action']=='record-amend':
            uuid(request['record_id'])
            record=deepcopy(records(files,entities).get(request['record_id']))
            require(record and record['context']['project_id']==pid and record['context']['task_id']==session['task_id'] and self.readable(record),'Záznam není dostupný.')
            require(type(request['record_revision']) is int and len(record['revisions'])==request['record_revision'],'Záznam se změnil.')
            self.comment(request,record['context'])
            record['revisions'].append(dict(comment=request['comment'],selected_checklist=request['selected_checklist'],author_id=self.work.user_id,created_at=now()))
            meta=dict(entities[record['id']])
        else:
            events=self.events(request)
            if request['action']=='record-offer':
                require(isinstance(request['state'],str) and request['state'] in {'draft','deferred','dismissed'},'Invalid offer state')
                op=dict(record_type='task-record-offer',state='completed')
            else:
                outputs=self.outputs(events);privacy=request['privacy']
                require(isinstance(privacy,str) and privacy in PRIVACY,'Invalid annotation privacy')
                minimum=max([PRIVACY[m['privacy']] for m in entities.values()]+[PRIVACY[o['privacy']] for o in outputs]+[PRIVACY[e.get('privacy','local-only')] for e in events])
                require(PRIVACY[privacy]>=minimum and (not self.work.network or privacy!='local-only'),'Záznam vyžaduje vyšší privacy.')
                identifier=str(uuid5(UUID(request['operation_id']),'task-record'))
                record=dict(schema=SCHEMA,id=identifier,context=deepcopy(events[0]['context']),
                    events=[dict({k:e[k] for k in ('event_id','operation_id','kind','outcome','author_id','created_at','request_references','result_references')},selected_checklist=e['context']['selected_checklist']) for e in events],
                    outputs=outputs,privacy=privacy,revisions=[dict(comment=request['comment'],selected_checklist=request['selected_checklist'],author_id=self.work.user_id,created_at=now())])
                meta=dict(schema_version=1,id=identifier,title='Záznam práce · '+session['task_id'],kind='document',file='task-work.json',
                    tags=[SCHEMA],privacy=privacy,provenance='user',author_id=self.work.user_id,created_at=record['revisions'][0]['created_at'])
        if request['action']!='record-offer':
            require(head==request['expected_head'],'Projekt se změnil; obnovte kontext a zachovejte komentář.')
            validate(record)
            op=dict(record_type='task-record-publish',state='prepared',record=record,metadata=meta,base_head=head,
                native_operation_id=str(uuid5(UUID(request['operation_id']),'task-record-project')),events=[e['event_id'] for e in events],body=body)
        with self.work._db(write=True) as db:
            self.work._window(db,request)
            require(not self.work._operation(db,request['operation_id'],request['window_id']),'Operation already exists')
            if events:self._save_offers(db,events,request,request.get('state','pending'),**({'pending_operation_id':request['operation_id']} if op['state']=='prepared' else {}))
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',(request['operation_id'],self.work.user_id,request['window_id'],canonical(body),canonical(op)))
            checkpoint('task-record-before-intent-commit')
        checkpoint('task-record-intent-prepared');return op

    def run(self,handle,op,checkpoint):
        record=op['record'];pid=record['context']['project_id'];self.work._authorize(pid)
        ws=self.work.projects.workspace(pid,blocking=False)
        def prepare(workspace):
            self.work._authorize(pid)
            self.work._pin(workspace.git.snapshot(workspace.git.head()),pid,record['context']['task_id'],workspace.git.head())
            require(workspace.git.head()==op['base_head'],'Projekt se změnil; obnovte kontext.')
            for output in record['outputs']:require(self.activities._readable(output['project_id']),'Výsledek již není dostupný.')
            prefix='artifacts/'+record['id']+'/'
            return {prefix+'metadata.json':encoded(op['metadata']),prefix+'task-work.json':encoded(record)},'Workspace user',self.work.user_id+'@local.invalid','Record work on '+record['context']['task_id']
        receipt=ws.transact(op['native_operation_id'],dict(action='task-record-publish',record=record,base_head=op['base_head']),prepare,
            expected_head=op['base_head'],checkpoint=checkpoint)
        checkpoint('task-record-after-project')
        with self.work._db(write=True) as db:
            self.work._window(db,handle)
            for identifier in op['events']:
                event=json.loads(self.work._operation(db,identifier,handle['window_id'])['doc'])
                state=event['offer'];require(state.get('pending_operation_id')==handle['operation_id'],'Offer reservation changed')
                event['offer']=dict(state,state='confirmed',revision=state['revision']+1,record_id=record['id'])
                event['offer'].pop('pending_operation_id',None);self.work._save_operation(db,identifier,event)
            op.update(state='completed',result=dict(record_id=record['id'],commit_id=receipt['commit_id']))
            self.work._save_operation(db,handle['operation_id'],op);checkpoint('task-record-before-finalize')
        checkpoint('task-record-after-finalize')

    def cancel(self,handle,op):
        require(op['record_type']=='task-record-publish' and op['state']=='prepared','Record operation cannot be cancelled')
        ws=self.work.projects.workspace(op['record']['context']['project_id'],blocking=False)
        with ws.journal.lock(shared=True),ws.journal.connect() as db:
            require(not db.execute('SELECT 1 FROM operations WHERE id=?',(op['native_operation_id'],)).fetchone(),'Projektový zápis již začal; dokončete obnovu.')
        with self.work._db(write=True) as db:
            self.work._window(db,handle)
            for identifier in op['events']:
                event=json.loads(self.work._operation(db,identifier,handle['window_id'])['doc']);state=event['offer']
                event['offer']=dict(state,state='draft',revision=state['revision']+1);event['offer'].pop('pending_operation_id',None)
                self.work._save_operation(db,identifier,event)
            op['state']='rejected';self.work._save_operation(db,handle['operation_id'],op)

    def output(self,request):
        uuid(request['project_id']);uuid(request['record_id'])
        _,_,files,entities=self.snapshot(request['project_id']);record=records(files,entities).get(request['record_id'])
        require(record and record['context']['project_id']==request['project_id'] and self.readable(record),'Záznam není dostupný.')
        index=request['output_index'];require(type(index) is int and 0<=index<len(record['outputs']),'Invalid output')
        require(request['version'] in {'original','current'},'Invalid output version')
        output=record['outputs'][index];pid=output['project_id']
        git,head,_,_=self.snapshot(pid,write=False);commit=output['commit_id'] if request['version']=='original' else head
        require(git.run('merge-base','--is-ancestor',commit,head,check=False).returncode==0,'Původní verze již není v historii projektu.')
        files=git.snapshot(commit);entities=validate_snapshot(files);meta=entities.get(output['artifact_id'])
        require(meta is not None,'Artefakt je v aktuální verzi odstraněný; původní verze zůstává dostupná.')
        if self.work.network:require(all(m['privacy']!='local-only' for m in entities.values()),'Project contains local-only data')
        prefix='artifacts/'+output['artifact_id']+'/'
        sidecar=prefix+'metadata.json' in files;path=prefix+meta['file'] if sidecar else next(p for p in files if p.startswith(prefix))
        if request['version']=='original':require(path==output['path'] and hashlib.sha256(files[path]).hexdigest()==output['sha256'],'Output pin differs')
        return preview(dict(id=output['artifact_id'],commit_id=commit,metadata=meta,path=path,raw=files[path],sidecar=sidecar),request['page'])
