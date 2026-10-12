# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Portable output capability descriptors and a static fail-closed catalog."""
from copy import deepcopy
import json
from pathlib import Path
import re
import stat

from spikes.metadata import MAX_METADATA, parse_json, require
from spikes.module_manifest import (BOUNDARIES, IDENTIFIER, LIMIT_NAME, PRIVACY,
                                    SCHEMA_REF, VERSION)


MAX_DESCRIPTORS = 64
MAX_ITEMS = 32
MAX_TEXT = 512
HASH = re.compile(r'[0-9a-f]{64}')
MIME = re.compile(r'[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*')
KINDS = {'renderer', 'transformation', 'computation'}
OUTPUT_KINDS = {'web', 'presentation', 'image', 'report', 'table', 'chart', 'data'}
COST_CLASSES = {'none', 'local-compute', 'metered-external'}
SIDE_EFFECTS = {'none', 'local', 'external'}
CONFIRMATIONS = {'before-execution', 'before-external-effect', 'before-publication'}
REVIEWED_CATALOG = Path(__file__).resolve().parents[1] / 'modules' / 'output-capabilities'


def _fields(value, required, *, name):
    require(isinstance(value, dict), f'Output {name} must be an object')
    require(value.keys() == required, f'Unknown or missing output {name} field')


def _identifier(value, field):
    require(isinstance(value, str) and bool(IDENTIFIER.fullmatch(value)),
            f'Invalid output {field}')


def _version(value, field, *, patch=False):
    require(isinstance(value, str) and bool(VERSION.fullmatch(value))
            and (not patch or value.count('.') == 2), f'Invalid output {field}')


def _text(value, field):
    require(isinstance(value, str) and value.strip() == value
            and 0 < len(value) <= MAX_TEXT and '\0' not in value,
            f'Invalid output {field}')


def _list(value, field, *, allow_empty=False, maximum=MAX_ITEMS):
    require(isinstance(value, list) and len(value) <= maximum
            and (allow_empty or bool(value)), f'Invalid output {field}')
    return value


def _identifier_list(value, field, *, allow_empty=False, allowed=None):
    _list(value, field, allow_empty=allow_empty)
    for item in value:
        _identifier(item, field)
    require(len(value) == len(set(value)), f'Duplicate output {field}')
    if allowed is not None:
        require(set(value) <= allowed, f'Unsupported output {field}')


def _text_list(value, field):
    _list(value, field)
    for item in value:
        _text(item, field)
    require(len(value) == len(set(value)), f'Duplicate output {field}')


def _schema(value, module_id, field):
    require(isinstance(value, str) and bool(SCHEMA_REF.fullmatch(value))
            and value.startswith(f'module://{module_id}/schemas/'),
            f'Invalid output {field}')


def _port(value, module_id, *, output=False):
    required = {'port_id', 'schema', 'mime_types', 'format'}
    if not output:
        required |= {'min_items', 'max_items'}
    _fields(value, required, name='port')
    _identifier(value['port_id'], 'port ID')
    _schema(value['schema'], module_id, 'port schema')
    _list(value['mime_types'], 'MIME types')
    require(all(isinstance(item, str) and bool(MIME.fullmatch(item))
                for item in value['mime_types']), 'Invalid output MIME type')
    require(len(value['mime_types']) == len(set(value['mime_types'])),
            'Duplicate output MIME type')
    _identifier(value['format'], 'port format')
    if not output:
        require(type(value['min_items']) is int and type(value['max_items']) is int
                and 0 <= value['min_items'] <= value['max_items'] <= 1024,
                'Invalid output port cardinality')


def _reference(value, module_id, *, instruction=False):
    required = {'id', 'version', 'sha256', 'reference'}
    if instruction:
        required |= {'output_schema'}
    _fields(value, required, name='reference')
    _identifier(value['id'], 'reference ID')
    _version(value['version'], 'reference version')
    require(isinstance(value['sha256'], str) and bool(HASH.fullmatch(value['sha256'])),
            'Invalid output reference hash')
    prefix = f'module://{module_id}/'
    require(isinstance(value['reference'], str) and value['reference'].startswith(prefix)
            and '..' not in value['reference'] and '\\' not in value['reference'],
            'Invalid output reference')
    if instruction:
        _schema(value['output_schema'], module_id, 'instruction output schema')


def _role_requirement(value):
    _fields(value, {'id', 'revision'}, name='role requirement')
    _identifier(value['id'], 'required role ID')
    _identifier(value['revision'], 'required role revision')


def _backend_requirement(value):
    _fields(value, {'operation', 'revision', 'output_format'},
            name='backend capability requirement')
    for field in ('operation', 'revision', 'output_format'):
        _identifier(value[field], f'backend {field}')


def parse_output_capability(data):
    """Validate a portable declaration; runtime bindings and secrets are excluded."""
    value = parse_json(data)
    required = {
        'schema_version', 'capability_id', 'capability_version', 'module', 'kind',
        'output_kind', 'display_name', 'description', 'supported_intents',
        'instruction_examples', 'unsupported_uses', 'inputs', 'output', 'templates',
        'instruction_templates', 'required_roles', 'required_backend_capabilities',
        'limits', 'privacy', 'execution_boundary', 'permissions', 'cost_class',
        'side_effect', 'provenance_required', 'preview_required', 'confirmations',
    }
    _fields(value, required, name='capability descriptor')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported output capability schema')
    _identifier(value['capability_id'], 'capability ID')
    _version(value['capability_version'], 'capability version')
    _fields(value['module'], {'id', 'version'}, name='module')
    module_id = value['module']['id']
    _identifier(module_id, 'module ID')
    _version(value['module']['version'], 'module version', patch=True)
    require(value['kind'] in KINDS, 'Unsupported output capability kind')
    require(value['output_kind'] in OUTPUT_KINDS, 'Unsupported output kind')
    require(value['kind'] != 'renderer'
            or value['output_kind'] in {'web', 'presentation', 'image', 'report'},
            'Renderer declares an incompatible output kind')
    require(value['kind'] == 'renderer'
            or value['output_kind'] in {'image', 'table', 'chart', 'data'},
            'Tool declares an incompatible output kind')
    for field in ('display_name', 'description'):
        _text(value[field], field)
    _identifier_list(value['supported_intents'], 'supported intent')
    _text_list(value['instruction_examples'], 'instruction example')
    _text_list(value['unsupported_uses'], 'unsupported use')
    _list(value['inputs'], 'input ports')
    for port in value['inputs']:
        _port(port, module_id)
    input_ids = [port['port_id'] for port in value['inputs']]
    require(len(input_ids) == len(set(input_ids)), 'Duplicate output input port')
    _port(value['output'], module_id, output=True)
    for field, instruction in (('templates', False), ('instruction_templates', True)):
        _list(value[field], field, allow_empty=True)
        for reference in value[field]:
            _reference(reference, module_id, instruction=instruction)
        keys = [(item['id'], item['version']) for item in value[field]]
        require(len(keys) == len(set(keys)), f'Duplicate output {field}')
    for field, validator in (('required_roles', _role_requirement),
                             ('required_backend_capabilities', _backend_requirement)):
        _list(value[field], field, allow_empty=True)
        for requirement in value[field]:
            validator(requirement)
        keys = [tuple(sorted(item.items())) for item in value[field]]
        require(len(keys) == len(set(keys)), f'Duplicate output {field}')
    require(isinstance(value['limits'], dict) and 0 < len(value['limits']) <= 16,
            'Invalid output limits')
    for name, limit in value['limits'].items():
        require(isinstance(name, str) and bool(LIMIT_NAME.fullmatch(name)),
                'Invalid output limit name')
        require(type(limit) is int and 0 < limit <= 2 ** 31 - 1,
                'Invalid output limit')
    _identifier_list(value['privacy'], 'privacy class', allowed=PRIVACY)
    require(value['execution_boundary'] in BOUNDARIES,
            'Unsupported output execution boundary')
    _identifier_list(value['permissions'], 'permission')
    require(value['cost_class'] in COST_CLASSES, 'Unsupported output cost class')
    require(value['side_effect'] in SIDE_EFFECTS, 'Unsupported output side effect')
    require(type(value['provenance_required']) is bool
            and type(value['preview_required']) is bool,
            'Output provenance and preview flags must be boolean')
    _identifier_list(value['confirmations'], 'confirmation', allow_empty=True,
                     allowed=CONFIRMATIONS)
    require(value['side_effect'] != 'external'
            or 'before-external-effect' in value['confirmations'],
            'External output effect requires separate confirmation')
    require(not value['preview_required'] or 'before-execution' in value['confirmations'],
            'Previewed output requires execution confirmation')
    return value


def read_output_capability(path):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), 'Output capability must be a regular file')
    with path.open('rb') as handle:
        data = handle.read(MAX_METADATA + 1)
    require(len(data) <= MAX_METADATA, 'Output capability exceeds 64 KiB')
    return parse_output_capability(data)


def canonical_output_capability(value):
    parsed = parse_output_capability(
        json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
    return (json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode()


class OutputCapabilityCatalog:
    """Immutable-by-copy registry; resolution never falls back across revisions."""
    def __init__(self, descriptors):
        require(isinstance(descriptors, list) and 0 < len(descriptors) <= MAX_DESCRIPTORS,
                'Invalid output capability catalog')
        self._descriptors = {}
        for descriptor in descriptors:
            parsed = parse_output_capability(canonical_output_capability(descriptor))
            key = (parsed['capability_id'], parsed['capability_version'])
            require(key not in self._descriptors, 'Duplicate output capability')
            self._descriptors[key] = parsed

    def resolve(self, capability_id, capability_version):
        descriptor = self._descriptors.get((capability_id, capability_version))
        require(descriptor is not None, 'Unsupported output capability or version')
        return deepcopy(descriptor)

    def list(self):
        return [deepcopy(self._descriptors[key]) for key in sorted(self._descriptors)]


def load_output_catalog(directory):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(),
            'Output capability catalog must be a regular directory')
    entries = sorted(directory.iterdir(), key=lambda path: path.name)
    require(0 < len(entries) <= MAX_DESCRIPTORS, 'Invalid output capability catalog')
    descriptors = []
    for path in entries:
        require(path.name.endswith('.output-capability.json'),
                'Unexpected output capability catalog entry')
        descriptors.append(read_output_capability(path))
    return OutputCapabilityCatalog(descriptors)


def reviewed_output_catalog():
    return load_output_catalog(REVIEWED_CATALOG)
