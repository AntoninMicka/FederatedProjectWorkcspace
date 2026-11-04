<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# MON-02 — Bezpečný Source Collector

Lokální CLI `spikes.source_collector` připojuje již existující public-source
reader k [ručnímu reportingu](manual-reporting.md). První typ je statický
UTF-8 text (`text/plain`) na přesné veřejné HTTPS URL. Sběr nevytváří Event,
nevyvozuje tvrzení ani nespouští obsah zdroje. Redirect, přihlášení, HTML/PDF,
dotazy v URL, IP literal, nestandardní port a jiné typy se odmítnou.
Rozhodnutí a recovery: [ADR 0069](adr/0069-reporting-source-collector.md).

## Připnutá policy

ReportingTask.source_policy musí ukazovat na místní uživatelsky vytvořený
document s čistým JSON obsahem (bez Markdown fences). Příklad struktury:

```json
{
  "schema": "fpw-reporting-collector-policy-v1",
  "type": "static-utf8-text-v1",
  "access_reviewed": true,
  "binding": {
    "schema_version": 1,
    "binding_id": "UUID",
    "revision": "v1",
    "adapter": "static-html-v1",
    "origins": ["https://example.org"],
    "user_agent": "WorkspaceCollector/0.1",
    "auth": "none",
    "max_wire_bytes": 65536,
    "max_decoded_bytes": 65536,
    "max_text_chars": 20000,
    "max_compression_ratio": 10,
    "timeout_seconds": 10
  },
  "urls": ["https://example.org/document.txt"],
  "source_role": "primary",
  "license": {
    "identifier": "Dolozena-licence",
    "terms_ref": {"project_id": "UUID", "artifact_id": "UUID", "commit_id": "FULL_COMMIT", "path": "artifacts/UUID/content.md", "sha256": "SHA256"},
    "capture_allowed": true,
    "retention_policy": {"project_id": "UUID", "artifact_id": "UUID", "commit_id": "FULL_COMMIT", "path": "artifacts/UUID/content.md", "sha256": "SHA256"}
  }
}
```

Zástupné hodnoty nahraďte skutečnými PinnedRef z reporting CLI `pin`.
Nejdříve připravte podklad licence/podmínek a retence, pak policy document,
potom novou revizi ReportingTask s její referencí. Stejný místní podklad může
obsahovat podmínky i retenci, musí však být konkrétně posouzený.

Access_reviewed a capture_allowed jsou výslovná rozhodnutí operátora;
aplikace neurčuje práva z dostupnosti URL/robots. Chybějící licence, terms_ref,
retence či souhlas se odmítne. Source_role není potvrzení tvrzení. Externí/LLM
dokument nemůže sám fungovat jako policy. Text zdroje nevybírá URL ani limity.

Task, policy a licenční/retention podklady se před síťovým účinkem a importem
znovu porovnají s aktuálním projektem. Změna/smazání, nahrazená task revize nebo
local-only privacy zneplatní původní plán; žádné tiché přepnutí na novou verzi.
Cross-project reference se zatím odmítnou.

## Preview → fetch → preview importu → import

```sh
python3 -m spikes.reporting --node NODE pin PROJECT_UUID TASK_REVISION_UUID > task-ref.json
python3 -m spikes.source_collector --node NODE preview PROJECT_UUID task-ref.json \
  https://example.org/document.txt "Ručně zvolený titulek" --run-id RUN_UUID > fetch-preview.json

# Prohlédněte value: konkrétní URL, dva GET účinky, policy a limity.
# SHA256 je hodnota sha256 z obálky; nejde o sha256sum celého JSON souboru.
python3 -m spikes.source_collector --node NODE fetch fetch-preview.json --sha256 SHA256 --confirm
python3 -m spikes.source_collector --node NODE status RUN_UUID

python3 -m spikes.source_collector --node NODE preview-import RUN_UUID \
  --operation-id OPERATION_UUID > import-preview.json
# Prohlédněte Source, raw metadata, souborové digesty a stažené bajty.
python3 -m spikes.source_collector --node NODE publish import-preview.json --sha256 SHA256 --confirm
```

CLI vrací `{value, sha256}` a umí uloženou obálku opět načíst. Preview sám
připne aktuální repository HEAD. Titulek je ručně zvolený; downloaded Date
není datum publikace. Datum/autorství bez důkazu zůstanou unknown/null.
Fetch nic nezapisuje do projektového Gitu.
TASK_REVISION_UUID je ID reportingového artefaktu, nikoli plánovací ID MON-02.

Raw bajty a inertní projekce leží v soukromém stagingu vedle node.json:
`.<node-filename>.source-collector/public-source-staging/<run-id>/` obsahuje
raw.bin, projection.txt a projection.json. Při review je lze číst jako data,
nikoli spouštět. Gzip zachová přesnou komprimovanou odpověď; dekódovaná
projekce je samostatná. Jde o lokální administrativní CLI bez HTTP endpointu
a grafických formulářů.

## Výsledky, chyby a obnova

- Schválený import atomicky uloží nový raw source s import provenance a
  reportingový Source deskriptor přes původní Workspace writer. BatchRef
  připíná raw sourozence; staré bajty se nepřepíšou.
- Další zachycení stejné URL/task revize naváže Source následníka a zachová
  původní imported_at. Nové raw ID a fetched_at dokládají další capture i při
  shodných bajtech. Jiná URL se neslučuje podle hashe.
- Chybové HTTP stavy, stažení/nedostupnost zdroje, přihlášení, neúplný obsah
  nebo neověřené TLS nemohou do importu. Původní Source je záznamem svého
  úspěšného zachycení, nikoli dnešní dostupnosti. Nový neúspěch drží lokální
  journal. Event se nevytvoří ani po úspěchu.
- 429/503 uloží backoff stejného originu podle Retry-After (nejméně 60 sekund,
  malformed delay 24 hodin). Nový i připravený run ho respektuje. Žádný
  automatický retry/scheduler.
- Přerušený dispatch se při recovery označí unknown a stejný run se nevysílá
  znovu. Ztracený/změněný staging zneplatní succeeded fetch. Unknown vyžaduje
  ruční diagnostiku/reconciliation, nikoli náhradní run ID naslepo.
- Po připraveném Workspace importu recovery používá journalové bajty, bez
  stagingu a sítě. Stejné operation ID a stejný schválený preview vrátí původní
  receipt; jiný payload je konflikt. Cizí změna HEAD se nepřepíše.
- Chybějící/prázdná fetch DB v existující složce se nezaloží znovu: sběr a
  nové importy se zastaví pro ruční reconciliation. Již připravený Workspace
  import a jeho receipt fungují i bez fetch DB. Nejde o obnovu celé ztracené
  node-state složky nebo disku; po takové ztrátě se staré plány nesmějí použít
  jako údajný nový běh.
- Před připravením importu může nesouvisející změna vyžadovat nový
  preview-import nad aktuálním HEAD. Stávající fetch se použije jen při stále
  platném tasku/policy. Po nejasném výsledku nejprve zopakujte původní
  publikaci; nevyrábějte nové operation ID.

## Síťová hranice a ověření

Reuse readeru validuje veřejné DNS adresy, připíná connect IP a zachovává
hostname/SNI i systémové TLS ověření. Collector vyžaduje úspěšný 200
text/plain robots preflight. 401/403/404, redirect, nepodporovaný charset,
non-ASCII/percent robots pravidla a NUL se odmítnou; cesty URL jsou prosté
ASCII bez percent escapes, dot-segments nebo dvojitých lomítek. Robots
allow/disallow přijímá jen doslovné prefixy; wildcard/anchor pravidla odmítne.
Gzip musí být jeden úplný stream bez dalších members nebo koncových bajtů.
Je to konzervativnější rozsah než obecné
[RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), nikoli nový úplný parser.
Wire/decoded/text/compression limity a socket timeouty používají stávající
transport. Systémový DNS resolver zde nemá procesovou izolaci; nejde o
tvrzení production-ready crawleru.

Prompt injection uzavírá oddělení dat od oprávnění, nikoli heuristika, která
údajně pozná všechny škodlivé věty. Obsah je untrusted external source;
nespouští nástroje, LLM, policy ani následné URL a automaticky se nepublikuje
jako událost či report. Scheduler/extrakce jsou samostatné dávky.

Testy `tests.test_source_collector`, `tests.test_public_source` a
`tests.test_reporting` pokrývají chyby/bezpečnost, skutečné CLI, prepared a
dispatching fetch i process-crash před/po Git CAS. Nesimulují fyzický výpadek
proudu ani přerušení libovolného syscallu. Konkrétní výsledky jsou v předání.

Ověření 4. 11. 2026:

| Vrstva | Důkaz |
| --- | --- |
| Finální cílená sada | `python3 -m unittest tests.test_source_collector -v`: 16 testů OK, 33,741 s; skutečné CLI, 9 process-crash hranic importu a dispatch interruption, ztráta fetch DB bez nového GET i obnova již připraveného importu. |
| Celá regresní sada | `python3 -m unittest discover -s tests -v`: 1525 testů za 519,651 s, OK, 44 skipped. Běh s povolenými lokálními sockety zahrnul finální collector, původní reader/reporting i ostatní moduly. Volitelné Qt/WebEngine scénáře nejsou ruční UI akceptace. |
| Veřejný transport | Samostatný finální TextAdapter probe `https://www.rfc-editor.org/rfc/rfc9309.txt`: succeeded, 20:47:23 UTC; robots + skutečné HTTPS/TLS, wire 7657 B, text 21031 znaků, SHA-256 `d2f1ee32cd010f364fb2a215eb9b8fc85ed6b19a2b4110175c375755841108a1`. Jen izolovaný staging, bez projektového importu a bez tvrzení schválené licence pro produkční archivaci. |
| Diff a dokumentace | Kontrola syntaxe Pythonu, nových souborů, místních odkazů a `git diff --check` OK. |

Zadání při zahájení: projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, MON-02,
queue revision 200, project HEAD `e13888860de54992f7cbd13368af20af5415d6ee`,
export `060d8d1b68f08c42d53025b742801701b12732f834f7a04879330b2ac1038c0f`,
packet `e92139c816dc1ea5549d6a414fe547a95cf0abd9929d5a67b3a66c20bc58960c`;
current=true, stale=false, MON-01 user_confirmed=true. Zdrojový základ
`7d49cdf`. Návod je evidence k review, nikoli další plán nebo lidská akceptace.
