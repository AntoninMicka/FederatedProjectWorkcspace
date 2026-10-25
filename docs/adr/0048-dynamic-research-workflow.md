<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0048 — Dynamický výzkumný workflow nad doménovými autoritami

Datum: 2026-10-24. Stav: navrženo v
`F-M4-RESEARCH-WORKFLOW-01-A`. Rozšiřuje
[ADR 0047](0047-dynamic-workflow-plan-revisions.md), používá řízené hledání
podle [ADR 0045](0045-governed-automatic-search-dispatch.md) a reader podle
[ADR 0033](0033-public-source-retrieval.md) a
[ADR 0046](0046-structured-public-source-projection.md).

## Kontext

Současné hledání umí iterovat nad titulky, URL a úryvky a uživatel může každý
vybraný výsledek samostatně načíst readerem. Obecný plán verze 3 již umí
typované návaznosti a append-only `append`, `repeat` a `finish`, ale nemá
výzkumné činnosti ani planner, který by z cíle a dosavadních výsledků navrhl
další fázi. Pevná pipeline je nepraktická: někdy stačí jedno hledání, jindy je
nutné zopakovat dotaz, načíst více dokumentů, ověřit jejich společný původ,
vložit analýzu nebo skončit jako nedostatečné bez sestavení silnějšího tvrzení.

Výzkumný workflow nesmí spojit různé síťové a modelové účinky do jednoho
neobnovitelného kroku. Search, fetch, LLM analýza a projektový zápis mají
odlišné identity, journaly a okamžiky, kdy může být výsledek neurčitý.

## Rozhodnutí

### Katalog výzkumných činností

Registry dostane reviewované verze následujících činností:

1. `search.iterative-query` — existující přesný SearXNG dotaz a jeho Ollama
   vyhodnocení;
2. `source.fetch-public` — jeden přesný reader preview a nejvýše robots GET a
   GET zvoleného dokumentu;
3. `research.verify-evidence` — lokální deterministická kontrola identity,
   původu, času, hashe, adapteru a známých vazeb mezi durable výsledky;
4. `research.select-relevant` — bounded modelové hodnocení relevance, které
   vrátí pouze existující source/run ID, důvody výběru a omezení;
5. `research.analyze` — volitelná bounded analýza přes přesně vybrané zdroje;
6. `research.compose-report` — sestavení reviewovatelného návrhu zprávy s
   citacemi na dostupná source/run ID;
7. `research.plan-next` — auditovatelný planner krok, který navrhne právě
   `append`, `repeat` nebo `finish`.

Vnořené objekty každé činnosti mají vlastní uzavřený parser a limity. Obecný
typ `object` nebo `array` v action descriptoru není povolením neznámých polí.
Výstup odkazuje na doménový run a jeho digest; raw stránka ani celý providerový
response se nekopírují do autonomy journalu.

`research.verify-evidence` rozlišuje deterministická zjištění od modelových
úsudků. Shodný hostname, deklarovaný autor, časová posloupnost, content hash a
odkazy mezi známými URL lze zaznamenat jako doložené vlastnosti. Nezávislost,
důvěryhodnost, pravdivost a podpora tvrzení jsou hodnocení s uvedeným důvodem,
nikoli ověřená fakta. Prompt injection ve zdroji zůstává nedůvěryhodnými daty
a nemůže měnit policy nebo navrhovat síťový cíl.

### Profily jsou policy, nikoli pipeline

UI nabídne tři verzované výchozí profily:

- `quick-search-v1`: search, relevance a návrh zprávy nad bounded výsledky;
- `read-and-verify-v1`: search, explicitní fetch, kontrola evidence, relevance
  a návrh zprávy;
- `deep-research-v1`: stejné činnosti plus volitelná analýza a opakování
  hledání, fetch a ověření.

Profil váže allowlist akcí a verzí, permissions, privacy, execution boundary,
provider/binding volby, maximální počet kroků, cost a čas. Neurčuje povinný
počet fází ani jejich jedinou sekvenci. Uživatel může zvolit ruční nebo
automatický režim a menší počáteční limit. Profil nesmí povolit `local-only`
pro search nebo fetch a nesmí obsahovat automatickou projektovou publikaci.

Zvýšení kteréhokoli kumulativního limitu se provede výhradně přes přesný
confirmation digest nové revize podle ADR 0047. Aplikace může z ceny navržené
akce deterministicky vypočítat minimální potřebný limit, model však limit
nezvyšuje a profilové maximum nepřekročí.

### Planner a materializace dalšího kroku

`research.plan-next` je běžný viditelný krok s vlastním providerovým run ID,
Context Manifestem, cost a recovery. Dostane pouze cíl výzkumu, profil,
aktuální revizi, bounded ledger dokončených kroků, aplikačně sestavený uzavřený
seznam přesných typed kandidátů a zbývající limit. Jeho uzavřený výstup obsahuje
rozhodnutí, důvod, ID jednoho nabídnutého kandidáta nebo důvod ukončení.
Kandidátní vstup, oprávnění, privacy, execution boundary ani autoritativní změnu
budgetu model nesestavuje.

Aplikační materializátor znovu načte aktuální projektový HEAD a všechny
doménové autority. Zvolený candidate ID nahradí přesným vstupem, který aplikace
před dispatch připravila z těchto autorit. Cizí URL, neexistující source/run ID,
změněný preview,
nepovolenou návaznost nebo stale revizi odmítne. Z validního planner výsledku
odvodí stabilní proposal ID a přes AutonomyQueue uloží nejvýše jeden návrh
`append`, `repeat` nebo `finish`. Opakované zpracování stejného planner runu
vrátí tentýž návrh a nevytvoří druhý krok.

Po doménové činnosti profil smí deterministicky nabídnout nový planner krok;
ten je stále samostatnou revizí a v ručním režimu samostatně schvalovaným
krokem. Automatický režim používá živý UI lease a countdown. Pokud je nutné
zvýšit celkový limit, workflow čeká na potvrzení revize bez ohledu na režim.

`finish` rozlišuje nejméně `completed`, `insufficient`, `budget-exhausted` a
`cancelled-by-user`. Označení `completed` po sestavení zprávy znamená, že
workflow dokončil schválený proces, nikoli že jsou závěry pravdivé.

### Source ledger, analýza a zpráva

Autonomy step results tvoří bounded ledger identit a hashů. Přesné kandidáty
dalšího kroku aplikace odvozuje ze search ID, reader run ID, source ID,
adapteru/revize, URL, raw/text/projection hashů, provider run ID a hashů
validovaných hodnocení v doménových autoritách. Ledger i kandidáti jsou
odvoditelní a při každém následníku se znovu ověří. Nenahrazují `SearchRuns`,
`PublicSourceRuns`, `OllamaRuns` ani `TaskOutcomes`.

Relevance, analýza a zpráva používají existující Context Manifest a
providerový journal. Aplikace přijme jen uzavřené schema, dostupná source/run
ID a doložené citace. Neznámá citace, chybějící staging, změněný hash nebo
nevalidní modelový JSON krok ukončí známou chybou; výstup se heuristicky
neopravuje.

Sestavená zpráva je dočasný task draft. Uložení do projektového Gitu zůstává
samostatnou existující operací s přesným preview, expected HEAD, content hash,
provenance a potvrzením. Aktivace profilu, countdown ani plannerovo `finish`
nejsou souhlasem s publikací.

Chat promítá dokončená kola hledání, načtené zdroje, terminální výzkumné kroky,
potvrzené revize a závěrečnou odpověď do jediné chronologické časové osy podle
durable časů a stabilních ID. Starší záznam se kvůli novému kroku nepřepisuje
ani nevytváří druhou vnořenou historii v původním návrhu hledání. Měnit se smí
jen právě streamovaná odpověď, výslovně dočasná stavová zpráva a jedna aktuální
ovládací karta workflow; po restartu se historie znovu odvodí z doménových
journalů a task projection.

## Persistentní autority a crash boundaries

Nevznikne nový `ResearchRuns` journal. `autonomy-queue.sqlite` je autoritou
profilové policy, pořadí, revizí, planner proposalů a bounded referencí.
`SearchRuns`, `PublicSourceRuns`, providerové run stores a `TaskOutcomes`
zůstávají jedinými autoritami svých účinků.

| Hranice | Autoritativní stav a obnova |
| --- | --- |
| Pád před uložením planner runu | Plán se nezměnil a žádný návrh nevznikl. |
| Planner `dispatching` nebo provider `unknown` | Planner krok i workflow skončí `unknown`; model se automaticky nevolá znovu. |
| Provider uspěl, queue nemá planner výsledek | Adapter ověří shodné run/manifest ID a digest, načte uloženou odpověď a dokončí původní krok bez druhého dispatch. |
| Planner výsledek uložen, návrh revize chybí | Stabilní proposal ID dovolí idempotentně uložit tentýž návrh; aktuální revize a doménové preconditions se znovu ověří. |
| Fetch preview existuje, síť nezačala | `PublicSourceRuns` zůstane `prepared`; restart nic neodešle a pokračování vyžaduje původní přesný digest. |
| Fetch `dispatching` | Platí ADR 0033: výsledek je `unknown` a automatický retry je zakázán. |
| Search nebo LLM účinek dokončen, queue výsledek chybí | Pouze odpovídající doménový adapter smí doložit shodnou identitu a digest a uzavřít původní krok. |
| Zdrojový staging chybí nebo změnil hash | Zdroj je nepoužitelný; následná verifikace, analýza i zpráva se zastaví bez tichého refetch. |
| Dva planner návrhy nad stejnou revizí | Uspěje nejvýše jeden; druhý je stale a nic nepřipojí. |
| Limit nestačí na navrženou akci | Návrh čeká na přesné potvrzení zvýšeného limitu nebo workflow skončí jako `budget-exhausted`. |
| Pád po sestavení draftu před projektovou publikací | Draft zůstane reviewovatelný; projektový Git se nezměnil. Publikace má vlastní journal a receipt. |

Změna projektového HEAD, profilu, bindingu, privacy nebo dostupnosti zdroje
mezi plannerem, revizí a dispatch zastaví pokračování fail-closed. Restart
odpojí UI; automatický countdown ani potvrzení revize se neobnoví jako
implicitní souhlas.

## Reuse a odmítnuté varianty

Reuse/adaptují se `ActionRegistry`, `AutonomyQueue`, append-only revize,
`SearchRuns`, search candidate builder, `PublicSourceRuns`, strukturovaná
projekce, `ContextBuilder`, `OllamaRuns`, `TaskOutcomes`, UI lease/countdown a
stávající draft/publikační hranice. Reader dostane čistý candidate builder
obdobný search builderu; síťový writer a durable preview zůstanou jediné.

Odmítá se pevná univerzální pipeline, druhý research journal, obecný agent
framework, skrytý tool loop uvnitř jednoho handleru, crawler, automatické
otevírání všech výsledků, automatické zvýšení limitu, retry `unknown`,
heuristická oprava modelového JSON, implicitní tvrzení o nezávislosti zdrojů a
automatická publikace zprávy. Soukromá reuse inventura neposkytuje komponentu
se shodnou kombinací doménových autorit, typed revizí, privacy a recovery;
žádný její kód ani neveřejné detaily se nepřenášejí.

## Důsledky a omezení

První řez pracuje pouze s již podporovaným SearXNG, statickým HTTPS readerem a
nakonfigurovanou Ollamou. JavaScript-only stránky zůstávají nepodporované a
profil nesmí zavést browser automation jako fallback. Kvalita výběru,
analýzy a zprávy je modelový úsudek; aplikace garantuje schema, provenance,
limity a bezpečný lifecycle, nikoli faktickou správnost závěrů.
