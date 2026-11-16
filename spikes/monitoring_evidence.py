# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only views of retained inputs, successful uses and calendar intentions."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from spikes.message_pools import MessagePools
from spikes.reporting_schema import moment,digest,encoded


def next_processing(schedule, now, last_slot=None):
    from spikes.composable_monitoring import processing_slot
    if schedule['kind']=='manual':return None
    zone=ZoneInfo(schedule['timezone']);local=datetime.fromtimestamp(now,zone)
    slot=processing_slot(schedule,now)
    if slot is not None and slot!=last_slot:return now  # overdue, no backlog replay
    hour,minute=map(int,schedule['time'].split(':'))
    for offset in range(371):
        day=local.date()+timedelta(days=offset)
        candidate=datetime(day.year,day.month,day.day,hour,minute,tzinfo=zone).timestamp()
        # Find the first real minute after a DST gap satisfying the wall time.
        normalized=datetime.fromtimestamp(candidate,zone)
        if (normalized.hour,normalized.minute)!=(hour,minute):
            while datetime.fromtimestamp(candidate-60,zone).date()==day and datetime.fromtimestamp(candidate-60,zone).strftime('%H:%M')>=schedule['time']:
                candidate-=60
        # During the autumn fold the first occurrence may already be past,
        # while the worker is still waiting for the second wall-clock occurrence.
        if candidate<=now and day==local.date():
            folded=datetime(day.year,day.month,day.day,hour,minute,tzinfo=zone,fold=1).timestamp()
            if folded>now:candidate=folded
        candidate_slot=processing_slot(schedule,candidate)
        if candidate>now and candidate_slot and candidate_slot!=last_slot and candidate_slot!=slot:return candidate
    return None


def references(intent):
    return {(pool,r['item_entry']) for pool,groups in intent.get('pools',{}).items()
            for group in groups for r in group['revisions']}


class Evidence:
    def __init__(self, pools, pid, blocks, rows, uses,*,clock=time.time,issued=()):
        self.blocks={b['id']:b for b in blocks};self.uses={};self.now=(pools.clock if pools is not None else clock)();self.issued=issued
        for intent in uses:
            self.uses.setdefault(intent['block']['id'],set()).update(references(intent))
        self.views={b['id']:MessagePools.view_rows(pid,b['id'],rows)
                    for b in blocks if b['value']['kind']=='pool'}

    def pool(self,pool_id):
        consumers=[b['id'] for b in self.blocks.values() if b['value']['kind']=='processing'
                   and pool_id in b['value']['config']['pool_ids']]
        included=set().union(*self.uses.values()) if self.uses else set()
        rows=[]
        for group in self.views.get(pool_id,[]):
            for rev in group['revisions']:
                key=(pool_id,rev['item_entry'])
                at=rev['item'].get('published_at') or rev['item'].get('discovered_at') or min(m['selected_at'] for m in group['contributions'] if m['item_entry']==rev['item_entry'])
                instant=moment(at).timestamp()
                eligible={id_ for id_ in consumers if self.now-self.blocks[id_]['value']['config']['lookback_days']*86400<=instant<=self.now}
                rows.append(dict(item_entry=rev['item_entry'],included=key in included,
                    waiting_for=[id_ for id_ in consumers if id_ in eligible and key not in self.uses.get(id_,set())],
                    outside_window_for=[id_ for id_ in consumers if id_ not in eligible and key not in self.uses.get(id_,set())]))
        return dict(items=rows,pending_count=sum(bool(r['waiting_for']) for r in rows),
                    included_count=sum(r['included'] for r in rows),consumer_ids=consumers)

    def report(self,intent,built_at=None):
        rows=[];changed=False
        built=datetime.fromisoformat(built_at.replace('Z','+00:00')).timestamp() if built_at else intent.get('started_at')
        for pool,groups in intent.get('pools',{}).items():
            current={g['key']:g for g in self.views.get(pool,[])}
            for group in groups:
                live=current.get(group['key'],{});used={r['item_entry'] for r in group['revisions']}
                used_times=[moment(m['selected_at']).timestamp() for m in group.get('contributions',[])+live.get('contributions',[])
                            if m['item_entry'] in used and m.get('selected_at')]
                baseline=min(used_times) if used_times else built
                # An unseen correction may have been collected before the report
                # on a different node and transferred only after its assembly.
                additions=[]
                for alternative in live.get('revisions',[]):
                    times=[moment(m['selected_at']).timestamp() for m in live.get('contributions',[]) if m['item_entry']==alternative['item_entry']]
                    if alternative['item_entry'] not in used and baseline is not None and times and min(times)>baseline:
                        additions.append(alternative['item_entry'])
                changed=changed or bool(additions)
                for rev in group['revisions']:
                    retained=next((r for r in live.get('revisions',[]) if r['item_entry']==rev['item_entry']),None)
                    item=retained['item'] if retained else {}
                    rows.append(dict(pool_id=pool,pool_title=self.blocks.get(pool,{}).get('value',{}).get('title','Nedostupný pool'),
                        item_entry=rev['item_entry'],revision=rev['revision'],title=item.get('title'),url=item.get('url'),
                        source_id=item.get('source_id') or rev.get('source_id'),filter_revisions=sorted({m['filter_revision'] for m in group.get('contributions',[]) if m['item_entry']==rev['item_entry']}),available=retained is not None,additional_versions=additions))
        searches={id_:value if isinstance(value,str) else digest(encoded(value)) for id_,value in intent.get('searches',{}).items()}
        from spikes.monitoring_report_inputs import freshness
        reports=freshness(intent.get('report_inputs',[]),self.issued)
        return dict(inputs=rows,reports=reports,report_gaps=intent.get('report_gaps',[]),potentially_stale=changed or any(r['potentially_stale'] for r in reports),processing_ref=intent['block'].get('ref'),input_head=intent.get('input_head'),searches=searches,
                    coverage='Porovnání s místně dostupnými položkami; chybějící nebo expirované vstupy nelze plně ověřit.')
