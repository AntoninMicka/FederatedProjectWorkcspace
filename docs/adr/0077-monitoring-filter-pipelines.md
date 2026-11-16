<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0077 — verzované filtry a explicitní LLM pokračování

Stav: implemented; cílené PoC ověření, lidská akceptace samostatně.
Rozsah: MON-08-04, pokračování [ADR 0076](0076-recurring-rss-findings.md).

## Rozhodnutí

WatchDefinition.selection může aditivně obsahovat uzavřenou `pipeline`
`fpw-monitoring-pipeline-v1`. Původní definice a režimy capture-only/queue-all
zůstávají platné. Nový režim RSS bindingu `pipeline` vyžaduje explicitní
schválení přesného definition pinu stejně jako dosavadní sběr.
Volný text instrukcí se nepředstírá jako provedený filtr.

Posloupnost nejvýše 16 pojmenovaných kroků obsahuje restrict, keywords,
regex, dedup, volitelně jedno llm, assessment a závěrečný handoff.
Levné kroky musejí předcházet LLM; LLM bez levného předfiltru nelze uložit.
Restrict přijímá kanály, explicitní jazyk a požadovaná pole. RSS SourceItem
dosud jazyk nedeklaruje; chybějící jazyk neprojde jazykovým omezením.
Žádná heuristika ani model jazyk v tomto kroku nedoplňuje.

Keywords kombinuje ALL, ANY a NONE nad explicitními poli. Regex má pole,
search/fullmatch, negaci a whitelist příznaků. Jeden izolovaný Python proces
zpracuje celý regex krok, s wall timeoutem 750 ms, CPU limitem 1 s a AS limitem
192 MiB. Nejvýše čtyři regex kroky, 512 znaků vzoru a 4 MiB položek omezují
celý běh; limit se nenásobí počtem položek. Neplatný, přerušený či příliš
náročný regex vytváří vysvětlený error, nikdy prázdný úspěch nebo výběr.
Nepoužívá se vlákno s nezrušitelným stdlib re ani nová závislost.

Výsledky nesou engine revision, přesnou pipeline/hash, hash vstupní dávky,
hash dedup historie, input HEAD a průchod pravidly. Definition pin a původní
raw zachycení umožňují rekonstruovat tehdejší vstupy; staré nálezy a definice
se nepřepisují. Dedup je volitelný výběrový krok a nemaže původní položky.
Je oddělený od GUID/URL aliases deduplikace samotného sběru. Historie dedup
je omezena na 5000 aktuálně vybraných nálezů téhož watch, napříč vstupy.
Nová pravidla automaticky znovu nezařazují nezměněné již uložené položky.

## Hranice persistence a obnova

Pro sběr/filtry platí původní FSM, journal a Workspace CAS z ADR 0076.
Filtr nemá síťové účinky. Pád při výpočtu před uložením plánu jej může znovu
spočítat ze zachyceného XML; GET se neopakuje. Po uložení plánu se publikuje
přesně zmrazený výsledek. Capture i trace jsou v jedné Workspace transakci;
Git ref, journal a rebuild indexu nemají druhého writera. Regex error uloží
failed nález a dokončí poll, ostatní bindingy pokračují.

LLM krok sběrač sám nespouští: nález čeká v captured/not-evaluated a trace
uvádí explicitní LLM pokračování. `MonitoringEvaluation` připraví přesné
WatchDefinition a SourceFinding jako dva autorizované ProjectInputs,
vlastní scope a TaskInstruction přes ContextBuilder. Role classifier,
extractor či evidence-evaluator má samostatnou monitoring revizi; instrukce
i modelový Target jsou součástí pravidel. Výběr jiného modelu/binding revize
selže; žádný fallback není implementovaný. Dispatch znovu ověří autoritu,
privacy, aktuální HEAD a nesupersedované vstupy.

Síťový účinek vlastní původní backend run journal: prepared/dispatching,
succeeded/failed/unknown a jeho existující no-retry recovery. Není nový LLM
journal ani druhý worker. Pád po dispatch bez výsledku vyžaduje původní
explicitní reconciliation. Úspěšný výsledek lze opakovaně prohlížet bez
dalšího modelového volání. Chyba JSON či schématu nevybere náhradní metodu.

Preview nepublikuje. Explicitní accept s approval digestem uloží nástupce
SourceFinding a `assistance.json` původním Reporting.apply/Workspace writerem.
Audit obsahuje exact context projection, instruction, role/target, pipeline,
levný trace, finální kroky, výsledek a run/manifest/result hash. Session,
node identity a autorizační policy zůstávají node-local podle ADR 0071.
Nález má evaluation_ref na audit i run_refs; metadata zůstávají external.
Pád před ref i po ref obnoví původní transakci a receipt; opakovaný accept
stejného operation ID nevytvoří druhý commit ani LLM volání.

Relevance a potenciální význam jsou nezávislá nullable skóre. Bez samostatných
důkazů smí source-only výstup uvádět jen unverified/insufficient trustworthiness
a musí uvést omezení. Assessment interpretuje tyto oddělené rozměry;
handoff je kandidát pro následující reporting, nikoli vydání zprávy,
Event nebo potvrzení průlomu. Syntéza a úplný editor definice patří do
dalších úkolů aktuální dávky.

## Reuse

Reuse/adapt: SourceItem, WatchDefinition revision/pin, RSS publication plan,
Reporting assistance audit, ContextBuilder, RoleRegistry a backend runs.
Nový je malý uzavřený vyhodnocovač a resource-limited regex podproces.
Obecný workflow framework, automatické LLM smyčky a kopie writer/journal
jsou odmítnuté; pro tento rozsah nepřinášejí potřebnou hranici účinků.
API, ukázka a omezení: [monitoring-filters](../monitoring-filters.md).
