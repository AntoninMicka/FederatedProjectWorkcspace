<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# AUDIT-B1 — zámky, verzové podmínky a podivnosti

Stav dokumentu: **AUDIT-B1-T1 až T5 designed** (metodika, inventura, audit
zámků, verzových podmínek, dalších podivností a prioritizace). Platné priority
a zařazení nálezů jsou v [sekci T5](#audit-b1-t5--prioritizace-a-návrh-nápravných-dávek);
priority v tabulkách T2–T4 jsou jejich výchozí odhad.

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

## AUDIT-B1-T3 — podmínky vázané na verzi a revizi

Výchozí commit `0e69cc5`. Prošel jsem 139 literálových verzových podmínek
z V01 (52 modulů), 6 porovnání s pojmenovanou konstantou
(`backend_catalog`, `backend_contract`, `model_catalog`), verzové brány
rozšíření, revizní vazby uvedené v zadání a legacy/compat větve z V04.
V03 (322 porovnání revize, digestu či fingerprintu) sloužil jako seznam
modulů; neprocházel jsem jej řádek po řádku, viz [limity](#ověření-t3-a-limity).

### Dva významy „verze N+1“

- **(a) za běhu:** program dostane data nebo zprávu vyšší verze (downgrade,
  novější peer, novější rozšíření, ručně zacommitovaný artefakt).
- **(b) při vývoji:** do kódu se přidá verze N+1 a některá větev `== N`
  nebo `in {…}` se nedoplní.

Kategorie výsledku podle metodiky: explicitní chyba / migrace / viditelný
degradovaný stav / tiché vypnutí / tichý fallback. U (b) je „tichý fallback“
odhad z cesty kódu, nikoli pozorované chování.

### Souhrn

Pro (a) jsem **nenašel žádné tiché vypnutí**. Neznámá vyšší verze dat,
DB schématu i zpráv končí explicitní chybou, starší verze migrací.
Problémem je dosah a srozumitelnost chyb: jediný artefakt s metadaty v5
znepřístupní celý projekt a hlášky nerozlišují „nepodporovaná novější
verze“ od poškozených dat. Tichý fallback existuje jen jako vývojová past (b)
v autonomii. Revizní vazby ze zadání jsou viditelné, a tedy legitimní.

### Reprodukce

**R3 — artefakt s metadaty v5 v jinak platném projektu.** Dočasný projekt,
skutečné `Artifacts`/`Projects`; metadata se zvýší přímo v Git commitu.
Spuštění: `PYTHONPATH=$PWD python3 probe_r3.py`.

```python
"""AUDIT-B1-T3 probe: one artifact with metadata schema_version N+1 in a committed project."""
import json, subprocess, tempfile
from pathlib import Path
from uuid import uuid4
from spikes.artifacts import Artifacts, main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.storage import Git

with tempfile.TemporaryDirectory() as temp:
    base = Path(temp); node = base / 'node.json'; root = base / 'project'
    pid = ProjectCreation(node).create('Project', str(root), str(uuid4()))['id']
    artifacts = Artifacts(node); git = Git(root)
    artifacts.save(dict(project_id=pid, artifact_id=main_todo_id(pid), base_head=git.head(),
                        title='T', body='- [ ] Task\n', new=True), str(uuid4()))
    print('before:', len(artifacts.open(pid)['documents']), 'documents')
    path = root / 'artifacts' / main_todo_id(pid) / 'metadata.json'
    meta = json.loads(path.read_text()); meta['schema_version'] = 5
    path.write_text(json.dumps(meta, indent=2) + '\n')
    subprocess.run(['git', '-C', str(root), 'commit', '-qam', 'newer metadata'], check=True,
                   env={'GIT_AUTHOR_NAME': 'n', 'GIT_AUTHOR_EMAIL': 'n@x', 'GIT_COMMITTER_NAME': 'n',
                        'GIT_COMMITTER_EMAIL': 'n@x', 'PATH': '/usr/bin:/bin'})
    for name, call in (('artifacts.open', lambda: artifacts.open(pid)),
                       ('projects.open', lambda: artifacts.projects.open(pid))):
        try:
            call(); print(name, '-> ok')
        except Exception as exc:
            print(name, '->', type(exc).__name__ + ':', exc)
```

Výsledek: `before: 1 documents`; po commitu `artifacts.open` i
`projects.open` → `ValidationError: Unknown schema version`.

**R4 — plán autonomie v4 v `parse_plan`.** Přímé volání
`spikes.action_autonomy.parse_plan` s `schema_version: 4`:
jen se základními poli → `ValidationError: Unsupported autonomy plan schema`;
s poli verze 3 (`countdown_seconds`, `policy`) →
`ValidationError: Unknown or missing autonomy plan field`. Tichý fallback
B-VER-02 je tedy za běhu nedosažitelný, ale hláška u druhé varianty
neuvádí verzi.

### Nálezy B-VER

| ID | Pri | Zdroj | Podmínka | N+1 | Výsledek | Důkaz | Doporučený kontrakt |
|---|---|---|---|---|---|---|---|
| B-VER-01 | P2 | `metadata.py:303` (přes `validate_snapshot`) | Metadata artefaktu musí mít `schema_version in {1, 2, 3, 4}`. | (a) | Explicitní chyba, ale pro **celý projekt**: otevření ani čtení neprojde a hláška neuvádí artefakt, nalezenou verzi ani potřebu novějšího programu. | R3 | Chyba s ID artefaktu, nalezenou a podporovanou verzí a výzvou k aktualizaci. Zda připustit viditelný degradovaný stav jednoho artefaktu, je architektonická otázka (sémantická validace celého snapshotu, ADR) pro T5. |
| B-VER-02 | P2 | `autonomy_service.py:144`, `:555`, `:569`; `action_autonomy.py:924`, `:927`, `:1543`, `:1582` | Chování plánu se větví podle `plan_schema_version == 3` nebo `in {2, 3}`; jinak se použije logika v1/v2 (`_append_search_continuation`, výchozí `countdown_seconds`, bez automatického `advance`, bez `policy`). | (b) | Tichý fallback na starou logiku pro budoucí plán v4. Za běhu nedosažitelné (R4). | S, R4 | Větvit podle deklarované schopnosti plánu (např. přítomnost `policy`), nebo vyčerpávající výčet verzí s explicitní chybou pro neznámou. |
| B-VER-03 | P3 | `administration.py:213`, `extensions/workspace-bridge/bridge.js:56`, `federation_sync.py:264`, `federation_catalog.py:142`, `action_autonomy.py:361-362` | Neznámá vyšší verze registru, pairing, výměny obsahu, katalogu peeru či plánu. | (a) | Explicitní chyba s hláškou, která verzi nezmiňuje nebo ji slučuje s jinou chybou: „Invalid registry identity/version“, „Neplatné nebo expirované propojení.“, „Invalid content sync exchange“, „Invalid project catalog“, „Unknown or missing autonomy plan field“. | S, R4 | Samostatná typovaná chyba „nepodporovaná verze N, podporováno ≤ M“ před kontrolou polí; u federace a rozšíření uvést, kterou stranu aktualizovat. |
| B-VER-04 | P3 | `ide_bridge.py:231` (`set(message) <= {…}`), `bridge.js:56`, `updater.js:46` | Mezi rozšířením a backendem není deklarovaná protokolová verze. Backend verzi rozšíření nekontroluje; nové pole od novějšího rozšíření odmítne jako „Invalid message“; rozšíření přijímá pairing `{1, 2}`. Updater jen nabízí aktualizaci. | (a) | Explicitní, ale nerozlišená chyba; kompatibilitu nelze ověřit předem. | S | Protokolová verze v pairing/exchange a srozumitelná nekompatibilita na obou stranách. |

### Podmínky bez nálezu

| Skupina | Zdroj | Výsledek při N+1 | Verdikt |
|---|---|---|---|
| Lokální DB schémata | `action_autonomy.py:719`, `chat_threads.py:64`, `role_workflows.py:100`, `summary_tasks.py:66`, `reporting_scheduler.py:107-108`, `storage.py:240`, `project_repair.py:324`, `project_creation.py:199` | Starší verze migrace; vyšší explicitní chyba („Unsupported …“, u indexu „index retained“). | správný kontrakt |
| Node registry | `administration.py:141-151`, `:187`, `:207-213` | Migrace při startu; vyšší verze explicitní chyba (hlášku řeší B-VER-03). Sady polí `in {…}` při přidání verze selžou explicitně, ne tiše. | správný kontrakt |
| Sloupce podle `version >= N` | `chat_threads.py:161-174` | Volá se jen za bránou `1..6` (`:64`); `>=` je dopředně správný směr. | správný kontrakt |
| Dokumenty, zprávy a deskriptory `require(schema_version == 1)` | ~80 řádků V01 (`research_workflow`, `output_*`, `ollama/openai/atlascloud/direct/media_backend`, `public_source`, `presentation_*`, `project_replication`, `configuration`, `module_manifest`, …) a pojmenované konstanty v `backend_catalog`, `backend_contract`, `model_catalog` | Explicitní chyba. | správný kontrakt; srozumitelnost hlášek jako B-VER-03 |
| Vazba aktivace autonomie | `action_autonomy.py:1054`, `:1160` | Digest aktivace musí sedět; náhrada plánu (`replace_plan`) aktivaci zruší a vyžaduje novou. | legitimní viditelná kontrola |
| Verze CMS modulu | `publication_cms.py:335-336`, `status` | Změna verze modulu → viditelný stav „enable it again after review“, `compatible: false`. | legitimní viditelná kontrola |
| Context Manifest | `context_builder.py:385-396` | Změna HEAD, autority, binding či policy revize → explicitní chyba před odesláním. | legitimní viditelná kontrola |
| Discovery katalog OpenAI | `openai_backend.py:244-265`, `model_catalog.py:307-313` | Jiná binding/credential revize nebo legacy soubor → `freshness: 'stale'`. | viditelný degradovaný stav |
| Schválení náhledem, pin peeru, CAS revize | `preview_sha256`, fingerprint peeru, `expected_head` (V03) | Explicitní odmítnutí s výzvou obnovit náhled. | legitimní bezpečnostní kontrola (omezení zadání) |
| Legacy větve s verzovým významem | `presentation_documents.py:58`, `:312-336` (v1 → v2 v paměti), `chat_threads.py` (legacy tabulky), `ollama_backend.py:454-478` (`legacy_digest` pro retry), `roadmap_rebuild.py:480-568` (karanténa) | Migrace nebo zachování identity požadavku. | ponechat; mrtvý kód a skryté legacy UI (`desktop_ui.py:425`, `:563`) patří do T4 |
| Discovery rozšíření | `bridge.js:97` (`ENOENT` → uložený endpoint) | Dokumentovaná kompatibilita se starším desktopem; chybný endpoint selže viditelně. | ponechat |

### Ověření T3 a limity

- Žádné „tiché vypnutí“ typu (a) jsem nenašel; tichý fallback B-VER-02 je
  doložen cestou kódu a jeho nedosažitelnost za běhu sondou R4.
- R3 a R4 běžely v dočasných adresářích bez změny runtime kódu.
- V03 jsem neprocházel řádek po řádku; ověřené jsou revizní vazby uvedené
  v zadání a vzorek tichých návratů (`if … != …: return/continue`), který
  našel jen legitimní filtrování (`reporting_schema.py:828`,
  `report_outputs.py:66`).
- Neověřeno: validaci konfigurace CMS verze 2+ provádí externí modul
  (`publication_cms.py:262-305` předává `sites.json` skriptu); kód modulu
  jsem nečetl.
- Commit `ed1d536` (po výchozím commitu) mění revizní vazbu fronty:
  review se už neváže na aktuální `queue_revision`, ale na neměnný packet.
  Zhodnotí ji T5 nad aktuálním HEAD.

## AUDIT-B1-T4 — další podivnosti

Výchozí commit `0e69cc5`. Vstupem byla inventura O01–O11 a I03/I04.
Široké `except` (O01) jsem klasifikoval podle těla handleru: 37 chybu
znovu vyhodí nebo přeloží, 29 vrací chybový stav či odpověď, 4 logují,
32 předávají chybu jinak (UI hláška, `last_errors`, stav řádku) a 4 ji
tiše spolknou.

### Souhrn

Skutečně skryté chyby jsou vzácné a soustředěné ve smyčkách schedulerů.
Větším rizikem pro údržbu je vazba na text: text chybové hlášky slouží
jako stav přes hranici procesu a stovky testů ověřují doslovný zdrojový
text inline UI místo chování. Ostatní nálezy jsou duplicity s nízkou
prioritou. Automatická kontrola odkazů dokumentace na kód nenašla žádný
chybějící cíl.

### Nálezy B-ODD

| ID | Pri | Zdroj | Podivnost | Důkaz | Verdikt |
|---|---|---|---|---|---|
| B-ODD-01 | P2 | `federation_catalog.py:317`, `federation_sync.py:1573`, `replication_control.py:109`, `rss_subscription_sync.py:129` | Smyčky automatické synchronizace spolknou každou výjimku (`except Exception: pass`). Trvalý stav se zapíše jen v části cest: RSS zapisuje chybu jen uvnitř `try` (`prepare()` na `rss_subscription_sync.py:107` je mimo), katalog jen pro vyjmenované typy výjimek (`federation_catalog.py:297-305`). Neočekávaná chyba, například programátorská, zmizí bez logu i stavu. | S | zjednodušit: logovat a zapsat obecný chybový stav peeru; očekávané typy ponechat |
| B-ODD-02 | P2 | `extensions/workspace-bridge/extension.js:155` ↔ `ide_queue.py:136`, `:203` (po `ed1d536` `:181`, `:185`); `bridge.js:130` ↔ HTTP odpověď `{'error': 'server busy'}` (`local_api.py:352`, `:365`) | Text chybové hlášky slouží jako stav přes hranici procesu (backend → rozšíření). Commit `ed1d536` musel hlášku změnit na obou stranách současně (`===` → `startsWith`); starší rozšíření s novým backendem by čekání na review nepoznalo. | S, historie `ed1d536` | zjednodušit: typovaný kód stavu (např. `waiting_review: true`, `busy: 'server'`) vedle lidské hlášky |
| B-ODD-03 | P3 | `desktop_ui.py:9793`, `project_repair.py:389`, `role_workflow_service.py:205`, `summary_service.py:189`, `composable_monitoring.py:404` | Rozhodování podle textu výjimky nebo uložené hlášky v rámci procesu (`str(exc) == …`, `'unavailable to this owner' in str(exc)`). Změna formulace tiše změní větvení. | S | zjednodušit: typovaná výjimka nebo kód |
| B-ODD-04 | P2 | `tests/test_desktop.py` a další (O10) | Testy ověřují doslovný zdrojový text: 531 asercí `assertIn(…, JS)` a 626 asercí na `HTML` jen v `test_desktop` (celkem 736 asercí na HTML/zdroj ve všech testech), včetně víceřádkových fragmentů kódu s přesnými mezerami a skrytého legacy markupu (`test_desktop.py:871`, `test_backend_catalog.py:88`). Takový test refaktoring rozbije bez změny chování a chování nedokládá. Behaviorální browser testy existují jen pro část oblastí (`tests/*_browser.py`, `tests/*.test.js`). | S | zjednodušit: kritické toky pokrýt behaviorálními browser testy, textové kontroly ponechat jen pro skutečné kontrakty (ID prvků, CSP) |
| B-ODD-05 | P3 | `federation_catalog.py:28`, `federation_sync.py:55`, `project_replication.py:36`; joiny `federation_catalog.py:351`, `replication_control.py:143`, `federation_sync.py:1610` | Stejnojmenná `NETWORK_TIMEOUT` má ve třech modulech hodnoty 15, 60 a 30 s. Bounded `join` při shutdownu má tyto hodnoty natvrdo + 5 s (20/35/65) jako literál. Celkem 91 číselných `timeout=` v 59 modulech, z toho 31× `30` převážně u SQLite (B-LOCK-08). | S | zjednodušit: pojmenované rozpočty podle zdroje; join odvodit z konstanty |
| B-ODD-06 | P3 | peer politiky `federation_catalog.py:234`, `federation_sync.py:1094`, `project_replication.py:571`, `rss_subscription_sync.py:88`, `sync_fingerprint.py:171`; bind/endpoint `network_backend.py:111`, `web_server.py:742`, `http_deadline.py:99`, `:106`, `deployment_targets.py:70`, `lxc_deployment.py:83`, `:107` | Pět kopií téměř stejné politiky „soukromá IPv4 adresa peeru“; replikace na rozdíl od ostatních zakazuje loopback. Jen IPv4 je zdokumentovaný předpoklad (`docs/desktop-network.md:8`, ADR 0020), chyby jsou explicitní. | S | ponechat předpoklad; zjednodušit do jednoho helperu; rozdíl u loopbacku zdokumentovat nebo sjednotit |
| B-ODD-07 | P3 | `desktop_ui.py:425` (`legacy-home-diagnostics`), `desktop_ui.py:563` (`backend-settings-legacy`) | Skryté legacy bloky UI stále nesou funkční prvky napojené na JS (`chat-backend-form`: 3 odkazy) a testy ověřují jejich markup. Není doloženo, zda je cesta k nim dosažitelná. | S | odstranit, nebo zdokumentovat, proč zůstávají; dosažitelnost ověří T5 |
| B-ODD-08 | P3 | `desktop_ui.py` (I03: 9 914 řádků, 119 řádků nad 500 znaků; I04: 169 v celém `spikes/`) | Celé HTML/CSS/JS UI je inline v Python řetězcích. Ztěžuje review i diff a umožňuje B-ODD-04. | S | zjednodušit: statické assety mimo Python; stylistické, proto P3 |
| B-ODD-09 | P3 | `web_server.py:119` (`WebHandler(DesktopHandler)`), 24 rout dispatchovaných v obou handlerech (např. `/v1/task-queue`, `/v1/media/preview`, `/v1/workflows/prepare`) | Web přepisuje dispatch kvůli RBAC, vlastníkovi a privacy (`allow_local_only=False`). Oddělení je oprávněné, ale validace se udržuje dvakrát; divergence nebyla měřena. | S | zjednodušit: sdílený dispatch s parametrem politiky |
| B-ODD-10 | P3 | `desktop_ui.py:8467`, `:8468`, `extensions/workspace-bridge/extension.js:187` | Prázdné `catch {}` tiše ztratí chybu prezentačního pollu, nastavení poměru stran a hlášení nedostupnosti. Ostatních 10 z 13 (O04) je best-effort (měření času, parsování URL, reload se zachovanou původní hláškou). | S | zobrazit nebo zalogovat u tří tichých; ostatní ponechat |

### Podivnosti bez nálezu

| Skupina | Zdroj | Verdikt |
|---|---|---|
| Překlad a vrácení chyby | 37 + 29 širokých `except` (O01) | ponechat |
| Validace převádějící výjimku na neplatnou hodnotu | `action_autonomy.py:113` | ponechat |
| Liveness vzorek bez detailu | `backend_availability.py:47` (komentář: diagnostika může obsahovat privátní endpoint) | ponechat |
| Retry přechodných závodů při startu scheduleru | `federation_catalog.py:341`, `federation_sync.py:1600`, `replication_control.py:133` | ponechat; zdokumentováno komentářem |
| Rollback s opětovným vyhozením | `network_backend.py:177` | ponechat |
| Odkazy dokumentace na kód | 67 cest v backticku, 56 Markdown odkazů na `spikes/`/`tests/`/`extensions/`/`scripts/`, 103 testovacích modulů `tests.test_*` v `*.md` a `docs/` | všechny cíle existují nad `0e69cc5` |

### Ověření T4 a limity

- Každý nález má zdrojové místo; stylistické nálezy (B-ODD-08) mají P3.
- Klasifikace O01 je heuristická podle prvních řádků těla handleru;
  tiché a hraniční případy jsem prošel ručně.
- Kontrola dokumentace ověřila jen existenci odkazovaných souborů
  a testovacích modulů, nikoli pravdivost tvrzení o chování.
- B-ODD-02 a B-ODD-07 nemají dynamickou reprodukci; B-ODD-04 hodnotí
  kvalitu důkazů, nikoli funkčnost aplikace.

## AUDIT-B1-T5 — prioritizace a návrh nápravných dávek

Vstupem jsou nálezy T2–T4 (12 B-LOCK, 4 B-VER, 10 B-ODD) nad výchozím
commitem `0e69cc5` a kontrola, zda je pozdější commit `ed1d536` nezměnil.
Zařazení je **návrh k lidskému review**; autoritativní plán mění jen
Workspace lifecycle. Nálezová ID nejsou úkoly Workspace.

### Stav nálezů nad aktuálním HEAD

`ed1d536` (`fix(ide-queue): prevent review and refresh circular blocking`)
mění `ide_queue.py`, `task_queue.py`, `ide_bridge.py`, rozšíření a ADR 0062.
Žádný nález neodstraňuje:

- B-LOCK-05 trvá: `TaskQueue.execute` drží pro `status` stejné zámky;
  změna se týká jen hodnocení dokončených položek.
- B-ODD-02 trvá: rozšíření nyní rozpoznává hlášku přes `startsWith`
  (`extension.js:155`), stav se tedy dál odvozuje z textu.
- Review hlášení se nově váže na neměnný packet místo aktuální
  `queue_revision`; nativní writer dál kontroluje HEAD a podmínky úkolu.
  Je to zdokumentováno v ADR 0062 a odpovídá pravidlu B3-T1 (vazba na
  stabilní identitu, ne revizi). Nový nález nevzniká.

Commit je runtime oprava mimo rozsah auditní dávky („bez změny runtime
kódu“). Rozhodnutí, zda ho ponechat v PR dávky, nebo přesunout do vlastní
větve, je na uživateli.

### Konzistence s ADR

| Oblast | ADR | Závěr |
|---|---|---|
| B-LOCK-01 až 05, 11 | [ADR 0003](adr/0003-coordinated-operation.md#upřesnění-čtecího-vlastnictví-11-11-2026) | Navržené nápravy aplikují už přijatý vzor (SH čtení, uvolnění SH a EX pro revalidovanou obnovu indexu, neměnný Git mimo zámek). Bootstrap a migrace zůstávají výhradní; B-LOCK-01 jen nespouští bootstrap nad inicializovaným journalem. Zápisy zůstávají serializované. ADR se nemění. |
| B-LOCK-06 až 10 | [ADR 0050](adr/0050-bounded-http-monitor-concurrency.md) | Bounded kapacita a krátké admission čekání zůstávají; mění se mapování domén a rozsah kritických sekcí. Pokud B2 změní počty workerů nebo rezervu, vyžaduje to doplnění ADR 0050. |
| B-VER-01 až 04, B-ODD-02 | [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md), [ADR 0060](adr/0060-local-file-ide-bridge.md), [ADR 0062](adr/0062-pinned-queue-handoff.md) | Pravidlo B3-T1 odpovídá ADR 0082 (aktivace na stabilním ID bloku) a ADR 0062 po `ed1d536`. Rozhodnutí o viditelném degradovaném stavu jednoho artefaktu (B-VER-01) by měnilo princip sémantické validace celého snapshotu: vyžaduje ADR. Protokolová verze rozšíření (B-VER-04) doplňuje ADR 0060. |
| B-ODD-06 | `docs/desktop-network.md`, [ADR 0020](adr/0020-lxc-web-viewer.md) | Jen IPv4 je zdokumentovaný předpoklad; B4-T2 rozhodne o IPv6 výslovně. |

### Prioritizovaný seznam a zařazení

Platná priorita je výsledkem T5. Proti výchozím odhadům T2–T4 se nemění
žádná priorita; mění se jen zařazení dvou nálezů mimo jejich kategorii
(B-ODD-02 do B3 kvůli kompatibilitě rozšíření a backendu, B-LOCK-09 do
B2-T3 kvůli recovery).

| Pořadí | ID | Pri | Stručně | Zařazení |
|---:|---|---|---|---|
| 1 | B-LOCK-01 | P1 | EX bootstrap journalu při každém otevření projektu | AUDIT-B2-T1 |
| 2 | B-LOCK-02 | P1 | Čistá čtení pod EX journalu přes snapshot a validaci | AUDIT-B2-T1 |
| 3 | B-LOCK-03 | P2 | Čtení s možnou obnovou indexu vždy pod EX | AUDIT-B2-T1 |
| 4 | B-LOCK-05 | P2 | Status fronty pod výhradními zámky, globální HTTP lane | AUDIT-B2-T1 |
| 5 | B-LOCK-04 | P2 | Bodová kontrola nativní operace pod EX; u RSS bez skutečné bariéry | AUDIT-B2-T1 (čtení na SH); bariéru `rss_monitoring` posoudit v AUDIT-B2-T3 |
| 6 | B-LOCK-06 | P2 | RSS view pod cache mutexem a sdílenou lane s fetch (A07) | AUDIT-B2-T2 |
| 7 | B-LOCK-10 | P2 | Sdílená reference/Julia lane, telemetrie pod mutexem (A11) | AUDIT-B2-T2 |
| 8 | B-LOCK-08 | P2 | Přímé SQLite connecty s čekáním 30 s mimo bounded politiku (A09) | AUDIT-B2-T2 |
| 9 | B-LOCK-07 | P2 | Klientská FIFO serializace v prohlížeči a rozšíření (A08) | AUDIT-B2-T2, až po oddělení backendových čtenářů v B2-T1 |
| 10 | B-LOCK-09 | P2 | Ztráta reference na živý worker při shutdownu (A10) | AUDIT-B2-T3 |
| 11 | B-VER-01 | P2 | Artefakt s metadaty N+1 znepřístupní celý projekt | AUDIT-B3-T1 (pravidlo, případně ADR), AUDIT-B3-T2 (hláška), AUDIT-B3-T3 (fixture R3) |
| 12 | B-VER-02 | P2 | Větve `plan_schema_version == 3` jako past pro plán v4 | AUDIT-B3-T2 |
| 13 | B-ODD-02 | P2 | Text hlášky jako stav mezi backendem a rozšířením | AUDIT-B3-T2 (typovaný stav), AUDIT-B3-T3 (starší rozšíření × nový backend) |
| 14 | B-ODD-01 | P2 | Smyčky synchronizace spolknou výjimky bez logu a stavu | AUDIT-B4-T1 |
| 15 | B-ODD-04 | P2 | Testy doslovného zdrojového textu UI místo chování | AUDIT-B7-T1 (nová dávka) |
| 16 | B-LOCK-11 | P3 | Čtení SQLite store otevírá writer transakci | AUDIT-B2-T1 |
| 17 | B-VER-03 | P3 | Hlášky nerozlišují nepodporovanou verzi | AUDIT-B3-T2 |
| 18 | B-VER-04 | P3 | Chybí protokolová verze rozšíření–backend | AUDIT-B3-T1, AUDIT-B3-T3 |
| 19 | B-ODD-03 | P3 | Větvení podle textu výjimky v procesu | AUDIT-B4-T1 |
| 20 | B-ODD-10 | P3 | Tři tiché `catch {}` v UI a rozšíření | AUDIT-B4-T1 |
| 21 | B-ODD-05 | P3 | Stejnojmenné `NETWORK_TIMEOUT` s různými hodnotami, odvozené literály | AUDIT-B5-T1 (dříve B4-T2) |
| 22 | B-ODD-06 | P3 | Pět kopií IPv4 politiky peeru | AUDIT-B5-T1 (dříve B4-T2) |
| 23 | B-ODD-07 | P3 | Skryté legacy bloky UI napojené na JS | AUDIT-B6-T1 (dříve B4-T3) |
| 24 | B-ODD-09 | P3 | Duplicitní desktop/web dispatch 24 rout | AUDIT-B6-T1 (dříve B4-T3) |
| 25 | B-LOCK-12 | P3 | Zobrazení poolu provádí cleanup | **odmítnuto**: read-only varianta `export_readonly` existuje, cleanup jen vynucuje retenci a nemá doložený dopad |
| 26 | B-ODD-08 | P3 | Obří inline UI | **odloženo, bez dávky**: stylistické; přesun assetů je velký refaktoring a bez behaviorálních testů (B-ODD-04) by nešel ověřit |

Kontrola úplnosti: 26 nálezů, 24 zařazených, 1 odmítnutý, 1 odložený
s důvodem. Každá dávka obsahuje jen nálezy své kategorie, s výjimkou
dvou výslovně zdůvodněných přesunů výše.

### Návrh změny plánu k review

Navrhované změny autoritativního plánu. **Zapsáno 18. 11. 2026 na výslovný
pokyn uživatele** nativním editorem položek plánu (`PlanItems`: journal,
Git CAS, jedna operace = jeden commit) do artefaktu „Roadmapa projektu“
(`75404a16-1e1d-522c-8e90-54a0db1fa604`) projektu
`c898b941-8eb0-4406-8dad-6e2b96c06d59`: 18 commitů `8a71ad0..e67d75b`,
revize grafu `540be809f468d18ff98426722982e41fbdb93a78a7fb7579da918b237f366d62`.
Body 1–4 jsou zapsané do položek; pořadí z bodu 5 vyjadřují stávající
závislosti a tento dokument. Akceptace AUDIT-B1-T5 zůstává lidským review.

1. **AUDIT-B2** (jedna větev, jeden PR) — upřesnit rozsah úkolů:
   B2-T1 = B-LOCK-01, 02, 03, 04 (čtení), 05, 11; B2-T2 = B-LOCK-06, 07,
   08, 10; B2-T3 = B-LOCK-09, bariéra B-LOCK-04 u `rss_monitoring`, crash
   boundaries změněných operací s odkazem na ADR 0003. Akceptace B2-T1
   doplnit o sondu R1: souběžní čtenáři nedostanou `ProjectBusy`, zapisovatel
   je dál vyloučen.
2. **AUDIT-B3** (jedna větev, jeden PR) — B3-T1 = pravidlo kompatibility
   včetně rozhodnutí k B-VER-01 (ADR) a protokolové verze B-VER-04;
   B3-T2 = B-VER-01 (hláška), 02, 03, B-ODD-02; B3-T3 = fixture R3, plán
   v4 (R4), starší rozšíření × nový backend.
3. **AUDIT-B4** — podle svého rozsahu rozdělit na tematicky nezávislé
   dávky (jedna dávka = jeden PR): B4 chyby a hlášky = B4-T1 (B-ODD-01,
   03, 10); samostatná dávka limity a síť = dnešní B4-T2 (B-ODD-05, 06);
   samostatná dávka legacy a duplicity = dnešní B4-T3 (B-ODD-07, 09).
   Uživatel zvolil ID **AUDIT-B5** (úkol B5-T1) a **AUDIT-B6** (B6-T1);
   plánované nezahájené B4-T2 a B4-T3 byly smazány, jejich text převzaly
   B5-T1 a B6-T1 (historie zůstává v Gitu projektu).
4. **Nová dávka pro B-ODD-04** — behaviorální testy kritických toků UI
   místo asercí na zdrojový text; textové kontroly ponechat jen pro
   kontrakty. Předpoklad pro případné pozdější řešení B-ODD-08. Zapsáno
   jako **AUDIT-B7** (úkol B7-T1).
5. **Pořadí:** B2 (obsahuje oba P1) → B3 → dávky z B4 a testovací dávka
   v libovolném pořadí. B2 a B3 jsou nezávislé; souběžně je lze řešit jen
   na samostatných větvích bez stacked PR.

### Ověření T5

- Každý z 26 nálezů je zařazen, nebo výslovně odmítnut či odložen.
- Konzistence s ADR 0003, 0050, 0060, 0062, 0082 a ADR 0020 je výše;
  změna ADR je navržena jen u B-VER-01 a doplnění ADR 0060 u B-VER-04.
- Odkazy dokumentu a `git diff --check` jsou ověřené po poslední úpravě.
