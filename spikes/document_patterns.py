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
from spikes.julia_computation import validate_computation


SCHEMA = 'fpw-document-pattern-catalog-v1'
MAX_TEXT = 1024 * 1024
ID = re.compile(r'^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$')
FORMATS = {
    'text/markdown', 'application/x-fpw-presentation-markdown',
    'text/x-julia', 'application/toml', 'application/json',
}
INSERTION_MODES = {'document', 'block', 'cursor'}


def _presentation_pattern(scenario='single', *, filled=False):
    templates = layout_presets()
    def slide(index, title, bullets, *, layout='content', kind='main', next_=None,
              backups=None, notes=''):
        return {
            'id': f'00000000-0000-4000-8000-{index:012d}', 'kind': kind,
            'title': title, 'bullets': bullets, 'notes': notes,
            'background': '#102b36', 'foreground': '#ffffff', 'wallpaper': '',
            'next': next_, 'backups': backups or [], 'repeat': False,
            'reveal': 'all', 'layout': layout, 'column_break': 0,
        }
    if scenario == 'single':
        title = 'Stav projektu' if filled else 'DOPLNIT: název prezentace'
        slides = [slide(1, 'Stav projektu' if filled else 'DOPLNIT: nadpis',
                        ['Integrace je připravena k akceptaci'] if filled
                        else ['DOPLNIT: hlavní sdělení'])]
    elif scenario == 'briefing':
        title = 'Briefing vydání 1.4' if filled else 'DOPLNIT: stručný briefing'
        slides = [
            slide(11, 'Vydání 1.4' if filled else 'DOPLNIT: téma briefingu',
                  ['Rozhodnout o nasazení ve středu'] if filled else ['DOPLNIT: účel a publikum'],
                  layout='title', next_='00000000-0000-4000-8000-000000000012'),
            slide(12, 'Současný stav' if filled else 'DOPLNIT: současný stav',
                  ['Regresní sada prošla', 'Riziko: chybí mobilní smoke'] if filled
                  else ['DOPLNIT: klíčový fakt', 'DOPLNIT: dopad nebo riziko'],
                  next_='00000000-0000-4000-8000-000000000013'),
            slide(13, 'Další krok' if filled else 'DOPLNIT: další krok',
                  ['Eva provede mobilní smoke do úterý 15:00'] if filled
                  else ['DOPLNIT: vlastník a termín'],
                  layout='closing'),
        ]
    elif scenario == 'decision':
        title = 'Volba databáze indexu' if filled else 'DOPLNIT: rozhodovací prezentace'
        slides = [
            slide(21, 'Který lokální index použít?' if filled else 'DOPLNIT: rozhodovací otázka',
                  ['Potřebujeme obnovitelnou projekci Git commitu'] if filled
                  else ['DOPLNIT: proč je rozhodnutí potřeba'], layout='title',
                  next_='00000000-0000-4000-8000-000000000022',
                  backups=['00000000-0000-4000-8000-000000000024']),
            slide(22, 'Varianty' if filled else 'DOPLNIT: varianty',
                  ['SQLite: transakční a lokální', 'JSON: jednodušší, ale bez dotazů'] if filled
                  else ['DOPLNIT: varianta A', 'DOPLNIT: varianta B'],
                  layout='two-column', next_='00000000-0000-4000-8000-000000000023'),
            slide(23, 'Doporučení' if filled else 'DOPLNIT: doporučení',
                  ['Použít SQLite', 'Index vždy svázat s ID commitu'] if filled
                  else ['DOPLNIT: volba', 'DOPLNIT: podmínky a další krok'],
                  layout='closing'),
            slide(24, 'Výsledek PoC' if filled else 'DOPLNIT: podpůrný důkaz',
                  ['Obnova 10 000 položek trvala 1,8 s na testovacím stroji'] if filled
                  else ['DOPLNIT: zdroj, omezení a interpretace'], kind='backup'),
        ]
    else:
        raise ValueError('Unknown presentation pattern scenario')
    deck = {'version': 1, 'title': title, 'templates': templates, 'slides': slides}
    return encode_deck(deck)


def _julia_computation_pattern():
    value = {
        'schema': 'fpw-julia-computation-v1',
        'computation_id': '00000000-0000-4000-8000-000000000101',
        'title': 'DOPLNIT: název výpočtu',
        'entrypoint': {
            'artifact_id': '00000000-0000-4000-8000-000000000102',
            'path': 'artifacts/00000000-0000-4000-8000-000000000102/model.jl',
            'git_blob': '0' * 40, 'sha256': '0' * 64,
        },
        'environment': {
            'project_path': 'artifacts/00000000-0000-4000-8000-000000000103/Project.toml',
            'project_sha256': '0' * 64,
            'manifest_path': 'artifacts/00000000-0000-4000-8000-000000000104/Manifest-v1.10.toml',
            'manifest_sha256': '0' * 64, 'julia_compat': '1.10.12',
        },
        'inputs': [],
        'parameters': [{
            'name': 'value', 'type': 'number', 'required': True,
            'default': None, 'constraints': {},
        }],
        'outputs': [{
            'name': 'result', 'kind': 'report', 'media_type': 'text/plain',
            'required': True, 'max_bytes': 65536,
        }],
        'execution_policy': {
            'network': 'deny', 'timeout_ms': 30000, 'cpu_threads': 1,
            'max_processes': 8, 'memory_bytes': 536870912,
            'output_bytes': 1048576, 'output_files': 4,
            'stdout_bytes': 65536, 'stderr_bytes': 65536,
        },
    }
    validate_computation(value)
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def _julia_computation_example():
    value = json.loads(_julia_computation_pattern())
    value['computation_id'] = '75c26e73-ef24-4f1f-a3d1-3cf36f598a04'
    value['title'] = 'Součet denních odběrů'
    value['entrypoint'].update({
        'artifact_id': '81ff754d-a384-4120-a89a-bab27d1c96fc',
        'path': 'artifacts/81ff754d-a384-4120-a89a-bab27d1c96fc/model.jl',
        'git_blob': '1' * 40, 'sha256': '2' * 64,
    })
    value['environment'].update({
        'project_path': 'artifacts/23e9c177-d44c-460b-8d56-98b627c26470/Project.toml',
        'project_sha256': '3' * 64,
        'manifest_path': 'artifacts/416f6121-036f-47cb-9bf9-c40774ff93bb/Manifest-v1.10.toml',
        'manifest_sha256': '4' * 64,
    })
    validate_computation(value)
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


ADAPTERS = (
    {
        'id': 'markdown', 'version': 2, 'label': 'Markdown dokument',
        'formats': ['text/markdown'], 'comment_prefix': '<!--',
        'comment_suffix': '-->', 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'artifact-document',
        'integration': 'available', 'validation': 'bounded-text',
        'pattern_ids': ['markdown.document', 'markdown.section',
                        'markdown.checklist', 'markdown.decision',
                        'markdown.meeting-notes'],
        'format_help': {
            'text/markdown': 'Celý soubor je Markdown dokument. Nadpisy tvoří strukturu; odrážky, checklisty, odkazy a komentáře zůstávají obyčejným textem. Vložení vzoru mění jen lokální draft.',
        },
    },
    {
        'id': 'task-plan', 'version': 2, 'label': 'Úkol nebo plán',
        'formats': ['text/markdown'], 'comment_prefix': '<!--',
        'comment_suffix': '-->', 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'artifact-document',
        'integration': 'available', 'validation': 'bounded-markdown',
        'pattern_ids': ['task-plan.document', 'task-plan.external-document',
                        'task-plan.milestone', 'task-plan.batch-inline',
                        'task-plan.batch-file', 'task-plan.task',
                        'task-plan.dependency'],
        'format_help': {
            'text/markdown': 'Soubor plánu je profilovaný Markdown. Kanonická ID, typy, hierarchie a závislosti se materializují do grafu; raw text zůstává autoritou a vložení vzoru nic neukládá.',
        },
    },
    {
        'id': 'presentation', 'version': 2, 'label': 'Prezentace',
        'formats': ['application/x-fpw-presentation-markdown'],
        'comment_prefix': None, 'comment_suffix': None, 'max_bytes': MAX_TEXT,
        'supports_special': True, 'save_operation': 'presentation-document',
        'integration': 'available', 'validation': 'domain-round-trip',
        'pattern_ids': ['presentation.document', 'presentation.briefing',
                        'presentation.decision-review'],
        'format_help': {
            'application/x-fpw-presentation-markdown': 'Celý soubor je kanonický prezentační Markdown s YAML metadaty a fpw-slide bloky. Návrat do vizuálního editoru vyžaduje validní lossless round-trip.',
        },
    },
    {
        'id': 'julia', 'version': 2, 'label': 'Julia model',
        'formats': ['text/x-julia', 'application/toml', 'application/json'],
        'comment_prefix': '#', 'comment_suffix': None, 'max_bytes': MAX_TEXT,
        'supports_special': False, 'save_operation': 'julia-model-bundle',
        'integration': 'available', 'validation': 'bounded-and-structured',
        'pattern_ids': ['julia.script', 'julia.function', 'julia.module',
                        'julia.runner-entrypoint', 'julia.project-toml',
                        'julia.computation-json'],
        'format_help': {
            'text/x-julia': 'Celý soubor je Julia zdrojový kód. Editor kód pouze upravuje a syntakticky ohraničuje; vložení ani validace jej nespouští.',
            'application/toml': 'Celý soubor je Julia Project.toml. Závislosti a přesná kompatibilita prostředí musí odpovídat samostatnému Manifestu a připnutému runtime.',
            'application/json': 'Celý soubor je přenositelná definice fpw-julia-computation-v1. Odkazy a hashe jsou připnuté ke konkrétnímu Git snapshotu; neutrální hodnoty ze vzoru je nutné nahradit.',
        },
    },
)

_FORMAT_EXAMPLES = {
    'markdown': {
        'text/markdown': '# Zápis z technické porady\n\n## Závěry\n\n- Pilotní nasazení proběhne ve středu.\n\n## Další kroky\n\n- [ ] Eva ověří mobilní zobrazení do úterý.\n',
    },
    'task-plan': {
        'text/markdown': '<!-- fpw-plan-profile: software-development/v1 -->\n\n# TODO\n\n- [ ] [MILESTONE-EDITOR] Editory\n  - type: milestone\n  - [ ] [BATCH-HELP] Kontextová nápověda\n    - type: batch\n    - [x] [TASK-EXAMPLE] Doplnit vyplněné ukázky\n      - type: task\n',
    },
    'presentation': {
        'application/x-fpw-presentation-markdown': _presentation_pattern('single', filled=True),
    },
    'julia': {
        'text/x-julia': 'function total(values::Vector{Float64})\n    return sum(values)\nend\n\nprintln(total([12.5, 7.0, 3.5]))\n',
        'application/toml': 'name = "DailyTotals"\nuuid = "c4607280-4db7-4a55-9ba7-b83f0345cf96"\nversion = "0.1.0"\n\n[compat]\njulia = "=1.10.12"\n',
        'application/json': _julia_computation_example(),
    },
}
ADAPTERS = tuple({**adapter, 'version': adapter['version'] + 1,
                  'format_examples': copy.deepcopy(_FORMAT_EXAMPLES[adapter['id']])}
                 for adapter in ADAPTERS)

PATTERNS = (
    {
        'id': 'markdown.document', 'version': 2, 'name': 'Prázdný dokument',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '# <!-- DOPLNIT: název -->\n\n<!-- DOPLNIT: účel a obsah -->\n',
        'help': 'Nahradí lokální draft minimální kostrou celého Markdown dokumentu: jedním hlavním nadpisem a komentářem pro účel. Použijte ji pro nový samostatný dokument; existující text bude po potvrzení vložení nahrazen pouze v lokálním draftu.',
    },
    {
        'id': 'markdown.section', 'version': 2, 'name': 'Sekce',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'cursor',
        'text': '## <!-- DOPLNIT: název části -->\n\n<!-- DOPLNIT: obsah -->\n',
        'help': 'Vloží nadpis druhé úrovně a komentář pro obsah na aktuální pozici kurzoru. Hodí se pro rozšíření existujícího dokumentu; úroveň nadpisu a text komentáře lze po vložení upravit.',
    },
    {
        'id': 'markdown.checklist', 'version': 1, 'name': 'Kontrolní seznam',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'cursor',
        'text': '## <!-- DOPLNIT: název kontroly -->\n\n- [ ] DOPLNIT: první ověřitelný bod\n- [ ] DOPLNIT: druhý ověřitelný bod\n',
        'help': 'Vloží pojmenovaný Markdown checklist se dvěma nezaškrtnutými body. Každý bod formulujte jako konkrétní ověřitelnou podmínku; samotné zaškrtnutí nemění projektový task graph.',
    },
    {
        'id': 'markdown.decision', 'version': 1, 'name': 'Rozhodovací záznam',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '# <!-- DOPLNIT: název rozhodnutí -->\n\n- Stav: navrženo\n- Datum: <!-- DOPLNIT: YYYY-MM-DD -->\n\n## Kontext\n\n<!-- DOPLNIT: problém, omezení a důkazy -->\n\n## Rozhodnutí\n\n<!-- DOPLNIT: zvolená varianta -->\n\n## Důsledky\n\n<!-- DOPLNIT: přínosy, náklady a otevřená rizika -->\n',
        'help': 'Nahradí draft úplným stručným rozhodovacím záznamem s kontextem, rozhodnutím a důsledky. Nezakládá automaticky ADR ani nemění jeho stav; cílovou cestu, schválení a identifikátor určuje běžná dokumentová operace.',
    },
    {
        'id': 'markdown.meeting-notes', 'version': 1, 'name': 'Zápis ze schůzky',
        'adapter_ids': ['markdown'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '# <!-- DOPLNIT: název schůzky -->\n\n- Datum: <!-- DOPLNIT: YYYY-MM-DD -->\n- Účastníci: <!-- DOPLNIT -->\n- Cíl: <!-- DOPLNIT -->\n\n## Závěry\n\n- DOPLNIT: potvrzený závěr\n\n## Úkoly\n\n- [ ] DOPLNIT: vlastník, výsledek a termín\n\n## Otevřené otázky\n\n- DOPLNIT: otázka\n',
        'help': 'Nahradí draft kostrou zápisu, která odděluje potvrzené závěry, následné úkoly a otevřené otázky. Checkboxy jsou v tomto obecném dokumentu pouze Markdown; projektové task entity vznikají jen v profilovaném plánu.',
    },
    {
        'id': 'task-plan.document', 'version': 2, 'name': 'Hlavní TODO',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '<!-- fpw-plan-profile: software-development/v1 -->\n\n# TODO\n\n- [ ] [MILESTONE-01] DOPLNIT: milník\n  - type: milestone\n  - DOPLNIT popis milníku\n',
        'help': 'Vytvoří profilovaný kořen plánu; bez uložení nic nemění.',
    },
    {
        'id': 'task-plan.external-document', 'version': 3,
        'name': 'Soubor úkolů dávky',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'document',
        'text': '<!-- fpw-plan-document: definitions/v1 -->\n\n# Úkoly dávky\n\n- [ ] [TASK-01] DOPLNIT: úkol\n  - type: task\n  - DOPLNIT popis úkolu\n  - [ ] DOPLNIT ověřitelnou podmínku splnění\n',
        'help': 'Kořen externího souboru obsahuje pouze leaf úkoly jedné dávky; vnořené checkboxy jsou jejich podmínky splnění.',
    },
    {
        'id': 'task-plan.milestone', 'version': 2, 'name': 'Milník',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '- [ ] [MILESTONE-01] DOPLNIT: milník\n  - type: milestone\n  - DOPLNIT popis milníku\n',
        'help': 'Vloží kořenový milník softwarového profilu.',
    },
    {
        'id': 'task-plan.batch-inline', 'version': 3,
        'name': 'Dávka s pododrážkami',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '  - [ ] [BATCH-01] DOPLNIT: dávka\n    - type: batch\n    - DOPLNIT popis dávky\n    - [ ] [TASK-01] DOPLNIT: úkol\n      - type: task\n      - DOPLNIT popis úkolu\n      - [ ] DOPLNIT ověřitelnou podmínku splnění\n',
        'help': 'Vloží batch a jeden vnořený task s podmínkou splnění; odsazení lze přizpůsobit okolí.',
    },
    {
        'id': 'task-plan.batch-file', 'version': 2,
        'name': 'Dávka odkazující na soubor',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '  - [ ] [BATCH-01] [DOPLNIT: dávka](artifacts/00000000-0000-4000-8000-000000000001/content.md)\n    - type: batch\n    - DOPLNIT popis dávky\n',
        'help': 'Odkaz musí mířit na existující verzovaný Markdown document artefakt.',
    },
    {
        'id': 'task-plan.task', 'version': 3, 'name': 'Úkol',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '    - [ ] [TASK-01] DOPLNIT: úkol\n      - type: task\n      - DOPLNIT popis úkolu\n      - [ ] DOPLNIT ověřitelnou podmínku splnění\n',
        'help': 'Vloží leaf task s checklistem podmínek; podmínky nejsou samostatné uzly roadmapy.',
    },
    {
        'id': 'task-plan.dependency', 'version': 1, 'name': 'Závislost',
        'adapter_ids': ['task-plan'], 'formats': ['text/markdown'],
        'insertion': 'block',
        'text': '      - depends_on: TASK-00\n',
        'help': 'Vloží kanonickou dependency hranu do metadat vybraného uzlu.',
    },
    {
        'id': 'presentation.document', 'version': 2,
        'name': 'Prezentace s jedním slidem',
        'adapter_ids': ['presentation'],
        'formats': ['application/x-fpw-presentation-markdown'],
        'insertion': 'document', 'text': _presentation_pattern(),
        'help': 'Nahradí lokální raw draft kanonickou prezentací s jedním hlavním slidem. Je vhodná pro nejmenší samostatný deck; neutrální texty upravte před uložením ve raw nebo vizuálním režimu.',
    },
    {
        'id': 'presentation.briefing', 'version': 1,
        'name': 'Stručný briefing',
        'adapter_ids': ['presentation'],
        'formats': ['application/x-fpw-presentation-markdown'],
        'insertion': 'document', 'text': _presentation_pattern('briefing'),
        'help': 'Nahradí draft tříslidovým briefingem: titulní vymezení tématu, současný stav s dopadem a závěrečný další krok. Slidy už tvoří platnou hlavní linii a lze je dále upravit ve vizuálním editoru.',
    },
    {
        'id': 'presentation.decision-review', 'version': 1,
        'name': 'Rozhodovací prezentace',
        'adapter_ids': ['presentation'],
        'formats': ['application/x-fpw-presentation-markdown'],
        'insertion': 'document', 'text': _presentation_pattern('decision'),
        'help': 'Nahradí draft rozhodovacím deckem s otázkou, dvěma variantami, doporučením a jedním navázaným backup slidem pro důkaz. Vazby main/backup jsou validní, ale obsah ani disclosure oprávnění vzor neschvaluje.',
    },
    {
        'id': 'julia.script', 'version': 2, 'name': 'Julia skript',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'document',
        'text': '# DOPLNIT: popište model\n\nvalue = 0\nprintln(value)\n',
        'help': 'Nahradí draft minimálním samostatným Julia skriptem s popisem a jedním výstupem na stdout. Vložení ani ověření skript nespustí; skutečný runner vyžaduje samostatnou definici výpočtu a potvrzení.',
    },
    {
        'id': 'julia.function', 'version': 2, 'name': 'Julia funkce',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'cursor',
        'text': 'function model(value)\n    # DOPLNIT: implementace\n    return value\nend\n',
        'help': 'Vloží pojmenovanou funkci na pozici kurzoru. Upravte název, typy a návratovou hodnotu podle modelu; vložení pouze změní lokální text a funkci nevyhodnotí.',
    },
    {
        'id': 'julia.module', 'version': 1, 'name': 'Julia modul',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'document',
        'text': 'module DoplnitModel\n\nexport model\n\n"""DOPLNIT: popis veřejné funkce."""\nfunction model(value)\n    # DOPLNIT: implementace\n    return value\nend\n\nend # module DoplnitModel\n',
        'help': 'Nahradí draft malým Julia modulem s jednou exportovanou funkcí a docstringem. Název modulu musí odpovídat zamýšlenému balíčku; vzor nepřidává závislosti ani neupravuje Project.toml.',
    },
    {
        'id': 'julia.runner-entrypoint', 'version': 1,
        'name': 'Entrypoint s deklarovaným výstupem',
        'adapter_ids': ['julia'], 'formats': ['text/x-julia'],
        'insertion': 'document',
        'text': 'using SHA\n\noutput_index = findfirst(==("--fpw-output"), ARGS)\noutput_index === nothing && error("Chybí --fpw-output")\noutput_dir = ARGS[output_index + 1]\n\n# DOPLNIT: načtěte --fpw-request a proveďte model.\nraw = Vector{UInt8}("DOPLNIT: výsledek\\n")\nresult_path = joinpath(output_dir, "result.txt")\nwrite(result_path, raw)\nhash = bytes2hex(sha256(raw))\nmanifest = "{\\\"outputs\\\":[{\\\"kind\\\":\\\"report\\\",\\\"media_type\\\":\\\"text/plain\\\",\\\"name\\\":\\\"result\\\",\\\"path\\\":\\\"result.txt\\\",\\\"sha256\\\":\\\"$(hash)\\\",\\\"size\\\":$(length(raw))}],\\\"schema\\\":\\\"fpw-julia-result-v1\\\"}"\nwrite(joinpath(output_dir, "fpw-julia-result-v1.json"), manifest)\n',
        'help': 'Nahradí draft entrypointem kompatibilním s runnerem: najde výstupní adresář, vytvoří deklarovaný textový výstup, spočítá SHA-256 a zapíše result manifest. Čtení requestu a vlastní model jsou záměrně označené k doplnění; názvy a limity musí souhlasit s computation JSON.',
    },
    {
        'id': 'julia.project-toml', 'version': 2, 'name': 'Julia Project.toml',
        'adapter_ids': ['julia'], 'formats': ['application/toml'],
        'insertion': 'document',
        'text': 'name = "DoplnitModel"\nuuid = "00000000-0000-4000-8000-000000000002"\nversion = "0.1.0"\n\n[compat]\njulia = "=1.10.12"\n',
        'help': 'Nahradí draft platným minimálním Project.toml s názvem, UUID, verzí a přesně připnutou kompatibilitou Julia 1.10.12. Závislosti doplňte explicitně a udržujte je ve shodě s verzovaným Manifestem.',
    },
    {
        'id': 'julia.computation-json', 'version': 2,
        'name': 'Julia computation JSON',
        'adapter_ids': ['julia'], 'formats': ['application/json'],
        'insertion': 'document',
        'text': _julia_computation_pattern(),
        'help': 'Nahradí draft úplnou validní definicí fpw-julia-computation-v1 s jedním číselným parametrem, jedním textovým výstupem a fail-closed limity. Nulové hashe, UUID, cesty, název a limity jsou neutrální hodnoty k nahrazení podle skutečného committed snapshotu; JSON proto nepotřebuje neplatné pseudokomentáře.',
    },
)

_PATTERN_EXAMPLES = {
    'markdown.document': '# Provozní návod\n\nTento dokument popisuje bezpečné spuštění a zastavení služby.\n',
    'markdown.section': '## Omezení\n\nPostup je ověřený pouze na Linuxu s Pythonem 3.11+.\n',
    'markdown.checklist': '## Kontrola před předáním\n\n- [x] Cílené testy prošly\n- [ ] Odkazy byly ručně ověřeny\n',
    'markdown.decision': '# Volba lokálního indexu\n\n- Stav: schváleno\n- Datum: 2026-10-28\n\n## Kontext\n\nIndex musí být obnovitelný z Git commitu.\n\n## Rozhodnutí\n\nPoužijeme SQLite projekci svázanou s ID commitu.\n\n## Důsledky\n\nPři nesouladu s HEAD se index znovu sestaví.\n',
    'markdown.meeting-notes': '# Porada k vydání 1.4\n\n- Datum: 2026-10-28\n- Účastníci: Eva, Jan\n- Cíl: rozhodnout o pilotním nasazení\n\n## Závěry\n\n- Pilot proběhne ve středu.\n\n## Úkoly\n\n- [ ] Eva ověří mobilní zobrazení do úterý.\n\n## Otevřené otázky\n\n- Kdo bude držet pohotovost?\n',
    'task-plan.document': '<!-- fpw-plan-profile: software-development/v1 -->\n\n# TODO\n\n- [ ] [MILESTONE-EDITOR] Editory\n  - type: milestone\n  - Umožnit bezpečnou práci s více druhy dokumentů.\n',
    'task-plan.external-document': '<!-- fpw-plan-document: definitions/v1 -->\n\n# Úkoly dávky\n\n- [ ] [TASK-VALIDATE] Doplnit validaci katalogu\n  - type: task\n  - Odmítnout neplatné adaptéry a duplicitní ID vzorů.\n  - [x] Duplicitní ID vzoru skončí validační chybou.\n  - [ ] Chyba ukáže konfliktní ID.\n',
    'task-plan.milestone': '- [ ] [MILESTONE-EDITOR] Editory dokumentů\n  - type: milestone\n  - Umožnit bezpečnou práci s více druhy dokumentů.\n',
    'task-plan.batch-inline': '  - [ ] [BATCH-HELP] Kontextová nápověda\n    - type: batch\n    - Zobrazit nápovědu a vyplněné příklady vedle editoru.\n    - [ ] [TASK-EXAMPLE] Doplnit vyplněné ukázky\n      - type: task\n      - Přidat realistický příklad pro každý vzor.\n      - [x] Ukázka používá vyplněná data.\n      - [ ] Ukázka projde validací adaptéru.\n',
    'task-plan.batch-file': '  - [ ] [BATCH-CATALOG] [Katalog vzorů](artifacts/793cce75-eb41-40ca-aa70-55c52a6221f2/content.md)\n    - type: batch\n    - Uchovávat úkoly dávky v samostatném verzovaném souboru.\n',
    'task-plan.task': '    - [ ] [TASK-VALIDATE] Doplnit validaci katalogu\n      - type: task\n      - Odmítnout duplicitní ID vzoru.\n      - [x] Validátor vrátí konfliktní ID.\n      - [ ] Regresní test pokryje chybovou cestu.\n',
    'task-plan.dependency': '      - depends_on: TASK-DESIGN\n',
    'presentation.document': _presentation_pattern('single', filled=True),
    'presentation.briefing': _presentation_pattern('briefing', filled=True),
    'presentation.decision-review': _presentation_pattern('decision', filled=True),
    'julia.script': 'values = [12.5, 7.0, 3.5]\ntotal = sum(values)\nprintln(total)\n',
    'julia.function': 'function total(values::Vector{Float64})\n    return sum(values)\nend\n',
    'julia.module': 'module DailyTotals\n\nexport total\n\n"""Sečte denní hodnoty."""\ntotal(values::Vector{Float64}) = sum(values)\n\nend # module DailyTotals\n',
    'julia.runner-entrypoint': 'using SHA\n\noutput_dir = ARGS[findfirst(==("--fpw-output"), ARGS) + 1]\nraw = Vector{UInt8}("23.0\\n")\nwrite(joinpath(output_dir, "result.txt"), raw)\nprintln(bytes2hex(sha256(raw)))\n',
    'julia.project-toml': 'name = "DailyTotals"\nuuid = "c4607280-4db7-4a55-9ba7-b83f0345cf96"\nversion = "0.1.0"\n\n[compat]\njulia = "=1.10.12"\n',
    'julia.computation-json': _julia_computation_example(),
}
PATTERNS = tuple({**pattern, 'version': pattern['version'] + 1,
                  'example': _PATTERN_EXAMPLES[pattern['id']]}
                 for pattern in PATTERNS)

COVERAGE = (
    {'id': 'markdown.start-document', 'adapter_id': 'markdown',
     'format': 'text/markdown', 'operation': 'document',
     'pattern_id': 'markdown.document'},
    {'id': 'markdown.add-section', 'adapter_id': 'markdown',
     'format': 'text/markdown', 'operation': 'cursor',
     'pattern_id': 'markdown.section'},
    {'id': 'markdown.add-checklist', 'adapter_id': 'markdown',
     'format': 'text/markdown', 'operation': 'cursor',
     'pattern_id': 'markdown.checklist'},
    {'id': 'markdown.record-decision', 'adapter_id': 'markdown',
     'format': 'text/markdown', 'operation': 'document',
     'pattern_id': 'markdown.decision'},
    {'id': 'markdown.record-meeting', 'adapter_id': 'markdown',
     'format': 'text/markdown', 'operation': 'document',
     'pattern_id': 'markdown.meeting-notes'},
    {'id': 'presentation.single-slide', 'adapter_id': 'presentation',
     'format': 'application/x-fpw-presentation-markdown', 'operation': 'document',
     'pattern_id': 'presentation.document'},
    {'id': 'presentation.briefing', 'adapter_id': 'presentation',
     'format': 'application/x-fpw-presentation-markdown', 'operation': 'document',
     'pattern_id': 'presentation.briefing'},
    {'id': 'presentation.decision-review', 'adapter_id': 'presentation',
     'format': 'application/x-fpw-presentation-markdown', 'operation': 'document',
     'pattern_id': 'presentation.decision-review'},
    {'id': 'julia.start-script', 'adapter_id': 'julia',
     'format': 'text/x-julia', 'operation': 'document',
     'pattern_id': 'julia.script'},
    {'id': 'julia.add-function', 'adapter_id': 'julia',
     'format': 'text/x-julia', 'operation': 'cursor',
     'pattern_id': 'julia.function'},
    {'id': 'julia.start-module', 'adapter_id': 'julia',
     'format': 'text/x-julia', 'operation': 'document',
     'pattern_id': 'julia.module'},
    {'id': 'julia.runner-entrypoint', 'adapter_id': 'julia',
     'format': 'text/x-julia', 'operation': 'document',
     'pattern_id': 'julia.runner-entrypoint'},
    {'id': 'julia.project-environment', 'adapter_id': 'julia',
     'format': 'application/toml', 'operation': 'document',
     'pattern_id': 'julia.project-toml'},
    {'id': 'julia.computation-contract', 'adapter_id': 'julia',
     'format': 'application/json', 'operation': 'document',
     'pattern_id': 'julia.computation-json'},
)


def _validate_registry():
    adapter_ids = set()
    pattern_ids = set()
    for adapter in ADAPTERS:
        if (set(adapter) != {'id', 'version', 'label', 'formats', 'comment_prefix',
                             'comment_suffix', 'max_bytes', 'supports_special',
                             'save_operation', 'integration', 'validation',
                             'pattern_ids', 'format_help', 'format_examples'}
                or not ID.fullmatch(adapter['id']) or adapter['id'] in adapter_ids
                or type(adapter['version']) is not int or adapter['version'] < 1
                or not adapter['formats'] or not set(adapter['formats']) <= FORMATS
                or len(adapter['formats']) != len(set(adapter['formats']))
                or not isinstance(adapter['label'], str)
                or type(adapter['supports_special']) is not bool
                or adapter['max_bytes'] != MAX_TEXT
                or not isinstance(adapter['pattern_ids'], list)
                or not isinstance(adapter['format_help'], dict)
                or set(adapter['format_help']) != set(adapter['formats'])
                or not all(isinstance(value, str) and value.strip()
                           for value in adapter['format_help'].values())
                or not isinstance(adapter['format_examples'], dict)
                or set(adapter['format_examples']) != set(adapter['formats'])
                or not all(isinstance(value, str) and value.strip()
                           for value in adapter['format_examples'].values())):
            raise ValueError('Invalid raw-editor adapter registry')
        adapter_ids.add(adapter['id'])
    for pattern in PATTERNS:
        if (set(pattern) != {'id', 'version', 'name', 'adapter_ids', 'formats',
                             'insertion', 'text', 'help', 'example'}
                or not ID.fullmatch(pattern['id']) or pattern['id'] in pattern_ids
                or type(pattern['version']) is not int or pattern['version'] < 1
                or pattern['insertion'] not in INSERTION_MODES
                or not pattern['adapter_ids'] or not set(pattern['adapter_ids']) <= adapter_ids
                or not pattern['formats'] or not set(pattern['formats']) <= FORMATS
                or not isinstance(pattern['text'], str) or '\0' in pattern['text']
                or len(pattern['text'].encode('utf-8')) > MAX_TEXT
                or not isinstance(pattern['name'], str) or not isinstance(pattern['help'], str)
                or not isinstance(pattern['example'], str) or not pattern['example'].strip()):
            raise ValueError('Invalid document pattern registry')
        for adapter_id in pattern['adapter_ids']:
            adapter = next(item for item in ADAPTERS if item['id'] == adapter_id)
            if pattern['id'] not in adapter['pattern_ids'] \
                    or not set(pattern['formats']) <= set(adapter['formats']):
                raise ValueError('Pattern is inconsistent with its adapter')
        pattern_ids.add(pattern['id'])
    if any(set(adapter['pattern_ids']) - pattern_ids for adapter in ADAPTERS):
        raise ValueError('Adapter references an unknown pattern')
    coverage_ids = set()
    covered_patterns = set()
    for item in COVERAGE:
        pattern = next((value for value in PATTERNS
                        if value['id'] == item.get('pattern_id')), None)
        if (set(item) != {'id', 'adapter_id', 'format', 'operation', 'pattern_id'}
                or not ID.fullmatch(item['id']) or item['id'] in coverage_ids
                or pattern is None or item['adapter_id'] not in pattern['adapter_ids']
                or item['format'] not in pattern['formats']
                or item['operation'] != pattern['insertion']
                or item['pattern_id'] in covered_patterns):
            raise ValueError('Invalid pattern coverage map')
        coverage_ids.add(item['id'])
        covered_patterns.add(item['pattern_id'])
    expected = {item['id'] for item in PATTERNS if item['adapter_ids'] != ['task-plan']}
    if covered_patterns != expected:
        raise ValueError('Pattern coverage map is incomplete')

    for pattern in PATTERNS:
        for format_ in pattern['formats']:
            if format_ == 'application/toml':
                tomllib.loads(pattern['text'])
            elif format_ == 'application/json':
                value = json.loads(pattern['text'])
                if pattern['id'] == 'julia.computation-json':
                    validate_computation(value)
            elif format_ == 'application/x-fpw-presentation-markdown':
                if encode_deck(decode_deck(pattern['text'])) != pattern['text']:
                    raise ValueError('Presentation pattern is not lossless')


_validate_registry()


class DocumentPatterns:
    """Expose immutable built-ins and bounded, non-persistent validation."""

    def catalog(self):
        value = {'schema': SCHEMA, 'adapters': copy.deepcopy(list(ADAPTERS)),
                 'patterns': copy.deepcopy(list(PATTERNS)),
                 'coverage': copy.deepcopy(list(COVERAGE))}
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
            if adapter_id == 'julia':
                try:
                    value = validate_computation(value)
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    raise ValueError('Neplatná definice Julia výpočtu.') from exc
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
