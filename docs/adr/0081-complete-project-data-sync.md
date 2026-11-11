<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0081 — Úplnost a sémantická validace projektového přenosu

Datum: 2026-11-07. Stav: implementováno k review, izolovaný PoC;
fyzická Omnia ↔ desktop akceptace tohoto rozšíření není doložená.

Zadání `F-M5-FULL-DATA-SYNC-01`: kanonický projekt
`c898b941-8eb0-4406-8dad-6e2b96c06d59`, exportní revize
`c783f008285f133bcee381d4ecc46fe556d39c4d6b4479c6da1841ccb9210ad1`,
projektový commit `2dbfdf01197563190fdb8f3ba1efd8a411cb023a`.
Samostatná větev `feature/full-data-sync` vznikla z ověřeného develop
`85d264fe75f8a3fc9dd69521ba8839e9a76eac6d`; není stacked na MON-08.
Dokument je rozhodnutí a evidence řezu, nikoli další živý plán.

## Potřeba a reuse

[ADR 0042](0042-bidirectional-native-git-sharing-sync.md) již přenáší celé
povolené větve a historii nativním Git bundle a zachovává divergenci.
Metadata validátor ověřuje typy, ID, vztahy, privacy a neměnné revize.
Chyběla sémantická kontrola reportingových pinů na síťové hranici. Lokálně
dostupný pin navíc nemusí být dosažitelný z přenášených povolených větví.

**Reuse/adapt:** původní policy, `validate_history`, reportingové
`validate_git`, Ed25519/HTTPS, sync journal, Workspace CAS/Index recovery
a explicitní `ConflictResolution`. **Reject:** druhý transport/writer/index,
automatické doplnění skrytých větví, provider fallback a přepsání konfliktu.

## Rozhodnutí

1. Každý dosažitelný commit validovaného přenosu projde také původním
   reportingovým `validate_git`: přesné commit/path/hash piny, projektové
   identity, privacy vztahů, podklady reportu, capture metadata a publikace.
2. Validátor přijímá explicitní přesný `head`; historický commit se posuzuje
   ve svém kontextu. Běžný zápis nadále implicitně používá HEAD. Bare
   validační repo nepotřebuje checkout ani předem existující HEAD.
3. Odesílatel ověří hotový bundle v izolovaném bare repozitáři s výhradně
   skutečně přenášenými refy/objekty. Hidden ref ani unreachable object
   v lokálním Gitu nesmí maskovat chybějící podklad. Neúplný scope se odmítne;
   další větev vyžaduje původní samostatné posouzení policy.
4. Příjemce používá stejnou kontrolu po ověření podepsaného digestu a před
   publikací refů nebo registrací projektu. Podpis nenahrazuje validaci.
5. Přenášejí se původní projektové bajty a historie, nikoli souhrny či jen
   seznam pinů. Zpracování dál ověřuje skutečně dostupné přesné vstupy.
6. Credentials, provozní journaly a lokální aktivace kolektorů nejsou
   projektový bundle. Přenos WatchDefinition není execute grant.

Licence a retence zůstávají původními posouzenými politikami a připnutými
podklady; capture bez doloženého souhlasu ani chybný pin neprojdou. Řez
neinterpretuje právní význam volné prózy ani nevytváří exportní souhlas ze
staženého obsahu. Skutečný export vyžaduje povolený projekt/branch scope
a vypořádané podmínky zdroje. PoC používá syntetické povolené podklady.

## Konflikty a recovery

Divergence zachová oba heady pod incoming refs. Explicitní conflict review
může spojit nezávislé reportingové přírůstky nativním merge se dvěma rodiči.
Textově čistá unie dvou základních zpráv za stejné období neprojde doménovým
validátorem. Takový konflikt zůstává k doménovému rozhodnutí; jedna publikace
se nesmaže automaticky a historie obou větví zůstává zachovaná.

Platí crash hranice ADR 0042; nový persistentní formát ani journal nevzniká:

- Exportní validace je před durable outbound requestem a síťovým přenosem.
  Dočasný bare repo/bundle lze po pádu zahodit; není autoritou.
- Neplatný příjem se odmítá před durable inbound intentem a publikací.
- Po durable přijetí zůstává stejný operation ID a payload, CAS ref,
  checkout/index roll-forward a uložená přesná odpověď. Pád po ref update
  nedovoluje nový přenos s jiným obsahem pod stejným ID.
- Není atomická transakce přes oba uzly. Chatový payload zachovává stejnou
  koordinaci a lokální journal podle ADR 0056.

## Hranice a integrace

Zůstávají limity 500 dosažitelných commitů na head, 64 MiB bundle a původní
limity snapshotů. Úplnost se týká povoleného scope v těchto mezích.
Nepodporované schéma se odmítne; transport nevymýšlí jeho interpretaci.

MON-08 vyvíjí WatchDefinition/SourceFinding samostatně; develop je dosud
nemá. Kompatibilita je testovaná v dočasném složeném checkoutu: monitoring
schéma plus přesný transportní patch. Není to merge, nasazení ani akceptace
MON-08. Po začlenění obou větví se podmíněný test zapojí do běžné sady.

Ověření: [full-data-sync](../full-data-sync.md).

## 10. 11. 2026 — dokončený replay bez opakovaného průchodu historií

Lokální oprava dostupnosti navazuje na oddělení HTTP domén v ADR 0050.
Příjem nadále vlastní společný receive zámek z
[auditu HTTP](../http-concurrency-ownership.md). Nemění se protokol ani schéma
journalu; nová nebo nedokončená operace dál projde celou validací historie
před publikací. Neplatný nový vstup nevytvoří durable inbound intent.

Po ověření aktuální identity peeru, úrovně sdílení a podpisu lze nejprve
vyhledat původní operation ID v inbound journalu. Dokončený záznam lze použít
jen při shodě digestu, celé kanonické obálky a všech payload bajtů. Pouhá
existence ID nebo nedokončeného intentu nestačí. Historická sémantika těchto
přesných bajtů už byla ověřena před jejich původní publikací; dokončený replay
proto neopakuje import bundle do validačního repozitáře ani průchod historií.

Znovu se však kontrolují velikosti a podepsané digesty payload částí, privacy
a aktivní mapování příchozích chatů a validita poolů. U uložené odpovědi se
ověří původní lokální podpis/identita, vazba na operaci a oba uzly, aktuální
projektový/branch scope, dostupnost registrovaného projektu a oprávnění
příjemců odchozích chatů. Projektová kontrola připojí jen Git handle, nikoli
Workspace journal/index. Registr autority
musí být od první kontroly příchozího podpisu do závěrečné kontroly stejný.
Chybějící lokální identita se pro replay nevytváří znovu. Neplatné aktuální
oprávnění nebo poškozená odpověď znamená odmítnutí, ne přegenerování odpovědi
pod stejným ID.
Diagnostika rozlišuje fázi `receive-replay` od `receive-verify-history`.

Crash hranice se nemění: před uložením odpovědi se obnovuje původní intent
s úplnou validací; po uložení se mohou vrátit jen původní autorizované bajty.
Odmítnutý replay původní intent/odpověď nemaže a nepublikuje Git, chat ani
pool. Mezi journalovým lookupem a kontrolou oprávnění se nedrží SQLite
transakce. Po ztrátě HTTP odpovědi je stále nutné použít stejné operation ID
a stejné bajty; nevzniká automatický retry ani nový writer.

### Jedno ověření příchozí Git historie v rámci operace

Měření čekajícího balíku v izolovaném lokálním Gitu ukázalo 93 commitů a
6,56 s pro jeden průchod. Příjem po první úplné validaci opakoval stejný
průchod v `_apply`, ještě před tvorbou odpovědi. Toto druhé ověření totožného
Git grafu v témže volání se odstraňuje; nejde o cache mezi operacemi.

Samostatný vstup `_apply` nadále ověřuje celý přenos a teprve
potom volá privátní publikační část. Receiver může tuto část použít přímo
pouze po vlastní úplné validaci stejných neměnných payload bajtů a uložení
intentu, stále pod receive zámkem. Publikační část znovu kontroluje digesty,
pooly a živá chatová oprávnění; vlastní zápisové/CAS kontroly se nemění.
Nedokončená operace po pádu při novém volání opět projde úplnou validací.
Žádná validační autorita se nepřenáší do dalšího requestu nebo procesu.

Stejnou validovanou Git část lze v rámci této operace vrátit původnímu
odesílateli jako odpověď. Receiver zachytí neměnný kontext s operation ID,
projektem, oběma uzly, fingerprintem peeru, scope, úplnou sadou ref/head a
přesnými ověřenými Git bajty. Pod projektovým writer zámkem musí výstupní
inventura přesně odpovídat tomuto kontextu a aktuální policy. Pak lze vrátit
tentýž už ověřený objektový graf bez dalších dvou průchodů při exportu.
Jakýkoli jiný head, další lokální větev, jiný scope, peer nebo operation ID
ponechá původní úplnou exportní validaci. Chaty a pooly se stále sestavují
ze současného stavu s původními kontrolami. Kontext není persistentní cache,
nezapisuje se do journalu a nezavádí nový protokolový parametr.

## Doplnění 2026-11-10 — vynechání nepotřebného exportu

Při shodě celého aktuálního scope inventáře větví s inventářem, který peer
již zná, se Git bundle v protokolu neposílá. Dříve se přesto nejprve vytvořil
a dvakrát sémanticky ověřil, aby jej volající následně zahodil. Kontrola přesné
shody se proto přesouvá do přípravy pod původní project writer lock, až po
ověření aktuálního projektu, indexu a čistoty worktree, ale před export historie.
Odesílatel používá pouze naposledy potvrzené `last_sent.refs`; příjemce porovnává
aktuální inventář s podepsaným `known_remote_refs` požadavku.

Změněný head, přidaná větev nebo jiný scope, jehož inventář se liší, používá
původní úplný export a validaci. Shoda není validační cache ani oprávnění
k přenosu: pouze vynechá Git bajty, které by se stejně neposlaly. Nepravdivé
peer hlášení může způsobit vynechání odpovědi, nikoli publikaci či přenos
neověřeného grafu. Nové příchozí Git bajty nadále procházejí plnou sémantickou
validací. Aktuální identity, podpisy, sharing policy, chaty a pooly se kontrolují
nezávisle. Nevzniká další persistentní stav, nemění se protokol ani crash/recovery
hranice, a uložený nedokončený outbound request se kvůli této optimalizaci nepřepisuje.

## Sdílený časový rozpočet ověřování historie

Příprava/ověření bundle používá jeden kooperativní 60s rozpočet fáze, sdílený
vnořenými validacemi, větvemi a Git wrappery. Platí dřívější explicitní deadline
a dosavadní maximálně 30s limit jednotlivého Git podprocesu. Rozpočet neobnovuje
nová větev či dočasný repozitář; limit 500 commitů a všechny sémantické/privacy
kontroly zůstávají. Po dokončení CPU validace se ještě kontroluje vypršení.

Timeout není důkaz neplatného obsahu: přijímací HTTP hranice vrátí 503.
Sync/replikace zachovají původní operation ID, podepsaný request a payload pro
nativní explicitní retry/recovery; timeout nepovoluje nový zápis ani smazání
intentů. Před publikací se uklidí dočasné ověřovací repo, po durable intentu
platí původní recovery podle ADR 0003. Rozpočet se nevkládá kolem celé publikační
transakce a nemění žádný persistentní/protokolový formát.

Jde o limit fáze, ne celého HTTP requestu či synchronizace; CPU/fsync se během
volání preemptivně nepřerušuje. Delší validace vyžaduje budoucí tracked-job návrh,
ne vynechání kontrol. Důkazy a otevřené hranice viz
[audit vlastnictví](../http-concurrency-ownership.md).

### Zobrazení přenesených vydání — 11. 11. 2026

Přehled Výstupů čte konkrétní ReportSnapshot/dokument z validovaného Gitu,
nikoli pouze publikační job místního uzlu. Přijatý dokument proto nevytváří
kopii vzdáleného journalu ani grant. Nový název a čas sestavení se zmrazí
v původním kandidátovi/resultu a uloží standardními Git metadaty; Markdown,
Context Manifest, schválené hashe, privacy a formát přenosu zůstávají zachované.
Crash recovery používá původní publikační journal, CAS a receipt, bez další
persistentní vrstvy. Detaily: [konkrétní zprávy](../report-outputs.md).
