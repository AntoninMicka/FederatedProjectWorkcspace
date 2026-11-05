# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Two closed reporting periods in an isolated synthetic node; no network or LLM."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from scripts.reporting_demo import demo
from spikes.reporting import Reporting
from spikes.reporting_scheduler import ReportingScheduler


def run(destination, *, confirm=False):
    seed=demo(destination,scheduled_periods=('weekly',))
    node=Path(seed['node']);project=seed['project_id'];reporting=Reporting(node)
    records=reporting.read(project)['records']
    original=next(r for r in records if r['revision_id']==seed['report']['artifact_id'])
    task_ref=original['value']['task_ref']
    task=next(r for r in records if r['revision_id']==task_ref['artifact_id'])
    scheduler=ReportingScheduler(node)
    today=datetime.now(ZoneInfo(task['value']['calendar']['timezone']))
    monday=today.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=today.weekday())
    start=(monday-timedelta(days=14)).isoformat()
    queue=scheduler.catch_up(project,task_ref,'weekly',start,limit=2)
    initial=reporting.artifacts.workspace(project).git.head();results=[]
    for job in queue['runs']:
        claim=scheduler.claim(job['run_id'],str(uuid4()))
        value=deepcopy(original['value'])
        for key in ('task_ref','rules_ref','input_head','period','knowledge_cutoff','baseline_snapshot'):
            value[key]=job[key]
        value['markdown']=None
        value['generation']=dict(mode='manual',run_id=None,context_manifest_ref=None,result_sha256=None)
        value['approval'].update(actor_id=None,at=None)
        request=dict(project_id=project,base_head=reporting.artifacts.workspace(project).git.head(),
            records=[dict(type='ReportSnapshot',entity_id=None,previous=[],privacy=original['privacy'],value=value,
                markdown='# Přehled\n\nSyntetická perioda; nejde o ověřený provoz.\n\n## Omezení\n\n'
                         'Pouze syntetické reference s neznámými daty.\n')])
        preview=scheduler.stage(job['run_id'],claim['lease_token'],request)
        result=dict(run_id=job['run_id'],period=job['period'],state='review',approval_digest=preview['approval_digest'])
        if confirm:
            scheduler.approve(job['run_id'],preview['approval_digest'],confirm=True)
            done=scheduler.publish(job['run_id'])
            assert scheduler.publish(job['run_id'])==done
            result.update(state=done['state'],receipt=done['workspace_receipt'])
        results.append(result)
        if not confirm:
            break  # The later period must wait for the earlier human review.
    if not confirm:
        assert reporting.artifacts.workspace(project).git.head()==initial
    else:
        assert reporting.artifacts.workspace(project).git.run('rev-list','--count',initial+'..HEAD').stdout.strip()=='2'
    result=dict(node=str(node),project_id=project,journal=str(scheduler.path),runs=results,
                queued=len(queue['runs']),progress=scheduler.cutoff(project,task['entity_id'],'weekly'))
    (Path(destination)/'scheduler-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path,help='Nový neexistující adresář syntetického uzlu')
    parser.add_argument('--confirm',action='store_true',help='Potvrdit dva syntetické reporty v izolované fixture')
    args=parser.parse_args()
    print(json.dumps(run(args.destination,confirm=args.confirm),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
