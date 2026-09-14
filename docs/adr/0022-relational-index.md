<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0022 — Relační projekce metadat a vztahů

Datum: 2026-09-14. Stav: přijato pro F-M1-INDEX-01/V-03, lokální Linux PoC.
Výsledky ověření a stav předání drží [TODO](../../TODO.md). Navazuje na
[ADR 0002](0002-metadata-journal.md) a
[ADR 0003](0003-coordinated-operation.md); Git schéma v1 se nemění.

## Rozhodnutí a reuse

Adaptovat současný `Index` a `Workspace`, validátor `validate_snapshot` a stdlib
SQLite. Další databáze/framework ani externí kód nejsou pro tuto projekci potřeba;
současná koordinace už řeší Git commit, journal a recovery. Soukromá inventura
nedává důvod tento mechanismus nahrazovat.

Dosavadní index ukládal pouze ID/title a commit ID. Nová lokální verze indexu
(`PRAGMA user_version=1`, nezávislá na verzi metadat) obsahuje:

- `entities`: ID, title, kind, privacy, provenance, author_id, created_at,
  description, source_url, status/body registru, cestu obsahu nebo registry JSON
  a kanonický JSON validovaných metadat;
- `tags`: entity_id, ordinal a přesný text štítku;
- `relations`: source_id, ordinal, type a target_id, s cizími klíči na entity;
- `state`: jediný commit ID pro celý současně publikovaný snapshot.

JSON zachová přítomnost/absenci volitelných polí a umožní kontrolu shody
normalizovaných řádků. Neobsahuje druhou autoritativní kopii dat. Čtení projekce
sestaví metadata ze sloupců, štítků a vztahů a porovná je s uloženým JSON.
Projektový přehled navíc porovná celou projekci s validovaným Git snapshotem,
včetně cest a vztahů. Formátování YAML/JSON a bajty obsahu zůstávají v Gitu;
projekce uchovává metadata jako hodnoty, nikoli jejich původní serializaci.

Vztahy jsou pouze explicitně uložené směrované hrany. Pořadí a duplicity vztahů
i štítků se zachovají; nejsou zakázané schématem v1. Cykly a vlastní neprázdné
typy vztahů se nezpřísňují. Doporučené typy nejsou validační allowlist a inverzní
vztahy se nevytvářejí automaticky. V1 přijímá přesně `type` a `target_id`;
`note` není implementované pole. Tímto ADR se nerozšiřuje schéma ani nedokončuje
podrobnější provenance nebo celoživotní neměnnost zdrojů V-04/V-05.

## Čtení a aplikační hranice

Původní `Index.read(git)`/`Workspace.read()` zůstávají ID/title seznamem.
`Workspace.read_projection()` vrací `{commit_id, entities, relations}`;
`entities` je mapa ID na `{metadata, path}`. `relations` obsahují source_id,
ordinal, type a target_id. `Workspace.read_relations(entity_id,
direction='outgoing'|'incoming', relation_type=None)` vrací commit ID a filtrované
hrany v původním směru. Příchozí dotaz pouze vybere hrany podle target_id.
Neexistující kanonické UUID vrátí prázdný seznam. SQL hodnoty se parametrizují.

Nové Workspace vstupy sdílejí writer lock, odmítnutí pending a rebuild stale
indexu. Nejsou veřejným HTTP API ani alternativou autorizovaného Projects vstupu;
jsou určeny lokálnímu backendu nad jeho registrovaným Workspace. Nezavádějí UI
relačních dotazů, přenos dat, RBAC ani výjimku z privacy kontrol.

Index čte jednu SQL transakci a porovnává commit ID s HEAD před i po dotazu.
Rebuild čte pevný Git commit, validuje snapshot a před SQL potvrzením znovu
kontroluje HEAD. Low-level Index sám journal nezná a nenahrazuje Workspace zámek.
Nekooperující změna HEAD po poslední kontrole zůstává limitem Linux PoC.

## Migrace, crash boundaries a recovery

Hranice ADR 0003 se nemění: před commitem drží nedokončenou operaci journal;
po publikaci commitu lze index znovu postavit z HEAD. Změna indexu neovlivňuje
projektové soubory, Git historii, operation ID ani receipts.

Původní dvousloupcová projekce má user_version=0. Její otevření nemigruje ani
nevydává staré řádky za současnou plnou projekci: čtení vyvolá StaleIndex.
Workspace rebuild ji nahradí z validovaného HEAD. Neznámá budoucí verze nebo
neznámý legacy layout (včetně journalových tabulek) se odmítne bez přepsání; neprovádí se downgrade.

Migrace tabulek, FK, indexů, user_version, všech dat a commit ID proběhne v jedné
explicitní `BEGIN IMMEDIATE` transakci. Nepoužívá se executescript uvnitř migrace.
Čtenáři buď vidí starý snapshot, nebo kompletní nový snapshot.

| Hranice | Recovery |
| --- | --- |
| Před SQL transakcí / neplatný Git snapshot | Stará projekce zůstává, nový commit se nevydává za indexovaný. |
| `index-cleared`, `index-entities`, `index-relations`, `index-state` | Pád procesu vrátí celou SQL transakci včetně DDL/verze; opakovat rebuild z HEAD. |
| `index-published`, před uložením journalového `indexed` | Celá projekce je potvrzena; pending dál blokuje aplikaci, recovery bezpečně zopakuje indexaci. |
| Journal `indexed` a úklid | Beze změny ADR 0003; receipt/úklid se potvrdí po indexaci. |

FK se zapínají při každém rebuild spojení, všechny entity se vloží před hranami.
Chybějící index lze vytvořit a postavit z HEAD; při poškozené nebo nepodporované
DB se automaticky nemaže žádný stavový soubor. Journal se nesmí zaměnit za index
ani odstranit kvůli chybě projekce. Testy pádů mezi checkpointy nedokládají
výpadek napájení, pád uvnitř libovolného syscallu ani cílový výkon na Turrisu.

## Ověření

[Regresní scénáře](../../tests/test_index_projection.py) ověřují metadata,
frontmatter/sidecar/registry cesty, pořadí/duplicity a příchozí/odchozí dotazy,
FK, neplatný snapshot a drift HEAD, migraci, neznámou verzi, SQL čtenáře během
výměny, pády procesu při migraci i rebuild a recovery přes Workspace.
Integrační scénář používá skutečné native služby importu, metadata editace,
přejmenování a odstranění, zachování přesných zdrojových bajtů a obnovu chybějící
DB. Současné výsledky a omezení patří do TODO, nikoli do nové paralelní roadmapy.
