<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0027 — Detekované a výslovně povolené publikační CMS

Stav: přijato a v `MOD-01-UI` implementováno jako **PoC validated**. Rozhodnutí
zpřístupňuje pouze dvě capability prvního publikačního modulu; není obecným
plugin runtime ani instalátorem modulů.

## Kontext a rozhodnutí

Workspace prohlédne přímé podadresáře bezpečného `modules.local/` a zobrazí
validní manifesty jako přítomné moduly. Discovery je pouze čtení deklarace:
neimportuje Python, nespouští entrypoint a modul automaticky nepovoluje.
Publikační CMS lze spustit pouze tehdy, když jej uživatel v nastavení výslovně
povolí a současně platí:

- `module_id`, `schema_version`, `module_version` a verze API odpovídají
  reviewovanému manifestu hosta;
- celý `module.json` je shodný s deklarací této reviewované verze a obsahuje
  podporované `publication-sites.preview` i `publication-sites.generate`;
- úplná množina Python runtime souborů a použitá HTML šablona odpovídají SHA-256
  allowlistu v `modules/publication-experiment-registry.source.json`;
- Python se spouští izolovaně přes `-I`, s pevným bootstrapem a pevným
  entrypointem. Checkout nemůže dodat `sitecustomize`, měnit příkaz ani předat
  shellový fragment.

Binding obsahuje pouze identitu, povolenou verzi manifestu a příznak povolení a
leží v privátním node-local stavu mimo projektový Git. Cesta se znovu odvodí z
discovery a Git commit není součástí kontraktu. Změna povolení je odmítnuta,
pokud čeká nedokončená generační operace. Nová verze modulu nebo runtime vyžaduje
nové review manifestu i zdrojového allowlistu; pouhé přepsání čísla verze
nestačí. Starý binding založený na cestě a Git revizi selže uzavřeně a modul je
nutné znovu povolit.

Desktop zpřístupňuje záložku **Weby** lokálnímu uživateli. Webová varianta ji i
všechny `/v1/publication-cms/*` operace zpřístupňuje pouze node/federation
administrátorovi. UI nejprve zobrazí automaticky zjištěnou přítomnost, verzi a
kompatibilitu a nabídne samostatné Povolit/Zakázat. Po povolení načte
konfiguraci, dovolí editovat tři varianty, vytvoří izolovaný HTML náhled, zobrazí
přesnou konfiguraci, verzi modulu a hash náhledu a vyžádá samostatné potvrzení
před generováním. Náhled se vykresluje v sandboxed iframe; do okolního DOM se
nevkládá jako HTML.

CMS zatím zůstává nadprojektovou funkcí uzlu. Jeho konfigurace zůstává mimo
projektový Git a nesynchronizuje se. Generátor čte
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
   Opakování vrátí stejný receipt. Stejné ID s jiným requestem, změněná verze či
   runtime modulu, změněný náhled nebo nepotvrzený request se odmítne.

Neexistuje externí účinek se stavem `unknown`; automatická recovery je přípustná
jen proto, že lokální výstup je deterministický a nenasazuje se. Budoucí upload,
DNS nebo provider deploy musí mít samostatnou capability a externí recovery
kontrakt.

## Ověření a omezení

Testy pokrývají discovery bez spuštění, povolení a zákaz, odmítnutí jiné verze
manifestu nebo runtime hashů, oddělený preview/confirm tok, stale preview,
idempotentní receipt, HTTP autentizaci a pád po vygenerování před uložením
konfigurace. Desktop/web UI je staticky a přes lokální API ověřené; skutečný
Qt/WebEngine click test zůstává samostatnou akceptací.

Kontrola skutečného deploymentu a jeho vytvoření či aktualizace není vydávána za
lokální generování. Vyžaduje samostatnou externí capability s konkrétním
provider adapterem, stavem `unknown`, credential hranicí, status reconciliation
a odděleným potvrzením přesného cíle a obsahu.
