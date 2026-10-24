<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0047 — Typovaný katalog a append-only revize dynamického plánu

Datum: 2026-10-24. Stav: **navrženo** v
`F-M4-DYNAMIC-WORKFLOW-01-A`; typovaný katalog a validátor návazností jsou
implementované v bodu B a append-only revize plánu i limitu v bodu C.
Orchestrace a sdílené UI jsou implementované v bodu D; závěrečná recovery
akceptace patří do bodu E téže dávky. Rozšiřuje
[ADR 0044](0044-governed-orchestration-autonomy.md)
a zobecňuje search-only continuation z
[ADR 0045](0045-governed-automatic-search-dispatch.md).

## Kontext

`ActionRegistry` dnes uzavírá identitu a verzi akce, permissions, privacy,
účinek, povinné názvy vstupů, maximální cost a confirmation. Nevyjadřuje ale
typ výsledku, předpoklady ani kompatibilní následníky. `AutonomyQueue` umí
statický plán a search-specifickou verzi 2, která připojí jen další
`search.iterative-query`. `step_revisions` uchovává nahrazený neodeslaný search
krok, není však historií celého plánu ani potvrzené změny jeho limitu.

Obecný dynamický workflow potřebuje po dokončení kroku rozhodnout, zda
přidat kompatibilní činnost, zopakovat činnost s novým přesným vstupem, nebo
skončit dříve. LLM ani doménový handler nesmí sám měnit durable plán,
permissions, privacy, execution boundary nebo limity. Celkový limit je horní
mez, nikoli požadovaný počet kroků, a dokončovaný bounded krok se při jejím
dosažení nepřerušuje.

## Rozhodnutí

### Typovaný katalog činností

Action descriptor verze 2 rozšíří dosavadní bezpečnostní metadata o:

- uzavřené, bounded schéma vstupu a výstupu; pouze explicitně podporované
  skalární typy, objekty a bounded seznamy, bez volného schema fallbacku;
- pojmenované předpoklady, které musí validátor doložit z dokončených kroků
  nebo z aktuálního aplikačního kontextu;
- allowlist verzovaných následníků a mapování požadovaných výstupů
  předchůdce na vstupy následníka;
- explicitní execution boundary. Následník nesmí rozšířit permissions,
  oslabit privacy ani přejít na širší hranici vykonání, pokud taková
  hranice nebyla součástí aktivované policy.

Descriptor zůstá reviewovaným statickým souborem a jeho digest se ověřuje
před každým dispatch. Verze 1 zůstane čitelná pro existující workflow, ale
nebude použitelná jako obecný dynamický následník bez explicitního adapteru.
Validátor odmítne neznámou akci nebo verzi, neznámý typ, chybějící výstup,
nepovolenou hranu i nesplněný předpoklad. Neprovádí typovou konverzi ani
heuristickou opravu modelového návrhu.

### Obecný dynamický plán

Nová obecná verze plánu oddělí:

1. neměnnou aktivovanou policy — owner, projekt a HEAD, režim, privacy,
   permissions, execution boundaries, katalog/verze akcí a countdown;
2. kumulativní limit `max_steps`, `max_cost_units` a `max_seconds`;
3. append-only revize konkrétního plánu a dokončenou historii kroků.

Každý návrh změny je uzavřený objekt s `proposal_id`, očekávanou revizí
a digestem plánu, druhem `append`, `repeat` nebo `finish`, auditovatelným důvodem,
přesným novým krokem nebo důvodem ukončení a případným novým limitem.
`repeat` nikdy znovu nepoužije identitu ani approval původního kroku; vytvoří
nový krok s vlastním vstupem a digestem. `finish` pouze terminálně uzavře
plán a neoznačí neprovedené kroky za dokončené.

Model nebo doménový adapter smí návrh pouze vrátit. Obecný planner adapter ho
normalizuje do uzavřeného schématu, ale nezapisuje. `AutonomyQueue` v jedné
`BEGIN IMMEDIATE` transakci znovu ověří vlastníka, očekávanou revizi,
dokončení závislostí, katalogovou hranu, vstup/výstup, policy a zbývající limit.
Teprve potom zapíše novou revizi a případný krok.

Změna uvnitř již aktivované policy a limitu může být v automatickém režimu
aplikována deterministickou frontou; samotný modelový návrh není autoritou.
Každé zvýšení kumulativního limitu nebo rozšíření policy vytvoří stav
`awaiting-revision-approval`. UI musí zobrazit starý a nový limit, přesnou změnu,
důvod a digest. Potvrzení je samostatné od countdownu, approval doménového
účinku i původní aktivace a atomicky sváže novou revizi s novým limitem.
Snížení limitu nesmí být nižší než již spotřebovaná hodnota.

Pokud už `max_steps` nebo cost nestačí na další navržený krok, workflow
zůstane bezpečně zastavený s vysvětlením. Běžící krok dokončí svůj bounded
handler; limit se vyhodnotí před další revizí nebo dispatch. `max_seconds` je
deadline pro zahájení dalšího kroku, nikoli asynchronní přerušovač handleru.

### Persistentní autority

`autonomy-queue.sqlite` zůstane jedinou node-local autoritou pro aktivovanou
policy, revize plánu, jejich confirmation digesty, pořadí kroků, stav fronty a
spotřebu limitu. Nová tabulka revizí bude append-only; aktuální revize je
monotónní ukazatel ve workflow řádku. Existující `step_revisions` zůstane
auditem nahrazení neodeslaného kroku a nebude vydávána za historii plánu.

Doménové journaly (`SearchRuns`, `OllamaRuns`, `RoleWorkflows`, Workspace
journal a další reviewované executory) zůstávají jedinou autoritou vlastního
účinku. Queue ukládá jen bounded výsledek nebo referenci a pro dokončení
`dispatching` používá explicitní doménovou reconciliation. Nikdy neodvozuje
úspěch z absence chyby a nikdy sama nezapisuje projektový artefakt.

### Crash boundaries a recovery

| Hranice | Autoritativní stav a obnova |
| --- | --- |
| Pád před uložením návrhu | Durable plán se nezměnil; stejný kandidát lze znovu navrhnout, ale nemá žádný účinek. |
| Návrh uložen, před validací nebo potvrzením | Návrh zůstane neaktivní. Po restartu se znovu ověří katalog, policy, HEAD, předchozí revize a limit; nic se samo nepotvrdí. |
| Pád v transakci revize | SQLite atomicky zachová buď starou revizi, nebo celou novou revizi včetně limitu a kroku; poloviční revize není viditelná. |
| Revize uložena, krok dosud neodeslán | Queue je autoritou. Restart odpojí UI a workflow pozastaví; countdown ani approval se neobnoví jako implicitní souhlas. |
| Krok `dispatching` | Platí ADR 0044/0045: bez pozitivní doménové reconciliation je stav `unknown`, bez automatického retry a bez další revize plánu. |
| Doménový účinek dokončen, queue výsledek chybí | Pouze doménový adapter smí doložit shodnou identitu a digest; queue pak uzavře původní krok, nevytváří nový účinek. |
| Dva souběžné návrhy | Uspěje nejvýše jeden s aktuální očekávanou revizí. Druhý se odmítne jako stale a musí být sestaven z nové projekce. |
| Limit vyčerpán po dokončení kroku | Další dispatch nevznikne. Early finish je možný; zvýšení limitu čeká na přesné potvrzení nové revize. |

## UI projekce

Sdílené UI rozšíří existující kartu fronty; nevznikne paralelní editor
workflow. Projekce zobrazí aktuální revizi, lineární audit kroků a jejich
závislosti, stav a důvod navržené změny, její dopad na policy/limit a zbývající
steps/cost/time. Tlačítko potvrzení revize bude dostupné jen pro přesný
aktuální digest v živém UI. Pause, cancel, doménové approval a countdown
zůstanou oddělené akce.

Implementovaná aplikační hranice nepřebírá preconditions z klientského
požadavku. Znovu ověří aktuální projektový HEAD a podporované doménové
preconditions proti jejich autoritám, než návrh předá journalu. Sdílená karta
zobrazuje aktuální revizi, důvod, změnu budgetu, kapacitu kroků, cost a čas;
zvýšení limitu lze potvrdit jen uloženým digestem po obnovení živého UI.
Dynamický plán po dokončení posledního kroku nezíská implicitní stav
`completed`: čeká na další platnou revizi nebo explicitní `finish`.

## Reuse a odmítnuté varianty

Reuse/adaptují se `ActionRegistry`, `AutonomyQueue`, activation/approval
digesty, SQLite `BEGIN IMMEDIATE`, UI lease a countdown, `step_revisions`,
search continuation a explicitní doménové reconciliation. Search verze 2
zůstane kompatibilním specializovaným tokem a bude postupně převedena přes
obecný validátor, nikoli souběžně přepsána.

Odmítá se nový agent framework, obecný background worker/message queue,
mutable přepis jediného JSON plánu bez historie, automatické zvyšování limitu,
retry stavu `unknown`, typová heuristika a druhý doménový writer. Soukromá
inventura neposkytuje komponentu se stejným approval, privacy, journal a
recovery kontraktem; nekopíruje se z ní kód ani neveřejné detaily.

Konkrétní research akce, fáze a jejich profily nejsou součástí tohoto
rozhodnutí; patří do `F-M4-RESEARCH-WORKFLOW-01`.

Realistický read-only průchod přes revize, restart před potvrzením limitu a
kontrolu nezměněného projektového HEAD popisuje
[akceptační checklist dynamického workflow](../dynamic-workflow-acceptance.md).
