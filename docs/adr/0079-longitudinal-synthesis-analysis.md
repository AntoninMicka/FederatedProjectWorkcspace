<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0079 — analytická evidence měsíční a roční syntézy

Stav: implemented / cílené PoC ověření; lidská akceptace samostatně.
Rozsah MON-08-06, pokračování [ADR 0078](0078-frozen-watch-synthesis-inputs.md).

## Rozhodnutí

Nové měsíční/čtvrtletní/roční běhy sestaví z původního zmrazeného manifestu
neměnný `fpw-synthesis-analysis-v1` s engine `longitudinal-evidence-v1`.
Jde o strukturovanou analytickou evidenci, nikoli zřetězení výňatků reportů.
Každý výstup má vlastní report.instructions; volitelná report.analysis přidává
revision, input_level (weekly/monthly/mixed), explicitní case_studies a model
Target. Konkrétní vazby stále určují vstupní sledování; explicitní input_level
musí souhlasit s periodou jejich zmrazených definic.
Roční varianta přes měsíce i přímo přes týdny používají stejný kontrakt.

Analýza rekurzivně čte vybrané manifesty, vydání a jejich původní Event,
EvidenceAssessment, Story, SourceFinding a Source piny. WatchDefinition
deklarace případových studií mají vlastní piny a stav se nepřebírá odhadem
z textu. Zahrnou se i původní verze událostí/hodnocení a jejich přesné škály.
Native Reporting `records` zůstává jediným rozlišením skutečného reporting
záznamu od obyčejného JSON či zachyceného raw exportu. Source pojmenovaný
record.json se nesmí stát událostí jen kvůli obsahu nebo názvu.

Výběr je bounded: 1024 uzlů a ledger nejvýše 1 MiB. Každý pin musí být
dostupný, neporušovat aktuální privacy a ležet pod původním input HEAD/cutoff;
výjimkou je samotný kontrolní input manifest z ADR 0078. Case dokument není
oprávnění číst nové aktuální bajty místo původního pinu. Chybějící/revokovaný
obsah je chyba, nikoli domyšlená kompletní evidence.

## Identita, srovnatelnost a nejistota

Událost je počítaná podle stabilního entity ID. Potvrzené Story duplicate
decisions mohou sjednotit aliasy; retraction je zachována a zruší účinek
starého rozhodnutí. Konfliktní či cyklická dedup rozhodnutí selžou.
Shodný titulek nebo modelová podobnost nesjednocují identity automaticky.
Počet zmínek ve vydáních je samostatná informace, nikdy počet nezávislých důkazů.
Při shodném recorded_at určuje pořadí verzí ancestry, nikoli UUID.

Původní a aktuální tvrzení, scope, stupeň, datum a hodnocení jsou oddělené.
Maturity rozdíl vede k progress/stagnation/regression pouze ve stejném
claim hashi, stejné revizi škály/metodiky a jedné assessment chain, s výslovně
potvrzeným review a dostupným primárním/nezávislým support podle existujícího
Reporting kontraktu. Změna textu/scope/stupně nebo škály není číselný pokrok.
Metodika zahrnuje i scope a explicitní selection/evaluation revize zdrojové
definice. Periodické run-rules normalizují tyto části; jiný manifest stejného
zadání není sám nová metodika. U obecného ReportingTask zůstávají připnuté
policy identity/hash součástí porovnání. Neznámá metodika neprokazuje pokrok.
Více assessment identit se nezmění na latest-wins. Contradicts zůstává
explicitní a nevede k pozitivnímu potvrzení. Neověřené SourceFinding zůstává
signálem; vysoká relevance ani opakované shrnutí z něj nevytváří Event.

Přebírají se i mezery uvnitř upstream souhrnů, původní limitations,
correction refs a pozdě zaevidované podklady. Unknown datum se neodvozuje
z importu/záznamu. Reference-only zdroje ponechávají limited-inputs.
Případové studie zachovávají deklarace včetně jejich definition pinů:
ongoing, stalled, abandoned, completed nebo unknown. Completed je deklarace
uživatele, nikoli automatická akceptace projektu; slepá větev se neodhaduje
z absence zprávy nebo z chybějícího reportu.

## Volitelné modelové pokračování

report.mode=llm vyžaduje přesný Target v report.analysis a explicitní
ModelExecution(adapter,binding,authority) aplikačního volajícího.
Samotná definice/synchronizace nemůže aktivovat model. ContextBuilder dostane
ledger, vlastní definici, manifest a všechny zvolené podklady uzávěru, včetně
původních zdrojů. Všechny vyžadují aktuální read authorization; platí původní
privacy boundary a externí approval backendu. Neexistuje provider fallback,
implicitní search ani nahrazení metody deterministickým výstupem při chybě.

Role analyst / monitoring-synthesis-analyst-v1 vrací uzavřený JSON návrh:
overview a annotations nad existujícími claim IDs. Anotace musí ponechat
přesný trend aplikace a odkazovat jen na její evidence_refs. Model nemůže
přidat rating, změnit škálu nebo vytvořit Event/EvidenceAssessment.
Volný overview/explanation je označený modelový návrh k review; syntaktická
validace není důkaz pravdivosti prózy. Autoritativní evidence/matrix zůstává
v reportu vedle návrhu a ve vydání se automaticky nepovýší na ověřený fakt.

## Persistence, crash boundaries a recovery

1. Výpočet ledgeru je čisté čtení zmrazených pinů. Uložení ledgeru používá
   původní Workspace transaction a deterministický operation ID/receipt.
   Pád před/po ref zopakuje původní transakci, nikoli výběr nových zdrojů.
2. Před provider prepare/dispatch se celý PreparedContext (manifest + payload)
   zmrazí přes nový `bind_assistance_context` ve stejném FULL scheduler
   journalu. Jde o aditivní member původního run JSON, bez nové DB/tabulky.
   Privátní context se nevrací v public run projekci a nesynchronizuje se.
3. Provider effect vlastní původní adapter/run journal. Model run ID se
   odvozuje od původního report intentu, **nikoli od nového pokusu**.
   Unknown ani dispatching nelze obejít scheduler retry nebo jiným modelem.
   Změněná session/authority/model/instruction selže, neobnoví se odhadem.
4. Po succeeded backendu lze opět použít přesný durable výsledek bez nového
   volání, i když předchozí proces skončil před renderem/auditem. Opět se
   ověří současný přístup, target, role, manifest hash a vazba na ledger.
   Stale nesucceeded kontext nesplní původní HEAD guard pro nový dispatch.
5. Audit s role/target/instruction, sanitized context, výsledkem a hashi se
   uloží původním `_doc`/Workspace receipt. Session/node/policy authority
   zůstávají node-local. generation pin váže audit a render hash.
6. Review/publication pokračují původním ReportingScheduler. Native semantic
   validator znovu sestaví ledger ze zmrazených bajtů, porovná jeho obsah a
   ověří modelový kontrakt i výsledný render. Pád před/po Git CAS zůstává pod
   původním journal/receipt/index recovery; lidské vydání je samostatný krok.

Neúplný collecting lease přejde do unknown; potřebuje původní explicitní
reconciliation. Již úspěšný provider run se při potvrzeném pokračování čte,
není znovu odeslaný. Původní omezení issuing/revokace z ADR 0078 zůstává.
Context má původní 16 MiB limit, jeho privátní serializace limit 8 MiB;
větší výběr selže bez skrytého krácení. Výstup má stávající reporting limity.

Evidence refs analýzy rozšiřují původní trace/freshness. Historické verze,
které ledger již výslovně používá, se neoznačují za nové opravy. Nový
následník mimo tento uzávěr může označit výstup potentially_stale; původní
výstup se nepřepíše. Staré vydání bez analysis_ref se automaticky nemigruje.
Při budoucí změně engine kontraktu je nutné zachovat čtení jeho původní verze.

## Reuse a rozsah

Reuse/adapt: Reporting records/Story canonical_events, WatchSynthesis manifest,
Workspace receipts, scheduler run/lease/journal a ContextBuilder/RoleRegistry/
existující provider adapter. Nové jsou ledger, renderer a bounded JSON role.
Odmítnuto: parsovat volnou prózu jako potvrzení, automatické nové hledání,
nový writer/journal/provider framework nebo automatická akceptace.
Použití: [analytická syntéza](../synthesis-analysis.md).
