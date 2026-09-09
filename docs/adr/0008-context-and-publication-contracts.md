# ADR 0008 — Backend, Role, Context Manifest a publikace

Datum: 2026-09-09. Stav: přijato jako **designed** pro M0-08. Nejde o implementované schéma, LLM adapter, RBAC ani synchronizační službu.

## Rozsah a návaznost

Zpřesňuje [ARCHITECTURE](../../ARCHITECTURE.md), [FEDERATION](../../FEDERATION.md) a [SECURITY](../../SECURITY.md). Zachovává koordinaci a crash boundaries [ADR 0003](0003-coordinated-operation.md) i rozdělení konfigurace [ADR 0004](0004-project-node-config.md). Nemění existující validátory ani schéma project.json/node.json. Kontrakty níže jsou logické v1; jejich budoucí serializace musí mít explicitní verzi, odmítat neznámé verze a nesmí potichu migrovat data.

Reuse: zachovat Workspace, validaci celého kandidátního stromu a compare-and-swap (CAS). Nové LLM kontrakty nejsou důvod přepisovat storage ani přebírat cizí adapter. Přesná serializace a její testy vzniknou v M2/M3, propojení publikace v M1/M5.

## Backend a role

| Kontrakt | Povinný význam |
| --- | --- |
| BackendDefinition | Stabilní ID, revize definice, název, typ adapteru/provider, model nebo pravidlo jeho výběru; deklarované účely (např. role execution, orchestrator chat, extraction), formáty a limity. Přenositelná definice neobsahuje secrets ani soukromé adresy uzlu. |
| BackendBinding | Lokální vazba definice na spravující node ID, endpoint, skutečný model, ověřené capabilities, dostupnost a execution boundary. Credentials pouze jako lokální opaque reference mimo Git; binding se automaticky nesynchronizuje. |
| ExecutionBoundary | `same-node`: zpracování i obsah zůstávají na původním uzlu; `trusted-federation`: konkrétní autentizovaný a povolený peer; `external-provider`: konkrétní externí služba. Localhost proxy sama nedokládá same-node. Přesměrování ani další zpracovatel nesmějí nepozorovaně změnit schválený cíl. |
| RoleDefinition | Stabilní ID a revize, verzovaná šablona instrukcí, povolené zdroje, povinné/volitelné vstupy, výstupní formát, požadované capabilities, preference modelu/backendu a omezení privacy. Projektový override má vlastní revizi a dohledatelný základ. |

Role zahrnují creator, opponent, analyst, researcher, editor, extractor, summarizer, classifier a issue-spotter. Role ani projektový override neudělují uživateli další oprávnění. Backend preference není souhlas s přenosem. Efektivní povolení je průnik aktuálních oprávnění uživatele, projektu, uzlu, role a pravidel cíle; zákaz má přednost. Stejná capability může existovat ve všech třech boundaries. Dostupnost ani nízká cena nejsou autorizace.

Usage a billing jsou dvě samostatné volitelné capabilities. Výsledek přehledu nese stav (available, unsupported, forbidden, unavailable, stale), rozsah (run/project/account), zdroj, období, čas zjištění a jednotky; peněžní údaj také měnu a rozlišení hlášené hodnoty/odhadu s verzí ceníku. Chybějící hodnota není nula. Právo generate nezahrnuje účetní souhrny. Výpadek přehledu nemění routing ani cost policy; její vlastní požadavky se stále vyhodnotí. Obnovování/cache a provider API zůstávají M3-UB-01.

## Context Manifest a odeslání

Každý LLM běh včetně lokálního má manifest. Manifest identifikuje **konkrétní připravený požadavek**, nikoli pouze seznam názvů dokumentů.

| Část manifestu | Povinný obsah |
| --- | --- |
| Identita | Verze kontraktu, manifest ID, run ID, project ID, žádající user ID, původní node ID, čas vytvoření. ID uživatele musí být navázané na ověřenou session. |
| Role a cíl | ID/revize role a override, backend definition/binding revize, požadovaný a skutečně zvolený model, execution boundary a identita cíle. Neznámou přesnou verzi provider modelu přiznat. |
| Vstupy | Projektový commit ID; pro každý zdroj entity ID, cesta, blob ID, privacy, vybraná část a transformace. Instrukce, explicitní dotaz, vybrané zprávy a dosud necommitnuté vstupy mají vlastní neměnný snapshot a hash bajtů; nepředstírají Git verzi. |
| Připravený obsah | Pořadí zpráv/rolí, přesné texty, přílohy a parametry ovlivňující generování. Uchované finální obsahové bajty a jejich SHA-256, typ/kódování a velikost; odkazy na uchované přílohy s hash a velikostí. Credentials a transportní autentizační hlavičky se nearchivují. |
| Rozhodnutí | Revize použitých politik, povolený rozsah, vyhodnocení privacy a cost policy, zahrnuté/vynechané volitelné vstupy s důvodem, potvrzení výběru a případné explicitní reklasifikace. Audit nesmí zpřístupnit identitu či obsah zdrojů, které čtenář nesmí vidět. |

Hash bez uchovaných bajtů neumožňuje rekonstrukci. Plný manifest a snapshoty jsou chráněný lokální stav mimo projektový Git, se stejnými či přísnějšími oprávněními než vstupy. Jejich retence nesmí být zaměňována s obnovitelným indexem. Redigovaný/exportovaný audit musí přiznat, že není plně reprodukovatelný. Reprodukce požadavku nezaručuje stejný výstup modelu. Schválený výstup může do Gitu nést manifest ID/hash a bezpečnou provenance; úplný manifest se nepřikládá automaticky.

Tok: `UI / volitelný orchestrator chat → application orchestrator → Context Builder / workflow → backend adapter`.

1. Aplikační orchestrátor ověří session, požadovanou akci a oprávnění. Funguje bez LLM. Chat navrhuje strukturované akce; nedostává přímý přístup ke Gitu, shellu ani oprávnění obcházet aplikační služby.
2. Context Builder kontroluje právo číst ještě před načtením zdroje, vytvoří snapshot a deterministicky vybere povolený kontext. LLM může navrhnout výběr, ale jeho vlastní vstup vyžaduje manifest a stejnou kontrolu. Nesmí být povinným předpokladem Context Builderu.
3. Vyhodnotí skutečný cíl a privacy všech vstupů včetně uživatelského dotazu. Odvozeniny dědí nejpřísnější omezení a průnik přístupů zdrojů. Shrnutí ani prompt nemění klasifikaci. Překročení limitu nesmí tiše zahodit povinný vstup; vyžaduje změnu výběru. Volitelné vynechání je viditelné v manifestu.
4. Adapter připraví finální obsah požadavku bez síťového odeslání. Po kontrole formátů/limitů se zafixují bajty a manifest; žádné skryté přidání konverzace, vzdálené přílohy nebo instrukcí po schválení.
5. Bezprostředně před odesláním aplikace znovu ověří aktuální autorizaci, binding/cíl, policy a shodu bajtů s manifestem. Lokální změny policy a přechod do odesílání musí sdílet synchronizaci. Změna relevantních podmínek znamená odmítnutí a nové posouzení, případně nový manifest/souhlas. Odvolání po skutečném odeslání nemůže stáhnout již předaná data.
6. Adapter provede pouze schválené generate; vrátí výstup, stav, dostupné usage a provider request/model ID. Výstup je nedůvěryhodný návrh. Uložení jako projektový artefakt vyžaduje validaci, oprávnění a explicitní přijetí přes běžnou zápisovou operaci.

Fallback je ve výchozím stavu zakázaný. Explicitní pravidlo může povolit náhradní backend/cíl a nákladový rozsah; i potom se sestaví nový manifest a znovu ověří celý požadavek. Uživatelský výběr backendu nepřebíjí zákaz projektu. `local-only` nikdy nejde na peer ani provider bez explicitní, oprávněné a auditované reklasifikace konkrétních dat. Pouhé potvrzení „odeslat“ nestačí.

Lokální run record rozlišuje prepared, authorized, dispatching, succeeded, failed, cancelled a unknown. Přechod dispatching se trvale zaznamená před síťovým pokusem. Pád v této fázi nebo ztráta odpovědi znamená unknown, pokud provider nedoloží výsledek; není důvod automaticky opakovat potenciálně placený požadavek. Cancel requested není potvrzené cancelled. Budoucí implementace určí vlastní crash boundaries run recordu; nelze tvrdit, že Git journal z ADR 0003 zajišťuje právě-jednou síťové volání.

## Větve a publikace při změně HEAD

Publikace zde znamená posun autoritativní projektové větve **na jednom uzlu**. Není současně síťovým odesláním ani atomickou transakcí všech peerů. Projekt má explicitně zvolený plný ref (výchozí pro nový projekt `refs/heads/main`); nepředpokládat, že každý existující projekt používá main. Detached/unborn HEAD a probíhající merge/rebase dosavadní Workspace odmítá.

Přijaté peer refs a kandidáti jsou oddělení od projektové větve. Jméno větve nedokládá identitu peeru; příjem musí navázat commit na autentizovaný přenos a povolený projekt. Cizí objekty se nejprve validují v izolovaném prostoru. Fetch nesmí sám posunout projektovou větev ani index. Přenos celého Gitu zpřístupní i historii: před síťovým přenosem musí být povolen celý dosažitelný obsah, nejen současný strom. Projekt s local-only nebo jiným zakázaným historickým obsahem nelze sdílet běžným clone/push; případný filtrovaný export je samostatná explicitní operace, nikoli přepsání historie tohoto projektu.

Zápisový záměr nese operation ID, project ID, plný ref, expected HEAD, vlastněné cesty, autora a kandidáta. Uživatelské řešení konfliktu je vázané na přesné base/mine/theirs commit IDs. Pod společným zámkem se ověří oprávnění, čistý/povolený lokální stav a celý kandidátní strom (schéma, ID, obsah/sidecar, vztahy). Fast-forward vyžaduje stejné kontroly jako merge. Divergentní historie se slučuje commitem se dvěma rodiči; konfliktní rodiče se nezahazují a force-push se nepoužívá.

Kandidát se uloží do journalu **před** CAS posunem refu z expected HEAD. Změna refu nebo HEAD znamená konflikt; kandidát nesmí přepsat novou historii. Nový pokus načte nový základ, znovu sestaví a validuje kandidáta; původní lidské schválení odlišného konfliktu nepřebírá automaticky. Pending stav se řeší recovery/explicitním vyřešením, nikoli smazáním journalu. Abort zachová vstupní historie i cizí práci.

Crash boundaries z ADR 0003 zůstávají: před CAS není kandidát publikovaný; po CAS recovery rozpozná uložený kandidát, nevytváří duplicitní commit a dokončí index/receipt. Při jiném HEAD/větvi se zastaví s konfliktem. Index lze obnovit z validovaného publikovaného commitu; pending nebo stale projekce nesmí vydávat data za aktuální. Produkční merge musí tento lifecycle adaptovat v M5; dnešní Workspace merge neimplementuje. Nejde o ochranu proti nekooperujícímu procesu měnícímu filesystem nebo Git ref mimo aplikační zámek.

## Návrhová kontrola scénářů

Tabulka je review rozhodnutí, nikoli záznam spuštěných testů.

| Situace | Očekávané rozhodnutí |
| --- | --- |
| Uzel bez LLM | Projektové operace fungují, AI akce hlásí nedostupnost. |
| Lokální Ollama se schopností sumarizace | Po autorizaci a manifestu lze použít same-node; není nutný orchestrator chat. |
| Lokální backend nedostupný, cloud fallback nepovolený | Neodeslat; nabídnout změnu dostupnosti/výběru v mezích policy. |
| Explicitně povolený cloud a project data | Odeslat pouze při oprávnění, povolené boundary, cost policy a manifestu pro tento cíl. |
| Důvěryhodný peer a project data | Důvěra nestačí: ověřit uživatele/projekt/cíl a policy, vytvořit manifest. |
| local-only vstup nebo jeho shrnutí na peer/cloud | Odmítnout; nejprve explicitní oprávněná reklasifikace. |
| Role opponent navazuje na creator | Nový běh a manifest pouze s explicitně předanými artefakty; nepřidat celou konverzaci. |
| Policy/cíl změněný po náhledu | Zastavit odeslání a znovu vyhodnotit, nepoužít staré schválení. |
| Timeout po zahájení odesílání | Unknown, žádný automatický placený retry po restartu. |
| Billing nedostupný nebo bez oprávnění | Ukázat odpovídající stav; ne nulu, neposkytnout účetní data běžnému uživateli. |
| HEAD změněný po přípravě merge | CAS odmítne publikaci; nový základ a nové posouzení řešení. |
| Textově čistý merge s neplatným vztahem | Nepublikovat; starý index zachovat a nepovažovat za aktuální vůči jinému HEAD. |
| Zakázaný obsah pouze ve staré Git historii | Odmítnout přenos dosažitelných objektů, kontrola HEAD samotného nestačí. |

Návazná akceptace: M1/V-10 integrují klientské operation ID a receipts; M2 ověří manifest, přesné bajty a zákaz fallbacku; M3/M4 role, autorizaci a hranice; M3-UB-01 přehledy; M5 publikaci, historický rozsah přenosu a revokaci. Před implementací rozpracovat tyto scénáře do testů včetně selhání a restartu. Gate review M0-09 musí nadále zohlednit otevřené M0-05/M0-06.
