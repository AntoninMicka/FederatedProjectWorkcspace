<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-OLLAMA-01: Důvěryhodná lokalita Ollama backendu

Milník M2; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci M1-07. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-OLLAMA-01 — Důvěryhodná lokalita Ollama backendu

- Stav: [ ] [in progress]; cílová úroveň PoC validated.
- Původ: Ollama a execution boundaries z roadmapy a [ADR 0008](docs/adr/0008-context-and-publication-contracts.md).
- Skutečná větev: `feature/f-m2-ollama-01-locality`, založená z `develop` (`ab2a5ea`, PR #26 začleněn); jediný budoucí PR do `develop`.
- Výstup: Ollama adapter a lokální binding, které prokazatelně odliší proces na stejném uzlu od privátního LAN endpointu a vážou skutečný cíl/model do Context Manifest handoffu.
- Mimo rozsah: cloud provider, obecná federace, automatické vyhledávání Ollama služeb, chat UI, sumarizace a publikace výsledků.
- Akceptace: `same-node` a LAN nelze zaměnit konfigurací, DNS rebindingem ani HTTP redirectem; LAN má vlastní explicitní boundary, identitu cíle a transportní policy; `local-only` se na LAN neposílá; neexistuje implicitní LAN/cloud fallback; testy pokrývají nedostupnost, změnu cíle a restart.

- [x] [completed] **F-M2-OLLAMA-01-A — Execution boundary a binding kontrakt (implemented, 2026-09-17).** ADR 0008 a striktní node-local kontrakt rozlišují `same-node` číselný loopback od `private-network` číselné privátní HTTPS adresy s připnutým certifikátem a stabilní identitou; DNS, credentials v bindingu a neznámá pole se odmítají.
- [x] [completed] **F-M2-OLLAMA-01-B — Ollama adapter a bezpečný dispatch (implemented, 2026-09-18).** Adapter přijímá pouze autorizovaný handoff s přesným run ID/Target, znovu váže binding a request digest, před privátním HTTPS požadavkem ověří cert pin, nepovoluje redirect ani fallback a vede node-local SQLite run journal. `dispatching` se potvrdí před sítí; ztracená odpověď je `unknown` bez automatického retry, známé HTTP/response odmítnutí je durable `failed`.
- [ ] [in progress] **F-M2-OLLAMA-01-C — Restart, chybové scénáře a ověření (cílová úroveň: PoC validated).** Pokrýt same-node/LAN, DNS změnu, redirect, nedostupnost, změnu modelu/cíle, local-only a restart konfigurace; aktualizovat dokumentaci/reuse a spustit cílenou i celou sadu.

### Recovery hranice

- Binding/configurace je node-local stav mimo projektový Git a nesmí obsahovat přihlašovací tajemství.
- Adapter před síťovým pokusem potřebuje durable run record s přechodem `dispatching`; jeho návrh a implementace jsou součástí této dávky jen v rozsahu nutném pro bezpečný Ollama dispatch.
- Po ztrátě odpovědi se výsledek označí `unknown`; automatický retry nesmí zopakovat potenciálně nákladný nebo stavově významný běh.

### K předání do backlogu

- [x] [completed] **F-M2-OLLAMA-AH-01 — Začlenit návrh periodického monitoringu do roadmapy (designed, 2026-09-18).** Požadavek je zachycen v sekci 23 roadmapy a dávkách `MON-00` až `MON-06` v BACKLOG. Nemění akceptaci ani rozsah aktivní Ollama feature; při jejím předání se tato evidence odstraní z TODO, protože aktuální stav požadavku drží BACKLOG.
