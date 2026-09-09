# Patent Risk Register

Provozní evidence k [IP roadmapě](<IP, Defensive Publication & Crowdfunding Roadmap.md>), zejména sekcím 2–3 a 11. Související publikace drží [Defensive Disclosures](DEFENSIVE_DISCLOSURES.md). Stav k 2026-09-09: **implemented — struktura registru; screening neproveden**.

## Počáteční watchlist — neověřeno

Názvy a označení jsou převzaté náměty ze vstupní roadmapy, nikoli ověřené údaje o patentech, vlastnících či překryvu claims. Každý řádek je kandidát k rešerši; nemusí odpovídat jedné patentové rodině. Po identifikaci více rodin vytvořit samostatné záznamy s vazbou na původní ID.

| ID | Námět ze zdrojové roadmapy | Dotčená návrhová oblast projektu | Stav / další krok |
| --- | --- | --- | --- |
| PR-001 | Airia — privacy / sensitivity / model routing | Privacy, výběr backendu | unknown; identifikovat rodinu a claims |
| PR-002 | Cisco — RAG chunk filtering podle RBAC | Context Builder, oprávnění před retrievalem | unknown; identifikovat rodinu a claims |
| PR-003 | AT&T — interoperable GenAI orchestration | Backend kontrakty, orchestrace | unknown; identifikovat rodinu a claims |
| PR-004 | Citibank — gateway / agent routing | Backend routing | unknown; identifikovat rodinu a claims |
| PR-005 | Citibank — explainable model routing + audit | Routing, audit běhu | unknown; identifikovat rodinu a claims |
| PR-006 | Microsoft EP4657277 — multi-LLM consent | Consent, execution boundaries | unknown; ověřit převzaté označení a rodinu |
| PR-007 | Microsoft provenance PCT / případná EP fáze | Provenance, Context Manifest | unknown; identifikovat PCT a ověřit případnou EP fázi |
| PR-008 | AI provenance + version control | Verze artefaktů a provenance | unknown; identifikovat rodiny i přihlašovatele |
| PR-009 | Decentralizované agentní governance systémy | Federace, trust, workflow | unknown; identifikovat rodiny i přihlašovatele |

Pro všechny řádky platí: bibliografie kromě převzatého námětu, právní status, jurisdikce, claims a míra překryvu jsou neověřené; design-around ani rozhodnutí nejsou posouzené. Poslední kontrola: neprovedena. Datum příští kontroly: neurčeno; první kontrola před implementací relevantní významné funkce dle sekce 3 roadmapy. Datum založení registru není datum patentové kontroly.

## Šablona ověřovaného záznamu

Po rešerši doplnit záznam pod stabilním PR ID. Neznámá pole ponechat explicitně neověřená; každé zjištění opřít o zdroj a datum ověření.

```yaml
id: PR-XXX
patent_or_application_id: null
title: null
owner_or_applicant: null
priority_date: null
filing_date: null
publication_date: null
jurisdictions: []
family_members: []
status: unknown # pending | granted | expired | abandoned | unknown; podle člena/jurisdikce
independent_claims: [] # číslo, znění/odkaz, verze a jurisdikce
project_component: null
project_revision: null
overlap: unassessed
current_design_around: unassessed
decision: unassessed
rationale: null
sources: [] # URL, identifikátor dokumentu, datum ověření
reviewer: null
last_checked: null
next_check: null
related_disclosures: [] # DD ID; není důkaz právního účinku
```

Rozhodnutí po screeningu: bez relevantního konfliktu / nízké riziko / design-around / hlubší claim analysis / odložit. Zaznamenat rozsah prověrky a její důkazy; samotný název nebo abstrakt není dokončené posouzení claims. Historii kontrol a rozhodnutí zachovat s datem, zdroji a revizí projektu. Publikační vazby doplnit obousměrně přes DD ID, kde jsou relevantní.

## Nejbližší práce

- [ ] [planned] **designed — cíl:** provést baseline screening PR-001 až PR-009, doplnit identifikátory, primární zdroje, claims, jurisdikce a termíny dalších kontrol. Akceptace: každý námět má dohledanou rodinu, nebo výslovně zaznamenaný neuzavřený výsledek rešerše.
- [ ] [planned] **designed — cíl:** při významné změně podle sekce 3 roadmapy zaznamenat posouzení mechanismu proti claims a rozhodnutí před implementací; případný design-around propojit s návrhem/ADR. Bez doložené potřeby neměnit přijatou architekturu.
- [ ] [planned] **designed — cíl:** určit odpovědnost a první datum periodické kontroly (doporučená cadence 3–6 měsíců) a kontroly před významným releasem či kampaní.
