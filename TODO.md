<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-RESEARCH-WORKFLOW-01 — dynamický výzkumný workflow

Původ: uživatelem schválený směr po fyzickém ověření řízeného hledání,
readeru a dynamických revizí plánu; převzato se stejným ID z
[BACKLOG](BACKLOG.md). Milník M4, cílová úroveň **PoC validated**. Větev
`feature/f-m4-research-workflow-01` vznikla z `develop` `5d74144`; cílem je
jediný PR do `develop`.

Předchozí dávka `F-M4-DYNAMIC-WORKFLOW-01` byla doručena PR #88 jako merge
commit `5d74144`; její evidence je ve
[WORK_LOG](WORK_LOG.md#f-m4-dynamic-workflow-01--katalog-činností-a-dynamický-plán--2026-10-24).

## Rozsah a hranice

Nad existujícím search workflow, Public Source Readerem a typovaným katalogem
sestavit podle cíle proměnný tok `vyhledat → načíst → ověřit původ a vazby →
vybrat relevantní zdroje → volitelně analyzovat → sestavit zprávu`. Po každé
dokončené činnosti lze v aktivované policy navrhnout kompatibilní další krok,
opakování nebo předčasné ukončení; dokončená historie zůstává neměnná.

UI nabídne několik výchozích profilů, ale profil je pouze allowlist činností,
hranice a počáteční budget, nikoli pevná pipeline. Zvýšení celkového limitu
vyžaduje přesnou uživatelem potvrzenou revizi. Vyhledávání, fetch a LLM běhy
zůstávají v existujících doménových journalech a stav `unknown` se
automaticky neopakuje. Sestavená zpráva je reviewovatelný návrh; projektový
artefakt vznikne jen samostatnou přesně potvrzenou publikační operací.

## Úkoly

- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-A — kontrakt, profily, reuse a
  crash boundaries (cílová úroveň: designed).** Vymezit činnosti, typované
  vazby, dynamický planner, profilovou policy, persistentní autority a obnovu
  přes search, reader, provider a autonomy journal bez druhého writeru.
  Výsledek: [ADR 0048](docs/adr/0048-dynamic-research-workflow.md) definuje
  uzavřený katalog, tři výchozí profily, planner jako auditovatelný bounded
  krok a přesné recovery hranice. Reuse/reject je zaznamenán v
  [REUSE_CATALOG](REUSE_CATALOG.md).
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-B — výzkumný katalog a profily
  (cílová úroveň: implemented).** Přidat uzavřené deskriptory pro fetch,
  ověření evidence, výběr relevance, volitelnou analýzu, sestavení zprávy a
  návrh dalšího kroku. Validovat profilové policy, přesné vnořené vstupy a
  výstupy, povolené návaznosti a celkové limity.
  Výsledek: reviewovaný katalog obsahuje šest nových verzovaných akcí a
  profily `quick-search-v1`, `read-and-verify-v1` a `deep-research-v1` jako
  přesné allowlisty, nikoli pevné pipeline. `ActionRegistry` validuje uzavřené
  vnořené objekty, digesty, URL/binding readeru, evidence, citace, plannerovy
  podmíněné výstupy i jeho kandidátní vstup proti cílovému deskriptoru;
  profil nesmí rozšířit akce, permissions, privacy, hranice ani maximum.
  Ověření: `python3 -m unittest tests.test_research_workflow
  tests.test_action_autonomy -v` (28 testů OK), `python3 -m unittest
  tests.test_spdx -v` (1 test OK), `python3 -m unittest discover -s tests -v`
  (794 testů OK, 28 skipped) a `git diff --check` bez chyb.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-C — doménové adaptéry a dynamické
  materializování (cílová úroveň: implemented).** Adaptovat čistý reader
  candidate builder, existující search/reader/provider journaly a bounded
  source ledger. Plannerův výstup pouze navrhne append/repeat/finish;
  deterministický validátor z něj idempotentně vytvoří nejvýše jednu revizi.
  Výsledek: reader candidate je bez durable zápisu a opakované preview je
  stabilní i přes neautoritativní čas vytvoření; fetch, evidence, selection,
  analysis, report a planner používají stávající reader/Ollama journaly a
  hashově svázané source reference. Modelové JSON výstupy procházejí přesnými
  fail-closed validátory a nemohou doplnit cizí source ID. Plannerovo
  `append`/`repeat`/`finish` se materializuje z run ID a proposal hashe na
  deterministická UUID; replay ani restart nevytvoří druhou revizi a zvýšení
  limitu zůstává pending do přesného potvrzení. Ověření:
  `python3 -m unittest tests.test_research_workflow
  tests.test_autonomy_service.AutonomyServiceTests.test_research_planner_materializes_one_confirmed_budget_revision
  tests.test_chat_service.ChatServiceTests.test_web_search_requires_preview_and_reuses_results_after_restart
  -v` (8 testů OK), `python3 -m unittest discover -s tests -v` (796 testů OK,
  28 skipped), `python3 -m py_compile spikes/action_autonomy.py
  spikes/autonomy_service.py spikes/chat_service.py spikes/research_workflow.py`
  a `git diff --check` bez chyb.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-D — chatové UI a řízení průchodu
  (cílová úroveň: implemented).** Nabídnout profily a režim ruční/automatický,
  zobrazit fáze, zdroje, důvod změny, provenance, zbývající limit a přesné
  revizní potvrzení. Report zůstane návrhem se samostatným uložením.
  Výsledek: chat nabízí jednorázové hledání i tři reviewované profily v ručním
  nebo automatickém režimu. Aktivní průchod ukazuje skutečně materializované
  fáze, zdrojová URL a run ID, počty vazeb, výběr a závěry, důvody aplikovaných
  i čekajících revizí a zbývající cost/kroky/čas. Zvýšení limitu potvrzuje
  přesný digest revize. Dokončený report se načítá z provider journalu jako
  návrh; otevření pouze předvyplní běžný editor a Git se změní až jeho
  samostatným uložením. Ověření: cílené testy autonomy API, profilového cyklu,
  materializace revize a obnovení reportu prošly; `python3 -m py_compile
  spikes/desktop_ui.py spikes/action_autonomy.py spikes/autonomy_service.py
  spikes/chat_service.py`, kontrola generovaného JavaScriptu přes `node
  --check`, `python3 -m unittest discover -s tests -v` (797 testů OK, 28
  skipped) a `git diff --check` bez chyb.
- [ ] [planned] **F-M4-RESEARCH-WORKFLOW-01-E — regrese a realistická
  akceptace (cílová úroveň: PoC validated).** Ověřit předčasné ukončení,
  doplňující hledání, opakované načtení, ověření vztahů, výběr zdrojů,
  vloženou analýzu, prodloužení schváleného limitu, restart, `unknown` bez
  retry a nezměněný projekt před potvrzenou publikací.

## Akceptace

- Aktivovaný profil omezuje činnosti a hranice, ale nevynucuje pevné pořadí;
  každý dynamický následník projde typovou, policy, privacy a budget validací.
- Search, fetch a LLM účinky mají jedinou existující doménovou autoritu;
  planner ani autonomy queue účinek neopakují a neodhadují jeho úspěch.
- Původ, vazby, výběr a závěry jsou auditovatelně svázané s přesnými source/run
  ID a hashi; modelové hodnocení se nevydává za ověřený fakt.
- Limit lze zvýšit jen přes potvrzenou revizi, workflow může korektně skončit
  dříve a dokončená historie zůstává append-only.
- Zpráva se zobrazí jako návrh a do projektu se uloží až samostatným přesným
  potvrzením; cílené testy, úplná sada a realistický fyzický průchod projdou.
