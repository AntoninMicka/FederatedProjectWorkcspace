<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0090 — Jedna fronta v IDE, projekty IDE a koordinace oken

Datum: 24. 11. 2026. Stav: **implemented**, lokálně ověřeno testy; čeká na
review a živé ověření ve VSCodiu. Rozhodnutí podle přímého zadání uživatele:
fronta v IDE se nemá zasekávat, má být jedním sloučeným seznamem pro všechny
projekty, s možností přepnout konkrétní projekt, a rozšíření má umět vytvořit
projekt v IDE k existujícímu projektu Workspace. Navazuje na ADR 0060, 0062
a 0087. Rozšíření 0.6.0.

## Doložená příčina zasekávání

Výstup **Workspace bridge** z 15.–23. 11. 2026 (VSCodium, tři okna jednoho
profilu) obsahoval přibližně 193 000 opakování
`Panel <id>: ENOENT … SESSION.json`, 13 400 odpovědí `503 resource busy`
a přibližně 260 odmítnutí `Packet superseded`. Analýza kódu 0.5.11:

1. Každé okno má vlastní extension host a vlastní 10s časovač. Všechna okna
   synchronizovala stejné připojení a stejné schránky současně.
2. Jeden běh dělal na projekt `exchange` a dvakrát `queue`; následné obnovení
   panelu opět `panel` a dvakrát `queue`. Při třech oknech a třech projektech
   šlo zhruba o 50 požadavků za 10 s nad stejnými zámky projektu a fronty,
   souběžně s webovým UI.
3. `503 resource busy` (držený `flock`, `ProjectBusy`) se neopakoval a označil
   projekt jako nedostupný; akce fronty se zablokovaly až do dalšího úspěchu.
   Selhání katalogu takto označilo všechny projekty.
4. Ruční **Obnovit** během běžící synchronizace okamžitě skončilo bez účinku.
5. Lokální mapování bez prvního exportu (osiřelá session) se hlásilo při
   každém obnovení panelu.

## Rozhodnutí

### Jeden synchronizující lídr na profil

Soubor `sync-lease.json` v privátním `bridge-private` určuje jediné okno, které
na pozadí dotazuje Workspace. Lease má platnost 30 s a obnovuje se každým
tickem. Převzít jej lze po expiraci, po zániku procesu držitele nebo jde-li
o předchozí aktivaci téhož procesu (každé okno má vlastní extension host).
Ostatní okna nevolají Workspace na pozadí. Po každém běhu lídr zveřejní
`sync-state.json` s novou generací a textem stavového řádku; ostatní okna
pak panel obnoví z lokálních souborů. Ruční synchronizace funguje v každém
okně. Vypnutý Auto Sync vypíná i lídra.

Lease je pouze koordinace. Neautorizuje ani neřadí projektová data, zprávy,
receipts ani review. Souběžný běh dvou oken (současné převzetí, chyba čtení
lease) je stejně bezpečný jako dosavadní stav, kdy synchronizovala všechna
okna: zprávy se přehrávají podle UUID a soubory se publikují atomicky.

### Méně požadavků a zaneprázdnění bez blokace

- Panel po synchronizaci znovu neexportuje frontu, kterou běh právě exportoval.
  Obnovení na pozadí a při změně viditelnosti použije čtení panelu mladší
  než 20 s; ruční akce a příkazy čtou vždy znovu.
- Již publikovaná generace balíčku se všemi ověřenými podklady nepotřebuje
  druhý kontrolní dotaz `queue`; kontrola před publikací nové generace zůstává.
  Nezměněný `AGENT.md` se nepřepisuje.
- Bez balíčku (`has_queue: false`) se `queue.json` nastaví na `null` bez
  dalšího dotazu.
- `503 resource busy` se opakuje (250, 500, 1000 ms) jen u čtecích akcí
  (`status`, `extension-update`, `owner-queue`, `panel`, `queue`,
  `queue-document`, `document`) nebo když server uvede `outcome: not-started`.
  Zápis s neznámým výsledkem se automaticky neopakuje.
- Zaneprázdnění se zobrazuje odděleně (`STATUS.json` s `busy: true`, panel
  „Zaneprázdněné · poslední známý stav“). Poslední známý stav se nevydává
  za aktuální a akce vyžadující aktuální stav zůstávají blokované. Lídr po
  zaneprázdnění prodlužuje interval exponenciálně do 60 s; úspěch jej vrací.
- Ruční synchronizace během běžícího běhu se k němu připojí.
- Mapování bez lokálního exportu se v okně ohlásí jednou.
- `atomic()` odstraní vlastní dočasný soubor, pokud zápis nebo přejmenování
  selže.

### Sloučená fronta

Nová čtecí akce IDE spojení `owner-queue` (`{connection_id, action}`) vrací
`revision`, `order` (`[project_id, task_id]`) a `sessions` z owner fronty
podle ADR 0087. Rozsah tvoří pouze projekty navázané (`bound`) na toto
připojení, ve kterých má účet editora nebo je administrátor. Nenavázané
projekty se do IDE nepropagují. Akce čte jen owner soubor pod sdíleným
zámkem a databázi bridge. Nečte projekty, nemění Git, index, journal ani
soubory fronty a nevytváří owner soubor. Admission ji řadí do `ide_status`.

Rozšíření ukládá pořadí do `owner-queue.json`. Pořadí pouze uspořádá řádky.
Stav, oprávněnost a všechny akce řádku (▶, ✓, předání agentovi) pocházejí
z připnutého balíčku jeho projektu. Sloučený seznam tak není druhým plánem
ani druhou frontou. Reference bez položky v balíčku zůstává viditelná
jako read-only. Položka balíčku mimo společné pořadí se zobrazí na konci
s označením. Pořadí starší než 60 s nese čas načtení. Změnu pořadí dál
provádí Workspace (ADR 0087); IDE ji nenabízí.

Pohled **Fronta úkolů** ukazuje projekt tohoto okna jako první uzel a pod
ním uzel **Všechny úkoly ve frontě**. Bez vybraného projektu je sloučený
seznam přímo kořenem. Projekt okna se určí explicitní volbou (**Workspace:
Přepnout projekt**, `workspaceState`), jinak podle otevřené složky nebo
`.code-workspace`. Volba **Všechny projekty** vypne zaměření. Ostatní pohledy
se zaměří na stejný projekt. Přepnutí nabídne otevření projektu v tomto
nebo novém okně, nikdy je neprovede samo.

Kompatibilita: protokol K7 zůstává 1. Jde o novou čtecí akci, nikoli o nové
pole zprávy. Starší backend odmítne akci jako `Unsupported connection action`.
Rozšíření pak deset minut akci nevolá a zobrazí viditelný degradovaný stav
„pořadí po projektech“. Zvýšení protokolu by naopak starší backendy
odmítlo celé.

### Projekt v IDE k existujícímu projektu Workspace

Příkaz **Workspace: Vytvořit projekt v IDE k projektu Workspace** vybere
oprávněný projekt a jeden způsob: klonovat Git repozitář do nové složky,
použít existující složku nebo `.code-workspace`, či vytvořit nový prázdný
repozitář. Klon i inicializace běží bez interaktivního dotazu na přihlášení
(`GIT_TERMINAL_PROMPT=0`, SSH `BatchMode`) s limitem 10 minut. Cílová složka
nesmí existovat. Přiřazení pak používá stávající potvrzení a lifecycle
`map` → `bind` → uložení mapování. Nakonec se nabídne otevření.

Crash boundaries: selhaný `git clone` po sobě cílovou složku odstraní.
Po úspěšném klonu, ale před `map`, zůstane obyčejný lokální repozitář.
Opakování použije volbu „existující složka“. Mezi `map` a `bind` zůstává
dosavadní obnova mapování (ADR 0060). Po selhání `git init` zůstane prázdná
složka a chyba se ohlásí. Žádná z těchto hranic nemění projektový Git,
index ani journal Workspace.

## Omezení

- Nesynchronizují se lease a pořadí mezi profily ani mezi stroji. Každý profil
  má vlastního lídra.
- PID kontrola předpokládá jeden lokální stroj; Remote SSH/WSL zůstávají
  nepodporované (ADR 0060).
- Ověření je automatizované (jednotkové a integrační testy). Živé ověření
  běžného VSCodium profilu s více okny a lidská akceptace chybějí.
