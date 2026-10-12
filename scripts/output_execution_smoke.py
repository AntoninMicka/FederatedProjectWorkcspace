#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Execute one confirmed local web-static plan without changing the checkout."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.output_capabilities import reviewed_output_catalog
from spikes.output_execution import OutputExecutor
from spikes.output_plans import output_policy_sha256
from spikes.storage import Git


def main():
    git = Git(ROOT); head = git.head()
    before = git.run('status', '--short', '--untracked-files=all').stdout
    info, path = git.run('ls-tree', head, '--', 'README.md').stdout.strip().split('\t', 1)
    _, _, oid = info.split()
    raw = git.run('cat-file', 'blob', oid, binary=True).stdout
    catalog = reviewed_output_catalog()
    policy = {'schema_version': 1, 'policy_id': 'output.local-preview',
        'revision': 'smoke-v1',
        'allowed_capabilities': [{'id': 'renderer.web-static', 'version': '1.0'}],
        'permissions': ['artifact.read', 'output.compile'],
        'privacy': ['project'], 'execution_boundaries': ['same-process'],
        'cost_classes': ['local-compute'], 'side_effects': ['local']}
    source_id, plan_id, project_id, step_id = (str(uuid4()) for _ in range(4))
    plan = {'schema_version': 1, 'plan_id': plan_id, 'project_id': project_id,
        'project_commit': head, 'policy': {'id': policy['policy_id'],
            'revision': policy['revision'], 'sha256': output_policy_sha256(policy)},
        'privacy': 'project', 'artifacts': [{'source_id': source_id,
            'artifact_id': str(uuid4()), 'project_commit': head, 'path': path,
            'blob_id': oid, 'sha256': hashlib.sha256(raw).hexdigest(),
            'size': len(raw),
            'schema': 'module://workspace.output.web/schemas/ordered-sections-v1.json',
            'mime_type': 'text/markdown', 'format': 'markdown-section',
            'privacy': 'project'}], 'materialized': [],
        'steps': [{'step_id': step_id,
            'capability': {'id': 'renderer.web-static', 'version': '1.0'},
            'privacy': 'project', 'inputs': [{'input_port': 'sections',
                'source_type': 'artifact', 'source_id': source_id}]}], 'edges': []}
    operation_id, node_id, user_id = (str(uuid4()) for _ in range(3))
    with tempfile.TemporaryDirectory(prefix='fpw-output-smoke-') as temporary:
        state = Path(temporary); state.chmod(0o700)
        executor = OutputExecutor(git=git, state_dir=state, catalog=catalog, policy=policy)
        prepared = executor.prepare(operation_id, node_id, user_id, plan)
        completed = executor.execute(operation_id, node_id, user_id,
                                     prepared['approval_digest'])
        output, receipt = executor.cache.load_generation(operation_id, step_id)
        result = {'preview_status': prepared['state'],
            'confirmation_digest': prepared['approval_digest'],
            'execution_status': completed['state'],
            'step_status': completed['steps'][0]['state'],
            'output_sha256': receipt['output_sha256'],
            'output_size': len(output), 'project_head_unchanged': git.head() == head,
            'working_tree_unchanged':
                git.run('status', '--short', '--untracked-files=all').stdout == before,
            'publication_performed': False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
