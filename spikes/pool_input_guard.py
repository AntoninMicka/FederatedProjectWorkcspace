# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read known unfinished pool imports without initializing or replaying sync."""
import json
import os
from pathlib import Path
import stat

from spikes.metadata import ValidationError, require
from spikes.reporting_schema import moment
from spikes.sqlite_ownership import sqlite_connection


class IncompletePoolTransfer(ValidationError):
    pass


def manifest(rows):
    items={r['id']:r['value']['item'] for r in rows if r['kind']=='item'}
    observed={}
    for row in rows:
        if row['kind']=='observation':
            v=row['value'];observed[v['item_entry']]=min(observed.get(v['item_entry'],v['observed_at']),v['observed_at'])
    expected={}
    for row in rows:
        if row['kind']!='membership':continue
        v=row['value'];item=items.get(v['item_entry'],{})
        key=(v['pool_id'],v['item_entry'],v['expires_at'])
        expected[key]=dict(pool_id=v['pool_id'],item_entry=v['item_entry'],expires_at=v['expires_at'],
            published_at=item.get('published_at'),observed_at=observed.get(v['item_entry'],v['selected_at']))
    return [expected[k] for k in sorted(expected)]


def _legacy_pending(node,pid,known):
    """Recover pre-upgrade manifests from the original authenticated inbound intent."""
    node=Path(node).absolute();root=node.parent/('.'+node.name+'.network')
    path=root/'federation-content-sync.sqlite'
    if not path.exists():return []
    for p,directory in ((root,True),(path,False)):
        info=p.lstat()
        require(p.resolve()==p and info.st_uid==os.getuid() and not info.st_mode&0o077
                and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink==1),
                'Unsafe content sync journal')
    pending=[]
    with sqlite_connection(path.as_uri()+'?mode=ro',uri=True,timeout=2,resource='Pool input transfer status') as db:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inbound'").fetchone():return []
        candidates=db.execute("SELECT operation_id,envelope FROM inbound WHERE json_extract(envelope,'$.exchange.project_id')=? "
            "AND json_extract(envelope,'$.exchange.pool_size')>0 AND "
            "(response_envelope IS NULL OR json_extract(response_envelope,'$.conflict')=1)",(pid,)).fetchall()
        for operation_id,raw in candidates:
            if operation_id in known:continue
            exchange=json.loads(raw)['exchange'];size=exchange['pool_size']
            # Read only the bounded sidecar, never the potentially large Git bundle.
            from spikes.message_pools import MAX_PAYLOAD
            require(type(size) is int and 0<size<=MAX_PAYLOAD,'Invalid stored pool payload size')
            payload=db.execute('SELECT substr(bundle,length(bundle)-?+1,?) FROM inbound WHERE operation_id=?',
                               (size,size,operation_id)).fetchone()[0]
            from spikes.pool_sync import validate
            pending.append(dict(operation_id=operation_id,expected=manifest(validate(bytes(payload),pid))))
    return pending


def require_available(pools,pid,pool_ids,rows,*,since,until,covered=()):
    if not pool_ids:return
    with pools.read_db() as db:
        receipts=[(state,json.loads(raw)) for state,raw in db.execute(
            "SELECT state,document FROM block_jobs WHERE project=? AND json_extract(document,'$.kind')='pool-sync'",(pid,))]
    known={v['operation_id'] for _,v in receipts if v.get('expected') is not None and v.get('operation_id')}
    pending=[v for state,v in receipts if state!='completed' and v.get('expected')]
    pending.extend(_legacy_pending(pools.scheduler.node,pid,known))
    now=pools.clock();scope=set(pool_ids)
    available={(r['value']['pool_id'],r['value']['item_entry']) for r in rows if r['kind']=='membership'
               and moment(r['value']['expires_at']).timestamp()>now}
    available.update(covered)
    missing=set();operations=set()
    for transfer in pending:
        for expected in transfer['expected']:
            pool=expected['pool_id']
            if pool not in scope or moment(expected['expires_at']).timestamp()<=now:continue
            at=moment(expected['published_at'] or expected['observed_at']).timestamp()
            if at<since or expected['published_at'] and at>until:continue
            if (pool,expected['item_entry']) not in available:
                missing.add(pool);operations.add(transfer['operation_id'])
    if missing:
        raise IncompletePoolTransfer('Neúplný přenos vstupních dat: pool '+', '.join(sorted(missing)[:4])+
            ' (operace '+', '.join(sorted(operations)[:3])+'). Zprávu nelze zpracovat ani vydat jako úplnou; dokončete přenos a spusťte zpracování znovu.')
