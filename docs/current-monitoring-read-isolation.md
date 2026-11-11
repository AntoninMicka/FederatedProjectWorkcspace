<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Podklady, aktuální nástroje a čtení při synchronizaci

Zdrojový základ: `5e3886a`, oprava uživatelem nahlášeného zobrazení RSS
v Podkladech, legacy variant sledování a blokování příjmu synchronizace.
Dokument nedokládá nasazení ani akceptaci výkonu Omnie.

## Oddělení obsahu

Podklady zobrazují uživatelské artefakty, ne interní reportingové záznamy,
RSS nálezy, uložené kopie feedů ani původní definice sledování. Klasifikace
používá existující reporting schema/tag, typovaný record, jeho `raw_ref`,
tag `rss-capture` a původní explicitní marker sledování; nepoužívá název
článku ani obecné `provenance=external`. Ručně importované uživatelské
podklady tím nejsou plošně skryté. Filtr je společný pro otevření projektu
a katalog editoru dokumentů. Přímé auditní čtení a Git historie zůstávají.

Pooly mají vlastní uzlové SQLite úložiště a přenosný sidecar. Jejich zprávy
nejsou artefakty Podkladů. Obsah se prohlíží v konkrétním poolu s původem,
filtry a verzemi. Vydané zprávy zůstávají konkrétními vydáními ve Výstupech.
Tato změna historické RSS kopie, definice ani zprávy nemaže a nepřevádí.

UI již neobsahuje původní ani dvoufázový editor sledování, legacy kategorii,
volby jejich vytváření ani migrační panel. Živý `Monitoring.start` spouští
jen blokový model. Historická API/recovery a explicitní servisní operace
zůstávají pro uložená data; staré bindingy nejsou při startu automaticky
vykonávány ani převáděny na nové granty.

## Doložená kolize a oprava čtení

Read-only diagnostika běžící Omnie zaznamenala `/v1/monitoring/view` ve fázi
processing přes 18 sekund a souběžné odmítnutí příjmu jako
`SyncBusy / project-journal`. Zaznamenala také kolizi `content-state` a
katalogu peeru ve společné `peer_catalog_lane`. V okamžiku jednoho pozdějšího
vzorku nebyla aktivní žádná publikace; tento vzorek není důkaz použitelnosti
UI během synchronizace.

Nové UI posílá `view` s `mode=blocks`. Jedna validovaná Git revize poskytuje
aktuální bloky i seznam vydaných zpráv, bez starého RSS statusu, watch jobs,
freshness přepočtů a druhého HTTP požadavku na stejné bloky. `MonitoringBlocks`
vytváří piny přímo z téhož snapshotu, místo samostatného Workspace/index
otevření pro každý blok. Poolový runtime a počty se čtou read-only; katalog
nespouští cleanup. Retenci dál provádí původní worker.

`content-state` má vlastní bounded `peer_state` HTTP linku. Nečeká na linku
katalogu. Sdílená konečná kapacita HTTP workerů zůstává zachovaná; nejde
o zvýšení počtu workerů ani timeoutů.

## Vlastnictví, crash boundaries a recovery

Navazuje na [ADR 0050](adr/0050-bounded-http-monitor-concurrency.md) a
[ADR 0081](adr/0081-complete-project-data-sync.md). Nevzniká nový writer,
persistentní formát ani druhý journal.

1. Read-only Workspace pouze připojí existující journal, bez inicializace
   indexu nebo journalu. Tento handle odmítá publikaci i recovery zápisů.
   Krátký původní writer zámek ověří vlastníka journalu,
   absenci aktivní operace/pending řádků a zachytí HEAD.
2. Snapshot, schémata a historické reporting piny se validují z neměnných
   Git objektů mimo vlastnictví projektového writeru. Reporting sémantická
   validace zůstává plná. SQLite index se při tomto přímém Git čtení nepoužívá
   ani neopravuje; není vydávána jeho případná stará projekce.
3. Před vydáním odpovědi krátký checkpoint znovu kontroluje pending/aktivní
   operaci a stejný HEAD. Současně dokončený zápis způsobí `StaleIndex`,
   rozpracovaný zápis `PendingOperation`, obsazený owner řízené busy.
   Stale HTTP čtení vrací 503 s `retry=read-again`, nikoli rozpojený socket.
4. Pád čtenáře mezi checkpointy nemá co obnovovat: neprovedl projektový
   zápis, index rebuild ani recovery. Pád writeru zachová původní journal;
   čtenář ho nečistí a nerozhoduje místo původního lifecycle.
5. Explicitní staré `Reporting.read` dál používá původní recovery vstup,
   ale drahou následnou validaci také provádí mimo dlouhý writer zámek.
   Publikace, CAS a dokončování indexu/journalu zachovávají původní hranice.

Klidový blokový worker neprochází Git katalog každých deset sekund. Bere
registrovaná ID z uzlové konfigurace, provede lokální retenci/reconciliation
a při chybějících aktivacích nebo ještě nesplatných RSS vstupech skončí bez
projektového writeru a sémantické validace Git. Před skutečným síťovým účinkem
se vždy znovu ověří aktuální definice, aktivace a souhlas. Processing bindingy
zachovávají své původní ověření plánovacího slotu; z hintu nevzniká grant.

## Ověření a hranice

Cílené testy ověřují zachování skrytých dat v Git, Podklady bez RSS/poolových
článků, nepřítomnost legacy UI, neaktivaci starého scheduleru, klidový worker
bez Git/writeru, jednoznačný snapshot přehledu a řízenou stale HTTP odpověď.
Souběhový test pozastaví reporting validaci čtenáře a během ní skutečný
`SyncReceiver` publikuje nový commit; čtenář po uvolnění odmítne starý výsledek.
Nejde pouze o test samotného zámku.

Qt/WebEngine scénář používá izolovaný profil a lokální HTTP backend se
skutečně zachyceným RSS, bloky a naplněným poolem. Otevře projekt a nástroje,
zkontroluje nepřítomnost RSS v Podkladech a legacy variant a otevře obsah
poolu na správném místě. Live výkon po aktualizaci obou skutečných uzlů
zůstává samostatným ověřením. CPU soutěž při nutné Git validaci a ostatní
publikační kritické sekce tím nejsou prohlášené za odstraněné.

Finální ověření zdrojového základu `5e3886a` + diff: úplná sada má 2 082
případů, OK, 58 skip. Všech 190 top-level modulů je zahrnuto právě jednou
v konečné sadě čtyř izolovaných shardů. Po odstranění vyřazených formulářů
z tiskové inventury a aktualizaci testu pollingu se celé dotčené shardy 1 a 4
opakovaly s původním seznamem modulů; ostatní dva úspěšné shardy zůstaly
beze změny. Aplikační kód se při těchto opravách návazností neměnil. SHA-256
shoda finálního kódu/testů s izolovanými kopiemi byla ověřena.

Finální opt-in Qt/WebEngine scénář prošel nad skutečným lokálním HTTP
backendem. Prošla kompilace dotčených modulů, syntaxe sdíleného JavaScriptu,
kontrola lokálních odkazů a `git diff --check` včetně nových souborů.
Read-only diagnostické čtení existujícího lokálního projektu Pokus mělo
114 souborů a 48 reportingových záznamů a trvalo 0,723 s. To je měření
samotného lokálního snapshotu; čas celého webového přepnutí projektu na
Omnii tím doložen není. Nové změny nebyly tímto během na Omnii nasazeny.
