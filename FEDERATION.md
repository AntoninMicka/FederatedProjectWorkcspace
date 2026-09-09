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

Samostatně ověřit přejmenování–úprava, změna–smazání, změnu různých polí téže entity a textově čistý, ale významově chybný merge. Žádný automatický force push. Rozpracované lokální změny se před synchronizací musí bezpečně uložit nebo synchronizaci odložit.

PoC testuje skutečnou divergenci dvou repozitářů, obsah tří verzí, abort a zachování obou rodičů po vyřešení. Produkční izolovaný merge a síťová federace zatím nejsou implementovány.
