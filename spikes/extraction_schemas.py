# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed v1 extraction schema catalog and strict model-output validation."""
import json

from spikes.metadata import ValidationError, pairs, require, uuid


MAX_PREVIEW = 1024 * 1024
CATALOG = {
    ('facts', 'facts-v1'): ('statement',),
    ('action-items', 'action-items-v1'): ('title', 'details'),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def validate_schema(schema_id, revision):
    require((schema_id, revision) in CATALOG, 'Unsupported extraction schema')
    return CATALOG[(schema_id, revision)]


def instruction(schema_id, revision):
    fields = validate_schema(schema_id, revision)
    item = ', '.join(f'"{field}": "..."' for field in fields)
    return (f'Extract only information supported by the supplied sources. Return exactly one JSON '
            f'object with schema "{revision}" and items. Each item must contain exactly {item}, '
            'and "source_ids": ["..."] referencing the supplied source UUIDs. Return JSON only, '
            'without Markdown fences, commentary, inferred sources, or additional fields.')


def validate_preview(raw, schema_id, revision, selected_source_ids):
    require(isinstance(raw, str), 'Extraction response must be UTF-8 JSON text')
    encoded = raw.encode('utf-8')
    require(0 < len(encoded) <= MAX_PREVIEW, 'Extraction response exceeds 1 MiB')
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, 'Non-finite JSON number'))
    except (ValueError, RecursionError) as exc:
        raise ValidationError('Extraction response is not strict JSON') from exc
    fields = validate_schema(schema_id, revision)
    require(isinstance(value, dict) and set(value) == {'schema', 'items'}
            and value['schema'] == revision and isinstance(value['items'], list)
            and len(value['items']) <= 128, 'Invalid extraction envelope')
    require(isinstance(selected_source_ids, list) and bool(selected_source_ids),
            'Extraction source selection is required')
    order = {value: index for index, value in enumerate(selected_source_ids)}
    require(len(order) == len(selected_source_ids), 'Extraction sources must be unique')
    item_keys = set(fields) | {'source_ids'}
    for item in value['items']:
        require(isinstance(item, dict) and set(item) == item_keys,
                'Invalid extraction item fields')
        for field in fields:
            text = item[field]
            limit = 200 if field == 'title' else 4096
            require(isinstance(text, str) and bool(text.strip()) and '\0' not in text
                    and len(text.encode('utf-8')) <= limit,
                    f'Invalid extraction {field}')
        sources = item['source_ids']
        require(isinstance(sources, list) and bool(sources)
                and len(sources) == len(set(sources)),
                'Extraction source references must be non-empty and unique')
        for source_id in sources:
            uuid(source_id)
            require(source_id in order, 'Extraction references an unselected source')
        require([order[source_id] for source_id in sources]
                == sorted(order[source_id] for source_id in sources),
                'Extraction source references must follow selection order')
    return canonical(value).decode('utf-8')
