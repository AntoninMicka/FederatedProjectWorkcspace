<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0042 — Obousměrná interní synchronizace nativním Gitem

Datum: 2026-10-23. Stav: přijato a implementováno v
`F-M5-SHARING-SYNC-01`; automatické ověření prošlo, fyzická desktop ↔ LXC
akceptace obou směrů, návratu po restartu a zachování divergence prošla.

Doplnění 2026-10-26: ADR 0056 rozšiřuje tutéž obousměrnou operaci a její
durable journal o projektová RW chatová vlákna. Git pravidla níže se nemění;
chatový payload má vlastní fast-forward/fork strategii.

Doplnění `F-M5-SYNC-CONTROLS-01` přidává nad stejný controller hromadné
ruční spuštění a node-local vypínač automatiky. Nemění protokol, policy ani
projektové crash hranice.

## Kontext a rozsah

Katalog z ADR 0041 oznamuje jen UUID a název projektu. ADR 0040 požaduje pro
`same-team` automatický obousměrný přenos všech projektů a jejich větví a pro
`same-company` jen projekty a větve povolené místní maticí. Starší ADR 0038
řeší pouze podepsaný směr primary → read-only replica. Nový řez jej neruší jako
recovery základ, ale nesmí jednosměrný grant vydávat za cílový interní sync.

`external`, federace identit/rolí, automatický merge, řešení konfliktu a export
bez historie jsou mimo tuto dávku. Synchronizace dat sama neuděluje lokálnímu
uživateli projektovou roli.

## Reuse rozhodnutí

- **Reuse:** Git CLI a `git_transfer.validate_history`, Ed25519 node identity,
  peer CA a HTTPS ochrany, `Administration` schema v6, katalog, projektový
  writer lock, Journal/Index a `ProjectCreation` registrace.
- **Adapt:** `project_replication` signed bounded bundle a lost-response vzor
  na symetrickou výměnu inventur a volitelných bundle; node-local SQLite
  journal uchová přesný request i response. Přenos zůstává `git bundle`, ne
  vlastní serializace commitů.
- **Reject:** automatický merge/rebase, force push, kopírování worktree,
  synchronizace `.git` adresáře, nový Git writer, SSH heslo a browser bearer.
  Smart-HTTP server se nyní nepřidává: stávající připnutý node endpoint a
  bundle zachovávají menší síťovou plochu a již ověřené recovery hranice.

## Scope a protokol

Jedna operace se týká jednoho project UUID. Obě strany podepíší inventuru
`refs/heads/*` ve tvaru ref + commit ID. `same-team` smí exportovat všechny
větve všech dostupných projektů. `same-company` smí exportovat pouze projekt s
lokálním záznamem matice a větve po aplikaci `selected-only` nebo
`all-except-hidden`. Příjem dat je dovolen jen od schváleného peeru se stejnou
interní úrovní; `external` a `unspecified` jsou fail-closed.

Liší-li se inventura od posledního potvrzeného přenosu, strana přiloží jediný
bounded nativní `git bundle` s přesně vyjmenovanými povolenými refs. Jinak se
přenese jen malá inventura. Odpověď používá stejný formát a může nést bundle
opačného směru, takže serverový dynamický klient nemusí znát zpětný endpoint.
Podpis váže operation ID, oba uzly, project UUID, scope, všechny heady,
velikost a SHA-256 bundle. Browser API credential není node credential.

Každý dosažitelný commit každého přijatého refu projde `validate_history`.
Povoleny jsou `public`, `project` a `confidential`; `local-only`, neklasifikovaný
soubor, symlink, submodule, neplatný přechod nebo překročení limitu se odmítne.

## Refs, divergence a lokální oprávnění

Chybějící projekt lze z validovaného bundle zaregistrovat jako běžný lokální
projekt. Chybějící větev lze založit. Existující větev se změní jen když je
její současný head předkem kandidáta; protější starší head nic nepřepisuje.
Při divergenci zůstane lokální větev beze změny a kandidát se zachová pod
`refs/federation/incoming/<peer UUID>/<branch>`. Nikdy se automaticky
nemerguje, nerebasuje ani force-updateuje.

Přenos projektu neobchází lokální RBAC. Nově přijatý projekt lze číst podle
lokálního účtu a role; lokální zápis nadále vyžaduje místní oprávnění. Tato
dávka nefederuje credentials, session ani automaticky nevytváří členství.

## Persistentní vrstvy a recovery

1. Git-backed `Administration` je autorita trustu, sharing level a lokálního
   exportního scope; změna matice po přípravě zneplatní neodeslaný request.
2. Projektový Git je autorita obsahu a refů. Aktualizace jsou serializované
   project writer lockem; aktuální větev používá pending journal marker.
3. Node-local sync SQLite journal drží přesný podepsaný request/bundle a na
   příjmu přesnou odpověď. Není policy autoritou ani projektovým indexem.
4. Staging refs a bundle jsou obnovitelný pracovní stav. Projektový SQLite
   Index se po změně aktuální větve přestaví z nového HEAD.

Pád před durable inbound záznamem nemá účinek. Po něm lze tentýž operation ID
opakovat jen se shodnými bajty. Pád před změnou refů ponechá staging; po části
bezpečných ref update se retry dopočítá ze stejného kandidáta. Po změně aktuální
větve se recovery vždy roll-forward dokončí checkoutem a rebuildem indexu.
Přesná odpověď se uloží před odesláním; ztracená odpověď proto vrátí při retry
stejné potvrzení a bundle. Odlišný payload pod stejným operation ID se odmítne.

Ruční spuštění běží ve volatilním workeru, ale používá tentýž durable journal.
Požadavek na zrušení je kooperativní: před přípravou, před síťovým přenosem a
před lokální publikací zastaví další krok a ponechá outbound záznam pro bezpečný
retry. Vzdálený uzel už mohl přijatý request publikovat, proto zrušení nikdy
neprovádí destruktivní rollback; následující synchronizace rozdíl znovu
zrekonsoliduje. Pád procesu ukončí volatilní worker a existující journal se
obnovuje stejnými pravidly jako dosud.

Automatický scheduler nesmí po přechodné chybě prvního průchodu skončit. Chybu
registru nebo katalogu po startu zachytí na hranici celého průchodu, nejvýše za
pět sekund pokus zopakuje a po úspěchu se vrátí k běžnému intervalu. Jednotlivé
projektové chyby nadále izoluje uvnitř průchodu.

Výchozí automatika zůstává zapnutá kvůli kompatibilitě. Její revizně vázané
nastavení je jediný node-local řádek ve stejném SQLite journalu: commit je
atomická hranice a stale UI zápis se odmítne. Vypnutí zastaví budoucí
automatické průchody, nikoli již rozpracovanou operaci; ruční akce zůstávají
dostupné. Hromadné spuštění není globální transakce a pouze založí stávající
per-project workery. Sdílená policy projekce předem vyřadí `external`,
neschválený peer, chybějící endpoint, nepovolený same-company scope a
nevyřešený konflikt; dvojí spuštění stejného scope nevytvoří druhý worker.

## Omezení

Limit zůstává 500 dosažitelných commitů na validovaný head a 64 MiB na jeden
bundle. První verze přenáší celé povolené refy, nikoli thin bundle; inventura
zabraňuje opakovanému přenosu při nezměněných headech. Retence dokončených
journalů, automatické řešení divergence, shallow/partial clone a smart Git
HTTP/SSH transport zůstávají navazující optimalizace, nikoli podmínka tohoto
bezpečného řezu.

### Nativní export nad připnutým snapshotem

Export nedrží projektový journal po dobu celé validace historie a balení Gitu.
Pod krátkým vlastníkem zachytí povolené refs/head a stav bez pending operace;
drahá práce proběhne nad těmito immutable commity v privátním dočasném bare
repozitáři. Hotové přenášené bajty nadále procházejí úplnou validací grafu.
Před použitím výsledku se pod nativním vlastníkem znovu ověří refs/head, čistý
strom a nepřítomnost rozpracovaného zápisu. Souběžný commit export zneplatní
jako busy; místní změna či journal se nemaže ani nepřepisuje.

Stejná hranice platí pro normalizovaný export počátečního přenosu/repliky.
Dočasný export před durable intentem lze zahodit. Po publikaci platí původní
ID, přesný payload, CAS/index recovery a immutable replay odpovědi podle
ADR 0003 a 0081. Nejde o oslabení validace ani o nový retry protokol.

### Doplnění 2026-11-20: ověření jen nové historie na příjmu (AUDIT-B7-T1)

Příjemce dosud při každé synchronizaci znovu ověřoval celou historii balíku
(až 500 commitů s úplným snímkem každého). Na routeru s LXC to pro projekt
s 217 commity trvalo přes 60 s, příjem skončil `GitDeadlineExceeded`
a každý další pokus začal od nuly. Velký projekt se tak nesynchronizoval
nikdy.

Rozhodnutí: příjemce nadále ověřuje každý commit, který ještě nemá ve
vlastní historii projektu. Commity dosažitelné z jeho větví (`refs/heads/*`)
už ověřil, když do repozitáře vstoupily: zapsal je lokální writer, nebo
prošly dřívějším ověřeným příjmem. ID commitu určuje jeho obsah, proto je
podruhé neověřuje. Platí:

- důvěryhodné jsou jen hlavy větví, které balík také obsahuje, nikdy
  staging refy nedokončených příjmů;
- první nový commit se ověří jako přechod ze snímku svého důvěryhodného
  rodiče;
- bez lokálního projektu (počáteční sdílení) se ověřuje celá historie jako
  dřív;
- limit 500 commitů platí pro neověřenou část;
- ověřování na příjmu má rozpočet `CONTENT_RECEIVE_BUDGET` (45 s), kratší
  než lhůta odesílatele (60 s). Přetížený příjemce tak odpoví `busy`
  (`git-budget`) a odesílatel uloženou operaci zopakuje.

Hranice pádu se nemění: ověření proběhne před jakýmkoli trvalým záměrem
a před publikací do projektu, jako dosud. Výsledek ověření se mezi příjmy
neukládá, důvěra vychází jen z aktuálních větví příjemce. Export odesílatele
a ověření odpovědi zůstávají beze změny.

### Doplnění 2026-11-20: příjem na pozadí s heartbeat streamem (AUDIT-B7-T1)

Uložení příjmu na routeru trvalo pro projekt s 2 MB Git balíkem,
45 vlákny chatu a 568 položkami poolů 127 s. Odesílatel čekal na celou
výměnu jen 60 s (`CONTENT_SYNC_TIMEOUT`). Synchronní výměna tak nemohla
projít. Uživatel rozhodl převést příjem na asynchronní zpracování na pozadí
a spojení udržovat heartbeat zprávami.

Rozhodnutí:

- Odesílatel posílá hlavičku `Accept: application/vnd.federated-workspace.content-sync-stream-v1`.
  Příjemce, který ji zná, přečte tělo a spustí stávající
  `SyncReceiver.receive` jako úlohu na pozadí
  ([`spikes/content_receive_jobs.py`](../../spikes/content_receive_jobs.py)).
  Hned odpoví `200` s tímto typem obsahu.
- Odpověď je proud řádků JSON. Heartbeat přichází každých
  `HEARTBEAT_INTERVAL` (5 s) a nese jen pevný název fáze příjemce a uplynulý
  čas. Koncový rámec je buď `result` s délkou a bajty běžné odpovědi, nebo
  `error` se stavem 503, 409 nebo 422 a stejnými typovanými poli jako dosud.
- Odesílatel čeká na hlavičky v původním rozpočtu 60 s. Po přijetí
  streamu platí `HEARTBEAT_IDLE_TIMEOUT` (20 s) na každé čtení a celkový
  strop `CONTENT_SYNC_MAX_WAIT` (15 min). Výpadek heartbeatu i předčasné
  uzavření streamu skončí stavem `unanswered`. Fáze příjemce z heartbeatu se
  průběžně zobrazuje v diagnostice („Protistrana: …“).
- Úloha na pozadí není HTTP worker. SQLite v ní používá nativní čekání
  a ověření historie má rozpočet `BACKGROUND_RECEIVE_BUDGET` (10 min).
  Zámky `flock` se dál berou bez čekání.
- Na jednom uzlu běží nejvýš jedna úloha příjmu. Jiná operace dostane
  `busy` (`incoming-capacity`) jako dosud. Opakovaný požadavek se stejným
  operation ID a stejnými bajty se připojí k běžící úloze. Úspěšný výsledek
  zůstává k vyzvednutí 120 s. Neúspěšný pokus se nikdy znovu nepodává:
  opakování spustí příjem znovu.
- Ruční synchronizaci lze zrušit a plánovač ukončit na nejbližším
  heartbeatu. Úloha příjemce přitom doběhne.

Kompatibilita: starý příjemce hlavičku `Accept` nezná a odpoví synchronně
typem `content-sync-v2`. Odesílatel pak použije původní cestu s rozpočtem
60 s. Starý odesílatel hlavičku neposílá a dostane synchronní odpověď.
Verze schématu výměny se nemění.

Hranice pádu a recovery:

| Událost | Stav | Obnova |
|---|---|---|
| Odesílatel ztratí spojení nebo zruší čekání | úloha příjemce pokračuje; odesílatel drží řádek `outbound` | další pokus se stejnou operací se připojí k běžící úloze, nebo dostane uloženou odpověď (replay) |
| Pád procesu příjemce během úlohy | stejný jako pád synchronního příjmu | záměr `inbound` vzniká až po ověření; publikaci dokončí journal projektu; opakování znovu ověří a dokončí |
| Úloha skončí, odesílatel už nečeká | odpověď je trvale v `inbound` | replay ze stejných bajtů |
| Ukončení serveru | `server_close` čeká na úlohy do `shutdown_timeout` | nedokončená úloha skončí s procesem; obnova jako při pádu |

Nové trvalé úložiště nevzniká. Registr úloh je jen popisovač běhu
v paměti. Autoritou zůstává journal synchronizace obsahu (`inbound`)
a projektový journal (ADR 0003).

Omezení: po dobu streamu drží spojení jeden HTTP worker příjemce a linku
`content_sync`. Velikost těla a limity balíku se nemění.

### Doplnění 2026-11-21: ověření jen nových řádků poolu (AUDIT-B7-T1)

Po přechodu na příjem na pozadí synchronizace prošla, ale na routeru stála
přes 100 s ve fázi `*-pool-apply`. Každá výměna posílá celý přenosný pool
projektu a příjemce u každého řádku znovu ověřoval provenance: úplné čtení
reportingu a validaci celého snímku pro každý připnutý commit. Pro projekt
s 568 řádky a 21 piny to i na desktopu trvalo 4,9 s (561 volání Gitu).
Během té doby router nestíhal ani otevření projektu ve webu a automatická
kontrola stavu končila `TimeoutError`.

Rozhodnutí: ověřují se jen řádky, které uzel ještě nemá uložené se stejným
obsahem. Uložený řádek prošel ověřením, když vstoupil: vytvořil ho lokální
uzel, nebo přišel z dřívějšího ověřeného příjmu. Řádky poolu jsou neměnné
a piny ukazují na neměnné commity, stejně jako u historie výše. Platí:

- čtení reportingu proběhne jen tehdy, když nový řádek odkazuje na
  definici (`activation`, `report-outcome`, `membership`);
- `_merge` dál v jedné transakci kontroluje vazby, neměnnost a blokované
  vstupy nad celým payloadem;
- řádek se stejným ID, ale jiným obsahem se ověřuje jako nový a `_merge`
  ho jako konflikt neměnného záznamu odmítne.

Opakovaná výměna téhož poolu trvá na desktopu 0,1 s místo 4,9 s. První
přenos nového poolu ověřuje vše jako dřív. Hranice pádu se nemění: záměr
(`prepare`) i zápis (`_merge`) zůstávají, změnil se jen rozsah ověření před
zápisem.

### Doplnění 2026-11-21: kontrola stavu obsahu na pozadí (AUDIT-B7-T1)

Automatická kontrola změn se ptá protistrany na otisk všech sdílených
projektů najednou a odpověď musela přijít do `CONTENT_STATE_TIMEOUT` (15 s).
Router s jedenácti projekty to pod zátěží nestíhal. Kontrola pak končila
`TimeoutError`, automatika nic nespustila a karta zůstávala ve stavu
„Stav neověřen“, i když ruční synchronizace procházela.

Rozhodnutí: odpověď na kontrolu používá stejný heartbeat stream jako příjem
obsahu, s vlastním typem `content-state-stream-v1` a vlastním registrem
úloh (`STATE_JOBS`). Kontrola tak nesoupeří o kapacitu se synchronizací
obsahu. Platí:

- odesílatel ohlásí stream hlavičkou `Accept`. Příjemce spustí výpočet
  na pozadí s nativním čekáním SQLite a zámků a jedním rozpočtem Gitu
  `BACKGROUND_STATE_BUDGET` pro všechny projekty. Heartbeat nese fázi
  `content-state`;
- odesílatel čeká, dokud chodí heartbeat (`HEARTBEAT_IDLE_TIMEOUT`), nejvýš
  `CONTENT_STATE_MAX_WAIT`. Zrušení plánovače se projeví na nejbližším
  heartbeatu;
- starší peer odpoví synchronně a platí pro něj původní limit 15 s;
- nedostupný nebo poškozený projekt dál vrací prázdný otisk jen pro sebe;
- selhání a pomalý výpočet zapisují logy `content_state_failed`
  a `content_state_slow` bez adres a textu výjimek.

Hranice pádu: odpověď je jen pro čtení. Nezapisuje journal, index ani
registr. Ztráta spojení nebo pád procesu ztratí jen odpověď. Další kontrola
se zeptá znovu s novým nonce. Výsledek kontroly se dál nikdy nevykládá jako
„beze změn“, pokud nepřišel celý a podepsaný.

Omezení: po dobu výpočtu drží příjemce jeden HTTP worker a linku
`peer_state`.

### Doplnění 2026-11-21: automatika ustoupí běžící odchozí synchronizaci (AUDIT-B7-T1)

Odchozí synchronizace uzlu sdílejí jeden zámek odesílání. Automatika na něj
nečekala a ruční worker čekal nejvýš 60 s. Se streamem ale jedna výměna drží
zámek i několik minut a kontrola stavu před ní také může trvat minuty. Když
uživatel mezitím spustil ruční synchronizaci, automatika narazila na zámek
a zapsala `busy` (`BlockingIOError`, „odchozí linka uzlu“) jako chybu
projektu. Ruční synchronizace za dlouhou automatickou výměnou zase po 60 s
skončila jako `busy`.

Rozhodnutí:

- Automatika bere zámek s `defer_when_busy`. Obsazený zámek vyvolá
  `OutboundDeferred` a pokus se nepočítá jako spuštěný: nezapíše stav
  `runtime`, diagnostiku, odklad opakování ani výsledek kontroly. Kolo
  automatiky skončí a další kolo to zkusí znovu.
- Těsně před výměnou automatika znovu ověří, že neběží ruční synchronizace.
  Kontrola stavu mezi tím mohla trvat dlouho.
- Ruční worker čeká na zámek až `CONTENT_SYNC_MAX_WAIT`, tedy celkový strop
  jedné streamované výměny. Čeká jen jeho vlákno na pozadí a zrušení se
  projeví do 50 ms.

Hranice pádu se nemění: odložený pokus nezapsal nic, uložená operace
v `outbound` zůstává autoritou pro další pokus.

### Doplnění 2026-11-27: dokončený přenos a odložená čtecí kontrola

Matice přepisovala `idle` / `Content synchronized` na „Stav neověřen“, pokud
poslední nezávislá automatická kontrola měla `unavailable`. V ověřeném
lokálním journalu bylo všech 11 přenosů dokončeno a žádný outbound nečekal;
UI přesto ukazovalo starší `ProjectBusy` jako hlavní výsledek ručního přenosu.

Rozhodnutí:

- U `idle` s nedostupnou nebo odloženou kontrolou UI uvádí **Synchronizace
  dokončena** a odděleně stav současného ověření změn. Neprohlašuje tím
  aktuální shodu obsahu. Diagnostika posledního přenosu, stáří automatické
  kontroly i její typ chyby zůstávají viditelné. Nedokončený či chybový
  přenos se takto neoznačuje.
- `ProjectBusy` při přípravě probe nebo čtení potvrzení či místního fingerprintu je
  pozorování `deferred`. Žádný přenos při tom nezačal, a proto se pro tuto
  čtecí kolizi nezavádí exponenciální odklad opakování. Další běžné kolo
  plánovače kontrolu zopakuje. Nevzniká vnitřní retry smyčka ani fallback
  na neověřený přenos.
- Pozorování přenáší pouze typ výjimky a allowlistovaný `busy_resource`;
  žádnou cestu, endpoint nebo text výjimky. Odložený probe má INFO událost
  `content_state_deferred`, skutečné selhání dál `content_state_failed`.
- Timeout, chybějící platný snapshot a problém během skutečného pokusu
  o přenos zůstávají `unavailable` podle původních pravidel. Zejména
  `ProjectBusy` po vstupu do synchronizace není automaticky čtecím odkladem.
  Přesné payloady a operation ID pro recovery se nemění.

Hranice pádu se nemění: pozorování automatické kontroly je pouze omezený
procesní slovník. Neuděluje grant, nepotvrzuje obsah a po restartu se ztratí.
Trvalý journal přenosů, potvrzené otisky, CAS a příjem/publikace používají
původní writer a recovery. Žádné časové limity, zámky, privacy či ověření
podepsaných výsledků se neuvolňují. Ruční přenos bez nového podepsaného
baseline může nadále vyžadovat běžné konzervativní potvrzovací kolo.

Regrese v `test_sync_fingerprint` zahrnuje skutečný ruční přenos mezi dvěma
TLS uzly, kolizi čtecí kontroly bez failure backoff, následné ověření,
skutečný timeout a busy během přenosu. Chromium test stránky sdílení
rozlišuje dokončený přenos od neověřené shody i od chybového přenosu.
