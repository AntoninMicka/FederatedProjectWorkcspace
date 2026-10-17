<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-EXPLICIT-TASK-ROUTING-01

Feature dávka **F-M3-EXPLICIT-TASK-ROUTING-01 — explicitní podklady, výstup a
vykonání úkolu** vznikla z uživatelského zjištění 2026-10-17, že veřejný lokální
model při společném promptu nespolehlivě volí druh výsledku a nadměrně vrací
prezentace. Cílová úroveň: **implemented → PoC validated**.

Aktivní větev je `feature/f-m3-explicit-task-routing-01`. Jde o uživatelem
schválenou stacked výjimku založenou nad checkpointem
`feature/f-m3-public-source-reader-01` (`ea7d101`), protože fyzická akceptace
readeru potřebuje spolehlivou explicitní cestu k webovému hledání. Po společném
ověření se feature doručí odděleně v pořadí reader → routing; cílem obou PR je
`develop`, push, otevření PR ani merge zatím nejsou schválené.

Rozsah: režim `orchestration` dostane deterministické volby podkladů
(`conversation`, `artifacts`, `public-web` a povolené kombinace), výstupu
(`conversation`, `document`, `presentation`) a vykonání. Aplikace, nikoli
model, zvolí jedinou roli a jediné očekávané schéma. Lokální potvrzená Ollama
smí pracovat s explicitně vybranou konverzací, projektovými artefakty a veřejným
webem. Externí brainstorming/task běh v prvním řezu smí pracovat pouze s
explicitně vybranou konverzací a veřejným webem; projektové artefakty zůstanou
viditelně zakázané. `local-only` nikdy neopustí `same-node`.

Webové hledání a Public Source Reader jsou fáze získání podkladů, nikoli druh
výstupu. Dokument a prezentace zůstávají validovaným preview; jejich existující
samostatné potvrzení a Workspace zápis se nemění. Mimo rozsah jsou automatický
modelový router, obecný workflow builder, nové providery, nativní providerové
web-search tooly a automatická publikace.

Crash hranice: nový durable task plan váže přesný zdrojový režim, output kind,
execution target, vybraná ID, privacy, expected HEAD a vlastní digest. Příprava
plánu nemá externí účinek. Search, reader a LLM runy si ponechají vlastní
journaly a recovery; plán na ně pouze odkazuje a nesmí automaticky opakovat
`unknown` účinek. Změna plánu, bindingu, HEAD, výběru nebo privacy vyžaduje nový
manifest/run.

- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-A — přesný task-plan
  kontrakt a policy (cílová úroveň: implemented).** Definovat uzavřené osy
  podklady/výstup/vykonání, kompatibilní kombinace, privacy hranice, digest a
  deterministický výběr jediné role/schématu; reuse/adaptovat `ChatRunChoice`,
  `ContextBuilder`, `TaskOutcomes` a existující output capability kontrakty.
  Implementováno uzavřeným `ExplicitTaskPlan`, digestem a rolemi
  `task-output-{conversation,document,presentation}-v1`; rozhodnutí zachycuje
  ADR 0034.
- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-B — backendové explicitní
  routování (cílová úroveň: implemented).** Odstranit volbu outcome druhu z
  obecného modelového promptu, odmítnout jiný než požadovaný druh, zachovat
  přesný výběr vstupů a propojit web jako zdrojovou fázi bez implicitního
  dispatch nebo projektového zápisu. Lokální i externí backend dostávají právě
  jedno schéma, jiný kind se odmítne. Web bez reader runu připraví pouze search;
  potvrzený reader run vstupuje do nového manifestu. Externí výsledek se po
  potvrzení atomicky redukuje na odpověď nebo reviewovatelný draft.
- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-C — desktopové volby a
  diagnostika (cílová úroveň: implemented).** V režimu Zadání úkolu zobrazit
  podklady, výstup a vykonání; nedostupné interní artefakty u externího cíle
  ponechat viditelné a vysvětlit důvod. Preview musí ukázat přesné zdroje,
  privacy, cílový model/boundary a očekávaný výstup. UI nyní zobrazuje režimy
  Zadání úkolu / Volná konverzace, tři zdrojové volby, výstup i backend;
  načtené veřejné runy jsou samostatně volitelné a karta výsledku zobrazuje
  skutečný plán.
- [ ] [in progress] **F-M3-EXPLICIT-TASK-ROUTING-01-D — automatické a fyzické
  ověření (cílová úroveň: PoC validated).** Ověřit všechny podporované matice,
  odmítnutí modelové změny output kind, stale HEAD/binding/plan, local-only a
  externí artifact hranici, restart/replay bez dvojího účinku a skutečné UI
  průchody: konverzace, dokument, prezentace, web → každý výstup a navazující
  Public Source Reader. Automatická část 2026-10-17: `python3 -m unittest
  discover -s tests -v` úspěšně, **634 testů, 27 přeskočeno**; běh proběhl s
  povoleným loopbackem. Samostatně ověřena syntaxe desktopového JS přes Node a
  `git diff --check`. Zbývá fyzický desktopový průchod uvedené matice; bez něj
  zůstává cílová úroveň pouze implemented, nikoli PoC validated.

Akceptace dávky vyžaduje cílené testy, celou současnou testovací sadu,
`git diff --check`, kontrolu dokumentace a fyzický desktopový průchod. Dávka
není připravená k PR, dokud společný fyzický průchod neodblokuje také reader.
