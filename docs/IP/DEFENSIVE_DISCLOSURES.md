<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Defensive Disclosures

Provozní evidence k [IP roadmapě](<IP, Defensive Publication & Crowdfunding Roadmap.md>), zejména sekcím 4–11, 20 a 30. Patentové podklady drží [Patent Risk Register](PATENT_RISK_REGISTER.md). Stav k 2026-09-09: **implemented — struktura registru; žádné dokončené disclosure ani ověřená publikace zde nejsou evidovány**.

## Rezervované náměty

ID níže jsou plánované náměty, nikoli záznamy se stavem `draft` nebo `published`. Stav `draft` vznikne až s konkrétním technickým dokumentem. Podklady dokládají pouze návrh nebo uvedený PoC, nikoli datum veřejného zveřejnění. Náměty lze slučovat; původní ID zachovat s odkazem na výsledný dokument.

| ID | Téma | Existující podklad a hranice |
| --- | --- | --- |
| DD-001 | Core artifact-centric architecture | [ARCHITECTURE](../../ARCHITECTURE.md), [DATA_MODEL](../../DATA_MODEL.md) — designed |
| DD-002 | Git authoritative state + rebuildable index + recoverable operation | [ADR 0001](../adr/0001-m0-baseline.md), [ADR 0002](../adr/0002-metadata-journal.md) a [ADR 0003](../adr/0003-coordinated-operation.md) — koordinovaná operace Linux PoC validated; produkční integrace otevřená |
| DD-003 | Context Manifest | [ARCHITECTURE](../../ARCHITECTURE.md), master roadmapa §10 — designed, kontrakt zbývá uzavřít |
| DD-004 | Execution boundaries and fail-closed backend selection | [SECURITY](../../SECURITY.md), master roadmapa §9 a M0 — designed, nevynuceno aplikací |
| DD-005 | Federated backend capability model | Master roadmapa M0/M5 — návrhové požadavky; kontrakt otevřený |
| DD-006 | Deterministic orchestrator + optional LLM orchestrator chat | Master roadmapa §0, §9 a M0 — návrhové požadavky; aplikační orchestrátor neimplementován |
| DD-007 | Multi-role artifact-based process isolation | Master roadmapa §11 a M4 — návrhové požadavky, workflow neimplementováno |
| DD-008 | Bidirectional external client / Open WebUI integration | Master roadmapa §21 — návrhové požadavky, integrace neimplementována |
| DD-009 | Provenance and reproducible LLM execution | [DATA_MODEL](../../DATA_MODEL.md), master roadmapa §16 — návrh; kompletní LLM provenance neimplementována |
| DD-010 | Federation trust and offline operation | [FEDERATION](../../FEDERATION.md) — designed, síťová federace zůstává M5 |

[Master roadmapa](<../../Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) určuje rozsah produktu; dokončené výstupy a důkazy drží [WORK_LOG](../../WORK_LOG.md), aktuální práci [TODO](../../TODO.md). Náměty nejsou závazkem vytvořit deset samostatných publikací.

## Šablona záznamu

```yaml
id: DD-XXX
title: null
version: null
status: draft # draft | published | superseded
document: null
created: null
authors: []
published: null
implementation_level: null # designed | implemented | PoC validated | production-ready
git_commit: null
git_tag: null
github_release: null
doi: null
related_architecture: []
related_adrs: []
related_patent_risks: [] # PR ID; doplnit zpětný odkaz v patentovém registru
known_prior_art: []
supersedes: null
publication_evidence: [] # veřejné URL a datum ověření
```

Technický dokument musí pokrýt problém, řešení, datové struktury a toky, komponenty, algoritmus/state machine, alternativy, interoperabilitu, bezpečnostní invariants a failure/fallback scénáře podle sekce 4 roadmapy. Uvést přesnou verzi podkladů a odlišit návrh od ověřené implementace. Existující ADR automaticky není hotové disclosure.

`published` použít až po splnění Definition of Done v sekci 30: veřejný commit, pevný tag, release nebo jiný veřejný publication point, datum a dohledatelné vazby. DOI je volitelné; pokud vznikne, propojit jej obousměrně s konkrétní verzí. Neznámé SHA, data, autory ani DOI nedoplňovat odhadem. SHA označuje zmrazenou technickou revizi; následný commit doplňující publikační metadata ji nenahrazuje. `superseded` zachovává historii a vazbu nové verze přes `supersedes`.

## Nejbližší práce

- [ ] [planned] **designed — cíl:** vybrat první disclosure nebo sloučený dokument z DD-001/DD-002; popsat současný návrh a limity PoC podle ADR, odlišit dokončený M0-01 Linux PoC od produkční připravenosti.
- [ ] [planned] **designed — cíl:** u dalších významných architektonických změn posoudit DD-003 až DD-010 a evidovat výsledek včetně případného sloučení.
- [ ] [planned] **designed — cíl:** před prvním zveřejněním dokončit technický text, review patentových vazeb a publikační checklist; po publikaci ověřit řetězec commit ↔ tag ↔ release ↔ disclosure ↔ případné DOI a odkazy na PR záznamy.
