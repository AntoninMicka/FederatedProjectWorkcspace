<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Federace — návrh M0, implementace v M5

Každý uzel má trvalé Node ID a klíč; důvěra je explicitní a nezávislá na VPN. Pro první ověření propojit desktop s jedním zvoleným serverovým peerem. Server není globální autorita všech projektů; další topologie přijde až po ověření dvou uzlů.

Synchronizují se pouze autorizované projekty. Credentials se nikdy nekopírují. Git historie sama oprávnění neuděluje. Po reconnectu ověřit aktuální oprávnění před přenosem.

Upřesnění 2026-09-13 podle [ADR 0021](docs/adr/0021-local-accounts-and-bilateral-mapping.md): účty a přihlášení jsou lokální. Desktop má jediného běžícího uživatele, web může mít více vlastních účtů. Federace mapuje kvalifikované identity až po dvou podepsaných potvrzeních; nezavádí vzdálené přihlášení ani sdílená hesla. Offline potvrzení a revokace jsou implementované, automatické doručování a datový transport zůstávají M5. ACL/rights manifest a privacy se musí přenášet s daty, zachovat původní identity a omezit účinná práva průnikem s místní politikou; chybějící ACL není automatický přístup.

Plánované M5 rozšíření přidává capability profily `same-company-same-team`,
`same-company`, `trusted-partner`, `holding-partner` a `partner` vedle výchozího
`unspecified`. Nejde o numerický žebříček ani oprávnění; profil pouze omezuje,
jaký druh grantu smí lokální verzovaná policy vytvořit. `same-company-same-team`
smí federovat identity uživatelů a jejich projektové role, nikdy však credentials,
session nebo vzdálené přihlášení. `same-company` federuje data; vzdálené uživatele
vede jen jako kvalifikované identity pro provenance a audit, nevytváří z nich
lokální účty ani nesynchronizuje jejich role. `trusted-partner` dovoluje vybraná
data konkrétně mapovaným příjemcům, `holding-partner` navíc dovoluje grant ověřené
společnosti jako celku a `partner` pouze chat a obsah explicitně odeslaný nebo
nasdílený uživatelem. `unspecified` je fail-closed.

Vazba desktopu s libovolným běžným peerem může mít nejvýše profil
`same-company`; dovoluje mapování kvalifikovaných identit, nikoli synchronizaci
účtů a rolí. Jedinou výjimkou je peer přímo založený z daného desktopu: vůči
zakládajícímu desktopu může mít `same-company-same-team`, doložené neměnnou
podepsanou vazbou původu. Takový peer nesmí mít `same-company-same-team` s žádným
dalším uzlem, nesmí tuto vazbu delegovat a ve všech ostatních vztazích se
posuzuje jako desktop. Běžný peer nelze dodatečně povýšit na tuto výjimku;
relationship policy nesmí měnit ani obcházet původ uzlu.

Vztah `trusted-partner` i `holding-partner` musí na přijímajícím uzlu určit
aktivního místního styčného uživatele. Převzatá data nejsou ostatním místním
uživatelům automaticky dostupná; styčný uživatel jim přiděluje a odnímá práva
v mezích origin ACL, privacy, povolených akcí a zákazu dalšího exportu. Určení,
nahrazení i zneplatnění styčného uživatele je verzované a auditované. Chybějící
nebo neaktivní styčný uživatel zastaví nové přidělování práv, nikoli však audit
a bezpečné odvolání již udělených lokálních grantů.

Každý neveřejný projekt/ref i organizační grant přesto vyžaduje oboustranně
schválený scope, origin ACL, `export` a místní policy; členství společnosti musí
být ověřené, časově vymezené a verzované. Stejný model chrání federovaný lidský
chat. Jeho durable zprávy zůstávají mimo projektový Git;
uložení konverzace, shrnutí, zadání či jiného podporovaného artefaktu je až
explicitní Workspace publikace s preview, provenance a zděděnou privacy.

Stavy UI: offline, připraveno, přenos, vyžaduje rozhodnutí, synchronizováno, odmítnuto. Zobrazit poslední úspěšnou synchronizaci a čekající lokální změny.

## Scénář konfliktu

1. Desktop i server mají společný commit a tutéž entitu.
2. Oba změní její název offline a vytvoří vlastní commit.
3. Desktop stáhne peer větev; aktuální lokální projekt zůstane dostupný.
4. Izolovaný merge zjistí konflikt. UI ukáže název artefaktu a obsah „společný základ“, „moje verze“, „příchozí verze“.
5. Člověk vybere verzi, upraví výsledek nebo rozhodnutí odloží. U binárního obsahu lze zachovat obě verze s novým ID kopie.
6. Validace zkontroluje obsah, metadata a vztahy. Publikovat merge commit se dvěma rodiči až po úspěchu a kontrole, že se lokální HEAD nezměnil.
7. Po publikaci obnovit index. Pád nebo odložení zachovává původní větve.

Přejmenování–úprava, změna–smazání a textově čistý, ale významově chybný merge jsou lokálně ověřeny v M0-07 níže. Obecné UI pro slučování polí entity zůstává navazující práce. Žádný automatický force push. Rozpracované lokální změny se před synchronizací musí bezpečně uložit nebo synchronizaci odložit.

PoC testuje skutečnou divergenci dvou repozitářů, obsah tří verzí, abort a zachování obou rodičů po vyřešení. Produkční izolovaný merge a síťová federace zatím nejsou implementovány.

## Ověřené scénáře M0-07

`tests/test_merge_scenarios.py` doplňuje lokální PoC podle následujícího postupu:

| Situace | Zjištění | Lidské rozhodnutí / výsledek |
| --- | --- | --- |
| Úprava zdroje proti smazání celého artefaktu | Git vrátí modify/delete konflikt; základ a upravená verze existují, příchozí obsah je smazaný | Lze abortovat a zachovat původní HEAD. Při volbě zachovat artefakt obnovit i sidecar, validovat celý pár a commitnout oba rodiče. |
| Přejmenování zdroje a změna `file` v sidecaru proti úpravě obsahu a titulku | Git dokáže změny spojit bez textového konfliktu a přesunout úpravu na nový název | Validovat nový název, stejné ID, přesné bajty a metadata. Návrat ke starému sidecaru bez odpovídajícího obsahu se odmítá. |
| Smazání zdroje proti přidání rozhodnutí, které na něj odkazuje | Obě větve jsou validní; textově čistý merge obsahuje dangling relation | Kandidátní strom odmítnout před publikací. Člověk může obnovit zdroj nebo upravit vztah podle významu; test ověřuje obnovu zdroje. |

Před publikací kontrolovat celý strom, ne pouze konfliktní řádky nebo entity. Zachování obou rodičů uchová historii rozhodnutí. Při odložení použít abort nebo izolovaný stav mimo publikovanou větev; produkční UI pro odložený konflikt ještě neexistuje.

Negativní test úmyslně obchází validační bránu a vytvoří neplatný merge commit, aby doložil, že Index odmítne rebuild, ponechá předchozí commit/řádky a při čtení nesouladu s HEAD vrátí StaleIndex. Tento krok není doporučený publikační postup. Oprava přidává nový commit a nemaže konfliktní historii.

Rozsah: řízené dočasné repozitáře, testovací Git helper s add-all a ruční orchestrace. Nejde o produkční izolovaný merge, atomickou publikaci do aktivního Workspace, síťovou synchronizaci ani oprávnění peerů. Crash boundaries aplikačních zápisů nadále drží ADR 0003; tyto testy nepřidávají novou persistentní službu.

## Pravidla publikace M0-08

[ADR 0008](docs/adr/0008-context-and-publication-contracts.md) vymezuje projektový ref, izolovaný příjem, validaci fast-forwardu i merge a CAS při změně HEAD. Autorizace síťového přenosu zahrnuje dosažitelnou historii, nikoli jen současný strom. Publikace na jednom uzlu není atomická synchronizace peerů; produkční služba zůstává M5.
