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
samostatně. V lokálním PoC je doložen OllamaAdapter se syntetickým transportem.

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
