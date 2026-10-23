<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0041 — Federovaný katalog existence projektů

Datum: 2026-10-23. Stav: přijato; implementováno, fyzická akceptace čeká.

## Kontext

ADR 0040 určil, které projekty smějí jednotlivé úrovně vztahu sdílet, ale
záměrně nezavedl nový přenos. První přenosová fáze má protistraně oznámit pouze
existenci povolených projektů. Nesmí předstírat synchronizaci obsahu, založit
prázdný lokální projekt ani udělit právo projekt číst.

## Rozhodnutí

Katalog v1 obsahuje přesně `source_node_id`, `recipient_node_id`, monotónní
revizi a seřazený seznam nejvýše 256 objektů `{id, title}`. Popis, cesty,
větve, commity, obsah, historie, privacy, ACL, členství, credentials a lokální
stav se nepřenášejí. `same-team` vybírá všechny dostupné místní projekty;
`same-company` a `external` jen projekty s explicitní buňkou v matici.
Branch policy zatím pouze uchovává rozsah pro budoucí data a katalog dále
nefiltruje. `unspecified`, pending a revoked vztah selžou uzavřeně.

Jeden bounded HTTPS request nese katalog volajícího a úspěšná odpověď vrací
katalog příjemce. Oba payloady podepisuje stávající připnutá Ed25519 identita
uzlu a vážou oba Node UUID. TLS používá již uloženou peer CA. Node endpoint
nepřijímá browser Authorization, Origin, nepřesný Host ani chunked přenos.
`same-team` a `same-company` se zkoušejí automaticky každých 60 sekund;
`external` pouze explicitním tlačítkem. Server s dynamickým klientským peerem
neiniciuje spojení, ale vrátí svůj katalog při požadavku klienta.

Přijatý katalog je node-local projekce v `federation-catalog.sqlite`. UI jej
zobrazuje jako „projekt oznámený peerem“, odděleně od místních projektů.
Nevytváří zápis do `node.json`, projektový adresář, Git repo, Workspace,
projektový journal ani index. Existence proto není autorizací budoucího
stažení nebo otevření projektu.

## Persistence, souběh a recovery

Odchozí obsah každého peeru má v jedné SQLite transakci uložený digest, přesné
JSON a revizi. Stejný obsah zachová revizi, změna ji zvýší. Příjem v jedné
transakci atomicky nahradí projekci pouze novější revizí; starší opožděnou
revizi ignoruje a stejnou revizi s jiným obsahem odmítne.

- pád před odchozím SQLite commitem nevydá novou revizi;
- pád po commitu před odesláním zopakuje stejné podepsatelné bajty a revizi;
- příjem před inbound commitem nemá účinek;
- ztracená odpověď po inbound commitu vede k idempotentnímu opakování;
- lokální uložení odpovědi volajícího je další nezávislá hranice a po pádu se
  doplní dalším katalogovým kolem;
- registry policy se před i po načtení lokálních titulů porovná podle stejného
  commitu; změněný scope se neodešle a scheduler jej zkusí znovu.

SQLite katalog není autoritativní projektový index ani synchronizovaná data.
Po ztrátě jej lze znovu sestavit výměnou s peery. Revokované projekce mohou na
disku zůstat pro recovery, ale veřejná správa je po revokaci nezobrazuje.

## Reuse a odmítnuté varianty

Řez reuse/adaptuje `Administration`, `Projects.catalog`, `MappingSignatures`,
uložené peer CA, HTTPS validaci a společné administrační UI. Soukromá inventura
neobsahuje komponentu se stejnou maticí a připnutou identitou. Git bundle,
SSH, projektový Workspace/Journal/Index, message broker a nový externí sync
framework byly odmítnuty: přenášely by více dat nebo přidaly další autoritu,
než tato úzká fáze vyžaduje.

## Důsledky a navazující práce

Uživatel uvidí, že projekt na peeru existuje, ale nemůže jej zatím otevřít.
Nedostupná lokální registrace bez validního committed názvu se v katalogu
neobjeví; nejde o tvrzení, že vzdálený obsah je synchronizovaný. Přenos větví a
historie pro interní vztahy řeší F-M5-SHARING-SYNC-01. External data bundle,
patche, styčný uživatel a souborový kanál řeší F-M5-EXTERNAL-EXPORT-01.
