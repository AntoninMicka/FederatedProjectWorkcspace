#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit live smoke for bounded static public-source retrieval."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.public_source import (MAX_COMPRESSION_RATIO, MAX_DECODED_BYTES,
    MAX_TEXT_CHARS, MAX_WIRE_BYTES,
    PublicSourceBinding, PublicSourceError, PublicSourceRequest, PublicSourceRuns,
    StaticHTMLAdapter, normalize_url, url_origin)


def fetch(url):
    url = normalize_url(url); origin = url_origin(url)
    ids = {key: str(uuid4()) for key in ('binding', 'run', 'task', 'node', 'user', 'project')}
    binding = PublicSourceBinding.parse({'schema_version': 1,
        'binding_id': ids['binding'], 'revision': 'live-smoke-v1',
        'adapter': 'static-html-v1', 'origins': [origin],
        'user_agent': 'FederatedWorkspaceReader/0.1', 'auth': 'none',
        'max_wire_bytes': MAX_WIRE_BYTES, 'max_decoded_bytes': MAX_DECODED_BYTES,
        'max_text_chars': MAX_TEXT_CHARS,
        'max_compression_ratio': MAX_COMPRESSION_RATIO, 'timeout_seconds': 15})
    request = PublicSourceRequest.parse({'schema_version': 1, 'run_id': ids['run'],
        'task_id': ids['task'], 'user_id': ids['user'], 'project_id': ids['project'],
        'privacy': 'public', 'expected_head': '0' * 40,
        'binding_id': ids['binding'], 'binding_revision': binding.revision,
        'adapter': binding.adapter_id, 'candidate_source_id': 'live-smoke',
        'candidate_url': url, 'purpose': 'Explicit public source live smoke',
        'accept': ['text/html', 'text/plain'], 'max_wire_bytes': MAX_WIRE_BYTES,
        'max_decoded_bytes': MAX_DECODED_BYTES, 'max_text_chars': MAX_TEXT_CHARS,
        'max_compression_ratio': MAX_COMPRESSION_RATIO,
        'timeout_seconds': 15, 'created_at': '2026-10-17T00:00:00Z'})
    with tempfile.TemporaryDirectory(prefix='public-source-smoke-') as temporary:
        root = Path(temporary); root.chmod(0o700); runs = PublicSourceRuns(root)
        preview = {'schema_version': 1, 'run_id': ids['run'], 'url': url,
            'effects': ['GET ' + origin + '/robots.txt', 'GET ' + url],
            'limits': {'wire_bytes': MAX_WIRE_BYTES,
                       'decoded_bytes': MAX_DECODED_BYTES,
                       'text_chars': MAX_TEXT_CHARS,
                       'compression_ratio': MAX_COMPRESSION_RATIO,
                       'seconds': 15, 'redirects': 0}}
        prepared = runs.prepare(request=request, preview=preview,
                                binding=binding, node_id=ids['node'])
        result = StaticHTMLAdapter(runs).dispatch(
            ids['run'], binding, preview_sha256=prepared['preview_sha256'])
        _, projected = runs.read_staging(ids['run'])
        return {'url': url, 'origin': origin, 'result': result,
                'text_preview': projected.decode('utf-8')[:500]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve', action='store_true',
                        help='Confirm robots preflight and one GET for every supplied URL')
    parser.add_argument('urls', nargs='+')
    args = parser.parse_args()
    if not args.approve:
        parser.error('--approve is required because this command performs public GET requests')
    failed = False
    for url in args.urls:
        try:
            value = fetch(url)
        except PublicSourceError as exc:
            failed = True
            value = {'url': url, 'state': exc.state, 'code': exc.code,
                     'error': str(exc)}
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
