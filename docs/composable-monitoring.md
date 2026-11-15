<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Sledování ze samostatných bloků

V projektu vyberte konkrétní kategorii v levé liště **Nástroje**.
Filtry, pooly a zpracování mají [samostatná GUI](monitoring-entity-workspaces.md);
komplexní úloha je agregát jejich tabulek, bez vlastního editoru bloku.
Společný strom a menu založení popisují [Nástroje](tools-sidebar.md).
Starší editory ani migrační panel se již nezobrazují; jejich historická data
a explicitní servisní API zůstávají zachována. Založení bloků stará data
nepřevádí ani neaktivuje.

| Přehled | Obsah |
| --- | --- |
| Zdroje | RSS/Atom URL, interval, přístupové a retenční podmínky; také uložené dotazy webového hledání na vyžádání. |
| Filtry | Výběr více kanálů, pravidla a cílový pool. Více filtrů může přispívat do stejného poolu. |
| Pooly zpráv | Počet zpráv, jejich obsahové verze, pozorující uzly, důvody výběru a poslední potvrzený příjem synchronizace. |
| Zpracování zpráv | Více vstupních poolů, volitelná webová hledání, zadání, způsob a místní či konkrétní vzdálený uzel. |
| Komplexní úlohy | Agregát tabulek sdílených bloků; výběr existujících, založení položky jejím vlastním formulářem a návrh pomocí LLM. |
| Výsledky a běhy | Návrhy a vydané zprávy, běhy celé úlohy i jednotlivých zpracování, chyby a unknown příjem. |

U každého bloku je klikací využití. U úlohy se započítají i nepřímé vazby,
například kanál filtru, který plní zvolený pool. Sdílená definice se při
připojení nekopíruje. Historický běh zachová připnutou definici i vstupy;
pozdější změna společného bloku jej nepřepisuje.

## Doporučený postup

Návrhy filtrů a sestav pomocí LLM lze nově
[ověřit na skutečných ukázkách vybraných kanálů](monitoring-design-calibration.md).
Review ukáže výsledky původního filtrovacího enginu a neověřené vstupy.

1. Založte pool a RSS kanály; u kanálu vyplňte podmínky přístupu a uchování.
2. Vytvořte filtr, vyberte kanály a cílový pool. Jednoduchý editor nabízí
   výrazy a regex; bez nich přijímá všechny položky po deduplikaci. Pokročilé
   existující postupy zachová přesně, jejich kroky tímto stručným editorem
   nepřepisuje. Konektory a izolovaný regex mají původní bezpečnostní limity.
3. Založte zpracování nad jedním či více pooly. Pro hledání nejdřív přidejte
   zdroj typu Webové hledání a následně jej vyberte ve zpracování.
4. V komplexní úloze vyberte existující bloky nebo použijte **Vytvořit nové**.
   Po uložení nového bloku se vrátíte do rozpracované sestavy. Závislosti
   se dohledávají přes jejich ID; úprava společného filtru nevyžaduje ručně
   přepisovat seznam kanálů všech navazujících úloh.
5. Sběr zapněte na kterémkoliv oprávněném uzlu; aktivace i pozastavení se
   přenesou běžnou synchronizací projektu. Neexistuje výhradní těžař ani
   volba RSS leadera. Aktivovaný kanál se načítá podle svého intervalu i bez
   filtru; aktuální filtry se použijí při načtení. Jejich změna, přidání ani
   odebrání sběr nezastaví a nevyžaduje novou aktivaci kanálu. Při příští
   splatné kontrole se po změně filtrů/poolů vyžádá celé tělo kanálu, aby
   HTTP 304 nepřeskočilo nová pravidla. Bez filtrů se eviduje výsledek kontroly
   a počet vstupů, obsah se do poolu neukládá. Aktivace platí pro stabilní
   ID kanálu; změny definice ji samy neruší a HTTP validátory se při změně
   zdroje nebo výběrových pravidel zneplatní.
6. Spusťte zpracování nebo celou úlohu. Běh úlohy připraví návrhy svých
   zpracování na místním uzlu, i když je pro plánované běhy určen jiný uzel.
   Ruční spuštění používá místní model a oprávnění. Jednotlivé návrhy lze vydat po dokončení
   [hodinového ochranného období](report-protection.md).

RSS má vlastní interval a nevolá LLM. Zpracování může běžet ručně nebo
jednou denně ve zvoleném místním čase a časové zóně. Denní slot má stabilní
identitu; restart jej nespustí podruhé. Po výpadku se provede nejvýše aktuální
splatný slot, nevyrábí se zpětně řada zmeškaných vydání. Webové hledání nemá vlastní periodický sběr; spouští se až jako vstup
konkrétního sestavení zprávy, případně při aktivovaném
[kalendářním zpracování](monitoring-processing-calendar.md).
Uložení rozvrhu jej neaktivuje; aktivace zpracování je samostatná sdílená akce.
Přenos aktivace, návrhů i chybových výsledků popisuje
[sdílený stav monitoringu](monitoring-shared-state.md).

## Historický panel převodu a zachované servisní API

Následující popis zachovává původní migrační kontrakt a názvy tehdejšího
panelu. Panel byl následně odstraněn podle
[aktuálního rozdělení](current-monitoring-read-isolation.md).
Operace preview/apply/resume/cancel zůstávají explicitním servisním API,
které používá původní writer a recovery. Nový browser scénář ověřuje API
a výsledek v aktuálním katalogu, nikoli existenci starých ovládacích prvků.

V hlavní části je **Jednorázový převod starších sledování → Vybrat sledování
k převodu**. Před ostrým převodem aktualizujte všechny vykonávající uzly,
pozastavte starý provoz na ostatních uzlech a vyřešte tam rozpracované/unknown
operace. Lokální journal jiného uzlu se nepřenáší; samotný náhled na desktopu
neprokazuje jeho vyřešení na Omnii.

1. Vyberte původní zadání a související vstupní sledování, retenční dobu
   převzatých zpráv a případné nové konkrétní přiřazení uzlu.
2. RSS definice s explicitním levným filtrem se rozloží na zdroje, filtr,
   pool a navazující zpracování/úlohu. U původních víceperiodových dokumentů
   výslovně vyberte nové vstupní pooly; každé období dostane samostatné
   zpracování. Stejné mapování lze zvolit jako výslovnou náhradu starého
   vstupního řetězce. Dokumenty a obecné URL se neodhadují jako RSS.
3. **Zobrazit náhled převodu** ukáže vazby, počty převzatých/expirujících
   zpráv, soukromí a upozornění. Nová zpracování budou ruční, s viditelným
   oknem posledních 1/7/31/93/366 dní podle původní periody; původní kalendář,
   začátek období a nastavení prezentací zůstávají v archivu. Nejde o zachování
   starých automatických rozvrhů. Původní analytická metodika s případovými
   studiemi a jiné nejednoznačné vazby převod blokují; nezploští se potichu.
4. **Převést podle tohoto náhledu** uloží bloky i migrační audit jedním
   projektovým commitem a převezme platné vybrané nálezy do poolů. Historické
   definice, vyřazené položky, reporty a jejich důkazy zůstanou v původním Gitu.
   Nevyhodnocené položky se nestanou vybranými. Stav unknown/failed vyžaduje
   posouzení; není vydáván za úspěšný převod nálezu.

Nové bloky zůstávají vypnuté do samostatné aktivace. Staré zadání po převodu
slouží jako archiv; aktualizované uzly čtou stejný migrační záznam a odmítají
jeho opětovné spuštění i editaci přes staré API. Opakování dokončeného
převodu vrátí původní výsledek bez duplicit.

Při přerušení se nabídne **Dokončit přerušený převod**. Nejdřív se obnoví
původní Workspace operace, poté import a místní granty. Nové bloky nelze
aktivovat, dokud se převod nedokončí. Před uložením definic lze použít
**Zrušit dosud neuložený převod** a připravit nový náhled, například po
souběžné cizí změně. Po Git commitu je nutné původní převod dokončit.
Jeden převod je omezen na 31 nových bloků a 500 nálezů; nezávislé větší
skupiny lze převádět odděleně. Podrobnosti: [ADR 0083](adr/0083-one-time-monitoring-migration.md).

Starší formuláře a workery se odstraní až v navazujícím kroku po ověření
převodů. Čtení historických revizí a jejich provenance musí zůstat dostupné.

## Sestavení pomocí LLM

**Sestavit pomocí LLM** předá nastavenému modelu popis, katalog a uzavřený
kontrakt bloků. Používá existující Ollama binding a backend run journal;
bez nastaveného dostupného modelu nevytváří náhradní předstíraný výsledek.
ContextBuilder před dispatch kontroluje privacy; local-only katalog nesmí
odejít ani na private-network model. Model nedostává credentials.

Návrh rozlišuje nové či upravené bloky a použití existujících. Jednotlivé
bloky lze upravit formulářem. **Uložit posouzenou sestavu** používá jedinou
Reporting/Workspace transakci. Nic neaktivuje ani nevydává. Změněný HEAD,
neexistující reference, chybný typ vazby nebo snížení privacy se odmítnou.

## Pooly a federace

Definice jsou neměnné Reporting revize v Gitu. Obsah poolů, členství,
pozorování a rozpracované nové běhy jsou v samostatném `message-pools/pools.sqlite`
pod privátním reporting runtime adresářem uzlu. Jde o autoritativní data,
nikoli rebuildovatelný projektový index. Chybějící nebo cizí DB se nesmí
nahradit prázdnou kolekcí. Databáze se mezi uzly nekopíruje.

Původní podepsaná synchronizace projektu přenáší pooly jako logický sidecar
exchange verze 3. Je podporován úplný **same-team / all** projektový scope.
Vybrané větve same-company pooly nepřenášejí. Oba uzly musí mít tuto verzi
implementace; starší příjemce nový formát odmítne. Původní přenos bez poolů
zůstává exchange v2. Při nevyřešené divergenci projektových definic zůstane
pool přenos čekat na vyřešení Git konfliktu. Příjem sdílené aktivace mění zapnutí/pozastavení bloku podle
[aktuálního kontraktu](monitoring-shared-state.md). Provozní granty starých
WatchDefinition ani soukromé rozpracované journaly se nepřenášejí.

Stejná položka z více uzlů má jednu obsahovou revizi a více pozorování.
Stejné URL v poolu seskupuje příspěvky více filtrů; rozdílné obsahy se
zachovávají jako verze bez odhadu, která je nejnovější. GUI je označí jako
více obsahových verzí. Zpracování položku ostatním spotřebitelům neodebere.
Přenesené členství musí odpovídat skutečnému filtru, jeho revizi a poolu.
Local-only členství ani obsah se neexportují.

Jeden sidecar je omezen na 8 MiB a 20 000 záznamů. Při překročení přenos
viditelně selže; stránkování zatím není implementováno. Kolekce po dobu
své retence poskytuje vstupy zpráv, jejich časované expirace se po startu
uklidí před čtením či přenosem. Nevybrané texty se do této DB ani Gitu
neukládají. Jde o retenci kolekce, nikoli garanci odstranění vydaných zpráv,
modelových auditů, dokončených sync payloadů v původním transportním journalu,
cizích záloh či historických raw feedů původního monitoringu. Nová publikace
ukládá text posouzené zprávy a audit referencí/hashů, nikoli celý pool.

## Obnova a ověření

Crash boundaries a reuse popisuje [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md).
Známá přechodná chyba zdroje zůstává chybou a další kontrola respektuje
interval i Retry-After/backoff. Přerušený HTTP dispatch je unknown a blokuje další automatický GET stejného
kanálu. Po posouzení lze příjem uzavřít jako opuštěný a povolit další
kontrolu. Tím se původní neznámý výsledek nemění na úspěch. Příjemce sloučí
pool transakčně a opakování stejného přenosu nevytvoří duplicity. U modelu
unknown znamená samostatné posouzení, nikoli automatický nový pokus.

Testy používají izolované projekty, syntetické feedy, řízené hodiny a
modelové transporty. Neprokazují fyzické nasazení na Omnii, dostupnost
skutečných RSS kanálů ani lidskou akceptaci MON-08-12.

Ověření základního řezu ADR 0082, commit `b9c4a1a` (před přidáním převodu):

- `python3 -m unittest discover -s tests -v`: 1 805 testů, OK, 54 přeskočeno.
- Samostatný běh s `M0_DESKTOP_TEST=1`: 3 skutečné Qt/WebEngine scénáře OK
  (nové katalogy a inline sestava, původní editor, review/publish/presenter).
- Izolované HTTPS/RBAC scénáře jsou také součástí plné sady.
- Sdílený monitoring JavaScript prošel `node --check`; odkazy v dotčených
  návodech a whitespace celého diffu včetně nových souborů jsou zkontrolované.

Výsledky nejsou ruční akceptací běžného profilu ani nasazením na Omnii.

Ověření doplněného převodu ADR 0083:

- Regresní běh monitoringu, RSS, Reporting, poolů, modelové syntézy a tiskových
  formulářů: 128 cílených testů OK.
- Migrační scénáře ověřují devět skutečných ukončení procesu včetně importu
  zpráv, CAS/stale náhled, idempotentní replay, předcommitové zrušení,
  blokování unknown a nejednoznačných pravidel a privacy původních podkladů.
- Podepsaný dvouuzlový test přenesl migrační zákaz i pool; pozorující uzel
  zůstal původní, granty se nepřenesly.
- HTTPS/RBAC a dva prohlížečové scénáře: 8 testů OK. Finální migrační Qt scénář
  samostatně ověřil i zachování vzdáleného node ID mimo místní seznam.
- JavaScript syntaxe, odkazy a finální diff včetně nových souborů prošly kontrolou.

Plná sada 1 805 testů výše patří předchozímu commitu `b9c4a1a`, nikoli tomuto
doplnění. Celá závěrečná brána dávky zůstává na jejím finálním předání.
Živá uživatelská data tato implementační práce nepřeváděla.

## Co ověřit, když na druhém uzlu chybí data

Definice filtrů, zpracování a komplexních úloh jsou součástí projektového
Gitu; zprávy v poolech se přenášejí výše popsaným sidecarem. Stav busy nebo
konflikt nedokládá dokončený přenos. Diagnostický `busy_resource` rozlišuje
například `node-registry` a `project-journal`; nejde automaticky o obsazený
filtr nebo o chybějící podporu přenosu.

Po úspěšném ručně sledovaném syncu UI obnoví otevřený přehled sledování
stejného projektu. Nečte skrytý panel a nepřepisuje rozepsaný blok, návrh
sestavy ani probíhající uložení. Přechod do přehledu nebo tlačítko
**Obnovit přehled** načte aktuální data samostatně.

**Výsledky a běhy** zatím zobrazují místní provozní záznamy. Vydané texty
jsou v projektovém Gitu, ale jejich přijetí nevytvoří místní záznam běhu
ani kopii vzdáleného journalu. Chybějící položka v tomto přehledu proto
sama nedokládá, že chybí vydaný dokument. Jednotná projekce přenesených
vydaných výstupů do tohoto přehledu zůstává nedokončená.

Regrese `tests.test_message_pool_sync` ověřuje přesné definice v katalogu
příjemce, text vytěžené zprávy v poolu a zachování vypnutého sběru.
`tests.test_monitoring_polling` ověřuje obnovu po úspěšném syncu, odlišný
projekt, busy stav, souběžná čtení a ochranu rozepsaných editorů.

Ověření tohoto doplnění: 12 testů přenosu úplných dat/poolů, 5 testů
rozšířeného pool přenosu a obnovy UI a 28 regresních testů bloků/navigace/UI
prošlo (celkem 45 provedení, 1 volitelný skip; některé selektory se překrývají).
Sestavený JavaScript prošel `node --check`; `git diff --check` prošel.
Plná sada nebyla opakována. Izolované přenosy nejsou akceptací živého
přenosu desktop → Omnia. Živá read-only diagnostika 11. 11. 2026 stále
zachytila odmítnutí `node-registry` a `project-journal`; tato UI změna
jejich příčinu neodstraňuje a nebyla vzdáleně nasazena.
