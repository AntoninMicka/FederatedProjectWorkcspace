# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Pool sidecar of the existing signed native content exchange (v3)."""
import json
from pathlib import Path

from spikes.metadata import require
from spikes.message_pools import MessagePools, MAX_PAYLOAD, validate_entry
from spikes.reporting_schema import encoded, PRIVACY


def export(node, project_id):
    node = Path(node).absolute()
    if not (node.parent/('.'+node.name+'.reporting-runs')/'message-pools').exists(): return b''
    rows = MessagePools(node).export(project_id, transferable=True)
    return encoded(rows) if rows else b''


def validate(raw, project_id):
    require(isinstance(raw, bytes) and len(raw) <= MAX_PAYLOAD, 'Pool payload exceeds limit')
    rows = json.loads(raw)
    require(isinstance(rows, list) and len(rows) <= 20000, 'Invalid pool payload')
    for row in rows:
        validate_entry(row, project_id)
        privacy = row['value'].get('privacy') if row['kind'] == 'membership' else row['value'].get('item', {}).get('privacy')
        require(privacy != 'local-only', 'Pool sync contains local-only data')
    require(len({r['id'] for r in rows}) == len(rows), 'Duplicate pool sync entry')
    return rows


def apply(node, project_id, raw, *, checkpoint=lambda stage: None, operation_id=None, source_node_id=None):
    from spikes.reporting import Reporting
    rows = validate(raw, project_id)
    data = Reporting(node).read(project_id)
    records = {r['revision_id']: r for r in data['records']}
    blocks = {r['entity_id']: r for r in records.values() if r['type'] == 'MonitoringBlock'}
    items = {r['id']: r['value']['item'] for r in rows if r['kind'] == 'item'}
    for row in rows:
        v = row['value']
        if row['kind'] == 'membership':
            pool = blocks.get(v['pool_id']); filter_ = records.get(v['filter_revision'])
            require(pool and pool['value']['kind'] == 'pool' and filter_ and
                    filter_['type'] == 'MonitoringBlock' and filter_['value']['kind'] == 'filter' and
                    filter_['entity_id'] == v['filter_id'] and filter_['value']['config']['pool_id'] == v['pool_id'],
                    'Pool sync definition provenance is unavailable')
            require(pool['privacy'] == v['privacy'] and v['item_entry'] in items,
                    'Pool membership privacy or content differs')
            item = items[v['item_entry']]
            require(item['source_id'] in filter_['value']['config']['source_ids'], 'Pool filter did not use this source')
            require(PRIVACY[pool['privacy']] >= PRIVACY[item['privacy']], 'Pool sync lowers privacy')
    pool_store = MessagePools(node)
    pool_store.merge(project_id, rows, checkpoint=checkpoint)
    if operation_id is not None:
        from spikes.monitoring import ident
        from spikes.message_pools import stamp
        intent = dict(kind='pool-sync', source_node_id=source_node_id, received_at=stamp(pool_store.clock()),
            pool_ids=sorted({r['value']['pool_id'] for r in rows if r['kind']=='membership'}),
            expires_at=pool_store.clock()+30*86400)
        with pool_store.db() as db:
            db.execute('INSERT OR IGNORE INTO block_jobs VALUES(?,?,?,?,NULL)',
                (ident(operation_id,'pool-received'), project_id,'completed',encoded(intent)))
