# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicitly apply one reviewed roadmap bundle through native writers."""
import argparse
import json
import os
from pathlib import Path

from spikes.metadata import parse_json
from spikes.project_creation import default_node_path
from spikes.roadmap_importer import RoadmapImporter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--source-review', required=True)
    parser.add_argument('--expected-bundle-sha256', required=True,
                        help='Exact reviewed digest; prevents accidental package selection')
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--source-root', action='append', default=[])
    parser.add_argument('--receipt', required=True, help='New output file; never overwrites a receipt')
    args = parser.parse_args(argv)
    target = Path(args.receipt)
    if os.path.lexists(target):
        raise FileExistsError('Receipt output already exists')
    review = parse_json(Path(args.source_review).read_bytes())
    receipt = RoadmapImporter(args.node).apply(
        args.bundle, review, args.expected_bundle_sha256, source_roots=args.source_root)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    print('Import completed; durable per-project receipts were replayed/written. Receipt:', target)


if __name__ == '__main__':
    raise SystemExit(main())
