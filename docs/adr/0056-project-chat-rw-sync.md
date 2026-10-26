<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0056 — Projektové chaty v obousměrné obsahové synchronizaci

- Stav: přijaté pro PoC
- Datum: 2026-10-26
- Dávka: `F-M5-CHAT-HISTORY-01`

## Kontext a rozhodnutí

Historie workspace chatu není samostatný read-only export. Projektová vlákna
jsou součástí stejné uživatelské operace, scheduleru, podepsaného requestu a
response jako ostatní data sdíleného projektu podle ADR 0042. Protokol
`content-sync` v2 nese vedle nativního Git bundle omezený kanonický chatový
payload a inventuru digestů. Jeden iniciátor tak vymění Git i chaty v obou
směrech; samostatný chatový endpoint, tlačítko ani druhý outbox nevznikají.

Přenášejí se pouze vlákna přiřazená přesně synchronizovanému projektu. U P2P
vztahu musí mít vlastník aktivní ručně potvrzené bilaterální mapování pro tento
projekt. U schváleného klient–server vztahu se žádné druhé mapování nezakládá:
autorita se deterministicky odvodí z `account_binding`, který na obou uzlech
vznikl autentizovaným enrollmentem podle ADR 0039. Serverový účet musí zůstat
aktivní a mít přístup k projektu. Na cíli se vlastník přeloží na tento přesný
místní účet. Přijaté vlákno vstupuje do běžného `ChatThreads`, je read-write a
místní mapovaný uživatel v něm může pokračovat. Nezařazená vlákna se s
projektem nepřenášejí.

Payload nepřenáší credentials, provider session, Context Manifest payload ani
node-local run journal. Historické message/turn/run ID se při nekonfliktním
přenosu zachovají, ale tlačítko runtime evidence se nabízí jen pro run skutečně
dostupný na místním uzlu. Celé vlákno s `local-only` zprávou nebo s turnem ve
stavu `prepared` či `run-bound` zůstává lokální a neblokuje synchronizaci
ostatních projektových dat.

## Fast-forward a fork konfliktu

Chat je posloupnost neměnných zpráv a terminálních turnů. Shodný digest je
idempotentní. Je-li jedna verze přesným prefixem druhé a její revize neklesá,
delší verze je fast-forward. Při skutečné divergenci se žádná větev nezahodí:

1. kanonicky menší SHA-256 digest zůstane pod původním thread UUID;
2. druhá verze dostane deterministický UUIDv5 fork;
3. kopie ve forku dostane deterministicky nové message/turn/run ID, aby
   nekolidovala s původní historií;
4. `forked_from_thread_id` a `forked_from_digest` zachovají původ konfliktu.

Stejný výpočet na obou uzlech konverguje na původní zapisovatelné vlákno a
zapisovatelný fork. UI fork označí v běžném stromu chatů. Automatický obsahový
merge dvou odpovědí se neprovádí.

## Persistentní hranice a recovery

Podepsaný `content-sync` request, Git bundle i chatový payload se před sítí
uloží v jediném node-local sync journalu. Příjem uloží přesné request bajty
před účinkem. Poté idempotentně aplikuje Git pod project writer lockem a chaty
v jedné `ChatThreads` SQLite transakci. Pád mezi Git a SQLite není atomický
napříč úložišti; durable inbound request je recovery autorita a retry provede
roll-forward ze stejných bajtů. Odpověď se publikuje až po obou účincích a
ztracená odpověď vrací při retry stejný uložený response.

Migrace `ChatThreads` v6 pouze přidává nullable fork provenance. Rozpracovaná
lokální operace smazání blokuje nahrazení stejného vlákna. Mazání vláken a
tombstones se v tomto řezu nesynchronizují; chybějící položka ve vzdálené
inventuře proto nemaže místní kopii.

## Reuse a hranice

Reuse/adaptuje se ADR 0042, Ed25519 pinning, aktivní mapování ADR 0021,
`ChatThreads` a stávající content-sync journal. Odmítá se druhý transport,
read-only projekce, nový message broker a ukládání chatu do projektového Gitu.
Federovaný lidský chat `F-M5-CHAT-01`, nezařazené konverzace, synchronizované
mazání, provider runtime a obecné capability profily zůstávají mimo rozsah.
