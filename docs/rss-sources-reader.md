<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Čtečka kanálů v části Zdroje

Levá lišta používá stejný seznam položek a malé menu **⋮** jako Podklady.
Kliknutí na název zobrazí vpravo články. Menu nabízí zobrazení obsahu,
úpravu kanálu a načtení článků. Horní ikony **＋** a **import** mají přístupný
název a popis při najetí i fokusu. Editor obsahuje název, HTTPS URL a periodu
obnovy v minutách (1 minuta až 7 dní). Změna URL odstraní starou cache tohoto
kanálu; přejmenování a změna periody obsah zachovají.

## Import

Podporován je [OPML 1/2](https://2005.opml.org/spec2.html), tedy XML seznam
odběrů se zanořenými `outline` a atributem `xmlUrl`. Samotný RSS/Atom feed
není seznam odběrů. JSON přijímá pole objektů nebo objekt `subscriptions`:

```json
{"subscriptions":[{"title":"Novinky","url":"https://example.org/rss"}]}
```

Podporovány jsou také URL pole `xmlUrl`, `feedUrl` a Feedly `feedId` s
prefixem `feed/`. Nejde o obecný import libovolné JSON zálohy čtečky.
Náhled ukáže nové odběry, duplicity a neplatné řádky; uživatel vybere,
co uložit. Duplicitní normalizované URL se nepřidají. Import je omezen na
512 KiB a 1000 odběrů; DTD a XML entity se odmítají. Neplatná či HTTP URL
se zobrazí jako chyba řádku, nepřevádí se odhadem na HTTPS. Import neprovádí
síťový GET. Nový odběr má periodu 15 minut, kterou lze změnit editorem.

## Umístění a obnova

Čtečka je samostatná uzlová funkce, nikoli projektový monitoring. Odběry
se ukládají v sousedním souboru `node.rss-subscriptions.sqlite3` odvozeném
od cesty konfigurace uzlu. Nepřenášejí se jako definice projektových filtrů,
poolů nebo komplexních úloh. Cache článků zůstává paměťová a po restartu se
znovu načte. Zápis/import/načítání ve webu vyžadují správce uzlu; člen smí
číst přehled bez aktivace síťových požadavků.

Reuse: existující `RSSSources`, veřejný HTTPS RSS transport, omezený XML
parser `BoundedTree`, `sidebarItemMenu`, helper `sqlite_connection` a vzor
místních nastavení `GamepadSettings`. Před uložením se validuje celý nový
seznam. `BEGIN IMMEDIATE` a kontrola revize brání přepsání cizí změny;
přesné opakování uloženého seznamu po ztrátě odpovědi je idempotentní.

Crash boundaries: před transakcí může existovat pouze prázdný soubor nebo
prázdná tabulka; čtení tehdy použije původní výchozí odběry. Přerušení před
commitem vrátí celou změnu zpět, po commitu je celá sada trvale uložená.
Paměťová konfigurace se mění až po úspěšném zápisu; po pádu procesu se načte
z DB. Neexistuje navazující Git commit, projektový index ani druhý journal,
který by vyžadoval společnou recovery. Test simuluje přerušení před commitem,
restart, stale revizi a přesné opakování.

## Omezení zátěže a ověření

Automatická obnova běží jen v otevřené viditelné čtečce, bez rozepsaného
editoru/importu. Každých 30 sekund zkontroluje nejvýše jeden splatný kanál;
server znovu ověří jeho periodu. Ruční načtení seznamu posílá jednotlivé
kanály postupně a po odchodu ze čtečky další nepřidává. Přímé API `all`
je omezeno na osm kanálů; UI tento dlouhý hromadný request nepoužívá.
Dosavadní transportní limity, pravidla veřejných URL a oprávnění platí dál.

Cílené selektory: `tests.test_rss_sources`, `tests.test_rss_subscriptions`,
`tests.test_rss_sources_refresh`, `tests.test_http_ui_admission`,
`tests.test_startup_admission`, `tests.test_project_http_ownership`,
`tests.test_federation_http_ownership` a `tests.test_workspace_navigation`.
Skutečný `tests.test_rss_sources_browser` ověřuje desktop/mobil, inertní
obsah feedu, klávesnici, přidání, menu → editor, uložení periody a OPML import.
Plná sada ani nasazení na Omnii nejsou tímto ověřením doložené.

Výsledek cíleného ověření: 52 testů OK, 4 volitelné skipy. Samostatný Qt
průchod byl skutečně spuštěn a prošel; desktop i mobil byly vizuálně
zkontrolovány. Sestavený JavaScript prošel `node --check` a finální diff
prošel `git diff --check`. Změna zůstává v pracovním checkoutu bez commitu
nebo vzdáleného nasazení.
