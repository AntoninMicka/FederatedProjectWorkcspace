<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0064 — Blokové úpravy Markdownu

Datum: 2026-11-01. Rozhodnutí: přijato pro AI-FILE-EDIT-01 podle výslovného
zadání uživatele. Doručení a lidská akceptace jsou samostatné.

## Potřeba a rozhodnutí

Generování celého dokumentu ani kopírování textových kotev neposkytlo
spolehlivé výsledky nad rozsáhlou roadmapou. To není důkaz obecné neschopnosti
lokálních modelů. Python nyní připravuje rozsahy původního Markdownu, ID bloků
a SHA-256. Ollama dostane explicitní projekci v Context Manifestu a vrátí
`markdown-patch`. Nové běhy používají `task-output-markdown-patch-v2`;
původní role v1 a její výstupní schéma zůstávají kvůli připnutým běhům.

`spikes/markdown_patch.py` je omezený scanner, nikoli úplný CommonMark/GFM
parser. Rozlišuje ATX/setext nadpisy, sekce, odstavce, položky seznamů,
mezery, komentáře a uzavřené backtick/tilde fences s odsazením do tří mezer.
Neznámá syntaxe zůstává textem. Původní dokument se neserializuje přes AST;
nedotčené úseky se kopírují beze změny včetně CRLF, Unicode a koncových mezer.
Neuzavřené rozpoznané fences vyžadují nejprve ruční opravu.

ID `b00001` apod. platí jen pro snapshot vymezený `document_hash` a nezapisují
se do souboru. Každá operace kontroluje hash svého bloku, přesun i hash
cílového nadpisu. Sekce používají stejný hash nadpisového bloku: hash celého
dokumentu již připíná jejich potomky. Nepředává se dvojí očekávaný hash pro
jeden blok, který model při prvním ověření zaměňoval.

Revize v2 reaguje na skutečný odmítnutý návrh: model vytvořil ID b02509 až
b02512 v dokumentu s 2508 původními bloky. Nové ID nejsou platné adresy
vložení. JSON schéma nyní omezuje `block_id` a případné `destination_id`
výčtem povolených existujících ID z jediné připnuté projekce; `document_hash`
je také výčet s jednou hodnotou. Vložený text se předává v `content` operace
nad původním blokem. Neexistující blok a existující blok mimo rozsah mají
odlišné české hlášky. Aplikátor stále provádí vlastní kontrolu; schéma
nenahrazuje autorizaci, hash ani sémantickou validaci. Ani platná ID
nezaručují věcně správné zadání, správné místo či platnou syntaxi roadmapy.
Původní výstup se neopravuje, povolený rozsah se nerozšiřuje a nedochází
k automatickému opakování modelu. Recovery hranice se nemění.

Podporované operace jsou `replace`, `delete`, `insert_before`, `insert_after`,
`replace_section`, `append_section`, `move_section`, `rename_heading`.
Sekce končí před dalším nadpisem stejné či vyšší úrovně. Přesun kopíruje
původní text za cílovou sekci stejné úrovně; neumožňuje přesun do sebe,
potomků ani spojení sekcí bez potřebného konce řádku. Přejmenování zachovává
styl nadpisu. Náhrada sekce zachovává její nadpisovou úroveň; připojení
nevytváří sourozenecký nadpis mimo zvolenou sekci.

Operace míří do stejného původního snapshotu. Překryvy, nejednoznačné
vložení, neznámá pole/ID, chybný hash, zásah mimo rozsah a návrh beze změny
se odmítají jako celek. Není fuzzy matching, shell, `git apply`, ruční
automatická oprava výstupu ani opakování modelu. Limity: tělo 1 MiB,
8192 bloků, 64 operací a 64 KiB JSON návrhu.

## Revize v3: kompaktní odpověď bez hashů (2026-11-01)

Měření nad roadmapou v repozitáři (148 KiB, 1227 bloků) ukázalo, že JSON
projekce v1 měla 361 KiB, z toho přes 87 000 znaků SHA-256 hashů, a výstupní
schéma 111 KiB. Doložený běh se 131074 vstupními tokeny tak pravděpodobně
narazil na kontext 128k; Ollama delší prompt bez `num_ctx` tiše ořízne.
Hash bloku je navíc redundantní: aplikátor nejprve ověřuje `document_hash`
celého snapshotu, takže ID už jednoznačně určuje původní bajty.

Nové běhy proto používají roli `task-output-markdown-patch-v3` a projekci
`fpw-markdown-block-context-v2`:

- projekce neobsahuje hash bloků ani bloky tvořené jen prázdnými řádky;
  prompt ji zobrazuje jako prostý Markdown s řádky `<<b00012 kind>>`,
  nikoli jako escapovaný JSON (cca 1,1× velikosti dokumentu místo 2,4×);
- model vrací jen `{"kind","changes":[{block_id,action,destination_id,content}]}`;
  schéma má jeden tvar operace, jeden výčet ID a cílové ID omezené na nadpisy;
- `complete()` doplní hash dokumentu i bloků z připnutého snapshotu, titul a
  `null` pole podle akce a výsledek projde nezměněnou validací v1 (`validate_proposal`,
  `apply`). TaskOutcomes ukládá tento úplný tvar, preview i recovery se nemění;
- `complete()` doplní chybějící koncový newline ve stylu dokumentu a prázdný
  řádek mezi vkládaným a sousedním odstavcem, jinak by Markdown text tiše
  spojil (např. `- [ ] new- [ ] two`). Jiné úpravy obsahu neprovádí;
- požadavek nastavuje explicitní `num_ctx` (konzervativní odhad 2,5 B/token
  + výstupní rozpočet, zaokrouhleno na 2048) a `think:false`, aby tokeny
  přemýšlení nespotřebovaly výstupní rozpočet. Odhad nad 128k se odmítne před
  dispatch. Pokud `prompt_eval_count` po běhu ukazuje na zaplněný kontext,
  návrh se odmítne jako pravděpodobně oříznutý, bez dalšího modelového požadavku;
- u rozsahu „vložení pod milník“ projekce přidá read-only strukturu nejvýše
  čtyř prvních potomků (řádky s checkboxem a `type:`), aby model viděl formát
  dávky/úkolu. Popisy úkolů ani obsah mimo vybranou položku se neposílají.

Scanner už nepovažuje položku seznamu následovanou `---` za setext nadpis.
Projekce v1, role v1/v2 a jejich výstupní schémata zůstávají bajtově stejné
pro připnuté běhy a uložené návrhy; ověřeno porovnáním s předchozí revizí.
Recovery hranice se nemění: projekce i doplnění odpovědi probíhají v paměti.

## Rozsah, oprávnění a review

Narrow scope tvořený sousedící dvojicí řádku uzlu a jeho `type: milestone`
nebo `type: batch` reprezentuje UI akci vložení potomků. Model nemůže
upravovat rodiče: schéma dovolí jediný `insert_after` na poslední metadata
rodiče. Pokud za typem následují další rodičovská metadata, aplikace do
projekce zahrne poslední takový blok jako přesný cíl. Původní dvojice
zůstává v uloženém výběru; payload hash připíná i tento odvozený cíl.
`complete` i validace uloženého návrhu kontrolují stejný insertion kontrakt.
Nejde o volné rozšíření modelových oprávnění: rodičovská data zůstávají
read-only, ostatní akce a více operací se odmítají. První existující
potomek uzavírá rozsah metadat i v případě pokračujícího popisu na dalším
řádku. Code fences se nepovažují za definice ID.

Kontext obsahuje přesný vzor odsazení a typů pro novou dávku/úkol a krátký
nekolidující prefix ID odvozený z původního dokumentu. Převzetí starého ID
jako nové definice se výslovně odmítne; aplikace ID modelu nepřejmenovává.
Přijetí dál vyžaduje validaci celého grafu, diff a souhlas. Starší hashed
kontext v1 se tímto insertion kontraktem nemění. Nový writer ani recovery
hranice nevznikají.

ExplicitTaskPlan přidává `edit_format:blocks` a volitelné `edit_block_ids`.
Nadpis zahrne potomky; jiný vybraný blok pouze vlastní text. Bez výběru se
předá celý dokument jako bloky. UI nabízí kapitolu a u podporované roadmapy
dvojici bloků pro vložení pod milník. Výběr určuje aplikace, nikoli model.
Celodokumentový režim znamená jeden požadavek, nikoli automatické dělení do
více průchodů. Autonomní agent vybírající sekce se nezavádí.

UI u velkého dokumentu (stejná hranice 32 KiB / 500 řádků jako textové
patche) nemá implicitně vybraný celý soubor. Vyžaduje výběr kapitoly,
insertion scope pod milníkem nebo výslovnou volbu celého dokumentu.
Důvodem je doložený běh se 131074 vstupními tokeny, který začal kopírovat
celou kapitolu a vyčerpal výstupní limit. Jde o ochranu před nechtěně velkým
kontextem, nikoli automatický výběr sekce, zákaz globálních úprav či novou
autorizační/recovery hranici. Rozpočet modelu a jeho aplikátor zůstávají stejné.

Manifest zachovává SHA-256, velikost a privacy skutečného projektového vstupu.
Projekce doplňuje rozsah, hash těla a hash/velikost odeslané reprezentace.
Dispatch ji znovu sestaví a ověří. Oprávnění a privacy se kontrolují před
voláním modelu. Návrh uchová metadata projekce; náhled operace znovu ověří
nad připnutou verzí a validuje celý task graph včetně ID, hierarchie a vztahů.

Zachování ostatního textu nezaručuje zachování faktů uvnitř nahrazovaného
bloku. Platný návrh může být věcně chybný. Uživatel vidí sestavený výsledek
a unified diff a může jej přijmout, odmítnout nebo ručně upravit ve společném
editoru. Ruční editace nejsou vydávány za modelové zásahy omezené na bloky.

## Crash boundaries a recovery

Platí [ADR 0003](0003-coordinated-operation.md) a existující
[AI editace](../ai-file-edit.md#crash-boundaries-a-obnova). Scanner, projekce
i aplikátor sestavují návrh pouze v paměti. Neplatná odpověď nezaloží návrh
ani zápis; dokončený providerový přenos se nezmění na neznámý. Stream
rozlišuje `markdown-patch-invalid` / `invalid-proposal` od chyby přenosu.
Původní běh se neopakuje.

TaskOutcomes před native operací trvale připne schválené tělo, digest a
operation ID. Před touto hranicí je při pádu nutné nové potvrzení; po ní
obnova používá stejné tělo a ID. Workspace journal přebírá soubory, Git a
index podle ADR 0003. Pád po commitu před dokončením TaskOutcomes obnoví
receipt bez druhého commitu, aplikace patche nebo modelového požadavku.
Nevzniká nová persistentní vrstva ani druhý writer. Novější HEAD se odmítá.

## Reuse a ověření

Adaptují se ContextBuilder, Ollama Structured Outputs, AITaskOutcome,
TaskOutcomes, společný editor, diff a Artifacts.save/Workspace.transact.
Starší `artifact-patch` a `artifact-draft` zůstávají čitelné. Nová je pouze
vrstva strukturálního adresování a čistých operací; obecný AST serializer,
nový writer a kopie externího frameworku byly odmítnuty. Soukromá reuse
inventura nedává důvod nahrazovat existující zápisovou cestu.

`tests.test_markdown_patch` ověřuje CRLF/Unicode, opakovaný obsah, code fences,
nadpisy, sekce, přesuny, rozsah, hash, překryvy, neplatný návrh, náhled,
potvrzení, zrušení a ztracenou odpověď po native commitu. Procesní pády
sdíleného writeru pokrývají existující `tests.test_task_file_edit`. Qt smoke
ověřuje čitelné operace, více průběžných změn, výběr rozsahu a odmítnutí jeho
nedostupnosti bez tichého přechodu na celý dokument. Skutečné LLM pokusy a
omezení uvádí [kontrakt](../ai-file-edit.md#blokový-markdown-patch-engine).
