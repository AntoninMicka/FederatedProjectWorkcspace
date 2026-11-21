# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Pool sidecar of the existing signed native content exchange (v3)."""
import json
from pathlib import Path

from spikes.metadata import require
from spikes.message_pools import MessagePools, MAX_PAYLOAD, validate_entry
from spikes.reporting_schema import encoded, PRIVACY


def export(node, project_id, *, read_only=False):
    node = Path(node).absolute()
    if not (node.parent/('.'+node.name+'.reporting-runs')/'message-pools').exists(): return b''
    rows = (MessagePools.export_readonly(node, project_id) if read_only else
            MessagePools(node).export(project_id, transferable=True))
    return encoded(rows) if rows else b''


def validate(raw, project_id):
    require(isinstance(raw, bytes) and len(raw) <= MAX_PAYLOAD, 'Pool payload exceeds limit')
    rows = json.loads(raw)
    require(isinstance(rows, list) and len(rows) <= 20000, 'Invalid pool payload')
    for row in rows:
        validate_entry(row, project_id)
        privacy = row['value'].get('privacy') if row['kind'] in {'membership','activation','report-outcome'} else row['value'].get('item', {}).get('privacy')
        require(privacy != 'local-only', 'Pool sync contains local-only data')
    require(len({r['id'] for r in rows}) == len(rows), 'Duplicate pool sync entry')
    return rows


def prepare(node,project_id,raw,*,operation_id,source_node_id=None,checkpoint=lambda stage:None):
    """Durable reference-only projection; original sync intent owns replay."""
    if operation_id is None:return
    from spikes.pool_input_guard import manifest
    from spikes.monitoring import ident
    from spikes.message_pools import stamp
    from spikes.reporting_schema import digest,moment
    rows=validate(raw,project_id);expected=manifest(rows);store=MessagePools(node)
    key=ident(operation_id,'pool-received');payload_hash=digest(raw)
    with store.db() as db:
        old=db.execute('SELECT state,document FROM block_jobs WHERE id=? AND project=?',(key,project_id)).fetchone()
        prior=json.loads(old[1]) if old else None
        if prior and prior.get('payload_sha256'):
            require(prior['payload_sha256']==payload_hash and prior.get('source_node_id')==source_node_id,
                    'Pool receipt ID belongs to another payload')
            return
        intent=dict(kind='pool-sync',operation_id=operation_id,source_node_id=source_node_id,
            payload_sha256=payload_hash,expected=expected,
            received_at=(prior or {}).get('received_at',stamp(store.clock())),
            pool_ids=sorted({r['pool_id'] for r in expected}),
            expires_at=max([store.clock()+30*86400]+[moment(r['expires_at']).timestamp() for r in expected]))
        db.execute('INSERT OR REPLACE INTO block_jobs VALUES(?,?,?,?,NULL)',(key,project_id,'prepared',encoded(intent)))
    checkpoint('pool-receive-prepared')


def _not_held(node, project_id, rows):
    """Rows this node does not already hold byte-for-byte (AUDIT-B7-T1).

    A held entry passed provenance validation when it entered: local creation
    or an earlier verified receive. Entries are immutable and their pins name
    immutable commits, so re-validating them on every sync only repeats the
    same Git snapshot work. _merge still checks links and immutability over
    the whole payload inside its transaction.
    """
    with MessagePools(node).db() as db:
        held = {row[0]: row[1] for row in db.execute(
            'SELECT id,document FROM pool_entries WHERE project=?', (project_id,))}
    return [row for row in rows
            if row['id'] not in held or json.loads(held[row['id']]) != row]


def apply(node, project_id, raw, *, checkpoint=lambda stage: None, operation_id=None, source_node_id=None):
    from spikes.reporting import Reporting
    rows = validate(raw, project_id)
    prepare(node,project_id,raw,operation_id=operation_id,source_node_id=source_node_id,checkpoint=checkpoint)
    fresh = _not_held(node, project_id, rows)
    # Provenance needs the validated reporting snapshot only for new rows that
    # reference definitions; it is the expensive part (every pinned commit).
    if any(row['kind'] in {'activation', 'report-outcome', 'membership'} for row in fresh):
        data = Reporting(node).read(project_id)
        records = {r['revision_id']: r for r in data['records']}
    else:
        records = {}
    blocks = {r['entity_id']: r for r in records.values() if r['type'] == 'MonitoringBlock'}
    items = {r['id']: r['value']['item'] for r in rows if r['kind'] == 'item'}
    checked_pins={}
    for row in fresh:
        v = row['value']
        if row['kind'] in {'activation','report-outcome'}:
            pin=v['block_ref'];definition=records.get(pin['artifact_id'])
            require(definition and definition['type']=='MonitoringBlock' and definition['entity_id']==v['block_id'],
                    'Shared monitoring definition is unavailable')
            require(PRIVACY[v['privacy']]>=PRIVACY[definition['privacy']] and pin['project_id']==project_id,
                    'Shared monitoring privacy or project differs')
            from spikes.reporting import Reporting as _Reporting
            # Pin validation checks the historical bytes and cross-project access.
            key=(pin['artifact_id'],pin['commit_id'])
            if key not in checked_pins:checked_pins[key]=_Reporting(node).pin(project_id,*key)
            actual=checked_pins[key]
            require(actual==pin,'Shared monitoring pin differs')
            if row['kind']=='activation':
                require(definition['value']['kind'] in {'source','processing'},'Invalid activation target')
                require(definition['value']['kind']!='source' or definition['value']['config']['connector']=='rss-atom','Only RSS sources permit periodic intake')
            else:
                require(definition['value']==v['intent']['block']['value'],'Shared report definition differs')
                from spikes.monitoring_report_inputs import read_link
                for link in v['intent'].get('report_inputs',[]):read_link(_Reporting(node),project_id,link,v['privacy'])
                if v['state']=='published':
                    published=v['result']['report_ref'];key=(published['artifact_id'],published['commit_id'])
                    if key not in checked_pins:checked_pins[key]=_Reporting(node).pin(project_id,*key)
                    require(checked_pins[key]==published,'Published outcome artifact is unavailable or differs')
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
    with pool_store.db() as db:
        pool_store._merge(db,project_id,rows,checkpoint=checkpoint)
        if operation_id is not None:
            from spikes.monitoring import ident
            changed=db.execute("UPDATE block_jobs SET state='completed' WHERE id=? AND project=?",
                               (ident(operation_id,'pool-received'),project_id))
            require(changed.rowcount==1,'Pool receipt is unavailable')
        checkpoint('pool-receive-confirmed')
    checkpoint('pool-committed')
