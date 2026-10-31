# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Write a private source-inventory report; never contact or mutate Workspace."""
import argparse
import json
from pathlib import Path

from spikes.roadmap_migration import inventory, render_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='.')
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--module', nargs=3, action='append', default=[],
                        metavar=('MODULE_ID', 'REPOSITORY', 'REVISION'))
    parser.add_argument('--output', required=True, help='New report directory, must not exist')
    args = parser.parse_args()
    result = inventory(args.repository, revision=args.revision, modules=args.module)
    output = Path(args.output)
    output.mkdir(mode=0o700)
    (output / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'summary.md').write_text(render_summary(result), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
    print('Inventory only; no Workspace data changed. Report:', output)


if __name__ == '__main__':
    main()
