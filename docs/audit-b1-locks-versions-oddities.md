<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# AUDIT-B1 — zámky, verzové podmínky a podivnosti

Stav dokumentu: **AUDIT-B1-T1 designed** (metodika a inventura). Katalog
nálezů B-LOCK, B-VER a B-ODD doplní úkoly AUDIT-B1-T2 až T4, prioritizaci
a mapování na nápravné dávky AUDIT-B1-T5. Do té doby dokument neobsahuje
žádný nález ani verdikt.

Audit je podklad k review. Není akceptací, změnou autoritativního plánu ani
oprávněním k hromadnému odstranění zámků či podmínek. Nálezová ID nejsou úkoly
Workspace. Runtime kód se během auditu nemění.

## Zadání a výchozí stav

| Položka | Hodnota |
|---|---|
| Workspace projekt | `c898b941-8eb0-4406-8dad-6e2b96c06d59` |
| Repozitář | `https://github.com/AntoninMicka/FederatedProjectWorkcspace.git` |
| Exportní revize plánu | `451eb66a4cebc9e38dfcb7571d82d39cc6f434206023730121a4f88687f548ef` |
| Sync exportu | `2026-11-18T05:46:08.781Z`, `stale=false` |
| Výchozí commit auditu | `0e69cc5006be1739048c089c6c46f82868d5bd8c` (`develop`, merge #146) |
| Větev | `feature/audit-b1-locks-versions` |

Oblast auditu: `spikes/` včetně webového UI v `desktop_ui.py`
a `http_ui_admission.py` a rozšíření `extensions/workspace-bridge/`. Testy
slouží jen jako doklad chování, nikoli jako předmět nápravy.

Navazuje na [audit souběhu z 11. 11. 2026](concurrency-audit-2026-11-11.md)
a [nápravu P1](concurrency-p1-remediation.md). Nálezy A01–A06 tam mají
doloženou nápravu; A07–A11 znovu ověří AUDIT-B1-T2 nad výchozím commitem.
Zápisy nad stejnými nativními daty zůstávají serializované podle
[ADR 0003](adr/0003-coordinated-operation.md); audit nenavrhuje oslabení
journalu. Mantinely HTTP kapacit drží
[ADR 0050](adr/0050-bounded-http-monitor-concurrency.md).

## Metodika

### Kategorie

| Prefix | Kategorie | Patří sem |
|---|---|---|
| `B-LOCK` | Zámky a serializace | `threading` Lock/RLock/Condition/Semaphore, `fcntl.flock` EX/SH, SQLite `BEGIN IMMEDIATE/EXCLUSIVE` a writer reservation, HTTP admission domény (`http_admission_policy`, `request_ownership`), browser FIFO a Web Locks, serializace front v rozšíření. |
| `B-VER` | Verzové a revizní podmínky | Rovnosti a výčty verzí programu, schématu, definice či dokumentu; sloupce podle `version >= N`; stav vázaný na revizi, digest nebo fingerprint; verzové brány rozšíření proti backendu; legacy/compat větve. |
| `B-ODD` | Další podivnosti | Spolknuté chyby, text chybové hlášky jako stav, rozptýlené magické timeouty a rozpočty, kontroly jen IPv4, mrtvé legacy větve, obří inline UI, duplicitní desktop/web handlery a validace, testy ověřující text implementace, tvrzení dokumentace bez kódu. |

Nález patří do jediné kategorie. Legacy větev vázaná na verzi je `B-VER`;
jako `B-ODD` se eviduje jen tehdy, když nemá verzový význam (mrtvý kód,
duplicita). Překryv se zapíše odkazem na druhé ID, nikoli druhým nálezem.

### Kritéria nutnosti

**Zámek (`B-LOCK`)** je nutný, jen pokud lze pojmenovat chráněný invariant
a bez výhradního režimu by byl porušen. Pro každý zámek se zaznamená:

1. chráněný invariant (data, soubor, proces, kapacita);
2. kdo jsou čtenáři a kdo zapisovatelé; zda se čtenáři navzájem blokují;
3. zda se zámek drží přes síťové nebo diskové I/O, LLM volání či odeslání
   HTTP odpovědi;
4. zda blokuje status nebo cancel téže práce;
5. zda existuje recovery cesta, která na zámku závisí (journal, index rebuild).

Verdikty: **nutný** / **zúžit kritickou sekci** / **převést čtení na SH nebo
snapshot** (`mode=ro`, neměnný Git commit) / **nahradit CAS či revizní
kontrolou** / **odstranit**. Výhradní režim pro zápis nad stejnými nativními
daty se podle ADR 0003 považuje za nutný; posuzuje se jen jeho rozsah.

**Verzová či revizní podmínka (`B-VER`)** se posuzuje podle chování při
verzi N+1 a při nové revizi dokumentu. Výsledek je jeden z:
**explicitní chyba** / **migrace** / **viditelný degradovaný stav** /
**tiché vypnutí** / **tichý fallback na starou logiku**. Nálezem je jen tiché
vypnutí a tichý fallback; ostatní výsledky jsou přijatelný kontrakt, pokud je
uživateli viditelný. Vazba schválení na `preview_sha256`, pin fingerprintu
peeru či CAS revize je legitimní bezpečnostní kontrola, nikoli chyba.
Doporučený kontrakt (rozsah podporovaných verzí, migrace, chyba) se
zapisuje ke každému řádku.

**Podivnost (`B-ODD`)** je nálezem, pokud skrývá chybu, mění chování podle
nedeklarovaného předpokladu nebo zbytečně zdvojuje údržbu. Verdikty:
**ponechat** / **zjednodušit** / **odstranit** / **zdokumentovat**.
Čistě stylistické nálezy bez dopadu na chování jsou nejvýše P3.

### Priorita

| Priorita | Kritérium |
|---|---|
| P1 | Doložená ztráta dostupnosti či funkce v běžném provozu (čtenář blokuje čtenáře nebo cancel, tiché vypnutí funkce, dat či oprávnění po upgradu), skrytá chyba s dopadem na data nebo bezpečnostní hranici. |
| P2 | Dopad je podmíněný (souběh, konkrétní konfigurace, budoucí verze), nebo jde o zbytečnou serializaci bez ztráty funkce; existuje viditelné obejití. |
| P3 | Údržba, čitelnost a konzistence bez doloženého dopadu na chování. |

Priorita vychází z dopadu, nikoli z počtu výskytů. P1 vyžaduje důkaz typu
R nebo T; statický nález může mít P1 jen s výslovně popsanou cestou kódu
a poznámkou, že reprodukce chybí.

### Typy důkazu

| Typ | Význam | Požadavek |
|---|---|---|
| S — statický | Doložená cesta kódu `soubor:řádek` nad výchozím commitem. | Pojmenovaná volající cesta, nikoli jen výskyt vzoru. |
| R — reprodukce | Izolovaná sonda v dočasném adresáři/repozitáři, na loopbacku, bez skutečného LLM, peerů, feedů a cloudových služeb. | Příkaz nebo postup v dokumentu, pozorovaný výsledek (stavový kód, výjimka, stav). Sonda nemění runtime kód. |
| T — test | Existující test v `tests/`, který chování dokládá. | Explicitní unittest selektor a výsledek běhu. |

Tvrzení „čtenář blokuje čtenáře“ musí mít zdrojové místo a buď R, nebo
výslovné označení S. Každé „tiché vypnutí“ musí mít konkrétní cestu kódu;
vybrané případy se reprodukují fixture o verzi či revizi výš. Callbackové
sondy dokládají admission, nikoli plnou integraci feature.

### Záznam nálezu

Každý řádek katalogu obsahuje: ID, kategorii, zdroj `cesta:řádek`
(výchozí commit, pokud není uvedeno jinak), chráněný invariant nebo
podmínku, typ důkazu, verdikt, prioritu a po T5 cílovou dávku
(AUDIT-B2 až B4) nebo výslovné odmítnutí. ID se přidělují vzestupně
(`B-LOCK-01`, …), nepřečíslovávají se a odmítnutý nález si ID ponechá.

### Hranice závěru

Inventura je seznam kandidátů pro ruční posouzení, nikoli nálezů. Počty
závisí na regulárních výrazech níže a mají známé falešně pozitivní
i negativní výskyty (viz [poznámky](#poznámky-k-přesnosti)). Audit nebude
formálním důkazem absence deadlocků, zátěžovým testem ani auditem cizích
pluginů a závislostí.

## Reprodukovatelná inventura

Skript čte pouze objekty Git zadaného commitu (`git grep`, `git show`,
`git ls-tree`), takže nezávisí na pracovním stromu ani na nezacommitovaných
změnách. Spouští se z kořene repozitáře; volitelný argument je commit.
Řádek L08 načítá `spikes/http_admission_policy.py` z commitu do izolovaného
interpretru (`python3 -I`); modul nemá importy ani vedlejší účinky.

```bash
#!/usr/bin/env bash
# AUDIT-B1 inventory; read-only, independent of the working tree.
set -euo pipefail
C=${1:-0e69cc5006be1739048c089c6c46f82868d5bd8c}
git rev-parse --verify --quiet "$C^{commit}" >/dev/null
PY='spikes/*.py'; JS='extensions/workspace-bridge/*.js'
n() { wc -l | tr -d ' '; }
lines() { git grep -h -E "$1" "$C" -- "${@:2}" | n; }
hits()  { git grep -h -o -E "$1" "$C" -- "${@:2}" | n; }
files() { git grep -l -E "$1" "$C" -- "${@:2}" | n; }
row() { printf '%-5s %-44s %s\n' "$1" "$2" "$3"; }
row ID metrika počet
row I00 "commit" "$(git rev-parse "$C")"
row I01 "spikes Python moduly" "$(git ls-tree -r --name-only "$C" -- spikes | grep -c '\.py$')"
row I02 "spikes Python řádky" "$(git ls-tree -r --name-only "$C" -- spikes | grep '\.py$' | while read -r f; do git show "$C:$f"; done | n)"
row I03 "desktop_ui.py řádky / nad 500 znaků" "$(git show "$C:spikes/desktop_ui.py" | n) / $(git show "$C:spikes/desktop_ui.py" | awk 'length>500' | n)"
row I04 "spikes řádky nad 500 znaků" "$(lines '.{501}' "$PY")"
# Locks
row L01 "fcntl LOCK_EX výskyty / moduly" "$(hits 'LOCK_EX' "$PY") / $(files 'LOCK_EX' "$PY")"
row L02 "fcntl LOCK_SH výskyty / moduly" "$(hits 'LOCK_SH' "$PY") / $(files 'LOCK_SH' "$PY")"
row L03 "moduly jen s LOCK_EX" "$(comm -23 <(git grep -l LOCK_EX "$C" -- "$PY" | sort) <(git grep -l LOCK_SH "$C" -- "$PY" | sort) | n)"
row L04 "SQLite BEGIN IMMEDIATE|EXCLUSIVE řádky / moduly" "$(lines 'BEGIN (IMMEDIATE|EXCLUSIVE)' "$PY") / $(files 'BEGIN (IMMEDIATE|EXCLUSIVE)' "$PY")"
row L05 "threading Lock/RLock/Condition/Semaphore ctor" "$(hits 'threading\.(Lock|RLock|Condition|Semaphore|BoundedSemaphore)\(' "$PY")"
row L06 "  z toho moduly" "$(files 'threading\.(Lock|RLock|Condition|Semaphore|BoundedSemaphore)\(' "$PY")"
row L07 "threading.Event ctor" "$(hits 'threading\.Event\(' "$PY")"
row L08 "HTTP admission přesné routy / lanes" "$(git show "$C:spikes/http_admission_policy.py" | python3 -I -c 'import sys; g={}; exec(sys.stdin.read(), g); print(len(g["ROUTE_LANES"]), "/", len(g["LANES"]))')"
row L09 "Web Locks navigator.locks (soubory)" "$(files '\.locks\b' "$PY" "$JS")"
row L10 "rozšíření requestQueues/Promise tail" "$(lines 'requestQueues|tail: Promise' "$JS")"
# Versions / revisions
VER="version\w*['\"]?\]?\)?\s*(==|!=|>=|<=|<|>)\s*[0-9]|version\w*['\"]?\]?\)?\s*(not )?in\s*[{([]"
row V01 "verzová literálová podmínka řádky" "$(git grep -h -E "$VER" "$C" -- "$PY" | grep -v -E '(address|ip|ip_address\([^)]*\))\.version' | n)"
row V02 "  z toho moduly" "$(git grep -l -E "$VER" "$C" -- "$PY" | while read -r f; do git show "$f" | grep -E "$VER" | grep -q -v -E '(address|ip|ip_address\([^)]*\))\.version' && echo "$f"; done | n)"
row V03 "revize/digest/fingerprint ==|!= řádky / moduly" "$(lines "(revision|digest|fingerprint|sha256)\w*['\"]?\]?\)?\s*(==|!=)" "$PY") / $(files "(revision|digest|fingerprint|sha256)\w*['\"]?\]?\)?\s*(==|!=)" "$PY")"
row V04 "legacy|compat výskyty (i) spikes" "$(git grep -h -o -i -E 'legacy|compat' "$C" -- spikes | n)"
row V05 "legacy|compat výskyty (i) rozšíření" "$(git grep -h -o -i -E 'legacy|compat' "$C" -- "$JS" | n)"
# Oddities
row O01 "široké except Exception|BaseException|bare" "$(lines '^\s*except\s*(:|(Exception|BaseException)\b)' "$PY")"
row O02 "  z toho tělo jen pass|continue|return [None]" "$(git grep -h -A1 -E '^\s*except\s*(:|(Exception|BaseException)\b[^:]*:)\s*$' "$C" -- "$PY" | grep -c -E '^\s*(pass|continue|return( None)?)\s*$' || true)"
row O03 "  z toho inline pass|continue|return [None]" "$(lines '^\s*except\s+(Exception|BaseException)\b[^:]*:\s*(pass|continue|return( None)?)\s*$' "$PY")"
row O04 "JS prázdné catch {}" "$(hits 'catch\s*(\([^)]*\))?\s*\{\s*\}' "$PY" "$JS")"
row O05 "porovnání textu chyby jako stavu" "$(lines "(in|==)\s*str\((exc|error|err|e)\)|str\((exc|error|err|e)\)\s*(==|\.startswith|\.endswith)|\.message\s*==|message\.(includes|startsWith)\(" "$PY" "$JS")"
row O06 "číselný timeout= / timeout: (Python)" "$(hits '\btimeout\s*[=:]\s*[0-9]+(\.[0-9]+)?' "$PY")"
row O07 "číselné *TIMEOUT*/timeout_* konstanty (Python)" "$(git grep -h -o -i -E '\b\w*timeout\w*\s*[=:]\s*[0-9]+(\.[0-9]+)?' "$C" -- "$PY" | grep -v -E '^timeout\s*[=:]' | n)"
row O08 "číselný timeout v rozšíření" "$(hits '\b(timeout\s*:\s*|setTimeout\(\s*)[0-9]+|setTimeout\([^;]*,\s*[0-9]+\)' "$JS")"
row O09 "kontroly jen IPv4" "$(lines 'IPv4Address|IPv4Network|AF_INET\b|\.version\s*==\s*4' "$PY")"
row O10 "testy čtoucí zdrojový text (moduly)" "$(files 'inspect\.getsource|\.read_text\(\)' 'tests/*.py')"
row O11 "testovací moduly tests/test_*.py" "$(git ls-tree -r --name-only "$C" -- tests | grep -c '^tests/test_.*\.py$')"
```

Ověření reprodukovatelnosti: skript uložený mimo repozitář byl nad
výchozím commitem spuštěn dvakrát; výstupy byly bajtově shodné (`cmp`).
Prostředí: GNU bash, GNU grep/awk, Git s `git grep -E`, Python 3.

### Výsledky nad `0e69cc5`

| ID | Metrika | Počet | Orientační metrika v zadání |
|---|---|---:|---|
| I01 | Python moduly v `spikes/` | 217 | 211 |
| I02 | Řádky Pythonu v `spikes/` | 78 249 | ~76 tis. |
| I03 | `desktop_ui.py` řádky / řádky nad 500 znaků | 9 914 / 119 | ~9,9 tis. / 119 |
| I04 | Řádky nad 500 znaků v `spikes/*.py` | 169 | — |
| L01 | `LOCK_EX` výskyty / moduly | 20 / 18 | 20× |
| L02 | `LOCK_SH` výskyty / moduly | 2 / 2 | 2× |
| L03 | Moduly jen s výhradním flock | 16 | 16 |
| L04 | `BEGIN IMMEDIATE/EXCLUSIVE` řádky / moduly | 111 / 33 | 32 modulů |
| L05 | Konstrukce `threading` Lock/RLock/Condition/(Bounded)Semaphore | 30 | — |
| L06 | Moduly s těmito primitivy | 16 | — |
| L07 | Konstrukce `threading.Event` | 6 | — |
| L08 | Přesné HTTP admission routy / lanes | 279 / 34 | — |
| L09 | Soubory s Web Locks (`.locks`) | 1 | — |
| L10 | Řádky serializace front `requestQueues` v rozšíření | 4 | — |
| V01 | Řádky s literálovou verzovou podmínkou (bez IP `.version`) | 139 | ~104 |
| V02 | Moduly s V01 | 52 | — |
| V03 | Řádky / moduly s `==`/`!=` nad revizí, digestem, fingerprintem či SHA-256 | 322 / 101 | — |
| V04 | Výskyty `legacy`/`compat` v `spikes/` | 188 | ~180 |
| V05 | Výskyty `legacy`/`compat` v rozšíření | 13 | — |
| O01 | Široké `except Exception`/`BaseException`/holé `except` | 106 | 98 |
| O02 | Z toho s tělem na dalším řádku jen `pass`/`continue`/`return [None]` | 2 | — |
| O03 | Z toho na jednom řádku | 1 | — |
| O04 | Prázdné JS `catch {}` | 13 | — |
| O05 | Porovnání textu chyby jako stavu | 4 | — |
| O06 | Číselné `timeout=`/`timeout:` v Pythonu | 91 | 91 |
| O07 | Další číselné `*TIMEOUT*`/`timeout_*` konstanty v Pythonu | 16 | — |
| O08 | Číselné timeouty v rozšíření | 3 | — |
| O09 | Kontroly jen IPv4 | 13 | 13 |
| O10 | Testovací moduly čtoucí text souborů | 45 | — |
| O11 | Testovací moduly `tests/test_*.py` | 205 | — |

Rozdíly proti orientačním metrikám zadání nejsou chybou zadání ani
inventury: zadání neuvádí commit ani vzory. U I01 je doložen jen růst
ze 162 modulů v předchozím commitu `2b563fb` na 217 ve squash merge #146;
z jakého stavu pochází hodnota 211, nelze z dostupných podkladů určit.
U L04, V01, V04 a O01 se liší definice vzoru; platné jsou hodnoty této
tabulky s výše uvedeným vzorem.

### Poznámky k přesnosti

- L01/L02 počítají výskyty konstant, nikoli volání `flock`; jeden modul
  může tutéž konstantu předávat helperu. SH nad výchozím commitem používají jen
  `journal.py` (parametr `shared`) a `administration.py` (čtení node
  registry). L03 proto nerozliší modul, který SH získává voláním
  journalu; T2 to ověří u každého z 16 modulů.
- L04 počítá řádky s SQL řetězcem, nikoli běhové transakce; jeden řádek
  může být helper volaný z více cest. L05 nezachytí primitiva importovaná jménem; nad výchozím
  commitem `from threading import` importuje jen `Thread`.
- V01 zahrnuje i verze protokolu, manifestu a migrační kroky; ne každý
  řádek je brána. Nezachytí porovnání proti pojmenované konstantě
  (`== SCHEMA_VERSION`), ty T3 dohledá ručně podle modulů z V02.
- V03 je převážně legitimní CAS a integritní kontrola; slouží jako seznam
  modulů pro T3, nikoli jako počet podezřelých míst.
- O01 počítá jen řádky začínající `except`; tělo handleru (log, překlad
  chyby, tiché pokračování) posoudí T4. O02/O03 zachytí jen jednořádková
  těla, takže jde o dolní mez spolknutých chyb.
- O05 zachytí jen pojmenované proměnné `exc`/`error`/`err`/`e` a JS
  `message.includes/startsWith`.
- O09 obsahuje i řádky, které IPv4 jen rozlišují od IPv6
  (např. `provider_deadline.py` volí `AF_INET6`); T4 je vyřadí.
- O10 zahrnuje i legitimní čtení fixture a výstupních souborů; teprve T4
  odliší testy textu implementace od testů chování.
