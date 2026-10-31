<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Fronta odkazů na úkoly — PLAN-QUEUE-01

Fronta je lokální pracovní výběr pro jeden projekt a jednoho uživatele.
Kanonické definice, dokončení a závislosti drží Workspace; fronta je nemění.
Implementace je v `spikes/task_queue.py`, ovládání ve sdílené desktop/web
roadmapě. Rozsah první dávky nezahrnuje transport do IDE ani spouštění agenta.

## Ovládání

V roadmapě použijte existující filtr **Připravené**: nedokončené položky bez
závislostí nebo se všemi závislostmi dokončenými. Vyberte položku a v detailu
stiskněte **Přidat do fronty**. Fronta neobsahuje duplikáty ani dokončené položky.

Filtr **Navazující** ukazuje nedokončené položky, které ještě mají nesplněné
závislosti, ale všechny tyto přímé předpoklady už jsou ve frontě. Úkol bez
nesplněných závislostí patří mezi Připravené. Přidává se na konec; předpoklady
proto vždy předcházejí závislým položkám. Libovolné přetahování pořadí se
v této dávce nezavádí. Filtr respektuje vybranou úroveň roadmapy jako ostatní
pohledy; dávky vidíte na úrovni milníků, jejich tasky po otevření dávky.

**Odebrat** nejprve načte aktuální dopad a ukáže seznam všech odebíraných ID.
Jedno potvrzení odstraní také všechny tranzitivně závislé položky z fronty.
Nezávislé položky zůstávají. Změna fronty nebo roadmapy mezi náhledem a
potvrzením zneplatní náhled.

**Obnovit frontu** pouze načte aktuální stav. Po změně roadmapy znovu otevřete
projekt a použijte **Znovu ověřit**. Obnova ze staré revize není automatické
přijetí nových závislostí: chybějící ID, dokončená položka bez navázaného přijatého receiptu nebo předpoklad,
který chybí před úkolem, zablokují přidávání. Vadné položky lze odebrat
s náhledem dopadu a zbývající frontu znovu ověřit. Pokud referencované ID
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
