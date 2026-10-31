# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Rebind exact prior source decisions and require review for changed inputs."""
import argparse
import json
from pathlib import Path

from spikes.roadmap_rebuild_bundle import rebind_source_review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--prior-review', required=True)
    parser.add_argument('--classify', nargs=3, action='append', default=[],
                        metavar=('SOURCE_KEY', 'PRIVACY', 'RATIONALE'))
    parser.add_argument('--reviewed-at')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    review = rebind_source_review(args.bundle, args.prior_review, args.classify,
                                  reviewed_at=args.reviewed_at)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(review, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps({'bundle_sha256': review['bundle_sha256'],
                      'sources': len(review['source_classifications']),
                      'external_links': len(review['external_links']),
                      'output': str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
