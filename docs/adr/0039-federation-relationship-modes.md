<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0039 — Typy federačních vztahů P2P a klient–server

Datum: 2026-10-22. Stav: přijato; registr a správa vztahů jsou implementovány,
enrollment klient–server zatím ne.

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
se na klientovi neukládají. Tento protokol je navazující implementační řez;
současný editor jej nesmí nahrazovat ručním schválením.

## Migrace a bezpečnost převodu

Schéma registračního Git dokumentu se zvyšuje na verzi 4. Načtení verzí 1–3
přidá každému peeru `relationship_type: legacy` a `local_role: null`; účty,
endpoint, pin, mapování a replikační záznamy zachová. Migrace publikuje jediný
nový Git commit pod stávajícím flockem a CAS refu. Pád před změnou refu ponechá
platné staré schéma a další otevření migraci zopakuje; po změně refu je commit
autoritativní a žádný samostatný index se neopravuje.

Převod legacy vztahu je jedna atomická revize registru. Nejprve vytvoří
podepsané revokační tombstones všech navázaných mapování a replikací a vypne
replikace, potom uloží nový typ a lokální roli a vrátí trust do `pending`.
P2P zachová pevný endpoint. Převod na klient–server zachová endpoint na
desktopovém klientovi, ale na serveru jej odstraní. Původní stav zůstává v Git
historii; žádné existující oprávnění se automaticky nepřenese do nového typu.

## Důsledky a omezení

Tabulka federace zobrazuje typ a směr vztahu. Nové ruční založení je v tomto
řezu povoleno jen pro P2P na serveru. Desktop tlačítko Přidat pravdivě odkazuje
na chybějící přihlašovací krok a klient–server nelze ručně přepnout do
`approved`. Dokud enrollment nebude implementovaný, převedený klient–server
vztah zůstane `pending` a nemůže autorizovat mapování ani přenos.

Legacy kompatibilita je dočasná, aby upgrade nezastavil existující osobní
replikaci bez rozhodnutí správce. Její budoucí odstranění vyžaduje samostatnou
migraci a důkaz, že nezůstaly aktivní staré vztahy.
