# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Issued-report inputs selected by stable processing ID and frozen as Git pins."""
from spikes.metadata import require, uuid, validate_snapshot
from spikes.reporting_schema import PRIVACY, fields, ref, records, encoded
from spikes.report_outputs import published_outputs


def validate_links(links,pid):
    require(isinstance(links,list) and len(links)<=128,'Too many report inputs')
    seen=set()
    for link in links:
        fields(link,'task_id run_id ref');uuid(link['task_id']);uuid(link['run_id']);ref(link['ref'])
        require(link['ref']['project_id']==pid,'Report input belongs to another project')
        require(link['ref']['artifact_id'] not in seen,'Duplicate report input');seen.add(link['ref']['artifact_id'])


def editions(snapshot,pid):
    data,files,entities=snapshot
    return published_outputs(pid,data['commit_id'],files,entities,{r['revision_id']:r for r in data['records']},include_content=True)


def select(snapshot,pid,task_ids,since,until,privacy):
    if not task_ids:return [],[],[]
    outputs=editions(snapshot,pid);by_run={o['run_id']:o for o in outputs if o.get('run_id')}
    links=[];selected=[];gaps=[]
    for task_id in task_ids:
        candidates=[o for o in outputs if o.get('processing_id')==task_id and o.get('run_id')]
        superseded=set()
        for output in candidates:
            parent=output.get('reprocess_of');visited={output['run_id']}
            while parent:
                uuid(parent);require(parent not in visited,'Cycle in issued report corrections');visited.add(parent);superseded.add(parent)
                old=by_run.get(parent)
                if old is None:break
                require(old.get('processing_id')==task_id,'Correction belongs to another processing task')
                parent=old.get('reprocess_of')
        eligible=[o for o in candidates if o['run_id'] not in superseded and type(o.get('period_end')) in {int,float} and since<=coverage_time(o)<=until]
        from spikes.monitoring_blocks import validate_blocks
        from spikes.composable_monitoring import processing_slot
        source=validate_blocks({r['revision_id']:r for r in snapshot[0]['records']})[task_id]
        missing=expected_slots(source['value']['config']['schedule'],since,until)-{
            processing_slot(source['value']['config']['schedule'],o['period_end']) for o in eligible}
        if missing or not eligible:gaps.append(dict(task_id=task_id,periods=sorted(missing),missing_all=not bool(eligible)))

        roots={}
        for output in eligible:
            root=output['run_id'];parent=output.get('reprocess_of')
            while parent:
                root=parent;old=by_run.get(parent);parent=old.get('reprocess_of') if old else None
            require(root not in roots,'Souběžné opravy vstupní zprávy vyžadují posouzení');roots[root]=output
        for output in sorted(eligible,key=lambda o:(o['period_end'],o['id'])):
            validate_links(output.get('report_inputs',[]),pid)
            require(PRIVACY[privacy]>=PRIVACY[snapshot[2][output['id']]['privacy']],'Report input lowers privacy')
            links.append(dict(task_id=task_id,run_id=output['run_id'],ref=output['report_ref']));selected.append(output)
    validate_links(links,pid)
    validate_gaps(gaps)
    return links,selected,gaps


def read_link(reporting,pid,link,privacy):
    validate_links([link],pid)
    pin=link['ref'];actual=reporting.pin(pid,pin['artifact_id'],pin['commit_id'])
    require(actual==pin,'Pinned input report differs or is unavailable')
    files=reporting.artifacts.projects.repository(pid).snapshot(pin['commit_id']);entities=validate_snapshot(files)
    outputs=published_outputs(pid,pin['commit_id'],files,entities,records(files,entities),selected=pin['artifact_id'],include_content=True)
    require(len(outputs)==1 and outputs[0].get('processing_id')==link['task_id'] and outputs[0].get('run_id')==link['run_id'],
            'Input report creator or edition differs')
    require(PRIVACY[privacy]>=PRIVACY[entities[pin['artifact_id']]['privacy']],'Pinned report input lowers privacy')
    return outputs[0]


def approval(markdown,pools,links,gaps=()):
    from spikes.reporting_schema import digest,encoded
    if gaps:return digest(encoded([markdown,pools,links,gaps]))
    return digest(encoded([markdown,pools,links])) if links else digest(encoded([markdown,pools]))


def link_keys(links):
    return sorted((link['task_id'],link['ref']['artifact_id'],link['ref']['sha256']) for link in links)


def freshness(links,outputs):
    """Conservative transitive diagnostics; never edits or republishes editions."""
    by_id={o['id']:o for o in outputs};by_run={o['run_id']:o for o in outputs if o.get('run_id')}
    corrected={}
    for output in outputs:
        parent=output.get('reprocess_of');seen=set()
        while parent and parent not in seen:
            seen.add(parent);corrected.setdefault(parent,set()).add(output['id'])
            old=by_run.get(parent);parent=old.get('reprocess_of') if old else None
    def stale(link,seen):
        pin=link.get('ref',{});id_=pin.get('artifact_id');current=by_id.get(id_)
        if corrected.get(link.get('run_id')):return True
        if not current:return False  # absence is unknown, not evidence of correction
        if id_ in seen:return True
        if corrected.get(link.get('run_id')) or current['report_ref']['sha256']!=pin.get('sha256'):return True
        return any(stale(child,seen|{id_}) for child in current.get('report_inputs',[]) if isinstance(child,dict))
    return [dict(link,title=by_id.get(link['ref']['artifact_id'],{}).get('title','Historické vydání'),
                 in_current_catalog=link['ref']['artifact_id'] in by_id,
                 corrected_by=sorted(corrected.get(link['run_id'],set())),potentially_stale=stale(link,set())) for link in links]


def expected_slots(schedule,since,until):
    """Closed source slots using the same calendar as the existing worker."""
    from spikes.monitoring_evidence import next_processing
    from spikes.composable_monitoring import processing_slot
    slots=set();cursor=since-0.001;last=processing_slot(schedule,cursor)
    while True:
        candidate=next_processing(schedule,cursor,last)
        if candidate is None or candidate>until:break
        last=processing_slot(schedule,candidate);slots.add(last);cursor=candidate+0.001
        require(len(slots)<=3651,'Report coverage window exceeds limit')
    return slots


def coverage_time(output):
    """A scheduled catch-up belongs to its source slot, even if built later."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from spikes.composable_monitoring import processing_slot
    from spikes.monitoring_evidence import next_processing
    schedule=output.get('source_schedule')
    if not schedule or schedule['kind']=='manual':return output['period_end']
    slot=processing_slot(schedule,output['period_end'])
    if slot is None:return output['period_end']
    start=datetime.fromisoformat(slot).replace(tzinfo=ZoneInfo(schedule['timezone'])).timestamp()-0.001
    return next_processing(schedule,start,processing_slot(schedule,start))


def validate_gaps(gaps):
    from datetime import date
    require(isinstance(gaps,list) and len(gaps)<=128,'Invalid report coverage gaps')
    seen=set()
    for gap in gaps:
        fields(gap,'task_id periods missing_all');uuid(gap['task_id'])
        require(gap['task_id'] not in seen,'Duplicate report coverage task');seen.add(gap['task_id'])
        require(type(gap['missing_all']) is bool and isinstance(gap['periods'],list) and len(gap['periods'])<=3651,'Invalid missing report periods')
        require(gap['missing_all'] or gap['periods'],'Empty coverage gap')
        require(all(isinstance(period,str) and len(period)==10 and date.fromisoformat(period).isoformat()==period for period in gap['periods']),'Invalid missing report date')
        require(len(set(gap['periods']))==len(gap['periods']),'Duplicate missing report date')
    require(len(encoded(gaps))<=256*1024,'Report coverage metadata exceeds limit')


def coverage_notice(gaps,blocks):
    if not gaps:return ''
    names={b['id']:b['value']['title'] for b in blocks}
    lines=['## Neúplné pokrytí vstupních zpráv','',
        'Přehled vychází pouze z dostupných podkladů. Chybějící vydání neznamená, že v daném období nebyly žádné události.','']
    for gap in gaps:
        detail=', '.join(gap['periods']) if gap['periods'] else 'v požadovaném období není žádné vydání'
        lines.append('- '+names.get(gap['task_id'],gap['task_id'])+': '+detail)
    return '\n'.join(lines)+'\n\n'
