<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Reportingové návrhy — MON-03

Lokální API `spikes.reporting_proposals.ReportingProposals` doplňuje
[ruční reporting](manual-reporting.md) o volitelný modelový návrh. Rozhodnutí,
hranice a recovery: [ADR 0071](adr/0071-reporting-proposals-and-review.md).

## Spustitelná izolovaná ukázka

Z kořene repozitáře, s novým neexistujícím cílovým adresářem:

```bash
python3 -m scripts.reporting_proposals_demo /tmp/reporting-proposals-preview
python3 -m scripts.reporting_proposals_demo /tmp/reporting-proposals-accepted --confirm
```

Ukázka vytvoří syntetický uzel, task, zdroje, událost a ruční report podle
MON-01. Následně použije skutečný OllamaAdapter a jeho SQLite journal se
syntetickou odpovědí bez sítě. Výstup `generated_without_project_write=true`
prokazuje, že samotný MON-03 návrh neměnil projekt. `--confirm` navíc potvrdí
přesný návrh story v tomto izolovaném projektu a ověří, že opakované přijetí
vrátí tentýž receipt (`replay_same_receipt=true`). Nejde o volání reálného LLM,
aktualizaci běžného profilu ani akceptaci autoritativního tasku.

## Aplikační tok

1. Místní vlastník zvolí ReportingTask s `execution.llm=optional`, přesnou
   škálu a připnuté vstupy. Volající předá aktuální Authority s ověřenými
   readable_entities a schválený binding/adapter. Každá role dostane vlastní
   run_id, manifest_id a výslovný seznam input_refs; konverzace se nekopíruje.
   Aplikace přikládá úplný vnořený výstupní kontrakt a tabulku claim_subjects
   s přesnými hashi tvrzení; model je nemusí počítat ani odhadovat.
2. `prepare(...)` vrátí PreparedContext. Úplný manifest a payload uchovejte
   pro případ restartu soukromě mimo projektový Git s právy pouze vlastníka.
   Nezachovávejte credentials do kontextu. `dispatch(...)` znovu ověří práva,
   target a HEAD a používá existující backendový journal. Neúspěch se
   neinterpretuje jako prázdný nebo úspěšný výsledek.
3. `preview(...)` čte pouze úspěšný durable výsledek. Ukazuje přesné
   `request.records`, `limitations` a `assistance.audit`: instrukci, vybrané
   vstupy, model a run/result digesty. Je nutné posoudit celý tento obsah.
   Digest není souhlas; model jej nemůže sám schválit.
4. Člověk potvrdí celý přesný návrh přes `accept(prepared, operation_id,
   approval_digest, authority=..., binding=..., confirm=True)`. Nenahrazujte
   jej původním nevalidovaným JSON a nevolejte interní parametr writeru
   `_assistance` z UI/modelového vstupu. Přijaté modelové revize mají
   `provenance.method=derived`, metadata `llm-transformed` a úplné vstupní
   reference. Deduplikace je nová Story revize, nikoli přepis událostí.
5. Pro ztracenou odpověď použijte stejné operation ID a stejný obsah.
   Unknown backend nebo ztráta soukromého kontextu/journalu vyžadují dohledání
   původního výsledku. Nové UUID není způsob, jak neurčitý účinek obejít.

Role: `extractor/reporting-extractor-v1`,
`researcher/reporting-researcher-v1`,
`evidence-evaluator/reporting-evidence-evaluator-v1`. Sdílejí uzavřený
reportingový výstup; nedostávají autonomní nástroje. Volající vybírá provider
samostatně. Automatická sada používá OllamaAdapter se syntetickým transportem;
omezené živé ověření popisuje samostatná evidence níže.

Model smí navrhnout Event, EvidenceAssessment a Story. ReportingTask,
EvaluationScale, Source a ReportSnapshot mění původní ruční tok. Výstup s
neznámými poli, cizími referencemi, sníženou privacy, neplatným schématem
nebo nepravou identitou review se odmítne; modelový text se neopravuje.
Validace vztahů, task/scale identity a celé kandidátní revize probíhá také
pod zámkem původního writeru před commitem.

## Rozhodování o evidenci

- Primární marketing není nezávislé ověření provozu. Návrh může zůstat
  announcement/demonstration; modelový `verified-operation` je odmítnut.
  Provozní závěr vyžaduje samostatné lidské posouzení a ruční cestu.
- Všechny vybrané Source musí být ve zdrojích Eventu nebo evidence hodnocení.
  Odporující zdroj se nesmí potichu vynechat. Rozpor vyžaduje omezení a
  confidence nižší než high; význam vztahů kontroluje člověk.
- Community nebo chybějící dostupný podporující primární zdroj dovolují
  pouze null/insufficient confidence. Maturity a ostatní dimenze se
  neposuzují mimo přesně připnutou škálu.
- Neznámé datum zůstává unknown. Změna modelu/promptu neaktualizuje stará
  tvrzení ani starý report; nový návrh/revize má nové identity.
- Local-only vstup zůstává local-only i při odmítnutí jeho textu modelem.
  Přenos mimo same-node je odmítnut před providerovým voláním.
- Bez LLM nadále funguje původní ruční CLI. Není implicitní externí fallback.

Technické scénáře jsou v `tests.test_reporting_proposals`, včetně procesních
pádů před/po Git CAS a stejného receiptu po obnově. Reálnou kvalitu modelu,
běžný profil a lidskou akceptaci ve Workspace je třeba posoudit samostatně.

## Ověřené výsledky, 5. 11. 2026

Finální `python3 -m unittest discover -s tests -v` po poslední změně kódu,
testů a role instrukce: **1566 testů, 44 skipped, OK**, 576,313 s.
Sada zahrnuje všech 20 nových scénářů MON-03: tři role, přesnou vazbu
event/claim/hash, chybějící primární a komunitní evidenci, konfliktní zdroje,
ruční deduplikaci, změnu modelu/promptu, revokaci, local-only, privacy auditu,
unknown/retry a šest procesních pádů od prepared po completed.

Finální offline ukázka s `--confirm` ověřila návrh bez projektového zápisu
a stejný receipt při opakovaném přijetí. Kontrola Python syntaxe, místních
dokumentačních odkazů a `git diff --check` prošla. Izolované Git commity
vznikaly pouze ve fixtures/ukázce; ve zdrojovém repozitáři nebyl vytvořen
commit, push ani PR. Tyto důkazy nepotvrzují reálný model, běžný profil nebo
lidskou akceptaci MON-03 ve Workspace.

## Omezené živé ověření, 5. 11. 2026

Navazující kontrola zdrojového commitu
`8848d980d6b7fbea44ba75aca00b2b47ca7ec929` použila nakonfigurovaný lokální
`qwen3-coder:latest`, hranici `same-node` a výhradně syntetický izolovaný
projekt. Každá role dostala vlastní Context Manifest bez předchozího výstupu
jiné role. Rozpočet: nejvýše tři generační volání, timeout 60 s na volání.

| Role | Výsledek | Doba |
| --- | --- | --- |
| extractor | `unknown`, `response-timeout`; žádný automatický retry | limit 60 s |
| researcher | `valid-proposal`, EvidenceAssessment; preview prošel | 25,807 s |
| evidence-evaluator | `valid-proposal`, EvidenceAssessment; preview prošel | 25,345 s |

Oba dokončené návrhy zachovaly nevyplněná číselná hodnocení,
`confidence=insufficient` a `review=null`. Návrh researcher zachoval vztahy
supports i contradicts a výslovně přiznal chybějící provozní důkaz. Vstupy jsou
syntetické reference bez doloženého provozu; platný JSON není důkaz jejich
pravdivosti ani univerzální kvality modelu.

Původní extractor run `42d1ea0d-6caa-4913-9df9-f65e60e2c555` zůstal
v backendovém journalu jako unknown. Po timeoutu pomocná kontrola narazila
na vypršelý deadline dříve otevřené Git instance; neměnnost projektu byla
ověřena novým read-only přístupem. Další dvě role byly nezávislé původně
plánované běhy, nikoli opakování neznámého požadavku.

U všech tří běhů byly porovnány HEAD, snapshot a čistota izolovaného projektu:
generování jej nezměnilo. Žádný modelový návrh nebyl přijat ani publikován.
Manifests, payloads, raw odpovědi dokončených běhů, preview, report a SQLite
journal jsou zachovány v ignorované lokální evidenci
`.worktrees/mon-03-live-evidence/0wvctnk7/`; soupis hashů je
`evidence-sha256.json`. Běžný profil, konfigurace bindingu a autoritativní
task se neměnily. Tato první série extractor neověřila. Neznámý výsledek
není oprávněním k automatickému opakování nebo přepsání původního runu.

Po výslovném souhlasu uživatele proběhl jeden samostatný nový běh extractoru
s limitem 120 s, novým Context Manifestem a run ID
`ac83a16b-909f-461b-b69b-fec1ba34da44`. Za **25,191 s** vytvořil
`valid-proposal` typu EvidenceAssessment; preview prošel a projekt se
nezměnil. Evidence je v podadresáři `extractor-120s/`, včetně samostatného
backendového journalu a použitého harnessu. Původní unknown zůstává zachovaný.

Všechny tři role tedy vytvořily platný návrh nad jedním syntetickým případem
existující události; celkem proběhla čtyři generační volání včetně původního
timeoutu. Všechny dokončené výstupy byly EvidenceAssessment, nikoli nové
Event/Story. Tato kontrola neprokazuje obecnou kvalitu extrakce nových
událostí, autonomního výzkumu, deduplikace ani použití všech providerů.
Žádný živý návrh nebyl přijat do projektu a MON-03 nebyl automaticky uzavřen.

Zdrojová implementace ani testy se při této kontrole neměnily. Dřívější plná
sada se proto neopakovala; novou změnou je pouze tato evidence v dokumentaci.
