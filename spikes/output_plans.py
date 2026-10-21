# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed validation for read-only output composition plans."""
import hashlib
import json
import re

from spikes.metadata import parse_json, require, safe_path, uuid
from spikes.module_manifest import BOUNDARIES, IDENTIFIER, PRIVACY, SCHEMA_REF, VERSION
from spikes.output_capabilities import COST_CLASSES, MIME, SIDE_EFFECTS


MAX_STEPS = 64
MAX_SOURCES = 256
MAX_BINDINGS = 256
HASH = re.compile(r'[0-9a-f]{64}')
GIT_OBJECT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')
PRIVACY_RANK = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
SOURCE_TYPES = {'artifact', 'materialized', 'edge'}


def _fields(value, required, name):
    require(isinstance(value, dict), f'Output plan {name} must be an object')
    require(value.keys() == required, f'Unknown or missing output plan {name} field')


def _list(value, name, *, maximum, allow_empty=False):
    require(isinstance(value, list) and len(value) <= maximum
            and (allow_empty or bool(value)), f'Invalid output plan {name}')
    return value


def _identifier(value, name):
    require(isinstance(value, str) and bool(IDENTIFIER.fullmatch(value)),
            f'Invalid output plan {name}')


def _version(value, name):
    require(isinstance(value, str) and bool(VERSION.fullmatch(value)),
            f'Invalid output plan {name}')


def _hash(value, name):
    require(isinstance(value, str) and bool(HASH.fullmatch(value)),
            f'Invalid output plan {name}')


def _privacy_list(value):
    _list(value, 'privacy', maximum=len(PRIVACY))
    require(all(isinstance(item, str) and item in PRIVACY for item in value),
            'Unsupported output plan privacy')
    require(len(value) == len(set(value)), 'Duplicate output plan privacy')


def _identifier_list(value, name, *, allowed=None):
    _list(value, name, maximum=64)
    for item in value:
        _identifier(item, name)
    require(len(value) == len(set(value)), f'Duplicate output plan {name}')
    if allowed is not None:
        require(set(value) <= allowed, f'Unsupported output plan {name}')


def parse_output_policy(data):
    """Validate trusted policy supplied separately from an untrusted plan."""
    value = parse_json(data)
    _fields(value, {'schema_version', 'policy_id', 'revision',
                    'allowed_capabilities', 'permissions', 'privacy',
                    'execution_boundaries', 'cost_classes', 'side_effects'}, 'policy')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported output plan policy schema')
    _identifier(value['policy_id'], 'policy ID')
    _identifier(value['revision'], 'policy revision')
    _list(value['allowed_capabilities'], 'allowed capabilities', maximum=64)
    keys = []
    for capability in value['allowed_capabilities']:
        _fields(capability, {'id', 'version'}, 'allowed capability')
        _identifier(capability['id'], 'allowed capability ID')
        _version(capability['version'], 'allowed capability version')
        keys.append((capability['id'], capability['version']))
    require(len(keys) == len(set(keys)), 'Duplicate output plan allowed capability')
    _identifier_list(value['permissions'], 'permissions')
    _privacy_list(value['privacy'])
    _identifier_list(value['execution_boundaries'], 'execution boundaries',
                     allowed=BOUNDARIES)
    _identifier_list(value['cost_classes'], 'cost classes', allowed=COST_CLASSES)
    _identifier_list(value['side_effects'], 'side effects', allowed=SIDE_EFFECTS)
    return value


def canonical_output_policy(value):
    parsed = parse_output_policy(json.dumps(value, ensure_ascii=False,
                                            separators=(',', ':')).encode())
    return (json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode()


def output_policy_sha256(value):
    return hashlib.sha256(canonical_output_policy(value)).hexdigest()


def _source(value, kind, *, plan_id, project_commit):
    common = {'source_id', 'sha256', 'size', 'schema', 'mime_type', 'format', 'privacy'}
    fields = common | ({'artifact_id', 'project_commit', 'path', 'blob_id'}
                       if kind == 'artifact' else
                       {'producer_plan_id', 'producer_plan_sha256',
                        'producer_step_id', 'producer_output_port'})
    _fields(value, fields, f'{kind} source')
    uuid(value['source_id'])
    _hash(value['sha256'], 'source hash')
    require(type(value['size']) is int and 0 <= value['size'] <= 2 ** 31 - 1,
            'Invalid output plan source size')
    require(isinstance(value['schema'], str) and bool(SCHEMA_REF.fullmatch(value['schema'])),
            'Invalid output plan source schema')
    require(isinstance(value['mime_type'], str) and bool(MIME.fullmatch(value['mime_type'])),
            'Invalid output plan source MIME type')
    _identifier(value['format'], 'source format')
    require(isinstance(value['privacy'], str) and value['privacy'] in PRIVACY,
            'Unsupported output plan source privacy')
    if kind == 'artifact':
        uuid(value['artifact_id'])
        require(value['project_commit'] == project_commit,
                'Output plan artifact belongs to another project revision')
        safe_path(value['path'])
        require(isinstance(value['blob_id'], str)
                and bool(GIT_OBJECT.fullmatch(value['blob_id'])),
                'Invalid output plan artifact blob ID')
    else:
        uuid(value['producer_plan_id'])
        uuid(value['producer_step_id'])
        _hash(value['producer_plan_sha256'], 'producer plan hash')
        _identifier(value['producer_output_port'], 'producer output port')
        require(value['producer_plan_id'] != plan_id,
                'Current output plan cannot claim an already materialized result')


def _contract_matches(source, port):
    return (source['schema'] == port['schema']
            and source['mime_type'] in port['mime_types']
            and source['format'] == port['format'])


def _most_private(values):
    require(bool(values), 'Output plan step must have an explicit input')
    return max(values, key=PRIVACY_RANK.__getitem__)


def validate_output_plan(data, catalog, policy):
    """Validate a plan against an exact catalog and separately trusted policy.

    This function only validates and returns a parsed copy. It never dispatches a
    capability, selects a backend, reads artifacts, or writes durable state.
    """
    policy = parse_output_policy(canonical_output_policy(policy))
    value = parse_json(data)
    _fields(value, {'schema_version', 'plan_id', 'project_id', 'project_commit',
                    'policy', 'privacy', 'artifacts', 'materialized', 'steps',
                    'edges'}, 'document')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported output plan schema')
    uuid(value['plan_id'])
    uuid(value['project_id'])
    require(isinstance(value['project_commit'], str)
            and bool(GIT_OBJECT.fullmatch(value['project_commit'])),
            'Invalid output plan project commit')
    _fields(value['policy'], {'id', 'revision', 'sha256'}, 'policy reference')
    require((value['policy']['id'], value['policy']['revision'],
             value['policy']['sha256']) ==
            (policy['policy_id'], policy['revision'], output_policy_sha256(policy)),
            'Output plan policy reference differs from trusted policy')
    require(isinstance(value['privacy'], str) and value['privacy'] in PRIVACY,
            'Unsupported output plan privacy')

    sources = {}
    for field, kind in (('artifacts', 'artifact'), ('materialized', 'materialized')):
        _list(value[field], field, maximum=MAX_SOURCES, allow_empty=True)
        for source in value[field]:
            _source(source, kind, plan_id=value['plan_id'],
                    project_commit=value['project_commit'])
            source_id = source['source_id']
            require(source_id not in sources, 'Duplicate output plan source ID')
            sources[source_id] = (kind, source)

    _list(value['steps'], 'steps', maximum=MAX_STEPS)
    steps = {}
    descriptors = {}
    allowed = {(item['id'], item['version']) for item in policy['allowed_capabilities']}
    for step in value['steps']:
        _fields(step, {'step_id', 'capability', 'privacy', 'inputs'}, 'step')
        uuid(step['step_id'])
        require(step['step_id'] not in steps, 'Duplicate output plan step ID')
        _fields(step['capability'], {'id', 'version'}, 'step capability')
        _identifier(step['capability']['id'], 'step capability ID')
        _version(step['capability']['version'], 'step capability version')
        key = (step['capability']['id'], step['capability']['version'])
        require(key in allowed, 'Output plan capability is not allowed by policy')
        descriptor = catalog.resolve(*key)
        require(set(descriptor['permissions']) <= set(policy['permissions']),
                'Output plan capability permission is not granted')
        require(descriptor['execution_boundary'] in policy['execution_boundaries'],
                'Output plan execution boundary is not allowed')
        require(descriptor['cost_class'] in policy['cost_classes'],
                'Output plan cost class is not allowed')
        require(descriptor['side_effect'] in policy['side_effects'],
                'Output plan side effect is not allowed')
        require(isinstance(step['privacy'], str)
                and step['privacy'] in descriptor['privacy']
                and step['privacy'] in policy['privacy'],
                'Output plan step privacy is not allowed')
        _list(step['inputs'], 'step inputs', maximum=MAX_BINDINGS)
        binding_keys = []
        for binding in step['inputs']:
            _fields(binding, {'input_port', 'source_type', 'source_id'}, 'input binding')
            _identifier(binding['input_port'], 'input port')
            require(isinstance(binding['source_type'], str)
                    and binding['source_type'] in SOURCE_TYPES,
                    'Unsupported output plan source type')
            uuid(binding['source_id'])
            binding_keys.append((binding['input_port'], binding['source_type'],
                                 binding['source_id']))
        require(len(binding_keys) == len(set(binding_keys)),
                'Duplicate output plan input binding')
        steps[step['step_id']] = step
        descriptors[step['step_id']] = descriptor

    _list(value['edges'], 'edges', maximum=MAX_BINDINGS, allow_empty=True)
    edges = {}
    outgoing = {step_id: set() for step_id in steps}
    for edge in value['edges']:
        _fields(edge, {'edge_id', 'from_step_id', 'from_port', 'to_step_id',
                       'to_port', 'schema', 'mime_type', 'format', 'privacy'}, 'edge')
        for field in ('edge_id', 'from_step_id', 'to_step_id'):
            uuid(edge[field])
        require(edge['edge_id'] not in edges and edge['edge_id'] not in sources,
                'Duplicate output plan edge ID')
        require(edge['from_step_id'] in steps and edge['to_step_id'] in steps
                and edge['from_step_id'] != edge['to_step_id'],
                'Invalid output plan edge endpoint')
        producer = descriptors[edge['from_step_id']]['output']
        consumer_ports = {port['port_id']: port
                          for port in descriptors[edge['to_step_id']]['inputs']}
        require(edge['from_port'] == producer['port_id']
                and edge['to_port'] in consumer_ports,
                'Unknown output plan edge port')
        consumer = consumer_ports[edge['to_port']]
        require(edge['schema'] == producer['schema'] == consumer['schema']
                and edge['mime_type'] in producer['mime_types']
                and edge['mime_type'] in consumer['mime_types']
                and edge['format'] == producer['format'] == consumer['format'],
                'Incompatible output plan edge contract')
        require(edge['privacy'] == steps[edge['from_step_id']]['privacy'],
                'Output plan edge weakens producer privacy')
        edges[edge['edge_id']] = edge
        outgoing[edge['from_step_id']].add(edge['to_step_id'])

    edge_uses = {edge_id: 0 for edge_id in edges}
    source_uses = {source_id: 0 for source_id in sources}
    for step_id, step in steps.items():
        descriptor = descriptors[step_id]
        ports = {port['port_id']: port for port in descriptor['inputs']}
        counts = {port_id: 0 for port_id in ports}
        input_privacy = []
        for binding in step['inputs']:
            port = ports.get(binding['input_port'])
            require(port is not None, 'Unknown output plan input port')
            counts[binding['input_port']] += 1
            if binding['source_type'] == 'edge':
                edge = edges.get(binding['source_id'])
                require(edge is not None and edge['to_step_id'] == step_id
                        and edge['to_port'] == binding['input_port'],
                        'Output plan binding references another edge destination')
                edge_uses[binding['source_id']] += 1
                input_privacy.append(edge['privacy'])
            else:
                source = sources.get(binding['source_id'])
                require(source is not None and source[0] == binding['source_type'],
                        'Unknown output plan input source')
                require(_contract_matches(source[1], port),
                        'Incompatible output plan input contract')
                source_uses[binding['source_id']] += 1
                input_privacy.append(source[1]['privacy'])
        for port_id, port in ports.items():
            require(port['min_items'] <= counts[port_id] <= port['max_items'],
                    'Output plan input cardinality is outside capability limits')
        require(step['privacy'] == _most_private(input_privacy),
                'Output plan step privacy differs from its inputs')

    require(all(count == 1 for count in edge_uses.values()),
            'Every output plan edge must have exactly one destination binding')
    require(all(count > 0 for count in source_uses.values()),
            'Output plan contains an unused source')

    indegree = {step_id: 0 for step_id in steps}
    for destinations in outgoing.values():
        for destination in destinations:
            indegree[destination] += 1
    ready = sorted(step_id for step_id, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        step_id = ready.pop(0)
        visited += 1
        for destination in sorted(outgoing[step_id]):
            indegree[destination] -= 1
            if indegree[destination] == 0:
                ready.append(destination)
                ready.sort()
    require(visited == len(steps), 'Output plan graph contains a cycle')

    all_privacy = [source['privacy'] for _, source in sources.values()]
    all_privacy += [step['privacy'] for step in steps.values()]
    require(value['privacy'] == _most_private(all_privacy),
            'Output plan privacy differs from its inputs and steps')
    return value


def canonical_output_plan(value, catalog, policy):
    parsed = validate_output_plan(
        json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(),
        catalog, policy)
    return (json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode()
