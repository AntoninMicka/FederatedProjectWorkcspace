# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Immutable legacy retirement over the existing Reporting/Workspace writer."""
from contextlib import ExitStack
from functools import lru_cache
import json

from spikes.metadata import require, uuid
from spikes.reporting_schema import fields, ref, sequence, PRIVACY, digest


def validate_deletion(value):
    fields(value,'schema sources')
    require(value['schema']=='fpw-reporting-monitoring-deletion-v1','Unknown monitoring deletion')
    def source(item):
        fields(item,'kind id ref')
        require(item['kind'] in {'watch','definition'},'Unknown deleted watch kind')
        uuid(item['id']);ref(item['ref'])
    sequence(value['sources'],source,minimum=1)
    require(len(value['sources'])<=32 and len({s['id'] for s in value['sources']})==len(value['sources']), 'Invalid deletion target list')


def deleted_sources(rows):
    return [s for r in rows.values() if r['type']=='MonitoringDeletion' for s in r['value']['sources']]


def validate_deletions(rows,files,entities):
    from spikes.monitoring import MARKER,validate_watch
    if not any(r['type']=='MonitoringDeletion' for r in rows.values()):return
    watches=[r for r in rows.values() if r['type']=='WatchDefinition']
    parents={p['artifact_id'] for r in watches for p in r['previous']}
    # Resolve tips from all revisions, not the iteration order of record UUIDs.
    watches={r['entity_id']:r for r in rows.values() if r['type']=='WatchDefinition' and r['revision_id'] not in parents}
    seen=set()
    for row in rows.values():
        if row['type']!='MonitoringDeletion':continue
        require(not row['previous'],'Deletion receipt is immutable');validate_deletion(row['value'])
        for s in row['value']['sources']:
            require(s['id'] not in seen,'Watch already deleted');seen.add(s['id'])
            if s['kind']=='definition':
                original=watches.get(s['id'])
                require(original and original['revision_id']==s['ref']['artifact_id'],'Deleted definition changed or target differs')
                privacy=original['privacy']
            else:
                require(s['ref']['artifact_id']==s['id'] and s['ref']['path'] in files,'Deleted watch is missing')
                raw=files[s['ref']['path']]
                require(raw.startswith(MARKER.encode()) and digest(raw)==s['ref']['sha256'],'Deleted legacy definition changed')
                watch=validate_watch(json.loads(raw[len(MARKER):]))
                require(watch['id']==s['id'] and watch['privacy']==entities[s['id']]['privacy'],'Deleted legacy identity/privacy differs');privacy=watch['privacy']
            require(PRIVACY[row['privacy']]>=PRIVACY[privacy],'Deletion receipt lowers privacy')
    for id_,meta in entities.items():
        if id_ in seen or not meta.get('file'):continue
        raw=files.get('artifacts/'+id_+'/'+meta['file'],b'')
        if raw.startswith(MARKER.encode()):
            cfg=validate_watch(json.loads(raw[len(MARKER):]))
            require(not set(cfg['inputs'])&seen,'Deleted watch is still used by another watch')


def deleted_from_files(files):
    ids=set()
    for path,raw in files.items():
        if path.endswith('/record.json') and b'"MonitoringDeletion"' in raw:
            row=json.loads(raw)
            if row.get('type')=='MonitoringDeletion':
                validate_deletion(row['value']);ids.update(s['id'] for s in row['value']['sources'])
    return ids


@lru_cache(maxsize=128)
def deleted_for_head(repo_path,head):
    from spikes.storage import Git
    git=Git(repo_path)
    result=git.run('grep','-l','"type"[[:space:]]*:[[:space:]]*"MonitoringDeletion"',head,'--','artifacts/*/record.json',check=False)
    require(result.returncode in {0,1},'Cannot read monitoring deletion receipts')
    ids=set()
    for path in result.stdout.splitlines():
        row=json.loads(git.run('show',path).stdout)
        if row.get('type')=='MonitoringDeletion':
            validate_deletion(row['value']);ids.update(s['id'] for s in row['value']['sources'])
    return frozenset(ids)


class MonitoringDeletion:
    def __init__(self,monitoring):self.monitoring=monitoring

    def preview(self,pid,kind,id_):
        from spikes.monitoring_definitions import MonitoringDefinitions
        from spikes.monitoring_migration import MonitoringMigration
        from spikes.reporting import pinned
        require(kind in {'watch','definition'},'Unknown watch kind');uuid(id_)
        ws,head,files,entities,rows=self.monitoring._data(pid)
        if kind=='watch':
            cfg=next((w for w in self.monitoring.watches(files,entities) if w['id']==id_),None)
            require(cfg is not None,'Unknown legacy watch')
            source=dict(kind=kind,id=id_,ref=pinned(pid,head,id_,files,entities));title=cfg['name'];privacy=cfg['privacy']
        else:
            view=MonitoringDefinitions(self.monitoring.node).read(pid)
            require(view['commit_id']==head,'Project changed during deletion preview')
            row=next((r for r in view['definitions'] if r['watch_id']==id_),None)
            require(row is not None,'Unknown independent watch')
            source=dict(kind=kind,id=id_,ref=row['definition_ref']);title=row['definition']['title'];privacy=row['privacy']
        blockers=MonitoringMigration(self.monitoring)._pending(pid,{id_},rows)
        # Same semantic checks as publication, before asking for confirmation.
        candidate=dict(type='MonitoringDeletion',previous=[],privacy=privacy,value=dict(schema='fpw-reporting-monitoring-deletion-v1',sources=[source]))
        try:
            proposed=dict(rows);proposed['preview']=candidate
            validate_deletions(proposed,files,entities)
            from spikes.monitoring_definition_schema import validate_graph
            validate_graph(proposed)
        except ValueError as exc:blockers.append(str(exc))
        return dict(base_head=head,sources=[source],title=title,privacy=privacy,blockers=blockers)

    def remove(self,pid,base_head,sources,operation_id,*,confirm,checkpoint=lambda stage:None):
        from spikes.monitoring_migration import MonitoringMigration
        require(confirm is True,'Confirm deletion of the legacy watch')
        value=dict(schema='fpw-reporting-monitoring-deletion-v1',sources=sources);validate_deletion(value)
        m=self.monitoring;m._writable(pid)
        with ExitStack() as stack:
            require(m.lock.acquire(blocking=False),'Monitoring právě pracuje.')
            stack.callback(m.lock.release)
            require(stack.enter_context(m.rss_runtime.locked()),'RSS worker právě pracuje.')
            require(stack.enter_context(m.composable.locked()),'Monitoring právě pracuje.')
            ws,head,files,entities,rows=m._data(pid)
            blockers=MonitoringMigration(m)._pending(pid,{s['id'] for s in sources},rows)
            require(not blockers,'Nejprve vyřešte rozpracovaný nebo neznámý běh sledování.')
            privacy=max((entities[s['ref']['artifact_id']]['privacy'] for s in sources),key=PRIVACY.get)
            return m.reporting.apply(dict(project_id=pid,base_head=base_head,records=[dict(type='MonitoringDeletion',entity_id=None,previous=[],privacy=privacy,value=value)]),operation_id,confirm=True,checkpoint=checkpoint)
