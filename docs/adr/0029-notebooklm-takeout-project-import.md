<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0029 — Import osobního NotebookLM projektu z Google Takeout

Datum: 2026-10-08. Stav: přijato; parser, seeded vytvoření a desktop/web tok jsou
implementované. Izolovaný import největšího skutečného notebooku prošel;
uživatelské vytvoření trvalého projektu přes UI zůstává otevřenou akceptací.

## Kontext a ověřený vstup

Uživatel používá osobní Gemini Notebook/NotebookLM s Google AI plánem přes
Google One, nikoli Google Cloud Enterprise. V1 proto nepoužije Enterprise
Preview API, přihlašovací cookies ani neoficiální interní endpointy. Vstupem je
uživatelem stažený Google Takeout `.tgz`, který zůstává mimo projektový Git.

Vzorek `takeout-20261008T030103Z-1-001.tgz` byl přečten pouze lokálně a jeho
obsah se nezapisuje do verzované dokumentace. SHA-256 archivu je
`96c729dbcb2ebda169ec3e7e3f772df1adfa6c2782eb754e22b67d1845c97f25`.
Archiv má 243 běžných souborů, žádné symlinky, hardlinky, zařízení, traversal
ani duplicitní cesty a deklaruje 31 237 914 rozbalených bajtů. Obsahuje šest
notebooků pod `Takeout/NotebookLM/`; jeden reprezentativní notebook má 63
zdrojů, tři hotové tailored-report artefakty a jednu chatovou relaci.

Takeout v tomto vzorku ukládá notebook metadata, source metadata a obsahové
reprezentace, artefakt metadata + Markdown, chat jako jednoduché HTML a u
jednoho notebooku Discovered Sources JSON. Source typy zahrnují Drive, URL,
Google Doc, Gemini chat, PDF, image a Markdown. Všechny párované source obsahy
jsou exportní `.html` reprezentace; několik dalších obsahových záznamů je JSON.
Nejde o původní bajty PDF, obrázku či Google dokumentu a importér je za ně nesmí
vydávat.

Notebook metadata neobsahují stabilní notebook ID a source metadata neobsahují
source ID. Artefakt metadata sice nesou source UUID, ale export neposkytuje
doložené mapování těchto UUID na exportované source soubory. V1 proto uchová
opaque reference v importním manifestu, ale nevytvoří neověřené projektové
vztahy. Poznámky nejsou ve vzorku samostatnou kategorií; jejich absenci musí
preview uvést, nikoli interpretovat jako důkaz, že v notebooku nikdy nebyly.

## Rozhodnutí a mapování

- Jeden uživatelem vybraný Takeout notebook vytvoří jeden nový Workspace
  projekt. Opakovaným výběrem lze importovat další notebooky ze stejného
  archivu; v1 nevytváří všech šest projektů bez samostatného preview a
  potvrzení každého cíle.
- Každá source exportní reprezentace se uloží v přesných přijatých bajtech jako
  neměnný external source artefakt. Název a source typ pochází z doprovodných
  metadat; přípona a popis musí výslovně uvést, že jde o Takeout HTML/JSON
  reprezentaci, ne původní binární podklad.
- Notebook metadata a všechny doprovodné source/artifact metadata se zachovají
  beze změny v jednom bounded importním manifestu spolu s původními cestami,
  SHA-256 každého členu, bundle SHA-256, verzí importéru a mapováním na lokální
  artifact UUID. Manifest nesmí obsahovat soubory z jiných Google služeb ani
  jiného notebooku.
- Studio artefakty se importují v přesných Markdown bajtech jako oddělené
  neměnné external source artefakty s kategorií `notebooklm-artifact`. Chat se
  zachová jako přesné nedůvěryhodné HTML a navíc může mít bezpečně odvozenou
  textovou projekci pouze tehdy, pokud parser doloží explicitní `USER:` /
  `MODEL:` hranice; původní HTML zůstává autoritou přijatého obsahu.
- Discovered Sources se zachovají jako oddělený external JSON source.
  Nepodporované a neznámé kategorie se zobrazí v preview a blokují tvrzení o
  úplnosti; nesmějí být potichu zahozeny.
- Import report je odvozený neměnný snapshot s počty importovaných,
  nepodporovaných a chybějících částí, limity exportu a vazbou na manifest.
  Neznámý prompt, model, autor, čas, citace ani providerová identita se
  nedoplňují.

## Identity, duplicity a provenance

Preview vygeneruje stabilní project/artifact UUID pro jednu potvrzovanou
operaci a kanonický selection digest nad bundle hashem, přesným notebook path,
všemi vybranými member path/hash/size, parser revision, privacy a cílovou
cestou. Approval a retry se vážou na tento digest.

Stejný operation ID a selection digest musí vrátit tentýž projekt UUID, commit
a receipt. Nová operace se shodným notebook member manifestem se označí jako
exact duplicate a nabídne existující import. Protože Takeout neposkytuje
stabilní notebook/source ID, změněný nebo přejmenovaný export nelze automaticky
prohlásit za novou verzi téhož notebooku. Vyžaduje explicitní uživatelský výběr
existujícího importu nebo vytvoření nového projektu; shoda názvu sama nestačí.

Importní provenance v2 používá `importer.name = notebooklm-takeout-import` a
verzi kontraktu. `source_created_at` se použije jen pro doložený
`sourceAddedTimestamp`; filesystem mtime ani Takeout čas stažení jej
nenahrazují.
`source_revision` nese hash příslušného původního metadata záznamu, nikoli
vymyšlené providerové ID. Bundle/member hashe a NotebookLM-specifická metadata
drží manifest.

## Bezpečnost a preview

TGZ se nejprve pouze čte a hashuje. Parser má limity na velikost vstupu,
deklarovanou rozbalenou velikost, počet členů, velikost jednoho členu, hloubku a
délku cest. Odmítne absolutní cesty, `..`, backslash/control znaky, Unicode nebo
case-fold kolize, symlinky, hardlinky, zařízení a jiné typy, nested archivy a
změnu vstupního inode/size/mtime během čtení. HTML se nikdy nevykonává; v
projektu se zobrazuje pouze jako bounded bezpečně odvozená Markdown projekce.
Importované značky se nepředávají rendereru; skripty, styly, vložené
rámce, SVG, templates a obsah hlavičky se vynechají. JSON náhled zachová všechna
pole a hodnoty a platný dokument pouze přeformátuje do Markdown code blocku.
Markdown renderer vytváří vlastní DOM uzly s `textContent`; původní HTML i JSON
bajty zůstávají autoritativním obsahem artefaktu.

Preview ukáže přesný notebook, kategorie, počty, source typy, velikosti,
nepodporované části, chybějící notes a omezení vztahů. Projektový Git, node
registry ani index se před samostatným potvrzením nemění.

## Persistentní vrstvy a recovery

Adaptuje se `ProjectCreation`: potvrzená operace předá úplný validovaný počáteční
artifact snapshot se stabilními UUID. Přesné seed bajty se před potvrzením
durable záměru zkopírují do vlastněného node-local stagingu a svážou hashi;
recovery nikdy znovu nečte změněný Takeout archiv.

Existující creation journal zůstane jedinou autoritou vytvoření projektu.
Počáteční projektový commit obsahuje `project.json` i celý importní snapshot a
vznikne ještě v nepublikovaném staging rootu. Pád před `root-published`
nezviditelní částečný projekt. Po publikaci rootu recovery ověří stejný commit,
dokončí state/index/node registry a vrátí tentýž receipt. Cizí cílová cesta,
změněný seed manifest nebo registrace fail-closed. Samostatná série pozdějších
importních commitů ani druhý journal/Git writer se nezavádějí.

## Reuse a odmítnuté varianty

Reuse/adapt: `ProjectCreation`, `Workspace`/Journal/Index, `validate_snapshot`,
metadata/provenance v2, source immutability, bezpečný artifact preview a
desktop/web RBAC. Soukromá inventura neposkytla komponentu, která by tyto
autority nahradila bez ztráty Git/recovery kontraktu.

Odmítnuto: Enterprise API pro osobní účet, browser scraping, session cookies,
automatické stažení původních URL, vykreslení importovaného HTML ve WebEngine,
spojování podle názvu, domyšlené artifact→source vztahy, obecný ETL framework,
nová databáze a import všech notebooků bez jednotlivého preview/potvrzení.

## Ověření a otevřené hranice

Syntetické testy pokrývají platný formát, traversal, linky, case-fold kolize,
nested archiv, malformed metadata, orphan obsah, aktivní skript v chatu a změnu
archivu nebo selection digestu. Seeded import byl přerušen na každé durable
hranici a recovery vždy skončilo jedním projektem a jedním commitem. Opt-in
test nad soukromým TGZ importoval největší notebook (22 895 488 deklarovaných
bajtů) do izolovaného uzlu, znovu jej otevřel a ověřil idempotentní receipt.
Zbývá uživatelsky zvolit notebook a trvalou cílovou cestu přes skutečné UI a
potvrdit běžné použití importovaných podkladů po restartu aplikace.

Google může Takeout formát změnit bez verzovaného veřejného schématu. Parser je
proto fail-closed pro neznámý tvar a jeho revision je součástí manifestu.
Úplnost je omezena na exportované reprezentace: původní binární zdroje,
samostatné notes, úplné providerové identity a spolehlivě rozřešené citace ve
vzorku doloženy nejsou.
