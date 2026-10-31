# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Run a read-only pre-write review and publish a private report."""
import argparse
import json
from pathlib import Path

from spikes.project_creation import default_node_path
from spikes.roadmap_validation import validate_bundle


def pairs(values):
    result = {}
    for value in values:
        key, separator, item = value.partition('=')
        if not separator or not key or not item or key in result:
            raise ValueError('Expected unique SCOPE=VALUE')
        result[key] = item
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--output', required=True)
    parser.add_argument('--location', action='append', default=[], metavar='SCOPE=PATH')
    parser.add_argument('--source-privacy', action='append', default=[], metavar='SOURCE=CLASS')
    parser.add_argument('--source-review', help='Bundle-bound privacy and external-link review JSON')
    parser.add_argument('--source-root', action='append', default=[])
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(mode=0o700)
    source_review = json.loads(Path(args.source_review).read_text(encoding='utf-8')) if args.source_review else None
    report = validate_bundle(args.bundle, args.node, locations=pairs(args.location),
                             source_privacy=pairs(args.source_privacy), source_roots=args.source_root,
                             source_review=source_review)
    (output / 'review.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf-8')
    lines = ['# Předzápisová prověrka roadmapy', '',
             f'Bundle: `{report["bundle_sha256"]}`', '',
             f'Výsledek: {report["summary"]["passed"]} prošlo, {report["summary"]["blocked"]} blokuje, '
             f'{report["summary"]["needs_review"]} vyžaduje review.', '',
             '| Kontrola | Stav | Výsledek |', '| --- | --- | --- |']
    for row in report['checks']:
        lines.append(f'| `{row["code"]}` | {row["status"]} | {row["detail"]} |')
    lines += ['', 'Do projektu, Gitu, journalu ani indexu nebylo zapsáno.',
              'Podrobné počty, cíle a příklady jsou v `review.json`.', '']
    (output / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
