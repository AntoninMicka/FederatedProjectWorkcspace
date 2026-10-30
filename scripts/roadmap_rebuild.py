# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Build and audit a fresh roadmap candidate from pinned sequential sources."""
import argparse
import json
import sys
import time

from spikes.project_creation import default_node_path
from spikes.roadmap_rebuild import MAX_ATTEMPTS, RoadmapRebuild


def _duration(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds)); hours, rest = divmod(seconds, 3600); minutes, secs = divmod(rest, 60)
    return (f'{hours:d}:{minutes:02d}:{secs:02d}' if hours else f'{minutes:d}:{secs:02d}')


def progress_reporter(stream=None):
    stream = stream or sys.stderr; started = time.monotonic(); calls = 0
    interactive = stream.isatty()

    def report(event):
        nonlocal calls
        if event['event'] == 'result':
            calls += 1
        elapsed = time.monotonic() - started
        average = elapsed / calls if calls else None
        remaining = max(0, event['logical_total'] - event['logical_done'])
        eta = average * remaining if average is not None else None
        state = ('volám model' if event['event'] == 'dispatch' else
                 {'completed': 'hotovo', 'repair': 'oprava', 'failed': 'selhalo'}[event['outcome']])
        percent = event['logical_done'] * 100 / event['logical_total']
        line = (f'{event["phase"]} {event["block"]}/{event["blocks"]} '
                f'pokus {event["attempt"]}/{MAX_ATTEMPTS} · {state} · '
                f'{event["logical_done"]}/{event["logical_total"]} ({percent:.1f} %) · '
                f'běží {_duration(elapsed)} · ETA {_duration(eta)}')
        if interactive:
            print('\r' + line.ljust(120), end='', file=stream, flush=True)
        else:
            print(line, file=stream, flush=True)
    report.finish = lambda: print(file=stream, flush=True) if interactive else None
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--run-dir', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--repository', required=True)
    prepare.add_argument('--revision', default='HEAD')
    prepare.add_argument('--module', nargs=3, action='append', default=[],
                         metavar=('MODULE_ID', 'REPOSITORY', 'REVISION'))
    derive = sub.add_parser('derive')
    derive.add_argument('--from-run', required=True)
    derive.add_argument('--retry-extraction', action='append', default=[])
    derive.add_argument('--accept-audit', nargs=2, action='append', default=[],
                        metavar=('BLOCK_ID', 'REASON'))
    run = sub.add_parser('run'); run.add_argument('--limit', type=int, default=1)
    sub.add_parser('status')
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        service = RoadmapRebuild.prepare(args.node, args.run_dir, args.repository,
                                         revision=args.revision, modules=args.module)
        result = service.status()
    elif args.command == 'derive':
        service = RoadmapRebuild.derive(args.node, args.run_dir, args.from_run,
                                        retry_extractions=args.retry_extraction,
                                        audit_overrides=args.accept_audit)
        result = service.status()
    else:
        service = RoadmapRebuild(args.node, args.run_dir)
        if args.command == 'run':
            reporter = progress_reporter()
            try:
                result = service.run(limit=args.limit, progress=reporter)
            finally:
                reporter.finish()
        else:
            result = service.status()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
