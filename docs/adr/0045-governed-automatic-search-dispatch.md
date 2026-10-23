<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0045 — Řízený automatický dispatch iterativního hledání

Datum: 2026-10-23. Stav: **přijato pro implementaci** v
`F-M3-SEARCH-03`; tento ADR je návrhový kontrakt a sám nedokládá změnu
runtime ani fyzickou akceptaci. Rozšiřuje [ADR 0008](0008-context-and-publication-contracts.md)
a [ADR 0044](0044-governed-orchestration-autonomy.md).

## Kontext

Iterativní hledání má vlastní `SearchRuns` journal, který je jedinou
autoritou search workflow, kol, přesného preview a síťového účinku.
`OllamaRuns` je oddělenou autoritou evaluatoru a `TaskOutcomes` dokončeného
tasku. Obecná `AutonomyQueue` již řeší explicitní aktivaci, budget,
manual/automatic režim, UI lease, countdown a `dispatching`/`unknown`, ale
její první verze přijímá jen předem konečný seznam kroků.

Další search dotaz vzniká až po uložení výsledku a hodnocení předchozího
kola. Předvyplněné placeholdery by proto nebyly přesným aktivovaným plánem;
celý vícekolový cyklus skrytý uvnitř jednoho handleru by zase obešel
countdown, pause a kontrolu každého dotazu. Nový search journal nebo druhý
síťový writer by vytvořil nejednoznačnou recovery hranici.

## Rozhodnutí

### Jeden reviewovaný search krok

Registry dostane jedinou verzi akce `search.iterative-query` s účinkem
`external-request`, oprávněním `external-dispatch`, povolenou privacy
`public`/`project`/`confidential`, `automatable=true` a `confirmation=none`.
`local-only` zůstá zakázané. `query.external` se nepoužije: reprezentuje jiný
OpenAI approval journal a nemá search binding, kolo ani search budget.

Vstup search kroku obsahuje pouze přesný uzavřený objekt: kořenové
`task_id`, nové `search_id`, `synthesis_run_id`, `synthesis_manifest_id`, dotaz,
účel, privacy, index a rodiče kola, přesný serialized SearXNG binding,
jazyk, zbývající search budget a otisk kandidátního preview. UI zobrazuje
právě tento objekt; zkrácený popisek není podkladem dispatch.

Handler znovu načte task, ownera, oprávnění, privacy, Git HEAD, binding a
aktuální search budget. Potom přes stávající `ChatService` připraví
`SearchRuns` kolo, ověří shodu jeho preview hashe s krokem a zavolá existující
`task_search_confirm`. Samotná fronta nikdy nevolá SearXNG ani Ollamu a
neukládá jejich výsledek jako druhou autoritu.

Pro kontrolu a editaci před dispatch vznikne z existující validace čistý
builder kandidátního preview. Ten nic nezapisuje a nepovoluje síť; stejný
kandidát se při dispatch znovu sestaví a teprve pak uloží v `SearchRuns`.
Odpadá tak mutace již připraveného kola při editaci. Manuální dosavadní
preview/confirm tok může použít stejný builder, ale jeho bezpečnostní
hranice se nemění.

### Aktivovaná policy a dynamicky materializované kroky

Pro search workflow se zavede verze 2 autonomy plánu. Aktivace váže digest:

- ownera, projekt a expected Git HEAD;
- kořenové search `task_id` a akci `search.iterative-query` v přesné verzi;
- režim `manual` nebo `automatic`;
- search budget, autonomy cost/time budget a countdown 3, 4 nebo 5 sekund;
- continuation policy `first-proposed-v1`.

Tato policy znamená: po dokončení kola lze materializovat nejvýše jeden
další krok a pouze z prvního dotazu v pořadí validovaného
`follow_up_queries`. Neuděluje modelu nové oprávnění a dovoluje nejvýše
tolik kroků, kolik zbývá v již aktivovaném search i autonomy budgetu.
Identifikátory kroku, search a synthesis runů se odvodí deterministicky z
workflow ID, indexu kola a monotónní revize návrhu; opakovaná materializace
stejné revize proto nevytvoří druhý účinek a editace dostane novou identitu.

Nový krok není volná změna plánu. Fronta jej smí transakčně připojit jen
po dokončeném předchozím kroku, bez jiného pending/dispatching kroku, se
stejným taskem, akcí, ownerem, projektem, HEAD, privacy a policy a uvnitř
obou budgetů. Uloží přesný input i jeho digest. Historie již vykonaných nebo
zrušených kroků je neměnná. Statické plány verze 1 zůstanou beze změny a
neumožní dynamické připojení.

### Countdown a uživatelské zásahy

Countdown je vlastnost konkrétního aktivovaného workflow, ne konstruktorová
globální volba. Je součástí activation digestu a každý nový automatický
krok začíná nový durable countdown. Dispatch nadále vyžaduje živý UI lease;
skrytí/odpojení UI, pause, globální pause nebo restart countdown zruší a
workflow pozastaví.

- **Review/edit:** mění pouze dosud neodeslaný krok. Starý krok zůstane v
  auditu jako `cancelled`, vznikne nový krok s novými deterministicky
  odvozenými ID a hashem, znovu se ověří policy a začne nový countdown. Již
  založený `SearchRuns` záznam se tak nepřepisuje.
- **Send now:** je samostatné explicitní potvrzení digestu právě zobrazeného
  countdown kroku v živém UI. Backend atomicky odstraní jeho `not_before`;
  obecné `advance` nesmí countdown obejít.
- **Cancel:** zruší dosud neodeslaný krok a search workflow. Stav
  `dispatching`, `succeeded` ani `unknown` nesmí vydávat za odvolaný.
- **Manual:** každý nový krok čeká na vlastní approval přesného inputu;
  continuation policy pouze určí nabídnutý dotaz. Automatic místo approval
  použije viditelný countdown.

## Crash boundaries a reconciliation

| Hranice | Autoritativní stav a obnova |
| --- | --- |
| Pád před uložením kroku | Neexistuje queue krok ani síťový účinek; kandidát lze znovu deterministicky materializovat. |
| Uložený krok / countdown, před `dispatching` | `AutonomyQueue` je autoritou; restart nebo ztráta lease jej pozastaví bez search dispatch. |
| Queue `dispatching`, `SearchRuns` záznam chybí nebo je `prepared` | Pořadí handleru dokládá, že síť ještě nezačala. Explicitní search reconciliation smí krok vrátit pouze do `paused`; nikdy jej sama neodešle. |
| `SearchRuns.dispatching` nebo `unknown` | Síťový výsledek je neurčitý. Search krok i autonomy workflow skončí `unknown`; automatický retry je zakázán. |
| Search `succeeded`, evaluator nedokončen | `task_search_confirm` obnovuje stejný `OllamaRuns` run; `dispatching`/`unknown` evaluatoru se neopakuje. |
| Doménový tok dokončen, queue krok je stále `dispatching` | Reconciliation ověří stejný task, search ID, preview hash a uložené evaluation/outcome; pouze s tímto pozitivním důkazem označí krok `completed`. |
| Krok dokončen, další ještě nevznikl | Z uložené evaluation a aktivované policy se idempotentně vytvoří nejvýše jeden další krok, nebo se workflow terminálně uzavře. |

Reconciliation je explicitní adapter mezi oběma journaly; obecná fronta
nesmí z absence chyby odhadnout úspěch. Před každým pokračováním se znovu
ověří oprávnění, privacy, binding, HEAD, search budget i UI lease. Změna
kterékoli z nich workflow pozastaví nebo fail-closed ukončí bez dalšího
síťového účinku.

## Reuse, odmítnuté varianty a hranice

Reuse/adaptují se `SearchRuns`, `SearXNGAdapter`, `OllamaRuns`,
`TaskOutcomes`, search preview validace, `AutonomyQueue`, action registry,
approval digest, UI lease a countdown. Nové jsou pouze search action adapter,
striktní v2 continuation envelope a doménová reconciliation. Soukromá
inventura neposkytuje komponentu se stejnou dvojicí autorit a crash
kontraktem; nepřebírá se z ní kód ani neveřejné detaily.

Odmítá se agent framework, obecný background worker, message queue, nový
search journal, skrytý modelový tool call, předem vytvořené placeholder kroky,
celý cyklus uvnitř jednoho handleru a automatická publikace lokálního
artefaktu. Tento ADR také nezvyšuje tříkolový search budget a neslibuje
správnost modelového hodnocení nebo nalezených zdrojů.
