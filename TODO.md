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

- [x] [completed] **F-M4-PRESENTER-01-A1 — Konfigurovatelné lokální mapování
  gamepadu (implemented).** Doplnit do soukromého kokpitu výběr browserového
  zařízení, mapování a obrácení čtyř os, potvrzovací tlačítko, prahy a živý
  náhled. Použití pro relaci nesmí zapisovat; node-local SQLite konfigurace
  vznikne až po explicitním tlačítku **Uložit na tomto uzlu**. Ověřit validaci,
  restart, pád uprostřed transakce, symlink, JS gesta, API a celý test suite.

  Dokončeno 2026-10-15. Výchozí načtení i **Použít nyní** jsou bez zápisu;
  explicitní uložení používá jednu synchronní SQLite transakci mimo projektový
  Git. Cílené testy ověřily validaci, restart, oba crash scénáře, symlink, API
  a přemapovaná JS gesta. Celá sada `590 tests` prošla (27 přeskočených
  volitelných/fyzických testů), vložený JavaScript prošel `node --check` a
  offscreen Qt WebEngine smoke načetl UI i autentizované API. Fyzický gamepad
  nebyl v tomto běhu dostupný a zůstává k ruční akceptaci v úkolu F.

- [x] [completed] **F-M4-PRESENTER-01-A2 — Integrovaný editor prezentací
  (implemented).** Nahradit uživatelský tok přes samostatný Qt dialog jedinou
  záložkou **Prezentace** ve společném projektovém workspace. Sjednotit navigaci,
  formuláře, responzivní rozložení, náhled a stavové hlášky; zachovat hlavní
  linii, backup vazby, soukromé poznámky, tapetu, explicitní uložení, retry
  stejné operace a spuštění pouze přesně uložené revize. Formát v1 a layouty
  se v tomto kroku nemění; ty zůstávají v B a C.

  Dokončeno 2026-10-15. Horní desktopové tlačítko, panel promítání i projektová
  záložka vedou do jediného editoru ve workspace; samostatný Qt dialog již není
  v uživatelském toku. Editor obnovuje seznam podkladů po uložení, chrání
  rozepsaný či neověřeně uložený koncept a presenter přijme jen existující deck
  z přesného aktuálního HEAD. Cílených 20 editor/presenter/API testů prošlo,
  celá sada `592 tests` prošla (27 přeskočených volitelných/fyzických testů),
  vložený JavaScript prošel `node --check` a offscreen Qt WebEngine smoke načetl
  společné UI i autentizované API. Ruční vizuální a vstupní akceptace editoru
  zůstává součástí F-M4-PRESENTER-01-F.

- [x] [completed] **F-M4-PRESENTER-01-A3 — Seznam hotových prezentací v
  bočním panelu (implemented).** Doplnit do levého projektového panelu vlastní
  záložku se seznamem uložených prezentací. Každá platná položka nabízí přímé
  otevření v integrovaném editoru a spuštění přesně uložené revize. Pouhé
  otevření seznamu nevytváří soubor, artefakt ani commit.

  Dokončeno 2026-10-15. Záložka **Prezentace** je vedle Úkolů, Podkladů a Chatů;
  zobrazuje název a ID uloženého decku a akce **Upravit** a **Spustit**.
  Neplatný uložený dokument zůstane viditelný a označený, ale jeho akce jsou
  vypnuté. Webová varianta záložku zatím skrývá stejně jako lokální presenter.
  Cílených 27 presenter/editor/UI testů prošlo, stejně jako syntaxe vloženého
  JavaScriptu; celá sada `592 tests` prošla (27 přeskočených volitelných či
  fyzických testů). Ruční vizuální akceptace zůstává součástí úkolu F.

- [ ] [planned] **F-M4-PRESENTER-01-B — Markdown kontrakt decku a migrace
  v1 (implemented).** Nahradit JSON-only obsah fenced bloku lidsky editovatelným
  Markdown formátem s YAML frontmatterem, stabilními ID slidů, notes, backup vazbami
  a bezpečnou migrací existujícího `fpw-presentation-v1`. Parser musí selhat
  uzavřeně, zachovat Git historii a neinterpretovat vložené HTML.

- [x] [completed] **F-M4-PRESENTER-01-C — Stabilní layout šablony
  (implemented).** Zavést omezený registr verzovaných layoutů se stabilními zónami,
  minimálně titulní slide, nadpis + text/odrážky, dvousloupec a závěrečný
  kontakt. Speaker preview a audience renderer používají stejný layout kontrakt;
  delší obsah se validuje a nesmí posouvat základní kotvy mezi slidy.

  Dokončeno 2026-10-15 před B na přímý požadavek uživatele. Deck nese 1–20
  verzovaných pojmenovaných šablon; výchozí registr nabízí titulní, obsahový,
  dvousloupcový a závěrečný layout. Editor umožňuje předlohy přizpůsobit,
  kopírovat, obnovit a odstranit, ale nepřijímá CSS/HTML ani libovolné pozice.
  Renderer používá pevné zóny a tentýž resolved layout pro editor, speaker i
  audience projekci. Staré v1 decky se při čtení bezzápisově doplní výchozími
  šablonami; úkol B musí tato pole zachovat při migraci do Markdownu. Cílené
  testy dokumentového kontraktu, rendereru a UI prošly (33 testů, 1 přeskočený
  volitelný QR dekodér); po poslední změně prošla i celá sada 594 testů
  (27 přeskočeno), Python syntax check, JavaScript syntax check a diff check.

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
