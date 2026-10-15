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
schůzky, obecný rozhodovací strom a export PPTX. Implementace PDF exportu je
samostatná navazující feature `F-M4-PRESENTER-PDF-01` zachycená níže k předání
do backlogu. Demo obsah o gamepad patchi není produktová šablona ani
autoritativní projektový obsah.

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

- [x] [completed] **F-M4-PRESENTER-01-B — Markdown kontrakt decku a migrace
  v1 (implemented).** Nahradit JSON-only obsah fenced bloku lidsky editovatelným
  Markdown formátem s YAML frontmatterem, stabilními ID slidů, notes, backup vazbami
  a bezpečnou migrací existujícího `fpw-presentation-v1`. Parser musí selhat
  uzavřeně, zachovat Git historii a neinterpretovat vložené HTML.

  Dokončeno 2026-10-15. Formát `fpw-presentation` v2 má omezený YAML
  frontmatter pro deck a layouty, allowlisted YAML blok každého slidu a čitelný
  Markdown nadpis s odrážkami. Sdílený strict loader odmítá duplicity, aliasy,
  kotvy, explicitní tagy, nadměrné zanoření a neznámá pole; samostatné HTML
  konstrukce parser odmítne a HTML uvnitř nadpisu či odrážky zůstává textem.
  Legacy v1 JSON se otevírá bez zápisu a migruje se až explicitním uložením
  stejného artefaktu do nové Git revize, zatímco původní bajty zůstávají v
  historii. Cílených 15 presenterových testů prošlo (1 přeskočený fyzický
  WebEngine test), stejně jako cílené lokální API testy, Python syntax check a
  diff check. Celá sada `596 tests` prošla (27 přeskočeno).

- [x] [completed] **F-M4-PRESENTER-01-C — Stabilní layout šablony
  (implemented).** Zavést omezený registr verzovaných layoutů se stabilními zónami,
  minimálně titulní slide, nadpis + text/odrážky, dvousloupec a závěrečný
  kontakt. Speaker preview a audience renderer používají stejný layout kontrakt;
  delší obsah se validuje a nesmí posouvat základní kotvy mezi slidy.

  Dokončeno 2026-10-15 před B na přímý požadavek uživatele. Deck nese 1–20
  verzovaných pojmenovaných šablon; výchozí registr nabízí titulní, obsahový,
  dvousloupcový, obrázkový/grafový a závěrečný layout. Obrázkový layout používá
  existující bezpečně vložené PNG v pevné středové zóně. Editor umožňuje
  předlohy přizpůsobit, kopírovat, obnovit a odstranit, ale nepřijímá CSS/HTML
  ani libovolné pozice.
  Renderer používá pevné zóny a tentýž resolved layout pro editor, speaker i
  audience projekci. Staré v1 decky se při čtení bezzápisově doplní výchozími
  šablonami; úkol B musí tato pole zachovat při migraci do Markdownu. Cílené
  testy dokumentového kontraktu, rendereru a UI prošly (33 testů, 1 přeskočený
  volitelný QR dekodér); po poslední změně prošla i celá sada 594 testů
  (27 přeskočeno), Python syntax check, JavaScript syntax check a diff check.

- [x] [completed] **F-M4-PRESENTER-01-D — Návrh prezentace z orchestračního
  chatu (PoC validated).** Rozšířit typovaný výstup orchestrace o návrh nového
  decku a aktualizace existujícího decku z explicitního Context Manifestu.
  Deterministická vrstva validuje Markdown, layouty, oprávněné zdroje, privacy,
  původní revizi a nový digest; Ollama pouze navrhuje obsah.

  Dokončeno 2026-10-15. Ollama vrací uzavřený `presentation-proposal` pouze s
  obsahem a odkazy na explicitně vybrané zdroje; deterministická vrstva z něj
  sestaví nový deck se stabilními ID nebo bezpečně upraví pouze existující
  hlavní slidy vybrané prezentace. Výsledek znovu projde validací decku a
  kanonického Markdownu, váže privacy a původní Git revizi z Context Manifestu
  a nese SHA-256 nového Markdownu. Chat ukáže název, slidy, layouty, revizi a
  digest, ale nabízí jen **Zahodit**; nevzniká projektový dokument ani commit.
  Strukturální přidávání či mazání slidů při aktualizaci zůstává záměrně mimo
  tento PoC. Testy doložily vytvoření i aktualizaci, restart projekce, privacy,
  oprávněné zdroje, neznámý layout, změnu HEAD během běhu a absenci zápisu do
  projektu. Cílená sada prošla (107 testů, 3 přeskočené); celá sada prošla
  (600 testů, 27 přeskočených volitelných/fyzických testů).

- [x] [completed] **F-M4-PRESENTER-01-D1 — Zpřesnit kontrakt návrhu po fyzickém
  neúspěchu Ollamy (implemented).** Reálný běh s dokumentem „Architektura EZS —
  Track-to-Track Fúze“ vrátil správný druh návrhu, ale vynechal povinný layout,
  přesunul poznámku mimo slide a přimíchal nesouvisející téma. Router nyní
  explicitně opakuje všech pět polí každého slidu, povolené layouty nového decku,
  výchozí rozsah 6–12 slidů, jazyk zadání a vazbu pouze na vybrané zdroje.
  Deterministická vrstva vadný návrh nadále neopravuje ani neukládá a UI jej
  odliší od ostatních neplatných výsledků; nový běh zůstává výslovnou akcí.
  Pět cílených router/presenter/UI testů prošlo a celá sada prošla v prostředí
  s povolenými loopback sockety (`601 tests`, 27 přeskočených volitelných či
  fyzických testů).

- [x] [completed] **F-M4-PRESENTER-01-D2 — Textová projekce PDF pro LLM kontext
  (implemented).** Dva opakované fyzické pokusy s Google Drive PDF skončily před
  dispatchí, protože obecný router vyžadoval UTF-8 bajty a binární PDF nemohlo
  založit Ollama run. Adapter nyní pro bounded PDF vytvoří přes Poppler inertní
  UTF-8 textovou projekci označenou v promptu; Context Manifest a autorizace dál
  vážou původní commit, artifact ID, privacy, velikost a SHA-256 původních bajtů.
  Projekce nic nezapisuje, má limit 4 MiB, 2000 řádků a 15 sekund a při chybě
  selže před dispatchí bez fallbacku na jiný zdroj nebo backend. Skutečný
  104 733bajtový vybraný PDF artefakt prošel na 5 827 bajtů promptu se správným
  českým nadpisem a bez PDF binárních dat; čtyři cílené testy a celá sada
  `603 tests` prošly (27 volitelných či fyzických testů přeskočeno).

- [x] [completed] **F-M4-PRESENTER-01-D3 — Strojově vynucený kontrakt
  návrhu prezentace (implemented).** Fyzický běh s `qwen3-coder:latest`
  správně použil vybrané PDF a vytvořil šest obsahově relevantních českých
  slidů, ale navzdory explicitní instrukci u všech vynechal povinný `layout`.
  Router proto pro Ollama structured output nově posílá uzavřené JSON Schema
  všech povolených výsledků; větev prezentace vyžaduje přesně pět polí každého
  slidu včetně `layout` a odmítá další pole. Aplikační validace zdrojových ID,
  layoutů, HEAD, Markdownu a digestu zůstává druhou autoritativní vrstvou;
  návrh se nadále neopravuje ani neukládá bez platného výsledku. Dva nové
  kontraktové testy a související router test prošly; celá sada prošla
  (`605 tests`, 27 přeskočených volitelných či fyzických testů), stejně jako
  Python syntax check a diff check. Skutečný nový modelový běh se nespouštěl
  automaticky a zůstává vědomou fyzickou akceptací uživatele.

- [x] [completed] **F-M4-PRESENTER-01-D4 — Závazné směrování explicitního
  požadavku na prezentaci (PoC validated).** Opakovaná fyzická zkouška ukázala,
  že společné schema sice vynutilo platný tvar, ale dovolilo Ollamě zvolit
  platnou větev dokumentu. Pro explicitní požadavek na vytvoření či aktualizaci
  prezentace proto aplikace vybírá samostatně verzovanou roli a JSON Schema,
  jehož jediným povoleným výsledkem je `presentation-proposal`; odlišné zaměření
  nadále používá obecný router. Existující registr rolí a presenter schema byly
  adaptovány, nové paralelní ukládání ani provider nebyly zavedeny.
  Dokončeno 2026-10-15. Regresní test používá přesný český prompt
  `vytvoř z daného dokumentu prezentaci`, ověřuje presentation-only schema,
  zaznamenanou revizi role a odmítnutí dokumentového výsledku aplikační vrstvou.
  Cílená sada `101 tests` a celá sada `610 tests` prošly (27 přeskočených
  volitelných či fyzických testů).

- [x] [completed] **F-M4-PRESENTER-01-E — Povinné schválení vytvoření a
  aktualizace (PoC validated).** Chat zobrazí náhled/diff a teprve samostatná
  potvrzená akce vytvoří nebo aktualizuje lokální projektový dokument. Bez potvrzení
  nevznikne soubor, artefakt ani Git commit; stale HEAD/digest se odmítne a opakování
  stejného operation ID je idempotentní.
  Dokončeno 2026-10-15. Připravený návrh nyní nese deterministický schvalovací
  náhled s přesným before/after diffem odvozeným z historické base revision a je
  svázaný s base revision, kanonickým deck digestem i approval digestem. Samostatné
  potvrzení podporuje create i update, zachovává privacy a provenance a používá
  stabilní artifact/operation ID také při opakování po restartu. Stale projekt,
  pozměněný digest či změněné potvrzení se odmítají před zápisem; pád po projektovém
  commitu a před uzavřením výsledku se obnoví bez druhého commitu. Autentizovaný
  desktop endpoint a UI vyžadují výslovné tlačítko a zobrazují inertní diff jako
  text. Cílených `110 tests` prošlo (3 přeskočené), Python syntax check a vložený
  JavaScript prošly a celá sada `608 tests` prošla (27 přeskočených volitelných či
  fyzických testů). Fyzická desktopová akceptace zůstává v F-M4-PRESENTER-01-F.

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

- [ ] [planned] **F-M4-PRESENTER-PDF-01 — PDF export nativního decku a
  odprezentované relace (cílová úroveň: PoC validated).** Uživatelský požadavek
  z 2026-10-15; samostatná navazující feature po `F-M4-PRESENTER-01`, protože
  export je nezávisle dodávatelný výstup s vlastní recovery a souborovou
  hranicí. Navržená větev `feature/f-m4-presenter-pdf-01`, základ/cíl PR
  aktuální `develop` → `develop`.

  Nabídnout dva explicitně odlišené režimy. **Nativní (kanonická) verze**
  vyrenderuje pouze hlavní slidy přes jejich uloženou `next` linii v
  předdefinovaném pořadí; nezahrne backupy, soukromé notes ani automaticky
  generovaný závěrečný slide.
  **Odprezentovaná verze** vyrenderuje přesné audience snapshoty ve skutečném
  pořadí relace, včetně skutečně zobrazených backupů, opakování, závěrečného
  slidu a konkrétního stavu postupně odhalených odrážek. Nezobrazený obsah,
  soukromý preview, notes ani pouhý výběr do exportu nepatří. Export relace je
  dostupný jen dokud existuje její přesná historie; nesmí rekonstruovat údajný
  průběh z aktuálního decku.

  Před vytvořením každého PDF zobrazit režim, zdrojový deck a commit/revizi,
  počet a pořadí stránek, cílovou cestu a skutečnost, zda soubor bude přepsán.
  PDF ani pomocný obsahový soubor nesmí vzniknout před explicitním potvrzením
  uživatele. Po potvrzení použít atomickou publikaci nebo ponechat jednoznačně
  identifikovatelný obnovitelný stav; zrušení či známé selhání nesmí vydávat
  částečný soubor za hotový export. Oba režimy musí použít stejný bezpečný
  renderer a 16:9 layout jako audience, fungovat offline a nevložit vzdálené
  zdroje, HTML, skripty ani soukromá pole. Export sám není důkazem doručení ani
  DisclosureEvent. Akceptace zahrne stabilní pořadí, backup/opakování/reveal,
  prázdnou historii relace, změněnou revizi, zrušení výběru cíle, existující
  cílový soubor, pád během zápisu, restart a vizuální porovnání výsledného PDF.

- ER-04 zůstá autoritativním širším požadavkem pro disclosure policy,
  rozhodovací scénář, expozici a trvalou relaci; tato dávka jej neuzavírá.
