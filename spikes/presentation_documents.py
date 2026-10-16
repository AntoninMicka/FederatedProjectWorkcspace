# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Versioned basic decks stored through the existing document transaction boundary."""
import base64
import copy
import json
import re
import struct
from uuid import uuid4

import yaml

from spikes.artifacts import Artifacts
from spikes.configuration import committed_project
from spikes.markdown_documents import MAX_EDITOR, document
from spikes.metadata import (StrictLoader, ValidationError, require, uuid,
                             validate_snapshot)

LEGACY_PREFIX = '```fpw-presentation-v1\n'
MARKDOWN_PREFIX = '---\nformat: fpw-presentation\nformat_version: 2\n'
MAX_WALLPAPER = 256 * 1024
LAYOUT_PRESETS = (
    dict(id='title', revision=1, name='Titulní slide', preset='title',
         title_align='center', content_align='center', density='spacious',
         background='#102b36', foreground='#ffffff', accent='#79c9ac'),
    dict(id='content', revision=1, name='Nadpis a obsah', preset='title-content',
         title_align='left', content_align='left', density='normal',
         background='#102b36', foreground='#ffffff', accent='#79c9ac'),
    dict(id='two-column', revision=1, name='Dva sloupce', preset='two-column',
         title_align='left', content_align='left', density='compact',
         background='#102b36', foreground='#ffffff', accent='#79c9ac'),
    dict(id='visual', revision=1, name='Obrázek / graf', preset='visual',
         title_align='left', content_align='center', density='compact',
         background='#102b36', foreground='#ffffff', accent='#79c9ac'),
    dict(id='closing', revision=1, name='Závěrečný slide', preset='closing',
         title_align='center', content_align='right', density='spacious',
         background='#102b36', foreground='#ffffff', accent='#79c9ac'),
)


def layout_presets():
    return copy.deepcopy(list(LAYOUT_PRESETS))


def new_slide(kind='main', layout='content'):
    return dict(id=str(uuid4()), kind=kind, title='Nový slide', bullets=[], notes='',
                background='#102b36', foreground='#ffffff', wallpaper='', next=None, backups=[],
                repeat=False, reveal='all', layout=layout, column_break=0)


def new_deck():
    return dict(version=1, title='Nová prezentace', templates=layout_presets(), slides=[new_slide()])


def normalize_layouts(deck):
    """Upgrade legacy v1 decks in memory without rewriting their Git revision."""
    result = copy.deepcopy(deck)
    if 'templates' not in result:
        result['templates'] = layout_presets()
    for slide in result.get('slides', []):
        slide.setdefault('layout', 'content')
        slide.setdefault('column_break', 0)
    return result


def main_order(deck):
    main = {s['id']: s for s in deck['slides'] if s['kind'] == 'main'}
    require(bool(main), 'Prezentace musí mít alespoň jeden hlavní slide.')
    targets = set()
    for slide in main.values():
        target = slide['next']
        require(target is None or target in main, 'Next musí odkazovat na hlavní slide.')
        if target is not None:
            require(target not in targets, 'Slide nesmí mít více předchůdců.')
            targets.add(target)
    heads = set(main) - targets
    require(len(heads) == 1, 'Hlavní slidy musí tvořit jednu linii bez cyklů.')
    order, current = [], heads.pop()
    while current is not None:
        require(current not in order, 'Vazby next obsahují cyklus.')
        order.append(current)
        current = main[current]['next']
    require(len(order) == len(main), 'Některé hlavní slidy nejsou zapojené do linie.')
    return order


def relink(deck, order):
    by_id = {s['id']: s for s in deck['slides']}
    for index, id_ in enumerate(order):
        by_id[id_]['next'] = order[index + 1] if index + 1 < len(order) else None


def set_neighbor(deck, id_, target, *, previous=False):
    """Reorder the line; reciprocal previous is derived, never stored twice."""
    order = main_order(deck)
    require(id_ in order and (target is None or target in order and target != id_), 'Neplatný soused.')
    if previous:
        order.remove(id_)
        order.insert(order.index(target) + 1 if target else 0, id_)
    elif target:
        order.remove(target)
        order.insert(order.index(id_) + 1, target)
    else:
        order.remove(id_)
        order.append(id_)
    relink(deck, order)


def remove_slide(deck, id_):
    order = main_order(deck)
    require(id_ not in order or len(order) > 1, 'Poslední hlavní slide nelze odstranit.')
    deck['slides'] = [s for s in deck['slides'] if s['id'] != id_]
    relink(deck, [item for item in order if item != id_])
    for slide in deck['slides']:
        slide['backups'] = [item for item in slide['backups'] if item != id_]


def validate_wallpaper(value):
    require(isinstance(value, str) and len(value) <= MAX_WALLPAPER, 'Tapeta je příliš velká.')
    if not value:
        return
    require(value.startswith('data:image/png;base64,'), 'Tapeta musí být vložený PNG obrázek.')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    except ValueError as exc:
        raise ValueError('Neplatná tapeta.') from exc
    require(len(raw) >= 45 and raw[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', 'Neplatný PNG obrázek.')
    width, height = struct.unpack('>II', raw[16:24])
    require(0 < width <= 4096 and 0 < height <= 4096, 'Tapeta má příliš velké rozměry.')


def validate_deck(deck):
    deck = normalize_layouts(deck)
    require(isinstance(deck, dict) and deck.keys() == {'version', 'title', 'templates', 'slides'}
            and type(deck['version']) is int and deck['version'] == 1, 'Neplatný formát prezentace.')
    require(isinstance(deck['title'], str) and 0 < len(deck['title'].strip()) <= 200
            and not any(c in deck['title'] for c in '\r\n\0'), 'Vyplňte název prezentace (max. 200 znaků).')
    require(isinstance(deck['slides'], list) and 1 <= len(deck['slides']) <= 100, 'Prezentace má mít 1–100 slidů.')
    require(isinstance(deck['templates'], list) and 1 <= len(deck['templates']) <= 20,
            'Prezentace musí mít 1–20 šablon layoutu.')
    template_ids = set()
    template_fields = {'id', 'revision', 'name', 'preset', 'title_align', 'content_align',
                       'density', 'background', 'foreground', 'accent'}
    for template in deck['templates']:
        require(isinstance(template, dict) and template.keys() == template_fields,
                'Neplatná pole šablony layoutu.')
        require(isinstance(template['id'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', template['id'])
                and template['id'] not in template_ids, 'Neplatné nebo duplicitní ID šablony.')
        template_ids.add(template['id'])
        require(type(template['revision']) is int and 1 <= template['revision'] <= 1000000,
                'Nepodporovaná revize šablony.')
        require(isinstance(template['name'], str) and 0 < len(template['name'].strip()) <= 80
                and not any(c in template['name'] for c in '\r\n\0'), 'Neplatný název šablony.')
        require(template['preset'] in {'title', 'title-content', 'two-column', 'visual', 'closing'},
                'Neplatný typ layoutu.')
        require(template['title_align'] in {'left', 'center', 'right'}
                and template['content_align'] in {'left', 'center', 'right'}, 'Neplatné zarovnání layoutu.')
        require(template['density'] in {'compact', 'normal', 'spacious'}, 'Neplatná hustota layoutu.')
        for key in ('background', 'foreground', 'accent'):
            require(isinstance(template[key], str) and re.fullmatch(r'#[0-9a-fA-F]{6}', template[key]),
                    'Neplatná barva šablony.')
    seen = set()
    for slide in deck['slides']:
        required = {'id', 'kind', 'title', 'bullets', 'notes', 'background', 'foreground', 'wallpaper', 'next', 'backups'}
        require(isinstance(slide, dict) and required <= slide.keys()
                and slide.keys() <= required | {'repeat', 'reveal', 'layout', 'column_break'},
            'Neplatná pole slidu.')
        require(type(slide.get('repeat', False)) is bool, 'Opakování musí být boolean.')
        require(slide.get('reveal', 'all') in ('all', 'step'), 'Neplatný režim odrážek.')
        require(slide.get('layout', 'content') in template_ids, 'Slide odkazuje na neexistující šablonu.')
        uuid(slide['id'])
        require(slide['id'] not in seen, 'Duplicitní ID slidu.')
        seen.add(slide['id'])
        require(slide['kind'] in ('main', 'backup'), 'Neplatný typ slidu.')
        require(isinstance(slide['title'], str) and 0 < len(slide['title'].strip()) <= 200
                and not any(c in slide['title'] for c in '\r\0'), 'Vyplňte nadpis slidu.')
        require(isinstance(slide['notes'], str) and len(slide['notes']) <= 10000, 'Poznámky jsou příliš dlouhé.')
        require(isinstance(slide['bullets'], list) and len(slide['bullets']) <= 12
                and all(isinstance(b, str) and 0 < len(b.strip()) <= 500
                        and not any(c in b for c in '\r\0') for b in slide['bullets']),
                'Použijte nejvýše 12 odrážek po 500 znacích.')
        require(type(slide.get('column_break', 0)) is int and 0 <= slide.get('column_break', 0) <= len(slide['bullets']),
                'Neplatné rozdělení sloupců.')
        for key in ('background', 'foreground'):
            require(isinstance(slide[key], str) and re.fullmatch(r'#[0-9a-fA-F]{6}', slide[key]), 'Neplatná barva.')
        validate_wallpaper(slide['wallpaper'])
        require(slide['next'] is None or isinstance(slide['next'], str), 'Neplatná vazba next.')
        require(isinstance(slide['backups'], list) and all(isinstance(i, str) for i in slide['backups'])
                and len(slide['backups']) == len(set(slide['backups'])), 'Neplatné vazby backup.')
    backups = {s['id'] for s in deck['slides'] if s['kind'] == 'backup'}
    for slide in deck['slides']:
        require(set(slide['backups']) <= backups, 'Backup musí odkazovat na existující backup slide.')
        if slide['kind'] == 'backup':
            require(slide['next'] is None and not slide['backups'], 'Backup používá návrat k místu odbočení.')
    main_order(deck)
    require(len(json.dumps(deck, ensure_ascii=False).encode()) < MAX_EDITOR - 64, 'Prezentace překračuje limit 1 MiB.')
    return deck


def _yaml_dump(value):
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=1000000).rstrip()


def _yaml_load(text):
    require(isinstance(text, str) and len(text.encode('utf-8')) <= MAX_EDITOR,
            'YAML prezentace překračuje povolený limit.')
    try:
        depth = events = 0
        for event in yaml.parse(text, Loader=StrictLoader):
            events += 1
            require(events <= 20000, 'YAML prezentace je příliš složitý.')
            require(not isinstance(event, yaml.AliasEvent) and not getattr(event, 'anchor', None),
                    'YAML aliasy a kotvy nejsou podporované.')
            require(not getattr(event, 'tag', None), 'Explicitní YAML tagy nejsou podporované.')
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                require(depth <= 16, 'YAML prezentace je příliš zanořený.')
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
        return yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise ValidationError('Neplatný YAML prezentace.') from exc


def _markdown_text(lines, prefix, continuation):
    parts = lines.split('\n')
    return prefix + parts[0] + ''.join('\n' + continuation + part for part in parts[1:])


def encode_deck(deck):
    """Serialize the validated model as readable Markdown format v2."""
    deck = validate_deck(deck)
    template_fields = ('id', 'revision', 'name', 'preset', 'title_align',
                       'content_align', 'density', 'background', 'foreground', 'accent')
    templates = [{key: item[key] for key in template_fields}
                 for item in deck['templates']]
    front = dict(format='fpw-presentation', format_version=2,
                 deck=dict(version=deck['version'], title=deck['title'], templates=templates))
    sections = ['---\n' + _yaml_dump(front) + '\n---\n']
    metadata_fields = ('id', 'kind', 'notes', 'background', 'foreground', 'wallpaper',
                       'next', 'backups', 'layout', 'column_break')
    for slide in deck['slides']:
        metadata = {key: copy.deepcopy(slide[key]) for key in metadata_fields}
        for key in ('repeat', 'reveal'):
            if key in slide:
                metadata[key] = copy.deepcopy(slide[key])
        sections.append('\n```fpw-slide\n' + _yaml_dump(metadata) + '\n```\n'
                        + _markdown_text(slide['title'], '## ', '   ') + '\n\n'
                        + '\n'.join(_markdown_text(item, '- ', '  ') for item in slide['bullets']) + '\n')
    result = ''.join(sections)
    require(len(result.encode('utf-8')) < MAX_EDITOR, 'Prezentace překračuje limit 1 MiB.')
    return result


def _parse_markdown_content(text):
    lines = text.split('\n')
    while lines and lines[-1] == '':
        lines.pop()
    require(lines and lines[0].startswith('## '), 'Slide musí začínat nadpisem druhé úrovně.')
    title = lines[0][3:]
    index = 1
    while index < len(lines) and lines[index].startswith('   '):
        title += '\n' + lines[index][3:]
        index += 1
    require(index == len(lines) or lines[index] == '', 'Za nadpisem slidu musí následovat prázdný řádek.')
    if index < len(lines):
        index += 1
    bullets = []
    for line in lines[index:]:
        if line.startswith('- '):
            bullets.append(line[2:])
        elif line.startswith('  ') and bullets:
            bullets[-1] += '\n' + line[2:]
        else:
            require(False, 'Obsah slidu smí obsahovat pouze Markdown odrážky.')
    return title, bullets


def _decode_markdown(body):
    require(body.startswith('---\n'), 'Prezentace nemá YAML frontmatter.')
    end = body.find('\n---\n', 4)
    require(end >= 0, 'YAML frontmatter prezentace není uzavřený.')
    front = _yaml_load(body[4:end])
    require(isinstance(front, dict) and front.keys() == {'format', 'format_version', 'deck'}
            and front['format'] == 'fpw-presentation' and front['format_version'] == 2,
            'Neplatný frontmatter prezentace.')
    deck_header = front['deck']
    require(isinstance(deck_header, dict) and deck_header.keys() == {'version', 'title', 'templates'},
            'Neplatná metadata decku.')
    rest = body[end + 5:]
    require(rest.startswith('\n```fpw-slide\n'), 'Prezentace neobsahuje žádný slide.')
    chunks = re.split(r'(?=^```fpw-slide\n)', rest[1:], flags=re.MULTILINE)
    require(chunks.pop(0) == '', 'Neplatný obsah před prvním slidem.')
    slides = []
    slide_fields = {'id', 'kind', 'notes', 'background', 'foreground', 'wallpaper',
                    'next', 'backups', 'layout', 'column_break'}
    for chunk in chunks:
        require(chunk.startswith('```fpw-slide\n'), 'Neplatný začátek slidu.')
        close = chunk.find('\n```\n', len('```fpw-slide\n'))
        require(close >= 0, 'YAML metadata slidu nejsou uzavřená.')
        metadata = _yaml_load(chunk[len('```fpw-slide\n'):close])
        require(isinstance(metadata, dict) and slide_fields <= metadata.keys()
                and metadata.keys() <= slide_fields | {'repeat', 'reveal'},
                'Neplatná metadata slidu.')
        title, bullets = _parse_markdown_content(chunk[close + 5:])
        slides.append(dict(metadata, title=title, bullets=bullets))
    return validate_deck(dict(deck_header, slides=slides))


def _decode_legacy(body):
    require(body.startswith(LEGACY_PREFIX) and body.endswith('\n```\n'), 'Neplatný dokument prezentace.')
    try:
        value = json.loads(body[len(LEGACY_PREFIX):-5])
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError('Neplatný JSON starší prezentace.') from exc
    return validate_deck(value)


def is_presentation_document(body):
    if not isinstance(body, str):
        return False
    if body.startswith(LEGACY_PREFIX):
        return True
    if not body.startswith('---\n'):
        return False
    end = body.find('\n---\n', 4)
    front = body[4:end if end >= 0 else min(len(body), MAX_EDITOR)]
    return bool(re.search(r'(?m)^format:\s*["\']?fpw-presentation["\']?\s*$', front))


def decode_deck(body):
    require(isinstance(body, str) and len(body.encode('utf-8')) < MAX_EDITOR,
            'Neplatný dokument prezentace.')
    return _decode_legacy(body) if body.startswith(LEGACY_PREFIX) else _decode_markdown(body)


def public_content(slide):
    content = {key: copy.deepcopy(slide[key]) for key in ('title', 'bullets', 'background', 'foreground', 'wallpaper')}
    if 'layout' in slide:
        content.update(layout=copy.deepcopy(slide['layout']), column_break=slide.get('column_break', 0))
    if slide.get('closing') is True:
        content.update(closing=True, contacts=copy.deepcopy(slide['contacts']), qr=slide['qr'])
    return content


def project_deck(deck, revision):
    deck = validate_deck(deck)
    by_id = {s['id']: s for s in deck['slides']}
    templates = {item['id']: item for item in deck['templates']}
    order = main_order(deck)
    def project(slide):
        visible = dict(slide, layout=templates[slide['layout']])
        return dict(public_content(visible), id=slide['id'], body='\n'.join(slide['bullets']),
                    notes=slide['notes'], deck_revision=revision,
                    repeat=slide.get('repeat', False), reveal=slide.get('reveal', 'all'))
    return dict(active=True, title=deck['title'], slides=[project(by_id[id_]) for id_ in order],
                backups=[dict(project(s), after_slides=[i for i, id_ in enumerate(order) if s['id'] in by_id[id_]['backups']])
                         for s in deck['slides'] if s['kind'] == 'backup'],
                current_slide=0, message='Uložená prezentace je připravena.', revision=revision)


class PresentationDocuments:
    def __init__(self, node_path):
        self.artifacts = Artifacts(node_path)

    def open(self, project_id):
        view = self.artifacts.open(project_id)
        docs = []
        for document in view['documents']:
            if is_presentation_document(document['body']):
                row = dict(document)
                try:
                    row['deck'] = decode_deck(document['body'])
                except (ValueError, TypeError, KeyError) as exc:
                    row['error'] = str(exc)
                docs.append(row)
        return dict(view, documents=docs, layout_presets=layout_presets())

    def open_revision(self, project_id, revision):
        """Read a validated historical deck snapshot without recovery or index writes."""
        require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40,64}', revision),
                'Invalid presentation revision')
        workspace = self.artifacts.workspace(project_id)
        committed_project(workspace.git, revision, project_id)
        files = workspace.git.snapshot(revision)
        entities = validate_snapshot(files)
        docs = []
        for id_, item in entities.items():
            if item['kind'] != 'document':
                continue
            row = document(files, entities, id_)
            if is_presentation_document(row['body']):
                candidate = dict(row)
                candidate['deck'] = decode_deck(row['body'])
                docs.append(candidate)
        return {'id': project_id, 'commit_id': revision, 'documents': docs,
                'layout_presets': layout_presets()}

    def save(self, request, operation_id, *, checkpoint=lambda stage: None,
             privacy='project', provenance='user'):
        body = encode_deck(request['deck'])
        native = {key: request[key] for key in ('project_id', 'artifact_id', 'base_head', 'new')}
        native.update(title=request['deck']['title'], body=body)
        return self.artifacts.save(native, operation_id, checkpoint=checkpoint,
                                   privacy=privacy, provenance=provenance)

    def select(self, project_id, artifact_id, expected_head):
        """Return only an exactly current, validated saved deck for presenting."""
        view = self.open(project_id)
        require(view['commit_id'] == expected_head, 'Projekt se od načtení editoru změnil.')
        document = next((item for item in view['documents'] if item['id'] == artifact_id), None)
        require(document is not None and 'deck' in document, 'Uložená prezentace není dostupná.')
        return project_deck(document['deck'], expected_head + ':' + artifact_id)
