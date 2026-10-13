<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-PROJECT-DELETE-01 — Bezpečné odstranění celého projektu

Původ: roadmapa M1 a požadavek připravený v BACKLOGu. Cílová úroveň:
**designed → implemented → PoC validated**. Aktivní větev:
`feature/f-m1-project-delete-01-safe-project-removal`, základ a cíl jediného PR:
`develop` na merge commitu PR #64 `7373d81`.

## Rozsah feature

Oddělit odregistrování projektu, odstranění jeho odvozeného node-local
stavu, přesun vlastněného repozitáře do obnovitelného koše a definitivní
výmaz. Každá destruktivní varianta musí mít přesný preview a samostatné
potvrzení. Lokální operace nesmí tvrdit, že odstranila vzdálené,
federované nebo dříve sdílené kopie.

Mimo rozsah jsou vzdálené mazání, revokace dříve publikovaných dat,
cloudová synchronizace a obecný úklid cizích cest. Odregistrování doslova
chybějícího rootu z F-M1-PROJECT-LOCATION-01 zůstává zachovaným omezeným
případem, nikoli důkazem této feature.

## Persistentní hranice a recovery

Autoritativní Git historie zůstává v repozitáři, dokud uživatel výslovně
nezvolí definitivní výmaz. Node registry, odvozené indexy/cache, chatové a
workflow databáze, credentials reference a transfer/run journaly mají vlastní
ownership a nesmějí se tiše zaměnit za projektový Git. Nový autoritativní
node-local deletion journal před prvním účinkem připne operation ID, digest
preview, projektovou identitu, root, HEAD, zvolený režim a inventář vlastněného
stavu. Recovery je idempotentní; cizí nebo změněný root, nová pending operace
či neznámý externí účinek operaci zastaví fail-closed.

## Úkoly

- [x] [completed] **F-M1-PROJECT-DELETE-01-A — Kontrakt, inventář a reuse
  (designed).** Zmapovat vlastnictví registry, repozitáře, indexu, chatů,
  workflow/run stavů, credentials referencí, přenosů a federovaných stop;
  popsat režimy, blokující stavy, crash boundaries a adaptaci existujícího
  ProjectCreation/Workspace journalu a bezpečného mazání dokumentu. Rozhodnutí,
  ownership a recovery jsou v ADR 0031; reuse/reject je v REUSE_CATALOG.
- [x] [completed] **F-M1-PROJECT-DELETE-01-B — Doménová služba a durable recovery
  (implemented).** Implementovat přesný preview, explicitní confirm, stabilní
  operation ID/digest, serializaci, idempotentní receipt a obnovu pro podporované
  režimy bez následování symlinků nebo zásahu do cizích cest. Implementováno
  jako `ProjectDeletion` nad sdíleným node writer lockem a operation journalem;
  restore i purge jsou samostatné durable operace.
- [x] [completed] **F-M1-PROJECT-DELETE-01-C — Sdílené UI/API
  (implemented).** Zobrazit režim, přesné cesty, HEAD, inventář dopadů,
  blokátory a upozornění na vzdálené kopie; nechat Cancel jako bezpečný
  výchozí stav a vyžádat samostatné potvrzení definitivního výmazu. Desktop i
  web používají stejný preview/confirm adaptér; webové mutace vyžadují správce.
- [ ] [in progress] **F-M1-PROJECT-DELETE-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Otestovat každý persistentní přechod, retry/lost response,
  restart, změněný root/HEAD, symlink, cizí cestu, pending Workspace/transfer/
  provider účinek, souběh, odvolané oprávnění a zachování vzdálených stop;
  spustit celou testovací sadu a provést fyzickou desktop/web akceptaci.
  Automatické ověření: 11 cílených doménových testů, skutečná HTTPS cesta
  preview → koš → obnova, JS syntaxe a celá sada 530 testů za 116,058 s prošly;
  24 testů vyžadujících volitelný WebEngine/private vzorek bylo přeskočeno.
  Zbývá fyzická desktop/web akceptace správy odstranění.

## Podmínky dokončení

- Uživatel předem vidí přesný lokální rozsah a rozliší odregistrování,
  odstranění odvozeného stavu, obnovitelný koš a definitivní výmaz.
- Projekt s aktivní nebo neurčitou operací se nemaže; recovery nevytvoří
  duplicitní účinek a zachová cizí změny.
- Koš je skutečně obnovitelný a definitivní výmaz má nové explicitní
  potvrzení; lokální akce se nevydává za vzdálený výmaz.
- Cílené recovery/UI testy, celá sada, `git diff --check` a fyzická
  akceptace odpovídají dosaženému stavu bez neověřených tvrzení.

## K předání do backlogu

Zatím bez nových odkladů.
