# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Deterministic longitudinal evidence ledger; summaries never certify claims."""
from copy import deepcopy
import json

from spikes.metadata import require
from spikes.reporting_schema import digest, encoded, canonical_events, moment

SCHEMA='fpw-synthesis-analysis-v1'
ENGINE='longitudinal-evidence-v1'


def from_git(workspace,project_id,manifest,manifest_ref,definition,privacy,files=None,metas=None):
    from spikes.metadata import validate_snapshot
    from spikes.source_collector import SourceCollector
    from spikes.reporting_schema import PRIVACY,records
    files=workspace.git.snapshot(workspace.git.head()) if files is None else files
    metas=validate_snapshot(files) if metas is None else metas
    registered=records(files,metas)
    def resolve(pin):
        raw,current_meta=SourceCollector.resolve(workspace,project_id,pin,files,metas)
        meta=json.loads(workspace.git.run('show',pin['commit_id']+':artifacts/'+pin['artifact_id']+'/metadata.json',binary=True).stdout)
        require(PRIVACY[privacy]>=max(PRIVACY[meta['privacy']],PRIVACY[current_meta['privacy']]),'Analytical evidence would relax privacy')
        if pin!=manifest_ref:
            require(workspace.git.run('merge-base','--is-ancestor',pin['commit_id'],manifest['input_head'],check=False).returncode==0,
                    'Analytical evidence exceeds frozen input head')
            require(moment(meta['created_at'])<=moment(manifest['knowledge_cutoff']),'Analytical evidence exceeds cutoff')
        row=registered.get(pin['artifact_id']) if meta['kind']!='source' else None
        if row is not None:require(digest(encoded(row))==digest(raw),'Analytical record differs from pinned bytes')
        return meta,row,raw
    return build(manifest,manifest_ref,definition,resolve)


def build(manifest, manifest_ref, definition, resolve):
    """resolve(pin) -> (metadata, record-or-None, bytes); only frozen pins are read."""
    rows={};pins={};edges={};gaps=[];reports=[];corrections=[];source_limits=[];sources=[];cases=[];documents={}
    pending=[manifest_ref]+[c['ref'] for c in definition['report'].get('analysis',{}).get('case_studies',[])]
    def child(pin,parent):
        if 'at' in pin:pin={k:v for k,v in pin.items() if k!='at'}|dict(project_id=parent['project_id'],commit_id=parent['commit_id'])
        return pin
    while pending:
        pin=pending.pop(0);key=pin['artifact_id']
        if key in pins:
            require(pins[key]['sha256']==pin['sha256'],'Conflicting immutable evidence bytes');continue
        require(len(pins)<1024,'Analytical evidence closure exceeds limit')
        meta,row,raw=resolve(pin);pins[key]=deepcopy(pin);rows[key]=row;targets=[]
        if meta['kind']=='source' or row and row['type']=='Source':
            sources.append(dict(ref=pin,title=row['value']['title'] if row else meta.get('title',key),
                availability=row['value']['availability'] if row else 'captured'))
        if row:
            v=row['value'];kind=row['type']
            if kind=='ReportSnapshot':
                reports.append(dict(ref=pin,period=v['period'],knowledge_cutoff=v['knowledge_cutoff']))
                targets+=sum([v[k] for k in ('events','sources','stories','assessments')],[])
                if 'synthesis' in v:targets.append(v['synthesis']['manifest_ref'])
                if v['corrects']:corrections.append(dict(before=v['corrects'],after=pin,reason=v['correction_reason']))
                source_limits+=v['limitations']
                if v.get('task_ref'):targets.append(v['task_ref'])
            elif kind=='Event':
                targets+=v['sources']+v['assessments']+row['previous']
                if v.get('task_ref'):targets.append(v['task_ref'])
            elif kind=='EvidenceAssessment':
                targets+=[e['source_ref'] for e in v['evidence']]+[v['scale_ref']]+row['previous']
                if v.get('task_ref'):targets.append(v['task_ref'])
                if v['review'] and v['review'].get('policy_revision'):targets.append(v['review']['policy_revision'])
            elif kind=='ReportingTask':targets+=[v['source_policy'],v['selection_policy']]
            elif kind=='Story':targets+=v['events']+row['previous']
            elif kind=='SourceFinding':targets+=[v['raw_ref']]+row['previous']
            elif kind=='Source':
                if v['raw_ref']:targets.append(v['raw_ref'])
                if v['capture_state']=='reference-only' or v['availability']!='available':source_limits.append('Omezený zdroj: '+v['title'])
            elif kind=='WatchDefinition':
                for case in v.get('report',{}).get('analysis',{}).get('case_studies',[]):
                    cases.append(deepcopy(case)|dict(declared_in=pin));targets.append(case['ref'])
        elif meta['kind']=='document':
            try:doc=json.loads(raw)
            except (ValueError,UnicodeError):doc={}
            documents[key]=doc
            if isinstance(doc,dict) and doc.get('schema')=='fpw-watch-input-manifest-v1':
                if doc.get('definition_ref'):targets.append(doc['definition_ref'])
                for link in doc['inputs']:
                    targets+=link['refs']
                    if link.get('definition_ref'):targets.append(link['definition_ref'])
                    gaps.extend(dict(manifest_ref=pin,input_id=link['input_id'],detail=m) for m in link['missing'])
            elif isinstance(doc,dict) and doc.get('schema')=='fpw-monitoring-run-rules-v1':targets.append(doc['definition_ref'])
        targets=[child(p,pin) for p in targets];edges[key]=[p['artifact_id'] for p in targets];pending+=targets
    # Only the latest selected revision of each Story supplies active reviewed
    # duplicate decisions. Text similarity and model guesses never merge events.
    # Equal recorded_at timestamps are legal. Ancestry, not UUID ordering,
    # determines the original/current revision within a chain.
    depths={};remaining={id_:r for id_,r in rows.items() if r}
    while remaining:
        ready=[id_ for id_,r in remaining.items() if all(p['artifact_id'] not in remaining for p in r['previous'])]
        require(ready,'Cyclic analytical revision history')
        for id_ in ready:
            row=remaining.pop(id_);depths[id_]=1+max((depths.get(p['artifact_id'],0) for p in row['previous']),default=0)
    rank=lambda row:(row['recorded_at'],depths[row['revision_id']],row['revision_id'])
    story_tips={}
    for row in rows.values():
        if row and row['type']=='Story':
            old=story_tips.get(row['entity_id'])
            if old is None or rank(row)>rank(old):story_tips[row['entity_id']]=row
    aliases={}
    for row in story_tips.values():
        for before,after in canonical_events(row).items():
            require(before not in aliases or aliases[before]==after,'Conflicting reviewed event aliases');aliases[before]=after
    def canonical(identity):
        seen=set()
        while identity in aliases:
            require(identity not in seen,'Cyclic reviewed event aliases');seen.add(identity);identity=aliases[identity]
        return identity
    groups={};signals={};assessments=[]
    for row in rows.values():
        if not row:continue
        if row['type']=='Event':groups.setdefault(canonical(row['entity_id']),[]).append(row)
        elif row['type']=='EvidenceAssessment':assessments.append(row)
        elif row['type']=='SourceFinding':signals.setdefault(row['entity_id'],[]).append(row)
    def ordered(values):return sorted(values,key=rank)
    def reference(row):return pins[row['revision_id']]
    def rule_signature(pin):
        doc=documents.get(pin['artifact_id'])
        if isinstance(doc,dict) and doc.get('schema')=='fpw-monitoring-run-rules-v1':
            definition_row=rows[doc['definition_ref']['artifact_id']]['value']
            return dict(evaluation=definition_row['evaluation'],selection=definition_row['selection'],scope=definition_row['scope'])
        return dict(artifact_id=pin['artifact_id'],sha256=pin['sha256'])
    def methodology(row):
        v=row['value'];task=rows.get(v.get('task_ref',{}).get('artifact_id'))
        if not task:return None
        data=dict(scope=task['value']['scope'],source=rule_signature(task['value']['source_policy']),
                  selection=rule_signature(task['value']['selection_policy']))
        if v['review'] and v['review'].get('policy_revision'):data['review']=rule_signature(v['review']['policy_revision'])
        return digest(encoded(data))
    def supported(row):
        v=row['value']
        return bool(v['review'] and v['review']['decision']=='confirmed' and v['ratings']['confidence'] not in {None,'insufficient'} and any(
            e['relation']=='supports' and rows[e['source_ref']['artifact_id']]['value']['availability']=='available' and
            (rows[e['source_ref']['artifact_id']]['value']['source_role']=='primary' or e['independence_group']) for e in v['evidence']))
    def report_mentions(ids):
        found=[]
        for report in reports:
            todo=list(edges[report['ref']['artifact_id']]);seen=set()
            while todo:
                id_=todo.pop()
                if id_ in seen:continue
                seen.add(id_);todo+=edges.get(id_,[])
            if seen & ids:found.append(report['ref'])
        return found
    events=[]
    for identity,versions in sorted(groups.items()):
        versions=ordered(versions);claim_groups={}
        for event in versions:
            for claim in event['value']['claims']:claim_groups.setdefault((event['entity_id'],claim['claim_id']),[]).append((event,claim))
        claims=[]
        for (event_id,claim_id),history in sorted(claim_groups.items()):
            first,last=history[0],history[-1]
            relevant=ordered([a for a in assessments if a['value']['subject']['event_id']==event_id and a['value']['subject']['claim_id']==claim_id])
            # Event/claim ID alone is insufficient: stale ratings of changed text
            # never become the current claim's evidence by being repeated.
            matches=[a for a in relevant if a['value']['subject']['claim_sha256']==digest(encoded(last[1]))]
            chains={a['entity_id'] for a in matches};a0=matches[0] if matches else None;a1=matches[-1] if matches else None
            contradiction=any(e['relation']=='contradicts' for a in matches for e in a['value']['evidence'])
            scale=lambda a:(a['value']['scale_ref']['artifact_id'],a['value']['scale_ref']['sha256'])
            methodologies={methodology(a) for a in relevant}
            methodology_changed=len({scale(a) for a in relevant})>1 or len(methodologies-{None})>1
            trend='insufficient-evidence'
            if methodology_changed:trend='methodology-change'
            elif first[1]!=last[1]:trend='claim-change'
            elif contradiction:trend='conflicting-evidence'
            elif len(chains)>1:trend='multiple-assessments'
            elif a0 and a1:
                # A methodology change anywhere in this claim's recorded history
                # blocks numeric progression, including a simultaneous text edit.
                if methodology_changed:trend='methodology-change'
                elif first[1]!=last[1]:trend='claim-change'
                elif len(matches)>1 and None not in methodologies and supported(a0) and supported(a1):
                    lo=a0['value']['ratings']['maturity'];hi=a1['value']['ratings']['maturity']
                    if lo is not None and hi is not None:trend='progress' if hi>lo else 'regression' if hi<lo else 'stagnation'
            evidence=list({encoded(e['source_ref']):e['source_ref'] for a in relevant for e in a['value']['evidence']}.values())
            claims.append(dict(event_id=event_id,claim_id=claim_id,original=first[1],current=last[1],
                original_ref=reference(first[0]),current_ref=reference(last[0]),trend=trend,
                trustworthiness='reviewed-support' if matches and len(chains)==1 and supported(a1) and not contradiction else 'unverified',
                assessments=[reference(a) for a in relevant],evidence_refs=evidence))
            claims[-1].update(contradictions=contradiction,methodology_changed=methodology_changed)
            def assessment_state(a):
                return dict(ref=reference(a),ratings=deepcopy(a['value']['ratings']),scale_ref=a['value']['scale_ref'],
                    reviewed=bool(a['value']['review'] and a['value']['review']['decision']=='confirmed')) if a else None
            one_chain=len({a['entity_id'] for a in relevant})==1
            claims[-1].update(original_assessment=assessment_state(relevant[0]) if relevant and one_chain else None,
                             current_assessment=assessment_state(a1) if one_chain else None)
        events.append(dict(event_id=identity,aliases=sorted({r['entity_id'] for r in versions}),
            versions=[reference(r) for r in versions],original_title=versions[0]['value']['title'],current_title=versions[-1]['value']['title'],
            reported_in=report_mentions({r['revision_id'] for r in versions}),claims=claims,
            original_date=versions[0]['value'].get('event_date'),current_date=versions[-1]['value'].get('event_date'),
            late=any(moment(r['recorded_at'])>moment(manifest['period']['end_utc']) for r in versions)))
    signal_values=[]
    for identity,versions in sorted(signals.items()):
        versions=ordered(versions);current=versions[-1]
        signal_values.append(dict(finding_id=identity,title=current['value']['item']['title'],stage=current['value']['stage'],
            trustworthiness='unverified',versions=[reference(r) for r in versions]))
    levels=[]
    for link in manifest['inputs']:
        if link['kind']=='watch':
            _,upstream,_=resolve(link['definition_ref']);levels.append(dict(input_id=link['input_id'],kind=upstream['value']['schedule']['kind'],take=link['take']))
    settings=definition['report'].get('analysis',{})
    ledger=dict(schema=SCHEMA,engine=ENGINE,manifest_ref=manifest_ref,definition_ref=manifest['definition_ref'],
        instruction=definition['report']['instructions'],revision=settings.get('revision','longitudinal-v1'),
        period=manifest['period'],knowledge_cutoff=manifest['knowledge_cutoff'],input_levels=levels,
        unique_events=len(events),events=events,signals=signal_values,gaps=gaps,corrections=corrections,reports=reports,sources=sources,
        case_studies=cases+[deepcopy(c)|dict(declared_in=manifest['definition_ref']) for c in settings.get('case_studies',[])
                            if not any(existing['ref']==c['ref'] and existing['declared_in']==manifest['definition_ref'] for existing in cases)],
        limitations=sorted(set(source_limits+['Opakovaná zmínka není nezávislý důkaz.','Neznámý stav se neodhaduje ze souhrnu.'])),
        evidence_refs=[pins[k] for k in sorted(pins)])
    require(len(encoded(ledger))<=1024*1024,'Analytical ledger exceeds limit')
    return ledger


LABELS={'progress':'Pokrok','stagnation':'Stagnace','regression':'Regrese','methodology-change':'Změna metodiky — nesrovnatelné',
        'claim-change':'Změna tvrzení — nesrovnatelné','insufficient-evidence':'Nedostatek důkazů','conflicting-evidence':'Rozpor v důkazech',
        'multiple-assessments':'Více hodnocení — bez automatické preference'}


def render(ledger,required_sections=(),model=None):
    lines=['# Přehled','## Analytické zadání',ledger['instruction'],
        'Hranice znalosti: '+ledger['knowledge_cutoff'],'Unikátních událostí: '+str(ledger['unique_events']),
        'NEÚPLNÁ evidence — mezery jsou uvedené níže.' if ledger['gaps'] else 'Ve vybraných manifestech nejsou uvedené mezery.',
        'Výchozí versus aktuální stav jsou níže oddělené; zmínky napříč reporty nejsou nové nezávislé události.',
        '## Vývoj a srovnatelnost']
    def cite(pin):return '['+pin['artifact_id']+']('+pin['path']+') @ '+pin['commit_id']+' sha256:'+pin['sha256']
    for event in ledger['events']:
        lines+=['### '+event['current_title'], 'Identita: '+event['event_id']+'; zmínek ve vydáních: '+str(len(event['reported_in']))]
        lines.append('Přesnost data události: '+(event['current_date']['precision'] if event['current_date'] else 'unknown'))
        if event['late']:lines.append('Pozdě zaevidovaný podklad; datum záznamu není datem události.')
        for claim in event['claims']:
            lines+=['Původní tvrzení: '+claim['original']['text'],'Aktuální tvrzení: '+claim['current']['text'],
                    'Původní scope / stupeň: '+claim['original']['scope']+' / '+claim['original']['stage'],
                    'Aktuální scope / stupeň: '+claim['current']['scope']+' / '+claim['current']['stage'],
                    LABELS[claim['trend']]+' · '+claim['trustworthiness'], 'Původní podklad: '+cite(claim['original_ref']),
                    'Aktuální podklad: '+cite(claim['current_ref'])]
            for name,label in [('original_assessment','Původní hodnocení'),('current_assessment','Aktuální hodnocení')]:
                state=claim[name]
                lines.append(label+': '+(str(state['ratings'])+' · škála '+cite(state['scale_ref'])+' · '+('posouzené' if state['reviewed'] else 'návrh bez review') if state else 'neznámé nebo nejednoznačné'))
            if claim['contradictions']:lines.append('Existuje odporující důkaz; potvrzení se neodvozuje ze skóre.')
            lines+=['Důkaz: '+cite(p) for p in claim['evidence_refs']]
    lines+=['## Neověřené signály']
    lines += [s['title']+' — neověřené tvrzení · '+s['stage']+' · '+cite(s['versions'][-1]) for s in ledger['signals']]
    lines+=['## Rozpory, nejistota a mezery']
    lines += [g['detail']+' · '+cite(g['manifest_ref']) for g in ledger['gaps']] or ['Ve vybraných manifestech nejsou uvedené mezery; to nepotvrzuje tvrzení zdrojů.']
    lines+=['## Opravy a pozdní informace']+[cite(c['after'])+' opravuje '+cite(c['before'])+' · '+c['reason'] for c in ledger['corrections']]
    lines+=['## Rozpracované případové studie a slepé větve']
    lines += [c['status']+' (výslovně deklarovaný stav): '+c['note']+' · '+cite(c['ref'])+' · zadání '+cite(c['declared_in']) for c in ledger['case_studies']] or ['Nebyly explicitně vybrány případové studie; dokončení ani opuštění se neodhadují.']
    lines+=['## Podklady a vydání']
    lines += [r['period']['kind']+' '+r['period']['start_local']+' — '+r['period']['end_local']+' · '+cite(r['ref']) for r in ledger['reports']]
    lines += [s['title']+' · '+s['availability']+' · '+cite(s['ref']) for s in ledger['sources']]
    if model:
        lines+=['## Modelový analytický návrh — k posouzení',model['overview']]
        lines += [a['event_id']+' / '+a['claim_id']+' · '+LABELS[a['trend']]+' · '+a['explanation'] for a in model['annotations']]
    lines+=['## Omezení',*ledger['limitations']]
    if not ledger['events'] and not ledger['signals']:lines.append('Nebyla doložena významná změna.')
    for section in required_sections:
        if section not in lines:lines += [section,'Použijte výše uvedenou evidenci; další závěr bez důkazů zůstává neznámý.']
    return '\n'.join(lines)+'\n'
