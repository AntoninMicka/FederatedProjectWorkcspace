<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# MON-01 — ruční reporting

Lokální služba `spikes.reporting.Reporting` a CLI ukládají reportingové revize
přes registrovaný Workspace. Podporují definici tasku a škály, zdrojové
deskriptory, události s více zdroji, hodnocení, story rozhodnutí a vydání přesných
Markdown bajtů. Výběr podkladů, úsudek a text reportu kontroluje místní uživatel.
Datový formát: [kontrakt v1](reporting-contract-v1.md); persistence a recovery:
[ADR 0068](adr/0068-manual-reporting-transactions.md).

Tento řez nemá grafické formuláře, scheduler, Source Collector, externí
LLM/doručení, automatické určování late discovery ani trendové syntézy.
Policy dokumenty jsou připnuté podklady lidského rozhodnutí, nikoli spustitelná
pravidla. CLI neotevírá síťové zdroje ani nespouští jejich obsah. Cross-project
reference odmítá, dokud nebude připojen autorizovaný handoff XREF-01.

Navazující [MON-02 Source Collector](source-collector.md) přidává samostatný
potvrzený fetch a import, aniž by měnil tento ruční writer či vytvářel Event.

## Izolovaná spustitelná ukázka

Z kořene zdrojového repozitáře:

```sh
python3 -m scripts.reporting_demo /tmp/fpw-reporting-example
```

Cíl musí být nový neexistující adresář s existujícím rodičem. Příkaz vytvoří
vlastní node.json, projekt a lokální stav; nemění běžný uzel. Obsahuje
syntetickou policy, škálu, task, dvě odporující source reference, událost s
neznámým datem, story a vydaný report. Zdroje jsou reference-only: ukázka
nepředstírá archivaci ani skutečné ověření tvrzení. Výstup obsahuje project_id
a připnutý report. Vedle projektu zůstávají přesné `<operation-id>.request.json`
a `<operation-id>.receipt.json`, použitelné jako příklady pro CLI.
Potvrzení ukázky platí pouze pro syntetická data, nikoli produkční akceptaci.

## Ruční použití CLI

```sh
python3 -m spikes.reporting --node /cesta/node.json list PROJECT_UUID
python3 -m spikes.reporting --node /cesta/node.json pin PROJECT_UUID ARTIFACT_UUID
python3 -m spikes.reporting --node /cesta/node.json pin PROJECT_UUID ARTIFACT_UUID --commit FULL_COMMIT
python3 -m spikes.reporting --node /cesta/node.json apply request.json --operation-id OPERATION_UUID
python3 -m spikes.reporting --node /cesta/node.json apply reviewed-report.json --operation-id OPERATION_UUID --confirm
```

Jde o lokální administrativní CLI pod identitou uživatele vlastnícího uzel,
nikoli HTTP API. Read-only replika zůstává chráněná původním write guardem.
`list` obnoví pending Workspace operaci a vrací neměnné revize, jejich tipy
a deduplikační projekci aktuálních story. Konfliktní graf se odmítne.
`pin` vrací přesný commit, cestu a hash sidecar obsahu; reference se před
vydáním znovu ověřují.

`request.json` má právě `project_id`, `base_head` a `records` (1–32 položek).
Každá položka má právě:

| Pole | Význam |
| --- | --- |
| `type` | Jeden z typů kontraktu v1. |
| `entity_id` | `null` pro novou identitu, stávající UUID pro následníka. |
| `previous` | PinnedRef rodičů; pro genesis `[]`. |
| `privacy` | public/project/confidential/local-only; nesmí uvolnit použitý vstup. |
| `value` | Úplný uzavřený objekt příslušného schématu z kontraktu. |
| `markdown` | Pouze u ReportSnapshot: přesný zkontrolovaný Markdown řetězec. |

Reference musí být již vydané/připnuté. Nejdříve uložte policy dokumenty a
EvaluationScale, potom ReportingTask, Source, Event a návazné záznamy.
Stejná URL sama nic nededuplikuje.

Aplikace vyplní recorded_at/by, revision ID, provenance a při prvním přijetí
Source/Event imported_at (v požadavku může být null). Následník zachová původní
importní čas. Revision UUIDv5 vychází z operation ID a `record:N`, nová identita
z `entity:N`, Markdown sourozenec z `markdown:N`; N je index položky od nuly.

Nové review/approval má actor_id a at null, zvolenou decision, policy_revision
a důvod note. `--confirm` potvrzuje přesný požadavek místním uživatelem;
aplikace doplní jeho skutečné ID a čas. Podvrženou identitu nepřijme.
Existující story rozhodnutí se do následníka kopírují beze změny.

U ReportSnapshot musí být value.markdown null. Generation má mode manual a
context_manifest_ref null; run_id a result_sha256 doplní aplikace z operation
ID a Markdown bajtů. Approval musí používat publication policy tasku. Prázdný
report obsahuje větu `Nebyla doložena významná změna.`; každý report obsahuje
required_sections tasku. Neznámé datum/zjištění a reference-only zdroje
vyžadují limitations; reference-only nedovoluje exact-inputs reprodukci.

## Opravy a obnova

- Editace vytváří nový artefakt stejné entity s previous; Event potřebuje
  correction_reason. Dva nezávislé tipy jsou sémantický konflikt.
- Story duplicate nemaže Event ani Source. Retract v následníkovi uvede
  reverses na předchozí aktivní rozhodnutí a stejná event_ids. Historie je
  append-only; projekce znovu oddělí události a staré reporty nezmění.
- Oprava reportu má novou identitu, previous=[], corrects a důvod. Zachová
  task a periodu. Nový cutoff/operation ID ani připnutí stejné task revize
  v novějším commitu neobejde zákaz druhého základního vydání periody.
- Po ztracené odpovědi zopakujte **stejné operation ID, stejný požadavek a
  stejnou hodnotu --confirm**. Vrátí se původní receipt. Jiný intent pod
  stejným ID se odmítne; nové ID není retry.
- Pending operaci obnoví list/pin přes Workspace recovery. Cizí editace nebo
  staging se nepřepíše. Po změně HEAD zachovejte rozepsaný požadavek a
  připravte nové review nad aktuální revizí. Unknown nejprve diagnostikujte.
- Chybějící/stale SQLite index se obnoví z HEAD. Reportingová projekce se
  odvozuje z Git bajtů; není druhou persistentní evidencí. Ztráta journalu
  není běžný rebuild a neopravňuje k novému publikačnímu pokusu.

`tests.test_reporting` ověřuje dočasné registrované projekty, více zdrojů,
následníky, deduplikaci/retract, konflikty, opravy vydání, retry, strict
JSON/verze/hash/privacy, DST, index rebuild, skutečné CLI a pády procesu kolem
Git CAS. Fyzický výpadek proudu ani přerušení uvnitř libovolného syscallu
tímto nejsou simulované. Konkrétní výsledky běhu patří do předání k review.

Ověření 4. 11. 2026 po poslední změně implementace:

| Kontrola | Výsledek |
| --- | --- |
| `python3 -m unittest tests.test_reporting -v` | 21 testů OK; včetně deseti process-crash hranic a skutečného CLI. |
| `python3 -m unittest discover -s tests -v` | 1509 testů za 500,351 s, OK; 44 skipped. Spuštěno s oprávněním pro lokální sockety, které omezený sandbox odmítal. |
| `python3 -m scripts.reporting_demo /tmp/mon01-demo` a následné CLI list | Izolovaný uzel/projekt, 7 reportingových záznamů včetně vydání, přesné vstupy/receipts zachované; bez přístupu k externím zdrojům. |
| Diff, nové soubory, syntaxe Pythonu a místní odkazy | OK; včetně `git diff --check`. |

Původní neúspěšný sandboxový běh byl ukončen; nedokládá regresi ani úspěch
HTTP testů. Tabulka uvádí následný kompletní běh s lokálními sockety.
Volitelné Qt/WebEngine testy nebyly tímto běžným během aktivované; nejde o
ruční akceptaci běžného profilu nebo fyzický test výpadku napájení.

Zadání: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, MON-01,
queue revision 199, projektový HEAD `6b793ada176f43b1a571709b30ca792fc981f787`,
export `e2999add43d03394690c774f4b337a96f0dbf0181c2484ce0415ca934791e79c`,
packet `5d00588b495d8630e724561d091a86b9c259cbcbad030bd54778fb4ab5859cea`;
při načtení current=true, stale=false. Zdrojový základ `82cb613`.
Tento návod nepřepisuje plán ani neeviduje lidskou akceptaci MON-01.

Volitelné modelové návrhy pro Event, EvidenceAssessment a Story používají
samostatný tok [MON-03 — reportingové návrhy](reporting-proposals.md).
Generování nezapisuje projekt a přijetí vyžaduje přesné lidské potvrzení;
původní ruční CLI zůstává dostupné bez LLM.
