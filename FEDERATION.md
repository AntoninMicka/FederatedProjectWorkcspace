# Federace — návrh M0, implementace v M5

Každý uzel má trvalé Node ID a klíč; důvěra je explicitní a nezávislá na VPN. Pro první ověření propojit desktop s jedním zvoleným serverovým peerem. Server není globální autorita všech projektů; další topologie přijde až po ověření dvou uzlů.

Synchronizují se pouze autorizované projekty. Credentials se nikdy nekopírují. Distribuce uživatelských identit a revokací vyžaduje samostatný protokol; Git historie sama oprávnění neuděluje. Po reconnectu ověřit aktuální oprávnění před přenosem.

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
