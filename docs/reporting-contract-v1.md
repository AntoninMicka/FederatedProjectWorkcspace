<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# MON-00 — Reporting kontrakt v1

Stav: **navržený normativní kontrakt k review, designed**. Autorita zadání,
reuse a recovery jsou v [ADR 0063](adr/0063-reporting-contract-and-boundaries.md).
Existující aplikace tyto doménové struktury zatím nevaliduje ani nevydává.
Následující „musí“ jsou požadavky na navazující implementaci, nikoli její popis.

## 1. Verze, identity a společné typy

Projektové záznamy mají obálku `schema: fpw-reporting-record-v1` s právě
těmito povinnými poli; žádné další klíče ani duplicitní JSON klíče nejsou
přípustné. Nullable hodnoty jsou explicitní `null`, nikoli chybějící pole.

| Pole | Typ a význam |
| --- | --- |
| `schema` | Přesně `fpw-reporting-record-v1`. |
| `type` | `ReportingTask`, `Event`, `Source`, `Story`, `EvidenceAssessment`, `EvaluationScale`, `ReportSnapshot`. |
| `entity_id` | Kanonické UUID stabilní identity napříč revizemi. |
| `revision_id` | Nové kanonické UUID každé neměnné revize; rovná se ID jejího projektového artefaktu. |
| `previous` | Seznam 0–2 `PinnedRef` stejné identity a typu. Genesis má prázdný seznam; dva rodiče znamenají výslovně posouzené sloučení větví. |
| `recorded_at`, `recorded_by` | UTC čas zápisu a UUID skutečného zapisujícího aktéra. Netvrdí identitu externího autora. |
| `privacy` | `public`, `project`, `confidential`, `local-only`; shoduje se s privacy obálky artefaktu. |
| `provenance` | Přesně `{method, inputs, run_refs}`; method je `user`, `import`, `derived` nebo `migration`, inputs seznam `Ref`, run_refs seznam sanitizovaných `{run_id, manifest_sha256, result_sha256}`. |
| `value` | Uzavřený objekt podle oddílů níže; jeho vlastní verzi určuje `value.schema`. |

Obálka artefaktu se nerozšiřuje: `artifacts/<revision_id>/metadata.json`
a jeden `record.json` odpovídají stávajícímu sidecar layoutu. Typy jsou
doménou JSON obsahu, nikoli novými `registries/*` nebo hodnotami `kind`.
Řízené revize používají `kind: document`, vydané manifesty `kind: snapshot`;
jejich neměnnost musí MON-01 vynutit i mimo vlastní editor. Obsahové raw source
artefakty zůstávají `kind: source` podle ADR 0024; reportingový Source je
samostatný deskriptor těchto bajtů. Platná obecná metadata sama nedokládají
platný reportingový kontrakt.
metadata.id odpovídá revision_id, metadata.created_at odpovídá recorded_at
a metadata.author_id odpovídá recorded_by; vlastní schema_version metadat
zůstává nezávislá na doménovém `value.schema`.

UUID z projektových dat nesmějí kolidovat; odkazy na jiný projekt se přijmou
pouze přes jeho existující autorizované připnuté předání, nikoli jen znalost ID.
Více konkurenčních tipů stejné identity je viditelný sémantický konflikt;
pozdější hodiny, pořadí souborů ani textově čistý merge neurčují vítěze.

Společné uzavřené typy:

| Typ | Přesná pole a pravidla |
| --- | --- |
| `PinnedRef` | `{project_id, artifact_id, commit_id, path, sha256}`. UUID, přesný 40/64hex Git commit, bezpečná relativní cesta pod daným artefaktem, lowercase SHA-256 přesných uložených bajtů. Žádné `HEAD`, absolutní cesty, `..` či symlinky. |
| `BatchRef` | `{artifact_id, path, sha256, at}`; `at` je přesně `same-commit`. Jen nový sourozenec v téže atomické operaci téhož projektu. Kandidátní strom musí obsah i hash ověřit; při pozdějším čtení se řeší v commitu obsahujícím záznam. |
| `Ref` | Právě jeden z výše uvedených tvarů. Vstupy hotového ReportSnapshotu jsou jen `PinnedRef`; nové souběžně vydávané Markdown bajty mohou mít `BatchRef`. |
| `DateValue` | `{precision, start, end, basis}`. precision `unknown`, `day`, `month`, `year` nebo `range`. unknown má start/end null; ostatní mají platné ISO datum a interval `[start,end)` v kalendářních dnech, basis seznam source/evidence `Ref`. |
| `Period` | `{kind, timezone, calendar_revision, start_local, end_local, start_utc, end_utc}`. kind `weekly`, `monthly`, `quarterly`, `annual` nebo `custom`; IANA timezone, přesný kalendářní předpis, časy s offsetem a stejné krajní UTC okamžiky. Interval je vždy `[start,end)`. |
| `Review` | `{decision, actor_id, at, policy_revision, note}`. decision `confirmed`, `disputed` nebo `retracted`; UUID aktéra, UTC čas, připnutá revize oprávněné policy a důvod. Samotné tvrzení importovaného JSONu nenahrazuje aplikační autorizaci. |

Časy končící `_at` a UTC hranice jsou RFC3339 UTC s `Z`, podle stávajícího
metadatového kontraktu. `DateValue` je datum, nikoli domyšlený čas o půlnoci.
Pro den je konec další den, pro měsíc/rok začátek následujícího měsíce/roku.
`range` zachovává doloženou nejistotu; nejistý interval se automaticky
nepřiřadí k jedinému bodu trendu. Neznámý čas publikace ani původní autor se
nevymýšlí. Vstupní pořadí časů se nebere jako důkaz pravdivosti; budoucí nebo
odporující časy vyvolají upozornění a review.

JSON je UTF-8, bez NaN/Infinity, NUL a duplicit klíčů. Pro serializaci
record.json a hash strukturovaných klíčů/claimů platí pevné pravidlo:
JSON s `ensure_ascii=false`, řazenými klíči, oddělovači `,`/`:`,
bez koncového newline. Textové hodnoty se před hashováním tiše nenormalizují.
SHA-256 všech obsahových Ref, manifestu a Markdownu se vždy počítá z přesných
uložených bajtů; u strukturovaného run_key/claim_sha256 z uvedené kanonické
serializace jeho definovaného objektu.
Každý record má nejvýše 1 MiB, hloubku 16 a nejvýše 128 odkazů v každém
referenčním seznamu; dlouhé evidence se dělí do navázaných revizí. Raw assety
podléhají vlastním nižším policy limitům i projektovým limitům metadat.

## 2. ReportingTask a EvaluationScale

`ReportingTask.value.schema = fpw-reporting-task-v1`; zbývající povinná pole:

| Pole | Význam |
| --- | --- |
| `title`, `goal` | Téma a přesná otázka; textové hodnoty neudělují žádné oprávnění. |
| `scope` | `{entities, categories, geographies, tags}`; čtyři seznamy neprázdných identifikátorů/textů bez duplicit. Prázdný seznam znamená bez daného filtru. |
| `source_policy` | `PinnedRef` schválené definice allowlistu, licencí, limitů a povolených capabilities. Jen nesenzitivní logické binding aliasy, nikoli konkrétní credentials či podepsané URL. |
| `calendar` | `{timezone, calendar_revision, periods}`; seznam podporovaných druhů period, pondělní začátek weekly, kalendářní měsíce/čtvrtletí/roky v dané timezone. `custom` vyžaduje explicitní hranice. |
| `selection_policy`, `scale_ref` | Připnutá pravidla výběru/deduplikace/late discovery a `EvaluationScale`. Změna politiky znamená novou revizi tasku. |
| `outputs` | `{formats, language, required_sections}`; v1 základ `markdown`, deklarovaný jazyk a pojmenované části. Prázdný přehled musí říct, že nebyla doložena významná změna. |
| `execution` | `{llm, context_policy, publication_policy}`; llm `disabled` nebo `optional`, dvě `PinnedRef` policy. Výchozí vydání je po lidském review; auto-publication vyžaduje konkrétní výslovnou per-task policy a oprávnění. |
| `retention_policy` | `PinnedRef` deklarativní retenční policy bez tajemství. |

`EvaluationScale.value` má právě `schema: fpw-reporting-scale-v1`, `title`,
`dimensions`, `comparison_policy`. dimensions má přesně maturity, relevance,
novelty, impact a confidence. Každá dimenze je seznam `{value, label, criteria}`;
první čtyři mají právě celočíselné hodnoty 0–5, confidence má právě
`insufficient`, `low`, `medium`, `high`. Neznámá hodnota je `null`, nikdy 0.
comparison_policy je `same-revision-only` nebo `explicit-crosswalk`;
crosswalk není implicitní součást této škály, ale samostatný připnutý
schválený podklad porovnání v reportu.

Podklad crosswalku má uzavřený obsah `{schema, from_ref, to_ref, mappings,
losses, review}`, schema je `fpw-reporting-scale-crosswalk-v1`, obě škály
jsou PinnedRef, mappings seznam `{dimension, from_value, to_value,
rationale}` bez duplicit vstupního páru a losses seznam přiznaných ztrát.
Hodnoty musí existovat v odpovídajících škálách a review je potvrzený
oprávněný Review. Crosswalk vysvětluje porovnání; automaticky nepřepíše
staré hodnocení ani nenahradí posouzení důkazů pro nové hodnocení.

Základní interpretace maturity: 0 koncept; 1 deklarovaná či jednotlivě
demonstrovaná schopnost; 2 opakovatelný kontrolovaný/laboratorní výsledek;
3 doložený pilot v popsaném prostředí; 4 nezávisle ověřený omezený provoz;
5 doložené opakované běžné použití v deklarovaném kontextu. Každá konkrétní
škála musí uchovat vlastní přesná kritéria. Jde o stav důkazů pro vymezené
tvrzení, nikoli univerzální certifikaci produktu nebo bezpečnosti.

Relevance, novelty a impact rovněž vyžadují šest explicitních kotev ve
škále tasku; samotné číslo bez těchto kritérií je neplatné. Confidence je
úsudek s důvodem, nikoli vypočtená pravděpodobnost. Více citací stejné
tiskové zprávy nepředstavuje více nezávislých důkazů.

## 3. Source, Event a EvidenceAssessment

`Source.value` má právě:

| Pole | Typ / význam |
| --- | --- |
| `schema`, `task_ref` | `fpw-reporting-source-v1`, přesná revize tasku (`PinnedRef`). |
| `title`, `locator`, `declared_author` | Text, sanitizované URL nebo neprůhledný lokální locator, text/null. Žádné přístupové tokeny, cookies nebo lokální absolutní cesta. |
| `source_role`, `publication_date` | `primary`, `secondary`, `community` nebo `unknown`; `DateValue` deklarovaného zveřejnění. Role sama nepotvrzuje tvrzení. |
| `imported_at`, `retrieved_at` | Aplikační čas přijetí; čas skutečného stažení nebo null při ručním/reference-only záznamu. |
| `capture_state`, `raw_ref` | `captured` s `Ref` na neměnný raw source artefakt, nebo `reference-only` s null. Hash neviděných bajtů se nevymýšlí. |
| `availability` | `available`, `changed`, `withdrawn`, `unavailable` nebo `unknown`. Změna je nová revize deskriptoru, ne přepsání raw bajtů. |
| `license` | `{identifier, terms_ref, capture_allowed, retention_policy}`; identifier text/null, terms_ref Ref/null, boolean, připnutá policy. Neznámá licence není souhlas s archivací ani publikací. |

Stejná URL s novými bajty vytváří nový raw artefakt; deskriptor naváže
novou revizi. Shodné bajty při jiném původu nejsou automaticky stejný Source.
Stažení, přesměrování, chybná odpověď nebo odebrání zdroje samo nevytváří Event.

`Event.value` má právě:

| Pole | Typ / význam |
| --- | --- |
| `schema`, `task_ref` | `fpw-reporting-event-v1`, přesná revize tasku. |
| `title`, `summary` | Doložitelné shrnutí oddělené od raw obsahu a jeho licence. |
| `event_date`, `detected_at`, `imported_at` | `DateValue` skutečné události, doložený UTC čas prvního zjištění/null při neznámém čase a aplikační UTC čas prvního přijetí Event do tohoto projektu. imported_at se při opravě nemění; recorded_at nové revize je čas opravy. Source má vlastní imported_at. |
| `categories`, `entities`, `geographies`, `tags` | Seznamy textových identifikátorů bez duplicit. |
| `sources` | Neprázdný seznam Source `Ref`; více zdrojů zachovává samostatnou provenance. |
| `claims` | Neprázdný seznam `{claim_id, text, scope, stage}`. claim_id UUID, scope text, stage `announcement`, `demonstration`, `lab-result`, `controlled-demo`, `pilot`, `limited-production`, `verified-operation` nebo `unknown`. |
| `assessments` | Seznam EvidenceAssessment `Ref` pro konkrétní claim a jeho digest. Prázdný seznam se zobrazuje jako nehodnoceno. |
| `correction_reason` | Text/null; u opravy existujícího údaje povinný neprázdný důvod. |

Změna data, významu tvrzení nebo zdrojů je nová revize stejného Event ID,
ne oprava starých bajtů. Stejný claim_id s novým textem/scope/stage má jiný
digest a staré hodnocení se na něj nepřenese. Datum bez důkazu zůstává unknown;
odhad má range a basis, nikdy se neodvodí z data souboru nebo downloadu.
Neznámý detected_at z migrace se označí v limitations reportu; dostupnost
znalosti se stále vyhodnotí přes import a připnuté revize. Zjištění se nesmí
domyslet ani z časového razítka migračního běhu.

`EvidenceAssessment.value` má právě `schema: fpw-reporting-assessment-v1`,
`task_ref`, `subject`, `scale_ref`, `ratings`, `evidence`, `limitations`,
`review`. task_ref a scale_ref jsou `PinnedRef`. subject je
`{event_id, claim_id, claim_sha256}`; hash se počítá z přesného objektu claimu
výše, aby hodnocení nemuselo vytvářet cyklický hash odkazu na Event revizi.
Při publikaci se ověří shoda s claimem z vybrané Event revize.

ratings má přesně maturity, relevance, novelty, impact a confidence; každá
hodnota je null nebo hodnota příslušné připnuté škály. evidence je neprázdný
seznam `{source_ref, locator, relation, independence_group, rationale}`,
kde locator je přesná citace/strana/timecode nebo null s vysvětlením,
relation `supports`, `contradicts` nebo `context`, independence_group
text/null a rationale důvod. limitations je seznam omezení; review je
`Review`/null. LLM vrací pouze návrh s review=null. Potvrzení, zpochybnění
nebo odvolání vytvoří novou revizi s oprávněným Review.

Materiální tvrzení označené jako ověřené musí mít potvrzené hodnocení,
konkrétní primární nebo nezávislý důkaz a uvedený scope; task policy může
vyžadovat přísnější podmínky. Community signal bez těchto důkazů zůstane
neověřený i při vysoké popularitě. Odporující zdroj se zachová a zobrazuje;
nesmí se zprůměrovat do vyšší maturity. Nová škála vytváří nové hodnocení,
staré skóre se tiše nepřepočítá. Trend mezi škálami bez explicitního
crosswalku říká „změna metodiky, nelze přímo porovnat“.

## 4. Story a deduplikace

`Story.value` má právě `schema: fpw-reporting-story-v1`, `task_ref`, `title`,
`summary`, `events`, `decisions`. events je seznam přesných Event `Ref`.
decisions je append-only seznam `{decision_id, kind, event_ids,
canonical_event_id, reverses, reason, review}`. kind je `link`, `duplicate`
nebo `retract`; event_ids jsou existující stabilní Event UUID z events;
canonical_event_id je jeden z nich jen pro duplicate, jinak null;
reverses je ID předchozího rozhodnutí jen pro retract, jinak null;
reason je neprázdný text a review je oprávněný Review.

LLM může sestavit návrh draftu; potvrzená Story obsahuje jen posouzená
rozhodnutí. Rozhodnutí duplicate určí projekční canonical ID a může vést
k nové Event revizi s více Sources, ale neodstraňuje žádný původní Event,
Source ani jejich raw bajty. Retract přidá opačné rozhodnutí v další revizi,
obnoví samostatnou projekci a zachová vydané reporty beze změny. Vstupní
eventy/zdroje ve starém reportu se nepřepíšou. Inverse vazby Event → Story
jsou dotaz nad připnutým indexem, ne nezávislá druhá evidence.

## 5. ReportRun, období a late discovery

ReportRun je node-local JSON `schema: fpw-reporting-run-v1`, uložený v
autoritativním run journalu mimo projektový Git. Má právě následující pole:
`run_id`, `project_id`, `task_ref`, `period`, `rules_ref`, `input_head`,
`knowledge_cutoff`, `baseline_snapshot`, `run_key`, `request_sha256`,
`state`, `attempts`, `candidate`, `approval`, `publish_operation_id`,
`workspace_receipt`, `deliveries`, `last_error` a `schema`.

task_ref/rules_ref/baseline_snapshot jsou PinnedRef (baseline může být null),
input_head přesný commit, period je Period a knowledge_cutoff UTC čas.
Základní run_key je hash uzavřeného objektu `{project_id, task_ref, period,
rules_ref, baseline_snapshot, knowledge_cutoff}`; input_head je připnut
prvním trvalým intentem a změna jeho bajtů pod stejným run_id je konflikt.
Rezervace jediného základního vydání navíc používá unikátní klíč
`project_id + task entity_id + task revision_id + period + rules_ref`.
Jiný cutoff, retry nebo čerstvější input_head proto nesmějí nepozorovaně
vydat druhý základní report téže periody. Nový výpočet před vydáním je
explicitní nový pokus; po vydání už pouze navázaná oprava.

attempts je append-only seznam `{attempt_id, started_at, finished_at,
outcome, input_sha256, result_sha256}`; poslední dva výsledkové údaje mohou
být null do dokončení. candidate je null nebo
`{manifest_sha256, markdown_sha256, cache_ref}`; cache_ref je neprůhledný
node-local odkaz, který neopustí uzel. approval je Review/null,
publish_operation_id UUID/null, workspace_receipt sanitizovaný potvrzený
receipt/null. deliveries je seznam `{delivery_id, intent_sha256,
idempotency_key, state, receipt_ref}`; konkrétní providerové requesty,
credentials a raw responses drží samostatná node-local autorita. last_error
je sanitizovaný text/null. To není povolení tyto JSONy vložit do Gitu.

Přípustné stavy: `prepared → collecting → draft → review → approved →
issuing → issued → delivering → completed`; ruční běh bez sběru může jít
z prepared do draft a bez externího doručení z issued do completed.
`failed`, `cancelled` a `unknown` jsou explicitní odbočky s trvalým
výsledkem, nikoli completed. Stav unknown nemá automatický nový pokus.
Změna tasku za běhu nemění intent: původní běh buď dokončí připnutou revizi
po novém ověření oprávnění, nebo se explicitně zruší. Nová revize má nový klíč.

Periody vycházejí z místního kalendáře a až pak se převádějí na UTC.
Weekly zahrnuje sedm místních dnů, nikoli vždy 168 hodin; DST může změnit
délku UTC intervalu. Report připíná obě hranice, timezone i kalendářní
revizi. MON-00 neimplementuje scheduler ani catch-up.

Výběr má dvě osy: čas události (`event_date`) a dostupnost znalosti v
`input_head` do knowledge_cutoff. Porovnává vybrané revize proti baseline
snapshotu; nestačí filtrovat pouze timestamp. Nový odporující zdroj nebo
oprava je změna i pro starší Event ID. Dosud nezahrnutá stará událost se
označí `late-discovery`, import dříve zjištěné, ale až nyní přijaté události
`late-import`. Interval unknown má samostatnou kategorii; neřadí se podle
downloadu do časové osy. Rozdílový report může být prázdný.

`last_issued_snapshot` se může posunout až po ověřeném Workspace commitu.
`last_successful_cutoff` se posune v run journalu pouze při completed,
atomicky s receiptem; pokud task vyžaduje externí doručení, čeká i na ně.
Vydané interní dílo při unknown delivery zůstává evidované, ale další pokus
nevytváří duplicitní vydání a unknown neposouvá úspěšný cutoff.

## 6. ReportSnapshot: vydání, oprava a reprodukce

`ReportSnapshot.value` má právě:

| Pole | Význam |
| --- | --- |
| `schema`, `task_ref`, `rules_ref`, `scale_refs` | `fpw-reporting-snapshot-v1` a přesně připnuté definice. |
| `period`, `knowledge_cutoff`, `input_head` | Interval a přesná hranice znalosti použité při výběru. |
| `baseline_snapshot` | Předchozí report pro srovnání nebo null u prvního vydání. |
| `events`, `sources`, `stories`, `assessments` | Seznamy PinnedRef; žádné implicitní „latest“. Vybraný event sám nenahrazuje výčet skutečně použitých zdrojů a odvozenin. |
| `selection` | Seznam `{event_ref, reason}`; reason `new`, `changed`, `late-discovery`, `late-import` nebo `context`. |
| `query`, `methodology_changes` | Query je přesně `{selection_policy_ref, scope, include_unknown_dates, include_late}`: PinnedRef, scope ve tvaru tasku a dva booleany. Výběr respektuje task/policy, period a cutoff. methodology_changes je seznam připnutých crosswalků/metodických změn; nikdy credential-bearing URL. |
| `markdown` | Ref na přesné vydané Markdown bajty. Vydání manifestu a Markdownu proběhne v jednom commitu; BatchRef odkazuje na jejich sourozence. |
| `generation` | `{mode, run_id, context_manifest_ref, result_sha256}`; mode `manual` nebo `assisted`, Context Manifest Ref/null, SHA-256 finálních Markdown bajtů. Assisted vyžaduje auditovatelné připnuté provenance; chybějící provenance nedovoluje vydání jako plně doložené. |
| `approval`, `limitations`, `reproducibility` | Oprávněný Review, seznam přiznaných omezení, `exact-inputs` nebo `limited-inputs`. |
| `corrects`, `correction_reason` | PinnedRef a neprázdný důvod u opravy; obojí null pro základní vydání. |

Každé vydání i oprava má nové entity_id a revision_id a previous=[];
vztah oprav tvoří corrects, nikoli přepsání starého vydání. Rozpracovaný
Markdown je draft v cache nebo explicitně uložený běžný projektový dokument,
nikdy ReportSnapshot s částečnými vstupy. Candidate a schválení se vážou na
přesné digesty; změna textu či vstupů ruší schválení.

Manifest neobsahuje vlastní výsledný Git commit ani svůj vlastní hash,
protože by vznikl cyklus. Vydávající commit a digest manifestu jsou ve
Workspace receiptu/run journalu a při čtení v obálce PinnedRef. Raw source
obsahuje vlastní neměnné bajty, nikoli přepisovatelný webový odkaz.
Reprodukce znamená ověření přesných vstupů, jejich verzí a vydaného textu;
u LLM se neslibuje totožné nové generování ani při stejném seed/modelu.

Correction nezpřístupňuje citlivější původní report; přístup ke každému
vydání i jeho vztahům se znovu autorizuje. Vnější publikování prochází
samostatnou explicitní policy a delivery journalem, ne automaticky jen
proto, že vznikl ReportSnapshot.

## 7. Privacy, retence a migrace

Efektivní privacy je nejpřísnější ze všech použitých vstupů, metadat,
citací, promptů, odpovědí, extrakcí a samotného výsledku:
`public < project < confidential < local-only`. Odstranění citace nebo
nahrazení jména samo nezpřístupňuje text odvozený z citlivého podkladu.
I odvozenina local-only zůstává v lokální hranici důvěry; externí LLM,
federace ani export nesmějí tuto hranici implicitně překročit.

Před sestavením kontextu i před voláním/publikací se kontroluje živý RBAC,
privacy a revize policy. Neautorizovaný výsledek nesmí vrátit ani citlivý
titulek nebo existenci skrytého zdroje. Zdroje jsou nedůvěryhodná data;
instrukce v nich nesmějí měnit task, policy, kalendář či síťové cíle.
Context Manifest není sám oprávnění a veřejný report nevznikne pouhou
změnou hodnoty privacy v JSONu. Reklasifikace je zvláštní posouzená operace
s přesným výběrem obsahu a zachovanou historií.

| Vrstva | Autorita a retenční pravidlo |
| --- | --- |
| Definice, přijaté revize a vydané reporty v Gitu | Bez automatického TTL. Historie a opravy zůstávají; ordinary delete nevykoná bezpečné odstranění starých Git blobů. |
| Raw artefakty | Archivovat jen podle licence a privacy. Bez svolení k zachování zvolit reference-only a limited-inputs; digest bez bajtů neslibuje plnou reprodukci. |
| Run/Workspace journal a receipts | Autorita pending/unknown a deduplikace. Neuklízet, dokud je operace otevřená nebo potřebná pro ochranu proti duplicitám; při archivaci zachovat ID, request digest a outcome/commit tombstone. |
| Cache, temporary download a diagnostika | Obnovitelné, s explicitním TTL/kvótou v retenční policy; smazání cache nesmí změnit stav vydání. Neúplné/poškozené bajty nejsou Source. Logy nesmějí obsahovat secrets. |
| Projektový SQLite index | Smazatelná projekce validovaného commitu. Nesoulad s HEAD je stale; rebuild nesmí rekonstruovat ztracený run journal jako údajný úspěch. |

Do projektového Gitu nikdy nepatří privátní klíče a identita uzlu,
credential values ani konkrétní node-local credential references, session
tokeny, cookies, autorizované/podepsané URL, leases, rozpracované intents,
run journal, index, raw provider responses, osobní lokální cesty ani
neschválená data mimo dovolený kontext. Node-local neznamená automaticky
nesenzitivní; lokální journal/logy rovněž vyžadují přístupová práva a retenci.

Při nutném odstranění již uložených citlivých dat nestačí tombstone ani
privacy flag: je nutný samostatně schválený purge všech kopií a historie,
záloh, cache i exportů. Není součástí MON-00; bez jeho provedení se úplné
vymazání netvrdí. Revokace ihned zastaví další čtení/export, nikoli historii.

Migrace je explicitní aplikovaná operace nad připnutým base HEAD a přesným
manifestem `schema`, `from_schema`, `to_schema`, `input_refs`, `output_refs`,
`transformer`, `losses`, `approval`, `operation_id`. Každé pole má přesnou
hodnotu: schema `fpw-reporting-migration-v1`, názvy schémat, seznamy Ref,
`{name,version,sha256}` transformátoru,
seznam ztrát, oprávněný Review a UUID operace. Výstupy jsou nové revize/ID,
nikdy přepis vydaných reportů či raw sources. Před apply se zobrazí náhled;
stejné operation_id s jiným request digestem je konflikt.

Příklad staršího záznamu s jediným `date`, jehož význam není doložen:
v1 event_date zůstane unknown; původní řetězec a bajty se připnou jako
migrační vstup. detected_at se doplní pouze s doloženou sémantikou času,
jinak zůstane null s přiznaným omezením, nikoli domyšlený z importu.
Staré skóre bez revize kritérií se nepřetypuje na v1 maturity: nové
hodnocení je neznámé, starý údaj zůstane čitelným migračním podkladem.
Neznámé budoucí schéma lze bezpečně zobrazit jako raw text, ale nelze je
spouštět, hodnotit jako v1 ani zapojit do nového vydání.

## 8. Akceptační matice návrhu

Scénáře jsou specifikací budoucích testů, nikoli tvrzením, že reportingový
runtime testy již prošel. Pro MON-00 se ověřuje jednoznačnost výsledku.

| Scénář | Očekávaný výsledek a vazba na kontrakt |
| --- | --- |
| Událost 5. ledna, zjištěná 10. března, importovaná 11. března | Tři různé hodnoty se zachovají. Březnový report ji může zahrnout jako late-discovery, lednový trend ji zpětně nepřepíše (§1,3,5). |
| Datum události není ve zdroji | DateValue unknown s null hranicemi; přehled má samostatnou kategorii. Žádné datum downloadu místo události (§1,3). |
| Offline zjištění před cutoffem, import až po vydání | Další srovnání input_head/baseline ho najde jako late-import i při starém detected_at (§5). |
| Oprava data nebo shrnutí po vydání | Nová Event revize s důvodem; vydaný ReportSnapshot pořád odkazuje na starou. Opravený report má nové ID a corrects (§3,6). |
| Stejný článek na jiné URL, jiný obsah na stejné URL | Žádné implicitní ztotožnění provenance; změněné bajty mají nový raw artefakt. Deduplikace je posouzené rozhodnutí (§3,4). |
| Marketingové demo a odporující primární zdroj | Obě evidence jsou viditelné, stadium se nepovýší na ověřený provoz a confidence nemůže skrýt konflikt (§2,3). |
| Zrušení dřívější deduplikace | Retract rozhodnutí v nové Story revizi; původní události a zdroje nezmizí, starý report se nemění (§4). |
| Maturity 3 podle jiné verze škály | Nové posouzení s přesným scale_ref; bez crosswalku nelze vykázat vzestup/pokles jen z rozdílu čísel (§2,3). |
| Public shrnutí použilo local-only poznámku | Výsledek je local-only, export i externí LLM se odmítnou bez explicitní reklasifikace (§7). |
| Starší date/skóre bez sémantiky | Nový v1 výstup přizná unknown a potřebné doplnění; původní bajty a losses zůstanou, staré vydání se nepřepisuje (§7). |
| Pád během vydání / ztracená odpověď po CAS | Recovery používá původní publish_operation_id a Workspace receipt; nejvýše jedno vydání, index se obnoví z HEAD (ADR 0063). |
| Ztráta lokálního run journalu nebo unknown delivery | Git vydání lze přečíst; nové externí pokusy se zastaví do reconciliation. Úspěšný cutoff se neposune (§5, ADR 0063). |
| Žádná významná změna, nedostupný LLM | Ruční/deterministický draft přizná nulovou změnu; optional LLM nemá implicitní externí fallback. Vydání stále vyžaduje úplné vstupy a oprávnění (§2,5,6). |
| Časový posun DST, dva workeři, rerun | Připnuté místní i UTC hranice a unikátní základní vydání. Další pokus nebo nový cutoff nesmí obejít rezervaci (§5). |
| Textově čistý merge konkurenčních revizí nebo neznámé schéma | Sémantický konflikt / odmítnutí nového vydání, žádná automatická volba vítěze (§1,7). |

Součástí návrhu jsou požadavky na navazující implementaci: striktní obsahová
a přechodová validace ve všech cestách zápisu/importu/merge, CAS/idempotence,
chybové cesty recovery a kontrola privacy. MON-01 až MON-07 se tímto
neaktivují a nezískávají automatickou akceptaci.
