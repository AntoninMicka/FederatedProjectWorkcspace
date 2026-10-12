# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only smoke check for the reviewed output catalog and planner boundary."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.metadata import ValidationError
from spikes.output_capabilities import reviewed_output_catalog
from spikes.output_planner import review_output_proposal
from spikes.output_plans import output_policy_sha256

PROJECT_ID = '00000000-0000-4000-8000-000000000101'
PLAN_ID = '00000000-0000-4000-8000-000000000102'
STEP_ID = '00000000-0000-4000-8000-000000000103'
SOURCE_ID = '00000000-0000-4000-8000-000000000104'
ARTIFACT_ID = '00000000-0000-4000-8000-000000000105'
SCHEMA = 'module://workspace.output.web/schemas/ordered-sections-v1.json'


def git(*args, text=False):
    return subprocess.run(['git', *args], cwd=ROOT, check=True,
                          capture_output=True, text=text).stdout


def main():
    before = git('status', '--porcelain=v1')
    commit = git('rev-parse', 'HEAD', text=True).strip()
    blob_id = git('rev-parse', 'HEAD:README.md', text=True).strip()
    content = git('show', 'HEAD:README.md')
    policy = {
        'schema_version': 1,
        'policy_id': 'output.smoke-read-only',
        'revision': 'revision-1',
        'allowed_capabilities': [
            {'id': 'renderer.web-static', 'version': '1.0'}],
        'permissions': ['artifact.read', 'output.compile'],
        'privacy': ['project'],
        'execution_boundaries': ['same-process'],
        'cost_classes': ['local-compute'],
        'side_effects': ['local'],
    }
    artifact = {
        'source_id': SOURCE_ID,
        'artifact_id': ARTIFACT_ID,
        'project_commit': commit,
        'path': 'README.md',
        'blob_id': blob_id,
        'sha256': hashlib.sha256(content).hexdigest(),
        'size': len(content),
        'schema': SCHEMA,
        'mime_type': 'text/markdown',
        'format': 'markdown-section',
        'privacy': 'project',
    }
    plan = {
        'schema_version': 1,
        'plan_id': PLAN_ID,
        'project_id': PROJECT_ID,
        'project_commit': commit,
        'policy': {'id': policy['policy_id'], 'revision': policy['revision'],
                   'sha256': output_policy_sha256(policy)},
        'privacy': 'project',
        'artifacts': [artifact],
        'materialized': [],
        'steps': [{
            'step_id': STEP_ID,
            'capability': {'id': 'renderer.web-static', 'version': '1.0'},
            'privacy': 'project',
            'inputs': [{'input_port': 'sections', 'source_type': 'artifact',
                        'source_id': SOURCE_ID}],
        }],
        'edges': [],
    }
    proposal = {'schema_version': 1, 'action': 'propose-output-plan',
                'purpose': 'Read-only smoke review of an explicit Markdown source.',
                'plan': plan}
    authority = {'project_id': PROJECT_ID, 'project_commit': commit,
                 'artifacts': [artifact], 'materialized': []}
    catalog = reviewed_output_catalog()
    review = review_output_proposal(json.dumps(proposal).encode(), catalog,
                                    policy, authority)

    tampered = deepcopy(proposal)
    tampered['plan']['artifacts'][0]['sha256'] = '0' * 64
    try:
        review_output_proposal(json.dumps(tampered).encode(), catalog,
                               policy, authority)
    except ValidationError:
        tamper_rejected = True
    else:
        raise RuntimeError('Tampered source unexpectedly passed planner review')
    if git('status', '--porcelain=v1') != before:
        raise RuntimeError('Read-only smoke changed the working tree')

    print(json.dumps({
        'status': review['status'],
        'plan_sha256': review['plan_sha256'],
        'capabilities': [item['selected']['capability_id'] + '@'
                         + item['selected']['capability_version']
                         for item in review['explanations']],
        'execution_status': review['execution_handoff']['status'],
        'tampered_source_rejected': tamper_rejected,
        'working_tree_unchanged': True,
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
