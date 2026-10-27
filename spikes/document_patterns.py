# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed, read-only text pattern catalog and raw-editor adapter contracts."""
import copy
import hashlib
import json
import re
import tomllib

from spikes.presentation_documents import (decode_deck, encode_deck,
                                           layout_presets, validate_deck)


SCHEMA = 'fpw-document-pattern-catalog-v1'
MAX_TEXT = 1024 * 1024
ID = re.compile(r'^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$')
FORMATS = {
    'text/markdown', 'application/x-fpw-presentation-markdown',
    'text/x-julia', 'application/toml', 'application/json',
}
INSERTION_MODES = {'document', 'block', 'cursor'}


def _presentation_pattern():
    templates = layout_presets()
    deck = {
        'version': 1,
        'title': 'DOPLNIT: název prezentace',
        'templates': templates,
        'slides': [{
            'id': '00000000-0000-4000-8000-000000000001',
            'kind': 'main',
            'title': 'DOPLNIT: nadpis',
            'bullets': ['DOPLNIT: hlavní sdělení'],
            'notes': '',
            'background': '#102b36',
            'foreground': '#ffffff',
            'wallpaper': '',
            'next': None,
            'backups': [],
            'repeat': False,
            'reveal': 'all',
            'layout': 'content',
            'column_break': 0,
        }],
    }
    return encode_deck(deck)


ADAPTERS = (
    {
        'id': 'markdown', 'version': 1, 'label': 'Markdown dokument',
        'formats': ['text/markdown'], 'comment_prefix': '<!--',
        'comment_suffix': '-->', 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'artifact-document',
        'integration': 'available', 'validation': 'bounded-text',
        'pattern_ids': ['markdown.document', 'markdown.section'],
    },
    {
        'id': 'task-plan', 'version': 1, 'label': 'Úkol nebo plán',
        'formats': ['text/markdown'], 'comment_prefix': '<!--',
        'comment_suffix': '-->', 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'artifact-document',
        'integration': 'available', 'validation': 'bounded-markdown',
        'pattern_ids': ['task-plan.document', 'task-plan.external-document',
                        'task-plan.milestone', 'task-plan.batch-inline',
                        'task-plan.batch-file', 'task-plan.task',
                        'task-plan.dependency'],
    },
    {
        'id': 'presentation', 'version': 1, 'label': 'Prezentace',
        'formats': ['application/x-fpw-presentation-markdown'],
        'comment_prefix': None, 'comment_suffix': None, 'max_bytes': MAX_TEXT,
        'supports_special': True, 'save_operation': 'presentation-document',
        'integration': 'available', 'validation': 'domain-round-trip',
        'pattern_ids': ['presentation.document'],
    },
    {
        'id': 'julia', 'version': 1, 'label': 'Julia model',
        'formats': ['text/x-julia', 'application/toml', 'application/json'],
        'comment_prefix': '#', 'comment_suffix': None, 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'julia-model-bundle',
        'integration': 'comp-03', 'validation': 'bounded-and-structured',
        'pattern_ids': ['julia.script', 'julia.function', 'julia.project-toml',
                        'julia.computation-json'],
    },
)

PATTERNS = (
    {
        'id': 'markdown.document', 'version': 1, 'name': 'Prázdný dokument',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '# <!-- DOPLNIT: název -->\n\n<!-- DOPLNIT: účel a obsah -->\n',
        'help': 'Nahradí lokální draft základní kostrou Markdown dokumentu.',
    },
    {
        'id': 'markdown.section', 'version': 1, 'name': 'Sekce',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'cursor',
        'text': '## <!-- DOPLNIT: název části -->\n\n<!-- DOPLNIT: obsah -->\n',
        'help': 'Vloží sekci na pozici kurzoru.',
    },
    {
        'id': 'task-plan.document', 'version': 1, 'name': 'Hlavní TODO',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '<!-- fpw-plan-profile: software-development/v1 -->\n\n# TODO\n\n- [ ] [MILESTONE-01] DOPLNIT: milník\n  - type: milestone\n',
        'help': 'Vytvoří profilovaný kořen plánu; bez uložení nic nemění.',
    },
    {
        'id': 'task-plan.external-document', 'version': 1,
        'name': 'Soubor úkolů dávky',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '<!-- fpw-plan-document: definitions/v1 -->\n\n# Úkoly dávky\n\n- [ ] [TASK-01] DOPLNIT: úkol\n  - type: task\n',
        'help': 'Kořen externího souboru obsahuje pouze leaf úkoly jedné dávky.',
    },
    {
        'id': 'task-plan.milestone', 'version': 1, 'name': 'Milník',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '- [ ] [MILESTONE-01] DOPLNIT: milník\n  - type: milestone\n',
        'help': 'Vloží kořenový milník softwarového profilu.',
    },
    {
        'id': 'task-plan.batch-inline', 'version': 1,
        'name': 'Dávka s pododrážkami',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '  - [ ] [BATCH-01] DOPLNIT: dávka\n    - type: batch\n    - [ ] [TASK-01] DOPLNIT: úkol\n      - type: task\n',
        'help': 'Vloží batch a jeden vnořený task; odsazení lze přizpůsobit okolí.',
    },
    {
        'id': 'task-plan.batch-file', 'version': 1,
        'name': 'Dávka odkazující na soubor',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '  - [ ] [BATCH-01] [DOPLNIT: dávka](artifacts/00000000-0000-4000-8000-000000000001/content.md)\n    - type: batch\n',
        'help': 'Odkaz musí mířit na existující verzovaný Markdown document artefakt.',
    },
    {
        'id': 'task-plan.task', 'version': 1, 'name': 'Úkol',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '    - [ ] [TASK-01] DOPLNIT: úkol\n      - type: task\n',
        'help': 'Vloží leaf task; odsazení a stabilní ID musí odpovídat dávce.',
    },
    {
        'id': 'task-plan.dependency', 'version': 1, 'name': 'Závislost',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '      - depends_on: TASK-00\n',
        'help': 'Vloží kanonickou dependency hranu do metadat vybraného uzlu.',
    },
    {
        'id': 'presentation.document', 'version': 1,
        'name': 'Prezentace s jedním slidem',
        'adapter_ids': ['presentation'],
        'formats': ['application/x-fpw-presentation-markdown'],
        'insertion': 'document', 'text': _presentation_pattern(),
        'help': 'Používá platné neutrální hodnoty; instrukce zůstává v katalogu.',
    },
    {
        'id': 'julia.script', 'version': 1, 'name': 'Julia skript',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'document',
        'text': '# DOPLNIT: popište model\n\nvalue = 0\nprintln(value)\n',
        'help': 'Pouze textový draft; vložení skript nespustí.',
    },
    {
        'id': 'julia.function', 'version': 1, 'name': 'Julia funkce',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'cursor',
        'text': 'function model(value)\n    # DOPLNIT: implementace\n    return value\nend\n',
        'help': 'Vloží funkci na pozici kurzoru bez spuštění.',
    },
    {
        'id': 'julia.project-toml', 'version': 1, 'name': 'Julia Project.toml',
        'adapter_ids': ['julia'], 'formats': ['application/toml'],
        'insertion': 'document',
        'text': 'name = "DoplnitModel"\nuuid = "00000000-0000-4000-8000-000000000002"\nversion = "0.1.0"\n',
        'help': 'Platný TOML základ; komentáře nejsou vydávány za hodnoty.',
    },
    {
        'id': 'julia.computation-json', 'version': 1,
        'name': 'Julia computation JSON',
        'adapter_ids': ['julia'], 'formats': ['application/json'],
        'insertion': 'document',
        'text': '{\n  "schema": "fpw-julia-computation-v1",\n  "parameters": {},\n  "outputs": []\n}\n',
        'help': 'JSON nepoužívá pseudokomentáře; doplnění popisuje tato nápověda.',
    },
)


def _validate_registry():
    adapter_ids = set()
    pattern_ids = set()
    for adapter in ADAPTERS:
        if (set(adapter) != {'id', 'version', 'label', 'formats', 'comment_prefix',
                             'comment_suffix', 'max_bytes', 'supports_special',
                             'save_operation', 'integration', 'validation',
                             'pattern_ids'}
                or not ID.fullmatch(adapter['id']) or adapter['id'] in adapter_ids
                or type(adapter['version']) is not int or adapter['version'] < 1
                or not adapter['formats'] or not set(adapter['formats']) <= FORMATS
                or len(adapter['formats']) != len(set(adapter['formats']))
                or not isinstance(adapter['label'], str)
                or type(adapter['supports_special']) is not bool
                or adapter['max_bytes'] != MAX_TEXT
                or not isinstance(adapter['pattern_ids'], list)):
            raise ValueError('Invalid raw-editor adapter registry')
        adapter_ids.add(adapter['id'])
    for pattern in PATTERNS:
        if (set(pattern) != {'id', 'version', 'name', 'adapter_ids', 'formats',
                             'insertion', 'text', 'help'}
                or not ID.fullmatch(pattern['id']) or pattern['id'] in pattern_ids
                or type(pattern['version']) is not int or pattern['version'] < 1
                or pattern['insertion'] not in INSERTION_MODES
                or not pattern['adapter_ids'] or not set(pattern['adapter_ids']) <= adapter_ids
                or not pattern['formats'] or not set(pattern['formats']) <= FORMATS
                or not isinstance(pattern['text'], str) or '\0' in pattern['text']
                or len(pattern['text'].encode('utf-8')) > MAX_TEXT
                or not isinstance(pattern['name'], str) or not isinstance(pattern['help'], str)):
            raise ValueError('Invalid document pattern registry')
        for adapter_id in pattern['adapter_ids']:
            adapter = next(item for item in ADAPTERS if item['id'] == adapter_id)
            if pattern['id'] not in adapter['pattern_ids'] \
                    or not set(pattern['formats']) <= set(adapter['formats']):
                raise ValueError('Pattern is inconsistent with its adapter')
        pattern_ids.add(pattern['id'])
    if any(set(adapter['pattern_ids']) - pattern_ids for adapter in ADAPTERS):
        raise ValueError('Adapter references an unknown pattern')


_validate_registry()


class DocumentPatterns:
    """Expose immutable built-ins and bounded, non-persistent validation."""

    def catalog(self):
        value = {'schema': SCHEMA, 'adapters': copy.deepcopy(list(ADAPTERS)),
                 'patterns': copy.deepcopy(list(PATTERNS))}
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode('utf-8')
        value['revision'] = hashlib.sha256(canonical).hexdigest()
        return value

    @staticmethod
    def _adapter(adapter_id, format_):
        if not isinstance(adapter_id, str) or not isinstance(format_, str):
            raise ValueError('Neplatný typ nebo formát raw editoru.')
        adapter = next((item for item in ADAPTERS if item['id'] == adapter_id), None)
        if adapter is None or format_ not in adapter['formats']:
            raise ValueError('Neznámý typ nebo formát raw editoru.')
        return adapter

    def validate(self, adapter_id, format_, content):
        adapter = self._adapter(adapter_id, format_)
        if (not isinstance(content, str) or '\0' in content
                or len(content.encode('utf-8')) > adapter['max_bytes']):
            raise ValueError('Raw obsah je neplatný nebo překračuje limit 1 MiB.')
        result = {'valid': True, 'adapter_id': adapter_id, 'format': format_,
                  'bytes': len(content.encode('utf-8')),
                  'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                  'normalized_content': content}
        if adapter_id == 'presentation':
            deck = decode_deck(content)
            normalized = encode_deck(deck)
            result.update(value=deck, normalized_content=normalized,
                          lossless=normalized == content)
        elif format_ == 'application/json':
            try:
                value = json.loads(content)
            except (json.JSONDecodeError, RecursionError) as exc:
                raise ValueError('Neplatný JSON raw obsah.') from exc
            if not isinstance(value, dict):
                raise ValueError('JSON raw obsah musí být objekt.')
            result.update(value=value, lossless=True)
        elif format_ == 'application/toml':
            try:
                tomllib.loads(content)
            except (tomllib.TOMLDecodeError, RecursionError) as exc:
                raise ValueError('Neplatný TOML raw obsah.') from exc
            result['lossless'] = True
        else:
            result['lossless'] = True
        result['validation'] = adapter['validation']
        return result

    def serialize(self, adapter_id, format_, value):
        self._adapter(adapter_id, format_)
        if adapter_id != 'presentation':
            if not isinstance(value, str):
                raise ValueError('Tento adaptér serializuje pouze text.')
            return self.validate(adapter_id, format_, value)
        deck = validate_deck(value)
        return self.validate(adapter_id, format_, encode_deck(deck))
