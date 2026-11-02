#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Run bounded model self-tuning against isolated synthetic Markdown fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from spikes.markdown_self_tuning import Campaign
from spikes.ollama_backend import OllamaAdapter, OllamaBindings
from spikes.project_creation import default_node_path
from spikes.storage import Git


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',type=Path,default=default_node_path())
    parser.add_argument('--models',nargs='+',help='Installed Ollama tags; default is the configured model')
    parser.add_argument('--output',type=Path,help='New evidence directory; never overwritten')
    parser.add_argument('--run-live',action='store_true',help='Explicitly authorize bounded NEW provider runs')
    parser.add_argument('--budget-seconds',type=int,default=600)
    parser.add_argument('--max-calls',type=int,default=40)
    parser.add_argument('--call-seconds',type=int,default=90)
    parser.add_argument('--rounds',type=int,default=1)
    parser.add_argument('--repairs',type=int,default=1)
    args=parser.parse_args(argv)
    origin=args.node.absolute();state=origin.parent/('.'+origin.name+'.chat')
    binding=OllamaBindings(state).load()
    models=args.models or [binding.model]
    if args.run_live:
        available=OllamaAdapter.discover_models(binding)
        missing=set(models)-set(available)
        if missing:parser.error('Models are not installed (nothing was pulled): '+', '.join(sorted(missing)))
    output=args.output or Path(tempfile.gettempdir())/('fpw-self-tune-'+str(uuid4()))
    if output.absolute().is_relative_to(ROOT):parser.error('Evidence directory must be outside the source checkout')
    campaign=Campaign(output,binding,models,budget_seconds=args.budget_seconds,max_calls=args.max_calls,
                      call_seconds=args.call_seconds,rounds=args.rounds,repairs=args.repairs)
    git=Git(ROOT)
    campaign.report['source']={'head':git.head(),
        'dirty':bool(git.run('status','--short').stdout.strip()),
        'files':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in [
            'spikes/markdown_self_tuning.py','scripts/markdown_self_tune.py','spikes/markdown_patch.py',
            'spikes/ollama_backend.py','spikes/context_builder.py','spikes/task_file_edit.py']}}
    campaign.checkpoint()
    print(json.dumps(dict(evidence=str(output),state='running' if args.run_live else 'prepared',models=models)),flush=True)
    if not args.run_live:return 0
    try:
        report=campaign.run()
    except (Exception, KeyboardInterrupt) as exc:
        campaign.report.update(state='interrupted' if isinstance(exc,KeyboardInterrupt) else 'harness-error',
                               error=str(exc))
        for record in campaign.report['runs']:
            if record['state']=='running':record.update(state='unknown',passed=False)
        campaign.checkpoint()
        print(json.dumps(dict(evidence=str(output),state=campaign.report['state'],error=str(exc))),flush=True)
        return 2
    for profile in report['profiles']:
        print(json.dumps(dict(model=profile['model'],configuration=profile['configuration'],
            first_pass=sum(r['first_pass'] for r in profile['results']),
            after_repair=sum(r['after_repair'] for r in profile['results']),total=len(profile['results'])),ensure_ascii=False),flush=True)
    print(json.dumps(dict(evidence=str(output),state=report['state'],calls=report['calls'],
                         recommendations=len(report['recommendations']))),flush=True)
    latest={profile['model']:profile for profile in report['profiles']}
    return 0 if all(all(r['after_repair'] for r in p['results']) for p in latest.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
