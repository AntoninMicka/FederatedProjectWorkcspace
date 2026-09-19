<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-EXTERNAL-01: První externí provider a řízené volání

Milník M3; jedna dávka, větev `feature/f-m3-external-01-first-provider`, budoucí
PR do `develop`. [Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivováno po PR #35 dne 2026-09-19.
- Výstup: první externí textový provider, write-only credential, přesný preview a
  potvrzený dispatch; jednotné zadání Ollamě vrací přímou odpověď, návrh
  artefaktu, nebo připravený externí dotaz.
- Recovery: approval váže přesný manifest, payload, binding/model a credential
  reference. Durable `dispatching` vzniká před sítí; ztracená odpověď je
  `unknown` bez retry. Ollama sama nezapisuje do Gitu ani nevolá providera.
- Mimo rozsah: usage/billing `M3-UB-01`, obrazový pipeline `F-M3-MEDIA-01`,
  automatický routing/fallback, obecný agent runtime a synchronizace credentialů.

## Dokončené části dávky

- [x] [completed] **F-M3-EXTERNAL-01-A — Reuse a kontrakt (designed).** ADR 0008
  volí `openai-responses`, opaque node-local credential a nedůvěryhodný návrh
  Ollamy; soukromý kód bez doložené licence nebyl převzat.
- [x] [completed] **F-M3-EXTERNAL-01-B — Credential a textový adapter
  (implemented).** Přesný `store=false` request, striktní response parser,
  durable run journal, `unknown` bez retry a bezpečné nastavení bez vracení
  secretu. Úplná sada po opravě modelových ID: 300 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-B1 — Modelový katalog (implemented).**
  Explicitní omezené načtení, cache vázaná na binding/credential revizi a ruční
  modelové ID. Úplná sada: 302 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-C — Preview, privacy a potvrzený dispatch
  (PoC validated).** `local-only` fail-closed; ostatní privacy vyžadují potvrzení
  přesného hashe. Recovery po restartu/pádu neodesílá podruhé. Úplná sada:
  306 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-D — Ollama návrh a živá integrační
  akceptace (PoC validated).** Striktní návrh, explicitní výběr, nový manifest a
  samostatné potvrzení. První živé pokusy odhalily chybějící UUID v promptu a
  `reasoning` položku Responses API; obě opravy jsou fail-closed a tool cally
  zůstávají odmítnuté. Dva dřívější provider requesty mohou být účtované a
  neopakují se. Uživatel 2026-09-19 potvrdil úspěšný celý průchod po opravě.
  Ověření: 311 testů, 22 skipů, plus živá Ollama → OpenAI akceptace.

## Aktivní část E — jednotné lokální zadání a tři typy výstupu

- [x] [completed] **F-M3-EXTERNAL-01-E1 — Uzavřený outcome kontrakt
  (implemented).** `AITaskOutcome` dovoluje pouze `direct-answer`,
  `artifact-draft` nebo `external-request`; omezuje velikost, typ artefaktu a
  UUID zdrojů, odmítá provider/credential/tool pole. Přidána provider-neutral
  role `task-router-v1`. Ověření: vlastní testy a úplná sada 313 testů,
  22 environmentálních skipů dne 2026-09-19.
- [x] [completed] **F-M3-EXTERNAL-01-E2 — Durable orchestrace a artefaktový
  kontext (PoC validated).** `task_route` sestaví jeden manifest z explicitních
  artefaktů, seřazených zpráv a nového focus zadání, autorizuje jen vybraná UUID
  a striktně validuje outcome i jeho zdrojová ID. Context Builder nově bezpečně
  rozlišuje projektové vstupy od konverzace a focusu. Privacy výsledku je maximum
  všech manifestových vstupů; stejný request po restartu načte durable Ollama
  výsledek bez dalšího transportu. Ověření: cílené testy a úplná sada 315 testů,
  22 environmentálních skipů dne 2026-09-19.
- [x] [completed] **F-M3-EXTERNAL-01-E3 — Dočasné dlouhé zprávy a potvrzení
  (PoC validated).** Node-local `TaskOutcomes` obnoví po reloadu celý návrh a
  promítá jej jako dočasný, dokud jej uživatel nepotvrdí nebo nezamítne.
  Artifact potvrzení používá idempotentní Workspace operaci, zachová nejsilnější
  privacy a provenance `llm-generated`, poté obsah nahradí stabilním odkazem.
  Externí potvrzení znovu sestaví manifest i z vybraných artefaktů, používá
  existující exact approval/durable run a sjednocený tok redukuje na neobsahový
  provozní záznam bez zápisu plného requestu/response do `ChatThreads`.
  Crash hranice a retry jsou popsány v ADR 0008; backendové endpointy pokrývají
  route/list/cancel, artifact publish a external preview/confirm/cancel.
  Ověření: úplná sada 319 testů, 22 environmentálních skipů dne
  2026-09-19; předchozí sandboxový běh selhal pouze na zakázaném socket bindu.
- [ ] [planned] **F-M3-EXTERNAL-01-E4 — Jednotné UI a integrační akceptace
  (PoC validated).** Jedna hlavní akce, volba artefaktů, tři výsledné větve,
  limity bez tichého oříznutí, pády/reload a úplná sada. Ruční externí preview
  zůstane pouze pokročilou záložní akcí.
