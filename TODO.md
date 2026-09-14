<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-INDEX-01: Relační projekce projektového indexu

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-INDEX-01 — Relační projekce projektového indexu

- Stav: [x] [completed]; milník M1; lokální PoC validated. Výstup ověřen, dávka čeká na předání a sloučení PR do `develop`.
- Původ: V-03 a zbývající integrace metadat/indexu M1; ADR 0002/0003.
- Větev: `feature/f-m1-index-01-relations`, založena 2026-09-14 z lokálního `develop` (`0849ec8`). Dokumentační předání importní dávky bylo před implementací commitnuto (`54a2d39`). Cíl jediného PR: `develop`; PR zatím nevytvořen; implementace a ověření dokončeny, commit/push/merge v tomto běhu neprovedeny.
- Výstup: doložený kontrakt a implementace lokálně obnovitelné projekce vztahů/metadat, nesoucí přesný commit ID.
- Mimo rozsah: změna Git autority, synchronizace SQLite, nové LLM/RAG databáze.
- Závislosti: stabilní metadata kontrakt v `develop`; importní změny pouze pokud jej ovlivní.
- Akceptace jednoho PR: rebuild z HEAD, stale/pending odmítnutí, referenční integrita a změny po rename/delete/import, bezpečná migrace projekce, testy a dokumentace.

### Úkoly a ověření

- [x] [completed] **F-M1-INDEX-01 / V-03 — Relační projekce (PoC validated, 2026-09-14).** Index ukládá všechna validovaná metadata v1 artefaktů a registrů, cestu obsahu/registry, štítky a směrované vztahy vázané na přesný commit ID. FK, pořadí i duplicity se zachovávají; příchozí/odchozí dotazy filtrují explicitní hrany. Atomická migrace/rebuild, stale/pending odmítnutí a recovery po procesních přerušeních ověřeny. Native import, editace metadat, rename/delete a rebuild chybějící DB ověřeny; skutečný desktop, HTTP/backend, balení a offline běžely v celé sadě. Kontrakt: [ADR 0022](docs/adr/0022-relational-index.md).

V-03 — Vyjasnit omezení projekce indexu — je součástí této feature; jeho aktuální stav je zde. Výchozí index validoval vztahy, ale ukládal pouze id/title a commit ID. Rozšíření nyní pokrývá úplná validovaná metadata v1 artefaktů/registrů a explicitní vztahy; nejde o univerzální grafovou DB, další schémata ani produkční nasazení. Git zůstává autoritou, SQLite index je obnovitelná lokální projekce a není journalem rozpracovaných operací.

## Kontrakt před implementací — 2026-09-14

Adapt/reuse současného Index/Workspace, validátoru metadat a stdlib SQLite; nový storage framework ani externí kód nejsou potřeba. Soukromá inventura neposkytuje důvod nahrazovat tuto koordinaci. Git schéma se nemění; projekce zachová metadata včetně absence volitelných polí, cestu obsahu/registru, pořadí štítků a směrovaných vztahů i duplicity. Validátor dovoluje neprázdné vlastní typy vztahů; index je nezpřísní ani nedoplní inverzní vazby. Pole note není součástí spustitelného v1 schématu a index je nezavádí.

Crash boundaries ADR 0003 zůstávají platné. Rozšíření: migrace staré projekce a výměna entit/štítků/vztahů/commit ID proběhne v jedné explicitní SQLite transakci; pád před potvrzením ji vrátí, po potvrzení lze rebuild opakovat. Stará projekce se nepublikuje jako aktuální; neznámá budoucí verze se odmítne bez přepsání. Journal, Git commit, soubory a receipt se migrací nemění. Při pending stavu aplikační čtení odmítá data; samostatný Index journal nezná. Čtení kontroluje HEAD před i po SQL dotazu. Výpadek napájení a nekooperující FS/Git útočník zůstávají mimo PoC.

## Průběžné ověření — 2026-09-14

- `python3 -m unittest tests.test_index_projection tests.test_storage tests.test_workspace -v`: 25 testů prošlo, bez skip a chyb (8,915 s). Nových osm regresních testů pokrývá projekci všech v1 metadat, frontmatter/sidecar/registry, FK a příchozí/odchozí dotazy, vlastní typy/duplicity/pořadí, neplatný Git snapshot, drift HEAD při rebuild i čtení, migraci staré DB a odmítnutí budoucí verze, SQL čtenáře během výměny a 15 procesních přerušení (pět checkpointů při migraci, rebuild i Workspace recovery).
- Integrační native služby: import přesných CRLF/frontmatter bajtů, privacy local-only, změna popisu/štítků, rename bez změny vazeb, blokované odstranění při příchozí vazbě, následné odstranění a rebuild chybějící DB. Projektový přehled odmítne nesoulad projekce metadat/vztahů/štítků s validovaným commitem.
- První celá sada se zapnutým desktopem/balením/offline: 194 testů, šest UI selhání a jedna chyba vyčerpaného HEAD mocku, čtyři libgit2 skip (158,763 s). Příčiny odstraněny a ověřeny závěrečným během níže. Cílové LXC/router ani uživatelské projekty nejsou měněny; bez měření cílového výkonu, bez dokončení V-04/V-05 a bez uzavření Gate M1.

- [x] [completed] **F-M1-INDEX-AH-01 — Obnovit platnost skutečného desktop smoke při závěrečné akceptaci (PoC validated, 2026-09-14).** Původ: úplný běh odhalil timeouty v projektových smoke scénářích; historický globální selektor select odmítal i skryté administrační formuláře přítomné už v HEAD a sidebar test injektoval JavaScript do starých assets. Rozsah: omezit smoke kontrolu na projektový katalog/levý výběr projektu a připojit sidebar test k aktuálním desktopovým assets. Podmínka dokončení: všech šest dotčených WebEngine scénářů a následná celá sada. Nejde o samostatnou UI feature.

Doplnění crash/migrační ochrany: constructor odmítá i neznámé legacy tabulky/sloupce bez přidání indexových tabulek, včetně DB s operations; journal se nesmí inicializovat jako index. Cílený běh po této úpravě: 26 testů, bez chyb/skip (9,439 s). Pořadí volání HEAD v legacy testu bylo nahrazeno trvající změnou HEAD; projektový read při driftu odmítne reindexaci jiného snapshotu.

Cílené UI re-testy po opravách: tři scénáře náhledu/projektového přehledu/záložek prošly (22,646 s); další tři scénáře readonly TODO stromu, create/reopen a sidebar cancel/save prošly (17,421 s). Závěrečný běh celé sady po posledních změnách prošel, viz níže. Devět nových projekčních regresních testů prošlo (3,926 s).

## Závěrečné ověření a předání — 2026-09-14

- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` mimo omezení lokálních socketů/Qt v sandboxu: **195 testů, 191 prošlo, 4 přeskočeny, bez chyb (114,552 s)**. Skutečné Qt/WebEngine, native editor/history/preview, HTTP/HTTPS, izolované balení/install/upgrade/remove a offline provoz běžely. Přeskočeny pouze čtyři volitelné testy libgit2 probe; aplikace používá Git CLI.
- Devět nových projekčních regresních testů v `tests/test_index_projection.py`; procesní přerušení uvnitř SQL transakce (mezi checkpointy) při migraci/rebuild i při Workspace recovery. Výsledky dřívějších běhů výše jsou historické, tento běh pokrývá finální kód/testy.
- Dokumentace a místní odkazy ověřeny; `git diff --check`, finální diff i nové soubory zkontrolovány. Samostatný build/lint není pro aplikaci nakonfigurován; existující balicí kontroly běžely.

Scope jednoho PR `feature/f-m1-index-01-relations -> develop`: relační projekce metadat/cest/štítků/vztahů, atomická migrace z v0, FK a směrované dotazy, společná stale/pending hranice, porovnání celé projekce s Git snapshotem, regresní/recovery testy a ADR 0022. Nezbytná ad-hoc oprava zpřesňuje pouze testovací smoke selektor a používané assets; běžné UI workflow se nemění.

Recovery: před commitem zůstává autoritou journal; po commitu index rebuild z validovaného HEAD. Pád před SQL potvrzením vrátí celou projekci/migraci, po potvrzení lze indexaci opakovat bez dalšího commitu; pending se uvolní až po journalovém úklidu. Neznámá verze/layout DB se odmítá bez smazání/downgrade, journal se nemění. Omezení: lokální Linux PoC, bez cílového měření výkonu/paměti nebo nového LXC/router nasazení, bez výpadku napájení a nekooperačních FS záruk; V-04/V-05 a Gate M1 zůstávají otevřené. PR není otevřen ani sloučen; dokončené úkoly zůstávají v TODO do uzavření dávky.
