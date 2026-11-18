<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# AUDIT-B1 — zámky, verzové podmínky a podivnosti

Stav dokumentu: **AUDIT-B1-T1 a T2 designed** (metodika, inventura a audit
zámků). Nálezy B-VER a B-ODD doplní AUDIT-B1-T3 a T4, prioritizaci
a mapování na nápravné dávky AUDIT-B1-T5. Priority B-LOCK jsou předběžné
do T5.

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

## AUDIT-B1-T2 — zámky a mutexy

Výchozí commit `0e69cc5`; zdrojová místa platí pro něj. Prošel jsem všech
20 `LOCK_EX`/2 `LOCK_SH` míst (L01–L03), 50 získání zámku journalu (`journal.lock(` a `self.lock(` v `journal.py`),
30 `threading` primitiv (L05), enkapsulující funkce všech 111 řádků
`BEGIN IMMEDIATE/EXCLUSIVE` (L04), HTTP admission (L08), Web Locks (L09)
a frontu rozšíření (L10). A07–A11 předchozího auditu jsou ověřené znovu.

### Souhrn

Výhradní režim čtenářů je převážně v **nativní vrstvě**, nikoli v HTTP
admission. Projektový journal `writer.lock` se získává 4× sdíleně a 46×
výhradně. Mnoho čistých čtení drží EX přes `git snapshot` a validaci
celého projektu. Výchozí otevření `Projects.workspace()` navíc vždy
spouští EX bootstrap journalu. V HTTP režimu (`bounded_project_wait`) i při
`blocking=False` se zámek bere s `LOCK_NB`, takže souběžný čtenář nečeká,
ale **okamžitě dostane `ProjectBusy`** (HTTP 503 / typed busy).

Správný vzor už v kódu existuje a je otestovaný: `Workspace.committed_snapshot`
(krátký SH checkpoint, neměnný Git mimo zámek, druhý checkpoint)
a `_read_current_index` (SH, při zastaralém indexu uvolnit a znovu ověřit
pod EX). Náprava nemusí navrhovat nový mechanismus, jen jej použít.

### Reprodukce

**R1 — EX čtenář journalu odmítá čtenáře.** Izolovaný dočasný projekt,
skutečné `ArtifactHistory`, `Artifacts`, `Workspace`; HTTP režim simuluje
`bounded_project_requests()`. Spuštění z kořene repozitáře:
`PYTHONPATH=$PWD python3 probe_r1.py`.

```python
"""AUDIT-B1-T2 probe: an EX-held native reader refuses concurrent readers under HTTP bounded wait."""
import tempfile, threading
from pathlib import Path
from uuid import uuid4

from spikes.artifact_history import ArtifactHistory
from spikes.artifacts import Artifacts, main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.request_ownership import bounded_project_requests, ProjectBusy
from spikes.storage import Git


def outcome(fn):
    try:
        with bounded_project_requests():
            fn()
        return 'ok'
    except ProjectBusy as exc:
        return f'ProjectBusy({exc.busy_resource})'


def hold(cm_factory, entered, release):
    with cm_factory():
        entered.set(); release.wait(10)


with tempfile.TemporaryDirectory() as temp:
    base = Path(temp); node = base / 'node.json'; root = base / 'project'
    pid = ProjectCreation(node).create('Project', str(root), str(uuid4()))['id']
    artifacts = Artifacts(node); history = ArtifactHistory(node); git = Git(root)
    aid = main_todo_id(pid)
    artifacts.save(dict(project_id=pid, artifact_id=aid, base_head=git.head(), title='T',
                        body='- [ ] Task\n', new=True), str(uuid4()))
    head = git.head(); ws = artifacts.workspace(pid)
    readers = {
        'history.list (EX reader)': lambda: history.list(pid, aid, head),
        'snapshot_checkpoint (SH reader)': lambda: ws.snapshot_checkpoint(head),
        'artifacts.workspace() bootstrap': lambda: artifacts.workspace(pid),
        'projects.workspace(for_read=True)': lambda: artifacts.projects.workspace(pid, for_read=True, blocking=False),
    }
    holders = {
        'history._read held (EX)': lambda: history._read(pid, aid, head),
        'journal.lock(shared=True) held (SH)': lambda: ws.journal.lock(shared=True),
    }
    print('baseline:', {k: outcome(f) for k, f in readers.items()})
    for name, factory in holders.items():
        entered, release = threading.Event(), threading.Event()
        t = threading.Thread(target=hold, args=(factory, entered, release)); t.start()
        assert entered.wait(10)
        print(name + ':', {k: outcome(f) for k, f in readers.items()})
        release.set(); t.join()
```

| Držený zámek | `history.list` | `snapshot_checkpoint` (SH) | `artifacts.workspace()` | `workspace(for_read=True)` |
|---|---|---|---|---|
| žádný | ok | ok | ok | ok |
| `history._read` (EX čtenář) | ProjectBusy | ProjectBusy | ProjectBusy | ProjectBusy |
| `journal.lock(shared=True)` (SH čtenář) | ProjectBusy | ok | ProjectBusy | ok |

**R2 — vyvrácení statického podezření u SQLite store.** Helpery
`connect()` v `chat_threads`, `role_workflows`, `summary_tasks`
a `output_execution` zakládají `BEGIN IMMEDIATE`. Sonda držela otevřený
výsledek `ChatThreads.connect()` a souběžně volala `ChatThreads.list()`:
čekání **0,00 s**. Helper po bootstrapu a validaci schématu provede
`commit()` (`chat_threads.py` ve `connect`, `return closing(db)`); writer
rezervace tedy kryje jen otevření, nikoli celé čtení. Viz B-LOCK-11.

### Nálezy B-LOCK

Sloupec „I/O pod zámkem“: G = Git subprocess/snapshot, D = disk/SQLite,
N = síť, — = jen paměť. „Ctl“ = blokuje status/cancel téže práce.

| ID | Pri | Zdroj | Chráněný invariant / čtenáři a zapisovatelé | I/O | Ctl | Důkaz | Verdikt |
|---|---|---|---|---|---|---|---|
| B-LOCK-01 | P1 | `projects.py:127`, `workspace.py:57`, `journal.py:60` | EX bootstrap journalu (DDL, owner check, `chmod`, `fsync` adresáře) při **každém** výchozím otevření `Projects.workspace()`, tedy i u čtenářů. Invariant je nutný jen při chybějícím journalu. Jen 6 ze 134 volání `.workspace(` předává `for_read`/`for_snapshot`. | D | ne | R1 | převést čtení na SH/attach (`open_for_read`); EX jen při chybějícím či neinicializovaném journalu |
| B-LOCK-02 | P1 | `artifact_history.py:33`, `conflict_resolution.py:73`, `artifact_git.py:57`, `artifact_git.py:105`, `artifact_actions.py:32`, `artifact_actions.py:81`, `artifacts.py:36`, `cross_references.py:94`, `:113`, `:195`, `:332`, `reporting.py:69`, `google_drive_import.py:463`, `source_import.py:97`, `context_builder.py:196`, `:385`, `workspace.py:534` (`receipt`), `project_repair.py:676` | Čistá čtení (historie, konflikt, Git status/preview, plan draft, validace plánu, otevření dokumentu, reference, pin, výběr zdrojů, Context Manifest, receipt) drží EX journalu přes `git snapshot` a `validate_snapshot`. Čtenáři se navzájem odmítají, i když žádný nezapisuje. | G, D | ne | R1 (`history`), ostatní S | převést čtení na SH nebo snapshot (`committed_snapshot`); pending/HEAD kontrolu ponechat |
| B-LOCK-03 | P2 | `cross_references.py:94`, `:113`, `:195`, `:332`, `reporting.py:69`, `artifacts.py:36`, `federation_sync.py:364`, `git_transfer.py:97` | Čtenáři volají `_read_locked`, který může přestavět SQLite index. To zápis do indexu a EX potřebuje, ale jen při zastaralém indexu. | G, D | ne | S | převést na `_read_current_index` (SH, EX jen pro revalidovanou opravu) |
| B-LOCK-04 | P2 | `desktop_ui.py:8759`, `ide_bridge_panel.py:410`, `roadmap_dependencies.py:254`, `rss_monitoring.py:291` | Bodová kontrola „existuje nativní operace?“ pod EX bez vlastní mutace pod týmž zámkem. U `rss_monitoring` se vlastní stav mění až po uvolnění journalu, takže EX neposkytuje bariéru proti souběžnému startu. | D (G) | ne | S | převést čtení na SH; u `rss_monitoring` T5 posoudí, zda je potřebná skutečná bariéra (CAS na stavu pollu) |
| B-LOCK-05 | P2 | `task_queue.py:134`, `task_queue.py:231`, HTTP `task_queue_status` lane | Akce `status` (bez zápisu, `should_write = action != 'status'`) drží výhradní queue flock s `LOCK_NB` a EX journalu. Souběžný status vrátí „Frontu právě mění jiný požadavek“. HTTP lane `task_queue_status` je navíc jedna pro všechny projekty (A11). | G, D | ano (status) | S | převést status na snapshot čtení; zápisy ponechat serializované per projekt a uživatele |
| B-LOCK-06 | P2 | `rss_sources.py:46` (`view`), `rss_sources.py:93` (`refresh`), HTTP `rss_sources` lane | A07 trvá. HTTP view sdílí lane s refresh/save/import (6 rout). `view` drží cache mutex přes normalizaci, řazení a `deepcopy`; od #146 navíc přes `store.load()` (SQLite) při každém zobrazení. | D | ano (view) | S nad `0e69cc5`; R v auditu 11. 11. | zúžit kritickou sekci (snapshot pod mutexem, zpracování mimo); oddělit HTTP čtení od fetch |
| B-LOCK-07 | P2 | `http_ui_admission.py:98`, `extensions/workspace-bridge/bridge.js:158` | A08 trvá. Browser drží jeden request na lane key do EOF včetně Web Lock napříč okny; rozšíření má jeden FIFO na `connection_id` pro všechny projekty, sidebar, sync a updater. | N | nepřímo | S | po oddělení backendových čtenářů zúžit klíč; FIFO účinků a timeout-before-send zachovat |
| B-LOCK-08 | P2 | 21× `sqlite3.connect(..., timeout=30)` v 18 modulech (např. `chat_threads.py`, `publication_cms.py`, `publication_cloudflare.py`, `ollama_backend.py`) | A09 trvá. Přímé connecty (31 modulů) obcházejí bounded HTTP politiku `sqlite_connection` (17 modulů); čekání až 30 s. | D | — | S | sjednotit přes `sqlite_connection`; nejdřív zmapovat, které cesty jsou HTTP dosažitelné |
| B-LOCK-09 | P2 | `federation_catalog.py:351-352`, `replication_control.py:143-144`, `federation_sync.py:1610` | A10 trvá. Po `join(timeout=20/35/65)` se reference na thread nastaví na `None` bez `is_alive()`. Není to zámek, ale ztráta vlastnictví workeru. | — | — | S | deadline-aware drain s výsledkem clean/unclean; živou referenci zachovat |
| B-LOCK-10 | P2 | HTTP `reference` lane (`/v1/roadmap/graph`, `/v1/document-patterns`), `julia` lane (12 rout včetně `status` a `cancel`), `node_telemetry.py:260` | A11 trvá. Nesouvisející reference výpočty sdílejí mutex. `julia/cancel` má rezervovaný worker slot, ale stejný `julia_lane` mutex jako publish. Telemetrie drží mutex i přes `nvidia-smi` (timeout 2 s). | G, N (Julia), proces | ano (Julia) | S nad `0e69cc5`; R v auditu 11. 11. | oddělit domény a control cestu; telemetrii zúžit na stavové delty |
| B-LOCK-11 | P3 | `chat_threads.py:43`, `role_workflows.py`, `summary_tasks.py`, `output_execution.py` (`connect`) | Každé otevření včetně čtení (`get`, `list`) zakládá `BEGIN IMMEDIATE`, validaci a případnou migraci schématu, pak `commit`. Čtení se neserializují (R2), ale čtenář čeká až 30 s za cizí zápisovou transakcí a sám krátce blokuje zapisovatele. | D | ne | R2 | zúžit: read-only otevření (vzor `list_project_readonly`, `export_readonly`) |
| B-LOCK-12 | P3 | `message_pools.py:206` (`export`), `:256` (`view`, výchozí `read_only=False`) | Zobrazení poolu ve výchozím režimu provádí `_cleanup` pod `BEGIN IMMEDIATE`. Čtení má zápisový vedlejší účinek; read-only varianta existuje. | D | ne | S | zdokumentovat nebo oddělit cleanup od čtení |

### Zámky bez nálezu

| Zámek | Zdroj | Důvod verdiktu **nutný** |
|---|---|---|
| Journal writer EX při zápisu a recovery | `journal.py:127`, `:154`, `workspace.py:124`, `:149`, `:236`, `:265`, `:372` | ADR 0003: serializace zápisu a roll-forward; nezpochybňuje se. |
| Journal SH | `workspace.py:84`, `:365`, `:390`, `projects.py:152` | Správný vzor čtenáře. |
| Cancel/zrušení s vlastní mutací pod EX | `roadmap_refinement.py:924`, `task_file_edit.py:193`, `local_change_resolution.py:94` | Bariéra proti souběžnému startu nativní operace; mutace probíhá pod zámkem. |
| Zápisové a federační operace pod EX | `federation_sync.py:504`, `:910`, `project_replication.py:298`, `project_repair.py:755`, `cross_references.py:247`, `source_collector.py:220`, `:365`, `reporting.py:269` | Zápis nebo příprava zápisu s `_writable()`; dry-run `reporting.py:269` validuje kandidáta stejnou cestou jako zápis. |
| Node registry EX/SH | `administration.py:118`, `:180` | Zápis EX, čtení SH; vzorový stav. |
| Singletony workerů (`LOCK_NB`) | `composable_monitoring.py:68`, `rss_monitoring.py:103`, `roadmap_refinement.py:407`, `source_collector.py:158`, `julia_computation.py:534`, `project_creation.py:188`, `project_deletion.py:85`, `project_repair.py:183`, `federation_sync.py:113`, `:1333` | Jeden běžící worker či operace; neblokující pokus bez čekání. |
| Zapisovatelé node stavu | `deployment_targets.py:44`, `publication_cms.py:125`, `publication_cloudflare.py:278`, `replication_control.py:51`, `project_creation.py:724`, `git_transfer.py:191`, `google_drive_import.py:204` | Zápis lokálního stavu. Delší I/O pod zámkem u CMS/Cloudflare/Drive pokrývá B-LOCK-08 (A09); `git_transfer` drží globální zámek přes staging a `git bundle verify`, souběh přenosů nebyl měřen. |
| HTTP admission primitiva | `local_api.py:72-89`, `:345`, `request_ownership.py:71-122` | Omezená kapacita a krátké admission čekání (ADR 0050). Problémem je mapování domén (B-LOCK-05/06/10), nikoli primitiva. |
| Procesní mutexy nad malými mapami | `workspace.py:29`, `sync_retry.py:12`, `sync_fingerprint.py:39`, `sync_diagnostics.py:29`, `backend_availability.py:16`, `task_stream.py:18`, `:156`, `julia_workspace.py:90`, `federation_sync.py:1466`, `http_ingress.py:67`, `history_validation.py:20` | Krátké sekce nad pamětí nebo omezená kapacita; žádné I/O čtenáře pod nimi nebylo nalezeno. |
| Konfigurační RLock providerů | `chat_service.py:457` (pouze `configure*`, `reset_backend`) | Chrání jen mutace konfigurace. |
| Monitoring | `monitoring.py:78-85`, `monitoring_deletion.py:119`, `monitoring_migration.py:262`, `:324` | Neblokující singleton zpracování a správa služeb; HTTP stránku pokrývá náprava A02/A06. |
| SQLite IMMEDIATE v zápisových metodách | zbylé funkce L04 (`prepare`, `finish`, `_dispatch`, `put`, `save`, …) a read-only režimy `julia_computation`, `reporting_scheduler`, `x_connector` | Zápisové transakce; čtení mají `mode=ro`. |

### Ověření T2 a limity

- Každé tvrzení „čtenář blokuje čtenáře“ má zdrojové místo. B-LOCK-01
  a B-LOCK-02 (`history`) jsou reprodukované R1; ostatní řádky jsou
  výslovně statické. Podezření u SQLite store R2 vyvrátila a nález
  B-LOCK-11 má proto prioritu P3.
- A07–A11 jsou nad `0e69cc5` ověřené staticky: mapování lane, FIFO klíč,
  přímé connecty, join bez `is_alive` a telemetrie se od auditu 11. 11.
  nezměnily, s výjimkou SQLite `store.load()` přidaného do RSS `view`.
  Původní reprodukce A07 a A11 nebyly znovu spuštěny.
- Sondy R1/R2 neměnily runtime kód a běžely v dočasných adresářích bez
  sítě a peerů. Nebyl proveden zátěžový test, formální důkaz absence
  deadlocku ani měření desktop režimu s blokujícím čekáním.
- Audit nenavrhuje oslabení journalu: zápisy nad stejnými nativními daty
  zůstávají serializované podle ADR 0003.
