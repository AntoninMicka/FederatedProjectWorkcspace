<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Záznam dokončené práce

## M1-07 — LXC autostart; implementační předání s odloženou cílovou akceptací — 2026-09-17

Implementace byla začleněna PR #24 jako commit `3c09090` v `develop`; feature větev `feature/m1-07-lxc-autostart` dodala bezpečné idempotentní nastavení vlastní sekce `lxc-auto.federated_workspace`, rollback a testy. Dávka je administrativně předána na výslovné rozhodnutí uživatele odložit další restart routeru. Nejde o splnění cílové restartové akceptace ani uzavření Gate M1; otevřené ověření je zachováno v BACKLOG jako `M1-07-C`.

- [x] [completed] **M1-07-A — Lokální implementace autostartu (implemented, 2026-09-17).** Instalace spravuje jen vlastní pojmenovanou UCI sekci, zachovává ostatní kontejnery, odmítá cizí kolizi a zahrnuje stav do rollback journalu.
- [x] [completed] **M1-07-B — Lokální regresní ověření (PoC validated lokálně, 2026-09-17).** Cílených 15 testů prošlo; plná sada měla 216 úspěšných testů a 22 podmíněných skipů. Skutečný reboot nebyl součástí běhu.

Omezení: uživatel dříve potvrdil zachování instalace a dat po restartu, ale kontejner se tehdy automaticky nespustil. Oprava autostartu po novém reálném restartu dosud ověřena není. Ověřit běh kontejneru a služby, dlaždici, přihlášení a náhled; výsledek teprve může doložit zbývající část Gate M1.

## F-M1-SOURCE-02 — Vynucení neměnných zdrojů a navazující verze — 2026-09-17

Dávka uzavřena po začlenění PR #23 jako commit `a93dd75` v `develop`; feature větev `feature/f-m1-source-02-enforcement` končí `55c0211`. Dosažená úroveň je lokální PoC validated; Gate M1 zůstává otevřený.

- [x] [completed] **F-M1-SOURCE-02-A — Transition validátor a podporované publikační cesty.** Workspace kontroluje base/kandidát před journalem i commitem; první Git přenos kontroluje každý parent→child přechod převzaté historie. Změna či odstranění source bajtů, identity, basename nebo v2 import provenance pod stejným UUID se odmítá.
- [x] [completed] **F-M1-SOURCE-02-B — Metadata-only editace a navazující verze.** Povolené anotace jsou verzované, uvolnění privacy explicitně autorizované; nová verze má nové UUID a volitelný vztah `supersedes`. SHA-256 duplicity se pouze hlásí a neslučují automaticky.
- [x] [completed] **F-M1-SOURCE-02-C — UI, recovery a dokumentace.** Importní dialog nabízí předchůdce a upozornění na shodné bajty; operace používají společný Workspace journal/CAS/index/receipt lifecycle.

Ověření: cílená sada 33 testů OK s jedním podmíněným Qt skipem; samostatný skutečný Qt test 1/1 OK; plná sada mimo socketový sandbox 215 testů OK a 22 podmíněných skipů. Obecný merge/fast-forward projektů není současnou aplikační schopností a musí při budoucí implementaci použít stejný transition validátor. Cílové zařízení ani výpadek napájení tato dávka neověřovala.

## F-M1-META-02 — Implementace importní provenance v2 — 2026-09-17

Dávka uzavřena po doloženém začlenění PR #22 jako commit `fb613ad` v `develop`; feature větev `feature/f-m1-meta-02-provenance-v2` obsahovala implementaci i následné uživatelské upřesnění času vzniku zdroje. Dosažená úroveň je lokální PoC validated; Gate M1 zůstává otevřený.

- [x] [completed] **F-M1-META-02-A — Parser a projekce v2 (PoC validated, 2026-09-17).** Striktní parser podporuje smíšený v1/v2 snapshot, podmíněný importní blok a vazbu hashe na skutečné source bajty. Index projektuje úplnou provenance a staré/rozpracované schéma atomicky obnovuje z validovaného HEAD.
- [x] [completed] **F-M1-META-02-B — Nový import a doložená migrace (PoC validated, 2026-09-17).** Nové importy zapisují v2; request digest váže bajty, hash i provenance. Explicitní migrace vyžaduje doložený původní Workspace commit, ancestry, operation trailer a shodu neměnných polí/bajtů.
- [x] [completed] **F-M1-META-02-C — UI, recovery a akceptace (PoC validated, 2026-09-17).** UI bezpečně zobrazuje importní provenance; retry/receipt, chybné vstupy, pády před/po CAS a při indexaci, skutečné Qt/WebEngine, balení a offline provoz byly ověřeny.
- [x] [completed] **F-M1-META-AH-01 — Oddělit čas importu a vznik zdroje (implemented, 2026-09-17).** Import přijímá pouze explicitní doložený `source_created_at`; automatický `imported_at` zůstává samostatný a pozdější. Neznámý vznik se neodhaduje.

Oveření na finálním obsahu před předáním:

- Cílená sada metadata/import/index: 24 testů prošlo bez chyb a skipů.
- Rozšířená sada před posledním ad-hoc UI doplněním: 209 testů, 205 prošlo a čtyři volitelné libgit2 probe testy byly přeskočeny; skutečné Qt/WebEngine, `.deb` a offline scénáře běžely.
- Po F-M1-META-AH-01 prošlo 14 cílených backendových testů s jedním očekávaným Qt skipem a samostatné skutečné Qt dialog + WebEngine scénáře 2/2. Celá rozšířená sada měla 210 testů: 205 prošlo, čtyři libgit2 byly přeskočeny a jednou selhal nesouvisející HTTPS browser smoke bez očekávaného stdout; bezprostřední izolovaný retry prošel. Po poslední UI změně proto není doložen nový celý bezchybný běh.

Omezení: migrace je programová, nikoli plošný UI wizard. Obecná transition ochrana všech publish/fast-forward/merge cest, metadata-only editace source a import navazující verze pokračují ve F-M1-SOURCE-02. Výpadek napájení, pád uvnitř libovolného syscallu a cílové zařízení nebyly touto dávkou doloženy.

## F-M1-SOURCE-01 — Kontrakt neměnnosti a verzování zdrojů — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #20 jako squash commit `7152d64` v `develop`; feature větev `feature/f-m1-source-01-versioning` končí `f20482f`. Šlo o designed dokumentační výstup bez implementace transition validátoru nebo schématu v2.

- [x] [completed] **V-05 — Neměnnost zdrojů (designed, 2026-09-15).** [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md) vymezuje neměnné bajty, basename, identitu a importní provenance pod jedním source UUID; projektové anotace zůstávají verzovaně editovatelné a uvolnění privacy vyžaduje explicitní autorizovanou reklasifikaci.
- [x] [completed] **F-M1-SOURCE-01-A/B — Verze, duplicity, transition validace a recovery (designed, 2026-09-15).** Nové bajty nebo revize dostávají nové UUID a mohou použít vztah `supersedes`; SHA-256 shoda sama neslučuje provenance ani privacy. Publish/fast-forward/merge musí v budoucí implementaci porovnávat base a kandidáta a novou verzi publikovat jednou expected-HEAD/Journal/CAS/index/receipt operací.

Kontrakt byl věcně zkontrolován proti importu, validátoru, mazání, Git historii a existujícím testům; lokální odkazy a `git diff --check` prošly. Celá sada se neopakovala, protože se aplikační kód, testy ani konfigurace nezměnily. Implementace provenance v2 pokračuje ve F-M1-META-02 a obecná transition ochrana/import navazující verze ve F-M1-SOURCE-02; Gate M1 zůstává otevřený.

## F-M1-META-01 — Přesný kontrakt metadat a importní provenance — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #19 jako squash commit `9acd0ef` v `develop`; feature větev `feature/f-m1-meta-01-contract` končí `da7647a`. Šlo o designed dokumentační výstup bez změny aplikačního kódu nebo schématu.

- [x] [completed] **V-04 — Přesný kontrakt metadat v1 (designed, 2026-09-15).** Registry povinně nesou `status`/`body`, `relations` jsou volitelné. `created_at` je vznik entity v projektu a u nativního importu čas importu; `author_id` je projektový aktér/importér, nikoli původní autor. Spustitelný validátor v1 zůstal beze změny autoritou současného formátu.
- [x] [completed] **F-M1-META-01-A/B — Importní provenance, kompatibilita a recovery (designed, 2026-09-15).** [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md) vyhrazuje v2 s podmíněným `import` blokem, zachovává smíšené v1/v2 čtení a zakazuje vymýšlení chybějící provenance. Explicitní migrace použije standardní expected-HEAD/Journal/CAS/index/receipt recovery.

Kontrola proti `spikes/metadata.py`, `spikes/source_import.py`, `spikes/storage.py` a testům potvrdila popsané v1. Oba JSON příklady, lokální odkazy a `git diff --check` prošly; celá testovací sada se neopakovala, protože se kód, testy ani konfigurace nezměnily. Implementace v2, migrace a jejich recovery testy zůstávají F-M1-META-02; Gate M1 zůstává otevřený.

## F-M1-DELETE-01 — Ověření bezpečného odstranění dokumentu — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #17 jako squash commit `ab296fd` v `develop`; původní pracovní větev byla `F-M1-DELETE-01/M1-08`. Archivace evidence a aktivace další dávky probíhá na `feature/f-m1-meta-01-contract`; není novým během testů ani uzavřením Gate M1.

- [x] [completed] **M1-08 — Bezpečné odstranění dokumentu (PoC validated, 2026-09-15).** Nativní editor vyžaduje potvrzení; Artifacts odstraní verzovaný Markdown dokument a sidecar/frontmatter jednou Workspace operací, zachová Git historii, odmítne příchozí strukturované vztahy a neplatný kandidátní snapshot. Retry používá stejný operation ID/receipt, writer lock, expected HEAD, CAS a recovery dle ADR 0003/0016.
- [x] [completed] **Akceptační a recovery ověření (PoC validated, 2026-09-15).** Sidecar/frontmatter, vlastněné cesty, zachování ostatních entit/historie, příchozí vztahy z artefaktů i registrů, self/outgoing vztahy, hlavní TODO, stale/dirty/staged/busy, neplatné vstupy/snapshot, odmítnutí sources a skutečný Qt cancel/retry/reload byly ověřeny.

Osmnáct procesních přerušení sidecaru a sedmnáct frontmatteru (35 hranic včetně `before-ref` a pěti indexových checkpointů) skončilo po native open jedním commitem a indexem bez odstraněného UUID. Receipt zajistil idempotentní retry; cizí znovuvytvořený soubor při pending zůstal zachován a recovery odmítla pokračovat.

Ověření na finálním obsahu dávky:

- `M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_artifact_deletion -v`: 9 testů prošlo (16,350 s).
- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v`: 204 testů prošlo za 133,575 s, 4 volitelné libgit2 testy přeskočeny. Skutečné Qt/WebEngine, izolované balení/instalace a offline testy byly zapnuté.

Omezení: lokální Linux PoC bez cílového LXC/routerového ověření, výpadku napájení nebo přerušení uvnitř libovolného Git/SQLite syscallu. Koš, UI obnovy odstraněných dokumentů, mazání sources a federovaná synchronizace nebyly součástí dávky. Gate M1 zůstává otevřený.

## F-M1-INDEX-01 — Relační projekce projektového indexu — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #16 v lokálním `develop` (`948bf69`); feature větev `feature/f-m1-index-01-relations` končí `22d5098`. Porovnání implementace, testů a ADR 0022 mezi feature větví a `develop` je bez rozdílu. Archivace je dokumentační předání, nikoli nový běh testů ani uzavření Gate M1.

- [x] [completed] **F-M1-INDEX-01 / V-03 — Relační projekce (PoC validated, výstup 2026-09-14).** Metadata v1 artefaktů/registrů, cesty, štítky a explicitní směrované vztahy; atomická migrace/rebuild a přesný commit ID, FK a stale/pending hranice podle ADR 0022.
- [x] [completed] **F-M1-INDEX-AH-01 — Desktop smoke akceptace (PoC validated, 2026-09-14).** Selektor omezený na výběr projektu a sidebar test připojený k aktuálním assets; skutečné UI scénáře a závěrečná sada ověřeny.

Původní výsledky, návrh, recovery a omezení jsou zachovány níže. Závěrečná sada z 2026-09-14 měla 195 testů, 191 prošlo a čtyři volitelné libgit2 skip; desktop, HTTP/backend, balení a offline scénáře běžely. V tomto předání nebyla sada opakována, kód/testy se nemění. Git zůstává autoritou; SQLite projekce není journalem. V-04/V-05, cílové měření výkonu a Gate M1 zůstávají otevřené.

F-M1-DELETE-01/M1-08 přesunuta z BACKLOG do TODO jako jediná plánovaná feature; její implementace a větev nezahájeny. Částečný backendový důkaz odstranění z indexních testů nepokrývá celé M1-08. Backlog nyní připravuje tři další konkrétní dávky: návrh metadat V-04, návrh neměnnosti V-05 a Context Builder s podmínkami M1. V-04/V-05 mají stále svůj původní otevřený rozsah, návrh nenahrazuje jejich budoucí implementaci.

<details>
<summary>Původní evidence indexní dávky před uzavřením</summary>

Historický přepis zachovává původní důkazy a stav před PR. Formulace „PR není otevřen ani sloučen“ nebo „čeká na sloučení“ jsou překonány doloženým PR #16 výše, nejsou aktuálními otevřenými úkoly.

#### F-M1-INDEX-01 — Relační projekce projektového indexu

- Stav: [x] [completed]; milník M1; lokální PoC validated. Výstup ověřen, dávka čeká na předání a sloučení PR do `develop`.
- Původ: V-03 a zbývající integrace metadat/indexu M1; ADR 0002/0003.
- Větev: `feature/f-m1-index-01-relations`, založena 2026-09-14 z lokálního `develop` (`0849ec8`). Dokumentační předání importní dávky bylo před implementací commitnuto (`54a2d39`). Cíl jediného PR: `develop`; PR zatím nevytvořen; implementace a ověření dokončeny, commit/push/merge v tomto běhu neprovedeny.
- Výstup: doložený kontrakt a implementace lokálně obnovitelné projekce vztahů/metadat, nesoucí přesný commit ID.
- Mimo rozsah: změna Git autority, synchronizace SQLite, nové LLM/RAG databáze.
- Závislosti: stabilní metadata kontrakt v `develop`; importní změny pouze pokud jej ovlivní.
- Akceptace jednoho PR: rebuild z HEAD, stale/pending odmítnutí, referenční integrita a změny po rename/delete/import, bezpečná migrace projekce, testy a dokumentace.

##### Úkoly a ověření

- [x] [completed] **F-M1-INDEX-01 / V-03 — Relační projekce (PoC validated, 2026-09-14).** Index ukládá všechna validovaná metadata v1 artefaktů a registrů, cestu obsahu/registry, štítky a směrované vztahy vázané na přesný commit ID. FK, pořadí i duplicity se zachovávají; příchozí/odchozí dotazy filtrují explicitní hrany. Atomická migrace/rebuild, stale/pending odmítnutí a recovery po procesních přerušeních ověřeny. Native import, editace metadat, rename/delete a rebuild chybějící DB ověřeny; skutečný desktop, HTTP/backend, balení a offline běžely v celé sadě. Kontrakt: [ADR 0022](docs/adr/0022-relational-index.md).

V-03 — Vyjasnit omezení projekce indexu — je součástí této feature; jeho aktuální stav je zde. Výchozí index validoval vztahy, ale ukládal pouze id/title a commit ID. Rozšíření nyní pokrývá úplná validovaná metadata v1 artefaktů/registrů a explicitní vztahy; nejde o univerzální grafovou DB, další schémata ani produkční nasazení. Git zůstává autoritou, SQLite index je obnovitelná lokální projekce a není journalem rozpracovaných operací.

#### Kontrakt před implementací — 2026-09-14

Adapt/reuse současného Index/Workspace, validátoru metadat a stdlib SQLite; nový storage framework ani externí kód nejsou potřeba. Soukromá inventura neposkytuje důvod nahrazovat tuto koordinaci. Git schéma se nemění; projekce zachová metadata včetně absence volitelných polí, cestu obsahu/registru, pořadí štítků a směrovaných vztahů i duplicity. Validátor dovoluje neprázdné vlastní typy vztahů; index je nezpřísní ani nedoplní inverzní vazby. Pole note není součástí spustitelného v1 schématu a index je nezavádí.

Crash boundaries ADR 0003 zůstávají platné. Rozšíření: migrace staré projekce a výměna entit/štítků/vztahů/commit ID proběhne v jedné explicitní SQLite transakci; pád před potvrzením ji vrátí, po potvrzení lze rebuild opakovat. Stará projekce se nepublikuje jako aktuální; neznámá budoucí verze se odmítne bez přepsání. Journal, Git commit, soubory a receipt se migrací nemění. Při pending stavu aplikační čtení odmítá data; samostatný Index journal nezná. Čtení kontroluje HEAD před i po SQL dotazu. Výpadek napájení a nekooperující FS/Git útočník zůstávají mimo PoC.

#### Průběžné ověření — 2026-09-14

- `python3 -m unittest tests.test_index_projection tests.test_storage tests.test_workspace -v`: 25 testů prošlo, bez skip a chyb (8,915 s). Nových osm regresních testů pokrývá projekci všech v1 metadat, frontmatter/sidecar/registry, FK a příchozí/odchozí dotazy, vlastní typy/duplicity/pořadí, neplatný Git snapshot, drift HEAD při rebuild i čtení, migraci staré DB a odmítnutí budoucí verze, SQL čtenáře během výměny a 15 procesních přerušení (pět checkpointů při migraci, rebuild i Workspace recovery).
- Integrační native služby: import přesných CRLF/frontmatter bajtů, privacy local-only, změna popisu/štítků, rename bez změny vazeb, blokované odstranění při příchozí vazbě, následné odstranění a rebuild chybějící DB. Projektový přehled odmítne nesoulad projekce metadat/vztahů/štítků s validovaným commitem.
- První celá sada se zapnutým desktopem/balením/offline: 194 testů, šest UI selhání a jedna chyba vyčerpaného HEAD mocku, čtyři libgit2 skip (158,763 s). Příčiny odstraněny a ověřeny závěrečným během níže. Cílové LXC/router ani uživatelské projekty nejsou měněny; bez měření cílového výkonu, bez dokončení V-04/V-05 a bez uzavření Gate M1.

- [x] [completed] **F-M1-INDEX-AH-01 — Obnovit platnost skutečného desktop smoke při závěrečné akceptaci (PoC validated, 2026-09-14).** Původ: úplný běh odhalil timeouty v projektových smoke scénářích; historický globální selektor select odmítal i skryté administrační formuláře přítomné už v HEAD a sidebar test injektoval JavaScript do starých assets. Rozsah: omezit smoke kontrolu na projektový katalog/levý výběr projektu a připojit sidebar test k aktuálním desktopovým assets. Podmínka dokončení: všech šest dotčených WebEngine scénářů a následná celá sada. Nejde o samostatnou UI feature.

Doplnění crash/migrační ochrany: constructor odmítá i neznámé legacy tabulky/sloupce bez přidání indexových tabulek, včetně DB s operations; journal se nesmí inicializovat jako index. Cílený běh po této úpravě: 26 testů, bez chyb/skip (9,439 s). Pořadí volání HEAD v legacy testu bylo nahrazeno trvající změnou HEAD; projektový read při driftu odmítne reindexaci jiného snapshotu.

Cílené UI re-testy po opravách: tři scénáře náhledu/projektového přehledu/záložek prošly (22,646 s); další tři scénáře readonly TODO stromu, create/reopen a sidebar cancel/save prošly (17,421 s). Závěrečný běh celé sady po posledních změnách prošel, viz níže. Devět nových projekčních regresních testů prošlo (3,926 s).

#### Závěrečné ověření a předání — 2026-09-14

- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` mimo omezení lokálních socketů/Qt v sandboxu: **195 testů, 191 prošlo, 4 přeskočeny, bez chyb (114,552 s)**. Skutečné Qt/WebEngine, native editor/history/preview, HTTP/HTTPS, izolované balení/install/upgrade/remove a offline provoz běžely. Přeskočeny pouze čtyři volitelné testy libgit2 probe; aplikace používá Git CLI.
- Devět nových projekčních regresních testů v `tests/test_index_projection.py`; procesní přerušení uvnitř SQL transakce (mezi checkpointy) při migraci/rebuild i při Workspace recovery. Výsledky dřívějších běhů výše jsou historické, tento běh pokrývá finální kód/testy.
- Dokumentace a místní odkazy ověřeny; `git diff --check`, finální diff i nové soubory zkontrolovány. Samostatný build/lint není pro aplikaci nakonfigurován; existující balicí kontroly běžely.

Scope jednoho PR `feature/f-m1-index-01-relations -> develop`: relační projekce metadat/cest/štítků/vztahů, atomická migrace z v0, FK a směrované dotazy, společná stale/pending hranice, porovnání celé projekce s Git snapshotem, regresní/recovery testy a ADR 0022. Nezbytná ad-hoc oprava zpřesňuje pouze testovací smoke selektor a používané assets; běžné UI workflow se nemění.

Recovery: před commitem zůstává autoritou journal; po commitu index rebuild z validovaného HEAD. Pád před SQL potvrzením vrátí celou projekci/migraci, po potvrzení lze indexaci opakovat bez dalšího commitu; pending se uvolní až po journalovém úklidu. Neznámá verze/layout DB se odmítá bez smazání/downgrade, journal se nemění. Omezení: lokální Linux PoC, bez cílového měření výkonu/paměti nebo nového LXC/router nasazení, bez výpadku napájení a nekooperačních FS záruk; V-04/V-05 a Gate M1 zůstávají otevřené. PR není otevřen ani sloučen; dokončené úkoly zůstávají v TODO do uzavření dávky.

</details>

## F-M1-IMPORT-01 — Nativní import zdrojových dokumentů — 2026-09-14

- [x] [completed] **F-M1-IMPORT-01 — Nativní import (PoC validated).** Výběr Markdown/PNG/JPEG/PDF, původní bajty, sidecar metadata/privacy/provenance a společný Workspace commit; zobrazení v Podkladech. Bez nové mutující HTTP route.
- [x] [completed] **Ověření (PoC validated).** Závěrečný běh na lokálním `develop` `0849ec8`: `python3 -m unittest discover -s tests -v` mimo socketové omezení sandboxu — 186 testů, 166 prošlo, 20 přeskočeno, bez chyb (53.058 s). Obsahuje tři nové regresní testy formátů, importního limitu 16 MiB a nezávislého limitu náhledu 4 MiB. Volitelné scénáře nebyly zapnuté; první sandboxový běh selhal na lokálních socketech, nikoli na importních testech.
- [x] [completed] **Předání (PoC validated).** Lokální historie `develop` dokládá začlenění importu v PR #13 (`082b69f`), následné opravy Qt v #14 (`86e1fd6`) a regresních testů/dokumentace v #15 (`0849ec8`). Původní plán jednoho PR byl fakticky předán třemi již začleněnými PR ze dvou větví; tento dodatek popisuje doloženou historii. V tomto běhu nebyl proveden commit, push, otevření PR ani merge.

Nová samostatná kontrola `/tmp/fw-import-recovery-check.py`: 17 skupin prošlo, včetně byte-identity CRLF/frontmatter, metadata/privacy, unsafe/symlink/změněného zdroje, digestu, dirty/busy/stale, receipt/retry a pádu procesu na 12 checkpointech ADR 0003. Konfliktní cizí editace zůstala zachována; její odstranění proběhlo pouze v izolované fixture. Po obnově právě jeden commit, čistý Git a žádná pending operace. Dočasný harness není trvalý regresní test.

Nový skutečný Qt smoke (`QT_QPA_PLATFORM=offscreen`, `/tmp/fw-continue-import-qt.py`) prošel načtením dialogu, pickerem, zrušením potvrzení bez změny HEAD, potvrzeným importem a dokončením workeru/saved signálu; přesné původní bajty, jediný commit a čistý Git. Uživatel už dříve potvrdil import a zobrazení ve skutečném desktopu. Offscreen test neznamená nové cílové ověření LXC/routeru.

Recovery a mantinely ADR 0003/0016 se nemění. V-04/V-05 zůstávají otevřené v BACKLOG: samostatné datum importu/podrobná provenance a ochrana před externími Git úpravami nejsou dodány. Gate M1 zůstává otevřený. Relační projekce F-M1-INDEX-01/V-03 je přesunuta do TODO jako jediná plánovaná dávka; její implementace a větev nejsou zahájeny.

<details>
<summary>Původní evidence importní dávky před závěrečným předáním</summary>

Historický přepis zachovává původní důkazy a dočasné chyby/stavy. Formulace o neopravené Qt chybě, chybějícím regresním běhu a neprovedeném merge byly pozdějšími výsledky výše překonány; nejde o aktuální otevřené úkoly. Původní sekce „K předání do backlogu“ obsahovala převážně časový průběh ověření, který patří do historie; otevřené V-04/V-05 zůstávají pod původními ID v BACKLOG.

#### Rozsah a předání

- Větev: **`feature/f-m1-import-01-native-sources`**, založená z čistého lokálního `develop` při zahájení úkolu. PR do `develop` zatím nevytvořen; push/merge neprovedeny.
- Původ: uživatelem schválený import, zbývající požadavek M1; související V-04/V-05, ADR 0003/0016.
- Cílová úroveň: PoC validated. Aktuálně implemented, částečně ověřeno; rozsah důkazů a zbývající kontroly níže.
- Výstup: nativní výběr Markdown/PNG/JPEG/PDF, zachování původních bajtů, sidecar metadata/privacy/provenance, potvrzený společný zápis a zobrazení v Podkladech.
- Mimo rozsah: externí konektory IMP-01–03, LLM, synchronizace, obecná migrace metadat a globální zákaz externích Git úprav zdrojů.
- Kontrakt: imported source má kind=source/provenance=external, vytvoření artefaktu znamená okamžik importu. Obsah je v nativním editoru nepozměnitelný, nová verze má nové UUID. Samostatné imported_at a původní autor externího zdroje nejsou novými schema fields; V-04/V-05 zůstávají mimo tento omezený kontrakt otevřené.

#### Úkoly této feature

- [x] [completed] **F-M1-IMPORT-01 — Nativní import (implemented, 2026-09-14; částečně ověřeno).** Sources adaptuje Artifacts/Workspace, originální soubor a metadata publikuje jedním commitem, request digest váže SHA-256 přesných bajtů a opakování stejné operation ID. Před přípravou journalu validuje výsledný snapshot. Native picker má explicitní potvrzení a retry/recovery; uložený source se zobrazí přes stávající Podklady/preview. Bez nové mutující HTTP route.
- [ ] [completed] **Ověření:** byte-identita Markdown včetně CRLF/frontmatter, PNG/JPEG/PDF, 16 MiB limit a nezávislý 4 MiB preview limit, unsafe/symlink/změněný zdroj, metadata/privacy, stale/dirty/busy/foreign, receipt/retry a procesní checkpointy, source-only editor hranice, skutečný Qt a celá sada testů. Přidané cílené testy v `tests/test_source_import.py` ověřují: 1) podporu a uložení Markdown/PNG/JPEG/PDF, 2) odmítnutí nepodporovaného typu a překročení 16 MiB, 3) nezávislost náhledového limitu 4 MiB na importním limitu.
- [ ] [in progress] **Předání PR:** zakreslit scope, důkazy, omezení a recovery; připravit jeden PR `feature/f-m1-import-01-native-sources -> develop` bez mergování.

#### Návrh předání PR

- Scope: kompletní implementace nativního importu Markdown/PNG/JPEG/PDF přes picker a importní pipeline, validace integrity (SHA-256 byte-identita), sidecar metadata (`kind=source`, `provenance=external`, `privacy=project`), zobrazení přes Podklady/preview, journaling + recovery flow, validace limitů a bezpečnostních hranic.
- Důkazy: `tests/test_source_import.py` (lokální cílené scénáře), dočasný harness `/tmp/fw-import-recovery-check.py` (restart a checkpointy), real-time offscreen Qt smoke, a úplný výpis ověřovací sekce v TODO.
- Omezení: mimo testy nebylo ověřeno nasazení na cílové hardwarové instance/routery; `WorkingDirectory`/deploy path a externí LXC scénáře jsou mimo rozsah; Gate M1 zůstává otevřený.
- Recovery: retry přes stejné `operation_id` vrací původní receipt; stale/retry konflikty a cizí změny po prepare aktivují `RecoveryConflict`; po explicitní čisté obnově se import dokončí deterministicky, bez pending operací a při zachování cizích změn.

#### Důkazy ověření — 2026-09-14

- Uživatel potvrdil import a zobrazení zdroje ve skutečném desktopu.
- Po opravě kolize ImportDialog.finished se signálem Qt: skutečný offscreen Qt dialog a worker prošly; načtení aktivuje výběr souboru. Celá stávající sada po opravě: 183 testů, 163 prošlo, 20 přeskočeno, bez chyb (49,942 s, mimo socketová omezení sandboxu). Sada sama nepokrývá všechny nové importní scénáře.
- Izolovaný dočasný harness /tmp/fw-import-recovery-check.py: 17 skupin kontrol prošlo. Odmítnuty unsafe názvy, symlink, adresář, nepodporovaný formát, neplatné UTF-8/NUL, zdroj nad 16 MiB, změna při čtení, chybný digest a metadata. Dirty tree a obsazený writer lock odmítnuty bez přepsání cizích dat. Identický retry vrací původní receipt, změněný intent a stale HEAD jsou odmítnuty.
- Proces byl ukončen os._exit(73) na prepared, file:0, file:1, applied, files-applied, commit-created, commit-ready, ref-updated, committed, git-indexed, indexed a completed. Po restartu ve všech 12 případech přesné původní Markdown bajty včetně CRLF/frontmatter, kind=source/provenance=external/privacy=project, právě jeden commit, čistý Git a žádná pending operace. Cizí změna po přípravě vyvolá RecoveryConflict a zůstane zachována; po jejím explicitním odstranění pouze v testovací fixture recovery dokončí import.
- Harness není trvalý regresní test; živý LXC/router ani uživatelské projekty nebyly měněny. Tato kontrola neuzavírá celou dávku ani Gate M1.
- Definice obousměrných typů vazeb (`supports/supported_by`, `contains/part_of`, `depends_on`, `implements`, `derived_from`, `references`, `cites`, `produces`) byla doplněna v [DATA_MODEL.md](DATA_MODEL.md).

#### K předání do backlogu

Ověření 2026-09-14: izolované backendové scénáře importu prošly (původní bajty včetně CRLF/frontmatter, PNG/JPEG/PDF hlavičky, metadata, receipt/retry, náhled Markdown/PNG/PDF, odmítnutí stale HEAD, jiného SHA-256 a symlinku). Obnova po skutečném ukončení procesu na osmi checkpointech prošla s jediným commitem a čistým pracovním stromem. První běh celých testů v sandboxu: 183 testů, 20 socketových errors a 20 volitelných skip; běží opakování mimo socketové omezení. Skutečný Qt odhalil blokující chybu `RuntimeError: Failed to connect signal finished()` při otevření ImportDialog: handler `finished` koliduje s QDialog signálem. Oprava zatím neprovedena, feature není připravena k merge. Dočasné ověřovací scénáře nejsou novými trvalými regresními testy.

Žádné nové nezávislé feature. Návaznosti V-04/V-05 zůstávají v BACKLOG se svými původními ID.

Závěrečný regresní běh mimo socketově omezený sandbox: `python3 -m unittest discover -s tests -v` — 183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb, 49,613 s. Tento existující unittest běh neobsahuje nový ImportDialog smoke; jeho samostatně zjištěná Qt chyba proto dál blokuje akceptaci feature. Kompletní oprava/UI re-test zatím nebyly provedeny.

Oprava Qt blockeru (2026-09-14): handler přejmenován na operation_finished. Opakovaný skutečný Qt smoke prošel otevřením dialogu, zrušením potvrzení bez změny HEAD, potvrzeným importem, worker completion, zachováním přesných CRLF/frontmatter bajtů a čistým Git stromem. Qt blocker je odstraněný; po této opravě byla opakována pouze cílená UI kontrola, nikoli znovu celá regresní sada. PR/merge stále neprovedeny.

</details>

## WF-03 — Předání pravidel feature dávek — 2026-09-14

Pravidla feature větví/PR, čištění TODO a reorganizace backlogu byla předána uživatelem navazujícím pokynem zahájit další feature. Čistý lokální `develop` obsahoval commit `a450205 docs(workflow): automate feature branch creation and recommend pull requests`. Ověřeno při zahájení importní dávky; vzdálený stav PR ani merge nebyly kontrolovány a nejsou tímto tvrzené. Jde o administrativní předání podle pokynu uživatele, nikoli nový gate review. Dřívější kontrola úklidu doložila TODO o 24 řádcích a jednu aktivní dávku; následné úpravy pravidel nebyly znovu kompletně dokumentačně ověřeny. Nativní import má samostatnou větev a jediný plánovaný PR do develop.

Dokončené výstupy, výsledky ověření a historická gate review. Aktuální dávku včetně dosud nearchivovaných dokončených úkolů drží [TODO](TODO.md), vzdálenější otevřené položky [BACKLOG](BACKLOG.md), strategii a gates [roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>).

Starší záznamy od review M0-09R níže byly beze změny důkazů přesunuty z TODO. Časy, počty testů, popisy tehdejšího stavu a starší negativní review jsou historické; neoznačují automaticky dnešní stav. Nové záznamy přidávejte nahoru až při uzavření celé dávky, s ID úkolů, daty, úrovní výsledků, ověřením a omezeními. Během dávky zůstávají výsledky v TODO. Původní ID a důkazy zachovávejte; věcné opravy doplňujte jako datované dodatky.


## Administrativní předání dokončené evidence M1 — 2026-09-14

Převzaté dříve označené dokončené výstupy a původní důkazy ze širokého TODO. Nejde o nové testy, uzavření celé dávky M1 ani doložený merge PR. Otevřené části byly přesunuty do BACKLOG; milník a gates zůstávají otevřené. Staré formulace o umístění v TODO jsou historické, současný stav evidence určují TODO/BACKLOG.

- [x] [completed] **M1-AH-08 — Desktop federace bez prvního projektu a viditelné chyby (PoC validated, 2026-09-13).** Hlášení uživatele: desktopové nastavení federace tiše selhává. Opraveny dvě doložené mezery: chybějící node.json nového desktopu a status mimo odscrollovaný viewport. Native handler bezpečně inicializuje prázdný uzel přes ProjectCreation writer lock, zachová author/node UUID, nepřepíše poškozenou konfiguraci ani nenahradí identitu existujícího registru. Sticky status a role alert zobrazují API/HTML validation/nenačtenou správu/chybějící scope. Reuse bootstrap fsync/publikace a existujícího journalu; žádný nový projekt ani účet. Celá sada `python3 -m unittest discover -s tests -v` mimo socketový sandbox: **183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb**, 49,349 s. Nové testy: peer před prvním projektem, stabilní UUID, corrupt/lost config bez overwrite, retry po chybě publikace. Skutečný Qt/WebEngine s desktopovou request_policy/token politikou ověřil prázdný uzel, viditelné HTML/API chyby v odscrollovaném dialogu a úspěšné přidání peeru. JS syntaxe a whitespace diff bez chyb. Běh nezapínal všechny volitelné balicí/offline/Qt/libgit2 scénáře; uživatelova konkrétní běžící instalace nebyla aktualizovaná ani ověřena. M1-AH-07/M5 cílové akceptace zůstávají otevřené.

Ověření M1-AH-07 (2026-09-13, lokální PoC validated): závěrečné `python3 -m unittest discover -s tests -v` mimo socketově omezený sandbox — **180 testů, 160 prošlo, 20 volitelných přeskočeno, bez chyb**, 49,973 s. Dva dočasné uzly se skutečnými Ed25519 klíči ověřily samostatné podpisy, aktivaci až se dvěma potvrzeními, chybný pin/tampering, cizí login, ACL průnik s reader a zachování origin manifestu/privacy, revokaci/replay včetně revokace doručené před potvrzením, neobnovení mapování po opětovném trust a migraci registru bez změny credential. Ověřen i nativní token proti webovému klíči, jediná desktopová identita a odmítnutí dalších účtů; ztracený node key není nahrazen. Skutečný Qt/WebEngine smoke pro web i native handler prošel přepínáním samostatných záložek a tabulek a kontrolou jednoho desktopového účtu/skrytí tvorby účtů. JS syntaxe web/native a diff whitespace bez chyb. Celkový běh nezapínal všechny volitelné Qt/offline/balicí/libgit2 testy. Cílové nasazení, automatický transport a atomické publikování ACL s daty nebyly ověřeny ani implementovány v tomto kroku; nejsou tímto označené za hotové.

- [x] [completed] **V-11 — Příprava veřejné distribuce (designed, 2026-09-10).** Distribuční metadata a update channel byly sjednoceny pro aktuální PoC release režim: v `.deb` kontrolním souboru je explicitní `Maintainer` (už bez placeholderu), doplněn `Homepage` repozitáře a v dokumentaci je explicitně řečeno, že update je v této fázi ruční (`.deb` + `apt`), bez auto-updateru. V kontrolním testu .deb je potvrzeno, že placeholder byl odstraněn.

Ověření V-11:
- `python3 -m unittest tests.test_package_deb -v`
- `grep -n "Maintainer"` v `scripts/package_deb.py` a `tests/test_package_deb.py` potvrzuje novou hodnotu a regresní kontrolu.
- `git diff --check`.

Poznámka k otevřené části: před skutečným veřejným releasem zůstává právní review komponent distribuce mimo čistě projektovou kódovou základnu a oficiální potvrzení kontaktních dat v publikované licenci/release metadatech.

- [x] [completed] **V-08 — Registrace existujícího projektu (implemented, 2026-09-10).** Doplněn registrační tok pro již existující Git projekt: nová cesta `ProjectCreation.register` validuje kořenový Git repozitář, `project.json` v `HEAD` i pracovní kopii, kontroluje konfliktní/duplicitní `project_id`, vytváří lokální state vedle repozitáře a zapisuje registraci přes recovery flow.

Ověření V-08:
- `python3 -m py_compile spikes/project_creation.py tests/test_project_creation.py`
- `python3 -m unittest tests.test_project_creation.CreationTests -k register -v`: 4 testy OK, 2 testy přeskočeny.
- `python3 -m unittest tests.test_project_creation.CreationTests -v`: 15 testů, 1 chyba v legacy síťovém testu `test_default_path_is_lazy_and_http_cannot_create` (sandbox PermissionError na HTTP socketu), 2 přeskočeno.
- `git diff --check`.

- [x] [completed] **M1-06 — Přejmenování souboru Markdown dokumentu (PoC validated, 2026-09-10).** Navazující krok souhrnného M1 podle požadavku na konzistenci po přejmenování. Nativní editor ukládá název souboru, obsah a metadata jednou operací; zachová UUID, strukturované vztahy, hlavní TODO a historii. Sidecar aktualizuje file, frontmatter se přesune; čisté přejmenování přes službu zachová původní bajty. Reuse/adapt Artifacts, Workspace, validátoru a Qt; crash boundaries ADR 0003/0016 beze změny. [Kontrakt a limity](docs/adr/0016-markdown-editor.md#přejmenování-souboru-dokumentu--m1-06), [návod](docs/project-opening.md#přejmenování-souboru-dokumentu).

Ověření M1-06: cílených 21 testů artefaktů se skutečnými Qt widgety OK; doplněná ochrana dlouhého existujícího názvu následně ověřena cíleným Qt testem i závěrečnou celou sadou. Pokryty sidecar/frontmatter, souběžná změna textu/metadat, historie a příchozí vztahy, obnova odstraněného indexu, neplatné názvy, kolize s cizím souborem, stale/busy, cizí editace při recovery, ztracená odpověď/retry a restart, procesní přerušení na 13 checkpointech přejmenování. Závěrečný běh `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v`: **131 testů, 127 prošlo, 4 přeskočeny**, 91,259 s, bez chyb. Přeskočeny pouze volitelné testy porovnání libgit2 kvůli chybějícímu sestavenému probe; skutečný desktop, balení/upgrade/odstranění i offline běžely. Sandbox blokoval první pokus připojení Qt; ověření mimo sandbox prošlo. Místní odkazy včetně kotev, finální diff a `git diff --check` v pořádku. Omezení: volné textové odkazy na názvy se automaticky nepřepisují; Qt může normalizovat konce řádků. Lokální Linux PoC, bez nového ověření na cílovém zařízení. Mazání a import zůstávají otevřenými požadavky souhrnného M1; Gate M1 zůstává otevřený. Záznam zůstává v TODO do uzavření dávky.

- [x] [completed] **M1-05 — Metadata dokumentu v editoru (PoC validated, 2026-09-10).** Záložka Metadata zobrazuje uložená metadata pouze pro čtení a dovoluje upravit popis/štítky. Obsah i explicitní změny metadat se ukládají jednou operací s původním operation ID/retry/receipt; identita, autor, vytvoření, privacy a provenance se zachovávají. Podporovány sidecary i frontmatter, vyčištění hodnot a samostatná editace metadat. Po uložení se čte potvrzený stav z Gitu. Reuse/adapt Artifacts, Qt widgetů a validátoru; crash boundaries ADR 0003/0016 beze změny. Kontrakt a limity: [ADR 0016](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

Ověření M1-05: cílených 15 testů artefaktů OK se skutečnými Qt widgety; společný obsah/metadata a historie, restart, readonly metadata, ztracená odpověď a retry, vazba digestu na změny metadat, odmítnutí nepovolených/nevalidních/nadměrných metadat bez pending a recovery na všech 12 procesních checkpointech. Celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **119 testů OK, bez vynechání**, 62,895 s. Místní odkazy a `git diff --check` v pořádku. Lokální Linux PoC; produkční připravenost ani nové ověření na cílovém zařízení se tím neprohlašují. Zůstává v TODO do uzavření dávky M1.


## Ad-hoc úkoly aktuální dávky

- [x] [completed] **WF-02 — Práce po dávkách (implemented, 2026-09-10).** Požadavek uživatele: celé milníky v TODO, navazující dávky v BACKLOG, průběžně měnit jen TODO a archivovat až po uzavření dávky; podporovat ad-hoc práci. Upraveny pokyny a pracovní dokumenty, souhrnný úkol M1 přesunut z BACKLOG do této dávky. Ověření: konzistence pravidel a odkazů, zachování původních otevřených položek a historických záznamů, `git diff --check`. Pouze dokumentační změna; aplikační testy znovu nespouštěny. Záznam zůstává zde do uzavření dávky M1.

- [x] [completed] **M1-AH-01 — Materializované kompiláty v roadmapě (designed, 2026-09-10).** Ad-hoc požadavek uživatele: soubory s výsledky zpracování zdrojů podle zadání (např. orientační rozpočtové obálky), ručně obnovitelné z aktuálních i nových zdrojů, bez verzování a přenosu výsledků. Doplněna sekce 2E roadmapy, [ADR 0018](docs/adr/0018-materialized-compilations.md) a vazba v architektuře: zachované zadání, lokální cache mimo Git, manifest vstupů, aktuálnost, privacy, recovery a explicitní uložení trvalého artefaktu. Ověřena konzistence s Git autoritou, oddělením indexu/journalu a ADR 0008; návrhové scénáře zahrnují změny zdrojů, revokaci a pády. Místní odkazy a `git diff --check` ověřeny. Pouze návrh, bez implementace či nových runtime testů; Gate M1 se nerozšiřuje. Záznam zůstává v aktuální dávce.

- [x] [completed] **M1-AH-02 — Hlavní panel chatu a náhledů (PoC validated, 2026-09-10).** Hlavní panel přepíná orchestrační chat a náhled vybraného artefaktu s uloženým popisem/metadaty. Podporuje základní Markdown, PNG/JPEG a stránkový raster PDF; chat bez backendu umožňuje pouze lokální rozepsání zadání a odesílání je nedostupné. Přepnutí záložek zachová obsah, změna projektu jej vymaže a opožděné odpovědi se odmítají. Autentizovaný endpoint čte jeden validovaný commit a odmítá pending/stale; projektové soubory se nemění. Reuse Projects/Workspace, token/origin kontrol a DOM; PDF používá systémový Poppler deklarovaný v .deb. Kontrakt, limity a recovery: [ADR 0019](docs/adr/0019-main-panel-preview.md), [návod](docs/project-opening.md).

Ověření M1-AH-02: cílené API a skutečný WebEngine pro Markdown/PNG/PDF, klávesnicové přepínání, zachování draftu mezi záložkami, vymazání při změně projektu, neaktivní HTML, validace registrace/ID, stale/pending, čtení commitnutých bajtů, limity a chybné/nedostupné PDF. Vizuálně zkontrolováno skutečné okno 1100 × 800. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **123 testů OK, bez vynechání**, 74,043 s, včetně instalace/upgrade/odstranění a offline desktopu. Místní odkazy, syntaxe JS a `git diff --check` ověřeny. Omezení: vstup 4 MiB, Markdown 2000 odřádkování a omezené formátování, PDF stránky 1–100/raster 1200 px/timeout 15 s; není to sandbox PDF parseru, plné RBAC ani zapojený LLM chat. Zůstává v TODO do uzavření dávky M1.


- [x] [completed] **M1-AH-03 — Projektové karty a společný prompt (PoC validated, 2026-09-10).** Na požadavek uživatele úvod zobrazuje karty projektů s názvy/popisy a stručný seznam vlevo; otevřený projekt úvod skryje. Výběr artefaktu automaticky aktivuje náhled a označí položku. Prompt zůstává pod náhledem i chatem, psaní přepne na chat, Enter/tlačítko přidá lokální zadání bez volání backendu. Dole je návrat na seznam projektů, který vymaže projektový obsah/draft. Reuse/adapt Projects, Git, validátoru project.json a DOM; katalog čte bez inicializace indexu/journalu a zvládá nedostupné položky jednotlivě. Nativní editor přebírá skutečně otevřené ID. Kontrakt a hranice: [ADR 0019](docs/adr/0019-main-panel-preview.md), [návod](docs/project-opening.md).

Ověření M1-AH-03: cílené testy katalogu/projektů/náhledů a skutečný WebEngine, karty a stručný seznam, automatický chat při psaní, lokální přidání zadání, trvale viditelný prompt, klávesnicové záložky, návrat a znovuotevření, zachování a vymazání draftu, nedůvěryhodné názvy, autentizace a katalog bez zápisů. Obě obrazovky vizuálně ověřeny v okně 1100 × 800. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **124 testů OK, bez vynechání**, 76,158 s. Syntaxe JS, místní odkazy a `git diff --check` v pořádku. Chat/zadání zůstávají jen v paměti okna; LLM ani trvalý registr úkolů nejsou zapojené. Záznam zůstává v aktuální dávce.


- [x] [completed] **M1-AH-04 — Srozumitelné UI pro ukázku partnerům (PoC validated, 2026-09-10).** Požadavek uživatele: lidské popisky a vytvoření chybějícího hlavního seznamu úkolů z levého panelu. UI používá Úkoly, Podklady, Náhled, Chat a srozumitelné popisky editoru, historie i podrobností. Chybějící seznam nabízí Vytvořit seznam úkolů; otevře stávající nativní editor, dokument vznikne až uložením. Po uložení se přehled obnoví a tlačítko zmizí. Reuse/adapt EditorDialog a sidebaru; ukládání/recovery ADR 0016 beze změny, bez nového HTTP zápisu. [Kontrakt](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

Ověření M1-AH-04: cílených 32 testů OK, následně skutečné zahození návrhu přes potvrzovací dialog, opakované otevření, uložení jediného dokumentu a obnovení sidebaru. Vizuální kontrola levého panelu a editoru v Qt; existující/nepodporovaný seznam nenabízí vytvoření. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **125 testů OK, bez vynechání**, 83,027 s. Syntaxe JS, místní odkazy a `git diff --check` v pořádku. Úkol pro ukázku UI uzavřen v rozsahu lokálního PoC; asistent nadále neodpovídá a zadání nejsou trvale uložená. Gate M1 zůstává otevřený, záznam zůstává v TODO do uzavření dávky.


- [x] [completed] **M1-LC-01 — Compliance baseline a notices (implemented, 2026-09-10).** Dokončena integrace compliance patchu: přidané `THIRD_PARTY_NOTICES.md`, právní evidence pod `docs/legal/*` (`COMPLIANCE.md`, `LICENSE_SOURCES.md`, `DEPENDENCIES.toml`, `RELINKING.md`, `licenses/*`), nový `scripts/license_files.py`, a `tests/test_license_packaging.py`; úprava balicích skriptů pro zařazení povinných licenčních souborů do source i `.deb` distribuce. Ověření: `python3 -m unittest discover -s tests -p 'test_license_packaging.py' -v`, validace `git diff --check` po změnách, dokumentační vazby do `README.md` a `REUSE_CATALOG.md` podle zadání. Ověření plného regresního běhu po tomto commitu: `python3 -m unittest discover -s tests -v` -> selhalo (11 errors, 19 skipped, 114 passed) kvůli sandboxovým omezením síťových socketů/`socket` (PermissionError: Operation not permitted) u API lokálních testů; tyto chyby označují omezení prostředí, ne regresi aplikační logiky. Konkrétně `test_authentication*`, `test_framing*`, `test_same_contract*`, `test_stalled_client*`, `test_unix_peer_uid*`, `test_default_path_is_lazy_and_http_cannot_create`, `test_authenticated_api_and_no_filesystem_parameters`, `test_assets_do_not_bootstrap_token_and_api_still_requires_auth` a `test_real_api_auth_validation_and_no_path_access`. Ověřené i relevantní UI/paketizační testy: `test_deb_carries_notices...`, `test_contents_and_no_overwrite`, `test_source_archive_contains_all_legal_files_and_manifest`, `test_missing_notice_stops_deb_before_publishing` a `test_missing_license_stops_source_build` (závěr: pro compliance commit úspěšně ověřeno). Skippované testy označeny explicitně: Qt/WebEngine (`Requires real Qt/WebEngine`, `Requires real desktop`, `Requires actual sidebar tabs`) a instalační runtime (`Requires installed Debian runtime dependencies`) považuji jako neověřené v tomto prostředí. Testovaná revize: `HEAD`.

## K předání do backlogu

Doplnění k **V-11** při předání dávky: příští distribuční inventář musí zahrnout novou systémovou závislost `poppler-utils` pro PDF náhledy (M1-AH-02). Historické inventáře se nepřepisují; veřejný release zůstává samostatným úkolem.
## WF-01 — Přehledné aktuální okno práce — 2026-09-10

- [x] [completed] **WF-01 — Oddělení aktuální práce, backlogu a historie (implemented).** AGENTS vymezuje roadmapu pro milníky/gates, TODO pro nejvýše 5 bezprostředních úkolů, BACKLOG pro ostatní otevřenou práci a WORK_LOG pro dokončené výstupy a ověření. Úkol se přesouvá se stejným ID a kontextem; historie se nepřepisuje. Z původních 23 otevřených položek zůstává M1-05 v TODO a 22 v BACKLOG; všechny historické sekce byly zachovány beze změny důkazů. Opraveny odkazy a zastaralý aktuální milník v úvodu roadmapy na M1. Existující allowlist zdrojového balíčku byl rozšířen o oba nové dokumenty, včetně kontroly v manifest testu.

Ověření: automatické porovnání původních a přesunutých sekcí i všech otevřených položek, kontrola místních odkazů a finálního diffu. Cílené testy balíčku prošly (Qt v prvním běhu vynecháno); následně `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů OK, bez vynechání**, 62,380 s. `git diff --check` bez chyb. Tato změna nezahajuje M1-05 ani nemění aplikační chování či produkční připravenost.

<a id="gate-m0"></a>
## Závěrečné Gate review M0-09R

Posouzený HEAD `1efc6d3`, pracovní strom čistý. **Gate M0 splněn pro rozsah architecture spike; přechod do M1 je schválen.** Toto rozhodnutí nahrazuje předchozí negativní review, která zůstávají níže jako historie. Neprohlašuje produkční připravenost ani splnění Gate M1.

| Podmínka Gate M0 | Důkaz | Závěr |
| --- | --- | --- |
| Zaznamenaný stack podložený PoC | ADR 0013; srovnání Git ADR 0005, PySide/měření ADR 0010 | Splněno: Python, Git CLI/SQLite, PySide/WebEngine, Linux .deb. |
| Autoritativní schéma a obnova indexu | ADR 0002/0004, validátory a testy; M0-05 rebuild indexu na cíli | Splněno pro minimální schéma. |
| Koordinace a recovery | ADR 0003, Workspace testy a M0-05: všech 12 checkpointů na Omnia SSD | Splněno pro procesní pády ve vymezeném PoC. |
| Návrh bezpečného lokálního API | ADR 0006/0007/0010, token/origin policy, skutečné Qt okno | Splněno pro návrh a transportní PoC. |
| Konflikt entity a obsah/sidecar | M0-07, FEDERATION a test_merge_scenarios | Splněno včetně čistého sémanticky neplatného merge. |
| Orchestrace bez LLM a execution boundaries | ADR 0008, návrhové scénáře | Splněno jako designed; LLM/RBAC engine se nepředstírá. |
| Cílové prostředí a balení | ADR 0012 čistá instalace/offline/upgrade/purge; M0-05 ARMv7/Btrfs měření | Splněno jako PoC validated. |

Poslední plná sada má 73 úspěšných testů (důkaz u cílového probe); nový uživatelský výstup potvrzuje cílové ověření. V tomto dokumentačním review se testy neopakovaly. Ověřeny návaznost důkazů, odkazy a finální diff.

Otevřené V-01 až V-11 se nepřevádějí na hotové: V-08 a V-10 jsou integrační podmínky práce s projekty, V-04/V-05 podmínky rozšíření metadat/importu, V-06/V-07 produkční ochrany a V-11 veřejný release. Výpadek napájení, plné RBAC, síťová federace, LLM, kapacita velkých projektů ani další OS nejsou vstupními podmínkami M1 podle definice Gate M0. Jejich backlog zůstává zachovaný. Produkční HTTP server není schválen pouhým úspěchem loopback PoC.

- [x] [completed] **M1-01 — PoC validated: otevření existujícího projektu v desktopu.** Služba Projects ověřuje registraci v1, shodu commitnutého project.json, existující vlastněný root a soukromý state. Workspace vrací název, commit ID a artefakty pod společným zámkem; pending blokuje čtení, chybějící/stale index se obnovuje, neplatná projekce se nevydává za aktuální. Lokální API přijímá pouze registrovaná ID a zachovává token/Host/Origin ochrany. UI vykresluje názvy jako text a při změně výběru/chybě odstraňuje starý výsledek. Spuštění `./run.sh desktop --node SOUBOR` zachovává cesty vůči volajícímu. [Postup a izolovaná ukázka](docs/project-opening.md), [hranice recovery](docs/adr/0014-project-read.md).

  Ověření: plná sada s `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **83 testů úspěšně, bez skipů**. Nových deset testů pokrývá dva projekty/restart, ztrátu a stale index, nevalidní registraci/verzi/config, symlink/hardlink, pending, poškozenou projekci, změnu HEAD, přerušenou inicializaci a rollback indexace, autentizované HTTP, prázdný projekt, wrapper a skutečné Qt vykreslení HTML názvů jako textu. `bash -n run.sh` a `git diff --check` prošly. Nejde o produkční RBAC/Git sandbox ani nový cílový běh na Omnii. Balení a offline testy ověřují regresi původního smoke; nové projektové čtení má vlastní Qt test z checkoutu. Přesný příklad z návodu prošel skutečným desktopovým smoke; vizuálně ověřen název, commit a artefakt. Návod je zahrnut i v allowlistu zdrojového balíčku.

- [x] [completed] **M1-02 — PoC validated: vytvoření a registrace projektu z desktopu.** Nativní dialog přijímá název a neexistující cílovou složku; jeden worker připraví Git/project.json, lokální stav a index, atomicky publikuje registraci a otevře projekt. Bez `--node` používá výchozí XDG uzel, jehož konfigurace vzniká až při potvrzeném vytvoření. Uzlový SQLite journal drží stabilní ID/parametry/receipts, používá společný neblokující flock a při běžném restartu automaticky obnovuje pending vytvoření. Existující cíl, nesoulad konfigurace nebo cizí změna se nezahladí. HTTP zůstává pouze pro čtení; nativní mutující kontrakt a crash boundaries jsou v [ADR 0015](docs/adr/0015-project-creation.md). [Postup](docs/project-opening.md) a nápověda aktualizovány.

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **95 testů úspěšně, bez skipů**. Dvanáct nových testů pokrývá skutečné procesní pády na osmi hranicích, deterministickou obnovu prvního commitu, opakování ID/parametrů, dva projekty, busy/pending/timeout, zachování existujícího cíle a cizích změn, selhání atomického zápisu node.json, lazy default konfiguraci, odmítnutí mutace přes HTTP, skutečný Qt dialog a restart i automatickou obnovu/otevření při běžném startu GUI. Test nainstalovaného .deb nyní vytváří skutečný dočasný projekt a ověřuje jeho i node.json zachování po purge. Regresní offline start a předchozí storage crash testy prošly. `bash -n run.sh`, lokální odkazy a `git diff --check` ověřeny. Nejde o nové ověření na Omnii ani výpadek napájení.

- [x] [completed] **M1-03 — PoC validated: Markdown editor, checklisty a hlavní TODO projektu.** Nativní Qt dialog vytváří/upravuje Markdown document artefakty přes registrovaný Workspace; obsah/sidecar se commitují společně, existující frontmatter i metadata se zachovávají. Checklist panel mění značky přímo v Markdownu, hlavní TODO má rezervované stabilní UUIDv5 a vznikne až při prvním uložení. GUI drží operation ID při retry, Workspace váže požadavek na digest/receipt, kontroluje výchozí HEAD a používá neblokující zámek/deadline. Nativní otevření editoru dokončí pending journal; HTTP zůstává pro čtení. [Kontrakt a crash boundaries](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **105 testů úspěšně, bez skipů**. Deset nových testů ověřuje přesné Git bajty a metadata, hlavní TODO/rename, checklisty včetně Unicode a code fences, skutečný Qt dialog a opětovné otevření, ztracenou odpověď/retry, dvě souběžná vytvoření TODO, stale/busy/deadline, neplatné vstupy, cizí editaci, ztrátu indexu a skutečné procesní pády na 12 hranicích. Regresní testy desktopu, .deb a offline startu prošly; nové editování má vlastní Qt test z checkoutu, nejde o nový cílový běh na Omnii. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: 1 MiB těla dokumentu; rozepsaný neuložený text není trvalý draft, není implementovaný bohatý preview, automatické sloučení editací ani výpadek napájení. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03a — PoC validated: stromový přehled hlavního TODO v levém panelu.** Přehled zobrazuje uložené checklisty podle odsazení, stav dokončení a sbalitelné větve. Sdílí validovaný commit a zámek s přehledem projektu, bez mutací/recovery; nativní uložení využívá existující refresh. Starý výsledek se odstraní při změně projektu/načítání/chybě a opožděná odpověď se zahodí. Parser/čtení dokumentu sdílí editor a přehled přes `markdown_documents.py`. [Kontrakt](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **108 testů úspěšně, bez skipů**. Tři nové testy a rozšířený WebEngine smoke ověřují hierarchii/počet hotových položek, committed proti neuloženému obsahu, pending bez recovery, prázdný/nepodporovaný/velký TODO, readonly checkboxy, bezpečné texty, sbalení větví, vyčištění a opětovné načtení i restart. Vizuálně ověřen screenshot vlastního dočasného projektu. Regrese editoru, .deb a offline startu prošly. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. Limit přehledu je prvních 1000 položek s upozorněním; nadpisy nejsou stromové uzly a externí změny vyžadují nové otevření. Historie M1-04 nebyla zahájena.

- [x] [completed] **M1-04 — PoC validated: historie změn dokumentu.** Tlačítko Historie v editoru otevírá nativní readonly dialog s verzemi, datem/autorem/zprávou, původním Markdownem, metadaty a diffem uložených souborů. ArtifactHistory čte jen registrovaný projekt pod společným zámkem, kontroluje HEAD před/po čtení a odmítá pending bez recovery. Historické snapshoty validuje samostatně; neplatné verze zůstávají označené v seznamu. Full-history zachovává obě větve merge, diff nepouští externí drivery/textconv, draft se nemění. [ADR 0017](docs/adr/0017-artifact-history.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **116 testů úspěšně, bez skipů**. Osm nových testů pokrývá verze a diff checklistu/metadat, zachování HEAD/stagingu/journalu/indexu/draftů, unregistered/revspec/nedosažitelné revize, stale/busy/deadline/pending, historickou konfiguraci, invalidní snapshot, rename, obě větve merge, limit seznamu, smazání/recreate, zákaz externího diff driveru a skutečný Qt dialog se zachováním rozepsaného textu a vyčištěním výsledku po chybě. Vizuálně ověřen finální dialog nad vlastním dočasným projektem. Regrese .deb/offline/desktopu prošly; nový viewer má vlastní Qt test z checkoutu. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: nejvýše 100 záznamů a 1 MiB těla; bez revertu, prohlížeče nyní smazaných artefaktů nebo nového cílového ověření na Omnii. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03b — PoC validated: přepínání TODO a zdrojů/artefaktů v levém panelu.** Dvě readonly záložky používají společný snapshot otevřeného projektu. Seznam zahrnuje dokumenty i zdroje s názvem/ID. Přepínání kliknutím a šipkami/Home/End, zachovaná volba při refreshi a odstranění starých dat při přepnutí/chybě. Reuse existujícího seznamu artefaktů bez nového backendového endpointu nebo změn ukládání. [Návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů úspěšně, bez skipů**. Nový test skutečného WebEngine ověřuje PDF zdroj vedle dokumentu, prázdný projekt a neměnný HEAD; rozšířený smoke kontroluje obě záložky, klávesnici/fokus/ARIA, přesné názvy/ID jako text, zachování volby při refreshi a vyčištění obsahu. Vizuální kontrola vlastního dočasného projektu, odkazy, `bash -n run.sh` a `git diff --check` prošly. Volba záložky je pouze pro aktuální okno; po restartu začíná TODO. Seznam zatím neotevírá obsah zdrojů. Metadata M1-05 nebyla zahájena.

## Gate review M0-09 — 2026-09-09

Historické posouzení před následným ručním deployem; novější důkaz je uveden u M0-05 a v dokončených výstupech. Aktuální rozhodnutí drží závěrečné M0-09R výše.

Posouzený HEAD: `1c7b228`, vstupní pracovní strom čistý. Výsledek: **Gate M0 nesplněn; M1 nezahajovat automaticky.** Review je dokončené, schválení gate nikoli. Nezavádí se nové architektonické rozhodnutí ani změna priorit nasazení.

| Kritérium | Důkaz a úroveň | Závěr |
| --- | --- | --- |
| Autoritativní data a obnova indexu | ADR 0002–0004, metadata/configuration/storage a jejich testy; designed + PoC validated | Splněno pro rozsah M0; integrace konfigurace a úplnější projekce zbývají V-03/V-08. |
| Koordinovaná obnova zápisu | ADR 0003 a tests/test_workspace.py: crash boundaries, CAS, pending stav, dva zapisovatelé | Splněno pro řízený Linux PoC; ne důkaz produkčního hardeningu nebo výpadku napájení. |
| Bezpečné lokální API a desktopové propojení | ADR 0006/0007, tests/test_local_api.py a tests/test_desktop.py | Návrh a PoC splněny; persistentní operace a nedůvěryhodný obsah zbývají V-10. |
| Konflikty entity a obsah/sidecar | M0-07, tests/test_merge_scenarios.py a FEDERATION | PoC splněno včetně sémanticky neplatného čistého merge; conflict UI a síťová federace nejsou implementované. |
| Orchestrace bez LLM, role, manifest, execution boundaries | ADR 0008 a návrhová tabulka scénářů | Designed splněno; LLM/RBAC implementace se neprohlašuje za hotovou. |
| Finální stack a distribuční cesta | ADR 0005 volí Git CLI; ADR 0007 pouze PoC binding; M0-06b zdrojový archiv | **Nesplněno:** finální backendový stack/binding a distribuční posouzení M0-06 zůstávají otevřené. |
| Cílové prostředí a provozní měření | M0-05 doložený LXC bez běhu aplikace; desktopové testy na vývojovém hostu | **Nesplněno:** měření na Omnia/ARMv7 a úplné posouzení startu, paměti a instalace cílových variant. |

Uživatel následně potvrdil úspěch ruční akceptace desktopu: kliknutí, zavření a restart fungují. Současné UI obsahuje jen paměťový čítač; nelze v něm ještě otevřít projekt, uložit artefakt ani ověřit zachování projektových dat po restartu. Ruční akceptace: třikrát „Ověřit spojení“ → 1/2/3, zavření → návrat terminálu, nový `./run.sh desktop` → 0 a opět funkční tlačítko. Výsledek je uživatelské potvrzení, nikoli nový automatický test.

Evidence testů je převzatá z dokončených úkolů níže (poslední plná sada u M0-07), nikoli nový běh v tomto review. Zkontrolovány současné zdroje UI, pokrytí testů, návaznost ADR a gate. Dokumentační ověření: lokální odkazy a finální diff. Po doplnění M0-05/M0-06 zopakovat rozhodnutí o gate s novými důkazy; dnešní negativní výsledek zachovat jako historii. Samotné potvrzení čítače gate neuzavře.

## Aktualizované posouzení M0 po instalaci .deb

Historické posouzení před offline testem; novější důkaz je níže v dokončených výstupech.

Posouzený HEAD `2b0adf2`, vstupní pracovní strom čistý. Historický review výše se nepřepisuje. Nové důkazy: PySide6 skutečné okno, měření desktopu a renderer crash (ADR 0010), instalační balík s izolovaným dpkg lifecycle (ADR 0011), uživatelsky potvrzené instalované GUI na Ubuntu arm64 a v Debian kontejneru x86_64 pod běžným uživatelem, headless Omnia demo na SSD. Poslední plná sada je u balíku: 69 testů, v tomto dokumentačním review nebyla opakována.

[Inventář kandidáta](docs/adr/0011-runtime-inventory.md) obsahuje SHA-256 balíku, přibalených souborů a distribučních copyright souborů 229 systémových závislostí na vývojovém hostu. Je úplný pro popsaný průchod Depends/Pre-Depends, nikoli univerzální SBOM všech platforem nebo hotový licenční audit. Uživatelův Debian má vlastní doložené verze; inventář Ubuntu se na něj nepřenáší.

**Výsledek: Gate M0 zůstává otevřený.** Podklady pro Python/Git/SQLite + PySide a .deb výrazně pokročily; funkční instalace neznamená finální schválení produkčního stacku. M0-06e zbývá izolovaný offline start a doložení čistého OS bez checkoutu/testovací vrstvy, M0-05 cílová provozní měření. Před zveřejněním balíku navíc zbývá skutečný maintainer kontakt, licenční posouzení a způsob aktualizací.

Uživatel přesměrovává X11 přes síť; odpojení jeho kontejneru by přerušilo i displej a nebylo by vhodným testem aplikace. Offline ověření zůstává planned, nikoli tvrzené jako úspěch ani obecně blocked. **Nejbližší konkrétní krok:** připravit lokální grafický smoke v oddělené síťové konfiguraci se zachovaným loopbackem a lokálním displejem, bez zásahu do uživatelova X11 spojení. Akceptace: žádná externí konektivita, funkční čítač, zavření/restart; zaznamenat způsob izolace a závislosti. V této změně se tento experiment nespouští.

## Dokončené výstupy a důkazy

- [x] [completed] **M0-09R — Designed: závěrečné Gate review.** Podmínky Gate M0 splněny podle tabulky výše; přechod do M1 schválen. První implementační úkol M1-01 vymezen bez zahájení implementace. Produkční omezení a historické negativní review zachovány.

- [x] [completed] **M0-05 — PoC validated: cílový běh a recovery na Omnii SSD.** Uživatel doložil `spikes.target_probe` s výsledkem PASS: Btrfs, armv7l, Python 3.13.5, SQLite 3.46.1, Git 2.47.3. Navazuje na potvrzený Debian LXC a SSD /dev/sda; pracovní adresář /var/tmp/workspace-poc. Všech 15 případů má verified=true: tři normální běhy a 12 pádů vlastního workeru. Probe ověřil pending čtení, zachování kandidáta, přesné bajty, jediný commit operace, idempotenci recovery, rebuild smazaného indexu a úklid dočasných dat. Jde o uživatelský cílový výstup, nikoli nový běh celé unittest sady. Původní demo 0,66 s běželo na tmpfs a nemíchá se s novými SSD měřeními.

  | Normální běh | Celý worker (s) | Apply (s) | Python peak RSS (KiB) |
  | --- | --- | --- | --- |
  | 1 | 0,8741 | 0,489111 | 11392 |
  | 2 | 0,8749 | 0,487234 | 11648 |
  | 3 | 0,8655 | 0,481006 | 11648 |

  | Hranice přerušení | Recovery (s) |
  | --- | --- |
  | prepared | 0,4496 |
  | file:0 | 0,4446 |
  | file:1 | 0,4455 |
  | applied | 0,4472 |
  | files-applied | 0,4243 |
  | commit-created | 0,4261 |
  | commit-ready | 0,2838 |
  | ref-updated | 0,2765 |
  | committed | 0,2620 |
  | git-indexed | 0,2606 |
  | indexed | 0,2758 |
  | completed | 0,0011 |

  `process_s` zahrnuje start Pythonu a inicializaci Git projektu, nikoli start serverové služby; RSS patří Python workeru, ne celému kontejneru/Git potomkům. Normální recover bez pending operace trval 0,0010–0,0011 s. Pád procesu na checkpointu není výpadek napájení ani pád uvnitř libovolného syscallu. Malá fixture není kapacitní benchmark. Úroveň je PoC validated pro zvolený stack; další produkční hardening drží V-06/V-07. Ověřena konzistence dodaných hodnot, odkazy a diff; Gate M0 čeká na review M0-09R.

- [x] [completed] **Implemented — cílový probe pro M0-05.** `spikes.target_probe` přenáší stávající crash scénáře do ručního deploye, vyžaduje explicitní základ a očekávaný filesystem, měří tři normální běhy a ověřuje 12 pádů workeru, obnovu a přesné bajty bez duplicitního commitu. Při úspěchu uklidí jen vlastní data, při selhání je ponechá. Lokální regresní testy pokrývají skutečné pády, chybný filesystem bez zápisu a zachování diagnostiky. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 73 testů prošlo bez skipů. Ověřeny odkazy a finální diff. Skutečný běh na Omnia SSD zatím neproběhl v této změně, M0-05 zůstává otevřený.

- [x] [completed] **M0-06 — Designed: stack pro M1 uzavřen.** [ADR 0013](docs/adr/0013-m1-stack.md) přijímá Python, Git CLI, oddělené SQLite index/journal, PySide6/WebEngine, same-origin UI a linuxový .deb na základě již ověřených PoC. C++ port/hybrid není potřeba bez doloženého problému. Rozlišena volba technologií od produkčního HTTP serveru, release a cílových měření M0-05; gate zůstává otevřený. Ověřena návaznost ADR, odkazy a diff, bez nového běhu testů.

- [x] [completed] **M0-06e — PoC validated: instalační kandidát v čistém OS.** [ADR 0012](docs/adr/0012-clean-os-validation.md) dokládá nový oficiální Ubuntu 26.04 arm64 kontejner, skutečné stažení a vyřešení APT závislostí bez doporučených balíků, instalovaný launcher pod běžným uživatelem přes interní Xvfb, dva offline starty a upgrade/purge se zachováním kontrolních projektových/stavových souborů. Není použit checkout ani runtime hostitele. Dpkg audit čistý; runtime verze, velikosti, image digest a .deb hash zaznamenány. Kontejner odstraněn. Bez změny kódu a nového běhu celé unittest sady; provedeny skutečné instalační/grafické experimenty, kontrola odkazů a diffu. Inventář kandidáta drží ADR 0011; licenční posouzení veřejného releasu není tímto uzavřeno.

- [x] [completed] **PoC validated — offline grafický běh .deb.** `tests/test_desktop_offline.py` vytváří samostatný user/network namespace s pouze aktivním loopbackem; ověřuje namespace ID, nulové capabilities aplikace, nepřítomnost tras a odmítnutí externího TCP bez trasy. Lokální X11 socket zajišťuje skutečné okno, dva běhy ověřují kliknutí, zavření backendu a restart rozbaleného .deb. Hostitelská síť ani uživatelovo přesměrování X11 se nemění. Metoda a limity v ADR 0011; nejde o čistý OS ani obecný bezpečnostní sandbox. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 70 testů prošlo bez skipů. Odkazy a finální diff ověřeny.

- [x] [completed] **Designed — distribuční inventář a aktualizované M0 review.** Inventarizován konkrétní .deb a místní runtime, doplněny důkazy uživatelské instalace a omezení přesměrovaného X11. Rozhodnutí o gate zůstává otevřené; odkazy, shoda hashů a diff ověřeny, bez nového běhu aplikačních testů.

- [x] [completed] **Implemented — evidence uživatelského ověření .deb na druhém prostředí.** Uživatel hlásí funkční aplikaci v kontejneru; dodané os-release uvádí Debian GNU/Linux 13 Trixie 13.6, uname x86_64. Dpkg-query uvádí federated-workspace-poc 0.1.0~m0, python3 3.14.7-3, python3-pyside6.qtwebenginewidgets 6.8.2.1-4 a python3-yaml 6.0.3-1+b1. Jde o konkrétní uživatelské prostředí, nikoli automaticky standardní čistý Debian nebo obecnou podporu amd64. Původ balíků a offline start nejsou doloženy. Uživatel upřesnil spuštění instalovaného launcheru přes sudo -u user federated-workspace-poc: grafické okno tedy běželo pod běžným uživatelem, nikoli rootem. Funkčnost okna je uživatelsky potvrzená; diagnostický výpis pocházel z root shellu. Zaznamenání evidence neuzavírá M0-06e ani gate; bez nového běhu testů, ověřena konzistence a diff.

- [x] [completed] **Implemented / PoC validated — .deb kandidát a izolovaný dpkg lifecycle (část M0-06e).** `run.sh package-deb`, builder, launcher a desktop entry používají systémové závislosti bez instalace za běhu. Ověřeny obsah, nepřepsání výstupu, chybějící závislosti, upgrade/purge se zachováním kontrolních dat a skutečné instalované okno. Rozsah a předem popsané crash boundaries v ADR 0011; čistý OS test zůstává otevřený. Závěrečné `M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 69 testů prošlo bez skipů. Ověřen výsledný .deb, shellová syntaxe, odkazy a finální diff.

- [x] [completed] **M0-06d — PoC validated: PySide6/WebEngine a měření desktopu.** Desktop i launcher používají PySide6 bez fallbacku na PyQt, shiboken6 zajišťuje pořadí destrukce objektů. Skutečný click/close/restart, pád rendereru a rozbalený zdrojový balík ověřeny. `PYTHONPATH=/tmp/m0-pyside M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 67 testů prošlo bez skipů. Ověřen launcher z /tmp a SIGTERM, bash syntax a help. Tři měřené běhy a omezení RSS/loadFinished jsou v [ADR 0010](docs/adr/0010-pyside-desktop-validation.md). Runtime moduly byly rozbaleny do /tmp, běžný uživatel je musí připravit dle README; čistá instalace zůstává M0-06e. Dokumentace, lokální odkazy a finální diff zkontrolovány.

- [x] [completed] **M0-06c — Designed: posouzení bindingu a distribuce.** [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md) porovnává PyQt/PySide, zachování Python jádra a instalační varianty. Ověřeny oficiální licenční podklady, místní Qt/PyQt importy a apt kandidáti chybějících PySide WebEngine modulů. Doporučení PySide/.deb je podmíněné skutečným runtime a instalačním ověřením M0-06d/e. Žádná instalace ani změna kódu; dokumentační kontrola konzistence, odkazů a diffu, bez nového běhu testové sady.

- [x] [completed] **PoC validated — ruční deploy a storage demo na Omnii.** Uživatelem dodaný výstup potvrzuje instalaci PyYAML 6.0.3, vytvoření artefaktu a Git historie, index po znovuotevření, úklid dočasných dat a hlášku úspěšné instalace do current. Daemon se nespustil. Jde o úspěšný smoke běh, nikoli celou testovou sadu nebo recovery na cílovém zařízení. Následné orientační měření uživatele: celé demo 0,66 s, max RSS potomků 11 520 KiB, exit 0; podrobnosti a omezení u M0-05. Měřený běh používal /tmp na tmpfs. Další uživatelský výstup potvrzuje úspěšný neměřený běh s TMPDIR=/var/tmp/workspace-poc na /dev/sda/Btrfs, včetně indexu po znovuotevření a úklidu. Nejde o restart kontejneru ani test pádu. Zbývající ověření drží M0-05; desktopové připojení k serveru zatím neexistuje.

- [x] [completed] **M0-09 — Designed: Gate review před M1.** Kritéria, podklady a negativní rozhodnutí jsou v sekci Gate review výše. M0-05/M0-06 zůstávají otevřené; dokončení review neznamená splnění gate. Bez nového běhu testů a bez vzdáleného nasazení.

- [x] [completed] **M0-08 — Designed: kontrakty a pravidla publikace.** [ADR 0008](docs/adr/0008-context-and-publication-contracts.md) vymezuje Backend/Role/Context Manifest, přesné vstupy a cíl, autorizaci před odesláním, fallback, nejistý výsledek síťového volání a CAS publikaci při změně HEAD. Návrhové review scénářů zahrnuje uzel bez LLM, Ollamu, cloud, peer, local-only i zakázaný obsah v Git historii. Ověřena konzistence s ADR 0003/0004, roadmapou a odkazy; čistě dokumentační změna bez nového běhu testů. Implementace a akceptační scénáře navazují v M1–M5/V-10 a M3-UB-01; Gate M0 zůstává otevřený.

- [x] [completed] **M0-07 — PoC validated: zbývající merge scénáře.** `tests/test_merge_scenarios.py` ověřuje modify/delete s abortem a obnovou úplného páru obsah/sidecar, rename/edit s přesnými bajty a metadaty a textově čistý merge dvou validních větví s dangling relation. Validace kandidáta odmítne publikaci; úmyslně neplatný commit v negativním testu nenahradí index a čtení odmítne stale stav. Ověřena lidská oprava a rodiče merge; scénáře a limity jsou ve FEDERATION. Produkční synchronizace ani conflict UI nevznikají. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 66 testů prošlo bez skipů. Ověřeny lokální odkazy a finální diff.
- [x] [completed] **V-02 — PoC validated: přesný důvod odmítnutí duplicity indexem.** Existující test ve `tests/test_storage.py` nyní vytváří platnou Markdown entitu se stejným ID jako registr a vyžaduje chybu Duplicate ID; zachování indexu a odmítnutí stale čtení zůstává ověřeno. Původní nesoulad názvu JSON souboru již výsledek nezastíní.

- [x] [completed] **M0-06b — Implemented: reprodukovatelný zdrojový desktopový balíček.** `run.sh package-desktop` vytváří allowlistovaný tar.gz s manifestem SHA256, bez privátního katalogu, prostředí a binárních závislostí. Atomické zveřejnění kompletního souboru bez přepsání existujícího vydání; ověření rozbalené kopie je součástí grafických testů. Systémový runtime stále vyžaduje Python/Qt/PyYAML; finální binding, distribuční licence, instalační balík a M0-05 zůstávají otevřené. Závěrečná sada `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 63 testů prošlo bez skipů, včetně skutečného WebEngine z rozbaleného archivu mimo checkout. Bash syntax, lokální odkazy, finální diff a sestavení archivu ověřeny.

- [x] [completed] **Implemented — ruční deploy headless PoC na Omnii.** `run.sh deploy-omnia` poskytuje dry-run a explicitní SSH nasazení do běžícího Debian LXC na SSD, omezený archiv zdrojů, oddělená vydání a přepnutí current až po demu. Lokální testy ověřují obsah archivu, validaci vstupů, chyby SSH a zachování previous/current po chybě instalace. Závěrečná sada s `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1`: 60 testů prošlo bez skipů; bash syntax, dry-run, odkazy a diff ověřeny. Vzdálený deploy nebyl spuštěn; uživatel jej provede ručně, M0-05 zůstává otevřené.

- [x] [completed] **Designed — rozsah importu Drive, NotebookLM a konverzací.** Doplněna sekce 3C roadmapy a IMP-01 až IMP-03. Ověřeny oficiální podklady k dílčím API/exportům, lokální odkazy a diff. Konektory, autentizace ani parsery exportů nejsou implementované; žádná uživatelská cloudová data nebyla načtena.

- [x] [completed] **M0-06a — PoC validated: spustitelné desktopové okno.** `./run.sh desktop`, `spikes/desktop.py` a `desktop_ui.py` adaptují existující lokální API; Qt okno používá stejný Python proces s backendovým vláknem, token pouze v nativní části a off-the-record WebEngine. Skutečné UI/JS kliknutí ověřuje autentizované API a zavření backendu; nový start resetuje čítač. [ADR 0007](docs/adr/0007-desktop-poc.md) vymezuje změnu pořadí na žádost uživatele a otevřené produkční balení/licence i M0-05. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 56 testů prošlo bez skipů. Ověřeno vykreslené okno ze screenshotu, `bash -n run.sh`, help/chybné argumenty a skutečný launcher z /tmp včetně SIGTERM. Kontrola odkazů, soukromých údajů a diffu dokončena.

- [x] [completed] **M0-04 — PoC validated: lokální socket a loopback HTTP.** `spikes/local_api.py` a sedm testů v `tests/test_local_api.py` porovnávají stejný paměťový endpoint přes Unix socket a IPv4 loopback. Ověřeny token/rotace, Host/Origin, CSRF formáty/metody, UID/práva, limity/duplicity JSON a hlaviček, timeout a pipelining; odmítnuté požadavky nemění stav. [ADR 0006](docs/adr/0006-local-api-transport.md) preferuje same-origin loopback HTTP pro navazující UI, s Unix alternativou. Browser/obal, bootstrap tokenu a napojení Workspace zůstávají V-10. Závěrečné `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 53 testů prošlo bez skipů. Sandbox původně odmítl bind; běh s povolenými lokálními sockety uspěl. Dokumentace, odkazy a `git diff --check` ověřeny.

- [x] [completed] **R-00 — Implemented: oddělený veřejný a soukromý reuse katalog.** REUSE_CATALOG obsahuje technologie a komponenty workspace; seznam veřejných externích repozitářů je zatím prázdný. Lokální inventura je v `REUSE_CATALOG.private.md`, vyloučeném z Gitu. Ověřeny odkazy, absence soukromých detailů ve změněných veřejných dokumentech, ignore pravidlo a diff; bez nového běhu aplikačních testů. Detailní posouzení před převzetím zůstává R-01.

- [x] [completed] **M0-03 — PoC validated: Git CLI vs. C++/libgit2.** `spikes/libgit2/probe.cpp` sestaven s C++17 a `-Wall -Wextra -Werror` proti libgit2 1.9.1. `tests/test_git_comparison.py` spouští obě varianty nad stejnými scénáři commit/branch/clone/fetch, divergence/abort/merge, CAS a restart před/po publikaci, odmítnutí neplatné projekce a loopback HTTP autentizace. Finální `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 46 testů prošlo bez skipů. HTTP test vyžaduje povolený loopback socket; bez explicitních voleb jsou srovnávací testy skipped. [ADR 0005](docs/adr/0005-git-adapter-comparison.md) zachovává Git CLI jako výchozí adapter; libgit2 je ověřená alternativa, ne produkční náhrada Workspace. Zaznamenány build/runtime závislosti a orientační velikosti/start; cílové balení M0-05/M0-06 a produkční transporty V-09 zbývají. Hlavičky byly pouze rozbaleny do /tmp; systém ani produkční stack nebyly změněny.

- [x] [completed] **M0-02 — PoC validated: minimální project.json a konfigurace uzlu.** `spikes/configuration.py` a read-only `check_config`/`run.sh config` validují přenositelný projekt, lokální uzel, stabilní UUID, verzi v1, nepřekrývající se lokální cesty a opaque credential reference. Sdíleny parserové limity a UUID/timestamp pravidla; neznámé verze se odmítají bez migrace. Kontrakt a budoucí explicitní migrační pravidla: [ADR 0004](docs/adr/0004-project-node-config.md), příklady v DATA_MODEL. Deset nových testů konfigurace pokrývá i chybové cesty a read-only CLI. `python3 -m unittest discover -s tests -v`: 42 testů prošlo; `bash -n run.sh` a kontrola dokumentovaných příkladů/odkazů prošly. Zapojení konfigurace do aplikačního lifecycle, ověření identity/vaultu a migrační zápis zbývají V-08; distribuce uživatelů není implementována.

- [x] [completed] **Implemented — shellový launcher storage PoC.** `run.sh` poskytuje výchozí dočasné demo, explicitní setup do `.venv`, test, check a help; `spikes/demo.py` používá existující Workspace/Git a lifecycle podle ADR 0003. Ověřeno demo, `bash -n`, spuštění z cizího adresáře, relativní cesta s mezerami, chyby argumentů a neplatný/chybějící projekt bez zápisu. Přes `./run.sh test` prošlo 32 testů. Síťová instalace `setup` nebyla v tomto běhu provedena. Launcher není UI/server; běžná aplikace a balení zůstávají v M1.

- [x] [completed] **Implemented — optimalizace projektových instrukcí AGENTS.md.** Rozlišeno čtení pro návrh, dokumentaci a implementaci; doplněno opětovné použití nezměněných podkladů, pravidlo „další úkol“, aktualizace TODO po uceleném výsledku a evidence ověření bez duplikace počtů testů. Crash boundaries přesunuty před implementaci, zpřesněno cílené a závěrečné ověření. Architektonické mantinely, LLM workflow a pravidla commitů zachovány. Ověřena konzistence, lokální odkazy a diff; čistě dokumentační změna bez nového běhu testů.

- [x] **[completed] M0-01 — Jedna koordinovaná operace journal → validace → Git commit → index.**
  **PoC validated:** `spikes/workspace.py` adaptuje Journal/Git/Index a poskytuje apply/recover/read/receipt. Společný zámek, trvalé UUID a kandidátní commit před compare-and-swap posunem větve, blokované čtení pending operace a dokončený receipt. `tests/test_workspace.py`: 13 nových testů, včetně skutečných pádů procesu a dvou zapisovatelů; celkem 32 testů prošlo. Podrobnosti: [ADR 0003](docs/adr/0003-coordinated-operation.md). Původní akceptační požadavky:

  Operace musí mít stabilní `operation_id` a explicitní stavový životní cyklus. Minimálně musí být možné po restartu rozlišit:

  `prepared → files-applied → committed → indexed`

  Implementace nemusí použít přesně tyto názvy, ale stav musí být obnovitelný bez odhadu podle neúplných vedlejších efektů.

  Journal / operation record nesmí být definitivně odstraněn pouze proto, že byly úspěšně zapsány soubory. Musí zůstat dost informace k rozpoznání, zda příslušný Git commit již vznikl a zda byl index aktualizován.

  Operace eviduje minimálně:

  - operation ID,
  - výchozí HEAD,
  - zamýšlené změněné cesty,
  - stav operace,
  - po commitu výsledný commit ID.

  Recovery musí být idempotentní: opakovaný restart nesmí vytvořit další commit stejné operace.

  Git commit nesmí používat neomezené `git add --all`. Musí commitnout pouze cesty vlastněné aktuální operací, nebo operaci bezpečně odmítnout, pokud nelze oddělit cizí změny.

  Před commitem ověřit, že HEAD stále odpovídá výchozímu HEAD operace. Změna HEAD během operace nesmí být tiše přepsána.

  Akceptace: zámek pokrývá celý životní cyklus, pending stav brání publikaci neúplného projektu; commit obsahuje pouze zamýšlené změny a explicitního autora; restart po zápisu/před commitem i po commitu/před indexací neztratí změny ani nevytvoří duplicitní commit. Ověřit změnu HEAD, cizí rozpracované změny, opakovanou obnovu a dva kooperující zapisovatele. Původní podklad: ADR 0002; samostatný `Git.commit` zůstává testovacím helperem s `add --all`. Workspace jej nepoužívá a drží journal až do indexace. Limity: existující commit a běžná větev, čistý vstup, kooperující procesy se společným stavovým adresářem; ne produkční aplikace.

- [x] [completed] **IP-00 — Implemented: dokumentační integrace IP roadmapy.** Zachována podpůrná roadmapa v `docs/IP`, založeny PATENT_RISK_REGISTER a DEFENSIVE_DISCLOSURES s neověřeným watchlistem a rezervovanými DD náměty; propojeny master roadmapa, README a CONTRIBUTING. Zohledněna existující MPL-2.0. Ověřeny lokální odkazy, věcná konzistence a diff; patentová rešerše, publikace, DOI a crowdfunding zůstávají neprovedené.

- [x] **[completed] Designed — základní návrhy a kostra experimentů.** ARCHITECTURE, DATA_MODEL, FEDERATION, SECURITY, REUSE_CATALOG a ADR 0001/0002 existují; aplikační skeleton, síť ani UI tím nejsou hotové.
- [x] **[completed] PoC validated — Git divergence a historie.** `tests/test_storage.py`: dvě lokální repo kopie, tři konfliktní verze, abort, merge se dvěma rodiči. Žádná síťová federace/autentizace.
- [x] **[completed] PoC validated — validace artefaktů a registrů.** `spikes/metadata.py`, `tests/test_metadata.py`: schéma, UUID, JSON/YAML duplicity, limity, frontmatter, sidecar a vztahy.
- [x] **[completed] PoC validated — SQLite index.** `spikes/storage.py`, `tests/test_storage.py`: validovaný commit, stale detection, obnova z HEAD i po odstranění databáze, oddělení necommitnutých změn.
- [x] **[completed] PoC validated — souborový journal.** `spikes/journal.py`, `tests/test_journal.py`: vytvoření, přejmenování, smazání, přerušená obnova, cizí editace, zachování binárních bajtů a návazný ručně koordinovaný commit/index. Testy používají skutečné `os._exit` v pomocném procesu.
- [x] **[completed] Implemented, ručně ověřeno — CLI validátor projekce.** `spikes/check_project.py`; důkaz smoke testu v ADR 0002, automatizace zbývá V-01.
- [x] **[completed] Implemented — vývojový workflow.** AGENTS.md, tento TODO a reconciliace roadmapy vůči kódu; architektura, ADR a experimenty zachovány.

## Posouzení repozitáře k 2026-09-09

Výchozí HEAD posouzení: `71424f2`; pracovní strom byl čistý. Přečteny dokumenty, oba ADR, všechny spikes a testy. Opětovně spuštěno `python3 -m unittest discover -s tests -v`: **19 testů prošlo** na současném vývojovém hostu. Repozitář neobsahuje nakonfigurovaný build/lint/CI. Přehled neprohlašuje produkční připravenost.

Rozpory a opravy stavu: nezaškrtnuté frontmatter/sidecar, index a definice metadat v roadmapě jsou nyní výslovně PoC validated; původní operativní seznam sekce 19 je převeden sem. Návrhové body backendu, federace, desktopu a bezpečnosti jsou designed, ne implementované. Katalog SQLite nyní zahrnuje i lokální autoritativní journal, což nemění rozhodnutí o neautoritativním projektovém indexu. Věcné otevřené mezery metadat, indexu a testových důkazů jsou V-01 až V-06. Historické počty testů v ADR 0001/0002 zachovávají význam výsledků jednotlivých experimentů.
