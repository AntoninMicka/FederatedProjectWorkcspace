<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0088 — Pracovní kontext zahájeného úkolu ve Workspace

- Datum: 2026-11-21.
- Stav: **kontrakt s implementovaným řezem A a cíleným ověřením** pro
  `PLAN-TASK-WORK-01-A`. Zdroj obsahuje službu relací, základní ovladače a testy.
  Akceptace celé dávky, pravý panel, zachytávání činností a přijetí záznamů
  zůstávají samostatné navazující části; tento stav je neprohlašuje za hotové.
- Autorita zadání: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
  snapshot `c7b61487c2ef842c272fa45ce74216c0b9667dea`, exportní revize
  `3bff4cffeed97f1e5bcc9b5a1ec7f6ffcffeb25fa710a2a4f3cfa96e67d868e8`.
  Jde o provenance tohoto návrhu, nikoli druhý živý plán.
- Zdrojový základ: `54e66fe87f69b10c849ba1bf58fc7bb05f9dabc6` po merge #152.

## Účel a hranice

Uživatel zahájí konkrétní úkol z roadmapy nebo jeho detailu. Workspace vytvoří
pracovní relaci a naváže na ni následné činnosti. Zadání a dokončení úkolu
zůstávají autoritativně v projektovém Gitu; relace zaznamenává, v jakém kontextu
uživatel pracoval. Aktivní úkol se neodvozuje z otevřeného dokumentu, vybrané
položky roadmapy, pořadí fronty ani posledního projektu.

Kontrakt stanovuje model a lifecycle pro navazující implementaci. Pravý panel
řeší B, zachycení činností C, komentované záznamy D, LLM integraci E a společnou
persistenci/recovery F. Akceptační scénáře celé dávky drží Workspace. Implementace A není důkazem jejich implementace či splnění.

## Reuse a současný stav

| Součást | Použití v navržené implementaci |
| --- | --- |
| `Projects.plan_view`, `project_task_graph` | Validovaný aktuální graf, identita úkolu, checklist a jeho zdroj. |
| `dependency_start_blockers` | Jediné pravidlo zahajitelnosti z [ADR 0067](0067-plan-work-states-and-sum.md). |
| `PlanItems.open/save`, `item_span` | Připnutí vlastního bloku a scoped zápis beze změn ostatních uzlů. |
| `ide_bridge_panel._changes`, progress review | Existující chování zápisu Probíhá; před přímým UI zápisem vyčlenit sdílený kandidátní builder, nikoli vytvářet falešnou IDE relaci. |
| `Workspace.transact`, projektový journal | Zápis pracovního stavu a recovery podle [ADR 0003](0003-coordinated-operation.md). |
| `sqlite_ownership.store_connection`, `sqlite_connection` | Privátní lokální operační úložiště, readonly čtení a bounded contention. |
| `canLeaveWorkspaceEditors` | Ochrana neuloženého editoru při navigaci; samotné zahájení nic neukládá do rozepsaného dokumentu. |
| `ContextBuilder`, `TaskOutcomes`, chat/run journály | Budoucí zachycení kontextu před účinkem a vazba výsledku v C/E/F; původní run autorita se nekopíruje. |

[Fronta podle ADR 0087](0087-owner-task-queue.md) zůstává samostatným pracovním
výběrem. Změna pořadí ani odebrání odkazu z fronty neukončuje pracovní relaci.
Relace nedostává vlastní kopii roadmapy, registr dokončení ani alternativní
pravidla závislostí. Nový agent framework či povinný LLM provider nejsou potřeba.

## Identita a datový kontrakt

Pracovní relace `work_session_id` je neměnná identita jednoho pracovního úseku.
Není totožná s IDE session, chat threadem, run ID ani přihlašovací relací.
Základ záznamu:

| Pole | Význam |
| --- | --- |
| `schema_version` | Verze lokálního kontraktu; neznámá verze se odmítne bez přepsání dat. |
| `work_session_id` | UUID vytvořené před prvním účinkem; replay stejného zahájení použije stejné ID. |
| `project_id`, `task_id` | Skutečné project UUID a stabilní roadmapové task ID; existující ID se nepřejmenovávají. |
| `node_id`, `user_id` | Serverem ověřená identita uzlu a aktuálního uživatele, nikoli důvěryhodná pole klientského requestu. |
| `window_id` | Ověřené připoutání ke konkrétnímu pracovnímu oknu/tabu; součást vlastnictví lokálního kontextu. |
| `definition_pin` | Project commit, plan revision, source artifact/path a SHA-256 přesného vlastního bloku, ověřeného postupem `PlanItems.open`. |
| `definition_signature` | Digest obsahového zadání: ID/typ, rodič, název, popis, zdroj, závislosti a uspořádané texty checklistu; bez pracovních stavů a checked příznaků. |
| `state`, `revision` | Lokální `active`, `paused` nebo `closed` a monotonní CAS revize relace. |
| `created_at`, `updated_at`, `closed_reason` | Časové a kauzální údaje lifecycle; čas sám nerozhoduje o pořadí souběžných zápisů. |
| `previous_work_session_id` | Volitelná návaznost na předchozí úsek, například po přijetí nové verze zadání. |
| `selected_checklist` | `null`, nebo index bodu v checklistu svázaný s přesným `definition_pin`; nevymýšlí nová roadmapová ID. |

Lokální ukazatel aktivního kontextu má klíč `(node_id, user_id, window_id)`
a vlastní CAS revizi. Ukazuje nejvýše na jednu aktivní pracovní relaci, nebo
je prázdný. Historie relací se vyprázdněním ukazatele nemaže.

`definition_pin` se po zahájení nepřepisuje. Aktuálně ověřený HEAD patří do
oddělené projekce `validated_head`; nový nesouvisející projektový commit sám
neznehodnocuje shodné zadání. Změna obsahového zadání nebo jeho vazeb,
rozpoznaná přes `definition_signature`,
vyžaduje reconciliaci. Změna samotného pracovního stavu nebo zaškrtnutí bodu
checklistu se projeví v aktuální projekci, ale nevytváří nové zadání a nemění
původní pin. Přepočet podpisu stále používá úplnou validaci grafu; neignoruje
změny závislostí ani textů/pořadí checklistu. Přijetí změněného zadání uzavře
původní úsek s důvodem a založí
navazující relaci s novým pinem. Dřívější činnosti si ponechají původní pin.

Okno potřebuje vlastní serverem ověřené připoutání. Pouhé zkopírované UUID
v `localStorage` nebo duplikovaném `sessionStorage` není důkaz vlastnictví.
Nový tab dostane novou identitu; explicitní obnovení původní relace ověří
uživatele, uzel a její předchozí připoutání. Jiný uživatel ani vzdálený uzel
nemůže převzít aktivní ukazatel pouhým znalým session ID.

## Přechody a uživatelské akce

```mermaid
stateDiagram-v2
    [*] --> active: Zahájit
    active --> paused: Pozastavit
    paused --> active: Pokračovat po validaci
    active --> closed: Ukončit relaci
    paused --> closed: Ukončit relaci
    closed --> [*]
```

Kontrola přístupu a stavu zadání je samostatná projekce nad lifecycle.
`needs_reconcile`, `access_revoked`, `task_missing` a `source_unavailable`
nejsou nové stavy roadmapy. Po jejich zjištění nelze kontext použít pro novou
činnost; poslední lokální relace a dosavadní důkazy zůstávají zachované.

| Akce | Předpoklady a účinek |
| --- | --- |
| Zahájit | Platný aktuální graf, oprávnění zápisu, upravitelný projekt, nedokončený konkrétní task a splněná politika zahájení. Vytvoří relaci a aktivní ukazatel; při obsazeném okně vyžaduje explicitní Přepnout. |
| Pozastavit | Aktuální vlastněná relace a její CAS revize. Uvolní aktivní ukazatel; nemění projektový stav na Odloženo a neruší již spuštěný běh. |
| Pokračovat | Vlastněná pozastavená relace, znovu ověřené právo, pin a zahajitelnost. Obsazený ukazatel se nesmí přepsat implicitně. |
| Přepnout | Explicitní zdrojová relace/revize a nový cíl. Po úspěšném zahájení cíle pozastaví původní relaci a nastaví nový ukazatel jednou lokální transakcí. Při odmítnutí cíle zachová původní kontext. |
| Ukončit relaci | Uzavře lokální pracovní úsek a uvolní jeho ukazatel. Nezaškrtne task, checklist ani dávku. Další práce na stejném tasku dostane novou navazující relaci. |
| Navrhnout dokončení | Samostatný návrh s důkazy, připnutým cílem a verzí; sám neukončuje relaci ani nemění potvrzené dokončení. Lidské přijetí používá nativní projektový writer a znovu ověří podmínky dokončení. |

Zahájení přebírá přesně `dependency_start_blockers`: přímé předpoklady jsou
Vyřešeno/Dokončeno a nejvýše jeden může být Probíhá. Potvrzení dokončení
vyžaduje potvrzené checkboxy předpokladů, nikoli jen jejich zahajitelnost.
Zahajuje se konkrétní task; u skupiny UI nabídne volbu úkolu a nezruší SUM.
Task bez checklistu je plnohodnotný cíl. Volba bodu checklistu nic neodškrtává.

Zahájení zapisuje `status: in progress` stejným scoped/nativním postupem jako
existující progress přijetí. Pokud task už Probíhá, relace vznikne bez
zbytečného projektového commitu. Nevzniká druhý uložený pracovní stav tasku.
Intent nese předúčinkový `requested_pin`. Po potvrzení progress operace se
nová relace jednou finalizuje s `definition_pin` výsledného commitu; případný
no-op použije shodný commit. Tím vlastní zápis Probíhá nezpůsobí okamžitou
neplatnost nově zahájené relace. Oba piny a nativní receipt zůstanou propojené.
Pozastavení či uzavření jedné lokální relace tento sdílený stav nezmění:
na stejném tasku může současně pracovat jiné okno nebo jiný oprávněný uživatel.

Změna otevřeného projektu ani výběru v roadmapě kontext automaticky nepřepne.
Před činností v jiném projektu se nabídne pozastavení/přepnutí, nebo práce bez
vazby na aktivní úkol. Navigace zachovává dirty guard; zrušení dialogu nesmí
přepnout ukazatel ani uložit draft. Relace se nezahajuje obdržením synchronizace,
přijetím cizího záznamu, otevřením aplikace nebo obnovením run journalu.

## Logický request, replay a souběh

Mutace nese `operation_id`, aktuální `context_revision` a podle akce vlastní
session/revizi, cílové project/task ID, `expected_head` a digest definice.
Server odvozuje user/node/window binding z ověřené autority. Pole klienta
nemohou přepnout uživatele nebo převzít cizí okno. Implementační řez zpřístupňuje toto rozhraní na `POST /v1/task-work`;
konkrétní akce a omezení popisuje [návod](../task-work-context.md).

Stejné operation ID se shodným kanonickým requestem vrátí původní výsledek
nebo umožní dokončit původní záměr. Jiné bajty pod stejným ID jsou konflikt.
Dvojklik se stejným ID nevytvoří druhou relaci; dva různé souběžné požadavky
se stejnou CAS revizí nemohou oba přesměrovat jedno okno. Jiná okna mají různé
ukazatele. Chyba či ztracená odpověď vyžaduje načtení stavu původní operace,
nikoli nové operation ID a slepé zopakování.

Lokální metadata a nedokončené záměry patří do privátního node-local
operačního úložiště mimo projektový Git. Jde o autoritativní lokální stav,
nikoli obnovitelný projektový index. Implementace A používá databázi
`.<node-filename>.task-work/contexts.sqlite` s `user_version=1`, privátními
právy a stávajícími SQLite ownership helpery. Byla potřebná již pro bezpečný
start přes lokální intent a projektový writer. Její tabulky ukládají identitu
uzlu, vlastněná okna, relace a idempotentní operace; nekopírují text zadání,
task stav dokončení ani run journal. F má rozšířit společnou reconciliaci
o činnosti a potvrzené projektové záznamy, nikoli duplikovat tuto autoritu.
Projektové záznamy a komentované přílohy naproti tomu používají Git writer.

## Crash boundaries před implementací

Start/přepnutí zasahuje lokální záměr a případně projektový Git/index/journal.
Mezi nimi není distribuovaná transakce. Lokální intent váže původní ukazatel,
přesný request, nový session ID a deterministické project operation ID.
Rezervuje CAS revizi okna; do vyřešení nedovolí nové činnosti pod nejistým
kontextem. Starší již zachycené běhy přitom zůstávají přiřazené původní relaci.

| Hranice | Recovery a viditelný výsledek |
| --- | --- |
| Před lokálním intent commitem | Žádná změna projektu ani aktivního kontextu; starý kontext zůstává. |
| Intent uložen, projektová operace ještě nezačala | Stejné ID načte původní záměr. Znovu ověřit autoritu a pin; stale/odmítnutý start se uzavře bez přepnutí starého kontextu. |
| Projektová operace `prepared` až publikace | Obnovuje původní projektový journal podle ADR 0003; nesmí vzniknout nový projektový operation ID či druhý commit. Projektový index nerozhoduje o lokálním intentu. |
| Projektový commit/index dokončen, lokální finalizace chybí | Ověřit původní receipt, zapsat výsledek a přepnout ukazatel jednou lokální transakcí. Probíhá v projektu samo o sobě nedokládá dokončený start relace. |
| Lokální relace/ukazatel potvrzeny, odpověď ztracena | Stav původní operace vrátí stejnou relaci a výsledek; replay nezaloží další relaci ani commit. |
| Restart okna nebo backendu | Nejprve dohledat pending operace. Existující relaci nabídnout k explicitnímu pokračování; neaktivovat práci v jiném okně a nespouštět model ani síťový účinek. |

Pokud během recovery zanikne oprávnění či platnost připoutání, nesmí se
z původního requestu vyrobit nové oprávnění. Již publikovaný projektový commit
se tiše nevrací zpět; lokální operace má dohledatelný blokovaný/nejistý výsledek
a čeká na oprávněnou reconciliaci. Původní kontext se nezahodí a nepřesměruje
na jiný task. Čtení obsahu respektuje nynější práva.

Lokální pause/close a změna ukazatele bez projektového účinku jsou jedinou
lokální transakcí. Zámky lokálního intentu se nedrží přes projektový writer
nebo síťové/modelové volání; mezi fázemi je trvalá rezervace s CAS. Po skončení
projektové operace se finalizuje stejný intent. Tím nevzniká cyklus lokální
DB lock → projektový lock → lokální DB lock.

## Změna zadání, práv a kontext běhu

Před zahájením, pokračováním a novou činností se kontroluje nynější autorita,
read-only stav, existence tasku a obsahový podpis vůči pinu. Start request
navíc vyžaduje přesný aktuální HEAD a digest bloku před zápisem. Nesouvisející HEAD se rozliší od změny
zadání. Neplatný graf, nedokončená projektová operace a nedostupný zdroj mají
výslovný blokující stav. Po dokončení tasku jiným aktérem se nedovolí další
práce pod starým aktivním kontextem bez vědomého založení nového zadání.

Při odebrání práv se nezveřejní cachované zadání ani podklady. Zachová se
vlastní lokální rozpracovaný draft a dohledatelná existence pracovní relace;
žádné automatické uložení/export do nepovoleného projektu nebo odeslání LLM.
Restart/odhlášení nesmí takový draft tiše přenést jinému uživateli.

C/E před účinkem zachytí neměnnou vazbu `(work_session_id, definition_pin,
project_id, task_id, node_id, user_id)` spolu s operation/run ID. Změna aktivního
ukazatele už tuto vazbu nepřepíše. Pozdní výsledek patří původnímu tasku také po
pozastavení či uzavření relace; možnost jej číst nebo publikovat se posoudí
podle nynějších oprávnění. Neuložený text není uložený artefakt.

Zahájení samo nevolá LLM a nevytváří implicitní Context Manifest s veškerým
obsahem projektu. Nový uživatelem vyžádaný běh používá existující ContextBuilder,
RBAC/privacy a přesné vstupní revize. Local-only data zůstávají v lokální
hranici důvěry. Toto je integrační závazek pro E, nikoli nová implementace
LLM workflow v A.

## Předání a požadované důkazy

Kontrakt A lze posoudit podle jednoznačné identity, stavových přechodů,
rozdílu start/complete, dvou oken a dvou uživatelů, změněného zadání,
odebraných práv a uvedených hranic pádu. Autoritativní akceptace zůstává
ve Workspace; tento dokument neoznačuje úkol ani dávku za dokončené.

Implementační ověření navazujících částí musí zahrnout:

| Scénář | Požadovaný důkaz |
| --- | --- |
| Task bez checklistu, start s jedním Probíhá předpokladem | Relace vznikne; dokončení se tím nepovolí, nejsou-li předpoklady potvrzené. |
| Dvě Probíhá závislosti, read-only, cizí uživatel/okno | Start odmítnut bez změny relace, roadmapy nebo draftu. |
| Dvojklik, souběh a ztracená odpověď | Jedna relace a nanejvýš jeden progress commit; původní operace je dohledatelná. |
| Přepnutí A → B během běhu | Nová činnost patří B, původní výsledek stále A; společný task store nevznikne. |
| Nový nesouvisející HEAD nebo běžná změna stavu/checklistu proti změně definice | První zachová původní pin a aktualizuje projekci; změna textu/závislostí/pořadí bodů vyžádá reconciliaci. Vlastní progress commit start nezneplatní. |
| Odebrání práv, smazaný task, pending projektový writer | Viditelná blokace bez úniku obsahu, přesměrování a ztráty draftu. |
| Procesový pád na každé výše uvedené hranici | Replay původních ID, bez dvojího commitu/relace a bez samovolného modelového pokusu. |
| Pause/close, restart a synchronizovaný cizí záznam | Žádné automatické dokončení tasku ani převzetí aktivního kontextu. |

Tyto případy zde mají úroveň specifikace. Budoucí úspěšný happy-path, existence
panelu nebo test mock služby nenahradí crash/souběhové testy a oba živé
uživatelské scénáře celé dávky.


## Implementační řez A

Zadání implementace bylo ověřeno nad snapshotem
`5e715a57728a0483fb784b090e03f7cbaeea47ef`, exportní revizí
`f51f66a23da1858c6d2804cff31a15187588145252182fca2e7a370e3bdddae1` a zdrojovým
HEAD `e4d7683` obsahujícím původní kontrakt. Jde o další provenance, ne změnu
historického základu návrhu výše.

- `spikes/task_work.py`: lokální store, CAS relací/okna, start/switch/resume,
  pause/close, lokální návrh dokončení, snapshot kontextu a recovery/cancel.
- `spikes/plan_progress.py`: sdílený čistý builder Probíhá, použitý i původním
  IDE progress writerem. Existující IDE pravidla pro checklist a SUM se nemění.
- `spikes/task_work_ui.py`: Zahájit úkol v detailu a základní ovladače v pásu
  nad obsahem. Není to pravý doplňkový panel B.
- `POST /v1/task-work`: ověřená identita uživatele, capability konkrétního okna
  a znovu ověřovaná projektová oprávnění; readonly status/inspect/capture mají
  vlastní HTTP read lane. Native project a lokální DB/flock zůstávají autority.

Každý rozpracovaný start drží neblokující flock podle operation ID, aby se
replay a cancel téhož intentu nemohly předběhnout. Pořadí je operation owner →
krátká lokální transakce nebo projektový writer; lokální DB se nedrží přes Git.
Přepnutí a následný lokální ukazatel se finalizují jednou transakcí. Přijetí
nové definice stejného tasku uzavře předchozí úsek s `definition-updated`.

Server ukládá pouze hash window capability. Explicitní obnovení po reloadu
ji rotuje pomocí původního důkazu a stabilního restore operation ID; staré okno
už nemůže kontext číst nebo měnit. Přesný replay ztracené restore odpovědi
vrátí stejnou novou capability, dokud okno nepřevezme další operace. Klient
uchovává pending restore request pro tento replay a nikdy se k předchozímu
oknu nepřipojuje automaticky. Aktivní relace se při převzetí pozastaví.

Testy A ověřují stavové přechody, task bez checklistu, dvě okna a uživatele,
HTTP role/revokaci, checklist bez změny definice, různé projekty se stejným ID,
immutable capture, přijetí změněné definice, stale/cancel/replay, neplatnou
verzi/unsafe store a ukončení procesu před/po native publikaci i finalizaci.
Qt průchod ověřuje také dirty editor, ztracenou odpověď, explicitní recovery,
reload a ovládání v úzké šířce. Cílené testy nejsou plná závěrečná brána dávky
ani lidská akceptace běžného profilu.

Návrh dokončení je v A lokální položka relace se stavem pending. Nepublikuje se
zatím jako komentovaný Git artefakt ani nabídka jinému reviewerovi a nepoužívá
se jako důkaz akceptace tasku. To patří do D/F. Automatické zachycení reálných
souborových/chat/LLM činností a připojení výsledků zatím implementované není;
`capture` dodává pouze základ pro C/E. Žádný LLM účinek není součástí startu.
