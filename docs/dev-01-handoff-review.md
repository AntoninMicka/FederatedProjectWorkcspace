<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# DEV-01 — akceptace a předání autority, 31. 10. 2026

Stav: **implemented / PoC validated, uživatelem akceptováno, autorita předána**.
Uživatel výslovně potvrdil obsah obou projektů, běžný desktop/IDE tok po
restartu a konkrétní migrační diff. Kanonickým plánem je hostitelský Workspace
projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`; modulový plán drží projekt
`af24865c-a81f-58c9-b572-a397bd0c3d6e`. Aktuální úkoly se čtou z jejich
platného exportu, ne z archivovaných zdrojových dokumentů.

Uzavřenou feature evidenci drží [WORK_LOG](../WORK_LOG.md#dev-01--roadmapa-jako-projektová-data-a-export-úkolů--2026-10-31).
[TODO](../TODO.md) pouze čeká na doručení PR do develop; PR není vytvořen ani
sloučen. Tento dokument je předávací záznam, nikoli nový plán.

## Obnovené důkazy po ztrátě dočasných reportů

Původní run/bundle/receipt v `/tmp` nejsou dostupné. Níže je nová kontrola
trvalých dat; nenahrazuje původní LLM audit ani lidskou sémantickou akceptaci.
Tato kontrola sama neprovedla import ani scan. Níže jsou hodnoty připnutého
původního importu před pozdějším schváleným předáním; následné commity jsou
zaznamenané v další sekci.

### Hostitelský projekt

- Project ID: `c898b941-8eb0-4406-8dad-6e2b96c06d59`.
- Git HEAD: `549153757576f24fb5244c313818a08bb2273ce6`.
- Snapshot: 670 souborů / 335 entit; pracovní strom čistý.
- Graf: 709 jedinečných uzlů; batch: 202, milestone: 22, task: 485.
- ID v připnutém mappingu a živém grafu jsou totožná (709/709).
- Journal: 0 pending / 0 unfinished.
- Připnutý mapping SHA-256: `6cd535a8435e9d253181a9d7a9e6aadaf1bf7e845d77e6fc09b9e0167d51f86f`.

| Zdroj | Připnutý commit | SHA-256 | Bajty v projektu |
|---|---|---|---|
| `BACKLOG.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `cce3acad67fe4ffaf5eca1eddc2ddea8e9adba8f84fff13afafb0933e75dc6d2` | přesná shoda |
| `Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `27026cbd4e733f77f2e73748ab74a2580605f83475d56f3b85bbcf197cc3c280` | přesná shoda |
| `TODO.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `058a2bc4e9624e3e1a844999aa56ed399ddc81341cb88544caeb8611410f7aeb` | přesná shoda |
| `WORK_LOG.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `6f09540c8a1b26d3e173ff5c608ea2ee70cf1a24bc2925b4f7cdba56b43c27c0` | přesná shoda |
| `docs/adr/0026-module-unified-api.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `7ce4ddc7d9fc0fde3b7abc49844757c03006294fa61260e8921a49810dd5eddb` | přesná shoda |
| `docs/adr/0055-project-task-plan.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `6ba9fa7cc2f3df6a3657aee3c9d8b8f888d7f12949ac0b02dca38330d3dd6547` | přesná shoda |
| `docs/adr/0059-file-plan-hierarchy-and-task-editor.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `bc7633b2a94d69ab74efe2bc80d5bd9c3d6b34c4cb76217c919f5dc2da2f851e` | přesná shoda |
| `docs/adr/0060-local-file-ide-bridge.md` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `84af286d36c63fa8f570f148b1bf7667bf3de4f850afd89842ddb5abf612d88a` | přesná shoda |
| `docs/roadmap-graph.json` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `9ddc21b6477c0649bd9e10ef01edcf80c198ff57ede7f9ed9d17c0bab0084023` | přesná shoda |
| `modules/publication-experiment-registry.module.json` | `692e47abc2b25bf39f0999d83343bb482a8e9410` | `9c8ef53218df585736cc7ac35bab8cd5c7fc63817ea042453df806670b694366` | přesná shoda |

### Modulový projekt

- Project ID: `af24865c-a81f-58c9-b572-a397bd0c3d6e`.
- Git HEAD: `e9eea387918ed726daf7ee8c40ff309bd6fd8418`.
- Snapshot: 44 souborů / 22 entit; pracovní strom čistý.
- Graf: 19 jedinečných uzlů; batch: 1, milestone: 10, task: 8.
- ID v připnutém mappingu a živém grafu jsou totožná (19/19).
- Journal: 0 pending / 0 unfinished.
- Připnutý mapping SHA-256: `6cd535a8435e9d253181a9d7a9e6aadaf1bf7e845d77e6fc09b9e0167d51f86f`.

| Zdroj | Připnutý commit | SHA-256 | Bajty v projektu |
|---|---|---|---|
| `ROADMAP.md` | `446d98026b8ac9341d0995ab5387a6e83e7ecffd` | `b725af67023e9b844c1e143d20999edb8e2a331b602a996b12df03faf2bf0e83` | přesná shoda |
| `TODO.md` | `446d98026b8ac9341d0995ab5387a6e83e7ecffd` | `1fa36022b64e4b24aa348c0170a6799923c135b47129cdfadf6f92792f915d69` | přesná shoda |
| `module.json` | `446d98026b8ac9341d0995ab5387a6e83e7ecffd` | `9c8ef53218df585736cc7ac35bab8cd5c7fc63817ea042453df806670b694366` | přesná shoda |

Všech 13 zdrojů odpovídá přesným bajtům a velikostem posledního manifestu.
Deset hostitelských zdrojů bylo navíc porovnáno přímo s jejich původním Git
commitem. Tři modulové zdroje byly porovnány s připnutým manifestem a
importovanými zdrojovými artefakty; toto není nové otevření původního modulového
checkoutu. Sémantická správnost přiřazení a úplnost požadovaného rozsahu vyžadují
lidské posouzení; shoda hashů ani počtů je sama nedokazuje.

## Provedené předání

Lokální balík `.worktrees/dev-01-handoff-evidence/` není součástí PR;
na rozdíl od původních `/tmp` reportů zůstává v pracovním adresáři při restartu.
Obsahuje historický `source-delta.patch`, přesný `request.json` / `preview.json`,
receipts obou operací a původní `authority-handoff.patch`. Původní návrhový
patch se znovu neuplatňuje; výsledná evidence a skutečné stavy jsou v tomto
záznamu a WORK_LOG. Schválený náhled byl aplikovaný: pět novějších snapshotů,
samostatná specifikace
DEV-03 s pravidly agentů a rozcestník změn, celkem sedm nových artefaktů /
15 změněných cest. Novější pracovní snapshoty nejsou vydávány za bajty
Git commitu; jejich provenance váže výchozí commit a přesný digest obsahu.
Původní source artefakty se nepřepisují a ID existujících úkolů se nemění.

Preview SHA-256: `3e436a09ff56cac4ec79aa327c6d617a87c3ea60e86577fc4775c8f5ef417d7a`.
Před apply se znovu shodoval expected HEAD i přesný digest. Nativní operation
`6db660d3-43ba-4405-8f7e-253e0b264650` vytvořila projektový commit
`35dfc351e001353635050766b7668725489cb61b`. Všechny kandidátní bajty byly
zpětně porovnány, graf zůstal validní a journal idle.

Následný zápis potvrzené akceptace má preview SHA-256
`2afdb43cd42201865f77a8f3a2c378839cffe1ed2d5d4f396825ecbe23e638d0`,
operation `17b3eef7-f0be-4bf9-8592-e4acbfc531de` a výsledný host HEAD
`32a3bc04a6b00bfa0557f204ab662d2f9576e598`. Host má 686 souborů a validní
graf 712 uzlů; batch DEV-01 i všech 14 podúkolů jsou uzavřené. Původní
REFINE/RECONCILE experimenty jsou výslovně označené jako historické nahrazené
postupy, nikoli dodatečně akceptovaný první import. Akceptační artefakt
`41573b20-5d8d-53f8-8c01-c8985caab118` zaznamenává důvod i oddělené doručení.
DEV-03 a PLAN-SEMANTIC-AUDIT-01 zůstávají otevřené; jejich podklady byly
zachovány a navázány na správné existující ID. Modulový HEAD se neměnil.

Po obou operacích byly porovnány receipt HEAD, všechny kandidátní bajty,
stabilní ID i parent vazby, čistý pracovní strom a journal s 0 pending /
unfinished. Každá operace má vlastní native receipt a replay ID; mezi
projektovým zápisem a úpravou zdrojových pointerů není předstíraná atomicita.
Pravidla AGENTS a zdrojové pointery byly poté změněny podle přijatého diffu
a návrhové formulace nahrazeny skutečnými výsledky.

Celá testovací sada po poslední relevantní změně kódu/testů prošla;
konkrétní výsledky a omezení jsou v [uzavřené evidenci WORK_LOG](../WORK_LOG.md#dev-01--roadmapa-jako-projektová-data-a-export-úkolů--2026-10-31).
Uložený IDE export byl znovu porovnán se živým grafem: všech 709 task záznamů
se shoduje včetně obsahu, nikoli pouze ID. Poslední zaznamenaný sync byl
`2026-10-30T23:51:19.752Z`, `stale=false`; jde o konkrétní vzorek a shodu
uložených souborů, nikoli důkaz všech uživatelských UI operací po restartu.

## Doručení zdrojové feature

Čeká se na jediný PR `feature/dev-01-roadmap-migration -> develop`.
Push, otevření PR, merge ani commit v tomto vývojovém repozitáři nebyly
provedeny a vyžadují výslovný požadavek. Nová DEV-03 se aktivuje až po
merge na vlastní větvi z aktuálního develop; stacked výjimka nebyla schválena.
Před zahájením se načte aktuální schválené zadání z Workspace a vymezí
UI/review část DEV-03 podle přijatých podkladů.
