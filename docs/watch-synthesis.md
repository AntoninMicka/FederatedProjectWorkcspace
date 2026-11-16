<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08-05 — řetězení uložených výstupů

Navazující [MON-08-06](synthesis-analysis.md) přidává analytickou evidenci
měsíčních/ročních běhů a explicitní modelové pokračování. Níže uvedené
omezení na deterministické výňatky popisuje původní krok MON-08-05.

`WatchSynthesis` připraví report z jednoho nebo více upstream sledování,
případně z kombinace uložených nálezů a explicitních externích zachycení.
Rozhodnutí a crash hranice: [ADR 0078](adr/0078-frozen-watch-synthesis-inputs.md).

Příklad jednoho watch vstupu v existující WatchDefinition:

```json
{
  "id": "UUID vstupu",
  "kind": "watch",
  "watch_id": "UUID týdenního sledování",
  "take": "reports",
  "include_drafts": false,
  "policy": {
    "window": "ending-in-period",
    "approval": "issued",
    "missing": "wait"
  }
}
```

`ending-in-period` vybírá upstream kalendářní vydání s koncem v následném
období (start exkluzivní, end inkluzivní). `overlap` očekává všechny překrývající
se sloty včetně přesahujících. Respektují se upstream timezone/DST i start
definice. Neuzavřený očekávaný přesahující slot je chybějící vstup.
Každá vazba má vlastní policy. Druhy take jsou reports, findings a
processed-items; poslední vyžaduje processed. findings může vyžadovat captured,
selected či processed. Vstupy z téhož projektu zůstávají pod původním DAG a
privacy validátorem; přímý i nepřímý cyklus selže už při zápisu definice.

Nálezy se zařazují podle prvního discovered_at; date unknown není automaticky
časem skutečné události. Dostupnost se hodnotí k jednomu uloženému cutoffu.
Nulový nález bez upstream uzávěrky nelze vydávat za prokázaně kompletní sběr.
Do policy `missing="allow-incomplete"` patří výslovné rozhodnutí uživatele;
výsledek vypíše každou chybějící periodu a má complete=false.

## Příprava, review a vydání

Definice používá report.mode=deterministic, placement.mode=local a výstup
Markdown. Autentizovaný admin/writer může POST `/v1/monitoring/synthesis-run`:
`{project_id,definition_ref,period,external_refs?}`. Period má stávající úplný
kalendářní kontrakt ReportingScheduler a musí být uzavřený.

Výsledek je waiting-inputs s konkrétními mezerami, nebo původní scheduler run
ve stavu review. Před samotným sestavením je uložen neměnný manifest přesných
vstupů. Další pokus ani opožděná zpráva jeho piny nezmění. Stejný intent po
restartu vrátí stejný run/vydání; změněný intent téhož období selže s požadavkem
na explicitní opravu. Volná instrukce ani oprava upstream reportu nepřepíše
staré vydání.

Ve společném přehledu Sledování / Výstupy lze otevřít kandidáta, posoudit
zdroje a mezery a vydat jej původním potvrzeným `/v1/monitoring/publish`.
Změněná nebo pozastavená definice nedostane novou publikaci. již committed
publikace po přerušení používá původní receipt. Schválení výstupu není potvrzení
věcné správnosti zdrojového tvrzení.

Přímé Python API: `WatchSynthesis(node).prepare/execute(project_id,
definition_ref, period, external_refs=...)`; `scheduler.preview(run_id)` vrací
přesný kandidát a approval_digest; `publish(run_id,digest,confirm=True)` vydává
jen tento schválený kandidát. `retry(run_id,confirm=True)` používá původní
zmrazený manifest. Unknown se nejprve řeší původní scheduler reconciliation.

## Doplňkové externí vstupy

Syntéza sama nevyvolává web search ani RSS fetch. `external_refs` je seznam
`{input_id,ref: PinnedRef}` pro explicitně definované static-text/web-search
vstupy. Capture nebo hledání zajišťuje původní samostatně schvalovaný tok;
převezme se zachycený source artefakt nebo Reporting Source ve stavu captured.
Pouhá reference bez uložených bajtů nestačí. Jeden supplemental pin je přiřazen
k jednomu input ID; více zachycení znamená více explicitních vstupů.
Přímé RSS vstupy používají již evidované nálezy téhož sledování.

Takto může týdenní přehled spojit denní findings, další upstream sledování a
schválený uložený výsledek hledání. Měsíční přehled nad vydanými týdny žádný
nový externí vstup nepotřebuje. Platformní konektor zůstává nedostupný;
include_drafts se explicitně odmítá, protože synchronizovatelné draft vydání
zatím nemá implementovaný publikační kontrakt. Node-local scheduler review
není publikovaný zdroj a nepřebírá se skrytě.

## Dohledání a opravy

Reader projektu může POST `/v1/monitoring/synthesis-trace` s
`{project_id,report_ref}`. Vrací bounded graf přesných pinů: roční report →
měsíční report → týdenní report → SourceFinding či zachycený zdroj.
Obsah se nepřefetchuje; chybějící bajty, jiný projekt nebo privacy zákaz selžou.
`/v1/monitoring/synthesis-freshness` se stejným vstupem vrací potentially_stale
a piny novějších oprav/následníků. Kontrola sleduje i transitivní podklady.
UI u vydání zobrazí upozornění; původní obsah, cutoff a seznam vstupů zachová.

Výňatky v deterministickém přehledu jsou omezené na 2000 znaků/položku;
plné přesné bajty zůstávají dostupné přes piny. Analytický měsíční/roční
výklad a odstranění dvojího započítání událostí má MON-08-06. Spouštění tohoto
nového toku je nyní přes aplikační API; úplný editor vazeb má MON-08-09.

Ověření: `tests.test_monitoring_synthesis` (uložené týdny, mezery, kombinované
vstupy, freeze/real-process crash, opravy, transitive trace, paused publish),
relevantní Reporting/Definitions/Scheduler/Monitoring regrese a společné
HTTPS/RBAC/Qt testy. Fixtures jsou syntetické a nenahrazují živou akceptaci
referenčního řetězce ani závěrečnou plnou sadu celé MON-08.
