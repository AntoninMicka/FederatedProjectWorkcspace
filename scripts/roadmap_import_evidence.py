# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Create a read-only source-to-import completeness report."""
import argparse
import json
from pathlib import Path

from spikes.project_creation import default_node_path
from spikes.roadmap_import_evidence import audit_import_evidence, render_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--node', default=str(default_node_path()))
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError('Evidence output already exists')
    report = audit_import_evidence(args.run_dir, args.bundle, args.receipt, args.node)
    output.mkdir(parents=True)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False,
        sort_keys=True, indent=2) + '\n', encoding='utf-8')
    (output/'summary.md').write_text(render_summary(report), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
