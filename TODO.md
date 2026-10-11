<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-OUTPUT-ROUTER-01

Feature dávka **F-M4-OUTPUT-ROUTER-01 — Deklarativní katalog výstupních
capability a read-only kompoziční plán**.

- Původ: roadmapa 2E.1 a nejbližší dávka v BACKLOG; uživatel 2026-10-11
  výslovně požádal pokračovat dalším úkolem.
- Milník: M4; cílová úroveň: designed → PoC validated.
- Větev: `feature/f-m4-output-router-01` z `develop` na `916e5ec`; cíl jediného
  PR: `develop`. M1-LXC-DNS-TLS-01 byla doručena PR #58.
- Výstup: verzovaný přenositelný capability descriptor, fail-closed statický
  katalog a validovaný read-only plan/step DAG bez spuštění nástrojů.
- Hranice rozsahu: žádný execution, runtime discovery, node-local binding,
  credential, automatický výběr backendu, Git publikace ani UI spouštění.
  Materializované mezivýstupy, receipts, recovery a renderery patří navazující
  F-M4-OUTPUT-ROUTER-02 v BACKLOG.
- Reuse: adaptovat validační primitiva `module_manifest`, provider-neutral
  capability/role kontrakty ADR 0008 a explicitní artefaktové předání
  F-M4-WORKFLOW-01; descriptor není executable plugin ani oprávnění.
- Persistentní vrstvy/crash boundary: tato dávka pouze deterministicky čte
  verzované JSON descriptory a validuje request v paměti. Nezapisuje projektový
  Git, index ani journal; pád nezanechá rozpracovanou operaci.

## Úkoly a akceptace

- [x] [completed] **F-M4-OUTPUT-ROUTER-01-A — Descriptor a fail-closed katalog
  (implemented / locally PoC validated).** Uzavřený v1 kontrakt a statický
  katalog odmítají neznámá pole/verze, duplicity, symlinky, cizí schema
  reference, node-local konfiguraci i nekompatibilní deklarace. Verzovaný
  `renderer.web-static` descriptor popisuje pouze lokální statický webový bundle
  a výslovně nepovoluje publikaci, runtime discovery ani spuštění skriptů.
  Cílené ověření: 10 testů OK, 1 přeskočený kvůli omezení loopback socketu;
  úplná sada: 470 testů OK, 25 přeskočených volitelných environmentálních testů.
- [x] [completed] **F-M4-OUTPUT-ROUTER-01-B — Read-only plan/step DAG
  (implemented / locally PoC validated).** Uzavřený plán v1 váže kanonická
  plan/step/source/edge ID, přesný project commit, artifact a materializované
  snapshoty, typované porty a acyklické hrany. Samostatně dodaná policy je
  připnutá ID, revizí a hashem; přesná capability verze, permissions, privacy,
  execution boundary, cost a side-effect se ověřují bez dispatch, backend
  selection nebo fallbacku. Cílené ověření katalogu a plánů: 8 testů OK;
  úplná sada: 474 testů OK, 25 přeskočených volitelných environmentálních testů.
- [ ] [planned] **F-M4-OUTPUT-ROUTER-01-C — Planner boundary a dokumentace
  (PoC validated).** Vymezit nedůvěryhodný strukturovaný návrh planneru,
  aplikační revalidaci, vysvětlení volby/alternativ a navazující execution
  kontrakt; spustit cílené i úplné testy a uzavřít evidenci dávky.

[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)
