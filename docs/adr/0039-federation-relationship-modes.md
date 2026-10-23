<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0039 — Typy federačních vztahů P2P a klient–server

Datum: 2026-10-22. Stav: přijato a implementováno pro odlehčený osobní režim.

## Kontext

Dosavadní peer registr rozlišoval jen endpoint, připnutou identitu a stav
důvěry. To zaměňovalo dvě odlišné topologie: rovnocenné servery s pevnými
adresami a desktopového klienta, jehož adresa se může měnit. Staré záznamy
navíc neobsahují dost informací pro bezpečné automatické určení topologie.

Plný návrh centrální identity, MFA a společného policy modelu z ADR 0037
zůstává odložený. Toto rozhodnutí pouze zpřesňuje vztah mezi dvěma uzly a
nevydává ruční peer trust za dokončené přihlášení nebo mapování účtů.

## Rozhodnutí

Registr rozlišuje tyto typy vztahu:

- `p2p`: rovnocenné serverové uzly, oba s pevnou HTTPS adresou. Lokální role
  je `peer`, založení je dostupné pouze na serverovém deploymentu a schválení
  nadále vyžaduje nezávislé ověření UUID a otisku klíče;
- `client-server`: desktopový klient se může připojovat z proměnlivé adresy a
  spojení vždy iniciuje on. Na desktopu je lokální role `client` a uchovává se
  pevný endpoint serveru; na serveru je role `server` a endpoint klienta se
  neukládá;
- `legacy`: bezeztrátové označení všech starších záznamů, jejichž topologii
  nelze spolehlivě odvodit. Zůstávají funkční ve stávajícím protokolu, ale
  nelze je běžně editovat. Správce je musí převést nebo odvolat.

Nový klient–server vztah vznikne až přihlášením klienta existujícím serverovým
účtem přes důvěryhodné TLS. Enrollment následně připne node key klienta,
vydá omezený obnovitelný credential a vytvoří explicitní vazbu lokální identity
desktopu na serverový účet. Původní heslo ani dlouhodobý uživatelský access key
se na klientovi neukládají. Desktop podepíše jednorázový požadavek svou
federační identitou a server vrátí podepsanou odpověď vázanou na oba uzly, oba
účty a operation UUID. Serverový access key je pouze bootstrap autentizace;
desktop jej po požadavku zahodí. Samostatný node credential zůstává mimo Git,
je omezený na budoucí obnovu klientského vztahu a opakované přihlášení jej
rotuje. Enrollment nevytváří projektová oprávnění ani replikační grant.

## Migrace a bezpečnost převodu

Schéma registračního Git dokumentu se zvyšuje na verzi 5. Načtení verzí 1–3
přidá každému peeru `relationship_type: legacy` a `local_role: null`; účty,
endpoint, pin, mapování a replikační záznamy zachová. Migrace publikuje jediný
nový Git commit pod stávajícím flockem a CAS refu. Pád před změnou refu ponechá
platné staré schéma a další otevření migraci zopakuje; po změně refu je commit
autoritativní a žádný samostatný index se neopravuje.

Migrace verze 4 na 5 přidá `account_binding: null`. Schválený vztah
`client-server` musí mít přesnou dvojici `local_user_id` a `remote_user_id`;
P2P a legacy ji mít nesmí. Na serveru může přihlášení vytvořit nový klientský
peer nebo dokončit existující odpovídající pending záznam. Již připnutý jiný
klíč, odvolaný peer nebo vazba na jiný serverový účet se odmítne.

Převod legacy vztahu je jedna atomická revize registru. Nejprve vytvoří
podepsané revokační tombstones všech navázaných mapování a replikací a vypne
replikace, potom uloží nový typ a lokální roli a vrátí trust do `pending`.
P2P zachová pevný endpoint. Převod na klient–server zachová endpoint na
desktopovém klientovi, ale na serveru jej odstraní. Původní stav zůstává v Git
historii; žádné existující oprávnění se automaticky nepřenese do nového typu.

## Důsledky a omezení

Tabulka federace zobrazuje typ a směr vztahu. Nové ruční založení je povoleno
jen pro P2P na serveru. Klient–server nelze ručně přepnout do `approved`;
pending desktop vztah dokončí akce Přihlásit k serveru. Server vztah založí
nebo dokončí z ověřeného přihlášení klienta a nečeká na druhé ruční schválení.

Legacy kompatibilita je dočasná, aby upgrade nezastavil existující osobní
replikaci bez rozhodnutí správce. Její budoucí odstranění vyžaduje samostatnou
migraci a důkaz, že nezůstaly aktivní staré vztahy.

Doplnění 2026-10-23: topologie již neurčuje rozsah sdílení. Samostatné úrovně
`same-team`, `same-company` a `external`, pravidlo klient–server = `same-team`
a projektovou matici definuje [ADR 0040](0040-federation-sharing-levels-and-project-matrix.md).

## Persistentní hranice enrollmentu a recovery

Server nejprve pod svým registry lockem publikuje schválený peer a účetní
vazbu, potom v lokální SQLite databázi vydá nebo otočí hashovaný node
credential. Pád mezi těmito kroky může zanechat schválený vztah bez
credentialu, nikoli credential s širšími právy; stejné přihlášení bezpečně
vydá nový credential bez druhého peeru.

Klient nejprve ověří TLS, připnutý serverový node key, podpis odpovědi a přesná
ID požadavku. Potom atomicky uloží node credential mimo Git a teprve následně
publikuje lokální `approved` a `account_binding`. Pád po serverovém commitu,
ztracená odpověď nebo pád po uložení credentialu se řeší zopakováním stejného
enrollmentu; server credential otočí a oba registry se dorovnají vpřed.
Odvolání peeru smaže lokálně dostupný node credential, zruší účetní vazbu a
nadále používá existující podepsané tombstones mapování a replikací.
