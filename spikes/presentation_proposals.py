# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Materialize an untrusted model proposal without writing a project artifact."""
import copy
import hashlib
from uuid import NAMESPACE_URL, uuid5

from spikes.metadata import require, uuid
from spikes.presentation_documents import (PresentationDocuments, encode_deck,
                                           layout_presets, new_slide, relink,
                                           validate_deck)


def _text(value, name, limit, *, multiline=False):
    require(isinstance(value, str) and bool(value.strip()) and '\0' not in value
            and len(value.encode('utf-8')) <= limit, f'Invalid {name}')
    require(multiline or '\r' not in value and '\n' not in value, f'Invalid {name}')
    return value.strip()


def _parse(value):
    fields = {'schema_version', 'kind', 'operation', 'target_artifact_id', 'title',
              'source_artifact_ids', 'slides'}
    require(isinstance(value, dict) and set(value) == fields
            and value.get('schema_version') == 1
            and value.get('kind') == 'presentation-proposal'
            and value.get('operation') in {'create', 'update'},
            'Invalid presentation proposal')
    operation = value['operation']
    target = value['target_artifact_id']
    require((operation == 'create' and target is None)
            or (operation == 'update' and isinstance(target, str)),
            'Invalid presentation proposal target')
    if target is not None:
        uuid(target)
    sources = value['source_artifact_ids']
    require(isinstance(sources, list) and len(sources) == len(set(sources)),
            'Presentation sources must be a unique list')
    for source in sources:
        uuid(source)
    slides = value['slides']
    require(isinstance(slides, list) and 1 <= len(slides) <= 100,
            'Presentation proposal must contain 1-100 slides')
    parsed = []
    slide_fields = {'slide_id', 'title', 'bullets', 'notes', 'layout'}
    for slide in slides:
        require(isinstance(slide, dict) and set(slide) == slide_fields,
                'Invalid presentation slide proposal')
        slide_id = slide['slide_id']
        require((operation == 'create' and slide_id is None)
                or (operation == 'update' and isinstance(slide_id, str)),
                'Invalid proposed slide ID')
        if slide_id is not None:
            uuid(slide_id)
        bullets = slide['bullets']
        require(isinstance(bullets, list) and len(bullets) <= 12,
                'Invalid proposed slide bullets')
        parsed.append(dict(slide_id=slide_id,
            title=_text(slide['title'], 'proposed slide title', 200),
            bullets=[_text(item, 'proposed bullet', 500, multiline=True)
                     for item in bullets],
            notes=(_text(slide['notes'], 'proposed notes', 10000, multiline=True)
                   if slide['notes'] else ''),
            layout=_text(slide['layout'], 'proposed layout', 64)))
    ids = [item['slide_id'] for item in parsed if item['slide_id'] is not None]
    require(len(ids) == len(set(ids)), 'Proposed slide IDs must be unique')
    return dict(operation=operation, target_artifact_id=target,
                title=_text(value['title'], 'presentation title', 200),
                source_artifact_ids=sources, slides=parsed)


def _apply_content(slide, proposal, templates):
    template = templates.get(proposal['layout'])
    require(template is not None, 'Proposed slide uses an unavailable layout')
    slide.update(title=proposal['title'], bullets=proposal['bullets'],
                 notes=proposal['notes'], layout=proposal['layout'],
                 background=template['background'], foreground=template['foreground'])
    slide['column_break'] = (len(slide['bullets']) + 1) // 2 if template['preset'] == 'two-column' else 0


def materialize_presentation_proposal(value, *, task_id, project_id, base_revision,
                                      selected_artifact_ids, node_path):
    """Return a validated durable preview; this function never saves the deck."""
    proposal = _parse(value)
    uuid(task_id); uuid(project_id)
    selected = set(selected_artifact_ids)
    require(set(proposal['source_artifact_ids']) <= selected,
            'Presentation proposal cited an unavailable source')
    if proposal['operation'] == 'create':
        templates = layout_presets()
        by_layout = {item['id']: item for item in templates}
        slides = []
        for index, item in enumerate(proposal['slides']):
            slide = new_slide()
            slide['id'] = str(uuid5(NAMESPACE_URL, f'fpw:presentation:{task_id}:{index}'))
            _apply_content(slide, item, by_layout)
            slides.append(slide)
        deck = {'version': 1, 'title': proposal['title'], 'templates': templates,
                'slides': slides}
        relink(deck, [item['id'] for item in slides])
    else:
        target = proposal['target_artifact_id']
        require(target in selected and target in proposal['source_artifact_ids'],
                'Updated presentation must be an explicitly selected source')
        view = PresentationDocuments(node_path).open(project_id)
        require(view['commit_id'] == base_revision,
                'Project changed while preparing presentation proposal')
        document = next((item for item in view['documents']
                         if item['id'] == target and 'deck' in item), None)
        require(document is not None, 'Selected presentation is unavailable')
        deck = copy.deepcopy(document['deck'])
        deck['title'] = proposal['title']
        templates = {item['id']: item for item in deck['templates']}
        main = {item['id']: item for item in deck['slides'] if item['kind'] == 'main'}
        for item in proposal['slides']:
            require(item['slide_id'] in main,
                    'Presentation proposal references an unavailable main slide')
            _apply_content(main[item['slide_id']], item, templates)
    deck = validate_deck(deck)
    markdown = encode_deck(deck)
    digest = hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    return {'schema_version': 1, 'kind': 'presentation-draft',
            'operation': proposal['operation'],
            'target_artifact_id': proposal['target_artifact_id'],
            'source_artifact_ids': proposal['source_artifact_ids'],
            'base_revision': base_revision, 'deck': deck, 'deck_sha256': digest}
