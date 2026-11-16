# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Report names and read-only output projection of an already validated Git head."""
from datetime import datetime, timezone
import json
import math
from zoneinfo import ZoneInfo
from spikes.reporting_schema import digest

BUILT_PREFIX='fpw-output-built-at:'
AUDIT_MARKER='\n\n<!-- Frozen monitoring input references\n'
PRESENTATION_SOURCE='fpw-report-presentation-v1:'


def presentation_source(metadata):
    """Read provenance only; metadata never authorizes a write or external effect."""
    from spikes.reporting_schema import ref
    from spikes.metadata import parse_json
    description=metadata.get('description','')
    if (not isinstance(description,str) or 'monitoring-derived-presentation' not in metadata.get('tags',[])
            or not description.startswith(PRESENTATION_SOURCE)):return None
    try:
        source=parse_json(description[len(PRESENTATION_SOURCE):].encode());ref(source)
        return source
    except (ValueError,KeyError,TypeError):return None


def derived_presentations(pid,files,entities,records):
    from spikes.presentation_documents import decode_deck
    superseded={p['artifact_id'] for r in records.values() if r['type']=='ReportSnapshot' for p in r['previous']}
    result=[]
    for id_,meta in entities.items():
        source=presentation_source(meta)
        if source is None or source['project_id']!=pid or not meta.get('file'):continue
        path='artifacts/'+id_+'/'+meta['file']
        try:decode_deck(files[path].decode())
        except (ValueError,KeyError,TypeError,UnicodeDecodeError):continue
        current=entities.get(source['artifact_id'],{})
        current_path='artifacts/'+source['artifact_id']+'/'+current.get('file','')
        available=current_path in files
        stale=(not available or digest(files[current_path])!=source['sha256']
               or source['artifact_id'] in superseded)
        result.append(dict(artifact_id=id_,title=meta['title'],source_ref=source,
                           source_available=available,potentially_stale=stale))
    return sorted(result,key=lambda r:r['artifact_id'])


def safe_built_at(value):
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:return None
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:return None


def output_title(name,built_at,zone='UTC'):
    stamp=datetime.fromisoformat(built_at.replace('Z','+00:00')).astimezone(ZoneInfo(zone))
    return name.strip()[:150]+' · '+stamp.strftime('%Y-%m-%d %H:%M:%S %Z')


def published_outputs(pid,head,files,entities,records,*,selected=None,include_content=False,include_intent=False):
    from spikes.reporting import pinned
    result=[]
    for row in records.values():
        if row['type']!='ReportSnapshot' or selected is not None and row['revision_id']!=selected:continue
        value=row['value'];meta=entities[row['revision_id']];description=meta.get('description','')
        built_at=safe_built_at(description[len(BUILT_PREFIX):]) if description.startswith(BUILT_PREFIX) else None
        task=records.get(value['task_ref']['artifact_id'])
        base=task['value']['title'] if task else 'Zpráva'
        title=meta['title'] if built_at else output_title(base,row['recorded_at'],value['period']['timezone'])+' (vydáno)'
        result.append(dict(id=row['revision_id'],artifact_id=row['revision_id'],title=title,built_at=built_at,
            issued_at=row['recorded_at'],kind='snapshot',run_id=value['generation']['run_id'],state='completed',**({'markdown':files[value['markdown']['path']].decode()} if include_content else {}),
            report_ref=pinned(pid,head,row['revision_id'],files,entities)))
    for id_,meta in entities.items():
        if selected is not None and id_!=selected:continue
        if meta['kind']!='document' or not meta.get('file','').endswith('.md'):continue
        path='artifacts/'+id_+'/'+meta['file'];data=files[path]
        tagged='monitoring-output' in meta.get('tags',[])
        if AUDIT_MARKER.encode() not in data and not tagged:continue
        try:raw=data.decode()
        except UnicodeDecodeError:continue
        body=raw;audit={};source_schedule=None
        if AUDIT_MARKER in raw:
            clean,tail=raw.rsplit(AUDIT_MARKER,1)
            try:
                if not tail.rstrip().endswith('-->'):raise ValueError('Malformed audit')
                candidate=json.loads(tail.rstrip()[:-3].strip());block=candidate['block'];pin=block['ref']
                record=records[pin['artifact_id']]
                if (candidate['project_id']!=pid or pin['project_id']!=pid or record['type']!='MonitoringBlock' or
                    record['value']['kind']!='processing' or record['entity_id']!=block['id'] or
                    digest(files[pin['path']])!=pin['sha256']):raise ValueError('Unavailable output provenance')
                body=clean;audit=candidate;source_schedule=record['value']['config']['schedule']
            except (ValueError,KeyError,TypeError):
                if not tagged:continue
        run_id=audit.get('run_id')
        if run_id is not None:
            from spikes.monitoring import ident
            try:
                if ident(run_id,'report')!=id_:raise ValueError('Output identity differs')
            except (ValueError,TypeError,AttributeError):
                if not tagged:continue
                run_id=None
        description=meta.get('description','')
        built_at=(safe_built_at(description[len(BUILT_PREFIX):]) if description.startswith(BUILT_PREFIX) else None) or safe_built_at(audit.get('built_at'))
        title=meta['title'] if built_at else output_title(meta['title'],meta['created_at'])+' (vydáno)'
        until = audit.get('protection_until')
        if until is None and built_at:
            until = datetime.fromisoformat(built_at.replace('Z','+00:00')).timestamp()+3600
        if type(until) not in {int,float} or not math.isfinite(until) or until < 0: until = None
        result.append(dict(id=id_,artifact_id=id_,title=title,built_at=built_at,issued_at=meta['created_at'],
            kind='block-report',run_id=run_id,processing_id=audit.get('block',{}).get('id'),source_schedule=source_schedule,period_end=audit.get('period_end'),reprocess_of=audit.get('reprocess_of'),report_inputs=audit.get('report_inputs',[]),executor_node_id=audit.get('executor_node_id'),state='completed',reprocess_until=until if audit else None,
            **({'reprocess_intent':audit} if include_intent else {}),
            **({'markdown':body} if include_content else {}),report_ref=pinned(pid,head,id_,files,entities)))
    if selected is None:
        from spikes.monitoring_report_inputs import freshness
        for output in result:
            output['potentially_stale']=any(link['potentially_stale'] for link in freshness(output.get('report_inputs',[]),result))
    presentations=derived_presentations(pid,files,entities,records)
    for output in result:
        output['presentations']=[p for p in presentations if p['source_ref']['artifact_id']==output['id']]
    return sorted(result,key=lambda r:(r['built_at'] or r['issued_at'],r['id']),reverse=True)
