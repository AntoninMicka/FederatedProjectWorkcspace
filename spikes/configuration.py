"""Read-only executable v1 schemas for portable project and local node metadata."""
import os
from pathlib import Path
import re
import stat

from spikes.metadata import MAX_METADATA, parse_json, require, timestamp, uuid


def fields(value, required, optional=frozenset()):
    require(isinstance(value, dict), 'Configuration must be an object')
    require(required <= value.keys(), 'Missing required configuration field')
    require(value.keys() <= required | optional, 'Unknown configuration field')


def header(value, required, optional=frozenset()):
    fields(value, required | {'schema_version', 'id'}, optional)
    require(type(value['schema_version']) is int and value['schema_version'] == 1,
            'Unsupported configuration version; explicit migration required')
    uuid(value['id'])


def text(value):
    require(isinstance(value, str) and bool(value.strip()), 'Expected non-empty text')


def parse_project(data):
    meta = parse_json(data)
    header(meta, {'title', 'created_at', 'author_id'}, {'description'})
    text(meta['title'])
    timestamp(meta['created_at'])
    uuid(meta['author_id'])
    if 'description' in meta:
        require(isinstance(meta['description'], str), 'Description must be text')
    return meta


def local_path(value):
    text(value)
    path = Path(value)
    require(path.is_absolute() and path != Path('/'), 'Expected absolute local directory path')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and not {'..', '.git'} & set(path.parts), 'Unsafe local directory path')
    # Existing symlink prefixes must not disguise overlap. This creates nothing.
    return path.resolve()


def overlap(first, second):
    return first.is_relative_to(second) or second.is_relative_to(first)


def parse_node(data, *, location):
    meta = parse_json(data)
    header(meta, {'name', 'projects'}, {'identity_credential_ref'})
    text(meta['name'])
    require(isinstance(meta['projects'], list), 'Projects must be a list')
    if 'identity_credential_ref' in meta:
        ref = meta['identity_credential_ref']
        require(isinstance(ref, str) and re.fullmatch(r'credential:[A-Za-z0-9][A-Za-z0-9._-]{0,127}', ref),
                'Expected opaque credential reference, not secret material')
    ids, paths, roots = set(), [], []
    for project in meta['projects']:
        fields(project, {'project_id', 'root', 'state_dir'})
        uuid(project['project_id'])
        require(project['project_id'] not in ids, 'Duplicate registered project ID')
        ids.add(project['project_id'])
        root, state = local_path(project['root']), local_path(project['state_dir'])
        roots.append(root)
        for path in (root, state):
            require(not any(overlap(path, previous) for previous in paths),
                    'Project roots and state directories must be disjoint')
            paths.append(path)
    config = Path(location).resolve()
    require(not any(overlap(config, root) for root in roots), 'Node configuration must be outside projects')
    return meta


def read_config(path):
    """Bound the read itself; refuse symlink files and non-regular inputs on Linux."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'Configuration must be a regular file')
        data = handle.read(MAX_METADATA + 1)
    require(len(data) <= MAX_METADATA, 'Configuration exceeds 64 KiB')
    return data
