# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
import json
import yaml

ENTITY = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
AUTHOR = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def metadata(title='Test', entity_id=ENTITY, **extra):
    return dict(schema_version=1, id=entity_id, title=title, kind='document',
                created_at='2026-09-09T12:00:00Z', author_id=AUTHOR,
                privacy='project', provenance='user', **extra)


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def markdown(meta=None):
    return ('---\n' + yaml.safe_dump(meta or metadata(), sort_keys=True) + '---\nObsah.\n').encode()


def source(content=b'%PDF-1.7\x00\xff\r\n', name='source.pdf'):
    meta = metadata(file=name)
    meta.update(kind='source', provenance='external')
    return {f'artifacts/{ENTITY}/{name}': content,
            f'artifacts/{ENTITY}/metadata.json': encoded(meta)}


def registry(title='Test', entity_id=ENTITY):
    meta = metadata(title, entity_id)
    meta.update(kind='decisions', status='proposed', body='Decision body')
    return encoded(meta)
