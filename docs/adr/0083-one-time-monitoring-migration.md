<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0083 — jednorázový převod starších sledování

Datum: 2026-11-08. Zadání uživatele navazuje na ADR 0082 a MON-08-10.
Staré čtečky zůstávají dočasně kvůli historii; nový provoz používá bloky.
U víceperiodových v1 dokumentů a při změně vstupního řetězce musí uživatel
výslovně přiřadit nové pooly; náhrada vstupů není odvozena z textu zadání.

Převod má náhled připnutý na projektový HEAD, explicitní výběr sledování,
retenční dobu a cílový uzel. Neodhadnutelné vstupy, modelové vyhodnocovací
postupy a reportové řetězce, pro které nový model nemá ekvivalent, jsou
blokující položky, ne tiché zploštění či změna metodiky. Změna rozvrhu na
ruční zpracování je v náhledu výslovná; automatická aktivace není součástí
převodu. Starší definice, běhy, vydání a provenance se nemění.

Bloky mají deterministické identity odvozené od původních identit. Jeden
Reporting/Workspace commit uloží nové bloky i neměnný MonitoringMigration
záznam: přesné původní reference, mapování a parametry schváleného převodu.
Ten synchronizuje zákaz dalšího starého provozu na aktualizované uzly.
Odstranění podpory starých schémat a přepis historického Gitu nejsou součástí
převodu. Starý nenainstalovaný worker tento zákaz neumí číst; před ostrým
převodem je nutné aktualizovat všechny vykonávající uzly, pozastavit starý
provoz na ostatních uzlech a vyřešit jejich rozpracované/unknown operace.
Kontrola lokálního journalu není distribuovaným důkazem quiescence.

## Persistentní hranice a recovery před implementací

Reuse Reporting.apply / Workspace.transact a jejich CAS, journal a receipt
podle ADR 0068; kolekce poolů používá transakci ADR 0082. Nevzniká druhý
projektový writer ani kopírování provozních SQLite souborů.

1. Před zápisem se ověří konkrétní náhled a neexistence nedořešených starých
   dispatchů. Místní worker zámky brání souběžnému sběru. Prepared, collecting,
   unknown a nedokončené RSS polly blokují převod; rozpracované výsledky se
   nikdy neprohlašují za zpracované ani automaticky nezahazují.
2. Trvalý lokální migration intent obsahuje původní náhled, schválené hashe
   a stabilní operation ID. Pád před commitem používá původní Workspace
   recovery. Retry se stejným ID nemění zadání a nevytváří jiné bloky.
   Překrytí jiné rozpracované migrace blokuje nový převod stejného sledování.
   Pokud ještě nevznikl commit a cizí změna zneplatnila náhled, lze intent
   výslovně zrušit; po commitu se pouze dokončuje původní operace.
3. Po Git commitu marker ihned zakazuje starý sběr a nové staré zpracování.
   Pád před naplněním poolu nechá nové bloky neaktivované. Z původního
   receipt a intentu se dopočte import vybraných nálezů bez nového fetch/LLM.
4. Obsahové revize, členství a pozorování se slučují v jedné pool transakci.
   Stejný marker/operation ID import neopakuje jako nové položky. Původní
   záznam výběru zůstává dohledatelný v migračním auditu a historickém Gitu.
5. Nakonec se místní staré granty a bindings zneplatní a intent označí za
   dokončený. Pád mezi tím a odpovědí se dořeší replayem. Synchronizovaný
   marker neaktivuje nový sběr; každý uzel potvrdí novou konfiguraci zvlášť.

Historické vybrané nálezy se převezmou pouze v rámci zvolené retence;
vyřazené/nevyhodnocené položky se nepovýší na vybrané. Přesný počet importů,
expirací a blokujících položek je součást náhledu. Historické původní bajty
v Gitu se nemažou a nejde o garanci odstranění starého obsahu.

Migrační audit připíná až 500 původních nálezů a 128 definic. Jen pro nový
MonitoringMigration je provenance.inputs rozšířeno na nejvýše 628 unikátních
Ref; limity ostatních Reporting typů se nemění. Původní uzel pozorování se
nepřepisuje na uzel převodu. Starší neznámá identita pozorujícího uzlu zůstane
explicitní null v pool observation; čas pozorování se zachová.

## Další odstranění kompatibility

Po posouzení převodů a aktualizaci všech uzlů lze odebrat staré zakládání,
editory a workery. To není součást této změny ani automatická akceptace
MON-08-10; historické formáty a provenance zůstávají čitelné.

Ověření používá izolované projekty, syntetický RSS a lokální podepsaný sync.
Zahrnuje skutečná ukončení procesů na devíti hranicích a reálný Qt/WebEngine
průchod náhledem, převodem a čtením archivu. Nejde o nasazení na Omnii ani
schválený převod běžného profilu. Rozsah a výsledky viz
[návod](../composable-monitoring.md#jednorázový-převod-starších-sledování).
