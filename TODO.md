<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-PRESENTER-01: Markdown prezentace jako výstup orchestrace

## Dávka

- **ID:** F-M4-PRESENTER-01
- **Původ:** uživatelský požadavek z 2026-10-14; existující základ z
  `origin/feature/gamepad-demo-presenter` (`55aa483`)
- **Milník:** M4 / prezentační renderer; omezený základ budoucího ER-04
- **Cílová úroveň:** PoC validated
- **Větev:** `feature/f-m4-presenter-01-markdown-decks`
- **Základ a cíl PR:** aktuální `develop` → `develop`

## Výsledek a hranice

Presenter vychází z existujícího editoru, dvou oddělených zobrazení,
ovládání a obnovitelného projektového uložení z demo větve. Prezentace bude
editovatelný projektový Markdown dokument se stabilními layouty; orchestration
chat smí navrhnout nový deck nebo jeho aktualizaci, ale vytvoření či změna
lokálního dokumentu nastane až po explicitním uživatelském náhledu a schválení.

Mimo rozsah jsou plný Disclosure Registry, semafor expozice, trvalá relace
schůzky, obecný rozhodovací strom a export PPTX/PDF. Demo obsah o gamepad patchi
není produktová šablona ani autoritativní projektový obsah.

## Úkoly

- [x] [completed] **F-M4-PRESENTER-01-A — Začlenit a stabilizovat existující
  presenterový základ (PoC validated).** Sloučit historii demo větve se současným
  desktopem bez ztráty novějšího chatu, vyhledávání, importů, publikace a
  bezpečnostních hranic. Zachovat editor, speaker/audience okno, role displejů,
  klávesnici/gamepad, backupy, profil a závěrečný slide. Ověření: cílené
  presenter testy, celá unittest sada, syntaxe vloženého JavaScriptu a diff check.

  Začleněno 2026-10-14 bez převzetí zastaralého TODO a bez obnovení
  odstraněných nativních editorů/importů. Současný sdílený webový UI stack,
  Google Drive/NotebookLM, vyhledávání, chat, workflow, media a CMS zůstaly
  zachovány; presenter doplnil své routy a assety. Ověření: cílený běh
  62 testů pro presenter a desktop prošel (12 přeskočených Qt/hardwarových),
  celá sada `584 tests` prošla (35 přeskočených volitelných fyzických testů),
  vložený JavaScript prošel `node --check` a Python soubory `py_compile`.
  Následná runtime kontrola odhalila a odstranila závislost presenterového editoru
  na již odstraněném `spikes.desktop_editor`; 8 skutečných Qt testů editoru,
  displejů a profilu prošlo se systémovým PySide6.

- [ ] [planned] **F-M4-PRESENTER-01-B — Markdown kontrakt decku a migrace
  v1 (implemented).** Nahradit JSON-only obsah fenced bloku lidsky editovatelným
  Markdown formátem s YAML frontmatterem, stabilními ID slidů, notes, backup vazbami
  a bezpečnou migrací existujícího `fpw-presentation-v1`. Parser musí selhat
  uzavřeně, zachovat Git historii a neinterpretovat vložené HTML.

- [ ] [planned] **F-M4-PRESENTER-01-C — Stabilní layout šablony
  (implemented).** Zavést omezený registr verzovaných layoutů se stabilními zónami,
  minimálně titulní slide, nadpis + text/odrážky, dvousloupec a závěrečný
  kontakt. Speaker preview a audience renderer používají stejný layout kontrakt;
  delší obsah se validuje a nesmí posouvat základní kotvy mezi slidy.

- [ ] [planned] **F-M4-PRESENTER-01-D — Návrh prezentace z orchestračního
  chatu (PoC validated).** Rozšířit typovaný výstup orchestrace o návrh nového
  decku a aktualizace existujícího decku z explicitního Context Manifestu.
  Deterministická vrstva validuje Markdown, layouty, oprávněné zdroje, privacy,
  původní revizi a nový digest; Ollama pouze navrhuje obsah.

- [ ] [planned] **F-M4-PRESENTER-01-E — Povinné schválení vytvoření a
  aktualizace (implemented).** Chat zobrazí náhled/diff a teprve samostatná
  potvrzená akce vytvoří nebo aktualizuje lokální projektový dokument. Bez potvrzení
  nevznikne soubor, artefakt ani Git commit; stale HEAD/digest se odmítne a opakování
  stejného operation ID je idempotentní.

- [ ] [planned] **F-M4-PRESENTER-01-F — Dokumentace a fyzická akceptace
  (PoC validated).** Aktualizovat návod a reuse evidenci a na Linux desktopu ověřit
  editor, uložení/aktualizaci, spuštění, speaker/audience oddělení, stabilní
  layouty a bezpečné chování při odpojení displeje. Gamepad ověřit fyzicky,
  je-li podporované zařízení dostupné; jinak zůstane explicitně neověřený.

## Crash boundaries a recovery

Základní deck i aktualizace použijí existující `Artifacts.save` a jeho
Workspace/Journal/Git/index hranici. Před commitem je autoritou journal; po commitu
lze index obnovit z HEAD. Chatový návrh ani presenterová relace nejsou důkazem
uložení. Pád před explicitním potvrzením nesmí vytvořit dokument; ztracená
odpověď po potvrzeném commitu se obnovuje stejným operation ID bez druhého commitu.

## Akceptace dávky

- Demo základ je začleněn do aktuálního desktopu bez regrese novějších funkcí.
- Deck je lidsky editovatelný Markdown a starý v1 dokument má doloženou migraci.
- Stejný verzovaný layout se použije v editoru, speaker preview i audience okně.
- Orchestration chat umí navrhnout vytvoření i aktualizaci a ukáže přesný náhled.
- Žádný lokální soubor, dokument ani artefakt nevznikne bez explicitního
  potvrzení uživatele.
- Cílené a plné automatické testy projdou; fyzická omezení jsou pojmenována.

## K předání do backlogu

- ER-04 zůstá autoritativním širším požadavkem pro disclosure policy,
  rozhodovací scénář, expozici a trvalou relaci; tato dávka jej neuzavírá.
