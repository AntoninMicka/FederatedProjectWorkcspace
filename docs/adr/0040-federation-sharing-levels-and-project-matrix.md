<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0040 — Úrovně sdílení a matice projektů federace

Datum: 2026-10-23. Stav: přijato; implementováno je verzované nastavení,
transport a skládání exportních balíčků zůstávají navazující prací.

## Kontext

Dosavadní registr směšoval topologii `p2p` / `client-server` s jedním úzkým
modelem `primary` → `read-only-replica`. Nový požadavek rozlišuje technický
způsob spojení od organizační hranice a od projektového/branch scope. P2P může
spojovat jeden tým, dvě části stejné společnosti nebo externí organizace.
Klient–server naproti tomu vždy představuje vlastní tým.

## Rozhodnutí

Topologie zůstává `p2p`, `client-server` nebo migrační `legacy`. Samostatná
úroveň sdílení je:

- `same-team`: automatická obousměrná synchronizace všech projektů a celé
  povolené Git historie;
- `same-company`: automatická obousměrná synchronizace pouze explicitně
  vybraných projektů. Pro každý projekt policy buď skryje uvedené větve, nebo
  povolí jen uvedené větve;
- `external`: žádná background synchronizace. Styčný uživatel na vyžádání
  sestaví a odešle datový balíček, volitelně s patchi pouze z jedné explicitní
  exportní větve. Balíček nepřenáší vlastní Git historii příjemci; ten vede
  nezávislou historii importu;
- `unspecified`: pouze migrační fail-closed stav starého P2P vztahu. Nepovoluje
  nové sdílení.

`client-server` musí mít vždy `same-team`. Nový nebo převedený P2P vztah musí
mít jednu ze tří skutečných úrovní. Trust `pending` / `approved` / `revoked`
zůstává oddělený a samotná úroveň sdílení nic nepřenáší.

Nastavení používá matici projekt × peer. `same-team` je v ní odvozeno jako
všechny projekty; nevytváří se redundantní záznam pro každou buňku.
`same-company` a `external` ukládají jen explicitně zapnuté buňky s branch
policy. Desktop i web používají stejnou správu; mobilní zobrazení převádí
matici na lineární karty projektů.

## Autorita, crash hranice a migrace

Federační Git registr se zvyšuje na schema v6. Peer dostává `sharing_level` a
registr seznam `project_shares`. Každá změna peeru nebo jedné buňky matice se
validuje před zápisem a publikuje jediným commitem pod existujícím flockem a
CAS refu. Pád před změnou refu zachová starý stav; po změně refu je nový commit
autoritativní. SQLite ani UI nejsou další policy autoritou.

Migrace v5 → v6 nastaví klient–server na `same-team`, protože tento vztah tak
vznikl autentizovaným enrollmentem. P2P se nastaví na `unspecified`, aby upgrade
bez potvrzení nerozšířil přístup. Legacy zůstane `unspecified`. Staré mappingy
a jednosměrné replikační granty se migrací nemažou ani nevydávají za nový
obousměrný režim.

## Hranice současné implementace

Implementováno je pouze durable nastavení a jeho UI. Dosavadní podepsaný HTTPS
transport nadále vykonává jen explicitní `primary` → `read-only-replica` grant
z ADR 0038. Neinterpretuje `same-team`, `same-company` ani `external` jako
novou transportní autoritu.

Navazující řezy musí samostatně navrhnout a ověřit obousměrnou synchronizaci,
divergenci a merge bez ztráty historie, autorizaci všech dosažitelných objektů
větví, sestavení obsahově omezeného exportního balíčku, patch provenance,
styčného uživatele, přímý i souborový přenos, import do nezávislé historie a
revokaci dalších účinků. `local-only` nesmí opustit svůj uzel v žádném režimu.

