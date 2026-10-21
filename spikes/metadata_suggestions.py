# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict metadata-advisor snapshot, output validation and diff projection."""
import json

from spikes.metadata import ValidationError, pairs, require


MAX_PREVIEW = 1024 * 1024
SCHEMA = 'metadata-suggestions-v1'
FIELDS = ('title', 'description', 'tags', 'kind', 'privacy', 'provenance')
INSTRUCTION = ('Suggest a concise description and useful tags for the supplied artifact. '
    'The second input is the current metadata snapshot. Preserve its meaning and return exactly '
    'one JSON object with schema "metadata-suggestions-v1", description as a string or null, '
    'and tags as an array of strings. Return JSON only, without Markdown or additional fields.')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def snapshot(meta):
    require(isinstance(meta, dict), 'Invalid artifact metadata')
    value = {field: meta.get(field) for field in FIELDS}
    value['description'] = value['description'] if value['description'] is not None else ''
    value['tags'] = value['tags'] if value['tags'] is not None else []
    require(all(isinstance(value[field], str) for field in
                ('title', 'description', 'kind', 'privacy', 'provenance'))
            and isinstance(value['tags'], list)
            and all(isinstance(tag, str) for tag in value['tags']),
            'Invalid artifact metadata snapshot')
    return value


def validate_preview(raw):
    require(isinstance(raw, str), 'Metadata suggestion must be UTF-8 JSON text')
    require(0 < len(raw.encode()) <= MAX_PREVIEW, 'Metadata suggestion exceeds 1 MiB')
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, 'Non-finite JSON number'))
    except (ValueError, RecursionError) as exc:
        raise ValidationError('Metadata suggestion is not strict JSON') from exc
    require(isinstance(value, dict) and set(value) == {'schema', 'description', 'tags'}
            and value['schema'] == SCHEMA, 'Invalid metadata suggestion envelope')
    description = value['description']
    require(description is None or (isinstance(description, str)
            and description.strip() == description and bool(description)
            and '\0' not in description and len(description.encode()) <= 4096),
            'Invalid suggested description')
    tags = value['tags']
    require(isinstance(tags, list) and len(tags) <= 16, 'Invalid suggested tags')
    folded = []
    for tag in tags:
        require(isinstance(tag, str) and tag.strip() == tag and bool(tag)
                and not any(ord(char) < 32 or ord(char) == 127 for char in tag)
                and len(tag.encode()) <= 64, 'Invalid suggested tag')
        folded.append(tag.casefold())
    require(len(folded) == len(set(folded)), 'Duplicate suggested tag')
    return canonical(value).decode()


def project_diff(original, proposed):
    current = snapshot(original)
    value = json.loads(validate_preview(proposed)) if isinstance(proposed, str) else proposed
    existing = {tag.casefold() for tag in current['tags']}
    additions = [tag for tag in value['tags'] if tag.casefold() not in existing]
    return {'description': {'before': current['description'], 'after': value['description'],
                            'changed': value['description'] is not None
                                       and value['description'] != current['description']},
            'tags': {'existing': current['tags'], 'suggested_additions': additions}}
