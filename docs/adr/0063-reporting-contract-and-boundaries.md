<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0063 — Reporting kontrakt a hranice

Datum: 2026-10-31. Stav: **navrženo k review v MON-00; cílová úroveň designed**.
Datové struktury, stavové přechody a recovery tohoto ADR nejsou implementací
reportingového runtime. Přijetí návrhu eviduje oprávněný člověk ve Workspace.

## Zadání a kontext

Aktuální předání projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59` řadí jako
první zahajitelnou položku `MON-00 — Reporting kontrakt a hranice`.
Packet při prvním načtení `2c8b78c2693a6ef59e4c8d9d938286e23adcb8e48b10687506e422d660c7046f`,
queue revision `13`, projektový HEAD
`7e62e086fe010c4af0fef208946572a9d5e5c33f`, exportní revize
`d260870402c0ca5f48231320928793cc9d9b16848a4f4aa5fcf973903bd9c7f5`.
Při načtení `current=true`, `blockers=[]`, `MON-00.eligible=true`;
mapping směřuje na tento zdrojový repozitář. Vývojový základ je
`a0adc43`, větev `feature/mon-00-reporting-contract`.

Při aktivaci automatizace byl stejný rozsah znovu předán pod packet ID
`25c9bfb48d859db3c80eeb88f68d37a17caef1be67e606fd64e18710cc61eabd`.
Projektový HEAD, exportní revize, queue revision i bajty podkladů zůstaly
shodné; nová generace výslovně připnula zdrojový základ `a0adc43` místo
baseline předchozí vývojové větve. Starý balíček se nepřepisoval.

Rozsah a akceptaci určuje exportovaný BACKLOG source artefakt
`3928de31-234c-5754-a6a6-b31f587d2a45`, SHA-256
`cce3acad67fe4ffaf5eca1eddc2ddea8e9adba8f84fff13afafb0933e75dc6d2`,
řádek 345. Jeho bajty byly ověřeny proti manifestu. Historická sekce 23
master roadmapy slouží jako kontext původního požadavku, nikoli jako další
aktuální plán. Toto ADR ani [kontrakt v1](../reporting-contract-v1.md)
nemění stav autoritativního úkolu.

## Rozhodnutí k review

1. Uzavřít doménové formáty v1 pro ReportingTask, Event, Source, Story,
   EvidenceAssessment, EvaluationScale, ReportRun a ReportSnapshot podle
   [kontraktu](../reporting-contract-v1.md). Neznámé verze a pole nesmějí být
   implicitně převedeny ani použity k novému vydání reportu.
2. Projektový Git drží schválené revize definic, událostí, zdrojových
   deskriptorů, hodnocení, story a vydaných reportů. Každá oprava přidává
   nový artefakt s vazbou na předchůdce; staré bajty zůstávají zachované.
3. Projektový SQLite index je obnovitelná projekce konkrétního commitu.
   Journal Workspace a node-local ReportRun journal jsou samostatné
   autority rozpracovaných operací. Scheduler lease, credentials, raw
   provider responses a staging soubory nejsou projektová data.
4. `event_date`, `detected_at` a import se neodvozují jeden z druhého.
   Neznámé datum se přizná. Pozdní zjištění a pozdní import se zobrazí
   odděleně od skutečné časové osy událostí.
5. Zdroj není tvrzení ani jeho potvrzení. Primární/komunitní původ,
   pozorované stadium, hodnoticí škála a lidské/policy rozhodnutí jsou
   samostatné položky. Žádná agregace nesmí marketing přejmenovat na
   nezávisle ověřený provoz.
6. Vydání znamená jeden Workspace commit s neměnným manifestem a přesnými
   bajty Markdownu. Externí doručení je další, samostatně oprávněný účinek.
   Oprava vydání má nové ID, důvod a přesnou vazbu `corrects`.
7. Privacy odvozeniny zahrnuje všechny skutečně použité vstupy včetně
   vyřazeného citlivého podkladu, pokud ovlivnil text nebo hodnocení.
   Uvolnění vyžaduje samostatnou explicitní reklasifikaci.

## Reuse/adapt a hranice implementace

| Existující komponenta | Rozhodnutí a ověřená hranice |
| --- | --- |
| `Workspace`, `Journal`, `Index`; ADR 0003 a 0022 | Reuse společného writer locku, expected HEAD, Git CAS, obnovy a receipts. Nevznikne druhý projektový writer. |
| `metadata.validate_snapshot/validate_transition`; ADR 0023 a 0024 | Adapt obálky artefaktu a neměnnosti source. Současný validátor nezná reportingový obsah ani jeho append-only přechody; to musí doplnit MON-01. |
| `ContextBuilder`; ADR 0008 | Reuse explicitních vstupů, RBAC, privacy a execution boundary před externím voláním. Reporting je navržen i bez LLM. |
| `research_workflow`; ADR 0048 | Adapt připnutých source/run referencí a rozlišení deterministického zjištění od úsudku. Existující výzkumná evidence není sama verzovaným hodnocením zralosti ani dlouhodobým event registrem. |
| Materializace; ADR 0018 | Reuse obnovitelné cache s digesty. Cache neurčuje, co bylo vydáno, a nenahrazuje uchování licenčně povolených vstupů. |
| `PublicationCms` a externí deployment | Oddělená doménová autorita. Reportingové vydání se nesmí vydávat za externí publikaci ani získat implicitní deployment oprávnění. |

Veřejný katalog reuse a dostupná soukromá inventura byly zkontrolovány.
Pro MON-00 není potřeba přebírat externí kód ani znovu provádět inventuru.
Providerové a observační adaptéry jsou mimo tento návrhový řez.

## Persistence, crash boundaries a recovery

Platí [ADR 0003](0003-coordinated-operation.md); následující tabulka
specifikuje přechod mezi run journalem a projektovým vydáním. Nezavádí
distribuovanou transakci přes filesystem, oba SQLite soubory a Git.

| Hranice | Autorita a obnova |
| --- | --- |
| Před uložením run intentu | Neexistuje běh ani rezervace vydání. Bez trvalého intentu se nespouští externí účinek. |
| Run intent potvrzen; sběr/draft/cache | Run journal drží request digest a dílčí stavy. Temporary soubor není potvrzený source. Pád ponechá draft/failed/unknown; nevydává report ani neposouvá úspěšný cutoff. |
| Schválené vydání, před Workspace voláním | Run journal uloží neměnné candidate digesty, `publish_operation_id` a expected HEAD. Resume používá stejné operation ID a bajty, nikoli nové stažení nebo generování. |
| Workspace prepared/files-applied/commit-ready | Obnova dle ADR 0003. Rozpracovaná kombinace Markdownu a manifestu není vydání. Cizí změna vyžaduje review, ne tichý rebase. |
| Git CAS proběhl, run journal ještě nemá receipt | Vydání už existuje v Gitu. Dohledat původní Workspace receipt/operation, dokončit index a propojit tentýž snapshot; nevytvářet druhé vydání. Nedostupný receipt znamená neurčitý stav a diagnostiku. |
| Receipt a aktualizace úspěšného cutoffu | Run journal uloží receipt, snapshot odkaz a příslušné pointery atomicky. Chybějící/stale projektový index se obnoví z validovaného HEAD; run journal se z indexu neregeneruje. |
| Externí doručení a ztracená odpověď | Trvalý delivery intent a idempotency key před účinkem. `unknown` vyžaduje dohledání vzdáleného výsledku; žádný slepý nový publish. Interní vydání zůstává dohledatelné, úspěch celého běhu se netvrdí. |

Ztráta run journalu není běžný index rebuild. Existující Git vydání se může
read-only rekonstruovat, ale bez reconciliation se nespustí další pokus
téhož běhu ani neurčitá externí operace. Retence a migrace jsou normativně
popsány v kontraktu; cílené crash testy náležejí implementačním dávkám.

## Ověření a stav

MON-00 uzavírá návrhové rozhodnutí k lidskému review. Akceptační matice
v kontraktu propojuje každý požadavek se scénářem a očekávaným výsledkem.
Kontrola konzistence s existujícími autoritami, odkazy a diffem nenahrazuje
runtime test. Toto ADR neprohlašuje implementované schéma, scheduler,
collector, migrátor, retenci ani fyzickou akceptaci reportingu.

Pro tento dokumentační řez byly ověřeny místní odkazy, text/whitespace,
pokrytí akceptace maticí a soulad layoutu s aktuálním `validate_snapshot`.
Jednorázový probe potvrdil, že běžný sidecar umí uchovat `record.json`, ale
nevaliduje reportingovou sémantiku; doménová validace proto zůstává výslovným
požadavkem MON-01. Výpočet hranic Europe/Prague 23.–30. 3. 2026 ověřil
167hodinový UTC interval sedmi místních dnů. Nebyla měněna implementace ani
spouštěna nová celá unittest sada; kontroly návrhu ji nepředstírají.
