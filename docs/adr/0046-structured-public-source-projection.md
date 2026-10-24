<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0046 — Strukturovaná projekce veřejného HTML

Datum: 2026-10-24. Stav: přijato pro
`F-M3-PUBLIC-SOURCE-READER-02`.

## Kontext

První řez readeru podle [ADR 0033](0033-public-source-retrieval.md) bezpečně
získá jednu schválenou statickou stránku, ale výsledný plochý text ztrácí
nadpisovou hierarchii, hranice seznamů a tabulkové vztahy. Raw bajty a textová
projekce jsou už součástí durable stagingu a Context Manifestu. Nová čitelná
vrstva proto nesmí vytvořit druhou autoritu fetch operace ani obejít její
SSRF, privacy, preview a recovery hranice.

## Rozhodnutí

`static-html-v1` nadále používá bounded parser ze standardní knihovny, ale pro
nové úspěšné runy vytváří také uzavřenou projekci
`public-source-structured-v1`. Dokument obsahuje title a nejvýše 2 048 bloků
v dokumentovém pořadí. Povolené bloky jsou nadpis, odstavec, položka seznamu,
citace, preformátovaný text, termín/popisek definice a tabulka. Každý blok
nese aktuální nadpisovou cestu a deterministický anchor odvozený z kanonického
obsahu; opakovaný shodný blok dostane pořadové zakončení. Tabulky mají zvlášť
caption, bounded řádky, buňky a indexy plně hlavičkových řádků.

Hlavička stránky, navigace, footer, aside, formuláře, explicitně skryté
elementy a `role=navigation` nejsou obsahové bloky. Běžná obsahová karta
zapsaná jako položka seznamu s vnořeným nadpisem a odstavcem zůstane jedním
souvislým blokem; vnořený nadpis nesmí změnit cestu následující karty. Neznámé
inline elementy mohou přispět pouze svým viditelným textem k právě otevřenému
bloku. Parser nespouští HTML, JavaScript, odkazy ani další síťový účinek.
Prompt injection zůstává inertním nedůvěryhodným textem.

`projection.txt` zůstává vstupem pro model a auditovatelným textovým
fallbackem. U nového HTML se deterministicky renderuje ze strukturovaných
bloků; `projection.json` je jeho čitelná doprovodná projekce. Výsledek i
Context Manifest nesou schema a SHA-256 celého kanonického JSON, který tím
váže také typy, pořadí, heading paths a anchory. UI sestavuje pouze vlastní DOM
elementy a nastavuje `textContent`; vzdálené HTML nikdy nevkládá jako markup.
Uživatel může přepnout mezi strukturovaným výtahem a původním bounded textem.

## Kompatibilita a recovery

Stávající `PublicSourceRuns` zůstává jediným journálem. Před přechodem runu do
`succeeded` se `raw.bin`, `projection.txt` a u nového runu také
`projection.json` zapíší přes dočasný soubor, fsyncnou a atomicky přejmenují.
Pád před uzavřením SQLite stavu zůstává podle ADR 0033 `unknown`; žádný fetch
se neopakuje. Po restartu recovery ověří přítomné soubory, jejich hashe a
uzavřené schema struktury. Chybějící nebo změněná deklarovaná projekce
zneplatní run jako `staging-invalid`.

Starý výsledek bez `projection_file` se nemigruje ani nepřepisuje. Raw a text
se ověří původním způsobem, strukturované čtení vrátí `None` a UI automaticky
zobrazí textový fallback. Tím se nemění autorita ani hash historického runu.

## Reuse a odmítnuté varianty

Řez **adaptuje** existující `HTMLParser`, `PublicSourceRuns`, kanonickou JSON
serializaci, Context Manifest a inertní sdílené desktop/web UI. Nepřidává
Readability/BeautifulSoup ani nový runtime balík. Externí parser, headless
browser, heuristické přeskupování článku a druhý projekční journal se
odmítají: pro tuto bounded sadu bloků by rozšířily závislosti nebo síťovou a
recovery hranici bez potřebného přínosu. Soukromá reuse inventura neposkytla
shodnou komponentu; žádný její kód ani neveřejné detaily se nepřenášejí.

## Omezení

Jde o čitelnou statickou projekci, ne o úplnou implementaci HTML layoutu.
Složité tabulky s `rowspan`/`colspan`, CSS generovaný obsah, shadow DOM,
JavaScript-only stránky a přesné vizuální pořadí nejsou podporované. Reader
neodhaduje hlavní článek pomocí skórování a nadále nestahuje navazující zdroje.
