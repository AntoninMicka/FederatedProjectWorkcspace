# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Immutable RSS finding state; operational poll state belongs to the run journal."""
from spikes.metadata import require, uuid
from spikes.reporting_schema import choice, fields, hex_id, ref, sequence, text
from spikes.source_connectors import validate_item

STAGES={'captured','selected','pending','processed','discarded','failed','unknown'}


def validate_finding(value):
    fields(value,'schema definition_ref input_id item aliases entry_sha256 stage selection change_reason raw_ref')
    ref(value['definition_ref']);uuid(value['input_id']);validate_item(value['item'])
    require(value['item']['connector']=='rss-atom','RSS finding requires an RSS item')
    require(value['item']['imported_at'] is not None,'Finding import time is required')
    sequence(value['aliases'],text,minimum=1);hex_id(value['entry_sha256'])
    require(all(a.startswith(('id:','url:')) for a in value['aliases']),'Invalid RSS aliases')
    choice(value['stage'],STAGES);text(value['change_reason'])
    names='decision reason filter_revision filter_sha256'
    if isinstance(value['selection'],dict) and 'evaluation_ref' in value['selection']:
        ref(value['selection']['evaluation_ref'],batch=True)
        require(value['selection']['filter_sha256']==value['selection']['evaluation_ref']['sha256'], 'Evaluation audit hash differs')
        names+=' evaluation_ref'
    if isinstance(value['selection'],dict) and 'audit' in value['selection']:
        from spikes.monitoring_filters import validate_pipeline, ENGINE
        from spikes.reporting_schema import digest, encoded
        audit=value['selection']['audit'];fields(audit,'engine pipeline pipeline_sha256 items_sha256 previous_sha256 languages input_head result')
        validate_pipeline(audit['pipeline'])
        require(audit['engine']==ENGINE and audit['pipeline_sha256']==digest(encoded(audit['pipeline'])), 'Invalid selection audit')
        require(value['selection']['filter_sha256']==audit['pipeline_sha256'] and
                value['selection']['filter_revision']==audit['pipeline']['revision'], 'Selection differs from pipeline')
        for key in ('items_sha256','previous_sha256'):hex_id(audit[key])
        hex_id(audit['input_head'],True)
        require(isinstance(audit['languages'],dict),'Invalid language audit')
        result=audit['result'];fields(result,'item_id decision reason steps assessment handoff')
        require(result['item_id']==value['item']['id'],'Selection audit belongs to another item')
        choice(result['decision'],{'selected','discarded','waiting','error'});text(result['reason'])
        require(result['assessment'] is None and type(result['handoff']) is bool,'Automatic capture cannot claim assessment')
        require(isinstance(result['steps'],list) and len(result['steps'])<=16,'Invalid selection trace')
        for step in result['steps']:
            fields(step,'id kind outcome reason');text(step['id']);text(step['kind']);text(step['reason'])
            choice(step['outcome'],{'selected','discarded','waiting','error'})
        require([(s['id'],s['kind']) for s in result['steps']]==
                [(s['id'],s['kind']) for s in audit['pipeline']['steps'][:len(result['steps'])]],'Selection trace differs from pipeline order')
        require(result['steps'] and result['steps'][-1]['outcome']==result['decision'] and
                all(s['outcome']=='selected' for s in result['steps'][:-1]),'Invalid selection trace outcomes')
        expected=result['decision'] if result['decision'] in {'selected','discarded'} else 'not-evaluated'
        require(value['selection']['decision']==expected,'Selection audit decision differs')
        names+=' audit'
    fields(value['selection'],names)
    choice(value['selection']['decision'],{'not-evaluated','selected','discarded'})
    text(value['selection']['reason']);text(value['selection']['filter_revision']);hex_id(value['selection']['filter_sha256'])
    if value['stage'] in {'selected','pending','processed'}:
        require(value['selection']['decision']=='selected','Processing requires selected input')
    if value['stage']=='discarded':require(value['selection']['decision']=='discarded','Missing discard decision')
    ref(value['raw_ref'],batch=True)
    require(value['raw_ref']['sha256']==value['item']['provenance']['raw_sha256'],'Finding raw provenance mismatch')
