<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Fronta odkazů na úkoly — PLAN-QUEUE-01

Fronta je lokální pracovní výběr pro jeden projekt a jednoho uživatele.
Kanonické definice, dokončení a závislosti drží Workspace; fronta je nemění.
Implementace je v `spikes/task_queue.py`, ovládání ve sdílené desktop/web
roadmapě. Rozsah první dávky nezahrnuje transport do IDE ani spouštění agenta.

## Ovládání

V roadmapě použijte existující filtr **Připravené**: nedokončené položky bez
závislostí nebo s předpoklady ve stavu Vyřešeno/Dokončeno, přičemž nejvýše
jeden předpoklad může být Probíhá. Vyberte položku a v detailu
stiskněte **Přidat do fronty**. Fronta neobsahuje duplikáty ani dokončené položky.

Filtr **Navazující** ukazuje nedokončené položky, které ještě mají nesplněné
závislosti, ale všechny tyto přímé předpoklady už jsou ve frontě. Úkol bez
nesplněných závislostí patří mezi Připravené. Přidává se na konec; předpoklady
které stále blokují zahájení, proto předcházejí závislým položkám. Pořadí lze upravit tlačítky
**Posunout nahoru / Posunout dolů** na stránce Fronta úloh. Filtr respektuje
vybranou úroveň roadmapy jako ostatní pohledy; dávky vidíte na úrovni milníků,
jejich tasky po otevření dávky.

Přesun zachová všechny položky a mění pouze pořadí. Pokud B závisí na
nedokončeném A a C na B, musí zůstat A před B před C; přesun A za B/C nebo
B před A se odmítne. Nezávislé položky lze přesouvat a dokončený předpoklad
nemusí být ve frontě. Neplatný či cyklický graf se odmítá už při načtení;
přesun samotný nemění vztahy v roadmapě.

Hotfix v dávce MON-08 umožňuje přesuny i v neplatné pracovní frontě nad
platným aktuálním grafem. Každý přesun smí odstranit nebo zachovat jednotlivé
chyby, nesmí přidat novou. Frontu s více porušenými závislostmi tak lze opravit
postupně. Neplatná fronta zůstává zablokovaná pro předání do IDE; přesun ani
oprava nemění dokončení, souhlasy nebo závislosti v roadmapě.

Server vrací u položek `can_move_up`, `can_move_down` a vysvětlení
`move_up_reason` / `move_down_reason`. UI zakáže nepřípustný sousední přesun
a v popisku uvede konkrétní blokující ID. Po přesunu zůstane fokus na téže
položce, takže lze pokračovat klávesnicí. Klient zobrazuje nové pořadí až
po odpovědi serveru. Odmítnutý nebo neznámý výsledek vyžaduje obnovu stavu;
mutace se automaticky neopakuje a odpověď starého projektu nepřepíše nový.

**Odebrat** nejprve načte aktuální dopad a ukáže seznam všech odebíraných ID.
Jedno potvrzení odstraní také tranzitivně závislé položky, kterým by odebráním
chyběl nesplněný předpoklad. Odebrání dokončené položky závislé položky nemění,
protože její předpoklad zůstává splněný. Nezávislé položky zůstávají. Změna fronty nebo roadmapy mezi náhledem a
potvrzením zneplatní náhled.

**Opravit pořadí a předpoklady…** načte náhled úplného výsledného pořadí
a doplňovaných předpokladů podle aktuální roadmapy. Zachová nedokončené
odkazy a jejich příznaky; chybějící předpoklady doplní rekurzivně a řadí je
před následníky. Není to vyprázdnění a nové naplnění fronty. Náhled nic
nezapisuje a změna se provede až po potvrzení přesného náhledu.

Dokončené položky vypíše náhled jako odkazy k vyřazení z pracovní fronty.
Jediné potvrzení vyřadí všechny uvedené dokončené odkazy; zbývající fronta,
audit příznaků, přijaté výsledky a staré IDE balíčky zůstanou zachované.
Příznak Pozastaveno se zruší pouze u vyřazeného odkazu. Samotný náhled nic
nemaže a vyřazení nemění dokončení ani historii úkolu v roadmapě.

Odkaz na chybějící položku se nemaže automaticky a zůstává překážkou opravy.
**Vyřadit jen tento odkaz** nabídne náhled
odebrání jediné položky a zachová následníky i ostatní odkazy. Ti mohou
dočasně zůstat neplatní; jejich chybějící předpoklady lze následně doplnit
opravou. Původní **Odebrat** nadále nabízí explicitní kaskádové odebrání.
Změna roadmapy nebo revize fronty zneplatní oba typy náhledu.

**Obnovit frontu** pouze načte aktuální stav. Po změně roadmapy znovu otevřete
projekt a použijte **Znovu ověřit**. Obnova ze staré revize není automatické
přijetí nových závislostí: chybějící ID, dokončená položka bez navázaného přijatého receiptu nebo předpoklad,
který chybí před úkolem, zablokují předání do IDE. Nezávislou novou položku
lze přidat po ověření jejích vlastních předpokladů; nesouvisející chyby tím
nezmizí. Vadné odkazy lze jednotlivě odebrat s náhledem nebo opravit pořadí
a předpoklady bez smazání ostatních položek. Pokud referencované ID
zmizelo, staré vztahy se nevymýšlejí; případné zbývající chyby jsou výslovně
uvedené a fronta zůstává neplatná, dokud nejsou vyřešené.

Po chybě či timeoutu mutace nejprve obnovte stav. Klient mutaci automaticky
neopakuje. Při změně projektu se předchozí fronta nesmí zobrazovat jako aktuální.

## Úložiště, oprávnění a recovery

Reuse/adapt: stávající graf a jeho `ready` příznaky, `Projects.open`,
Workspace journal lock, `private_directory`, `sync_dir` a vzor obyčejných
privátních souborů z [ADR 0060](adr/0060-local-file-ide-bridge.md).
Nepřidává se další projektový index, broker ani databáze plánu.

Fronta leží vedle node konfigurace v privátním adresáři
`.<node-filename>.task-queues/`, mimo libovolný Git worktree. Názvy souborů jsou
SHA-256 dvojice project ID / owner ID. JSON obsahuje scope, revizi, připnutý
project HEAD a uspořádaná task ID; neobsahuje kopie definic ani stav dokončení.
Desktop používá lokálního autora uzlu; web přihlášený účet, bootstrap admin
lokálního autora. Tyto scope se nesmějí zaměňovat. Při každém API přístupu
web znovu ověří účet a projektové oprávnění. Reader může svou frontu číst,
editor/project-admin ji mění; read-only replikace mutace nepovoluje.
Webový `Projects.open` navíc vynucuje stávající privacy kontrolu.

`POST /v1/task-queue` používá pole `project_id`, `action` a podle akce další
povinná pole. `status` je pouze čtení obsahu fronty. `add` a `remove-preview`
potřebují `task_id`, `revision`, `expected_head`. `remove` navíc potřebuje
přesný `preview_sha256`. `revalidate` potřebuje `revision`, `expected_head`.
`move` potřebuje `task_id`, `target_index`, `revision`, `expected_head`.
`repair-preview` potřebuje `revision`, `expected_head`; `repair` navíc
`preview_sha256` odvozené z původního i navrženého pořadí, doplněných i
vyřazovaných dokončených ID,
chyb, scope a revize. `remove-single-preview` a `remove-single` používají
stejná pole jako původní remove varianty, ale náhled má `cascade:false`,
takže digest náhledu nelze zaměnit s kaskádovým odebráním.
`target_index` je výsledná pozice počítaná od nuly v rozsahu celé fronty;
musí být celé číslo, nikoli boolean. Například přesun D v A/B/C/D na index 1
dá A/D/B/C, pokud zůstane platné pořadí závislostí. Stejná cílová pozice nic
nezapíše a nezvýší revizi; skutečný přesun zvýší revizi právě jednou.
Owner se nikdy nepřebírá z requestu. Nepodporované akce a další pole se odmítají.
Status může inicializovat prázdný lokální adresář a lock, nikoli projektový Git.

Zámek fronty je neblokující `flock`; současně je držen nativní zámek projektu,
aby plán neměnily jiné nativní zápisy. Pracuje se s platným commit/index
snapshotem a kontroluje HEAD. Externí Git proces není účastníkem tohoto zámku;
zjištěná změna po zápisu znamená neznámý výsledek a nutnost nového načtení.
Není předstíraná atomická transakce lokální fronty a projektového Gitu.

Crash boundaries:

1. Před zápisem se kontroluje revize fronty a HEAD. Stale request nic nemění.
2. Dočasný soubor má režim 0600 a zapíše se přes fsync. Pád před replace
   ponechá původní frontu; osiřelý temporary se nikdy nepoužije jako autorita.
3. Atomický replace publikuje celou novou revizi. Fsync adresáře potvrzuje
   její trvanlivost; při prvním založení se synchronizuje i rodič adresáře.
4. Chyba po replace je `QueueOutcomeUnknown`. Po restartu se načte jediný
   finální JSON, buď stará, nebo nová validní revize. Symlink, cizí scope,
   neplatná práva a poškozený JSON se odmítají; nic se tiše nevynuluje.
5. Ztracená odpověď se řeší načtením stavu. Původní revize zabrání slepému
   zopakování úspěšné mutace. Přidání/odebrání nemění Git, index ani journal;
   journal se používá pouze pro projektový zámek a kontrolu rozpracované operace.

Tyto hranice platí také pro `move`; nepřidává se nový journal ani formát
fronty. Přesun nemění projektový Git a index ani již zveřejněné IDE balíčky.
Stejné hranice platí pro `repair` a `remove-single`: všechny kontroly i celý
nový obsah se dokončí pod původním zámkem, pak se publikuje jediným původním
atomickým replace. Pád před replace zachová původní frontu, pád po něm
úplnou novou revizi; nejistota vyžaduje reload. Stav příznaků a jejich audit
zůstávají zachované, nové předpoklady nejsou implicitně pozastavené ani přijaté.
Stávající idle refresh podle [ADR 0062](adr/0062-pinned-queue-handoff.md)
vytvoří další neměnný balíček s novou revizí a pořadím, zachová původní
balíčky a ověřená lidská přijetí. Čekající lidský review se nadále respektuje.

PoC používá existující linuxový `fcntl`/fsync model. Trvanlivost při fyzické
ztrátě napájení závisí na filesystemu a zařízení; fault-injection test není
nezávislý důkaz chování konkrétního disku. Windows a produkční víceprocesový
provoz nejsou tímto implementačním řezem prohlášeny za ověřené.

## Ověření a předání

Cílené testy: `python3 -m unittest tests.test_task_queue
 tests.test_web_server.WebTests.test_task_queue_roles_owner_isolation_and_confirmation -v`
(při spuštění spojte na jeden řádek). Zahrnují řetězení, částečně splněné
předpoklady, cascade preview, scope, stale, poškození a přerušení před/po replace,
chybu fsync, sdílenou JS logiku bez browseru a skutečné lokální HTTPS RBAC.
Celou závěrečnou bránu spouští standardní unittest discovery podle AGENTS.
Ruční akceptace v běžném desktop/web profilu je samostatný krok; headless
JS nebo automatické API testy ji nenahrazují.

Regrese přesunu navíc ověřuje stale revizi, libovolnou cílovou pozici,
nezávislé položky, dokončené předpoklady, důvody odmítnutí a read-only režim.
Procesové testy ukončí writer před i po replace a ověří původní/novou frontu;
fsync chyba nebo souběžný externí Git commit musí vrátit unknown.
`tests.test_ide_queue` ověřuje nové pořadí v novém balíčku a neměnnost historie.
Opt-in Qt test `tests.test_page_layout` ověřuje skutečné ovladače, fokus,
zotavení po odmítnutí a desktopovou i mobilní šířku.

Pro ruční přijetí `PLAN-QUEUE-03` otevřete Frontu úloh s A, B závislým na A
a nezávislým D. Přesuňte D nahoru/dolů pomocí klávesnice, ověřte zakázaný
přesun B před A a vysvětlení v popisku, obnovte/restartujte a zkontrolujte
pořadí. V read-only projektu musí být změny zakázané. Po synchronizaci IDE
ověřte nové pořadí v novém balíčku a zachování starého balíčku i přijetí.

Autoritativní zadání: Workspace projekt
`c898b941-8eb0-4406-8dad-6e2b96c06d59`, `PLAN-QUEUE-01`; při schváleném předání
HEAD `f7b07663eaeedd74e0f148a0c9489acfa08019f8`, exportní revize
`2278c9487fc455d08c731c8b29c55b86d29d944e076e6f3d27a5a4373f5e0e22`.
Jde o provenance zadání, nikoli druhý živý plán. Automatické doplňování
závislostí a LLM návrhy fronty zůstávají odložené. Transport podkladů,
feature/test příznaky, instrukce agentům a návrat výsledků do Workspace
vyžadují vlastní explicitně předané dávky.

### Ruční průchod v běžném profilu

Po restartu backendu/desktopu s touto zdrojovou větví otevřete projekt a jeho
roadmapu. Z pohledu Připravené přidejte jednu položku. Přepněte na Navazující,
přidejte jejího následníka a ověřte pořadí ve frontě. Odebrání předpokladu musí
předem ukázat obě ID a změnit frontu až po potvrzení. Znovu přidejte položku,
restartujte aplikaci a ověřte zachování fronty. Stav dokončení v roadmapě má
během tohoto průchodu zůstat stejný. Tento lidský průchod se eviduje odděleně
od automatického testu v dočasném projektu.

### Technické výsledky 31. 10. 2026

Finální plná brána: `python3 -m unittest discover -s tests -v` — **1153 testů,
40 skipped, OK**, 292,825 s. Cílené queue/RBAC testy: 12 OK; po opravě sdíleného
importu navíc 4 cílené webové/JS regresní scénáře OK. Izolovaný Qt/WebEngine
nad dočasným HTTPS projektem prošel přihlášení, otevření roadmapy, A → B → C,
Navazující, potvrzení dopadu a kaskádové odebrání. Ověřil také aktivní CSS pro
scroll seznamu bez CSP chyby. Syntaxe sdíleného JS a `git diff --check` prošly.

Ruční akceptace běžného profilu zůstává otevřená. Běžící uživatelský backend
se v rámci implementace nerestartoval; testovací prohlížeč používal izolovaný
server. Zdrojový commit, push ani PR nevznikly. Autoritativní task se tímto
technickým ověřením automaticky neoznačil za dokončený.

Od rozšíření 0.4.0 navazuje [předání fronty a potvrzování](ide-queue-handoff.md).
Agentní a uživatelské flags se obnovují z bridge/native receipts; roadmapa
zůstává autoritou dokončení. Vlastní přijaté výsledky balíčku mají explicitně
ověřenou návaznost, jiné změny HEAD nadále vyžadují revalidaci/nové předání.

Zahajitelnost neznamená možnost potvrdit dokončení: ta vyžaduje potvrzené
splnění všech předpokladů. Stejné pravidlo zahájení používá graf plánu,
fronta, přesuny/odebrání referencí i přijetí zprávy Probíhá z IDE. Podrobnosti
uvádí [ADR 0067](adr/0067-plan-work-states-and-sum.md#zahajitelnost-závislých-úkolů).
