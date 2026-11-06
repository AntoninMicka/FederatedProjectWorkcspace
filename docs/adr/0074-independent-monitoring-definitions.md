<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0074 — Samostatná propojená sledování a připnuté definice běhů

Datum: 2026-11-06. Stav: implementace modelu MON-08-01 k review.

## Potřeba a rozsah

Uživatel odmítl současný výsledek MON-05 a převedl nápravu do MON-08.
Model několika reportovacích period uvnitř jednoho sledování neumožňuje
samostatně řídit sběr, vyhodnocování a návaznou syntézu. Tento ADR nahrazuje
příslušnou část deklarace sledování v [ADR 0073](0073-monitoring-ui-and-period-synthesis.md).
Jeho původní runtime zůstává kompatibilní cestou do explicitní migrace;
tento krok sám nepřevádí ani neaktivuje existující uživatelská sledování.

Zadání při zahájení: kanonický projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
export `c118e80bd0e52b3a168a84b6b975f70ad17dad66aa698af142df3a45e770226f`,
projektový HEAD `df5f6eeaccccfa4edddf23f27c0f49512e3e92fc`, stale=false.
Zdrojový základ `014537b`. Uživatel výslovně zařadil RSS/Zdroje a tento model
do jedné dávky MON-08 na téže větvi. Tento záznam neduplikuje živý plán.

## Rozhodnutí a reuse

Reporting dostává aditivní typ `WatchDefinition`, value schema
`fpw-reporting-watch-v1`. Envelope zůstává `fpw-reporting-record-v1`.
Stabilní `entity_id` je identita sledování; `revision_id`, rodiče, přesné
bajty a provenance používají původní Reporting/Workspace writer.
Nejde o druhý konfigurační soubor, databázi ani writer.

Každá definice obsahuje název, cíl, scope a privacy v envelope, deklarovanou
aktivaci, jeden hlavní kalendářní rozvrh, vstupy s vlastními intervaly
kontroly zdrojů, verzovaná pravidla výběru a vyhodnocení, zadání/formáty
výstupu a požadované umístění běhu. Denní interval je skutečný kalendářní
den v zadané zóně, včetně 23/25 hodin při změně času. U collect-only jsou
výstupem nálezy, nikoli fiktivní zpráva. Konektorové typy jsou deklarace;
jejich přijetí není důkaz dostupného konektoru.

Vstup z jiného sledování má stabilní watch ID a rozlišuje nálezy,
zpracované položky a zprávy. Výchozí zprávy jsou pouze vydané; použití
návrhů vyžaduje explicitní `include_drafts=true`. Vazby musí tvořit DAG
nad aktuálními revizemi. Chybějící cíl, self-link, cyklus a snížení privacy
se odmítnou při sémantické validaci celého kandidáta, včetně obecného writeru
a raw editoru. Externí vstup nesmí mít credentials, query konfiguraci ani
neposouzený přístup/uchování. Local-only sledování neprovádí externí sběr.

`active` deklaruje požadované zapnutí; není souhlasem s externím účinkem.
Modelové API vrací `runtime_state=not-connected`. Tento řez nepropojuje
nové definice s periodickým workerem, RSS sběrem ani LLM. Skutečný dispatch
musí nadále ověřit oprávnění, aktuální souhlas a explicitní Context Manifest.

Příprava reportingového běhu použije původní rules dokument, EvaluationScale,
ReportingTask a ReportingScheduler. Připne konkrétní vlastní revizi i přímé
upstream definice a jejich pravidla výběru vstupů. Piny normalizuje na commit
zavedení neměnné revize, aby nesouvisející commit nevytvářel novou identitu
pravidel. Výsledek je pouze `prepared` intent v existujícím journalu, bez
dispatch, syntézy a publikace. Nový běh nad nahrazenou vlastní definicí se
odmítne; replay původního run ID ponechá jeho původní intent. Collect-only
a vzdálené umístění se tímto reportingovým vstupem nespouštějí.

Veřejný i soukromý reuse katalog byly zkontrolovány. Reuse/adaptují se
Reporting/PinnedRef, společný sémantický gate, Monitoring materializační
receipts a EvaluationScale, ReportingScheduler a HTTP/RBAC. Druhý run
journal, writer, provider SDK nebo automatická migrace byly odmítnuty.

## Crash boundaries a recovery

Platí [ADR 0068](0068-manual-reporting-transactions.md) pro definice a
[ADR 0072](0072-reporting-scheduler-and-run-recovery.md) pro run journal.
Nové nejsou žádné perzistentní vrstvy. Operace se nesmějí prezentovat jako
jedna atomická transakce napříč projektovým Gitem a node-local journalem.

| Hranice | Chování |
| --- | --- |
| Neplatný model / stale HEAD před prepare | Žádná revize a žádná aktivace. Validuje se i výsledný graf. |
| Prepared / soubory / Git CAS / index definice | Původní Workspace journal dokončí přesné bajty; replay stejného operation ID vrátí receipt bez druhé revize. Cizí změny se nepřepíší. |
| Mezi materializací rules/scale/task | Každý krok má svůj deterministický receipt. Restart opakuje původní kroky bez nových artefaktů. Žádný krok nevysílá externí požadavek. |
| Před/po rezervaci run intentu | Existující scheduler váže run ID a reservation na neměnný intent. Replay ověří původní přístup a vrátí původní běh; jiné zadání je konflikt. |
| Ztráta projektového indexu | Obnova z validovaného HEAD, nikoli z indexu. Run journal není obnovitelná projekce a jeho ztráta vyžaduje původní fail-closed reconciliation. |

## Hranice akceptace

Tento řez implementuje model a jeho API. Neimplementuje celé MON-08:
konektory, průběžný RSS sběr, filtry a zpracování, výběr skutečných reportů
jiného sledování, federované umístění, nové formuláře a migrace mají své
navazující úkoly. RSS sekce Zdroje zatím zůstává samostatným ručním readerem.
Původní rozhraní a worker MON-05 nejsou prohlášeny za opravené nebo akceptované.
Použití modelového API a ověření: [Samostatná sledování](../independent-monitoring.md).
