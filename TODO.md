<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-WORKFLOW-01: Artifact-based creator/opponent handoff

Milník M4; jedna dávka, větev
`feature/f-m4-workflow-01-artifact-handoff`, budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivována 2026-10-06 z `develop` `da449bc`
  po začlenění F-M3-MEDIA-01 v PR #46. Tento aktivační dokument je první změna
  nové feature větve.
- Původ: roadmapa M4, ADR 0008 a backlogová položka `F-M4-WORKFLOW-01`.
- Výstup: první deterministicky řízený dvoukrokový workflow creator → opponent.
  Creator vytvoří bounded materializovaný výstup s hashem a provenance;
  opponent dostane pouze tento uživatelem schválený výstup a explicitně
  vybrané povolené podklady, nikdy implicitně celou creator konverzaci.
- Hranice: nejde o obecný agent framework, paralelní multi-agent běh, autonomní
  loop, pluginový/output router, background execution ani automatickou
  publikaci. První verze má právě jeden creator krok a nejvýše jeden opponent
  krok; role, adapter, binding a model se volí odděleně a bez fallbacku.
- Projektový Git je autoritou až pro explicitně publikovaný výsledek. Workflow,
  jednotlivé step/run záznamy, přesné Context Manifesty, materializovaný
  mezivýstup a approval jsou node-local durable stav mimo projektový Git a
  nejsou obnovitelným indexem.
- Crash boundaries: každý backendový run zachovává vlastní durable
  `dispatching`/`unknown` hranici. Pád po creator odpovědi nesmí vyvolat druhý
  providerový účinek; handoff se váže na uložené bajty/hash. Pád před publikací
  nemění projekt, pád během publikace obnovuje stejný Workspace operation ID.
  Změna HEAD, vstupů, policy, oprávnění, role, bindingu nebo materializovaného
  výstupu ruší starý souhlas a ve v1 vyžaduje nové workflow s novými
  step/run/manifest identitami, nikoli tichý retry.
- Privacy odvozeniny je nejpřísnější privacy a průnik oprávnění všech skutečných
  vstupů daného kroku. Backend druhého kroku nesmí rozšířit povolenou execution
  boundary. `local-only` nesmí opustit lokální hranici bez samostatné oprávněné
  reklasifikace, která není součástí v1.
- Reuse: adaptovat `ContextBuilder`, `RoleRegistry`/backend adaptery a run
  journals, `SummaryTasks` durable approval/publish pattern, Workspace recovery,
  bezpečný Markdown preview a existující desktop/web RBAC. Nevytvářet druhý
  Git writer, projektový index, provider pool, message queue ani vektorovou DB.

## Aktivní části dávky

- [x] [completed] **F-M4-WORKFLOW-01-A — Kontrakt workflow, isolation a reuse
  (designed).** Uzavřít verzi a validaci `workflow_id`, dvou
  stabilních `step_id`, samostatných `run_id`/`manifest_id`, stavů, role/binding
  identity, přesného vstupního selection a materializovaného creator outputu.
  Doplnit roli `opponent` bez změny oprávnění; popsat instruction/revision,
  formát, byte limit, hash, privacy/provenance, approval digest a publikovatelný
  výsledek. Zaznamenat reuse/adapt/reject a všechny persistentní/crash hranice;
  změnit ADR pouze tam, kde dosavadní rozhodnutí workflow neurčuje.
  Dokončeno 2026-10-06 v ADR 0008: v1 má právě jeden creator a nejvýše jeden
  opponent krok, samostatná step/run/manifest ID, explicitní role/binding/model
  a tři oddělená potvrzení dispatch, handoff a publikace. Creator output je
  neměnný UTF-8 Markdown do 1 MiB se SHA-256; opponent dostane povinně pouze
  tyto durable bajty a nula až 64 znovu explicitně vybraných artefaktů, nikdy
  prompt, chat ani celý creator kontext. Privacy je nejpřísnější průnik
  skutečných vstupů a trust boundary se nesmí rozšířit. Navržen je vlastní
  workflow journal v SQLite s režimem `0600` a dvěma step záznamy; backendové
  run journaly a Workspace zůstávají oddělenými autoritami účinků. Pro
  crash/restart/`unknown`, nové vědomé workflow a idempotentní publikaci jsou
  vymezené recovery hranice. Reuse katalog adaptuje `ContextBuilder`,
  `RoleRegistry`, adaptery, vzor `SummaryTasks` a Workspace; odmítá
  `ChatThreads` jako workflow autoritu i nový agent framework, frontu nebo DB.
  Runtime role `opponent-v1`, schéma, journal a validace zůstávají implementací
  části B.

- [ ] [planned] **F-M4-WORKFLOW-01-B — Durable dvoukrokový orchestrátor
  (cílová úroveň: implemented).** Implementovat striktní node-local workflow
  journal a aplikační službu: připravit creator Context Manifest a přesný
  request, potvrdit nejvýše jeden dispatch, validovat/uložit bounded výstup,
  zobrazit přesný opponent handoff a teprve po novém potvrzení připravit jeho
  samostatný manifest a run. Vynutit oddělené role/backendy, immutable hashe,
  privacy/RBAC revalidaci, žádný skrytý kontext, fallback nebo retry po
  `unknown`; restart musí navázat na doložené succeeded runy bez druhého volání.

- [ ] [planned] **F-M4-WORKFLOW-01-C — UI, opponent preview a publikace
  (cílová úroveň: implemented).** Desktop i oprávněný web zobrazí workflow a
  každý krok odděleně: zdroje, roli, backend/model, privacy, exact request,
  stav a materializovaný předávaný výstup. Uživatel samostatně potvrdí creator
  dispatch, opponent handoff/dispatch a až poté volitelnou publikaci vybraného
  výsledku jako Markdown artefaktu s workflow/step/run/manifest provenance.
  Změna kteréhokoli potvrzeného pole zneplatní navazující preview; publikace
  použije standardní Workspace recovery a serverové RBAC na desktopu i webu.

- [ ] [planned] **F-M4-WORKFLOW-01-D — Regrese, dokumentace a akceptace
  (cílová úroveň: PoC validated).** Ověřit creator a opponent se stejnými i
  různými explicitními backendy, nulové implicitní zprávy, přesné hashe a
  provenance, privacy/RBAC, stale HEAD/selection/policy/binding, malformed a
  oversized výstup, známé selhání versus `unknown`, restart na každé durable
  hranici, vědomě nový run a idempotentní publikaci bez duplicitního provider
  účinku. Spustit úplnou sadu a relevantní skutečný Qt/WebEngine i dostupný
  provider smoke; neprovedené živé ověření ponechat výslovně otevřené.

## Podmínky dokončení dávky

- Jeden creator → opponent scénář projde pouze přes dva samostatně autorizované
  Context Manifesty a hashovaný materializovaný handoff; opponent nedostane
  neuvedenou creator konverzaci ani jiné projektové bajty.
- Každý krok má stabilní identitu, přesný request, durable stav a doloženou
  recovery bez automatického opakování neurčitého síťového účinku.
- Výsledek se do Gitu dostane pouze samostatnou potvrzenou publikací s privacy a
  workflow/step/run/manifest provenance; retry vrací tentýž receipt/commit.
- Desktopové a webové UI zachovají stejné serverové autorizační hranice a
  bezpečné textové vykreslení nedůvěryhodného výstupu.
- Cílené testy, úplná sada, dokumentace, odkazy a `git diff --check` projdou;
  skutečné versus neprovedené živé ověření bude výslovně rozlišeno.

## K předání do backlogu

Zatím prázdné. Obecný output/plugin router zůstává samostatnou plánovanou dávkou
`F-M4-OUTPUT-ROUTER-01` v BACKLOG a není podmínkou dokončení tohoto workflow.
