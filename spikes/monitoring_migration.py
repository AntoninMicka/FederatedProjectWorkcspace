# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed one-time migration; archived definitions remain immutable evidence."""
from contextlib import ExitStack
from copy import deepcopy
from functools import lru_cache
import json

from spikes.metadata import require, uuid
from spikes.monitoring import ident
from spikes.monitoring_blocks import validate_block
from spikes.reporting import operation_uuid
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, ref, sequence, hex_id


def validate_migration(value):
    fields(value, 'schema sources block_ids finding_refs retention_days processing_node_id preview_sha256')
    require(value['schema']=='fpw-reporting-migration-v1','Unknown monitoring migration')
    def source(s):
        fields(s, 'kind id ref');require(s['kind'] in {'watch','definition'},'Unknown migration origin')
        uuid(s['id']);ref(s['ref'])
    sequence(value['sources'], source, minimum=1);sequence(value['block_ids'],uuid,minimum=1)
    require(type(value['retention_days']) is int and 1<=value['retention_days']<=3650,'Invalid migration retention')
    require(isinstance(value['finding_refs'],list) and len(value['finding_refs'])<=500,'Too many migrated findings')
    for reference in value['finding_refs']:ref(reference)
    uuid(value['processing_node_id']);hex_id(value['preview_sha256'])


def validate_migrations(rows):
    seen=set();blocks={r['entity_id']:r for r in rows.values() if r['type']=='MonitoringBlock'}
    for r in rows.values():
        if r['type']!='MonitoringMigration':continue
        require(not r['previous'],'Migration receipt is immutable')
        validate_migration(r['value'])
        require(set(r['value']['block_ids'])<=set(blocks),'Migration blocks are missing')
        require(all(PRIVACY[r['privacy']]>=PRIVACY[blocks[id_]['privacy']] for id_ in r['value']['block_ids']),'Migration receipt lowers block privacy')
        for source in r['value']['sources']:
            key=(source['kind'],source['id'])
            require(key not in seen,'Watch already has a one-time migration')
            seen.add(key)
            if source['kind']=='definition':
                original=rows.get(source['ref']['artifact_id'])
                require(original and original['type']=='WatchDefinition' and original['entity_id']==source['id'],
                        'Migration origin differs from watch definition')


@lru_cache(maxsize=128)
def _retired(repo_path,head):
    from spikes.storage import Git
    git=Git(repo_path)
    result=git.run('grep','-l','"type"[[:space:]]*:[[:space:]]*"MonitoringMigration"',head,'--','artifacts/*/record.json',check=False)
    require(result.returncode in {0,1},'Cannot read migration retirement markers')
    ids=set()
    for path in result.stdout.splitlines():
        row=json.loads(git.run('show',path).stdout)
        if row.get('type')=='MonitoringMigration':
            validate_migration(row['value'])
            ids.update(s['id'] for s in row['value']['sources'])
    return frozenset(ids)


def retired_ids(node,pid):
    from spikes.projects import Projects
    git=Projects(node).repository(pid)
    return _retired(str(git.root),git.head())


def require_not_retired(node,pid,watch_id):
    require(watch_id not in retired_ids(node,pid), 'Sledování bylo převedeno na nové bloky; starý provoz je vypnutý.')


class MonitoringMigration:
    def __init__(self,monitoring):
        self.monitoring=monitoring;self.node=monitoring.node
        self.runtime=monitoring.composable
        self.reporting=monitoring.reporting

    def inventory(self,pid):
        from spikes.monitoring_definitions import MonitoringDefinitions
        ws,head,files,entities,rows=self.monitoring._data(pid)
        retired=retired_ids(self.node,pid)
        watches=[dict(id=w['id'],kind='watch',title=w['name'],converted=w['id'] in retired)
                 for w in self.monitoring.watches(files,entities)]
        definitions=MonitoringDefinitions(self.node).read(pid)
        require(definitions['commit_id']==head,'Project changed during migration inventory')
        watches.extend(dict(id=b['watch_id'],kind='definition',title=b['definition']['title'],
                            converted=b['watch_id'] in retired) for b in definitions['definitions'])
        with self.runtime.pools.db() as db:
            pending=[dict(operation_id=r[0],watch_ids=json.loads(r[1])['watch_ids']) for r in db.execute("SELECT id,document FROM block_jobs WHERE project=? AND state NOT IN ('completed','cancelled')",(pid,)) if json.loads(r[1]).get('kind')=='migration']
        return dict(commit_id=head,items=watches,pending=pending)

    def _pending(self,pid,watch_ids,rows,*,ignore_operation_id=None):
        task_ids={ident(w,'definition-task-entity') for w in watch_ids}|{ident(w,'task-entity') for w in watch_ids}
        tasks={r['revision_id'] for r in rows.values() if r['type']=='ReportingTask' and r['entity_id'] in task_ids}
        blockers=[]
        with self.monitoring.scheduler.db() as db:
            for id_,state,raw in db.execute('SELECT id,state,document FROM rss_polls'):
                poll=json.loads(raw)
                if poll.get('project_id')==pid and poll.get('watch_id') in watch_ids and state in {'prepared','dispatching','fetched','publishing','unknown'}:
                    blockers.append('RSS '+id_+' / '+state)
            for raw, in db.execute('SELECT document FROM runs'):
                run=json.loads(raw)
                if run['project_id']==pid and run['task_ref']['artifact_id'] in tasks and run['state'] not in {'completed','cancelled','review','failed'}:
                    blockers.append('Report '+run['run_id']+' / '+run['state'])
        with self.runtime.pools.db() as db:
            for id_,raw in db.execute("SELECT id,document FROM block_jobs WHERE project=? AND state NOT IN ('completed','cancelled')",(pid,)):
                saved=json.loads(raw)
                if id_!=ignore_operation_id and saved.get('kind')=='migration' and set(saved['watch_ids'])&watch_ids:
                    blockers.append('migration '+id_)
        return blockers

    def preview(self,pid,watch_ids,retention_days,processing_node_id,*,pool_bindings=None):
        from spikes.monitoring_definition_schema import validate_graph
        from spikes.reporting import pinned
        require(isinstance(watch_ids,list) and watch_ids and len(set(watch_ids))==len(watch_ids),'Vyberte sledování k převodu.')
        for id_ in watch_ids:uuid(id_)
        uuid(processing_node_id)
        require(type(retention_days) is int and 1<=retention_days<=3650,'Zvolte retenční dobu 1–3650 dní.')
        ws,head,files,entities,rows=self.monitoring._data(pid)
        definitions=validate_graph(rows)
        legacy={w['id']:w for w in self.monitoring.watches(files,entities)}
        retired=retired_ids(self.node,pid)
        require(pool_bindings is None or isinstance(pool_bindings,dict),'Invalid explicit pool bindings')
        bindings=deepcopy(pool_bindings or {})
        require(isinstance(bindings,dict) and set(bindings)<=set(watch_ids),'Invalid explicit pool bindings')
        catalog=self.runtime.blocks.read(pid)
        require(catalog['commit_id']==head,'Project changed during migration preview')
        existing={b['id']:b for b in catalog['blocks']}
        for owner,pools in bindings.items():
            require(isinstance(pools,list) and pools and len(set(pools))==len(pools),'Choose explicit input pools')
            for pool in pools:
                uuid(pool);require(pool in existing and existing[pool]['value']['kind']=='pool','Unknown explicit pool')
        require(set(watch_ids)<=set(definitions)|set(legacy),'Vybrané sledování není dostupné.')
        require(not(set(watch_ids)&retired),'Sledování již bylo převedeno. Obnovte přehled.')
        sources=[];specs={};issues=[];notices=[];pool_map={};filter_map={};input_map={}
        def add(id_,kind,title,privacy,config):
            v=dict(schema='fpw-reporting-block-v1',kind=kind,title=title[:150],config=config)
            validate_block(v);spec=dict(id=id_,previous=[],privacy=privacy,value=v)
            require(id_ not in specs or specs[id_]==spec,'Migration identity collision')
            specs[id_]=spec
        for id_ in sorted(watch_ids):
            if id_ in legacy:
                w=legacy[id_]
                sources.append(dict(kind='watch',id=id_,ref=pinned(pid,head,id_,files,entities)))
                if id_ not in bindings:
                    issues.append(dict(id=id_,reason='Původní víceperiodové sledování: vyberte nové vstupní pooly. Původní dokumenty a obecné URL se nesmějí odhadnout jako RSS.'));continue
                privacy=max([w['privacy']]+[existing[p]['privacy'] for p in bindings[id_]],key=lambda p:PRIVACY[p])
                processing=[]
                for period,instructions in w['periods'].items():
                    p_id=ident(id_,'migration-v1:processing:'+period);processing.append(p_id)
                    add(p_id,'processing',w['name']+' — '+period,privacy,dict(pool_ids=sorted(bindings[id_]),search_ids=[],
                        instructions=w['goal']+'\n\n'+instructions,mode=w['mode'],schedule=dict(kind='manual',time='07:00',timezone=w['timezone']),
                        lookback_days={'weekly':7,'monthly':31,'quarterly':93,'annual':366}[period],node_id=processing_node_id))
                add(ident(id_,'migration-v1:task'),'task',w['name'],privacy,dict(source_ids=[],filter_ids=[],pool_ids=sorted(bindings[id_]),
                    processing_ids=processing,instructions=w['goal']))
                notices.append(w['name']+': každé původní období bude samostatné ruční zpracování nad vámi zvolenými pooly. '
                    'Původní dokumenty, URL, kalendář a nastavení prezentace zůstávají v archivu, nejsou novými aktivními vstupy. Všechna nová spuštění jsou vypnutá.')
                continue
            row=definitions[id_];v=row['value'];privacy=row['privacy']
            sources.append(dict(kind='definition',id=id_,ref=pinned(pid,head,row['revision_id'],files,entities)))
            if id_ in bindings and v['report']['mode']!='collect-only':continue
            if any(i['kind']=='external' and i['connector']!='rss-atom' for i in v['inputs']):
                issues.append(dict(id=id_,reason='Externí konektor nemá jednoznačný převod na RSS nebo dotaz webového hledání.'));continue
            external=[i for i in v['inputs'] if i['kind']=='external']
            if not external:continue
            if v['selection'].get('pipeline') is None:
                issues.append(dict(id=id_,reason='Volný text výběru není vykonaný filtr. Nejdřív doplňte explicitní pravidla filtrace.'));continue
            if any(s['kind'] not in {'keywords','regex','restrict','dedup','handoff'} for s in v['selection']['pipeline']['steps']):
                issues.append(dict(id=id_,reason='Modelový filtr vyžaduje samostatné rozhodnutí o novém zpracování.'));continue
            if any('channel' in step.get('fields',[]) or 'channel' in step.get('required_fields',[]) or step.get('channels') for step in v['selection']['pipeline']['steps']):
                issues.append(dict(id=id_,reason='Filtr závisí na názvu kanálu z původního feedu. Zkontrolujte pravidla pro nové samostatné zdroje.'));continue
            pool_id=ident(id_,'migration-v1:pool');filter_id=ident(id_,'migration-v1:filter')
            pool_map[id_]=pool_id;filter_map[id_]=filter_id;source_ids=[]
            for i in external:
                sid=ident(id_,'migration-v1:source:'+i['id']);source_ids.append(sid);input_map[(id_,i['id'])]=sid
                add(sid,'source',v['title']+' — '+i['locator'],privacy,dict(connector='rss-atom',locator=i['locator'],
                    poll_seconds=i['poll']['seconds'],terms=i['access']['terms'],retention=i['access']['retention']))
            add(pool_id,'pool',v['title']+' — pool',privacy,dict(retention_days=retention_days))
            add(filter_id,'filter',v['title']+' — filtr',privacy,dict(source_ids=source_ids,pool_id=pool_id,pipeline=deepcopy(v['selection']['pipeline'])))
        for id_ in sorted(set(watch_ids)&set(definitions)):
            row=definitions[id_];v=row['value'];privacy=row['privacy']
            if v['report']['mode']=='collect-only':continue
            pools=list(bindings[id_]) if id_ in bindings else ([pool_map[id_]] if id_ in pool_map else [])
            if id_ in bindings:
                privacy=max([privacy]+[existing[p]['privacy'] for p in pools],key=lambda p:PRIVACY[p])
                notices.append(v['title']+': původní vstupní řetězec bude nahrazen vámi zvolenými pooly; nejde o převzetí vydaných reportů.')
            bad=False
            for i in v['inputs']:
                if id_ in bindings or i['kind']!='watch':continue
                if i['watch_id'] not in watch_ids:
                    issues.append(dict(id=id_,reason='Do stejného převodu vyberte i vstupní sledování '+i['watch_id']+'.'));bad=True
                elif i['take']!='findings' or i.get('include_drafts') or i.get('policy',{}).get('approval')!='selected' or i['watch_id'] not in pool_map:
                    issues.append(dict(id=id_,reason='Řetězec vydaných reportů, nezpracované nebo nepotvrzené nálezy vyžadují explicitní nové mapování poolů.'));bad=True
                else:pools.append(pool_map[i['watch_id']])
            if bad or not pools:
                if not bad:issues.append(dict(id=id_,reason='Není dostupný vstupní pool s potvrzeným výběrem.'))
                continue
            analysis=v['report'].get('analysis')
            if analysis and (analysis['case_studies'] or analysis['input_level']!='mixed') or 'presentation' in v['report']['formats'] or v['report']['language']!='cs':
                issues.append(dict(id=id_,reason='Analytická metodika, modelové cíle nebo prezentace vyžadují explicitní převod; nepřevádějí se jen jako text zadání.'));continue
            if analysis and analysis.get('target'):
                notices.append(v['title']+': původní model '+analysis['target']['model']+' je archivován. Nový model se před ručním spuštěním řídí aktuální konfigurací uzlu.')
            node=v['placement']['node_id'] if v['placement']['mode']=='node' else processing_node_id
            if v['placement']['mode']!='node':notices.append(v['title']+': potvrďte nové konkrétní přiřazení uzlu '+node+'.')
            p_id=ident(id_,'migration-v1:processing')
            instructions='\n\n'.join([v['goal'],v['report']['instructions'],'Výběr: '+v['selection']['instructions'],
                'Vyhodnocení: '+v['evaluation']['instructions'],'Struktura zprávy: '+' / '.join(v['report']['required_sections'])])
            add(p_id,'processing',v['title'],privacy,dict(pool_ids=sorted(set(pools)),search_ids=[],instructions=instructions,
                mode=v['report']['mode'],schedule=dict(kind='manual',time='07:00',timezone=v['schedule']['timezone']),
                lookback_days={'daily':1,'weekly':7,'monthly':31,'quarterly':93,'annual':366}[v['schedule']['kind']],node_id=node))
            notices.append(v['title']+': nové zpracování bude ruční, okno posledních '+str(specs[p_id]['value']['config']['lookback_days'])+
                ' dní. Původní kalendář, začátek období a scope jsou archivovány, nejsou automaticky aktivovány.')
            selected_pools=set(pools);fs=[b for b in specs.values() if b['value']['kind']=='filter' and b['value']['config']['pool_id'] in selected_pools]
            source_ids=sorted({s for b in fs for s in b['value']['config']['source_ids']})
            task_id=ident(id_,'migration-v1:task')
            add(task_id,'task',v['title']+' — úloha',privacy,dict(source_ids=source_ids,filter_ids=sorted(b['id'] for b in fs),
                pool_ids=sorted(selected_pools),processing_ids=[p_id],instructions=v['goal']))
        # Unselected downstream definitions would otherwise keep depending on retired workers.
        for id_,row in definitions.items():
            if id_ not in watch_ids and id_ not in retired and any(i['kind']=='watch' and i['watch_id'] in watch_ids for i in row['value']['inputs']):
                issues.append(dict(id=id_,reason='Navazující sledování musí být zahrnuto nebo explicitně přemapováno před převodem jeho vstupu.'))
        for b in self.runtime.blocks.read(pid)['blocks']:
            if b['id'] in specs:issues.append(dict(id=b['id'],reason='Cílové ID již existuje bez dokončeného převodu; vyžaduje obnovu původní operace.'))
        pending=self._pending(pid,set(watch_ids),rows)
        issues.extend(dict(id=pid,reason='Nejprve vyřešte rozpracovanou operaci: '+p) for p in pending)
        specs_list=sorted(specs.values(),key=lambda b:b['id'])
        if len(specs_list)>31:issues.append(dict(id=pid,reason='Převod přesahuje 31 bloků; rozdělte nezávislé skupiny.'))
        parent_ids={p['artifact_id'] for r in rows.values() for p in r['previous']}
        findings=[];expired=0
        for r in rows.values():
            if r['type']!='SourceFinding' or r['revision_id'] in parent_ids:continue
            v=r['value'];owner=rows[v['definition_ref']['artifact_id']]['entity_id']
            key=(owner,v['input_id'])
            if key not in input_map:continue
            if v['stage'] in {'unknown','failed'}:
                issues.append(dict(id=r['revision_id'],reason='Nejprve vyřešte nález se stavem '+v['stage']+'.'));continue
            if v['selection']['decision']!='selected' or v['stage'] not in {'selected','pending','processed'}:continue
            from spikes.reporting_schema import moment
            selected_at=v['item']['imported_at'] or v['item']['discovered_at']
            expires_at=moment(selected_at).timestamp()+retention_days*86400
            if expires_at<=self.monitoring.clock():expired+=1;continue
            if PRIVACY[r['privacy']]>PRIVACY[specs[pool_map[owner]]['privacy']]:
                issues.append(dict(id=r['revision_id'],reason='Nález má přísnější soukromí než navržený pool.'));continue
            findings.append(dict(ref=pinned(pid,head,r['revision_id'],files,entities),source_id=input_map[key],
                filter_id=filter_map[owner],pool_id=pool_map[owner],selected_at=selected_at,expires_at=expires_at,
                reason=v['selection']['reason'],item=deepcopy(v['item']),
                observer_node_id=rows[v['definition_ref']['artifact_id']]['value']['placement']['node_id']))
        if len(findings)>500:issues.append(dict(id=pid,reason='Převod zahrnuje více než 500 nálezů; rozdělte jej.'))
        result=dict(project_id=pid,base_head=head,sources=sources,blocks=specs_list,findings=findings,
            expired_findings=expired,issues=issues,notices=notices,
            retention_days=retention_days,processing_node_id=processing_node_id,pool_bindings=bindings)
        require(len(encoded(result))<=8*1024*1024,'Migration preview exceeds 8 MiB')
        result['preview_sha256']=digest(encoded(result))
        return result

    def apply(self,pid,watch_ids,retention_days,processing_node_id,preview_sha256,operation_id,*,confirm,pool_bindings=None,checkpoint=lambda stage:None):
        uuid(operation_id);require(confirm is True,'Potvrďte konkrétní náhled převodu.');hex_id(preview_sha256)
        self.monitoring._writable(pid)
        with ExitStack() as stack:
            require(self.monitoring.lock.acquire(blocking=False),'Monitoring právě pracuje; zkuste převod po dokončení běhu.')
            stack.callback(self.monitoring.lock.release)
            require(stack.enter_context(self.monitoring.rss_runtime.locked()),'RSS worker právě pracuje.')
            require(stack.enter_context(self.runtime.locked()),'Nový monitoring právě pracuje.')
            with self.runtime.pools.db() as db:
                row=db.execute('SELECT project,state,document,result FROM block_jobs WHERE id=?',(operation_id,)).fetchone()
            if row:
                saved=json.loads(row[2]);require(row[0]==pid and saved.get('kind')=='migration','Operation ID belongs to another intent')
                require(saved['preview_sha256']==preview_sha256 and saved['watch_ids']==sorted(watch_ids) and
                        saved['retention_days']==retention_days and saved['processing_node_id']==processing_node_id and saved.get('pool_bindings',{})==(pool_bindings or {}),'Migration intent changed')
                require(row[1]!='cancelled','Převod byl zrušen; připravte nový náhled.')
                if row[1]=='completed':return json.loads(row[3])
                plan=saved['plan']
            else:
                require(self.monitoring._receipt(pid,operation_id) is None,'Operation ID already belongs to another Workspace write')
                plan=self.preview(pid,watch_ids,retention_days,processing_node_id,pool_bindings=pool_bindings)
                require(plan['preview_sha256']==preview_sha256,'Náhled se změnil; načtěte a posuďte nový.')
                require(not plan['issues'] and plan['blocks'],'Převod má nevyřešené položky.')
                saved=dict(kind='migration',watch_ids=sorted(watch_ids),preview_sha256=preview_sha256,
                    retention_days=retention_days,processing_node_id=processing_node_id,pool_bindings=deepcopy(pool_bindings or {}),plan=plan)
                with self.runtime.pools.db() as db:
                    db.execute('INSERT INTO block_jobs VALUES(?,?,?,?,NULL)',(operation_id,pid,'prepared',encoded(saved)))
            checkpoint('migration-prepared')
            receipt=self.monitoring._receipt(pid,operation_id)
            ids=set(watch_ids)
            if receipt is None:
                specs=[dict(type='MonitoringBlock',entity_id=b['id'],previous=b['previous'],privacy=b['privacy'],value=b['value']) for b in plan['blocks']]
                privacy=max([self._source_privacy(pid,s) for s in plan['sources']]+[b['privacy'] for b in plan['blocks']],key=lambda p:PRIVACY[p])
                specs.append(dict(type='MonitoringMigration',entity_id=ident(operation_id,'migration-marker'),previous=[],privacy=privacy,
                    value=dict(schema='fpw-reporting-migration-v1',sources=plan['sources'],block_ids=[b['id'] for b in plan['blocks']],finding_refs=[f['ref'] for f in plan['findings']],
                        retention_days=retention_days,processing_node_id=processing_node_id,preview_sha256=preview_sha256)))
                def guard(ws,files,entities):
                    from spikes.reporting_schema import records
                    require(not self._pending(pid,ids,records(files,entities),ignore_operation_id=operation_id),'Staré sledování má rozpracovaný běh.')
                receipt=self.reporting.apply(dict(project_id=pid,base_head=plan['base_head'],records=specs),operation_id,
                    confirm=True,checkpoint=checkpoint,_publication_guard=guard)
            checkpoint('migration-definitions')
            pool_rows=self._pool_rows(pid,plan,operation_id)
            with self.runtime.pools.db() as db:
                self.runtime.pools._merge(db,pid,pool_rows,checkpoint=checkpoint)
                active_count=sum(f['expires_at']>self.monitoring.clock() for f in plan['findings'])
                result=dict(receipt=receipt,converted=sorted(ids),block_ids=[b['id'] for b in plan['blocks']],
                            imported_findings=active_count,expired_findings=plan['expired_findings']+len(plan['findings'])-active_count)
                db.execute("UPDATE block_jobs SET state='imported',result=? WHERE id=?",(encoded(result),operation_id))
            checkpoint('migration-pools')
            with self.monitoring.scheduler.db() as db:
                for id_ in ids:db.execute('DELETE FROM watch_grants WHERE project_id=? AND watch_id=?',(pid,id_))
                for key,raw in db.execute('SELECT key,document FROM rss_bindings').fetchall():
                    config=json.loads(raw)
                    if config['project_id']==pid and config['watch_id'] in ids:
                        config['enabled']=False;db.execute('UPDATE rss_bindings SET document=? WHERE key=?',(encoded(config),key))
            checkpoint('migration-paused')
            with self.runtime.pools.db() as db:
                audit={k:v for k,v in saved.items() if k!='plan'}
                db.execute("UPDATE block_jobs SET state='completed',document=?,result=? WHERE id=?",(encoded(audit),encoded(result),operation_id))
            checkpoint('migration-completed')
            return result

    def cancel(self,pid,operation_id,*,confirm):
        uuid(operation_id);require(confirm is True,'Potvrďte zrušení dosud neuloženého převodu.')
        self.monitoring._writable(pid)
        with ExitStack() as stack:
            require(self.monitoring.lock.acquire(blocking=False),'Monitoring právě pracuje.')
            stack.callback(self.monitoring.lock.release)
            require(stack.enter_context(self.monitoring.rss_runtime.locked()),'RSS worker právě pracuje.')
            require(stack.enter_context(self.runtime.locked()),'Monitoring právě pracuje.')
            require(self.monitoring._receipt(pid,operation_id) is None,
                    'Definice již byly uloženy; dokončete původní převod.')
            with self.runtime.pools.db() as db:
                row=db.execute('SELECT document,state FROM block_jobs WHERE id=? AND project=?',(operation_id,pid)).fetchone()
                require(row is not None,'Převod není dostupný.')
                saved=json.loads(row[0]);require(saved.get('kind')=='migration','Not a migration operation')
                require(row[1] in {'prepared','cancelled'},'Převod již nelze zrušit.')
                minimal={k:v for k,v in saved.items() if k!='plan'}
                db.execute("UPDATE block_jobs SET state='cancelled',document=?,result=NULL WHERE id=?",(encoded(minimal),operation_id))
        return dict(cancelled=True)

    def resume(self,pid,operation_id,*,checkpoint=lambda stage:None):
        with self.runtime.pools.db() as db:
            row=db.execute('SELECT document FROM block_jobs WHERE id=? AND project=?',(operation_id,pid)).fetchone()
        require(row is not None,'Migrační operace není dostupná.')
        saved=json.loads(row[0]);require(saved.get('kind')=='migration','Not a migration operation')
        return self.apply(pid,saved['watch_ids'],saved['retention_days'],saved['processing_node_id'],
            saved['preview_sha256'],operation_id,confirm=True,pool_bindings=saved.get('pool_bindings',{}),checkpoint=checkpoint)

    def _source_privacy(self,pid,source):
        ws=self.reporting.artifacts.workspace(pid)
        from spikes.metadata import validate_snapshot
        return validate_snapshot(ws.git.snapshot(source['ref']['commit_id']))[source['ref']['artifact_id']]['privacy']

    def _pool_rows(self,pid,plan,operation_id):
        from spikes.message_pools import entry,revision,stamp
        index={b['id']:i for i,b in enumerate(plan['blocks'])};by_id={b['id']:b for b in plan['blocks']};rows={}
        for f in plan['findings']:
            item=deepcopy(f['item']);observed=item['discovered_at'];raw_hash=item['provenance']['raw_sha256']
            item.update(source_id=f['source_id'],channel=by_id[f['source_id']]['value']['title'],discovered_at=None,imported_at=None)
            item['id']=digest(encoded([item['connector'],item['source_id'],item['original_id'] or item['url']]))
            item['provenance'].update(raw_sha256=None,input_ref=None)
            r=entry(pid,'item',dict(revision=revision(item),item=item));expires=stamp(f['expires_at'])
            o=entry(pid,'observation',dict(item_entry=r['id'],node_id=f['observer_node_id'],
                observed_at=observed,raw_sha256=raw_hash,expires_at=expires))
            m=entry(pid,'membership',dict(pool_id=f['pool_id'],item_entry=r['id'],filter_id=f['filter_id'],
                filter_revision=operation_uuid(operation_id,'record:'+str(index[f['filter_id']])),selected_at=f['selected_at'],
                expires_at=expires,reason=f['reason'],privacy=by_id[f['pool_id']]['privacy']))
            for row in (r,o,m):rows[row['id']]=row
        return list(rows.values())
