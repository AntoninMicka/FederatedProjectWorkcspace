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
- [ ] [planned] **F-M3-BACKEND-01-B — Společný adapter/run kontrakt a migrace Ollamy (cílová úroveň: implemented).** Zavést minimální rozhraní a převést Ollama služby bez paralelní autority, implicitního fallbacku nebo oslabení same-node/private-network validace.
- [ ] [planned] **F-M3-BACKEND-01-C — Integrace služeb, negativní scénáře a dokumentace (cílová úroveň: PoC validated).** Ověřit chat, souhrn, extrakci a metadata přes společný kontrakt, neznámé capabilities/provider/role, změnu cíle, restart a `unknown`; aktualizovat UI/návod jen v rozsahu skutečně změněného chování a spustit úplnou sadu.
