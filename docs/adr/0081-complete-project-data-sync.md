<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0081 — Úplnost a sémantická validace projektového přenosu

Datum: 2026-11-07. Stav: implementováno k review, izolovaný PoC;
fyzická Omnia ↔ desktop akceptace tohoto rozšíření není doložená.

Zadání `F-M5-FULL-DATA-SYNC-01`: kanonický projekt
`c898b941-8eb0-4406-8dad-6e2b96c06d59`, exportní revize
`c783f008285f133bcee381d4ecc46fe556d39c4d6b4479c6da1841ccb9210ad1`,
projektový commit `2dbfdf01197563190fdb8f3ba1efd8a411cb023a`.
Samostatná větev `feature/full-data-sync` vznikla z ověřeného develop
`85d264fe75f8a3fc9dd69521ba8839e9a76eac6d`; není stacked na MON-08.
Dokument je rozhodnutí a evidence řezu, nikoli další živý plán.

## Potřeba a reuse

[ADR 0042](0042-bidirectional-native-git-sharing-sync.md) již přenáší celé
povolené větve a historii nativním Git bundle a zachovává divergenci.
Metadata validátor ověřuje typy, ID, vztahy, privacy a neměnné revize.
Chyběla sémantická kontrola reportingových pinů na síťové hranici. Lokálně
dostupný pin navíc nemusí být dosažitelný z přenášených povolených větví.

**Reuse/adapt:** původní policy, `validate_history`, reportingové
`validate_git`, Ed25519/HTTPS, sync journal, Workspace CAS/Index recovery
a explicitní `ConflictResolution`. **Reject:** druhý transport/writer/index,
automatické doplnění skrytých větví, provider fallback a přepsání konfliktu.

## Rozhodnutí

1. Každý dosažitelný commit validovaného přenosu projde také původním
   reportingovým `validate_git`: přesné commit/path/hash piny, projektové
   identity, privacy vztahů, podklady reportu, capture metadata a publikace.
2. Validátor přijímá explicitní přesný `head`; historický commit se posuzuje
   ve svém kontextu. Běžný zápis nadále implicitně používá HEAD. Bare
   validační repo nepotřebuje checkout ani předem existující HEAD.
3. Odesílatel ověří hotový bundle v izolovaném bare repozitáři s výhradně
   skutečně přenášenými refy/objekty. Hidden ref ani unreachable object
   v lokálním Gitu nesmí maskovat chybějící podklad. Neúplný scope se odmítne;
   další větev vyžaduje původní samostatné posouzení policy.
4. Příjemce používá stejnou kontrolu po ověření podepsaného digestu a před
   publikací refů nebo registrací projektu. Podpis nenahrazuje validaci.
5. Přenášejí se původní projektové bajty a historie, nikoli souhrny či jen
   seznam pinů. Zpracování dál ověřuje skutečně dostupné přesné vstupy.
6. Credentials, provozní journaly a lokální aktivace kolektorů nejsou
   projektový bundle. Přenos WatchDefinition není execute grant.

Licence a retence zůstávají původními posouzenými politikami a připnutými
podklady; capture bez doloženého souhlasu ani chybný pin neprojdou. Řez
neinterpretuje právní význam volné prózy ani nevytváří exportní souhlas ze
staženého obsahu. Skutečný export vyžaduje povolený projekt/branch scope
a vypořádané podmínky zdroje. PoC používá syntetické povolené podklady.

## Konflikty a recovery

Divergence zachová oba heady pod incoming refs. Explicitní conflict review
může spojit nezávislé reportingové přírůstky nativním merge se dvěma rodiči.
Textově čistá unie dvou základních zpráv za stejné období neprojde doménovým
validátorem. Takový konflikt zůstává k doménovému rozhodnutí; jedna publikace
se nesmaže automaticky a historie obou větví zůstává zachovaná.

Platí crash hranice ADR 0042; nový persistentní formát ani journal nevzniká:

- Exportní validace je před durable outbound requestem a síťovým přenosem.
  Dočasný bare repo/bundle lze po pádu zahodit; není autoritou.
- Neplatný příjem se odmítá před durable inbound intentem a publikací.
- Po durable přijetí zůstává stejný operation ID a payload, CAS ref,
  checkout/index roll-forward a uložená přesná odpověď. Pád po ref update
  nedovoluje nový přenos s jiným obsahem pod stejným ID.
- Není atomická transakce přes oba uzly. Chatový payload zachovává stejnou
  koordinaci a lokální journal podle ADR 0056.

## Hranice a integrace

Zůstávají limity 500 dosažitelných commitů na head, 64 MiB bundle a původní
limity snapshotů. Úplnost se týká povoleného scope v těchto mezích.
Nepodporované schéma se odmítne; transport nevymýšlí jeho interpretaci.

MON-08 vyvíjí WatchDefinition/SourceFinding samostatně; develop je dosud
nemá. Kompatibilita je testovaná v dočasném složeném checkoutu: monitoring
schéma plus přesný transportní patch. Není to merge, nasazení ani akceptace
MON-08. Po začlenění obou větví se podmíněný test zapojí do běžné sady.

Ověření: [full-data-sync](../full-data-sync.md).
