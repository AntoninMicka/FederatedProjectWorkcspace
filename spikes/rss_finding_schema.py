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
    fields(value['selection'],'decision reason filter_revision filter_sha256')
    choice(value['selection']['decision'],{'not-evaluated','selected','discarded'})
    text(value['selection']['reason']);text(value['selection']['filter_revision']);hex_id(value['selection']['filter_sha256'])
    if value['stage'] in {'selected','pending','processed'}:
        require(value['selection']['decision']=='selected','Processing requires selected input')
    if value['stage']=='discarded':require(value['selection']['decision']=='discarded','Missing discard decision')
    ref(value['raw_ref'],batch=True)
    require(value['raw_ref']['sha256']==value['item']['provenance']['raw_sha256'],'Finding raw provenance mismatch')
