# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Strict manifest and same-node API compatibility check for external modules."""
import ipaddress
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from spikes.metadata import MAX_METADATA, ValidationError, parse_json, require


MAX_CAPABILITIES = 64
MAX_LIST_ITEMS = 64
IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*')
LIMIT_NAME = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*')
VERSION = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?')
SCHEMA_REF = re.compile(r'module://[a-z][a-z0-9.-]*/schemas/[A-Za-z0-9][A-Za-z0-9._-]*\.json')
PRIVACY = {'public', 'project', 'confidential', 'local-only'}
BOUNDARIES = {'same-process', 'same-node', 'private-network', 'external-service'}
IDEMPOTENCY = {'read-only', 'idempotency-key', 'operation-id'}
SIDE_EFFECTS = {'none', 'local', 'external'}
STATES = {'completed', 'failed', 'unknown'}


def _fields(value, required, optional=frozenset(), *, name='object'):
    require(isinstance(value, dict), f'Module {name} must be an object')
    require(required <= value.keys(), f'Missing module {name} field')
    require(value.keys() <= required | optional, f'Unknown module {name} field')


def _identifier(value, field):
    require(isinstance(value, str) and bool(IDENTIFIER.fullmatch(value)),
            f'Invalid {field}')


def _version(value, field, *, patch=False):
    require(isinstance(value, str) and bool(VERSION.fullmatch(value)),
            f'Invalid {field}')
    require(not patch or value.count('.') == 2, f'{field} must use major.minor.patch')


def _string_list(value, field, *, allowed=None):
    require(isinstance(value, list) and 0 < len(value) <= MAX_LIST_ITEMS,
            f'Invalid {field}')
    require(all(isinstance(item, str) and bool(item) for item in value),
            f'Invalid {field}')
    require(len(value) == len(set(value)), f'Duplicate {field}')
    if allowed is not None:
        require(set(value) <= allowed, f'Unsupported {field}')


def _capability(value, module_id):
    required = {
        'id', 'version', 'input_schema', 'output_schema', 'permissions',
        'privacy', 'execution_boundary', 'limits', 'idempotency',
        'side_effect', 'states', 'errors', 'provenance_required',
    }
    _fields(value, required, name='capability')
    _identifier(value['id'], 'capability id')
    _version(value['version'], 'capability version')
    for field in ('input_schema', 'output_schema'):
        require(isinstance(value[field], str) and bool(SCHEMA_REF.fullmatch(value[field])),
                f'Invalid {field}')
        require(value[field].startswith(f'module://{module_id}/schemas/'),
                f'{field} belongs to a different module')
    _string_list(value['permissions'], 'permissions')
    for permission in value['permissions']:
        _identifier(permission, 'permission')
    _string_list(value['privacy'], 'privacy classes', allowed=PRIVACY)
    require(value['execution_boundary'] in BOUNDARIES, 'Unsupported execution boundary')
    require(isinstance(value['limits'], dict) and 0 < len(value['limits']) <= 16,
            'Invalid capability limits')
    for name, limit in value['limits'].items():
        require(isinstance(name, str) and bool(LIMIT_NAME.fullmatch(name)),
                'Invalid limit name')
        require(type(limit) is int and 0 < limit <= 2 ** 31 - 1,
                'Invalid capability limit')
    require(value['idempotency'] in IDEMPOTENCY, 'Unsupported idempotency model')
    require(value['side_effect'] in SIDE_EFFECTS, 'Unsupported side effect')
    _string_list(value['states'], 'states', allowed=STATES)
    _string_list(value['errors'], 'errors')
    for error in value['errors']:
        _identifier(error, 'error')
    require(value['side_effect'] != 'external' or 'unknown' in value['states'],
            'External side effects must declare unknown')
    require(type(value['provenance_required']) is bool,
            'provenance_required must be boolean')
    return value


def parse_module_manifest(data):
    """Validate one portable declaration; it must not contain endpoint credentials."""
    value = parse_json(data)
    required = {
        'schema_version', 'module_id', 'display_name', 'module_version',
        'roadmap', 'api', 'capabilities', 'dependencies',
    }
    _fields(value, required, name='manifest')
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported module manifest version')
    _identifier(value['module_id'], 'module_id')
    require(isinstance(value['display_name'], str) and 0 < len(value['display_name'].strip()) <= 128,
            'Invalid display_name')
    _version(value['module_version'], 'module_version', patch=True)
    require(value['roadmap'] == 'ROADMAP.md', 'Module roadmap must remain in its repository')
    _fields(value['api'], {'name', 'version', 'manifest_path'}, name='API')
    require(value['api']['name'] == 'workspace-module-api', 'Unsupported module API')
    _version(value['api']['version'], 'API version')
    require(value['api']['manifest_path'] == '/v1/module/manifest',
            'Unsupported module manifest endpoint')
    require(isinstance(value['dependencies'], list) and len(value['dependencies']) <= MAX_LIST_ITEMS,
            'Invalid module dependencies')
    require(all(isinstance(item, str) and bool(IDENTIFIER.fullmatch(item))
                for item in value['dependencies']), 'Invalid module dependency')
    require(len(value['dependencies']) == len(set(value['dependencies'])),
            'Duplicate module dependency')
    capabilities = value['capabilities']
    require(isinstance(capabilities, list) and 0 < len(capabilities) <= MAX_CAPABILITIES,
            'Invalid capabilities')
    for capability in capabilities:
        _capability(capability, value['module_id'])
    keys = [(item['id'], item['version']) for item in capabilities]
    require(len(keys) == len(set(keys)), 'Duplicate module capability')
    return value


def read_module_manifest(path):
    path = Path(path)
    with path.open('rb') as handle:
        data = handle.read(MAX_METADATA + 1)
    require(len(data) <= MAX_METADATA, 'Module manifest exceeds 64 KiB')
    return parse_module_manifest(data)


def verify_module_api(expected, actual_data):
    """Fail closed unless the API reports exactly the reviewed declaration."""
    actual = parse_module_manifest(actual_data)
    require(actual == expected, 'Module API manifest differs from the reviewed manifest')
    return actual


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _same_node_url(base_url, manifest_path):
    require(isinstance(base_url, str) and len(base_url) <= 512, 'Invalid module API URL')
    parsed = urlsplit(base_url)
    require(parsed.scheme == 'http' and parsed.username is None and parsed.password is None,
            'Module API v1 requires credential-free same-node HTTP')
    require(not parsed.query and not parsed.fragment and parsed.path in {'', '/'},
            'Module API base URL must not contain path, query, or fragment')
    require(parsed.hostname is not None and parsed.port is not None,
            'Module API URL requires an explicit host and port')
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError as exc:
        raise ValidationError('Module API v1 requires a literal loopback address') from exc
    require(loopback, 'Module API v1 is restricted to the same node')
    host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
    return f'http://{host}:{parsed.port}{manifest_path}'


def fetch_and_verify_module(manifest_path, base_url, *, timeout=3.0):
    expected = read_module_manifest(manifest_path)
    url = _same_node_url(base_url, expected['api']['manifest_path'])
    request = Request(url, headers={'Accept': 'application/json'}, method='GET')
    try:
        with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            require(response.status == 200, 'Module API manifest request failed')
            content_type = response.headers.get_content_type()
            require(content_type == 'application/json', 'Module API manifest must be JSON')
            data = response.read(MAX_METADATA + 1)
    except HTTPError as exc:
        exc.close()
        raise ValidationError('Module API manifest is unavailable') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValidationError('Module API manifest is unavailable') from exc
    require(len(data) <= MAX_METADATA, 'Module API manifest exceeds 64 KiB')
    return verify_module_api(expected, data)


def canonical_manifest(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
