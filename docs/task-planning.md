<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Projektový plán a podgrafy

## Úprava jedné položky

V pohledu **Plán** otevřete detail milníku, dávky nebo úkolu a zvolte
**Upravit tuto položku**. Společný raw editor načte vlastní Markdown blok
položky s popisem, vztahy a případným checklistem. Podúkoly dávky ani ostatní
obsah souboru do editoru nevstupují. **Uložit** změní pouze tento blok a vrátí
vás do plánu; neuložené změny chrání běžný dialog při odchodu z editoru.

Stabilní ID, typ a hierarchie se tímto způsobem nemění. Pro přesun použijte
celý zdrojový seznam. Při chybě revize zůstane draft zachovaný;
po nejasném výsledku lze zopakovat stejné uložení se stejným ID operace.
Projekt pouze pro čtení tuto akci nenabízí. Recovery a přesné hranice změny
popisuje [ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md#dílčí-úprava-jedné-položky-plan-editor).

## Nová položka, závislosti a mazání

**Přidat kořenovou položku** nad plánem vytvoří milník. V detailu milníku nebo
dávky přidáte **Přidat dávku** / **Přidat úkol**: vyplňte název, volitelně popis,
stabilní ID (jinak se vygeneruje) a závislosti. Položka se zařadí jako poslední
potomek a typ určí profil plánu.

**Upravit závislosti** v detailu nastaví přesný seznam předpokladů; cyklus nebo
neznámé ID se neuloží. Závislost zapsanou u jiné položky přes `blocks` je nutné
odebrat tam.

**Smazat položku** nejprve ukáže celý mazaný podstrom. Smazání se nenabídne,
pokud na položce závisí jiná položka, je ve vaší frontě úkolů, odkazuje na ni
výřez nebo jiný vztah, nebo jde o dávku v samostatném souboru. Text zůstává
v historii projektu. Recovery popisuje
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md#vytvoření-závislosti-a-mazání-položky).

## Zápis plánu a vztahů

Hlavní seznam úkolů je autoritou. Každý checkbox začíná stabilním ID:

```markdown
- [x] [CORE-01] Připravit základ
- [ ] [UI-02] Zobrazit výsledek
  - závisí na: CORE-01
  - souvisí s: DOC-01
```

Podporované kanonické vztahy jsou `depends_on`, `duplicates`, `supersedes`,
`relates_to` a `parent_of`. České popisky `závisí na`, `blokován`, `blokuje`,
`duplikuje`, `duplikován`, `nahrazuje`, `souvisí s` a `rodič` se převedou na
jedinou kanonickou hranu. Jen dependency hrany ovlivňují připravenost,
blokování a kritickou cestu.

Podgraf je běžný Markdown dokument s tagem `plan-subgraph`. Jeho checkboxy
odkazují pouze na existující ID, např. `- [ ] [UI-02]`. Stav a případný text
v podgrafu se ignorují; zobrazí se kanonický úkol z hlavního TODO.

## Profilované typy a více definičních souborů

Profil `software-development/v1` podle [ADR
0059](adr/0059-file-plan-hierarchy-and-task-editor.md) používá
`milestone → batch → task`: milník je strategický výsledek, batch jedna feature
větev/PR a task nejmenší změna normálně cílená na jeden commit. Typ je povinné
metadata `type` a rodič vychází z fyzického vnoření.

Každý z těchto uzlů může mít pod `type` jednu nebo více obyčejných vnořených
odrážek. Ty tvoří víceřádkový popis uzlu; rozpoznaná metadata jako `type` a
`depends_on` do popisu nepatří. Například:

```markdown
- [ ] [MILESTONE-01] Import projektu
  - type: milestone
  - Importovat roadmapu, úkoly a popisy z původního projektu.
  - [ ] [BATCH-01] Načíst soubory plánu
    - type: batch
    - Zachovat původní bajty a stabilní ID položek.
    - [ ] [TASK-01] Ověřit vstup
      - type: task
      - Neplatný bundle odmítnout bez částečné projekce.
      - [x] Neplatný vstup skončí validační chybou.
      - [ ] Chyba zachová původní soubor beze změny.
```

Checkbox odrážky bez stabilního ID jsou v profilovaném plánu povolené pouze
pod uzlem `task` a až po jeho `type: task`. Jsou bounded podmínkami splnění se
stavem a textem, nikoli další úrovní hierarchie. Nevstupují do počtu uzlů,
dependency grafu ani stromu roadmapy; task zůstává leaf typem.

Batch může tasky obsahovat jako vnořené odrážky, nebo jeho titul může být
přesný Markdown odkaz `artifacts/UUID/content.md`. Odkazovaný dokument začíná
`<!-- fpw-plan-document: definitions/v1 -->` a obsahuje kořenové leaf tasky.
Obě varianty vytvářejí stejné `parent_id`; graf je materializovaná read-only
projekce verzovaných task souborů, nikoli další autorita. Kombinace odkazu a
inline potomků, neznámá cesta, rekurze a duplicitní ID fail-closed odmítnou
projekci.

Kanonická definice ID smí být právě v jednom souboru bundle. Podgraf i potom
pouze vybírá ID a nepřebírá jejich stav. Uživatelský příklad je v
[návodu ke vzorům a skládání plánu](document-patterns-and-task-authoring.md).

Položka **Plán** v levé liště zpřístupňuje strom roadmapy a seznam podgrafů.
Kořen `/` otevírá hlavní profilovaný pohled: milníkové pruhy s popisem a batch
karty s popisem. Dependency hrany batch mohou vést i mezi různými milníky;
plátno proto roste do šířky a lze je vodorovně posouvat, zatímco levý nadpis a
popis milníku zůstávají ukotvené. Pod `/` strom obsahuje milestone a jejich
batch, ale už ne tasky. Výběr milestone přepne plátno na pruhy jeho batch a
task karty uvnitř; výběr batch tentýž pohled zúží na jediný pruh. Karta tasku
shrnuje stav checklistu a detail ukáže jednotlivé podmínky.

Roadmapa je pouze pro čtení. Hlavní TODO a odkazované task soubory lze upravit
specializovaným editorem **Kostky / Raw text**. Kostky mění jen rozpoznané
řádky; před uložením existujícího souboru se celý draft ověří proti přesnému
committed bundle a expected HEAD. Neplatné nebo duplicitní ID, neznámý cíl,
profilový či dependency cyklus odmítnou projekci; projekt a raw editor zůstanou
dostupné.

## Pracovní stavy a SUM

V detailu položky zvolte **Upravit tuto položku** a v editoru použijte
**Stav položky**. Změna připraví Markdown draft; potvrzuje ji tlačítko
**Uložit**. Podporované stavy jsou Plánováno, Probíhá, Vyřešeno, Selhalo,
Dokončeno a Odloženo. Stejné barevné štítky vidíte v plánu a frontě; pole
**Stav** filtruje graf. Kritická cesta a připravenost jsou oddělené příznaky.

Milníkům a dávkám lze nastavit **SUM — odvodit z položek**. Stav se pak
počítá ze všech potomků, včetně skrytých filtrem a těch v samostatných
souborech. Převládá Selhalo; všechny dokončené položky znamenají Dokončeno,
všechny odložené Odloženo, pouze plánované/odložené Plánováno, pouze
vyřešené/dokončené Vyřešeno a ostatní směsi Probíhá. Prázdná skupina je
Plánováno. Přepnutí na ruční stav agregaci vypne.

SUM ani Vyřešeno automaticky nepotvrzují splnění skupiny či přijetí práce
agenta. Checkbox a lidské review zůstávají samostatné. Přesná pravidla a
zápis `status:` popisuje [ADR 0067](adr/0067-plan-work-states-and-sum.md).

SUM lze zapsat přímo do značky skupiny, například
`- [SUM] [MILESTONE-DEV] DEV` s následujícím řádkem `  - type: milestone`.
Tento zápis zachová agregaci při uložení i úpravě názvu. Pro běžný úkol
či podmínku checklistu značka SUM povolená není.

## Vnořené odrážky v náhledu zdrojového seznamu

Markdown náhled zachovává odsazení odrážek: popis dávky, vnořené části
popisu a podřízené úkoly zůstávají ve svých seznamech. Prázdný řádek před
podúkolem nezruší jeho vizuální vazbu na dávku. Návrat k menšímu odsazení
uzavře příslušnou úroveň, například při začátku další dávky.

Náhled nepřepisuje zdrojový dokument ani identifikátory úkolů. Validace
plánovacího grafu zůstává samostatná; struktura vnořeného seznamu nenahrazuje
kontrolu stabilních ID, vztahů a typů uzlů.

Detail položky v Plánu používá samostatnou Markdown projekci popisu, která
zachovává odrážky a jejich odsazení. Textová projekce zůstává dostupná pro
stručné karty a kompatibilní klienty. Podúkoly dávky se zobrazují zvlášť jako
odkazy do jejich detailů; netvoří součást popisu rodiče.

Chyba validity (například duplicitní ID či chybějící typ) nesmí odstranit
rozpoznané hranice položek. Plán, sidebar i strukturovaný editor v takovém
případě zobrazují pouze čitelnou strukturu fyzických bloků. Odsazení určuje
vnoření, číslo řádku rozlišuje i stejné ID. Tato projekce není plánovací graf:
nelze z ní potvrzovat úkoly, exportovat platný graf ani spouštět práci.
Typ odvozený pro náhled je výslovně označen jako nedeklarovaný. Oprava údajů
probíhá v raw textu a při uložení znovu podléhá původní úplné validaci.

## Ručně rozepsaný soubor roadmapy

Při ruční úpravě hlavního souboru plánu na lokálním desktopu není nutné
commitovat každou rozepsanou část jen pro její zobrazení. Znovuotevření Plánu
zpřístupní současný pracovní soubor jako volitelný rozpracovaný náhled. V něm uvidíte
již napsané popisy i samostatné bloky úkolů, i když další část nemá doplněné
typ nebo jiné povinné údaje. Úplná validace se tím nevypíná.

Hlavička položky ve tvaru checkboxu se stabilním ID otevírá nový blok.
Odsazení určuje jeho rodiče; milník i dávka mohou mít vlastní popis a současně
podřízené položky. Začátkem podúkolu končí vlastní popis rodiče. Náhled nikdy
neslučuje dva bloky jen kvůli stejnému ID.

Rozpracovaný obsah se čte také v lokálním náhledu zdrojového dokumentu a při
výslovném otevření jeho náhledu v editoru. Při další změně na disku znovu
otevřete Plán. Náhled nic nezapisuje, nepotvrzuje ani nepředává do fronty;
uložený plán a jeho revize zůstávají oddělené. Editor rozpracovaného souboru
je pouze pro čtení, aby nepřepsal právě prováděnou externí úpravu. Pokračovat
lze ve vlastním textovém editoru.

Původní API připnutých náhledů nadále vrací bajty z požadovaného commitu.
Pracovní soubor se neposkytuje síťovým klientům a nevstupuje do kontextových
manifestů, synchronizace ani autoritativního indexu. Chybějící, měnící se,
nečitelný nebo nepřípustný soubor vyvolá explicitní zprávu, nikoli tichou
záměnu za údajně aktuální uloženou verzi.

Pokud existuje rozpracovaná kopie, nad Plánem jsou přepínače **Uložený graf**
a **Rozepsaný soubor**. První vrací graf poslední uložené platné revize,
druhý náhled právě přepisovaného souboru. Volba zůstává zachovaná při dalším
otevření Plánu v témže projektu. Přepnutí nic neukládá ani nemaže; pokud
uložená revize nemá platný graf, odpovídající tlačítko je zakázané s důvodem.

## Režimy editoru a pracovní plocha

Editor hlavního plánu nabízí v záhlaví **Kostky**, **Raw text** a **Náhled**.
Náhled vykresluje aktuální obsah textového pole, včetně dosud neuložených
změn. Přepnutí nic neukládá a zachovává rozepsaný obsah i výběr v raw textu.
Pohled Plán při otevření projektu standardně zobrazuje uložený graf;
rozpracovaný soubor lze prohlížet v editoru nebo zvolit jeho samostatný náhled.

Obsah editoru využívá zbývající výšku a celou dostupnou šířku stránky.
Posouvá se text nebo náhled, nikoli záhlaví s akcemi. Pomocné vzory,
ověření a kontextová nápověda jsou v rozbalovací části **Nástroje a nápověda**.
Vlastnosti dokumentu zůstávají samostatně rozbalovací; pro náhled externě
rozepsaného souboru a editor jedné položky se prázdné vlastnosti nezobrazují.
Toto rozložení používá společnou hlavičku a tělo stránky jako ostatní editory.
