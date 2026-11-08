# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Composable monitoring definitions. No effects or runtime grants on save/sync."""
from copy import deepcopy
from datetime import time
from zoneinfo import ZoneInfo

from spikes.metadata import require, uuid
from spikes.reporting_schema import PRIVACY, encoded, fields, sequence, text

KINDS = ('source', 'filter', 'pool', 'processing', 'task')


def ids(value):
    sequence(value, uuid)


def dependencies(value):
    c = value['config']; kind = value['kind']
    if kind == 'filter':
        return [(i, 'source') for i in c['source_ids']] + [(c['pool_id'], 'pool')]
    if kind == 'processing':
        return [(i, 'pool') for i in c['pool_ids']] + [(i, 'source') for i in c['search_ids']]
    if kind == 'task':
        return [(i, k) for k in KINDS[:-1] for i in c[k+'_ids']]
    return []


def validate_block(value):
    fields(value, 'schema kind title config')
    require(value['schema'] == 'fpw-reporting-block-v1' and value['kind'] in KINDS,
            'Unknown monitoring block')
    text(value['title']); require(len(value['title']) <= 150, 'Block title exceeds limit')
    c = value['config']; kind = value['kind']
    if kind == 'source':
        fields(c, 'connector locator poll_seconds terms retention')
        require(c['connector'] in {'rss-atom', 'web-search'}, 'Unsupported source connector')
        for k in ('locator', 'terms', 'retention'):
            text(c[k]); require(len(c[k]) <= 4000, 'Source configuration exceeds limit')
        if c['connector'] == 'rss-atom':
            from spikes.source_collector import public_url
            public_url(c['locator'])
            require(type(c['poll_seconds']) is int and 60 <= c['poll_seconds'] <= 604800,
                    'RSS interval must be 60..604800 seconds')
        else:
            require(c['poll_seconds'] is None, 'Web search is on demand only')
    elif kind == 'filter':
        fields(c, 'source_ids pool_id pipeline'); ids(c['source_ids']); uuid(c['pool_id'])
        require(c['source_ids'], 'Choose input channels')
        from spikes.monitoring_filters import validate_pipeline, CHEAP
        validate_pipeline(c['pipeline'])
        require(all(s['kind'] in CHEAP | {'handoff'} for s in c['pipeline']['steps']),
                'Collection filters require explicit cheap rules')
    elif kind == 'pool':
        fields(c, 'retention_days')
        require(type(c['retention_days']) is int and 1 <= c['retention_days'] <= 3650,
                'Pool retention must be 1..3650 days')
    elif kind == 'processing':
        fields(c, 'pool_ids search_ids instructions mode schedule lookback_days node_id')
        ids(c['pool_ids']); ids(c['search_ids']); text(c['instructions']); uuid(c['node_id'])
        require(c['pool_ids'] or c['search_ids'], 'Choose pools or web searches')
        require(c['mode'] in {'deterministic', 'llm'}, 'Unknown processing mode')
        require(type(c['lookback_days']) is int and 1 <= c['lookback_days'] <= 3650,
                'Invalid processing window')
        fields(c['schedule'], 'kind time timezone'); ZoneInfo(c['schedule']['timezone'])
        require(c['schedule']['kind'] in {'manual', 'daily'}, 'Unknown processing schedule')
        require(isinstance(c['schedule']['time'], str) and
                time.fromisoformat(c['schedule']['time']).strftime('%H:%M') == c['schedule']['time'],
                'Choose HH:MM processing time')
    else:
        fields(c, 'source_ids filter_ids pool_ids processing_ids instructions')
        for k in KINDS[:-1]: ids(c[k+'_ids'])
        text(c['instructions']); require(c['processing_ids'], 'Choose at least one processing block')
    require(len(encoded(value)) <= 32*1024, 'Monitoring block exceeds limit')
    return value


def validate_blocks(records):
    rows = [r for r in records.values() if r['type'] == 'MonitoringBlock']
    parents = {p['artifact_id'] for r in rows for p in r['previous']}
    tips = {r['entity_id']: r for r in rows if r['revision_id'] not in parents}
    for row in rows:
        for p in row['previous']:
            require(records[p['artifact_id']]['value']['kind'] == row['value']['kind'],
                    'Monitoring block cannot change kind')
    for row in tips.values():
        v = validate_block(row['value'])
        for id_, kind in dependencies(v):
            require(id_ in tips and tips[id_]['value']['kind'] == kind, 'Missing or wrong monitoring dependency')
            if not (v['kind'] == 'filter' and kind == 'pool'):
                require(PRIVACY[row['privacy']] >= PRIVACY[tips[id_]['privacy']], 'Monitoring dependency lowers privacy')
        c = v['config']
        if v['kind'] == 'filter':
            require(all(tips[i]['value']['config']['connector'] == 'rss-atom' for i in c['source_ids']),
                    'Filters require periodic channels, not on-demand search')
            require(PRIVACY[tips[c['pool_id']]['privacy']] >= PRIVACY[row['privacy']], 'Pool lowers filter privacy')
        if v['kind'] == 'processing':
            require(all(tips[i]['value']['config']['connector'] == 'web-search' for i in c['search_ids']),
                    'Processing searches must use web-search sources')
    return tips


def dependency_closure(identity, values):
    selected = set(); pending = [identity]
    while pending:
        current = pending.pop()
        for id_, _ in dependencies(values[current]['value']):
            if id_ not in selected:
                selected.add(id_); pending.append(id_)
    return sorted(selected)


class MonitoringBlocks:
    def __init__(self, node):
        from spikes.reporting import Reporting
        self.reporting = Reporting(node)

    def read(self, project_id):
        data = self.reporting.read(project_id)
        tips = validate_blocks({r['revision_id']: r for r in data['records']})
        rows = []
        for id_, row in tips.items():
            direct = [i for i, r in tips.items() if any(d == id_ for d, _ in dependencies(r['value']))]
            tasks = []
            for i, r in tips.items():
                if r['value']['kind'] == 'task' and id_ in dependency_closure(i, tips):
                    tasks.append(i)
            rows.append(dict(id=id_, privacy=row['privacy'], value=deepcopy(row['value']),
                ref=self.reporting.pin(project_id, row['revision_id'], data['commit_id']),
                used_by=sorted(set(direct+tasks)), tasks=sorted(tasks),
                resolved_ids=dependency_closure(id_, tips)))
        return dict(project_id=project_id, commit_id=data['commit_id'], blocks=rows)

    def save(self, project_id, base_head, blocks, operation_id, *, checkpoint=lambda stage: None):
        require(isinstance(blocks, list) and 1 <= len(blocks) <= 32, 'Expected 1..32 block edits')
        specs = []
        for b in blocks:
            fields(b, 'id previous privacy value'); uuid(b['id']); validate_block(b['value'])
            specs.append(dict(type='MonitoringBlock', entity_id=b['id'], previous=b['previous'],
                              privacy=b['privacy'], value=deepcopy(b['value'])))
        return self.reporting.apply(dict(project_id=project_id, base_head=base_head, records=specs),
                                    operation_id, checkpoint=checkpoint)
