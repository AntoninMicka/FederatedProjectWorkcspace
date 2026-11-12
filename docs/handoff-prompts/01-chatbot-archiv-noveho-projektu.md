<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Instrukce pro chatbota: archiv projektu pro předání do Workspace

Následující zadání vlož chatbotovi, u kterého vznikaly podklady projektu.
Text je nezávislý na poskytovateli. Údaje v hranatých závorkách nahraď.

## Zadání k použití

Připrav přenositelný archiv projektu **[NÁZEV PROJEKTU]** pro založení
nového projektu ve Federated Project Workspace. Použij dostupnou konverzaci,
poskytnuté dokumenty, soubory a moje výslovně potvrzená rozhodnutí.

Chci skutečné soubory, ideálně v jediném ZIP archivu. Samotný souhrn v chatu
nestačí. Pokud soubory nebo ZIP neumíš vytvořit, přiznej to a odevzdej přesné
obsahy souborů s názvy, abych je mohl uložit. Nevytvářej nefunkční odkazy.

### Co zachovat a co nevymýšlet

1. Zachovej všechny dostupné podstatné požadavky, rozhodnutí, důvody,
   alternativy, omezení, otevřené otázky, neúspěšné pokusy a další práci.
2. Rozlišuj moje zadání, tvůj návrh, schválené rozhodnutí, implementovaný
   výsledek a skutečně ověřené chování. Návrh chatbota není schválené rozhodnutí.
3. Stav „hotovo“ převezmi pouze s dostupným důkazem a kontextem akceptace.
   Rozlišuj designed, implemented, PoC validated a production-ready.
4. Originální poskytnuté soubory zachovej beze změny bajtů. Jejich překlady,
   extrakty a souhrny ukládej zvlášť a označ je jako odvozené.
5. Konverzaci exportuj v dostupném pořadí s rolemi účastníků. Známé časy
   zachovej včetně časové zóny; neznámé nevymýšlej. Souhrn není úplný přepis.
6. Pokud starší část chatu, přílohy nebo plný export nemáš k dispozici,
   vypiš přesně, co chybí. Netvrď, že jsi obnovil nedostupný obsah z paměti.
7. Existující ID, názvy a vazby zachovej. Kolize nebo rozpory vypiš k review;
   nepřejmenovávej je potichu a nevybírej bez upozornění jednu verzi.
8. Zdroje opatři dostupným původem: název, autor, URL, datum či revize.
   Odkaz bez staženého souboru označ jako odkaz, ne jako přiložený obsah.
9. Nezabaluj hesla, API klíče, cookies, soukromé klíče ani lokální credentials.
   Nalezenou citlivou přílohu označ k oddělenému soukromému předání; neupravuj
   její originál potichu. Redigovanou kopii jednoznačně odliš od originálu.

### Struktura předávaného archivu

Použij UTF-8 Markdown, běžné soubory a relativní odkazy. Doporučená struktura:

```text
projekt-slug/
  00-PROJEKT.md
  01-KONTEXT.md
  02-ROZHODNUTI.md
  ROADMAPA-WORKSPACE.md
  04-OTAZKY-A-RIZIKA.md
  05-PREHLED-SOUBORU.md
  konverzace/
    001-prepis.md
  originaly/
    ...dostupne-puvodni-soubory...
  odvozene/
    ...volitelne-extrakty-a-souhrny...
```

- `00-PROJEKT.md`: název, cíl, komu projekt slouží, očekávaný výstup,
  rozsah a jeho hranice, jazyk, doporučené soukromí, stav a pokyny k převzetí.
- `01-KONTEXT.md`: potřebné souvislosti, používané pojmy, současné řešení,
  relevantní prostředí a odkazy na skutečné podklady.
- `02-ROZHODNUTI.md`: stabilní ID rozhodnutí, jejich obsah, důvod, alternativy,
  známé potvrzení a případné nahrazení novým rozhodnutím. Návrhy odděl.
- `ROADMAPA-WORKSPACE.md`: jeden kandidátní plán se stabilními ID. Pokud je zadána
  konverze roadmapy, použij její samostatné instrukce. Nevytvářej duplicitní
  živé TODO v několika souborech.
- `04-OTAZKY-A-RIZIKA.md`: nezodpovězené otázky, předpoklady, rizika, rozpory,
  nedostupné podklady a to, co musí při převzetí potvrdit člověk.
- `05-PREHLED-SOUBORU.md`: relativní cesta každého souboru, jeho účel,
  originál/odvozený obsah, původ, dostupnost a doporučené soukromí.
  SHA-256 přidej pouze tehdy, když ho skutečně spočítáš z finálních bajtů.
  Soupis nehashuj sám do sebe; jeho hash může být uveden vedle archivu.

Archiv nesmí obsahovat absolutní cesty, `../`, symlinky, `.git`, node.json,
lokální databáze, journaly nebo předstírané interní Workspace konfigurace.
Nepřidávej prázdné placeholdery místo nedostupných originálů. Delší přepis
rozděl na očíslované části se soupisem; nezkracuj ho bez upozornění.

### Co skutečně podporuje současný Workspace

Tento ZIP je **předávací archiv**, nikoli deklarovaný nativní formát projektu.
Nevydávej ho za NotebookLM Takeout ani nevyráběj jeho falešnou strukturu.
Současný obecný import podkladů přijímá jednotlivé Markdown, PNG, JPEG a PDF
soubory do 16 MiB. UTF-8 Markdown se importuje bez překódování. JSON/HTML,
zdrojový kód a jiné originály mohou být součástí archivu, ale tento picker
je přímo nepřijímá; přidej samostatný Markdown přehled a originály zachovej.
Počítej také s limitem 64 MiB celého nativního snapshotu včetně metadat.
Pokud ho podklady překračují, navrhni výběr nebo rozdělení projektů k review;
nevypouštěj kvůli tomu obsah archivu a neslibuj úplný import bez ověření.

Do `00-PROJEKT.md` vlož tento postup převzetí:

1. Archiv bezpečně rozbalit a porovnat soupis, dostupnost a případné hashe.
2. Ve Workspace založit nový projekt z ověřeného názvu a cíle. Workspace
   vytvoří vlastní UUID a interní metadata; chatbot je nepředstírá.
3. V novém projektu přes **Podklady → Importovat zdroj** přijmout podporované
   soubory s vědomě zvoleným soukromím. Importované originály jsou neměnné.
4. Roadmapu nejprve převzít jako podklad. Po review ji vložit do hlavního
   editovatelného plánu projektu. Samotný import Markdown podkladu nevytvoří
   automaticky úkoly a relativní odkazy z archivu nedostanou automaticky
   interní artefaktové cesty.
5. Prověřit převod všech ID, vztahů a odkazů. Teprve po potvrzení určit hlavní
   plán ve Workspace jako autoritu; původní soubory uchovat jako zdrojové snapshoty.
6. Import nic automaticky neakceptuje, neaktivuje worker ani LLM a neuděluje
   oprávnění k přenosu citlivých dat. Local-only obsah předávat pouze lokálně.

### Výstup chatbota

Odevzdej archiv nebo jednotlivé skutečné soubory, krátký soupis obsahu a
výslovný seznam chybějících částí. Nakonec uveď, co je připravené k importu
podkladů a co ještě vyžaduje převod nebo lidské review. Neoznamuj „projekt
importován“, pokud jsi neprovedl skutečný import a nemáš jeho výsledek.

## Ověřené podklady tohoto návodu

Kontrakt k 12. 11. 2026: [import zdrojů](../native-source-import.md),
[plán projektu](../task-planning.md) a
[samostatný NotebookLM import](../notebooklm-import-acceptance.md).
Při jiné verzi aplikace ověř její aktuální importní možnosti.
