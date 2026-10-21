# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Application review boundary for untrusted output-plan proposals."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from spikes.metadata import parse_json, require, uuid
from spikes.output_plans import (canonical_output_plan, canonical_output_policy,
                                  parse_output_policy, validate_output_plan)


MAX_PROPOSAL = 512 * 1024
MAX_PURPOSE = 2000
REVALIDATIONS = (
    'catalog-revisions', 'trusted-policy-hash', 'project-head',
    'artifact-authorization-and-bytes', 'materialized-source-hashes',
    'privacy-and-port-contracts',
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class OutputPlanProposal:
    purpose: str
    plan: dict

    @classmethod
    def parse(cls, data):
        value = parse_json(data, maximum=MAX_PROPOSAL)
        required = {'schema_version', 'action', 'purpose', 'plan'}
        require(isinstance(value, dict) and value.keys() == required,
                'Unknown or missing output planner proposal field')
        require(type(value['schema_version']) is int and value['schema_version'] == 1
                and value['action'] == 'propose-output-plan',
                'Unsupported output planner proposal')
        purpose = value['purpose']
        require(isinstance(purpose, str) and purpose.strip() == purpose
                and bool(purpose) and '\0' not in purpose
                and len(purpose.encode()) <= MAX_PURPOSE,
                'Invalid output planner purpose')
        require(isinstance(value['plan'], dict), 'Output planner plan must be an object')
        return cls(purpose, deepcopy(value['plan']))

    def serialize(self):
        return {'schema_version': 1, 'action': 'propose-output-plan',
                'purpose': self.purpose, 'plan': deepcopy(self.plan)}

    def sha256(self):
        return _digest(_canonical(self.serialize()))


def _trusted_sources(authority, field):
    values = authority[field]
    require(isinstance(values, list) and len(values) <= 256,
            f'Invalid trusted output {field}')
    result = {}
    for source in values:
        require(isinstance(source, dict) and isinstance(source.get('source_id'), str),
                f'Invalid trusted output {field} source')
        uuid(source['source_id'])
        require(source['source_id'] not in result, 'Duplicate trusted output source ID')
        result[source['source_id']] = source
    return result


def _policy_allows(descriptor, policy, privacy):
    allowed = {(item['id'], item['version']) for item in policy['allowed_capabilities']}
    return ((descriptor['capability_id'], descriptor['capability_version']) in allowed
            and set(descriptor['permissions']) <= set(policy['permissions'])
            and privacy in descriptor['privacy'] and privacy in policy['privacy']
            and descriptor['execution_boundary'] in policy['execution_boundaries']
            and descriptor['cost_class'] in policy['cost_classes']
            and descriptor['side_effect'] in policy['side_effects'])


def _compatible(candidate, selected):
    return (candidate['inputs'] == selected['inputs']
            and candidate['output'] == selected['output'])


def _explain(plan, catalog, policy):
    explanations = []
    for step in plan['steps']:
        selected = catalog.resolve(step['capability']['id'],
                                   step['capability']['version'])
        alternatives = []
        for candidate in catalog.list():
            if ((candidate['capability_id'], candidate['capability_version']) ==
                    (selected['capability_id'], selected['capability_version'])):
                continue
            if (_compatible(candidate, selected)
                    and _policy_allows(candidate, policy, step['privacy'])):
                alternatives.append({
                    'capability_id': candidate['capability_id'],
                    'capability_version': candidate['capability_version'],
                    'display_name': candidate['display_name'],
                })
        explanations.append({
            'step_id': step['step_id'],
            'selected': {
                'capability_id': selected['capability_id'],
                'capability_version': selected['capability_version'],
                'display_name': selected['display_name'],
            },
            'selection_basis': [
                'exact-reviewed-capability', 'typed-port-compatibility',
                'trusted-policy', 'derived-privacy',
            ],
            'execution_boundary': selected['execution_boundary'],
            'cost_class': selected['cost_class'],
            'side_effect': selected['side_effect'],
            'required_confirmations': sorted(selected['confirmations']),
            'compatible_alternatives': alternatives,
        })
    return explanations


def review_output_proposal(data, catalog, policy, authority):
    """Revalidate an untrusted proposal and return a non-executable review.

    ``authority`` is assembled by the application from the current project and
    authorized source registries. It is never copied from the planner response.
    """
    proposal = OutputPlanProposal.parse(data)
    policy = parse_output_policy(canonical_output_policy(policy))
    require(isinstance(authority, dict)
            and authority.keys() == {'project_id', 'project_commit',
                                     'artifacts', 'materialized'},
            'Unknown or missing trusted output authority field')
    uuid(authority['project_id'])
    require(isinstance(authority['project_commit'], str),
            'Invalid trusted output project commit')
    trusted_artifacts = _trusted_sources(authority, 'artifacts')
    trusted_materialized = _trusted_sources(authority, 'materialized')

    plan_raw = json.dumps(proposal.plan, ensure_ascii=False,
                          separators=(',', ':')).encode()
    plan = validate_output_plan(plan_raw, catalog, policy)
    require((plan['project_id'], plan['project_commit']) ==
            (authority['project_id'], authority['project_commit']),
            'Output proposal targets a stale or different project')
    for field, trusted in (('artifacts', trusted_artifacts),
                           ('materialized', trusted_materialized)):
        for source in plan[field]:
            require(trusted.get(source['source_id']) == source,
                    'Output proposal source differs from trusted application state')

    canonical_plan = canonical_output_plan(plan, catalog, policy)
    plan_sha256 = _digest(canonical_plan)
    explanations = _explain(plan, catalog, policy)
    confirmations = sorted({confirmation for explanation in explanations
                            for confirmation in explanation['required_confirmations']})
    return {
        'schema_version': 1,
        'status': 'validated-read-only',
        'proposal_sha256': proposal.sha256(),
        'purpose': proposal.purpose,
        'purpose_trust': 'untrusted-planner',
        'plan': deepcopy(plan),
        'plan_sha256': plan_sha256,
        'explanations': explanations,
        'execution_handoff': {
            'schema': 'fpw-output-execution-handoff-v1',
            'status': 'not-authorized',
            'plan_id': plan['plan_id'],
            'plan_sha256': plan_sha256,
            'project_id': plan['project_id'],
            'project_commit': plan['project_commit'],
            'policy': deepcopy(plan['policy']),
            'required_confirmations': confirmations,
            'required_revalidations': list(REVALIDATIONS),
        },
    }
