<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-BACKEND-01: Provider-neutral backend a role kontrakt

Milník M3; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M3-BACKEND-01 — Provider-neutral backend a role kontrakt

- Stav: [ ] [in progress]; aktivováno po začlenění PR #34 dne 2026-09-19.
- Původ: roadmapa M3 „Backend abstraction“ a „Role“; navazuje na Context Manifest, durable Ollama run lifecycle a centralizovaná node-local nastavení.
- Skutečná větev: `feature/f-m3-backend-01-provider-neutral`, založená z `develop` (`f493a33`); jediný budoucí PR do `develop`.
- Výstup: provider-neutral kontrakt capabilities, targetu, bindingu, role a run lifecycle; současná Ollama implementace jej používá bez oslabení trust/privacy hranic.
- Mimo rozsah: první externí provider, provider credentials, usage/billing, automatický routing/fallback, multi-role workflow a změna Context Manifestu bez samostatného rozhodnutí.
- Recovery: síťový účinek zůstává durable před dispatch; `unknown` se automaticky neopakuje a změna bindingu, targetu, modelu nebo capability zneplatní připravený handoff.
- Akceptace: role je nezávislá na provideru/modelu; capabilities jsou explicitní a fail-closed; Ollama prochází společným kontraktem; provider nemůže obejít manifest, aplikační autorizaci ani privacy; restart/retry zachová stávající právě-jednou hranici.

- [x] [completed] **F-M3-BACKEND-01-A — Kontrakt backendu, capabilities, rolí a reuse review (cílová úroveň: designed).** [ADR 0008](docs/adr/0008-context-and-publication-contracts.md#provider-neutral-aplikační-kontrakt-v1) uzavírá striktně verzované `BackendBinding`, `BackendCapabilities`, `RoleDefinition`, `BackendAdapter` a `BackendRunStore`, fail-closed registry i revalidaci před dispatch. Mapování potvrdilo neutrální `ContextBuilder`, ale přímé Ollama vazby ve službách a rozptýlené konstanty rolí. Migrace zachová binding v1 i ID/revize a stávající run evidence; legacy `dispatching`/`unknown` se neopakují a `prepared` lze dokončit jen při shodném digestu. Reuse review v `REUSE_CATALOG.md` volí adaptaci současné recovery namísto cizí abstrakce bez manifest/privacy hranic. Dokumentační kontrola a `git diff --check` dokončeny 2026-09-19; implementace a migrační testy patří do B/C.
- [x] [completed] **F-M3-BACKEND-01-B — Společný adapter/run kontrakt a migrace Ollamy (cílová úroveň: implemented).** `spikes/backend_contract.py` zavádí striktní capabilities, role, execution identitu, společné chyby a explicitní adapter registry bez discovery/fallbacku. Chat, souhrn, extrakce a návrhy metadat načítají binding přes společný registr; role-based služby vážou přesnou roli a výstupní formát. Ollama zachovává binding v1, endpoint/TLS/boundary validaci i `ollama-runs.sqlite`; run evidence nově váže adapter, binding, capability, roli, manifest a request digest. Transakčně rozšířená legacy DB zachová dokončené/unknown řádky, `unknown` neopakuje a `prepared` migruje jen při shodném původním digestu. Cíleně prošlo 21 testů; úplná sada `python3 -m unittest discover -s tests -v` prošla 2026-09-19: 288 testů, 22 environmentálních skipů. První sandboxový běh měl 24 výhradně socketových `PermissionError`; opakování s povolenými lokálními sockety prošlo.
- [x] [completed] **F-M3-BACKEND-01-C — Integrace služeb, negativní scénáře a dokumentace (cílová úroveň: PoC validated).** Testy dokládají společnou execution identitu pro chat (`generate-text`/`text` bez task role), summarizer (`summarizer`/`text`), extractor (`extractor`/`json`) a metadata advisor (`metadata-advisor`/`json`). Fail-closed scénáře pokrývají neznámý adapter, capability a revizi role, změnu bindingu/targetu/modelu nebo capability po přípravě, přesný manifest/request digest, restart, durable úspěch i `unknown` bez automatického retry a zachování same-node/private-network/privacy hranic. UI a uživatelský návod se nemění, protože binding v1 i ovládání zůstaly kompatibilní; ADR 0008 a roadmapa popisují skutečný nový kontrakt a jeho omezení. Cíleně prošlo 22 testů; úplná sada `python3 -m unittest discover -s tests -v` prošla 2026-09-19 mimo socketově omezený sandbox: 290 testů, 22 environmentálních skipů. Akceptace dávky je splněná; uzavření a archivace čekají na commit/push a začlenění jediného PR do `develop`.
