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
    **Úkoly**, **Podklady**, **Nástroje**, **Výstupy** a **Nastavení**; desktop
    za ně přidává osmou capability záložku **Federace**;
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

  Nově schválený cílový směr společného pracovního prostoru nahrazuje omezení
  globálních Chatů: bez otevřeného projektu má jít zobrazit nezařazené vlákno a
  založit nové nezařazené vlákno. Otevřený projekt dostane vlastní úvodní
  stránku s názvem, stručným popisem a úkoly. Stejná hlavní stránka bude pro
  projekt i nezařazený chat rozdělená na horní kontextovou část (úvod projektu,
  editor nebo aktivní konverzace) a spodní jednotný widget pro zadání dotazu či
  úkolu. Detailní návrh prompt widgetu je vědomě odložený; před ním uživatel
  projde existující editory a určí jejich cílové uspořádání. Datová vrstva již
  podporuje vlákna s `project_id = null`, ale dnešní chat dispatch vyžaduje
  projektový workspace, jeho HEAD a projektový Context Manifest. Implementace
  proto musí před zpřístupněním nezařazeného odesílání explicitně navrhnout
  bezpečný projektově nezařazený dispatch kontrakt; nesmí pouze odstranit
  blokaci v UI ani předstírat projektový kontext. Projektová úvodní stránka a
  sdílený layout promptu jsou už implementované v položce C; nezařazené
  otevření, založení a dispatch zatím implementované nejsou.
- [ ] [in progress] **UX-FACELIFT-01-C — iterativní implementace schváleného řezu
  (cílová úroveň: implemented).** Promítnout schválené anotace do jediného
  sdíleného frontendu a zachovat mobilní layout, klávesnicovou přístupnost,
  bezpečné textové vykreslení a aplikační autorizační hranice. První řez
  levého panelu je implementovaný ve sdíleném desktop/web shellu: sedm základních
  záložek je viditelných v určeném pořadí, Projekty a Chaty zůstávají dostupné
  bez projektu a ostatní položky se odemykají až po jeho otevření. Projekty
  mají akce Nový projekt a Importovat projekt s aktuální možností NotebookLM;
  Chaty zachovávají globální přehled vláken, ale vytvoření a otevření vlákna
  bez projektu je bezpečně zablokované podle stávajícího backendového
  kontraktu. Úkoly a Podklady používají původní obsah, Nástroje mají pravdivý
  prázdný katalog bez předstíraného runneru, Výstupy obsahují prezentace a
  Nastavení scrollovatelný seznam dostupných sekcí respektující runtime role.
  Panel je nyní rozdělený do dvou souběžných částí: vlevo je úzký pás základních
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
  Otevřený projekt má nyní výchozí centrální stránku **Projekt** s názvem,
  commitnutým stručným popisem a přehledem nehotových položek hlavního TODO.
  Pod názvem používá široká obrazovka čtyřsloupcový poměr `1–2–1`: prázdnou
  připravenou dlaždici, neorámovaný popis přes dva sloupce a úkolovou dlaždici.
  Střední šířka skládá popis přes dva sloupce nad dvě samostatné dlaždice;
  mobil řadí popis, prázdnou dlaždici a úkoly po jednom pod sebe.
  Přehled reuse/adaptuje vzhled globální dlaždice úkolů a stejnou validovanou
  `main_todo` projekci jako levý panel; nevznikla druhá autorita ani nový zápis.
  Stávající chat composer je vložený jako jednotný spodní prompt widget, který
  lze ručně skrýt a zobrazit. Každá centrální záložka deklaruje svůj výchozí
  stav promptu atributem `data-prompt-default`: Projekt, Náhled a Chat jej
  otevírají, specializované workflow a editory jej standardně skládají.
  Přepnutí Náhledu nebo Chatu už nezávisí na pozičním indexu záložky.
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
  Po projektové úvodní stránce prošla celá sada **638 testy** (27 přeskočeno),
  cílené desktopové a inventurní testy, JavaScript parser, Python kompilace a
  `git diff --check`. Skutečný Qt WebEngine průchod prošel nad projektem s
  podklady i nad prázdným projektem; ověřil název, popis, nehotové úkoly,
  ruční skrytí/zobrazení promptu, deklarované výchozí stavy a nezměněný Git.
  Navazující geometrická kontrola stejného skutečného WebEngine průchodu
  ověřila také střední layout `2 / 1 1`; po změně znovu prošlo všech **638
  testů** (27 přeskočeno), cílené layoutové testy, JavaScript parser, Python
  kompilace a `git diff --check`.
  Volná levá dlaždice nyní zobrazuje nejvýše 20 posledních commitů projektu
  dosažitelných z ověřeného HEAD: bezpečně vykreslený předmět, datum, autora a
  zkrácené ID, bez cest a diffů. Backendový test ověřuje pořadí, limit i
  indikaci zkrácení. Po této změně prošla celá sada **639 testy** (27
  přeskočeno), cílené testy, JavaScript parser, Python kompilace a
  `git diff --check`; opt-in skutečný Qt WebEngine smoke prošel nad projektem s
  podklady i prázdným projektem a potvrdil historii, responzivní geometrii a
  nezměněný Git stav obou projektů.
  Spodní prompt widget nyní podle schváleného uživatelského návrhu odděluje
  režim, vícenásobné explicitní vstupy, akci, typ výsledku, soukromí a skutečný
  backend/model. Vstupy jsou společný checkboxový výběr konverzace, konkrétních
  podkladů a veřejných zdrojů se souhrnným počtem; nabídku lze zavřít klávesou
  Escape. Akce **Odpovědět** a **Vyhledat na webu** mapují stávající uzavřený
  task plán, zatímco neimplementovaný Julia runner ani oddělený obrazový editor
  se v tomto společném widgetu nevydávají za dostupné schopnosti. Vyhledávání
  rozbalí přímo ve widgetu pole přesného veřejného dotazu a zobrazuje řetězec
  `SearXNG → backend/model`; stávající hash-bound náhled a potvrzení síťového
  účinku zůstávají beze změny. Návrh výsledku se nadále ukládá nebo publikuje
  až samostatnou explicitní akcí. Široké, střední a mobilní rozložení používá
  jediný sdílený HTML/CSS/JS frontend; mobilní odeslání má nejméně 44 px a
  vstupní nabídka nepřetéká mimo viewport. Cílená sada sdíleného desktop/web UI
  prošla 83 testy (8 přeskočeno), JavaScript parser prošel a skutečný Qt
  WebEngine ověřil desktopové přepnutí akcí, vstupní nabídku/Escape a mobilní
  inline hledání při 390 px bez horizontálního přetečení. Následná celá sada
  prošla **640 testy** (27 přeskočeno). Po prvním fyzickém průchodu byl prompt
  dále zjednodušen: ze základního stavu zmizel duplicitní souhrn vstupů,
  technický endpoint, trvalé vysvětlení routování, výchozí instrukce k vláknu
  a spodní klávesnicová nápověda. Zkratka je dostupná v tooltipu odeslání,
  stavové místo se vykreslí jen pro skutečné varování, průběh, chybu nebo
  potvrzení a pokročilé ruční externí volání bylo skryto z běžného toku bez
  odstranění jeho potvrzovací logiky. Opakovaná cílená desktop/web sada prošla
  66 testy (6 přeskočeno), skutečný Qt WebEngine prošel desktopovým i mobilním
  průchodem a celá sada po změně znovu prošla **640 testy** (27 přeskočeno).
  Následující schválené zhuštění přesunulo trvale viditelné popisky Zadání,
  Režim, Akce, Výsledek, Soukromí, Backend a Model dovnitř rámečků jejich
  ovládacích prvků. Samostatná hlavička promptu a ruční
  skrývání byly odstraněny; deklarované automatické skrytí na specializovaných
  záložkách zůstalo zachované. Cílená desktop/web sada po změně prošla 66 testy
  (6 přeskočeno) a skutečný Qt WebEngine ověřil desktopovou i mobilní geometrii
  vnitřních popisků, 44px ovládání a nepřítomnost starého přepínače. Následná
  celá sada znovu prošla **640 testy** (27 přeskočeno). Po společném upřesnění
  nemá webové hledání druhý editor ani alternativní vlastní dotaz: aktuální
  zadání je jeho jediný povinný vstup, viditelný ve Vstupech jako nezrušitelná
  položka. Výsledek hledání je při této akci uzamčený na Konverzaci, odkud jej
  lze v dalším kroku zpracovat běžnou akcí Odpovědět; přesný síťový náhled a
  potvrzení zůstávají zachované. Skutečný desktopový i mobilní Qt WebEngine
  ověřil přepnutí tohoto kontraktu, obnovu předchozího typu výsledku a
  responzivní geometrii; následná celá sada znovu prošla **640 testy**
  (27 přeskočeno). Pokud je v Náhledu otevřený podklad, nabídka Vstupy nově
  zpřístupní také volitelný **Aktuální soubor** s jeho názvem. Při výběru se
  jeho ID deduplikovaně přidá mezi projektové vstupy; bez otevřeného souboru,
  při webovém hledání se položka nezobrazuje a pro externí běh ji nelze vybrat.
  Skutečný desktopový Qt WebEngine ověřil zobrazení, zaškrtnutí a souhrnný
  počet vstupů, mobilní Qt WebEngine zobrazení u otevřeného náhledu a celá sada
  po změně prošla **640 testy** (27 přeskočeno). Jako první převod zbývajících
  nativních dialogů byl uživatelský profil nahrazen formulářem v
  **Nastavení → Profil**. Sdílené HTML zůstává stejné, ale desktop bootstrap
  explicitně zpřístupní node-local panel a úzký endpoint pro načtení a uložení;
  serverová varianta drží záložku skrytou a endpoint bez desktopové služby
  odmítne. Formulář znovu používá původní validaci i atomické SQLite uložení,
  nic nezapisuje do projektu a nepřidává přísnější inferenci kontaktů. Starý
  `UserProfileDialog` a fragmentový Qt most byly po dosažení parity odstraněny
  a A4 inventura nyní profil eviduje jako 18. sdílený formulář. Cílené API a
  HTTPS testy prošly, skutečný Qt WebEngine profil načetl a uložil a následná
  celá sada prošla **641 testy** (27 přeskočeno). První fyzický průchod odhalil,
  že skutečný desktop skládá schopnosti v `desktop_management.py`, zatímco
  zpřístupnění profilu bylo jen v základním UI bootstrapu: po kliknutí proto
  synchronizace skryla položku s dosud skrytou cílovou záložkou. Oprava
  zpřístupňuje záložku i její položku v jediném skutečném desktop bootstrapu;
  ve výchozím serverovém HTML jsou obě skryté. Regresní Qt WebEngine scénář
  nyní otevírá profil skutečným kliknutím z nabídky, ověřuje, že položka
  zůstane viditelná, a teprve poté načte a uloží formulář. Tento skutečný
  desktopový průchod prošel a následná celá sada po opravě znovu prošla
  **641 testy** (27 přeskočeno); parser výsledného desktopového JavaScriptu,
  Python kompilace a `git diff --check` také prošly. Úvodní stránka otevřeného
  projektu následně dostala rozdílné chování podle šířky: na desktopu zůstává
  celý přehled pevný a samostatně se posouvají pouze seznamy Historie změn a
  Úkoly; na mobilu nemají karty ani jejich seznamy vlastní scroll a stránka
  vykreslí nejvýše pět posledních změn a pět nehotových úkolů. Stav přitom dál
  uvádí celkový počet a při změně breakpointu se projekce přepočítá. Skutečný
  desktopový Qt WebEngine ověřil uzamčený vnější panel a oba vnitřní scrolly;
  390px webový Qt WebEngine ověřil limit pěti položek, viditelné overflow a
  jediný scroll celé stránky. Následná celá sada znovu prošla **641 testy**
  (27 přeskočeno). Jako druhý nativní dialog byly **Displeje a role prezentace**
  převedeny do sdíleného webového formuláře presenteru. Formulář je v serverové
  variantě nedostupný; desktop jej zpřístupní capability bootstrapem a přes
  přesně allowlistovaný fragmentový most předává pouze index role a jednorázový
  token konkrétního seznamu obrazovek. Qt dál výhradně zjišťuje fyzické
  displeje, zobrazuje čtyřsekundové identifikátory a přesouvá okna. Připojení,
  odpojení nebo změna geometrie token zneplatní, skryje veřejný výstup a obnoví
  formulář; role zůstávají pouze v paměti presenter relace, takže nevzniká nový
  persistentní zápis ani recovery hranice. Starý `QDialog` a jeho Qt formulář
  byly odstraněny, A4 inventura nyní eviduje 19. sdílený formulář. Cílených 10
  testů mostu, správce displejů a inventury prošlo; skutečný Qt WebEngine otevřel
  formulář přes nativní presenter akci, ověřil nabídky a zrušil jej přes nový
  most. Následná celá sada znovu prošla **641 testy** (27 přeskočeno), parser
  výsledného desktopového JavaScriptu, Python kompilace a `git diff --check`
  také prošly.
  Třetí převod odstranil nativní dialog **Přenos veřejného projektu do LXC**.
  Desktop nyní na konec pásu přidává osmou ikonu **Federace**; server ji drží
  skrytou. Její první položka otevírá samostatnou webovou stránku s
  výběrem projektu, zapamatovaného LXC a veřejné CA, přesným náhledem a
  explicitním potvrzením celé veřejné Git historie. Stránka pravdivě uvádí,
  že jde o přechodovou funkci před plnohodnotnou správou federace projektů v
  další verzi. Web nedostává SSH ani Git writer: jednorázově tokenovaný most
  předá pouze potvrzené indexy a CA, nativní controller znovu ověří nezměněné
  katalogy a teprve potom spustí stávající `git_transfer.transfer`.
  Crash hranice zůstávají beze změny: před commitem lokálního SQLite outboxu
  nevzniká durable přenos; po jeho commitu retry používá stejné operation ID,
  source HEAD, digest a bundle; vzdálená publikace a registrace se obnovují
  existujícím cílovým stagingem a chyba lokálního completion ponechá journal k
  bezpečnému opakování. Běžící operace zamyká opuštění stránky. A4 inventura
  nyní eviduje 20. sdílený formulář a jako nativní ponechává už jen LXC deploy
  a nastavení síťového backendu. Cílených osm testů controlleru, mostu, UI a
  inventury prošlo; parser výsledného JavaScriptu, Python kompilace,
  `git diff --check` a skutečný Qt WebEngine průchod nové ikony, stránky a
  nativně dodaného katalogu také prošly. Následná celá sada prošla **643 testy**
  (27 přeskočeno).
  Čtvrtý převod odstranil nativní dialog **Síťový backend a spojení** a přidal
  jej jako druhou položku desktopové záložky Federace. Sdílená stránka odděluje
  node-local nastavení opt-in HTTPS listeneru od diagnostiky zapamatovaného LXC;
  serverová varianta zůstává se skrytou záložkou bez nové HTTP zapisovací cesty.
  Přes jednorázově tokenovaný a přesně validovaný fragmentový most přechází jen
  hodnoty formuláře, index peeru a veřejná CA. Generování certifikátů, atomické
  uložení konfigurace, ověření schváleného pinu, HTTPS probe a obousměrný SSH
  test zůstávají v nativním controlleru. Obousměrný test má samostatné potvrzení
  přesného routeru, kontejneru a desktopového endpointu. Persistentní hranice
  jsou ve stránce výslovné: nově vygenerovaná, ale dosud nepoužitá TLS složka
  může po následné chybě zůstat; `NetworkBackend.configure` při chybě spuštění
  nebo atomického publish obnoví předchozí listener. Jednosměrná diagnostika je
  read-only. Obousměrná diagnostika může po pozdější chybě zanechat na LXC již
  aktualizovanou veřejnou CA a adresu, ale nemění identity, práva, soukromé
  klíče, firewall ani projektová data. A4 inventura nyní eviduje 21. sdílený
  formulář a jako nativní ponechává už jen LXC deploy. Cílených 74 testů
  controlleru, mostu, sdíleného UI, inventury a serverových hranic prošlo;
  parser výsledného JavaScriptu a Python kompilace také prošly. Skutečný Qt
  WebEngine ve dvou projektových stavech kliknutím otevřel obě položky Federace,
  načetl síťový formulář z nativní vrstvy a nezměnil projektové Git repozitáře.
  Následná celá sada prošla **648 testy** (27 přeskočeno).
- [ ] [planned] **UX-FACELIFT-01-D — regresní a fyzická akceptace
  (cílová úroveň: PoC validated).** Ověřit dotčené desktopové i webové průchody,
  úzký viewport, klávesnici, potvrzení a finální fyzický průchod s uživatelem.

Akceptace celé dávky zůstává otevřená do dokončení interaktivní revize a
uživatelem schváleného implementačního řezu. Samotný A4 balíček dokončuje jen
položku A a není souhlasem s konkrétním redesignem.

## K předání do backlogu

- [ ] [planned] **UX-FEDERATION-02 — plnohodnotná správa federace projektů
  (cílová úroveň: designed).** Uživatelský požadavek pro další verzi: nahradit
  přechodovou stránku jednosměrného veřejného přenosu správou federovaných
  projektů. Při přípravě dávky konsolidovat, nikoli duplikovat, otevřené
  kontrakty M1-AH-14/M1-AH-15 a schopnosti roadmapy M5; výslovně navrhnout
  discovery, vztahy uzlů a projektů, směry operací, oprávnění, konflikty,
  stav/recovery a audit. Podmínkou dokončení návrhu je samostatná reviewovatelná
  feature dávka s vymezením proti pouhému prvnímu Git přenosu.
