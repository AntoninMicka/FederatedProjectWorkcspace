<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Kontrakt kompatibility verzí a revizí

Stav: **designed** (AUDIT-B3-T1), **implemented** (AUDIT-B3-T2, T3), 18. 11. 2026;
čeká na review. Zdrojová větev
`feature/audit-b3-version-compat`, výchozí HEAD `0ac911a`. Kanonický Workspace
projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, projektový HEAD `ec78422`.
Kontrakt navazuje na nálezy B-VER-01 až 04 a B-ODD-02
([audit B1](audit-b1-locks-versions-oddities.md#nálezy-b-ver)). Je to
dokument k review, nikoli akceptace ani druhý plán. Implementaci provádí
AUDIT-B3-T2 a regresní fixture AUDIT-B3-T3.

Rozhodnutí o rozsahu selhání u projektových dat zaznamenává
[ADR 0085](adr/0085-unsupported-version-fails-closed.md) a protokolovou verzi
rozšíření a backendu [doplnění ADR 0060](adr/0060-local-file-ide-bridge.md#doplnění-18-11-2026--protokolová-verze-rozšíření-a-backendu-audit-b3).

## Jediné pravidlo

1. **Neznámá verze je vždy explicitní.** Neznámá novější verze nikdy nevede
   k tichému vypnutí, k výkladu jako starší verze ani k ignorování dat.
   Výsledkem je viditelná typovaná chyba nebo již navržený viditelný
   degradovaný stav.
2. **Zapnutí a aktivace se váží na stabilní ID, ne na revizi.** Nová revize
   dokumentu, plánu či definice nesmí samovolně zastavit nic, co uživatel
   povolil.
3. **Vazba na revizi existuje jen z důvodu bezpečnosti nebo souběhu.**
   Takovou vazbu doprovází viditelný stav s důvodem a postupem obnovy.

Podrobná pravidla K1 až K7 tyto tři body zpřesňují.

## K1 — uzavřená množina verzí a pořadí kontrol

Každý čtenář verzovaných dat deklaruje uzavřenou množinu podporovaných verzí.
Kontrola verze předchází kontrole polí. Nečíselná, nižší nebo vyšší verze se
proto ohlásí jako nepodporovaná verze, a ne jako „neznámé pole“ nebo
„neplatná data“.

Neznámá verze vyvolá typovanou chybu `UnsupportedVersion`, která je podtřídou
`ValidationError`. Stávající mapování chyb proto zůstává funkční. Chyba nese:

| Pole | Význam |
|---|---|
| `kind` | Druh dat, například `artifact-metadata`, `registry`, `content-sync`, `project-catalog`, `autonomy-plan`, `ide-pairing`. |
| `subject` | Stabilní identifikátor předmětu: ID artefaktu, ID registru, ID operace, ID peeru nebo cesta k uzlovému souboru. Nikdy credential ani obsah. |
| `found` | Nalezená hodnota verze, nebo `null`, pokud chybí či nejde o celé číslo. |
| `supported` | Nejnižší a nejvyšší podporovaná verze. |
| `update` | Strana, která musí aktualizovat: `this-node`, `peer`, `extension` nebo `backend`. |

Lidská hláška má tvar „Nepodporovaná verze schématu N pro `<kind>` `<subject>`;
podporováno 1–M. Aktualizujte `<strana>`.“ Obecné mapovače chyb (například
generické 422 hlášky ve `web_server.py`) nesmějí `UnsupportedVersion`
nahradit obecnou větou. Nesmějí ztratit pole `code: "unsupported_version"`,
`found`, `supported` ani `update`.

Nižší verze, kterou program zná jako starší, se dál migruje nebo čte podle
svého dosavadního kontraktu. Tento kontrakt nemění žádnou existující migraci.

## K2 — chování se řídí úplným výčtem verzí nebo deklarovanou schopností

Kód nesmí větvit chování podle porovnání s nejnovější verzí (`== 3`, `in {2, 3}`)
a v ostatních případech použít starší logiku. Povolené jsou dva tvary:

- úplný výčet známých verzí, ve kterém neznámá verze vyvolá `UnsupportedVersion`;
- jedna tabulka schopností `verze → množina schopností` (například
  `countdown`, `continuation`, `policy`, `advance`). Chování se pak ptá na
  schopnost, ne na číslo verze.

Uložený záznam s neznámou verzí (například po downgrade uzlu) se stejně
odmítne explicitně a nespadne do logiky verze 1. Tím se uzavírá B-VER-02.

## K3 — rozsah selhání odpovídá jednotce validace

| Jednotka | Kontrakt při neznámé novější verzi |
|---|---|
| Projektový snapshot (artefakty, registry) | Projekt se neotevře pro čtení, zápis, merge ani sync. Chyba uvádí ID prvního nepodporovaného artefaktu či registru. Index se z takového commitu nestaví a starší index se nevydává za aktuální. Podrobnosti: [ADR 0085](adr/0085-unsupported-version-fails-closed.md). |
| Přijatá federační data (výměna obsahu, katalog, bundle) | Příjemce data odmítne před aplikací a jeho stav zůstane beze změny. `update: this-node`, protože odesílatel je novější. Chybová odpověď nese `code` a `supported`, aby odesílatel mohl zobrazit, že peer podporuje nejvýše M. |
| Uzlový stav (registr uzlu, lokální SQLite store, politiky) | Daný store nebo služba se neotevře a chyba uvádí cestu a verzi. Ostatní nezávislé store pokračují. Uzlový stav se mezi uzly nesynchronizuje, takže novější verze vzniká jen po downgrade programu: `update: this-node`. |
| Spustitelný dokument (plán autonomie, workflow) | Dokument se odmítne už při parsování. Uložený běh s neznámou verzí přejde do explicitního stavu chyby, nikdy do starší logiky (K2). |
| Protokol rozšíření a backendu | Platí K6. |

Nový viditelný degradovaný stav (část dat dostupná, část označená) zavádí jen
ADR. Dnešní povolené degradované stavy jsou ty, které audit B1 klasifikoval
jako „viditelný degradovaný stav“ nebo „legitimní viditelná kontrola“:
`freshness: 'stale'` u discovery katalogu a `compatible: false` u CMS modulu.

## K4 — aktivace na stabilním ID

Uživatelské zapnutí, místní aktivace a přiřazení se váží na stabilní ID
(ID bloku, ID připojení či relace, ID úkolu, ID modulu), nikoli na revizi
dokumentu. Toto pravidlo už platí v
[ADR 0082](adr/0082-composable-monitoring-and-message-pools.md) (aktivace
zdroje i zpracování na stabilním ID bloku) a v
[ADR 0062](adr/0062-pinned-queue-handoff.md) po `ed1d536` (reviewovatelnost
podle aktuálního serverového `queue_reviewable`, nikoli podle shody revize).
Kontrakt je zobecňuje na všechny nové funkce.

Ruční pozastavení, odvolání oprávnění a změna identity peeru zůstávají
explicitními akcemi uživatele či správce. Nejsou vedlejším účinkem nové revize.

## K5 — revizní vazby jen z důvodu bezpečnosti a souběhu, vždy viditelně

| Třída | Příklady dnešních vazeb | Požadované chování |
|---|---|---|
| Bezpečnostní re-autorizace | digest aktivace autonomie (`replace_plan` aktivaci zruší), hash CMS modulu, přesný Context Manifest, `preview_sha256`, fingerprint peeru | Viditelný stav s důvodem (například „enable it again after review“) a jedna jasná akce obnovy. Nikdy tichý konec. |
| Řízení souběhu (CAS) | `expected_head`, revize fronty, revize odběrů | Explicitní odmítnutí s výzvou obnovit náhled. Opakování nikdy nepřepíše cizí změnu. |
| Provenance a idempotence | `legacy_digest`, digest zprávy, operation ID | Zachovávají identitu požadavku. Nejsou podmínkou zapnutí. |

Nová revizní vazba mimo tyto tři třídy je v rozporu s kontraktem. Pokud ji
funkce potřebuje, zavádí ji ADR.

## K6 — typovaný stav přes hranici procesu

Stav, podle kterého se rozhoduje druhý proces, je strojový kód vedle lidské
hlášky. Rozhodování podle textu, prefixu ani podřetězce hlášky není povolené
(B-ODD-02). Kód je stabilní identifikátor. Lidská hláška se smí měnit bez
změny protokolu.

| Hranice | Dnešní text | Kód |
|---|---|---|
| synchronizace IDE, obnova fronty | prefix `Queue refresh waits for human review` (`ide_queue.py`, `extension.js`) | `queue_refresh_state: "waiting_review"` |
| HTTP 503 před dispatchem | `{"error": "server busy"}` (`local_api.py`, `bridge.js`) | `code: "server_busy"` |
| odmítnutý zastaralý report | `Wrong source revision`, `Packet superseded`, `Working queue changed; publish a new packet` (`bridge.js`) | `code: "stale_report"` |
| nepodporovaná verze | různé texty (B-VER-03) | `code: "unsupported_version"` (K1) |

Poslední dva řádky jsou stejnou třídou problému jako B-ODD-02, i když je
audit jmenovitě neuvádí. AUDIT-B3-T2 je opravuje spolu s ním.

Kompatibilita obou směrů: nový backend posílá kód a ponechává dosavadní text,
aby starší rozšíření dál fungovalo. Nové rozšíření rozhoduje podle kódu, a když
kód chybí (starší backend), použije dosavadní rozpoznání textu. Dosavadní text
lze odstranit až zvýšením minimální podporované protokolové verze rozšíření
(K7).

## K7 — protokolová verze rozšíření a backendu

Rozšíření a backend si vyměňují celočíselnou protokolovou verzi, odlišnou od
verze balíčku rozšíření i od `schema_version` souboru pairing. Podrobný návrh
je v [doplnění ADR 0060](adr/0060-local-file-ide-bridge.md#doplnění-18-11-2026--protokolová-verze-rozšíření-a-backendu-audit-b3).
Shrnutí:

- Rozšíření posílá v každém požadavku hlavičku `X-Workspace-Bridge-Protocol`.
  Chybějící hlavička znamená protokol 1, tedy dnešní rozšíření.
- Backend odpovídá hlavičkou se svým rozsahem `min–max`. Požadavek s vyšší
  verzí, než backend zná, odmítne před kontrolou polí kódem
  `unsupported_version` s `update: backend`. Požadavek pod minimem odmítne
  s `update: extension`.
- V rámci jedné protokolové verze zůstávají množiny polí uzavřené. Nové pole
  zprávy vyžaduje novou protokolovou verzi.
- Akce `extension-update` zůstává přijímaná pro každý protokol od 1 výš,
  aby se i nekompatibilní starší rozšíření mohlo aktualizovat.
- Neznámá novější `schema_version` souboru pairing vede v rozšíření k hlášce,
  že propojení vytvořil novější Workspace a rozšíření je třeba aktualizovat.
  Není to „neplatné nebo expirované propojení“.

## Povinnosti navazujících úkolů

**AUDIT-B3-T2 (implemented):**

- `UnsupportedVersion` podle K1 a její průchod HTTP odpovědí s `code`.
- Metadata artefaktu s ID artefaktu (B-VER-01).
- Plán autonomie a záznamy běhu podle K2 (B-VER-02).
- Registr uzlu, výměna obsahu, katalog projektů, pairing a plán podle K1
  (B-VER-03).
- Typované kódy podle K6 včetně zachování dosavadního textu (B-ODD-02).
- Protokolová hlavička a odmítnutí podle K7 (B-VER-04).
- Neměnit formát Gitu, indexu, journalu ani lokálních store.

**AUDIT-B3-T3 (implemented):**

- Fixture R3: artefakt s metadaty N+1 v commitu vede k `UnsupportedVersion`
  s ID artefaktu. Stav projektu se nezmění a po návratu na podporovanou verzi
  se projekt otevře.
- Fixture R4: plán autonomie v4 a uložený běh v4 vedou k explicitní chybě,
  ne k logice v1.
- Fixture N+1 pro registr, výměnu obsahu a katalog.
- Kombinace staršího rozšíření s novým backendem: chybějící hlavička, review
  rozpoznané podle textu a funkční `extension-update`.
- Kombinace nového rozšíření se starším backendem: chybějící kód a záložní
  rozpoznání textu.
- Nová revize dokumentu ponechá aktivovaný blok a frontu aktivní (K4).
- Žádný test nesmí očekávat tiché vypnutí jako správné chování.

## Crash boundaries

Kontrakt nemění operace přes více persistentních vrstev. Nová typovaná chyba
vzniká při validaci před zápisem, tedy před journalem, Gitem i indexem. Platí
crash boundaries [ADR 0003](adr/0003-coordinated-operation.md). Projekt s
nepodporovaným commitem se neobnovuje a index z něj nevzniká. Pending operace
v journalu zůstává zachovaná a obnova ji dokončí až program, který verzi
podporuje. Odmítnutý federační příjem nic neaplikuje. Typované kódy K6 a
protokolová hlavička K7 jsou bezstavové části odpovědí.

## Implementace (AUDIT-B3-T2) a regrese (AUDIT-B3-T3)

| Pravidlo | Implementace |
|---|---|
| K1 | `UnsupportedVersion`, `require_version` a `version_error_scope` ve `spikes/metadata.py`. `Handler.reply` (`local_api.py`) doplní chybovou odpověď 400, 409, 422 nebo 426 o typované údaje poslední verzové chyby téhož požadavku, takže je generická hláška routy nepřepíše. Odpovědi 401, 403, 404, 413 a 503 údaje nenesou. |
| K1 upřesnění | Pole `update` je vyplněné jen u **novější** verze. Nižší, chybějící nebo nečíselná verze jsou neplatná data bez rady k aktualizaci (`update: null`). Výjimkou je protokol K7, kde nižší verze znamená aktualizovat rozšíření. `subject` je jen bezpečný identifikátor; u snapshotu se bere z validované cesty, ne z obsahu. |
| K2 | `PLAN_CAPABILITIES` a `plan_capabilities()` v `action_autonomy.py`. Pohled na běh vrací `plan_capabilities`. `autonomy_service.py` a UI se ptají na `revisions`, `continuation`, `countdown` a `policy` místo `plan_schema_version == 3`. |
| K3 | Metadata artefaktu a registru (`validate_metadata`, `_validate_snapshot`), registr uzlu (`Administration.validate`), výměna obsahu (`validate_exchange`), katalog projektů (`validate_catalog`), plán a deskriptor akce. Odesílatel přeloží typované odmítnutí peeru (`peer_unsupported_version`) na `update: peer`: u výměny obsahu jako text stavu `rejected`, u katalogu jako `UnsupportedVersion`. |
| K6 | `SERVER_BUSY` (`code: server_busy`, i v přímé odpovědi admission), `StaleReport` (`code: stale_report`) a `ReviewWait` → `queue_refresh_state: waiting_review` / `blocked` / `null`. Rozšíření rozhoduje podle kódu a když kód chybí, podle dosavadního textu. |
| K7 | `spikes/bridge_protocol.py`, kontrola v `_do_POST` před dispatchem, hlavička odpovědi na `/v1/ide-bridge/*`. Rozšíření 0.5.10 posílá `X-Workspace-Bridge-Protocol: 1` a pairing s novějším schématem hlásí jako potřebu aktualizace. |

Regrese: `tests/test_version_compat.py`, která obsahuje fixture R3 (včetně
nezměněného HEAD a journalu a otevření po návratu verze), fixture R4 (parse
i uložený běh v4), registr, výměnu obsahu, katalog, překlad odmítnutí peeru
a protokol rozšíření a backendu přes skutečné HTTP. Dále `tests/ide_bridge.test.js`
(kód × dosavadní text oběma směry, 426, hlavička, pairing schema 3, typované
čekání na review) a `tests/test_ide_queue.py` (`queue_refresh_state`,
`stale_report`). K4 dokládají stávající testy
`test_monitoring_blocks.BlockTests.test_source_revision_change_preserves_activation_and_invalidates_http_cache`,
`…test_filter_change_keeps_schedule_and_reloads_unchanged_feed_without_reactivation`
a `…test_identical_processing_save_recovers_stale_revision_error_without_reactivation`.

## Konzistence s ADR a federačním kontraktem

| Podklad | Vztah ke kontraktu |
|---|---|
| [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md) | K4 přebírá aktivaci na stabilním ID bloku beze změny. Revize `MonitoringBlock` dál nese provenance, ale není podmínkou běhu. |
| [ADR 0062](adr/0062-pinned-queue-handoff.md) | K4 odpovídá stavu po `ed1d536`. CAS revize fronty spadá pod K5 (souběh). K6 nahrazuje textové rozpoznání čekání na review kódem a nemění sémantiku review. |
| [ADR 0060](adr/0060-local-file-ide-bridge.md) | K7 doplňuje protokolovou verzi. Pairing, discovery endpointu, updater a uzavřené množiny polí zůstávají. |
| [ADR 0003](adr/0003-coordinated-operation.md), [ADR 0023](adr/0023-metadata-and-import-provenance.md) | K3 potvrzuje validaci celého snapshotu a odmítnutí neznámé verze bez částečné projekce (ADR 0023: index „nesmí vydat částečnou v2 provenance“). |
| Federační kontrakt ([ADR 0042](adr/0042-bidirectional-native-git-sharing-sync.md), [ADR 0043](adr/0043-explicit-federated-conflict-resolution.md), [ADR 0081](adr/0081-complete-project-data-sync.md)) | Příjem validuje před aplikací a merge vyžaduje sémantickou validaci. K3 jen typuje odmítnutí a určuje stranu k aktualizaci. Žádná automatická volba verze ani částečný merge nevznikají. |

## Limity

- Výčet míst vychází z auditu B1, který neprošel V03 řádek po řádku.
  Zbývající `require(schema_version == 1)` u dokumentů a deskriptorů audit
  hodnotil jako správný kontrakt. Jejich hlášky zatím nejsou typované a pod
  K1 je převede až další dotčená změna.
- Odmítnutí peeru se k odesílateli dostane jen přes chybové tělo HTTP
  (≤ 4 KiB, validovaná pole). Překlad je ověřený jednotkovým testem
  `peer_unsupported_version`. Průchod do UI přes dvě skutečné instance uzlů
  ověřený není. Peer starší než tato dávka kód neposílá a odesílatel pak
  vidí dosavadní obecné odmítnutí.
- Automatická obnova (`ContentSyncScheduler`) zapisuje typované odmítnutí
  jen jako text stavu `rejected`. Strojový kód se v uloženém stavu neukládá.
- Validaci konfigurace externího CMS modulu audit nečetl. Kontrakt pro ni platí
  jako požadavek, nikoli jako ověřený stav.
