<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-PROJECT-REPAIR-01 / kontrola a oprava projektů

Aktivní návrhová dávka připravuje obecný nástroj **Check & Repair** pro
registrované projekty nedostupné z jiného důvodu než doslova chybějící
umístění. Skutečná větev je `feature/ux-project-repair-01`, lokálním základem
je `develop` na commitu `d24ad26` po administrativním začlenění release změn a
cílem jediného PR je `develop`. Vzdálený `origin/develop` je zatím na
`9fb4262`; před předáním se musí release změny doručit spolu s touto větví nebo
samostatně synchronizovat podle pokynu uživatele.

Rozsah končí návrhem diagnostického reportu, povolených opravných akcí, UI a
recovery hranic. Neimplementuje opravný backend ani UI, neopravuje chybné
projektové bajty heuristikou a nenahrazuje již dodané akce **Opravit
umístění** a **Odregistrovat** pro chybějící kořen. Autoritou návrhu je
[ADR 0035](docs/adr/0035-project-check-and-repair.md).

- [x] [completed] **UX-PROJECT-REPAIR-01-A — inventura a reuse rozhodnutí
  (cílová úroveň: designed).** Prověřeny katalog projektů, validační CLI,
  `Projects`/`Workspace`, uzlový a projektový journal, Git adapter, validátory
  metadat a atomický rebuild indexu. Návrh je reuse/adaptuje; nevytváří druhý
  journal, index ani obecný filesystemový opravář.
- [x] [completed] **UX-PROJECT-REPAIR-01-B — read-only diagnostický kontrakt
  (cílová úroveň: designed).** ADR 0035 definuje stabilní kódy zjištění,
  vrstvy registrace/cesta/Git/projekt/journal/index, konzistenční token,
  klasifikaci `healthy`, `repairable`, `manual` a `retry` a zákaz mutací při
  kontrole. Neznámý nebo souběžně změněný stav selže uzavřeně.
- [x] [completed] **UX-PROJECT-REPAIR-01-C — opravné a recovery hranice
  (cílová úroveň: designed).** Návrh povoluje v prvním implementačním řezu
  pouze rebuild odvozeného indexu a pokračování již existujícího přesně
  identifikovaného journalového intentu. Každá akce má nový náhled, potvrzení,
  precondition token a receipt; změna autoritativního Git obsahu, práv,
  identity či odstranění dat zůstává ruční a mimo tento nástroj.
- [ ] [in progress] **UX-PROJECT-REPAIR-01-D — review návrhu a vymezení
  implementační návaznosti (cílová úroveň: designed).** Projít s uživatelem
  diagnostické kategorie, první dvě opravné akce a umístění vstupu v menu
  nedostupného projektu. Po přijetí návrhu předat implementaci jako samostatnou
  navazující feature dávku, aby tento návrhový PR nemíchal nový persistentní
  zápis s architekturou.

## Persistentní a crash hranice

- projektový Git commit je autorita projektových dat; Check & Repair jej
  automaticky nepřepisuje ani nevytváří náhradní `project.json`;
- `index.sqlite` je pouze obnovitelná projekce validovaného `HEAD`; rebuild
  publikuje celou novou projekci atomicky a po pádu se bezpečně opakuje;
- `journal.sqlite` je autoritativní evidence nedokončené operace; nástroj jej
  nemaže ani neupravuje a může pouze vyvolat existující recovery nad původním
  operation ID nebo přesně svázanými pending řádky;
- uzlová registrace a identity leží mimo projektový Git; jejich změna používá
  stávající uzlový journal, nikoli diagnostický report;
- read-only report se váže na digest registrace, identity cest, `HEAD` a stav
  journalu/indexu. Jakákoli změna před potvrzením zneplatní náhled.

## Podmínky dokončení

- diagnostika sama nevytvoří soubor, SQLite databázi, zámek ani Git objekt;
- každý problém má stabilní kód, bezpečné vysvětlení bez úniku lokálních cest
  do síťového UI a právě jednu další volbu: bezpečná oprava, ruční postup nebo
  nové načtení;
- mutující akce je oddělená od kontroly, přesně pojmenovaná, předem zobrazí
  účinek a vyžádá potvrzení nad stále platným tokenem;
- navržená recovery zachovává rozdělení Git autority, journalu a odvozeného
  indexu a neoznačí neznámý stav za opravený;
- dokumentace, odkazy a finální diff jsou konzistentní; přijetí návrhu
  uživatelem je zaznamenané před archivací dávky.

## K předání do backlogu

- Navazující implementační dávka po přijetí ADR 0035: read-only diagnostický
  backend a report v menu nedostupného projektu; poté samostatně potvrzené
  akce rebuild indexu a recovery existující operace v rozsahu schváleném
  uživatelem.
