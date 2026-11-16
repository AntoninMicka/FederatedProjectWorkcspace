# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""User documents are distinct from monitoring storage and message pools."""
import json
from spikes.reporting_schema import SCHEMA


def document_ids(files, entities):
    hidden = set()
    for id_, meta in entities.items():
        path = 'artifacts/' + id_ + '/' + meta.get('file', '')
        raw = files.get(path, b'')
        if 'rss-capture' in meta.get('tags', []): hidden.add(id_)
        if raw.startswith(b'<!-- fpw-monitoring-watch-v1 -->'):
            hidden.add(id_)
        if (meta.get('kind') not in {'document','snapshot'} or
                SCHEMA not in meta.get('tags', []) or meta.get('file') != 'record.json'):
            continue
        value = json.loads(raw)
        if not isinstance(value,dict) or value.get('schema') != SCHEMA:
            continue
        hidden.add(id_)
        if value.get('type') == 'SourceFinding' and isinstance(value.get('value'),dict):
            capture = value['value'].get('raw_ref')
            if isinstance(capture,dict) and isinstance(capture.get('artifact_id'),str):
                hidden.add(capture['artifact_id'])
    artifacts = {path.split('/')[1] for path in files if path.startswith('artifacts/')}
    return (set(entities) & artifacts) - hidden
