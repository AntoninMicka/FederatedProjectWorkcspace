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
povolený export podkladů. IDE token nedostává publikační ani review API.

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
Mapping s aktivním balíčkem se při autosync nepřipíná automaticky na novou
revizi; vyžaduje explicitní nové předání. Staré soubory a zprávy zůstávají.

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
