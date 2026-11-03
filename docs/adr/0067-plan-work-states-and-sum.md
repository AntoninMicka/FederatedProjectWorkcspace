<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0067 — Pracovní stavy plánu a odvozený stav skupiny SUM

- Datum: 2026-11-03
- Stav: přijatý návrh podle uživatelského zadání
- Rozsah: `NEW-B7B56C4A0B-TASK-1`, uživatelem rozšířeno na celý plán i frontu

## Rozhodnutí

Stav se ukládá přímo do vlastního Markdown bloku uzlu jako `- status: VALUE`.
Nevzniká další registr ani persistentní vrstva. Povolené hodnoty:

| Hodnota | Popisek |
| --- | --- |
| `planned` | Plánováno (New/Pending) |
| `in progress` | Probíhá |
| `resolved` | Vyřešeno, čeká na potvrzení splnění |
| `failed` | Selhalo |
| `completed` | Dokončeno (Done) |
| `deferred` | Odloženo |
| `sum` | SUM, odvodit stav ze všech obsažených položek |

Bez pole `status` zůstává původní význam checkboxu: `[x]` = Dokončeno,
`[ ]` = Plánováno. Historické popisy `Stav: …` zůstávají obyčejným textem.
Neznámé a opakované deklarace `status` jsou neplatný plán.

Checkbox zůstává autoritou potvrzeného dokončení a závislostí. `resolved`
ani `SUM · Dokončeno` samy nezaškrtnou skupinu ani nevytvoří lidskou akceptaci.
U ručně zadaného stavu znamená `[x]` vždy Dokončeno, také po pozdějším
přijetí zprávy z IDE. Ručně zapsané `status: completed` bez `[x]` je neplatné.
Volba Dokončeno v editoru připraví současně `[x]`; volba jiného ručního stavu
připraví `[ ]`. Výběr SUM checkbox nepřepisuje. Změna se projeví až po
explicitním uložení existujícím editorem.

`SUM` je povoleno pro milestone/batch (včetně prázdné skupiny) nebo obecný
uzel s potomky, nikoli pro task. Skupina agreguje všechny přímé potomky,
nejen viditelný filtr nebo položky ve frontě. Jejich skupiny se vyhodnotí
rekurzivně, včetně definic v odkazovaných souborech. Ručně nastavený stav
vnořené skupiny má přednost před jejími potomky; automatická agregace je
vždy explicitní volba SUM.

Pravidla v pořadí vyhodnocení:

1. Bez potomků → Plánováno.
2. Všichni Dokončeno → Dokončeno.
3. Alespoň jeden Selhalo → Selhalo.
4. Všichni Odloženo → Odloženo.
5. Pouze Plánováno a Odloženo → Plánováno.
6. Pouze Vyřešeno a Dokončeno → Vyřešeno.
7. Ostatní kombinace → Probíhá.

Projekce zpřístupní výsledný `status`, uložený `status_mode` a počty přímých
potomků podle výsledného stavu v `status_counts`. Kritická cesta, závislostní
blokace, připravenost, lokální Pozastaveno a zprávy agentů/lidské review
zůstávají samostatné příznaky. Mohou se zobrazit vedle pracovního stavu.
IDE dostává stejná pole přes snapshot a projekci připnuté fronty; starý
balíček bez těchto polí nadále používá původní příznaky. Stale stav zůstává
výslovně označený jako poslední známý. Hlášení agenta nemění pracovní stav.

## Zápis a recovery

Adaptujeme scoped editor z [ADR 0059](0059-file-plan-hierarchy-and-task-editor.md)
a transakci z [ADR 0003](0003-coordinated-operation.md). Výběr v UI mění jen
lokální draft vlastního bloku; zrušení nic nezapisuje. Uložení kontroluje
HEAD, digest fragmentu, oprávnění/privacy a validitu celého bundle. Ostatní
uložené `status_mode` musí zůstat beze změny; odvozené stavy předků se
přepočítají read-only projekcí.

Crash boundaries se nemění: `prepared` / `files-applied` před publikací
obnovuje journal; po `ref-updated` lze index obnovit z HEAD, následně
`indexed` / `completed`. Retry používá původní operation ID a shodné zadání.
Fronta a export mají vlastní lifecycle; mezi jejich refreshem a projektovým
commitem nepředstíráme atomicitu. Neaktuální export se nepoužívá jako
aktuální stav.

## Ověření

Deterministický test pokrývá všech 36 dvojic šesti ručních stavů, prázdnou
skupinu, ruční override, rekurzi a souborové definice. Scoped zápis ověřuje
nezměněné okolní bajty a replay po přerušení na všech pěti hranicích.
Qt smoke čte SUM, vybere jiný stav, uloží přes skutečné API a ověří stav
ve frontě. Izolovaný smoke nenahrazuje ruční akceptaci běžného profilu.
