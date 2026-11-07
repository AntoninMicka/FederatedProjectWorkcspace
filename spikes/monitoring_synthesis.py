# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Frozen watch inputs over native Git manifests and the existing report journal."""
from copy import deepcopy
from datetime import datetime
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from spikes.metadata import require, uuid, validate_snapshot
from spikes.monitoring import Monitoring, ident
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.monitoring_definition_schema import validate_graph
from spikes.reporting import Reporting
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, moment, records
from spikes.reporting_schema import ref, text, hex_id, period as validate_period
from spikes.reporting_scheduler import ReportingScheduler, calendar_period, utc
from spikes.source_collector import SourceCollector

SCHEMA='fpw-watch-input-manifest-v1'


def validate_manifest(plan):
    fields(plan,'schema project_id definition_ref period input_head knowledge_cutoff external_refs inputs complete missing')
    require(plan['schema']==SCHEMA,'Unknown synthesis manifest');ref(plan['definition_ref']);validate_period(plan['period'])
    uuid(plan['project_id']);hex_id(plan['input_head'],True);moment(plan['knowledge_cutoff'])
    require(isinstance(plan['external_refs'],list) and len(plan['external_refs'])<=128,'Invalid supplemental pin list')
    for entry in plan['external_refs']:fields(entry,'input_id ref');uuid(entry['input_id']);ref(entry['ref'])
    require(isinstance(plan['inputs'],list) and 1<=len(plan['inputs'])<=128,'Invalid frozen input list')
    require(type(plan['complete']) is bool and isinstance(plan['missing'],list) and len(plan['missing'])<=128,'Invalid completeness')
    for gap in plan['missing']:text(gap)
    for link in plan['inputs']:
        fields(link,'input_id kind take definition_ref policy expected refs missing')
        require(link['kind'] in {'watch','external'},'Unknown frozen link');uuid(link['input_id']);text(link['take'])
        require(link['take'] in {'reports','findings','processed-items','captured-source'},'Unknown frozen output kind')
        if link['definition_ref'] is not None:ref(link['definition_ref'])
        fields(link['policy'],'window approval missing')
        require(link['policy']['window'] in {'ending-in-period','overlap'} and link['policy']['missing'] in {'wait','allow-incomplete'},'Unknown frozen policy')
        require(isinstance(link['expected'],list) and len(link['expected'])<=400,'Too many expected periods')
        for p in link['expected']:validate_period(p)
        require(isinstance(link['refs'],list) and len(link['refs'])<=128,'Too many frozen pins')
        for pin in link['refs']:ref(pin)
        require(isinstance(link['missing'],list) and len(link['missing'])<=400,'Invalid missing periods')
        for gap in link['missing']:text(gap)
    require(len(plan['missing'])==sum(bool(i['missing']) for i in plan['inputs']) and
            plan['complete']==(not plan['missing']),'Frozen completeness differs from gaps')
    require(len({i['input_id'] for i in plan['inputs']})==len(plan['inputs']) and sum(len(i['refs']) for i in plan['inputs'])<=512,'Invalid frozen input identities or size')
    require(len(encoded(plan))<=1024*1024,'Frozen manifest exceeds limit')
    return plan


def policy(link):
    if link['kind']=='external':return deepcopy(link.get('policy',dict(window='ending-in-period',
        approval='selected' if link['connector']=='rss-atom' else 'captured',missing='wait')))
    return deepcopy(link.get('policy',dict(window='ending-in-period',approval=
        'issued' if link['take']=='reports' else 'processed' if link['take']=='processed-items' else 'selected',missing='wait')))


def windows(schedule, period, mode):
    start=moment(period['start_utc']);end=moment(period['end_utc'])
    local=start.astimezone(ZoneInfo(schedule['timezone'])).replace(hour=0,minute=0,second=0,microsecond=0)
    cursor=local if schedule['kind']=='daily' else Monitoring.boundary(dict(timezone=schedule['timezone']),schedule['kind'],start)
    result=[]
    for _ in range(400):
        p=calendar_period(cursor.isoformat(),schedule['kind'],schedule['timezone'],'iso-calendar-v1')
        if moment(p['start_utc'])>=end:break
        matches=(moment(p['end_utc'])>start and (mode=='overlap' or moment(p['end_utc'])<=end))
        if matches and p['start_local'][:10]>=schedule['start']:result.append(p)
        cursor=datetime.fromisoformat(p['end_local'])
    else:require(False,'Too many required input periods')
    return result


class WatchSynthesis:
    @staticmethod
    def _public_run(run):return {k:v for k,v in run.items() if k!='assistance_context'}

    def __init__(self,node):
        self.node=node;self.reporting=Reporting(node);self.scheduler=ReportingScheduler(node)
        self.model=MonitoringDefinitions(node);self.monitoring=Monitoring(node,self.reporting.artifacts.projects)

    def _snapshot(self,pid):
        data=self.reporting.read(pid);ws=self.reporting.artifacts.workspace(pid)
        files=ws.git.snapshot(data['commit_id']);metas=validate_snapshot(files)
        return ws,data['commit_id'],files,metas,{r['revision_id']:r for r in data['records']}

    def _plan(self,pid,definition_ref,period,external_refs):
        ws,head,files,metas,rs=self._snapshot(pid);ws._writable()
        raw,_=SourceCollector.resolve(ws,pid,definition_ref,files,metas);row=json.loads(raw)
        require(row['type']=='WatchDefinition','Expected independent watch')
        tips=validate_graph(rs);value=row['value']
        require(tips[row['entity_id']]['revision_id']==row['revision_id'] and value['active'],'Watch is superseded or paused')
        require(value['placement']['mode']=='local','Remote synthesis is not connected')
        require(value['report']['mode'] in {'deterministic','llm'},'Synthesis requires a report mode')
        if value['report']['mode']=='llm':require(value['report'].get('analysis',{}).get('target') is not None,'LLM synthesis requires an explicit analytical model target')
        require(period['kind']==value['schedule']['kind'] and period['timezone']==value['schedule']['timezone'],'Synthesis period differs from definition')
        from spikes.reporting_schema import period as validate_period
        validate_period(period);require(moment(period['end_utc']).timestamp()<=self.scheduler.now(),'Synthesis period has not closed')
        require(period['calendar_revision']=='iso-calendar-v1' and
                all(period[edge+'_utc']==utc(moment(period[edge+'_utc'])) for edge in ('start','end')),
                'Synthesis period requires the canonical watch calendar')
        require(period['start_local'][:10]>=value['schedule']['start'],'Synthesis precedes watch start')
        cutoff=self.scheduler.stamp();parents={p['artifact_id'] for r in rs.values() for p in r['previous']}
        active=[r for r in rs.values() if r['revision_id'] not in parents and moment(r['recorded_at'])<=moment(cutoff)]
        require(isinstance(external_refs,list) and len(external_refs)<=128,'Too many supplemental inputs')
        explicit={}
        for entry in external_refs:
            fields(entry,'input_id ref');require(entry['input_id'] not in explicit,'Duplicate supplemental binding')
            explicit[entry['input_id']]=entry['ref']
        require(set(explicit)<={i['id'] for i in value['inputs'] if i['kind']=='external'},'Unknown supplemental source')
        selected=[];gaps=[];waiting=False
        def pin(r):return self.reporting.pin(pid,r['revision_id'],head)
        for link in value['inputs']:
            refs=[];missing=[];expected=[];upstream=None
            p=policy(link)
            if link['kind']=='watch':
                require(not link['include_drafts'],'Portable draft inputs are not available; issued reports are required')
                upstream=tips[link['watch_id']];upstream_pin=pin(upstream)
                settings=value['report'].get('analysis')
                if settings and link['take']=='reports' and settings['input_level']!='mixed':
                    require(upstream['value']['schedule']['kind']==settings['input_level'],'Upstream level differs from analytical definition')
                require(PRIVACY[row['privacy']]>=PRIVACY[upstream['privacy']],'Input would relax privacy')
                if link['take']=='reports':
                    expected=windows(upstream['value']['schedule'],period,p['window'])
                    if not expected:missing.append(link['id']+': no eligible reporting period has closed')
                    candidates=[r for r in active if r['type']=='ReportSnapshot' and
                        rs[r['value']['task_ref']['artifact_id']]['entity_id']==ident(link['watch_id'],'definition-task-entity')]
                    corrected={r['value']['corrects']['artifact_id'] for r in candidates if r['value']['corrects']}
                    candidates=[r for r in candidates if r['revision_id'] not in corrected]
                    for slot in expected:
                        matches=[r for r in candidates if r['value']['period']==slot]
                        require(len(matches)<=1,'Conflicting issued reports for an input period')
                        if matches:refs.append(pin(matches[0]))
                        else:missing.append(link['id']+': missing issued '+slot['start_local']+' / '+slot['end_local'])
                else:
                    for r in active:
                        if r['type']!='SourceFinding':continue
                        item=r['value'];owner=rs[item['definition_ref']['artifact_id']]['entity_id']
                        at=moment(item['item']['discovered_at'])
                        approved=(p['approval']=='captured' or item['stage']=='processed' or
                                  p['approval']=='selected' and item['selection']['decision']=='selected')
                        if owner==link['watch_id'] and moment(period['start_utc'])<=at<moment(period['end_utc']) and approved:refs.append(pin(r))
                    if not refs:missing.append(link['id']+': no eligible '+link['take']+' in period')
            elif link['connector']=='rss-atom':
                for r in active:
                    if r['type']=='SourceFinding' and r['value']['input_id']==link['id'] and rs[r['value']['definition_ref']['artifact_id']]['entity_id']==row['entity_id']:
                        at=moment(r['value']['item']['discovered_at'])
                        approved=p['approval']=='captured' or r['value']['stage']=='processed' or p['approval']=='selected' and r['value']['selection']['decision']=='selected'
                        if moment(period['start_utc'])<=at<moment(period['end_utc']) and approved:refs.append(pin(r))
                if not refs:missing.append(link['id']+': no captured RSS item in period')
            else:
                require(link['connector'] in {'static-text','web-search'},'Connector is unavailable')
                if link['id'] in explicit:
                    ref=explicit[link['id']];_,meta=SourceCollector.resolve(ws,pid,ref,files,metas)
                    record=rs.get(ref['artifact_id'])
                    require(meta['kind']=='source' or record and record['type']=='Source' and record['value']['capture_state']=='captured',
                            'Supplement must be an explicitly captured source')
                    refs.append(ref)
                else:missing.append(link['id']+': approved '+link['connector']+' capture is missing')
            for ref in refs:
                require(PRIVACY[row['privacy']]>=PRIVACY[metas[ref['artifact_id']]['privacy']],'Selected source would relax privacy')
                require(ws.git.run('merge-base','--is-ancestor',ref['commit_id'],head,check=False).returncode==0,'Input is beyond frozen head')
            require(len(refs)<=128,'Too many inputs on one link')
            if missing:gaps.append(link['id']+': '+str(len(missing))+' missing input(s); '+missing[0])
            waiting|=bool(missing) and p['missing']=='wait'
            selected.append(dict(input_id=link['id'],kind=link['kind'],take=link.get('take','captured-source'),
                definition_ref=upstream_pin if upstream else None,policy=p,expected=expected,refs=refs,missing=missing))
        require(sum(len(i['refs']) for i in selected)<=512,'Synthesis input list exceeds limit')
        plan=dict(schema=SCHEMA,project_id=pid,definition_ref=definition_ref,period=period,input_head=head,
                  knowledge_cutoff=cutoff,external_refs=deepcopy(external_refs),inputs=selected,complete=not gaps,missing=gaps)
        return row,validate_manifest(plan),waiting

    def prepare(self,pid,definition_ref,period,*,external_refs=None,checkpoint=lambda stage:None):
        external_refs=[] if external_refs is None else external_refs
        require(isinstance(external_refs,list) and len(external_refs)<=128,'Expected bounded supplemental source pins')
        ws,head,files,metas,rs=self._snapshot(pid);ws._writable()
        raw,_=SourceCollector.resolve(ws,pid,definition_ref,files,metas);definition=json.loads(raw)
        require(definition['type']=='WatchDefinition','Expected independent watch')
        slot=ident(definition['entity_id'],'synthesis:'+digest(encoded(period)))
        manifest_id=ident(slot,'inputs');operation=ident(slot,'freeze')
        ws.recover();receipt=ws.receipt(operation)
        if receipt is None:
            definition,plan,waiting=self._plan(pid,definition_ref,period,external_refs)
            if waiting:return dict(state='waiting-inputs',complete=False,missing=plan['missing'],inputs=plan['inputs'])
            require(ws.git.head()==plan['input_head'],'Project changed during input selection')
            manifest_ref=self.monitoring._doc(pid,manifest_id,'Sledování — zmrazené vstupy',encoded(plan).decode(),operation,definition['privacy'])
            checkpoint('synthesis-frozen')
        else:manifest_ref=self.reporting.pin(pid,manifest_id,receipt['commit_id'])
        current=ws.git.snapshot(ws.git.head());raw,_=SourceCollector.resolve(ws,pid,manifest_ref,current,validate_snapshot(current));plan=validate_manifest(json.loads(raw))
        require(plan['definition_ref']['artifact_id']==definition_ref['artifact_id'] and plan['definition_ref']['sha256']==definition_ref['sha256']
                and plan['period']==period and plan['external_refs']==external_refs,'Period already has a different frozen intent; explicit correction required')
        job=self.model.prepare_run(pid,plan['definition_ref'],period,ident(slot,'run'),frozen_inputs=manifest_ref,knowledge_cutoff=plan['knowledge_cutoff'])
        return dict(state=job['state'],run=self._public_run(job),manifest_ref=manifest_ref,complete=plan['complete'],missing=plan['missing'])

    def _manifest(self,run):
        ws=self.reporting.artifacts.workspace(run['project_id']);files=ws.git.snapshot(run['input_head']);metas=validate_snapshot(files)
        raw,_=SourceCollector.resolve(ws,run['project_id'],run['rules_ref'],files,metas);ref=json.loads(raw)['synthesis_manifest']
        raw,_=SourceCollector.resolve(ws,run['project_id'],ref,files,metas)
        return ref,validate_manifest(json.loads(raw))

    def execute(self,pid,definition_ref,period,*,external_refs=None,model_execution=None,checkpoint=lambda stage:None):
        prepared=self.prepare(pid,definition_ref,period,external_refs=external_refs,checkpoint=checkpoint)
        if 'run' not in prepared:return prepared
        run=prepared['run']
        if run['state']=='collecting':
            with self.scheduler.db() as db:
                until=db.execute('SELECT lease_until FROM runs WHERE run_id=?',(run['run_id'],)).fetchone()[0]
            if until<=self.scheduler.now():
                try:self.scheduler.claim(run['run_id'],str(uuid4()))
                except ValueError:pass
                prepared.update(run=self._public_run(self.scheduler.get(run['run_id'])),state='unknown')
        if run['state']!='prepared':return prepared
        _,initial_plan=self._manifest(run)
        ws=self.reporting.artifacts.workspace(pid);initial_files=ws.git.snapshot(ws.git.head())
        raw,_=SourceCollector.resolve(ws,pid,initial_plan['definition_ref'],initial_files,validate_snapshot(initial_files))
        if json.loads(raw)['value']['report']['mode']=='llm':
            from spikes.synthesis_model import validate_execution
            validate_execution(model_execution,json.loads(raw)['value'])
        claimed=self.scheduler.claim(run['run_id'],str(uuid4()),lease_seconds=600);run=claimed['run']
        try:
            manifest_ref,plan=self._manifest(run)
            ws,head,files,metas,rs=self._snapshot(pid)
            raw,_=SourceCollector.resolve(ws,pid,plan['definition_ref'],files,metas);definition=json.loads(raw)
            tips=validate_graph(rs);require(tips[definition['entity_id']]['revision_id']==definition['revision_id'] and definition['value']['active'],'Watch changed after freezing')
            value,markdown,_=self.monitoring.synthesize(pid,dict(privacy=definition['privacy'],inputs=[],name=definition['value']['title'],
                goal=definition['value']['goal'],periods={period['kind']:definition['value']['report']['instructions']}),run)
            if any(link['refs'] for link in plan['inputs']):
                markdown=markdown.replace('Nebyla doložena významná změna.',
                    'Převzaté podklady zachovávají původní zadání a stav ověření; tento přehled neposkytuje nové nezávislé ověření.')
            lines=[markdown,'\n## Vstupní sledování a úplnost', 'Úplná sada vstupů.' if plan['complete'] else 'NEÚPLNÁ sada vstupů.',*plan['missing']]
            for link in plan['inputs']:
                lines.append('\n### Vstup '+link['input_id']+' / '+link['take'])
                lines.extend(link['missing'])
                for pin in link['refs']:
                    raw,meta=SourceCollector.resolve(ws,pid,pin,files,metas)
                    lines.append('- ['+meta['title']+']('+pin['path']+') @ '+pin['commit_id']+' sha256:'+pin['sha256'])
                    record=rs.get(pin['artifact_id'])
                    if record and record['type']=='ReportSnapshot':
                        content=record['value']['markdown'];path=content['path']
                        original=ws.git.snapshot(pin['commit_id']);require(digest(original[path])==content['sha256'],'Input report content changed')
                        lines.append(original[path].decode()[:2000])
                    elif record and record['type']=='SourceFinding':
                        lines.append(record['value']['item']['title']+'\n'+(record['value']['item']['content'] or '')[:2000])
                    else:lines.append(raw.decode('utf-8',errors='replace')[:2000])
            lines+=['\n## Zadání tohoto sledování',definition['value']['report']['instructions'],
                    '\nPřevzetí podkladu nepotvrzuje jeho tvrzení. Výňatky jsou omezené; úplné bajty jsou připnuté ve zdrojích.']
            value['synthesis']=dict(manifest_ref=manifest_ref,complete=plan['complete'],missing=plan['missing'])
            if plan['missing']:value['limitations'].append('Neúplné vstupy: '+'; '.join(plan['missing']))
            markdown='\n'.join(lines)+'\n'
            generation=None
            if period['kind'] in {'monthly','quarterly','annual'} or 'analysis' in definition['value']['report']:
                from spikes.synthesis_analysis import from_git,render
                ledger=from_git(ws,pid,plan,manifest_ref,definition['value'],definition['privacy'],files,metas)
                analysis_ref=self.monitoring._doc(pid,ident(run['run_id'],'analysis'),'Sledování — analytická evidence',
                    encoded(ledger).decode(),ident(run['run_id'],'analysis-op'),definition['privacy'])
                checkpoint('synthesis-analysis')
                actual=ws.git.snapshot(ws.git.head())[analysis_ref['path']]
                require(json.loads(actual)==ledger,'Stored analytical ledger differs from frozen evidence')
                value['analysis_ref']=analysis_ref
                markdown=render(ledger,definition['value']['report']['required_sections'])
                if definition['value']['report']['mode']=='llm':
                    from spikes.synthesis_model import execute as model_execute
                    markdown,generation=model_execute(self,run,claimed['lease_token'],definition,ledger,analysis_ref,
                        manifest_ref,model_execution,checkpoint)
                    value['generation']=generation
                if ledger['gaps'] and not plan['missing']:value['limitations'].append('Převzaté zprávy obsahují mezery ve vstupech.')
                if any('Omezený zdroj:' in limit for limit in ledger['limitations']):value['reproducibility']='limited-inputs'
                head=ws.git.head()
            self.scheduler.stage(run['run_id'],claimed['lease_token'],dict(project_id=pid,base_head=head,records=[dict(
                type='ReportSnapshot',entity_id=None,previous=[],privacy=definition['privacy'],value=value,markdown=markdown)]),checkpoint=checkpoint,_generation=generation)
        except Exception:
            outcome='failed'
            if model_execution is not None:
                model=model_execution.adapter.runs.get(ident(run['run_id'],'analytical-model'))
                if model and model['state'] in {'dispatching','unknown'}:outcome='unknown'
            self.scheduler.fail(run['run_id'],claimed['lease_token'],outcome=outcome);raise
        prepared.update(state='review',run=self._public_run(self.scheduler.get(run['run_id'])))
        return prepared

    def publish(self,run_id,approval_digest,*,confirm=False,checkpoint=lambda stage:None):
        run=self.scheduler.get(run_id);_,plan=self._manifest(run)
        def guard(ws,files,metas):
            tips=validate_graph(records(files,metas));original=plan['definition_ref']
            row=next((r for r in tips.values() if r['revision_id']==original['artifact_id']),None)
            require(row is not None and row['value']['active'],'Synthesis definition was changed or paused')
        ws=self.reporting.artifacts.workspace(run['project_id']);ws.recover()
        if ws.receipt(run_id) is None:
            files=ws.git.snapshot(ws.git.head());guard(ws,files,validate_snapshot(files))
        self.scheduler.approve(run_id,approval_digest,confirm=confirm)
        return self._public_run(self.scheduler.publish(run_id,checkpoint=checkpoint,_publication_guard=guard))

    def retry(self,run_id,*,confirm=False,model_execution=None):
        run=self.scheduler.get(run_id);_,plan=self._manifest(run)
        ws=self.reporting.artifacts.workspace(run['project_id']);files=ws.git.snapshot(ws.git.head())
        raw,_=SourceCollector.resolve(ws,run['project_id'],plan['definition_ref'],files,validate_snapshot(files))
        definition=json.loads(raw)['value']
        if definition['report']['mode']=='llm':
            from spikes.synthesis_model import validate_execution
            validate_execution(model_execution,definition)
        self.scheduler.retry(run_id,confirm=confirm)
        return self.execute(run['project_id'],plan['definition_ref'],plan['period'],external_refs=plan['external_refs'],model_execution=model_execution)

    def freshness(self,pid,report_ref):
        ws,head,files,metas,rs=self._snapshot(pid)
        raw,_=SourceCollector.resolve(ws,pid,report_ref,files,metas);report=json.loads(raw)
        require(report['type']=='ReportSnapshot' and 'synthesis' in report['value'],'Expected a synthesis report')
        pin=report['value']['synthesis']['manifest_ref'];raw,_=SourceCollector.resolve(ws,pid,pin,files,metas);plan=json.loads(raw)
        selected={n['ref']['artifact_id'] for n in self.trace(pid,report_ref,_operative=True)['nodes'] if n['ref']['artifact_id']!=report_ref['artifact_id']};changed=[]
        for row in rs.values():
            if row['revision_id']==report_ref['artifact_id'] or row['revision_id'] in selected:continue
            if row['type']=='ReportSnapshot' and row['value']['corrects'] and row['value']['corrects']['artifact_id'] in selected:
                changed.append(self.reporting.pin(pid,row['revision_id'],head))
            elif any(p['artifact_id'] in selected for p in row['previous']):changed.append(self.reporting.pin(pid,row['revision_id'],head))
        return dict(potentially_stale=bool(changed),newer_inputs=changed,report_ref=report_ref,head=head)

    def trace(self,pid,report_ref,*,_operative=False):
        ws,head,files,metas,rs=self._snapshot(pid);pending=[(report_ref,None)];nodes={};edges=[]
        while pending:
            pin,parent=pending.pop();key=digest(encoded(pin))
            if parent:edges.append(dict(source=parent,target=key))
            if key in nodes:continue
            require(len(nodes)<2048,'Provenance trace exceeds limit')
            raw,meta=SourceCollector.resolve(ws,pid,pin,files,metas)
            require(ws.git.run('merge-base','--is-ancestor',pin['commit_id'],head,check=False).returncode==0,'Trace pin is outside history')
            nodes[key]=dict(id=key,ref=pin,type=meta['kind'])
            record=rs.get(pin['artifact_id']);refs=[]
            if record:
                nodes[key]['type']=record['type']
                from spikes.reporting_schema import references
                selected_record=deepcopy(record) if _operative else record
                if _operative:
                    selected_record['previous']=[];selected_record['provenance']['inputs']=[]
                    for name in ('corrects','baseline_snapshot'):selected_record['value'].pop(name,None)
                refs=list(references(selected_record))
            elif meta['kind']=='document':
                try:document=json.loads(raw)
                except (ValueError,UnicodeError):document={}
                if isinstance(document,dict) and document.get('schema')==SCHEMA:
                    refs=[document['definition_ref']]+[p for i in document['inputs'] for p in i['refs']]
                elif isinstance(document,dict) and document.get('schema')=='fpw-synthesis-analysis-v1':
                    refs=document['evidence_refs']
            for child in refs:
                if 'at' in child:child={k:v for k,v in child.items() if k!='at'}|dict(project_id=pid,commit_id=pin['commit_id'])
                pending.append((child,key))
        require(ws.git.head()==head,'Project changed while tracing inputs')
        return dict(project_id=pid,head=head,root=digest(encoded(report_ref)),nodes=list(nodes.values()),edges=edges)
