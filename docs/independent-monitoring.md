<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# MON-08-01 — Samostatná propojená sledování

Backendový model odděluje definici denního sběru, týdenního přehledu a
měsíční syntézy. Každé sledování má vlastní identitu a neměnné revize,
jeden hlavní rozvrh, vstupy, pravidla a zadání výstupu. Interval kontroly
externího zdroje se ukládá u daného vstupu; nemění rozvrh zprávy.
Rozhodnutí, kompatibilita a recovery: [ADR 0074](adr/0074-independent-monitoring-definitions.md).
Volitelná verzovaná `selection.pipeline` a její náhled:
[filtry a vyhodnocování](monitoring-filters.md).
Spustitelná deterministická syntéza ze zmrazených upstream vydání a nálezů:
[řetězení sledování](watch-synthesis.md).

## Datový kontrakt

`WatchDefinition` používá původní reportingový envelope. `entity_id` je
stabilní watch ID, `revision_id` identita konkrétní revize a `previous`
obsahuje přesné PinnedRef předchůdců. Privacy nese envelope; nejde o nový
neověřený klíč ve volném Markdownu. `version` v modelovém přehledu je
SHA-256 kanonické definice, nikoli ručně zadané číslo verze.

Příklad value denního sběru (zástupné ID vstupu nahraďte platným UUID):

```json
{
  "schema": "fpw-reporting-watch-v1",
  "title": "ČT24 — denní sběr",
  "goal": "Evidovat vybrané zprávy bez automatického LLM zpracování.",
  "scope": {"entities": [], "categories": [], "geographies": [], "tags": ["ct24"]},
  "active": true,
  "schedule": {"kind": "daily", "timezone": "Europe/Prague", "start": "2026-11-06"},
  "inputs": [{
    "id": "UUID",
    "kind": "external",
    "connector": "rss-atom",
    "locator": "https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313",
    "poll": {"seconds": 900},
    "access": {
      "reviewed": true,
      "capture_allowed": true,
      "terms": "Konkrétní operátorem posouzené podmínky přístupu a použití.",
      "retention": "Konkrétní operátorem posouzená pravidla uchování."
    }
  }],
  "selection": {"revision": "1", "instructions": "Vybrat položky odpovídající tématu sledování."},
  "evaluation": {"revision": "1", "instructions": "Původ položky není potvrzením jejího tvrzení."},
  "report": {
    "mode": "collect-only",
    "instructions": "Uložit nálezy pro navazující sledování.",
    "formats": ["findings"],
    "language": "cs",
    "required_sections": []
  },
  "placement": {"mode": "local", "node_id": null, "capabilities": []}
}
```

Externí vstup má vlastní stabilní identitu, typ konektoru, přesnou veřejnou
HTTPS adresu bez query/credentials, interval 60..604800 sekund a explicitní
podmínky přístupu/uchování. Texty podmínek v příkladu nejsou posouzením
licence ČT; jsou pouze strukturální příklad. Konektor není tímto modelem
implementovaný nebo schválený k síťovému účinku.

Vstup navazujícího sledování má místo externího vstupu tento tvar:

```json
{
  "id": "UUID-vstupu",
  "kind": "watch",
  "watch_id": "UUID-zdrojoveho-sledovani",
  "take": "reports",
  "include_drafts": false
}
```

`take` rozlišuje `findings`, `processed-items` a `reports`. Modelové API
doplní chybějící `take=reports` a `include_drafts=false`; kanonický uložený
záznam už obě hodnoty obsahuje. Jen výslovné `true` u reportů připouští
návrhy. Pro týdenní/měsíční syntézu se volí vlastní `schedule.kind`,
`report.mode=deterministic` nebo `llm`, formát `markdown` a neprázdné
sekce; `presentation` může být požadovaný odvozený formát. Jedno sledování
neobsahuje více hlavních period. Placement je místní, konkrétní uzel nebo
požadované capabilities; vzdálené spouštění tento řez neprovádí.

## Modelové API a připnutí běhu

- `POST /v1/monitoring/definitions`, tělo `{project_id}`: aktuální definice,
  jejich přesné reference a hash; bez síťového či LLM účinku.
- `POST /v1/monitoring/definition-save`: `project_id`, `base_head`,
  `watch_id`, `previous`, `privacy`, `definition` a `operation_id`.
  První revize má prázdné `previous`; oprava uvádí přesný pin předchůdce.
  Nový operation ID znamená novou operaci, nikoli retry neznámého výsledku.
- Lokální `MonitoringDefinitions.save` přijímá stejné tělo bez operation ID,
  které je druhým argumentem. Vrací původní Workspace receipt a definition pin.

Web vyžaduje oprávnění k projektu. Čtenář smí načíst modelový přehled,
ukládání vyžaduje administrátora a zapisovatelný projekt. Stejnou validaci
grafu používá obecný reportingový writer i raw editor. Cyklus, self-link,
chybějící vstup, snížení privacy nebo neúplná definice se odmítne před
journal prepare. Původní revize se neupravují a nemažou.

Interní `MonitoringDefinitions.prepare_run(project_id, definition_ref,
period, run_id)` připraví pouze reportingový intent původního scheduleru.
Rules dokument obsahuje přesný pin vlastní definice a přímých upstream
definic včetně volby jejich výstupů. Připne tím i selection/evaluation/report
zadání. Novější definice ani změna pravidel starý run nepřepíšou. Replay
původního run ID ponechá původní intent; jiné zadání se stejným ID selže.
Přerušená materializace znovu použije původní rules/scale/task receipts.

## Co je a není zapojené

Modelový přehled bez připojeného runtime vrací `runtime_state=not-connected`.
Po [MON-08-03](recurring-rss.md) rozlišuje také `collection-configured` a
`collection-paused` pro výslovně nastavený RSS binding téže revize. Tyto
stavy nejsou potvrzením vykonaného reportu nebo LLM zpracování. `active` je požadovaná
konfigurace, nikoli důkaz vykonávaného workeru nebo souhlas s externím
požadavkem. Collect-only a vzdálené běhy se přes přípravu reportingového
intentu odmítnou. Ani připravený lokální report neprovádí síť, LLM, dispatch
nebo automatické vydání.

Současný formulář/worker MON-05 dál čte původní markerový formát. Nevzniká
tichá migrace starých period na nová sledování. Formuláře nového modelu,
skutečný výběr vydaných upstream zpráv a migrace jsou
navazující práce MON-08. Sekce Zdroje zatím zůstává ručním readerem.
Tato dokumentace není potvrzením akceptace celého monitoringu.

## Ověření

- `python3 -m unittest tests.test_monitoring_definitions -v`: 14 testů OK
  nad finálním modelem, včetně denního DST kalendáře, tří propojených
  sledování, nezávislého poll intervalu, neměnného run intentu, privacy,
  neplatných definic, read-only/stale guardů a replay po přerušení.
- Průběžný společný běh `tests.test_monitoring_definitions`,
  `tests.test_reporting`, `tests.test_reporting_scheduler`, `tests.test_monitoring`:
  69 testů OK. Běh zahrnoval tehdejších 12 modelových testů, takže počty
  jednotlivých běhů se nesčítají jako unikátní testy.
- Po posledním vyčlenění sdíleného EvaluationScale prošel navíc cílený
  `tests.test_monitoring.MonitoringTests.test_watch_restart_report_review_publication_presentation_and_two_periods`.
- `python3 -m unittest tests.test_monitoring_http -v`: 2 testy OK se skutečným
  izolovaným HTTPS, včetně původního sledování a nového modelového API/RBAC.
- Process-crash test definice ukončuje subprocess na šesti hranicích
  `prepared`, `files-applied`, `before-ref`, `ref-updated`, `indexed`,
  `completed`; po recovery/replay ověřuje právě jeden commit revize a čistý
  pracovní strom. Není to simulace fyzického výpadku napájení.

Plná závěrečná sada celé dávky MON-08 ani ruční akceptace nového UI tímto
nebyly provedené. Tento řez nemění autoritativní stav úkolů Workspace.
