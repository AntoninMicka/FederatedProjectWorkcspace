<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-SEARCH-03 — Volitelný automatický dispatch hledání

Původ: roadmapa a [BACKLOG](BACKLOG.md), aktivováno po doručení závislosti
`F-M4-AUTONOMY-01` dne 23. 10. 2026. Milník M3, cílová úroveň
**designed → implemented → PoC validated**. Větev
`feature/f-m3-search-03-auto-dispatch` vznikla z `develop` `7dce1c4`; cílem je
jediný PR do `develop`.

Předchozí dávka byla doručena PR #85 jako merge commit `7dce1c4`; její
dokončená evidence zůstává ve
[WORK_LOG](WORK_LOG.md#f-m4-autonomy-01--obecná-řízená-autonomie-orchestrace--2026-10-23).

## Rozsah a hranice

Nad existujícím iterativním hledáním `F-M3-SEARCH-02` a společnou řízenou
frontou `F-M4-AUTONOMY-01` přidat pro jedno konkrétní hledání explicitní volbu
ručního potvrzování nebo bounded automatického odesílání navržených dotazů.
Každý automatický dotaz musí před sítí ukázat účel, přesný cíl, privacy, číslo
kola, zbývající budget a uživatelem zvolený countdown 3–5 sekund.

Během countdownu musí jít frontu pozastavit, dotaz zkontrolovat či upravit,
ihned odeslat nebo zrušit. Ztráta viditelnosti UI, lease, změna oprávnění,
privacy, bindingu či Git HEAD a restart další dispatch fail-closed pozastaví.
Po skutečném odeslání nelze síťový účinek odvolat a `unknown` se automaticky
neopakuje. Dávka nezavádí nový provider, obecný background worker ani
automatickou publikaci lokálního artefaktu.

## Úkoly

- [x] [completed] **F-M3-SEARCH-03-A — integrační kontrakt a reuse
  (cílová úroveň: designed).** Prověřit současné `ChatService`, `SearchRuns`,
  search approval/recovery a action registry; navrhnout jediný přesný
  registrovaný search dispatch bez druhého journalu či paralelního síťového
  writeru. Popsat crash boundaries a způsob vazby user-selected countdownu na
  aktivovaný plán. [ADR 0045](docs/adr/0045-governed-automatic-search-dispatch.md)
  ponechává `SearchRuns` jedinou autoritou síťového účinku a obecnou frontu
  autoritou orchestrace. Zavádí jednu přesnou reviewovanou search akci,
  activation digest s per-workflow countdownem, bounded dynamické kroky,
  editaci před vznikem search runu a explicitní fail-closed reconciliation.
  Reuse/odmítnuté varianty jsou zaznamenané v `REUSE_CATALOG.md`; runtime se
  v tomto kroku neměnil.
- [x] [completed] **F-M3-SEARCH-03-B — automatický search adapter
  (cílová úroveň: implemented).** Připojit navržený dotaz iterativního hledání
  k obecné frontě, zachovat stávající autorizaci, privacy, binding, round/time
  budget a audit přesných odeslaných bajtů a zajistit `unknown` bez auto-retry.
  Registry nyní obsahuje přesnou akci `search.iterative-query`; autonomy plán
  v2 váže search task, policy `first-proposed-v1` a per-workflow countdown.
  Fronta materializuje nejvýše jeden navazující krok s deterministickými ID a
  neměnným activation digestem, zatímco skutečný dispatch i audit zůstávají v
  `SearchRuns`/`OllamaRuns`. Čistý kandidát před countdownem nevytváří search
  journal; změna preview, HEAD, bindingu, privacy nebo budgetu selže před sítí
  a `unknown` je terminální bez retry. Cílených 83 testů prošlo; úplná sada
  23. 10. 2026 skončila 775 testy OK, 28 podmíněně přeskočeno. UI příprava,
  editace a `send-now` zůstávají v úkolu C.
- [x] [completed] **F-M3-SEARCH-03-C — ovládání ruční/automatické fronty
  (cílová úroveň: implemented).** V existujícím search UI zpřístupnit volbu
  režimu a countdownu 3–5 sekund, viditelný dotaz/účel/cíl/privacy/kolo/budget
  a akce pause, review/edit, send-now a cancel bez oslabení obecného UI lease.
  Search karta nyní ponechává dosavadní ruční preview/confirm tok a nabízí
  explicitně aktivovaný automatický režim s odpočtem 3–5 sekund. Zobrazuje
  přesný dotaz, účel, endpoint a target ID, privacy, kolo, budget i živý
  odpočet; podporuje pause/resume, editaci navazujícího dotazu, potvrzené
  send-now a zrušení samotné fronty. Skrytí karty nebo ztráta UI lease frontu
  fail-closed pozastaví. Editace před dispatchí nevytváří `SearchRuns`: původní
  přesný krok ukládá journal schématu 4 jako zrušenou revizi a nový krok znovu
  validuje přes čistý search candidate. Send-now přijme pouze digest právě
  zobrazeného countdown kroku a potom používá stejný `advance` a doménový
  journal jako běžné vypršení odpočtu. Cílených 25 testů prošlo; úplná sada
  23. 10. 2026 skončila 776 testy OK, 28 podmíněně přeskočeno. Reálný
  vícekolový průchod, restartové stavy a fyzická UI akceptace zůstávají v D.
- [x] [completed] **F-M3-SEARCH-03-C1 — jednotná časová osa chatu a úloh
  (ad-hoc, cílová úroveň: implemented).** Hlášení uživatele odhalilo, že UI
  nejprve vykreslovalo všechny uložené zprávy a teprve pod nimi samostatný blok
  task projekcí včetně opakovaných vstupů. Renderer nyní skládá jedinou stabilní
  časovou osu podle `created_at`; task svázaný přes `prompt.message_id` vloží
  výstup bezprostředně za existující vstup a prompt podruhé nevykreslí. Task bez
  uložené chatové zprávy vloží jako sousední dvojici vstup–výstup na jeho
  časovou pozici. Změna je pouze projekční, nemění persistentní data ani jejich
  recovery. Desktopových 46 testů prošlo, 3 podmíněně přeskočeny; úplná sada
  23. 10. 2026 skončila 776 testy OK, 28 podmíněně přeskočeno.
- [ ] [planned] **F-M3-SEARCH-03-D — regrese a fyzická akceptace
  (cílová úroveň: PoC validated).** Ověřit ruční i automatický vícekolový tok,
  editaci během countdownu, pause celé fronty, vyčerpaný budget, změny policy,
  skrytí/odpojení UI, restart ve všech stavech a `unknown` bez opakování;
  dokončit úplnou sadu, statické kontroly, dokumentaci a reálný desktopový
  průchod nad dostupným search backendem.

## Akceptace

- Uživatel může pro konkrétní iterativní hledání vědomě zvolit ruční nebo
  bounded automatický režim a později automatiku pozastavit či zrušit.
- Žádný dotaz neopustí uzel bez viditelného 3–5sekundového countdownu nebo
  explicitní akce send-now; skryté/odpojené UI a restart další dispatch
  pozastaví.
- Existující search journal zůstane autoritou síťového účinku, obecná fronta
  autoritou orchestrace a projektový Git pouze potvrzených projektových zápisů.
- Cílené testy, úplná sada `python3 -m unittest discover -s tests -v`, statické
  kontroly a fyzická desktopová akceptace projdou; omezení budou zdokumentována.
