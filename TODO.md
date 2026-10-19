<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-FACELIFT-01

Feature dávka **UX-FACELIFT-01 — interaktivní facelift pro první release**
začala 2026-10-17 na větvi `feature/ux-facelift-01` z doručeného `develop`
`8b24452` (konsolidovaný reader a task routing, PR #71). Cíl PR je `develop`;
push, otevření PR ani merge této dávky zatím nejsou schválené. Cílová úroveň:
**designed → implemented → PoC validated**.

Rozsah je záměrně interaktivní: uživatel bude nad skutečnými obrazovkami a
papírovými anotacemi průběžně určovat priority, takže konkrétní vizuální změny
nejsou předem zmrazené. Dávka zůstává jednou ucelenou UI feature: smí měnit
informační hierarchii, rozložení, popisky a ovladatelnost sdíleného web/desktop
frontendu, nikoli přidávat nové backendové schopnosti nebo uvolňovat RBAC,
privacy, potvrzovací a recovery hranice. Každý implementovaný řez se před
zařazením ověří proti uživatelským anotacím a mobilní/klávesnicové paritě.

- [x] [completed] **UX-FACELIFT-01-A — A4 inventura všech formulářů
  (cílová úroveň: implemented).** Vygenerovat z aktuálního UI tiskový balíček
  všech webových formulářů, formulářových panelů, potvrzení a používaných
  nativních Qt dialogů. A4 může používat menší písmo či měřítko, ale popisky,
  pole, volby a hranice jednotlivých obrazovek musí zůstat čitelné a musí být
  ponechaný prostor pro ruční kreslení. Generátor musí selhat, pokud nový
  webový `<form id>` není v inventuře. Generátor nyní pokrývá 31 formulářových
  listů: všech 17 aktuálních HTML formulářů, další formulářové/potvrzovací
  panely a pět používaných nativních dialogů. Lokální výstup má 33 stran A4;
  zdrojový skript ani aplikační JavaScript se do PDF nevykreslují. Vizuálně byly
  zkontrolovány titulní strana, běžný formulář, vícestránkové CMS, editor
  prezentací a nativní dialogy. Reprodukovatelný postup a hranice drží
  `docs/ux-facelift-forms-a4.md`. Cílené tři testy inventury prošly; následná
  celá sada `python3 -m unittest discover -s tests -v` prošla **637 testy**,
  27 volitelných testů bylo přeskočeno. `pdfinfo` potvrdilo 33 stran formátu A4
  a `git diff --check` prošel bez chyb.
- [ ] [in progress] **UX-FACELIFT-01-B — ruční anotace a společná revize
  (cílová úroveň: designed).** Uživatel vytiskne nebo anotuje balíček; společně
  projdeme priority, přesuny, slučování a odstranění tření. Konkrétní scope
  změn vznikne z této revize, nikoli z automaticky domyšleného redesignu.
  První schválený řez revize určuje novou informační architekturu levého
  hlavního panelu:

  - panel vždy zobrazuje ve stejném pořadí záložky **Projekty**, **Chaty**,
    **Úkoly**, **Podklady**, **Nástroje**, **Výstupy** a **Nastavení**;
  - **Projekty** a **Chaty** jsou dostupné i bez zvoleného projektu, zatímco
    ostatní záložky se zpřístupní až po jeho zvolení;
  - **Projekty** obsahují tlačítko pro vytvoření projektu, tlačítko pro import
    projektu s NotebookLM jako jednou z importních možností a samostatně
    scrollovatelný seznam projektů;
  - **Chaty** přebírají současný seznam vláken a před ním zobrazují tlačítko
    **Nové vlákno**;
  - **Úkoly** a **Podklady** přebírají svůj současný obsah a chování;
  - nové **Nástroje** budou katalogem výpočetních a simulačních skriptů
    (například Julia). Nástroj může vzniknout jako výstup chatu, číst podklady
    i vybrané výstupy a vytvářet nové výstupy; tento řez zatím neurčuje nový
    spouštěcí backend ani persistence kontrakt;
  - **Výstupy** nyní obsahují prezentace a počítají s budoucími grafy a
    výstupy výpočtů;
  - **Nastavení** zobrazují samostatně scrollovatelný seznam jednotlivých
    nastavení.

  Pro první implementační řez jsou globální Chaty bez projektu pouze přehledem
  uložených vláken; nové vlákno a jeho otevření vyžadují projekt podle
  stávajícího backendového kontraktu. Nástroje zatím ukazují prázdný katalog a
  Nastavení přebírají existující sekce dostupné dané runtime roli. Další revize
  může obsah těchto seznamů rozšířit, nesmí však potichu přidat novou schopnost
  spouštět výpočty ani změnit projektové, RBAC nebo privacy hranice.
- [ ] [in progress] **UX-FACELIFT-01-C — iterativní implementace schváleného řezu
  (cílová úroveň: implemented).** Promítnout schválené anotace do jediného
  sdíleného frontendu a zachovat mobilní layout, klávesnicovou přístupnost,
  bezpečné textové vykreslení a aplikační autorizační hranice. První řez
  levého panelu je implementovaný ve sdíleném desktop/web shellu: sedm záložek
  je trvale viditelných v určeném pořadí, Projekty a Chaty zůstávají dostupné
  bez projektu a ostatní položky se odemykají až po jeho otevření. Projekty
  mají akce Nový projekt a Importovat projekt s aktuální možností NotebookLM;
  Chaty zachovávají globální přehled vláken, ale vytvoření a otevření vlákna
  bez projektu je bezpečně zablokované podle stávajícího backendového
  kontraktu. Úkoly a Podklady používají původní obsah, Nástroje mají pravdivý
  prázdný katalog bez předstíraného runneru, Výstupy obsahují prezentace a
  Nastavení scrollovatelný seznam dostupných sekcí respektující runtime role.
  Panel je nyní rozdělený do dvou souběžných částí: vlevo je úzký pás sedmi
  ikonových tlačítek a vpravo obsah zvolené záložky. Každá ikona má přístupný
  název a při najetí myší i při klávesnicovém zaměření zobrazí popisek
  příslušné záložky.
  Navazující schválený řez zpřístupňuje Nastavení i bez otevřeného projektu a
  přesouvá formulář Nový projekt z úvodního přehledu na samostatnou stránku se
  zachovaným náhledem a explicitním potvrzením. Ve spodní části levého panelu
  přibyl grafický přehled zdrojů s detailním dialogem: OpenAI používá skutečný
  existující účetní přehled, lokální AI zobrazuje pouze stav konfigurace a
  pravdivě uvádí, že dostupnost nebyla ověřena. CPU, GPU, RAM, VRAM, DISK a NET
  jsou označené placeholdery bez předstírané systémové telemetrie; seznam
  providerů je připravený pro více zdrojů.
  Další schválený řez sjednocuje akční seznamy v levém panelu: kliknutí na
  hlavní plochu položky provede její výchozí akci a menu se třemi tečkami tuto
  akci vždy zopakuje spolu s dalšími skutečně podporovanými operacemi. Vzor je
  použitý pro projekty, chaty, úkoly, podklady, prezentace a nastavení; prázdný
  katalog Nástrojů zatím nemá položky. U úkolu vede výběr i menu poctivě do
  editoru celého hlavního seznamu, protože samostatná per-item editace ani
  mazání nemají backendový kontrakt. Stejně tak se u zdrojů a prezentací
  nezobrazují smyšlené destruktivní akce. Chat bez otevřeného projektu má
  výchozí akci v menu viditelnou, ale nedostupnou podle stávající projektové
  hranice. Globální přehled Chatů bez otevřeného projektu nyní zobrazuje pouze
  nezařazená vlákna; po otevření projektu zobrazuje nezařazená vlákna a vlákna
  přiřazená právě tomuto projektu, nikoli chaty ostatních projektů. Potvrzovací
  a recovery průchody mazání zůstaly beze změny.
  Aktuální schválený řez mění úvod na dlaždicový dashboard: široký viewport má
  čtyři sloupce a osm pozic pro dnešní datum, souhrn nehotových úkolů ze všech
  dostupných projektů, poštu, koš a nejvýše čtyři nedávné projekty. Projektové
  dlaždice už neopakují popis, ID ani samostatný odkaz; celá dlaždice je výchozí
  akcí a pořadí nedávných ID zůstává pouze v paměti aktuální relace a vždy se
  protíná s aktuálním autorizovaným katalogem. Mobilní úvod zobrazuje jen
  dlaždici úkolů. Implementace reuse/adaptuje existující validované
  `/v1/projects/open` a projekci hlavního Markdown checklistu, takže nevzniká
  druhá autorita úkolů ani nový storage formát. Koš má samostatnou stránku,
  dostupnou z panelu Projekty i dashboardu, při zachování původního
  preview/confirm/recovery kontraktu. Tři primární projektové akce jsou v panelu
  v jediné řadě jako ikonová tlačítka; jejich názvy zůstávají v přístupném
  `aria-label` a zobrazují se jako tooltip při najetí i zaměření klávesnicí.
  Diagnostické demo bloky byly z úvodu
  odstraněny; technický smoke harness zůstává skrytý mimo dashboard.
  Kalendář a pošta jsou zatím pravdivé vizuální placeholdery: aplikace nemá
  nakonfigurovaný přenositelný kontrakt pro otevření konkrétního externího
  klienta, takže dlaždice spuštění ani načtená data nepředstírají.
  Aktualizované regresní testy ověřují pořadí, dostupnost, akce a mobilní
  navigaci. Cílená integrační sada prošla 68 testy (6 přeskočeno), JavaScript
  prošel `node --check` a opt-in skutečný Qt WebEngine smoke prošel nad
  projektem s podklady i nad prázdným projektem bez zápisu do jejich Git
  stavů. Další skutečný WebEngine průchod ověřil globálně dostupné Nastavení,
  otevření a zavření dialogu zdrojů i vytvoření projektu ze samostatné stránky.
  Po sjednocení seznamů znovu prošla celá sada **637 testy** (27 přeskočeno),
  `node --check` i `git diff --check`. Skutečný projektový Qt WebEngine test
  prošel dvakrát nad hierarchickými úkoly a podklady, včetně nové výchozí akce
  v menu, a potvrdil nezměněný Git stav projektu. Obecný samostatný layoutový
  smoke zůstává v tomto prostředí občasný na své starší scrollovací časovací
  podmínce; při samostatném běhu prošel, ale dvojité opakování nebylo stabilní.
  Po dashboardovém řezu znovu prošla celá sada **637 testy** (27 přeskočeno),
  `node --check`, `git diff --check` i skutečný Qt WebEngine průchod načtením,
  interakcí a restartem sdíleného desktopového UI.
- [ ] [planned] **UX-FACELIFT-01-D — regresní a fyzická akceptace
  (cílová úroveň: PoC validated).** Ověřit dotčené desktopové i webové průchody,
  úzký viewport, klávesnici, potvrzení a finální fyzický průchod s uživatelem.

Akceptace celé dávky zůstává otevřená do dokončení interaktivní revize a
uživatelem schváleného implementačního řezu. Samotný A4 balíček dokončuje jen
položku A a není souhlasem s konkrétním redesignem.
