<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Přístup, privacy, odvolání a recovery — PROJECT-RELATIONS-01-F

Tento řez sjednocuje bezpečnostní kontrakt již implementovaných B–E,
doplňuje závěrečnou autorizaci přehledu/grafu a ověřuje odvolání i obnovu.
Navazuje na [ADR 0089](adr/0089-project-relations-and-derived-read-access.md),
[lifecycle B](project-relations-lifecycle.md), [resolver C](project-relations-hierarchy.md),
[výstupy D](project-relations-outputs.md) a [UI E](project-relations-ui.md).
Není to evidence lidské akceptace ani pozitivní federované delegace souhlasů.

Zadání: projekt Workspace `c898b941-8eb0-4406-8dad-6e2b96c06d59`, export
`92547e95feab0cfd5f33d4b753cabdb7c46cb80c32d67fbb207676dc13ab1858`,
Workspace HEAD `649f9a5150499cf9abb37ddd77b6159cd463d83e`, packet
`38d4e4da4da61f7bd49f7c069a69b66f9ecf4ce6516ab823546429407b5ca0e9`;
zdrojový základ `5e77896`. Stav autoritativního úkolu se tímto nemění.

## Čtecí právo a jeho rozsah

| Účinná role v příjemci | Odvozené čtení zdroje | Zadání AI v příjemci | Správa vztahu |
| --- | --- | --- | --- |
| reader / reviewer | Ano | Ne | Ne |
| editor | Ano | Ano, podle stávajícího task kontraktu | Ne |
| project-admin | Ano | Ano | Vlastní konec; návrh či změna vyžaduje správu obou konců |
| node-admin / federation-admin / lokální vlastník | Podle dosavadní uzlové autority | Podle dosavadní uzlové autority | Podle dosavadní uzlové autority |
| neaktivní účet / bez přístupu k příjemci | Ne | Ne | Ne |

Pravidla role vyhodnocuje existující `Administration` a `CrossReferences`.
Přístup vyžaduje registraci příjemce, aktivní účet a živý grant. Request scope
je další omezení, nikoli grant. Uživatel nemusí mít vlastní členství ve zdroji;
čtecí cestu dokládá přesná aktivní revize každého vztahu a oba souhlasy.
Přístup k projektu příjemce nelze zaměnit za přímou autorizaci zdroje.
Odvozené čtení neposkytuje zápis, správu členů, souhlas druhého konce ani
oprávnění otevřít celý zdrojový projekt jeho běžným API.

Webový request rozlišuje přímá členství od odvozeného čtení. Interní příznak
`derive_project_relations` nastavuje autentizovaný webový handler; není polem
klientského JSON. Skutečný delegovaný `allowed_projects` nadále omezuje také
všechny mezilehlé zdroje. `parent_of` sdílí data vzhůru; `depends_on` a
`relates_to` pouze publikované výstupy. Nejužší rozsah cesty nelze rozšířit
navazující hierarchií. Cizí artefaktová reference není zkratka do dalšího projektu.

Souhlas je rozhodnutí projektu v okamžiku nativního potvrzení. Pozdější
odchod jeho autora sám nepřepisuje historické rozhodnutí projektu; odvolání
vztahu je samostatný auditovaný krok. Naproti tomu aktuální ztráta práv
čtenáře příjemce okamžitě ruší jeho možnost nového použití.

## Privacy, model a historické doklady

- Projektový pohled čte pouze validovaná Git data. Identita uzlu, credentials,
  SQLite journaly, pracovní drafty a provozní relace nejsou jeho zdroje.
- `local-only` se nabízí pouze uvnitř `same-node`. Webový náhled a jiné hranice
  takové položky vylučují bez zveřejnění jejich názvů, ID či počtu.
- Historický pin vrací přesné původní bajty, ale účinná privacy je přísnější
  z původní a současné. Zpřísnění tedy chrání i historický obsah.
- Výběr textu je výslovný. Context Manifest váže původní ID, commit, obsah,
  metadata, přístupovou revizi, přesnou cestu a případnou publikaci. Manifest
  neobsahuje samotné bajty vstupu. Payload je samostatný a má vlastní otisk.
- Kontrola před dispatch znovu čte oprávnění, cestu, publikaci a privacy;
  nestačí integrita uloženého manifestu. Změna zdrojového HEAD mezi přípravou
  a dispatch také vyžaduje novou přípravu. Data se nevymění potichu.
- Zůstávají dosavadní modelové limity E: sdílené task vstupy používají režim
  Úkol a Ollama. Test hranice `external-provider` v ContextBuilder nedokládá
  zpřístupnění těchto vstupů všem externím adaptérům. Následný webový dotaz
  nesmí vycházet z `local-only`; použití původních pinů se znovu kontroluje.

Odvolání se vztahuje na budoucí čtení a odeslání. Nemůže vzít zpět obsah již
oprávněně předaný modelu či uživateli. Dřívější manifest zachová neměnnou
provenance; není poukázkou na nové načtení zdrojových bajtů. Již vytvořený
výstup zůstává vlastním artefaktem s dosavadní privacy a oprávněními.

## Invalidace přehledů, hledání a připnutého kontextu

| Změna | Následující použití |
| --- | --- |
| Odvolání jednoho konce | Připnutá cesta je neplatná, i kdyby HEAD příjemce zůstal stejný. |
| Nový typ, směr nebo důvod | Nová revize je pending do obou nových souhlasů; stará cesta přestává platit. |
| Odvolání publikace / smazání zdroje | Výstup již není dostupný přes tuto publikaci; historický blob není náhradou grantu. |
| Odvolání účtu, role či registrace příjemce | Další read/pin a připravený dispatch selžou. |
| Zpřísnění privacy | Znovu se posoudí skutečná hranice, včetně historických bajtů. |
| Alternativní cesta či publikace | Starý pin se nepřepne; nová dostupnost vyžaduje nový výběr a pin. |
| Offline, pending nebo neověřitelný graf | Nedostupnost, nikoli tichý prázdný úspěch nebo použití starého obsahu. |

Resolver nemá persistentní obsahovou cache. Držený katalog nebo budoucí
výsledek PROJECT-SEARCH je jen kandidát; `pin/read` vyžaduje živou kontrolu.
Starý provider objekt nezamrazí práva. Každý další krok používá stejné API;
tento řez neaktivuje samostatnou dávku fulltextu ani nový modelový nástroj.

Přehled a graf F dokončují čtení kontrolou stejné projekce a HEAD všech
projektů i původních přístupových revizí. Kontrola práv probíhá před i po
závěrečném scanu. Změna během sestavování zruší celý výsledek bez vrácení
starých názvů či příznaků správy. Není tím předstírán atomický snapshot
různých repozitářů; jde o ověřený stav k poslední kontrole.

UI při obnovení panelu zahodí staré řádky a zakáže vytvoření vztahu, dokud
nezíská celý platný výsledek. Chyba neponechá starý přehled vydávaný za aktuální.
Graf se takto choval už v E. Vybrané piny zadání zůstanou explicitním výběrem,
nikoli ověřenou cache; jejich následné použití prochází znovu backendem.
Už načtená stránka není živý odběr vzdálených revokací. Obnovení a skutečné
použití znovu ověřuje stav; nový grant se neodvozuje z DOM ani ze starých dat.

Místně známé hotové nativní vztahové operace musí zůstat v historii
aktuálního HEAD. `ProjectRelations._known_history` čte původní hotové receipts
s interním příznakem lifecycle a kontroluje jejich commity proti Git historii.
Starší nebo divergující větev nemůže skrýt již známé odvolání nebo novou
revizi. Při nesouladu se celý vztahový pohled odmítne; obnoví se původní
historie nebo její sémanticky validované sloučení. Journal se nemaže a index
není náhradním důkazem. Rozhodnutí a původní reprodukční test popisuje doplnění
ADR 0089. Uzel, který vzdálené odvolání nikdy neviděl, tím nezískává důkaz
jeho aktuálnosti; nejde o náhradu federované autority.

## Nový uzel a federovaná autorita

Projektová vazba není oprávnění přenést zdrojový Git na nový uzel. Přenos
má vlastní příjemce, projektový scope a privacy politiku podle
[ADR 0081](adr/0081-complete-project-data-sync.md). `git_transfer.validate_history`
kontroluje i historické bajty, takže současná metadata nemohou legalizovat
historický `local-only` obsah. Podpis existující synchronizační obálky
ověřuje původ a integritu přenosu; není důkazem, že konkrétní projektový
správce udělil tento souhlas s touto politikou.

Bezpečné chování současného PoC je proto explicitní: importovaný souhlas
bez ověřitelné nativní autority zůstává `unavailable`. Samotný JSON autora,
Git email, obecný importní receipt ani podepsaný bundle se nepovýší na
projektový grant. Journal ani credentials se nekopírují jako náhrada důkazu.
F ověřuje tento zákaz na skutečných Git kopiích dvou projektů registrovaných
na druhém izolovaném uzlu, bez kopie journalů. I fyzicky přítomný obsah
zdroje se tím nestane odvozeně dostupným.

Pozitivní federovaná delegace projektových souhlasů zde implementovaná není.
Pro její bezpečné zavedení je třeba samostatně ověřit projektovou autoritu
podepisujícího při udělení souhlasu, přesný digest/revizi/politiku a oba konce,
platnou důvěru v uzel a aktuálnost odvolání. Přijímací grant musí zabránit
rollbacku na starší repliku a nesmí automaticky rozšířit přenosový scope.
Neznámý/offline stav nesmí sloužit jako důkaz neexistence odvolání. Přenosový
podpis sám tyto podmínky neplní. Tento dokument tyto požadavky pojmenovává,
nepřidává neověřený podpisový protokol a netvrdí pozitivní federovanou akceptaci G.

## Crash boundaries a recovery

Platí původní [ADR 0003](adr/0003-coordinated-operation.md) a hranice
ADR 0089/B beze změny. F nepřidává persistentní vrstvu ani writer.

| Hranice | Autorita a očekávaná obnova |
| --- | --- |
| Náhled před intentem | Oba HEAD, digest a práva musí stále platit. Chyba je bez zápisu. |
| Prepared intent před ref | Lokální journal vlastní přesně schválené bajty. Resolver pending stav odmítne. Explicitní recovery nebo stejná operace použije tento intent. |
| Commit objekt před ref | Samotný objekt neuděluje grant; recovery dokončí původní publikaci ref. |
| Ref před indexem/receipt | Git obsah je uložený, ale nedokončená operace není doklad aktivního souhlasu. Recovery dokončí stejný commit, index a receipt. |
| První konec bez druhého | Pending, žádné nové čtení. Druhý souhlas je samostatná transakce, ne distribuovaný commit. |
| Jednostranné odvolání | Po obnově je cesta revoked; replay předchozího souhlasu ji neoživí. Pending odvolání už blokuje nové čtení. |
| Změna revize bez nových souhlasů | Pending; předchozí souhlasy novou revizi nenahradí. |
| Hotovo, ztracená odpověď | Stejný operation ID a request vrátí původní receipt; odlišný request se odmítne. |
| Stale index po restartu | Obnovitelná projekce HEAD, nikoli nový grant. Chybějící autoritativní journal nelze zrekonstruovat jako souhlas z indexu. |

Běžný resolver nepřebírá odpovědnost za dokončení pending zápisu. Recovery
nezískává nový souhlas od agenta; dokončuje původní schválený intent. Zámky
se nedrží přes lidské potvrzení či síť. Neznámý výsledek nezpůsobí automatické
nové operation ID ani nový placený modelový běh.

## Ověřovací důkazy

Nové [testy bezpečnosti](../tests/test_project_relation_security.py) ověřují
čtyři role bez zdrojového členství, nemožnost správy zdroje, odvolání práv
před dispatch se zachováním provenance, současnou privacy historického pinu,
neplatnost držených search kandidátů, souběžné revokace při tvorbě grafu a
přehledu, zákaz návratu HEAD před známé odvolání a nedůvěru v Git kopie souhlasů na novém uzlu. Browser test navíc
ověřuje odstranění starého přehledu a akcí po 403.

Stávající nativní testy B procházejí deset checkpoints původního writeru,
replay i skutečný `os._exit` před/po ref. Testy C/D ověřují pending journal,
obnovu indexu, odvolání alternativních cest/publikací, smazání zdroje a
privacy. Regrese UI/HTTPS ověřují přímé a odvozené role samostatně.
Samotné tyto testy nenahrazují živé hledání reálným LLM, pozitivní federovanou
delegaci, závěrečnou sadu celé dávky ani lidskou akceptaci G.
