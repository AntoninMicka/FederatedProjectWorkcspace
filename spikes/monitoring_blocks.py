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
    fields(value, 'schema kind title config'+(' deleted' if 'deleted' in value else ''))
    if 'deleted' in value: require(value['deleted'] is True, 'Invalid monitoring deletion marker')
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
            require(not records[p['artifact_id']]['value'].get('deleted'), 'Deleted monitoring block cannot be edited or restored implicitly')
            require(records[p['artifact_id']]['value']['kind'] == row['value']['kind'],
                    'Monitoring block cannot change kind')
        if row['value'].get('deleted'):
            require(len(row['previous']) == 1, 'Deletion requires one exact predecessor')
            before = records[row['previous'][0]['artifact_id']]
            require({k:v for k,v in row['value'].items() if k!='deleted'} == before['value']
                    and row['privacy'] == before['privacy'], 'Deletion must preserve the original definition')
    tips = {id_: row for id_, row in tips.items() if not row['value'].get('deleted')}
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

    def read(self, project_id, *, _snapshot=None):
        from spikes.reporting import pinned
        data, files, entities = (_snapshot if _snapshot is not None else
                                self.reporting.read_snapshot(project_id, read_only=True))
        tips = validate_blocks({r['revision_id']: r for r in data['records']})
        rows = []
        for id_, row in tips.items():
            direct = [i for i, r in tips.items() if any(d == id_ for d, _ in dependencies(r['value']))]
            tasks = []
            for i, r in tips.items():
                if r['value']['kind'] == 'task' and id_ in dependency_closure(i, tips):
                    tasks.append(i)
            rows.append(dict(id=id_, privacy=row['privacy'], value=deepcopy(row['value']),
                ref=pinned(project_id, data['commit_id'], row['revision_id'], files, entities),
                used_by=sorted(set(direct+tasks)), tasks=sorted(tasks),
                resolved_ids=dependency_closure(id_, tips)))
        return dict(project_id=project_id, commit_id=data['commit_id'], blocks=rows)

    def save(self, project_id, base_head, blocks, operation_id, *, checkpoint=lambda stage: None, _delete=False):
        require(isinstance(blocks, list) and 1 <= len(blocks) <= 32, 'Expected 1..32 block edits')
        specs = []
        for b in blocks:
            fields(b, 'id previous privacy value'); uuid(b['id']); validate_block(b['value'])
            require(_delete or not b['value'].get('deleted'), 'Use the confirmed block deletion action')
            specs.append(dict(type='MonitoringBlock', entity_id=b['id'], previous=b['previous'],
                              privacy=b['privacy'], value=deepcopy(b['value'])))
        return self.reporting.apply(dict(project_id=project_id, base_head=base_head, records=specs),
                                    operation_id, confirm=_delete, checkpoint=checkpoint)
