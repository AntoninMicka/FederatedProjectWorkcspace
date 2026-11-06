<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0062 — Připnutá fronta a potvrzení dokončení

Datum: 31. 10. 2026. Stav: přijatý návrh uživatele, implementační řez
`PLAN-QUEUE-02`, cílová úroveň PoC validated. Navazuje na ADR 0003, 0059 a 0060.
Autoritativní rozsah drží Workspace; tento dokument není druhým plánem.

## Rozhodnutí

Pracovní fronta je lokální výběr odkazů. Předání je jiný, neměnný objekt:
manifest `fpw-queue-packet-v1`, identifikovaný SHA-256 kanonického JSON.
Váže projekt, vlastníka, mapping/session, queue revision, plánový commit/revizi,
zdrojový repository commit, vybrané tasky, podklady a explicitní blockery.
Publikace ve Workspace vyžaduje aktuální mapping vlastníka fronty a lidsky
povolený export podkladů. IDE token nedostává volné publikační ani review API;
omezenou serverovou obnovu při autosync popisuje doplnění níže.

Podklady pocházejí výhradně z validovaného Git snapshotu. Relativní artifact
odkazy se procházejí s visited množinou a limity 128 dokumentů, hloubky 16 a
8 MiB. Manifest má limit 1 MiB, jeden textový dokument 1 MiB. Kanonické soubory
definic vybraných tasků se zahrnou jako provenance; jejich nesouvisející task
sekce se dále nerozbalují. Další odkazy pocházejí z popisů vybraných tasků a
rekurzivně z jejich podkladů. Zdrojové bajty se nepřepisují ani nesumarizují.
Nepovolený, chybějící nebo nepodporovaný artifact je blocker; neúplný balíček
nelze předat agentovi ani potvrdit jako dokončený. Export nepřidává oprávnění
k jinému projektu a nestahuje URL z internetu. Cross-project ID, které není
v oprávněném exportním katalogu tohoto mappingu, zůstává blockerem, nikoli
implicitním rozšířením scope.

Rozšíření 0.4 používá existující credential, obyčejné soubory a samostatný
pohled Fronta. Content-addressed cache drží jedny ověřené bajty; generace
balíčku odkazuje do této cache hardlinkem, případně relativním symlinkem,
a kopíruje až při nedostupnosti obou mechanismů. Symlinky jsou přípustné jen
v tomto exportním adaptéru a jen na přesný digest v téže cache. Obecný
filesystem reader i projektové úložiště je nadále odmítají. Nedělají se linky
do kanonického nebo pracovního Gitu. Bloby jsou read-only pro vlastníka;
při použití se ověřuje digest, vlastník, typ, velikost a cíl odkazu. Toto není
izolace proti útočníkovi se stejným OS účtem: změnu zjistí hash, nevzniká důkaz
fyzické neměnnosti. Poškozený obsah se nepřepíše jako údajně platný.

## Dvě nezávislá potvrzení

Agentní completion je zpráva v existujícím inboxu. Nese původní revision,
packet ID, task ID, skutečný zdrojový commit, shrnutí a evidence.tests/diff.
`reported_by: agent` deklaruje původ, nikoli ověřenou identitu procesu.
Zprávy se přenášejí pod credentialem existujícího mapování. Lidskou akceptaci
vytváří až oprávněný reviewer Workspace; IDE credential ji vyvolat nesmí.
Výsledek review obsahuje skutečnou identitu reviewera, operation ID a receipt.
Není vyžadováno dvojí lidské potvrzení v IDE a Workspace.

Navazující úkol nelze předat k realizaci ani nahlásit jako dokončený před
přijetím jeho předpokladů. Container (batch/milestone) lze dokončit až po
přijetí přímých potomků; agentní hlášení nesmí samo zavřít podřízené tasky.
Pro realizaci rozpracované dávky zařaďte její konkrétní tasky. Scope přijetí
zůstává jeden výslovně přijatý task/checklist, ne implicitně celý podstrom.
Starší nefrontové workflow zachovává původní omezení leaf tasků.

Přijetí mění plánový HEAD, nikoli připnutý manifest. Zbývající položky mohou
postoupit jen po ověření řetězce původní HEAD → native receipt přijatého
výsledku tohoto packetu → další takový receipt. Každý commit musí mít přesného
rodiče a nativní journal musí potvrdit jeho operation ID. Libovolný cizí
commit, superseded packet, revokace či změna pracovní fronty blokují další
completion. Nejde o automatický rebase starého zadání. Přijetí v UI se navíc
řídí aktuálním serverovým queue_reviewable, nikoli pouhou shodou task ID.
Původní požadavek na explicitní nové předání při změně revize nahrazuje
níže schválená automatická obnova. Staré soubory a zprávy zůstávají.

Fronta zobrazuje agentní a uživatelský flag jako obnovitelnou projekci bridge
review/native receipts. Není zaveden další autoritativní completion zápis do
JSON fronty. Původní text tasku a stav jeho dokončení drží pouze roadmapa.

## Crash boundaries a recovery

1. Před publikací se porovná revize fronty a HEAD; po sestavení je znovu
   ověřen mapping i rodičovské připojení. Balíček se vloží jednou bridge SQLite
   transakcí pod content digestem. Před vložením není publikovaný; po vložení
   lze stejný výsledek dohledat, aniž by vznikla druhá generace. Připravené
   mutující review blokuje publikaci nové generace.
2. IDE publikuje cache a odkazy přes temporary + fsync + rename; manifest
   až po všech dokumentech a druhé kontrole serveru. Před manifestem zůstanou
   nejvýše neodkazované bloby. Starý aktivní pointer se nepřepíše částečnou
   generací. Manifest je neměnný; queue.json je poslední známý stav zvlášť.
3. Inbox používá původní UUID/digest deduplikaci. Přijetí HTTP zprávy není
   lidské potvrzení. Ztracená odpověď dovoluje replay stejných bajtů pod stejným
   UUID; jiné bajty pod stejným ID se odmítnou. Neznámé účinky se nereportují
   jako no-change ani se nevytváří nové message ID pro slepý retry.
4. Review používá původní bridge intent → Workspace journal → Git → index →
   bridge outcome. Před native write se ověří stále stejný balíček i fronta.
   Po commitu a před outcome je packet dočasně stale; obnovuje se přesně stejný
   intent. Native receipt zabrání druhému commitu. Status fronty se po outcome
   znovu odvodí, bez nové koordinační transakce přes filesystem a SQLite.
5. Žádný bridge SQLite writer lock se nedrží přes nativní projektový zápis.
   Queue locks jsou neblokující; souběžná změna skončí explicitní chybou.
   Není deklarovaná atomicita pracovní fronty, bridge SQLite a projektového
   Gitu. Fyzická trvanlivost závisí na hostitelském filesystemu a zařízení.

## Ověření a omezení

Cíleně se ověřují přesné bajty a cykly, limity, evidence/ID, pořadí A/B/C,
revokace, stale a změna fronty, replay, všechny tři review hranice, přerušený
export před manifestem, hardlink/symlink/copy a tamper. Node integrace používá
skutečný HTTP backend a filesystem. Samostatné native extension-host smoke
ověřuje instalaci a aktivaci VSIX v izolovaném profilu. To nenahrazuje ruční
akceptaci plného toku v běžném profilu uživatele.

Windows/macOS, remote SSH/WSL a cross-project automatické importy nejsou
prohlášeny za ověřené. Během implementace se nespouští coding agent ani LLM.

## Automatická obnova fronty, zadání a podkladů

Uživatel 31. 10. 2026 výslovně požádal odstranit opakované ruční publikování
a vybral rozsah „Fronta i zadání a podklady“. Toto rozhodnutí nahrazuje
povinnou ruční obnovu po plánovém commitu nebo změně fronty; nemění lidskou
akceptaci výsledků ani povolení exportu v nastavení Workspace.

Prázdný `exchange` při běžném autosync může pro existující bound mapping
s lidsky povoleným exportem sestavit první nebo nový balíček vybrané fronty.
Server používá živou identitu vlastníka, současný Git snapshot, aktuální
frontu, stejné privacy kontroly a limity jako ruční publikace. Žádost z IDE
neobsahuje cílový HEAD, tasky nebo nový exportní scope. Nezavádí se další
publikační endpoint ani automatické spuštění agenta. Dosud nevybraná prázdná
fronta zachovává starší nefrontový workflow; vyprázdnění již předané fronty
vytvoří balíček bez položek, aby starý výběr nezůstal aktivní.

Změna zadání nebo podkladu vytváří novou neměnnou generaci, nepřeznačuje
staré hlášení. Původní dokumenty a balíčky zůstávají dohledatelné. Kontrola
porovnává i projektový commit, nikoli pouze vybraný text tasků. Neplatné ID
nebo pořadí fronty, nepovolený export a neúplné podklady zůstávají viditelným
blockerem. Stejný neúplný vstup nevytváří generaci při každém pollu.
Validní řetězec lidských přijetí umožňuje postup A → B ještě před dalším
idle pollem. Ten poté připne i snapshot mappingu k novému commitu.

Nezpracované `completed`/`progress` hlášení a připravené review pozastaví
automatickou obnovu. Zprávy z IDE se nejdřív doručují v dávkách po 20;
obnova probíhá až v cyklu bez odesílaných zpráv. Tím není zaručena znalost
rozepsaného textu v editoru či práce běžícího agenta: ten musí znovu načíst
konkrétní předání a report pod starým superseded packet ID se odmítne.
Přijetí a odmítnutí člověkem se nikdy neautomatizuje. Již potvrzené receipts
se přehrávají podle UUID a digestu i po změně snapshotu.

Při nové generaci se dřívější lidská přijetí přenesou pouze z ověřeného
native receipt řetězce předchozího packetu a jen pro stále dokončené vybrané
tasky. Manifest nese `accepted_task_ids` a `previous_packet_id`; samotný
checkbox bez tohoto důkazu se za lidskou akceptaci nevydává.

Crash boundaries: fronta se pouze čte pod existujícím zámkem. Nový snapshot
mappingu a balíček se zapisují společnou bridge SQLite transakcí, která
znovu kontroluje mapping, rodičovské připojení, HEAD a pending review. Pád
po změně snapshotu před insertem obojí rollbackne; po commitu lze výsledek
dohledat a další poll jej znovu nepublikuje. Nezapisuje se projektový Git,
projektový index ani journal a není slibována atomicita s jejich souběžnou
změnou: následný nesoulad HEAD se znovu projeví jako stale stav.

IDE 0.4.3 exportuje queue/context i při zavřeném sidebaru. Původní cache,
ověřování digestů a zveřejnění manifestu až po úplném stažení zůstávají.
Nová generace neodstraňuje starou. Source baseline adaptuje již existující
opravu `fix/queue-source-head`: IDE zjišťovalo zdrojový HEAD lokálně a při
použití ověřovalo návaznost historie. Tuto podmínku ruší doplnění
z 6. 11. 2026 níže. Reuse/adapt: `TaskQueue.assess`, `publish`,
`snapshot`, existující bridge transakce, atomic-file helper a cache;
nový scheduler, úložiště ani externí komponenta nejsou potřeba.

## Příznaky, ruční žádost a hierarchie (IDE-QUEUE-UX-01, 2. 11. 2026)

Rozhodnutí o lidském přijetí výše platí beze změny. Uživatel 2. 11. 2026 vybral
dvoukrokové potvrzení: tlačítko v pluginu vytvoří jen zprávu `reported_by: user`
a roadmapu mění dál pouze review ve Workspace. `reported_by` zůstává deklarací
původu, takže proces se stejným OS účtem může žádost napodobit; neuzavře tím úkol.

| Příznak | Zdroj | Změna |
|---|---|---|
| `held` (pozastaveno) | pracovní fronta | ručně, s revizí, HEAD a auditem |
| `agent_confirmed` | hlášení v inboxu | agent přes kontrakt balíčku |
| `user_requested` | zpráva `reported_by: user` | akce v pluginu |
| `user_confirmed` | native receipt review | jen reviewer ve Workspace |
| `eligible`, `startable`, `blocked_by` | plán a balíček | odvozené, needitovatelné |

Ruční změna `held` zapíše původní a novou hodnotu, aktéra a revizi do omezeného
auditu ve frontě. Zvýšení revize vytvoří novou generaci balíčku obvyklou obnovou,
takže pozastavení platí až po ní a do té doby je starý balíček `stale`. Pozastavená
položka není zahajitelná ani přijatelná; stav dokončení příznak nezmění.

Fronta nese dávku jako rodiče: `manifest.hierarchy` drží přímé potomky kontejnerů a
`manifest.linked_tasks` připnuté definice podúkolů, které jsou v rozsahu reportu,
ale nejsou položkami fronty. Podklady se procházejí i z nich, soubory se dál jen
odkazují. Pole vznikají pouze u kontejnerů s potomky, jiné balíčky mají původní
tvar i ID. Dávka je `startable` před přijetím podúkolů, `eligible` až po něm.
Ostatní kontejnery se předat nedají. Opakovaný odkaz se zobrazí jednou a označí,
cyklus je blocker a nerozřešený odkaz příjemce ukáže jako problém.

Crash boundaries: nové persistentní vrstvy nejsou. `held` používá atomický zápis
fronty a `QueueOutcomeUnknown` podle bodu 5; po ztrátě výsledku se stav načte znovu.
Ruční žádost používá inbox a UUID deduplikaci podle bodu 3 a review zůstává podle
bodu 4. Stav `queue.json` je poslední známý; plugin jej při výpadku označí jako
neaktuální a nenabídne předání ani žádost.

## Přidávání při chybách jiných položek (6. 11. 2026)

Uživatel upřesnil, že neplatné závislosti existující položky nesmějí blokovat
přidání jiného připraveného úkolu. Pracovní fronta smí během sestavování
obsahovat chyby; teprve neměnný balíček pro IDE vyžaduje její úplnou validaci.
Přidání ověřuje vlastní dostupnost, nehotovost, neduplicitu a předpoklady
nového uzlu nad aktuálním grafem. Předpoklad může být dokončený/vyřešený
nebo již zařazený před novým uzlem podle existujícího startovacího pravidla.
Žádost musí obsahovat aktuální projektový HEAD a revizi fronty; stará žádost
se odmítne. Starší připnutí obsahu fronty samo o sobě přidání neblokuje, pokud
žádost vznikla z aktuálního statusu. Výsledek uchová veškeré existující chyby
a skutečnou hodnotu `valid`; publikační `assess` zůstává povinný.

Persistence se nemění: jeden zámek, dočasný JSON, fsync, atomické replace
a fsync adresáře. Před replace zůstává původní fronta, po replace je výsledek
při ztrátě odpovědi `QueueOutcomeUnknown`; před dalším zápisem se načte stav.
Nezapisuje se plán ani přijetí úkolů. Stávající testy obou hranic writeru
platí i pro toto uvolnění vstupní podmínky.
## Obnova IDE bez závislosti na historii programu (6. 11. 2026)

Na výslovný požadavek uživatele není zdrojový commit ani jeho ancestry
podmínkou synchronizace či předání fronty. Squash/rebase, shallow clone nebo
stará lokální `source-baseline.json` nemají vyžadovat nové předání. IDE nadále
ověřuje identitu repozitáře; aktuální HEAD se zaznamenává jako provenance
výsledků. Původní manifesty a baseline soubory se nemění ani nemažou.
Revize kanonického Workspace, identita/podpis připojení, oprávnění, digesty
podkladů a lidská akceptace zůstávají závazné.

Čekání na lidské review se zobrazuje jako čekání, nikoli chyba spojení.
Zadání přitom zůstává stale a nelze je použít jako aktuální. Chyba vykreslení
panelu vždy uvolní synchronizační guard, takže další poll pokračuje. Chybějící
inbox při kontrole obnovy znamená žádné čekající zprávy; jiné filesystem chyby
se neignorují. Obnova stale zadání již nenabádá k opakovanému nastavení projektů.

Reuse/adapt: stávající discovery, autosync, `bridge.repository`, persistovaný
refresh intent a atomic-file helper; žádný druhý writer ani scheduler.
Crash boundaries zůstávají podle tohoto ADR a ADR 0060: změna neprovádí zápis
do projektového Gitu, indexu ani journalu. Lokální STATUS je obnovitelná
projekce; po pádu jej další poll přepíše. Neprovádí se slepý replay neznámých
mutací, automatické review, změna credentials ani spuštění desktopu.
