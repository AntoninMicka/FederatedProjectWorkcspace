<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0027 — Připnuté spuštění publikačního CMS

Stav: přijato a v `MOD-01-UI` implementováno jako **PoC validated**. Rozhodnutí
zpřístupňuje pouze dvě capability prvního publikačního modulu; není obecným
plugin runtime ani instalátorem modulů.

## Kontext a rozhodnutí

Samotná přítomnost checkoutu v `modules.local/`, shodný manifest ani
uživatelem zadaný Git commit nejsou důkazem, že lze bezpečně spustit jeho kód.
Workspace proto přijme publikační CMS pouze tehdy, když současně platí:

- absolutní lokální cesta po normalizaci míří do existujícího čistého Git
  checkoutu a jeho `HEAD` přesně odpovídá připnuté plné revizi;
- `module.json` je významově shodný s reviewovaným manifestem hosta a deklaruje
  `publication-sites.preview` i `publication-sites.generate`;
- úplná množina Python runtime souborů a použitá HTML šablona odpovídají SHA-256
  allowlistu v `modules/publication-experiment-registry.source.json`;
- Python se spouští izolovaně přes `-I`, s pevným bootstrapem a pevným
  entrypointem. Checkout nemůže dodat `sitecustomize`, měnit příkaz ani předat
  shellový fragment.

Binding obsahuje pouze cestu a revizi a leží v privátním node-local stavu mimo
projektový Git. Neobsahuje credential. Změna bindingu je odmítnuta, pokud čeká
nedokončená generační operace. Nová verze runtime vyžaduje nové explicitní
review a změnu zdrojového allowlistu; pouhé zachování manifestu nestačí.

Desktop zpřístupňuje záložku **Weby** lokálnímu uživateli. Webová varianta ji i
všechny `/v1/publication-cms/*` operace zpřístupňuje pouze node/federation
administrátorovi. UI načte konfiguraci, dovolí editovat tři varianty, vytvoří
izolovaný HTML náhled, zobrazí přesnou konfiguraci, source revision a její hash
a vyžádá samostatné potvrzení před generováním. Náhled se vykresluje v sandboxed
iframe; do okolního DOM se nevkládá jako HTML.

Konfigurace CMS zůstává mimo projektový Git a nesynchronizuje se. Generátor čte
pouze veřejný publikační registr modulu a zapisuje obnovitelné statické soubory
do jeho ignorovaného `dist/sites`. Tato operace není deployment, DNS změna ani
publikace na internet.

## Crash boundaries a recovery

SQLite journal v privátním node-local adresáři je autoritativní pro potvrzené
generace. Jeden filesystem lock serializuje konfiguraci, recovery i generování.

1. Před spuštěním modulu se uloží `operation_id`, hash a celý potvrzený request
   ve stavu `prepared`. Pád před výstupem nezmění autoritativní konfiguraci.
2. Generátor může při pádu zanechat částečný `dist/sites`; jde o odvozený lokální
   výstup. Opakování stejné operace jej deterministicky přegeneruje.
3. Po úspěšném generování se konfigurace uloží atomickým replace + fsync. Pád
   mezi výstupem a konfigurací ponechá journal `prepared`; příští status nebo
   stejné `operation_id` operaci bezpečně zopakuje.
4. Teprve poté se do journalu atomicky uloží receipt a stav `completed`.
   Opakování vrátí stejný receipt. Stejné ID s jiným requestem, změněná revize,
   změněný náhled nebo nepotvrzený request se odmítne.

Neexistuje externí účinek se stavem `unknown`; automatická recovery je přípustná
jen proto, že lokální výstup je deterministický a nenasazuje se. Budoucí upload,
DNS nebo provider deploy musí mít samostatnou capability a externí recovery
kontrakt.

## Ověření a omezení

Testy pokrývají čistotu a pin revize, shodu manifestu a runtime hashů, oddělený
preview/confirm tok, stale preview, idempotentní receipt, HTTP autentizaci a pád
po vygenerování před uložením konfigurace. Desktop/web UI je staticky a přes
lokální API ověřené; skutečný Qt/WebEngine click test a živé propojení s novým
commitnutým modulem zůstávají samostatnou akceptací. Modulový checkout je nyní
rozpracovaný, takže jej Workspace správně odmítne do vytvoření a připnutí jeho
čistého commitu.
