<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0084 — synchronizace odběrů uzlové RSS čtečky

Datum: 2026-11-12. Zadání uživatele: doplnit synchronizaci RSS zdrojů po
rozlišení projektových zdrojů a samostatné čtečky. Zdrojová větev
`feature/rss-direct-pilot`, výchozí HEAD `0c72bb5`. Kanonický Workspace
projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, platná exportní revize
`eeb67f514d0d7177d25735dd56892c023555daf1ead1fbea2ac8acf469f9ff71`.
Kontrakt implementace k review, nikoli akceptace nebo druhý plán.

## Rozsah, oprávnění a reuse

Odběry čtečky nejsou projektové `MonitoringBlock` definice. Definice i jejich
kauzální historie zůstávají ve stávající `node.rss-subscriptions.sqlite3`.
Je to autoritativní uzlové nastavení, nikoli obnovitelný projektový index,
synchronizovaný SQLite soubor nebo kopie provozního journalu. Projektový Git,
poolový přenos a aktivace z ADR 0082 zůstávají beze změny.

Přenášejí se názvy, normalizované HTTPS URL, intervaly, kauzální rodiče,
digesty a veřejná UUID původců revizí. Cache článků, časy načtení, aktivace
monitoringu, credentials, node.json a volby protistran zůstávají místní.
Původce revize je metadata historie; autentizovaná je protistrana podepisující
celý balík, nikoli samostatný podpis každé historické revize.

Správce musí sdílení výslovně povolit na **obou** uzlech pro konkrétní peer.
Platí současná schválená Ed25519 identita a vztah same-team/same-company.
Projektové sdílení samo přístup k odběrům neuděluje. External, unspecified
a odvolané vztahy se odmítají. Volba sdílení kontroluje předchozí hodnotu;
přesné opakování po ztracené odpovědi je idempotentní.

Reuse/adapt: původní `Subscriptions.save` a FULL transakce, validátor kanálu,
podpisové obálky, registry autority a peer CA, `DeadlineHTTPSConnection`,
minutový `CatalogScheduler` a cache `RSSSources`. Nepřibývá scheduler ani
projektový writer. Endpoint `/v1/federation/rss-subscriptions` kontroluje
Host, Content-Type, limit těla, uzavřený JSON parser, příjemce, aktuální
souhlas a podpis. Nepouští GET RSS/článku. Starší uzel bez podpory vrátí chybu
RSS přenosu, bez narušení projektového katalogu nebo transportního fallbacku.

## Kauzalita a konflikty

Odběry se sjednocují podle normalizované URL. Existující místní UI ID se
zachová; nový přijatý odběr dostane deterministické ID podle URL. ID revize
je hash hodnoty, rodičů a původce. Při prvním zápisu/sdílení se existující
seznam atomicky osadí kořenovými revizemi; stejné starší hodnoty mají stejný
kořen i při různých místních UI ID.

Příjem sjednotí validní neměnné revize. Rodiče musejí existovat, odpovídat
stejné URL a tvořit acyklický graf. Potomek převáží jen nad svými předky.
Nezávislé přírůstky se spojí, shodné souběžné hodnoty nekonfliktují.
Rozdílné souběžné konce se zachovají k review; místní hodnota se nepřepíše.
Výběr řešení vytvoří potomka všech přesně posouzených konců. Kontroluje
revizi seznamu i sadu konců. Nový příjem historie zvýší revizi seznamu také
tehdy, když konflikt ponechá zobrazenou hodnotu stejnou; starý editor tak
nemůže přepsat nově přijatou konfliktní větev. Přesný replay čítač nezvyšuje.

Odstranění v úplném uloženém seznamu má tombstone. Starý balík odběr neobnoví.
Změna URL je odstranění původní a přidání nové. Historie definic včetně
odstraněných URL zůstává kvůli kauzalitě; fyzický výmaz/kompakce není součástí.
Podepsané inventury šetří opakovaný přenos: při shodě se pošle malá kontrola,
po ztrátě inventury plný balík při následující kontrole. Ruční akce posílá
plnou historii hned. Inventury jsou optimalizace, nikoli autorita.

## Crash boundaries a obnova

- Historie, výsledný seznam a jeho revize se mění v jedné `BEGIN IMMEDIATE`
  transakci s `synchronous=FULL`; stejně se zapisují místní změny a rodiče.
- Pád před COMMIT vrátí celou změnu, včetně případného vytvoření tabulek.
  Seznam nemůže být publikovaný bez historie nebo opačně.
- Pád po COMMIT před odpovědí se obnoví replay; union nepřidá kopii ani další
  revizi seznamu. Potvrzené inventury mohou za daty zaostat a obnoví se
  opakováním. Nejde o distribuovanou transakci přes oba uzly.
- Vypnutí místního souhlasu během přenosu zabrání následnému importu.
  DB historie je vázaná na node UUID; kopie pod jinou identitou vyžaduje obnovu.
- Čtečka kontroluje revizi DB před čtením/zápisem. Název/perioda zachovají
  cache, nová URL dostane prázdnou. Po restartu se odběry a konflikty načtou
  z DB, paměťová cache se zahodí. Čtení samo neaktivuje backendový monitoring.
- Ruční síťové čekání vlastní `catalog_transfer`, příjem `peer_catalog`.
  HTTP čtení RSS cache se síťovým čekáním neblokuje; zápisy serializuje
  SQLite a změny paměti původní RSS zámky. Timer otevřené čtečky obnoví
  definice před výběrem nejvýše jednoho splatného kanálu. Draft/import je chráněn.

## Limity a ověření

Maximum 1000 odběrů, 10 000 revizí historie a 2 MiB. Překročení odmítne celou
změnu, nic neořízne. Automatická kontrola běží přibližně jednou za minutu,
pouze pro vybrané peers. Síťový pokus má 15sekundový deadline a ověřenou CA.
Potřebná podpora musí být na obou uzlech; transport se v témže pokusu neopakuje.

`test_rss_subscription_sync` ověřuje kauzalitu, tombstone, stale editor,
skutečné procesní pády, ztracené potvrzení, oprávnění, podpisy, skutečné HTTPS,
odmítnutí jiné CA a čtení během pomalého přenosu.
`test_rss_subscription_sync_browser` používá skutečné GUI pro zapnutí,
přenos, review a vyřešení konfliktu bez načtení článků.
Izolované ověření není fyzická akceptace Omnia/desktop.
