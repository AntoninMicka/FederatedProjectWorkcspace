<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08-06 — měsíční a roční analytická syntéza

Nové měsíční/čtvrtletní/roční běhy používají analytický ledger nad přesnými
vstupy [MON-08-05](watch-synthesis.md). Výsledek odděluje původní/aktuální
tvrzení, scope, stupeň, datum, rating a škálu; neskládá jen výňatky Markdownů.
Vlastní analytické zadání zůstává v `report.instructions`. Událost převzatá
přes několik vydání se počítá jednou podle identity nebo potvrzeného Story
dedup rozhodnutí. Zmínky se nevydávají za další nezávislé důkazy.

Volitelné nastavení `WatchDefinition.report.analysis`:

```json
{
  "revision": "annual-analysis-1",
  "input_level": "monthly",
  "case_studies": [],
  "target": null
}
```

Vazby inputs nadále explicitně vybírají konkrétní sledování. Monthly vstupní
úroveň je vhodná pro roční osnovu; weekly umožní přímý roční přehled z týdnů.
Mixed dovolí více úrovní/nálezy/explicitní externí capture. Explicitní
weekly/monthly nastavení musí souhlasit s periodou připnutých upstream
report definic. Bez tohoto bloku stávající deterministické definice fungují;
ledger zaznamená skutečné úrovně z jejich zmrazených vazeb.

Každá case_studies položka má `{ref: PinnedRef, status, note}`. Status je
ongoing/stalled/abandoned/completed/unknown. Jde o výslovnou deklaraci nad
pinem, nikoli odhad z textu ani automatické uzavření úkolu. Převzaté deklarace
z upstream definic mají vlastní origin piny; odlišné historické deklarace
se neschovají za jeden nepodložený latest-wins stav.

## Co může evidence doložit

- Pokrok/stagnaci/regresi jen při srovnatelném claim hashi a stejné škále,
  jedné assessment chain a výslovně posouzeném dostupném support.
- Změnu metodiky nebo tvrzení jako nesrovnatelnou změnu, nikoli číselný pokrok.
- Rozpory, chybějící data, multiple assessments a neověřené signály bez
  automatické preference či potvrzení průlomu.
- Původní zdroje i při ročním vstupu přes měsíce: analýza sestupuje přes
  manifesty k týdnům, událostem, hodnocením a zachyceným bajtům.

Marketing, modelový návrh a vysoká relevance nepřidávají potvrzený Event.
Datum události unknown zůstane unknown; pozdní záznam není datum události.
Zdroj reference-only ponechává limited-inputs. Mezery se propagují i zevnitř
již vydaných souhrnů: dostupné měsíční vydání nemusí mít kompletní týdenní
podklady. Výsledek je zobrazuje samostatně od dostupnosti top-level vydání.

ReportSnapshot má `analysis_ref` na neměnný `fpw-synthesis-analysis-v1`.
Analytické tvrzení má origin/current piny, assessment/scale/evidence refs;
report uvádí vstupní vydání a původní zdroje. Stávající trace/freshness čte
i tento uzávěr. Již zahrnutá historická revize není nová oprava; novější
nezahrnutý následník označí možné zastarání bez přepisu vydání.

## Modelové pokračování je explicitní

Pro report.mode=llm je nutný report.analysis.target s přesnými poli
Context Target: binding_id, binding_revision, boundary, target_id, model.
Deterministická analýza má target=null. Python aplikační tok:

1. `WatchSynthesis(node).prepare(project_id, definition_ref, period)` zmrazí
   vstupy a vrátí run ID; bez providerového volání.
2. Volající připraví existující provider-neutral adapter/binding a aktuální
   Authority s oprávněním ke všem zvoleným zdrojům i odvozenému ledgeru.
   Ledger artifact ID je `ident(run_id, "analysis")`.
3. `execute(..., model_execution=ModelExecution(adapter, binding, authority))`
   sestaví ledger, uloží PreparedContext do původního node-local journalu
   a použije roli analyst/monitoring-synthesis-analyst-v1.
4. Výstupem je review kandidát. Model vrací overview a anotace existujících
   claim IDs, přesného trendu a povolených důkazů. Nemůže přidat rating,
   změnit škálu, vytvořit potvrzený Event nebo sám vydat report.
5. Dosavadní scheduler preview/approval_digest a `publish(...,confirm=True)`
   ponechávají konečné posouzení a vydání oddělené.

Do Context Manifestu patří ledger i skutečně vybrané původní podklady;
metadata/refs nejsou náhradou jejich přístupových a privacy kontrol.
Externí backend používá původní explicitní approval. Serverový JSON endpoint
nemůže dodat důvěryhodný ModelExecution/Authority pouhým zasláním cíle;
nepřipojuje model automaticky. Plné ovládání modelového toku v UI má MON-08-09.
Hotové deterministické analýzy i modelové kandidáty lze číst a vydávat přes
dosavadní společný review tok.

Provider chyba, neplatný JSON nebo changed target nevede k fallbacku.
Privátní kontext se připíná před dispatch; model run ID se při retry nemění.
Po úspěšném backendu se opět čte uložený výsledek, po unknown je nutná
explicitní původní reconciliation. Session/authority změna se neobnovuje
odhadem. Volná modelová próza je označená jako návrh k review, nikoli důkaz
pravdivosti; původní strukturovaná evidence zůstává vedle ní.

Běh nepřidává hledání. Doplňkové search/capture piny se předávají samostatně
schváleným způsobem z MON-08-05. Uzávěr má limit 1024 uzlů, ledger 1 MiB,
privátní serialized context 8 MiB a původní provider/output limity. Příliš
velký nebo nedostupný vstup selže, není skrytě krácený na kompletní úspěch.

Rozhodnutí a crash hranice: [ADR 0079](adr/0079-longitudinal-synthesis-analysis.md).
Ověření: explicitní unittest moduly `tests.test_synthesis_analysis`,
`tests.test_synthesis_model` a relevantní původní Reporting/Definitions/
Scheduler/Monitoring/HTTPS/Qt regrese. Syntetický backend a dočasné projekty
nenahrazují živou referenční akceptaci MON-08-12; plná sada patří závěru dávky.

## MON-08-06 po začlenění plné synchronizace

Navazující review vychází z aktuálního Workspace projektu
`c898b941-8eb0-4406-8dad-6e2b96c06d59`, exportní revize
`c3ee867bcf19915337e3d23cf32b63f8964ed1952604480d920e1d360309595d`,
projektový commit `997a6e6c868f05a3316906fe3971c6d142b428ad`.
`F-M5-FULL-DATA-SYNC-01` je v tomto exportu dokončený a oba předpoklady
MON-08-06 jsou splněné. To samo neznamená přijetí implementace MON-08-06.

Dosavadní implementace ADR 0079 se nevytváří znovu. Nový integrační scénář
`tests.test_synthesis_federation` používá dva oddělené dočasné uzly,
schválené peer identity a původní podepsaný Git bundle transport:

1. První uzel vydá dvě týdenní zprávy nad revizemi stejné události a stejné
   explicitně posouzené škály. Změna maturity je 1 → 3.
2. Úplné definice a podklady se synchronizují na druhý uzel; ten vytvoří
   vlastní měsíční analýzu. Jedna událost má dvě zmínky, nikoli dvě identity
   či dva nezávislé důkazy. Chybějící týdny zůstávají jako mezery.
3. Druhý uzel vytvoří roční analýzu přes vydaný měsíc, včetně sestupu
   k původní události/hodnocení a zachování ongoing případové studie.
4. Vydání se synchronizují zpět. Na prvním uzlu se z jejich přesných pinů
   ověří deduplikace, trace k původním důkazům a freshness bez falešné opravy.

Scénář výslovně zakazuje nový connector fetch. Neznámé datum se neodvozuje
ze záznamu a reference-only evidence zachová `limited-inputs`. Běhové
journaly a oprávnění zůstávají node-local; na druhém uzlu se explicitně volá
původní WatchSynthesis, nejde o vzdálený dispatch nebo aktivaci pouhým sync.
Persistence a recovery zůstávají podle ADR 0079 a ADR 0081, bez nové vrstvy.

Akceptační pokrytí:

| Požadavek | Ověření |
| --- | --- |
| Opakovaná událost se nezapočítá vícekrát | native monthly/annual a federovaný průchod |
| Roční závěr je dohledatelný přes měsíce k důkazům | federovaný trace a native annual |
| Neověřené tvrzení se nepovýší na ověřený fakt | ledger/model regresní testy |
| Změna škály se nevykazuje jako pokrok | ledger změny škály, claimu a metodiky |
| Mezery v obdobích zůstanou viditelné | native a federovaný ledger gaps |
| Přímý roční přehled z týdnů | native annual s input_level=weekly |

Selektory: `python3 -m unittest tests.test_synthesis_analysis
tests.test_synthesis_model tests.test_synthesis_federation -v` (na jednom řádku).
Jde o izolované deterministické/syntetické ověření, nikoli fyzický Omnia PoC,
živý modelový běh nebo lidskou akceptaci celé dávky MON-08.

Výsledky navazujícího ověření 7. 11. 2026: `tests.test_synthesis_analysis`
a `tests.test_synthesis_model` — **16 testů OK**, 96,561 s;
`tests.test_synthesis_federation` — **1 test OK**, 207,324 s.
Výměna uzlů volá přímo původní transportní služby nad skutečnými Git bundle;
není to nový HTTPS test ani vzdálený dispatch. Síťová vrstva má samostatnou
evidenci F-M5-FULL-DATA-SYNC-01. Běhové timeouty produktu se nemění;
test pro závěrečné čtení otevírá nový nativní handle s vlastní platností.
Celkem 17 cílených testů, bez opakování plné sady před koncem dávky.
