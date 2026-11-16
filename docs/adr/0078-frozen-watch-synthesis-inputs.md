<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0078 — řetězení sledování přes zmrazené vstupy

Stav: implemented / cílené PoC ověření, lidská akceptace samostatně.
Rozsah MON-08-05; navazuje na [ADR 0074](0074-independent-monitoring-definitions.md),
[ADR 0072](0072-reporting-scheduler-and-run-recovery.md) a
[ADR 0076](0076-recurring-rss-findings.md).

## Rozhodnutí a reuse

WatchDefinition.inputs nadále odkazuje na stabilní watch identity. Každý watch
vstup může mít explicitní policy: window (`ending-in-period` nebo `overlap`),
approval (`issued` pro reporty; `captured`, `selected`, `processed` pro nálezy)
a missing (`wait` nebo `allow-incomplete`). Bez policy jsou reporty issued,
findings selected a processed-items processed; chybějící vstup znamená wait.
Externí vstup může stejným způsobem určit missing a approval; přímé RSS má
bez policy selected, jiný externí zdroj captured. DAG a privacy celého modelu
zůstávají součástí původní sémantické validace, včetně generického writera.

Nový `WatchSynthesis` čte vydané ReportSnapshot, SourceFinding a explicitně
vybrané zachycené externí zdroje. Nemá síťový účinek ani vlastní worker.
Externí hledání/capture proběhne přes dosavadní samostatně schvalované služby;
syntéza převezme přesné source piny přiřazené k definovanému vstupu.
Reference-only Source není zachycený výsledek. Přenos node-local review
kandidátů jako veřejných draftů není dostupný: include_drafts selže explicitně.

Příprava zmrazí neměnný projektový artefakt
`fpw-watch-input-manifest-v1`: vlastní definici, definice upstream vstupů,
období, input HEAD, cutoff, policy každé vazby, očekávané kalendářní sloty,
přesné vybrané revize a mezery. Pro zprávy je výchozí slot určen koncem
upstream období uvnitř downstream období. overlap zahrne i přesahující sloty.
Pro nálezy je časovým základem první discovered_at, nikoli odhad data události.
Všechny vybrané revize musí být dostupné a nesmějí překročit HEAD/cutoff/privacy.
Opravy stejného zdrojového reportu nahrazují předchůdce pouze při novém výběru;
konkurující vydání jednoho slotu jsou konflikt, nikoli náhodný latest-wins.

Manifest je evidence běhu v projektovém Gitu, nikoli druhý provozní journal.
Bootstrap pravidel a ReportingTask používá původní immutable receipts.
Pravidla připínají také manifest a **zmrazené** upstream definice, i když
se před dokončením bootstrapu objeví novější upstream revize.
ReportingScheduler nadále vlastní rezervaci/lease/review/publication a receipt.
Nezavádí se nová SQLite tabulka, writer, synchronizační kanál ani timer.

## Crash boundaries a recovery

1. Před freeze není síť ani částečně vydaná zpráva. wait vrací konkrétní
   chybějící sloty bez zápisu; další explicitní příprava je může znovu načíst.
2. Freeze je původní Workspace transakce. Manifest/operation/run ID se odvozují
   ze stabilního watch ID a období. Pád před ref obnoví původní journal,
   po ref se použije receipt. Dvě konfigurace téhož slotu se tiše nesloučí.
3. Po freeze se vstupy nevybírají znovu. Pád během postupného materializování
   pravidel/škály/tasku používá původní deterministické operation receipts.
   Chybějící nebo opožděný report příchozí později není připsaný do starého intentu.
4. Teprve následně vznikne původní scheduler run se stejným cutoffem a pinem
   manifestu. Nově materializovaná přesná task scale je control metadata,
   nikoli nová znalost; jen tato škála je u synthesis reportu vyjmuta z
   evidence timestamp cutoff kontroly. Evidence a všechny její piny zůstávají
   pod původním HEAD/cutoff. Jiné škály tuto výjimku nemají.
5. Sestavení je lokální bounded výpočet nad zmrazenými daty. Pád po claim
   bez dokončení přejde po vypršení lease do unknown, bez automatického retry;
   původní reconciliation/no-effect a potvrzený retry zachovají původní vstupy.
6. Review, approve a publication používají původní ReportingScheduler a
   Reporting.apply. Zpráva obsahuje `synthesis.manifest_ref`, complete a gaps;
   sémantická validace porovná manifest s task rules a ověří každý source pin.
   Guard pod writer lockem odmítá novou publikaci změněné/pozastavené definice.
   Již committed operace se obnovuje přes receipt, nikoli novou kontrolu zdrojů.
   Při úzkém závodu s revokací či jiném odmítnutí před Workspace prepare může
   journal zůstat issuing bez receipt: jde o explicitní operátorskou
   reconciliation původního publikačního intentu, ne bezpečný automatický retry.

Stejný slot/intent vytváří jedno základní vydání. Nová definice nebo změněné
supplemental piny neobcházejí starou rezervaci; vyžadují výslovně řešenou opravu.
Existující ruční Reporting korekce zachová corrects, původní období i historii.
Automatické přestavení downstream reportu se nepovoluje.

## Úplnost, audit a omezení rozsahu

wait vyžaduje všechny očekávané zdrojové reporty. allow-incomplete vyžaduje
uloženou explicitní policy a výsledek vypíše konkrétní chybějící intervaly.
Úplnost znamená dostupnost očekávaných vstupních vydání, nikoli potvrzení
jejich tvrzení nebo úplnost celého světa. Prázdná sada findings sama nedokládá
dokončenou nultou dávku upstream sběru: výsledek ji přizná jako mezeru.

Read-only trace prochází přesné manifesty/reporty/nálezy/provenance až k raw
zdrojům. Freshness hledá novější corrects a následníky také přes více úrovní.
Vrací potentially_stale, původní artefakt nijak nepřepisuje. Chybějící nebo
revokované bajty nejsou zaměněné za kompletní provenienci.

Runtime tohoto kroku sestavuje deterministický evidence přehled s omezenými
výňatky a plnými piny; model llm odmítá bez fallbacku. Analytické dlouhodobé
zadání, dedup událostí mezi souhrny a modelová syntéza náleží MON-08-06.
Plný editor vazeb a ručního spouštění v UI náleží MON-08-09; nyní je společný
review/publish výstup doplněný o úplnost a případné zastarání.

Reuse/adapt: Reporting/Workspace, Scheduler, WatchDefinition DAG, zdrojové
capture/import kontrakty a provenance. Nový je selektor/manifestační vrstva.
Odmítnuto: automatický crawler/hledání, druhý writer/journal a přepis vydání.
API a ověření: [řetězení sledování](../watch-synthesis.md).
