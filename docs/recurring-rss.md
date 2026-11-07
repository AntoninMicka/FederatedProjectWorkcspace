<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# MON-08-03 — Průběžný RSS sběr

Backend umí opakované RSS/Atom kontroly nezávislé na tvorbě zpráv.
Nálezy a jejich opravy jsou neměnné projektové revize; časování, HTTP
validátory a rozpracované polly používají původní node-local run journal.
Rozhodnutí a crash recovery: [ADR 0076](adr/0076-recurring-rss-findings.md).

## Zapnutí a API

Nová definice sledování sama nezapíná síť. Zapnutí vyžaduje explicitní
potvrzení konkrétní aktuální revize a RSS inputu z
[modelového API](independent-monitoring.md). Lokální služba
`RSSMonitoring.configure(request, confirm=True)` nebo
`POST /v1/monitoring/rss-configure` přijímá:

```json
{
  "project_id": "PROJECT_UUID",
  "watch_id": "WATCH_ENTITY_UUID",
  "input_id": "INPUT_UUID",
  "definition_ref": {"project_id": "PROJECT_UUID", "artifact_id": "REVISION_UUID", "commit_id": "FULL_COMMIT", "path": "artifacts/REVISION_UUID/record.json", "sha256": "SHA256"},
  "enabled": true,
  "mode": "capture-only",
  "confirm": true
}
```

Lokální metoda má confirm jako samostatný argument; HTTP jej nese v těle.
Jde o interní vývojové API, nikoli hotový nový uživatelský formulář.
Zástupné hodnoty musí odpovídat skutečně uloženému modelu. Zdroj musí být
RSS input s posouzeným access/retention, veřejnou podporovanou HTTPS URL,
local placement a ne-local-only privacy. Interval se bere z `input.poll.seconds`
(např. 900); hlavní `schedule.kind=daily` tím není změněný ani vykonaný.

- `capture-only`: zachytit nález bez tvrzení, že proběhl sémantický filtr.
- `queue-all`: výslovně vybrat všechny nové/opravované položky do fronty.
  To není automatické rozhodnutí o relevanci či pokroku.
- `enabled=false`: pozastavit existující binding, i když se definice změnila.

Původní backendový worker provádí tick každých 10 sekund. Splatný RSS input
zkontroluje jednou a next_due nastaví od dokončení; při vypnutém backendu
se nesbírá. Staré nezachycené RSS položky se po restartu nevymýšlejí.
Změna definice, URL či pravidel potřebuje nové potvrzení; nezačne se sama
používat jen proto, že Git obsahuje novou revizi. Nevyřešený poll může
nejdřív vyžadovat reconciliation. Opakované stejné configure neposune
rozvrh ani nevymaže validátory.

`POST /v1/monitoring/rss-status` s `{project_id}` vrací bindingy, polly a
aktuální SourceFinding revize. V **Sledování a zprávy → Průběžný sběr RSS**
je URL, interval, pause, poslední úspěch, příští kontrola a chyba/unknown.
Metadata `runtime_state` definice rozlišují `collection-configured`,
`collection-paused` a `not-connected`; konfigurace sběru neznamená zapojené
LLM zpracování nebo hotový reportovací runtime.

`POST /v1/monitoring/rss-tick` s `{project_id}` provede pouze splatné práce;
neobchází interval ani pozastavení. `rss-reconcile` přijímá project_id,
poll_id a confirm=true. Výsledek unknown se automaticky neopakuje. U stale
publikace reconciliation zachová cizí práci, ověří existenci původní
Workspace operace/receipt a teprve pak smí intent uzavřít či opustit.

Web vyžaduje projektová práva; čtenář smí status, změny/configure/tick
vyžadují administrátora a writable projekt. HTTP status nevrací ETag
validátory ani raw staging XML. Žádné credentials se nesynchronizují.

## Nálezy, opravy a fronta

Identity sledují GUID a URL v rámci konkrétního watch/input/zdroje. Obsahový
hash odhalí opakování a nativní položkový hash také změnu metadat. Jiná
identita se nesloučí jen kvůli stejnému textu. Dvojznačná vazba GUID/URL
nebo konfliktní duplicita v jednom feedu selže. Oprava přidá revizi a zachová
starý obsah, aliases a první discovered_at/imported_at. Raw XML a nálezy
se uloží atomicky přes původní writer. Nezměněný feed nevytvoří další commit.

Stavy jsou captured, selected, pending, processed, discarded s důvodem,
processing failed a unknown. SourceFinding.selection obsahuje explicitní
rozhodnutí, důvod a verzi/hash jednoduché capture/include-all policy;
definition_ref připíná i původní pravidla. Obecné keyword/regex postupy
patří MON-08-04. Volný text pravidel se netváří jako vykonaný filtr.
Změna režimu sama nezpracuje znovu staré nálezy; ty lze výslovně posunout
stavovou operací nebo pozdější re-evaluací.

`finding-transition` přijímá project_id, finding_ref, stage, reason,
operation_id a confirm=true. Povolí jen skutečný přechod stavu; zapisuje
neměnného následníka. Replay stejného operation ID vrátí původní receipt,
jiný požadavek selže. Opakované doručení processed položky ji nezařadí znovu.
Nová oprava zdrojového obsahu je nová revize a může vyžadovat nové zpracování.
Tyto stavy nejsou akceptací plánovacího úkolu Workspace.

## HTTP, chyby a persistence

If-None-Match / If-Modified-Since se ukládají až po dokončeném importu nebo
ověřeném HTTP 304. 304 je `not_modified`, nikoli prázdný feed. Neposouvá
projektový Git a nesmaže frontu. Chyba, poškozené XML, redirect, zakázané
robots nebo překročení limitů nejsou úspěšná nulová kontrola. 429/503
respektují sdílený origin backoff původního SourceCollectoru včetně dalších
kanálů; není okamžitý retry. Původní DNS/IP/TLS, XML a gzip kontroly zůstávají.

Rozpracované XML a frozen publish plán jsou v existujícím run journalu
se SQLite FULL synchronizací. Po úplném výsledku zůstávají jejich hashe,
výsledek/chyba a receipt; canonical artefakty drží Git. Missing/corrupt
journal není rebuildovatelný index a nesmí se nahradit prázdným stavem.
SourceFinding, raw XML a jejich provenience neznamenají potvrzený Event,
hodnocení pokroku, spuštění LLM ani vydání zprávy.

Existující ruční **Zdroje** RSS reader se tímto automaticky nezapíná jako
projektové sledování. Plné zakládání/editace sledování ve formulářích,
zpracování fronty, syntéza a federované umístění mají navazující scope.

## Ověření

Testy běží v izolovaných dočasných projektech, nikoli nad živými uživatelskými
odběry. Runtime scénáře používají řízené fetch odpovědi a posun clocku;
nejde o tvrzení odsledovaných skutečných 15minutových period u ČT24.

- `tests.test_rss_monitoring`: 17 testů pro conditional 304, stavy a přechody,
  restart, opravy a aliases, důvody výběru/vyřazení, odmítnutí živého druhého
  workeru, sdílený origin backoff, zachování cizí změny a reconciliation.
  Capture-only/queue-all nevytvářejí ReportSnapshot a test blokuje případné
  volání LLM dispatch.
- Process-crash scénář končí subprocess na sedmi hranicích rss-fetched,
  rss-plan, Workspace prepared, before-ref, ref-updated, rss-published,
  rss-completed. Restart nepoužije další GET a zachová čistý projektový strom.
  Samostatné přerušení dispatch vede do unknown bez dalšího GET. Nejde
  o simulaci fyzického výpadku disku nebo libovolného syscallu.
- Širší cílený běh reportingu, scheduleru, původního monitoringu, definic
  a tehdejších RSS testů: 82 testů OK. Zdrojové regrese collectoru, původního
  transportu, konektorů a RSS readeru: 54 testů OK. Běhy se překrývají,
  takže jejich počty nejsou součtem unikátních testů.
- `tests.test_monitoring_http` a `tests.test_monitoring_browser`: 3 testy
  se skutečným izolovaným HTTPS a Qt/WebEngine, včetně admin/reader oprávnění,
  potvrzeného zapnutí, nálezů/statusu bez validátorů v odpovědi, viditelného
  15minutového RSS rozvrhu a původního review/publish toku zpráv.

Plná závěrečná sada dávky MON-08 ani ruční akceptace běžného profilu zatím
neproběhly. Ověření source/DB/procesu není akceptací celé feature nebo
MON-05 a tato dokumentace nemění autoritativní plán Workspace.
