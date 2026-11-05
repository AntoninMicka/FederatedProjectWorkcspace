<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Reporting scheduler — MON-04

Lokální API `spikes.reporting_scheduler.ReportingScheduler` rozšiřuje
[ruční reporting](manual-reporting.md) o rezervace kalendářních běhů,
review a recovery. Architektura: [ADR 0072](adr/0072-reporting-scheduler-and-run-recovery.md).

## Izolovaná ukázka

Z kořene repozitáře s novými neexistujícími cílovými adresáři:

```bash
python3 -m scripts.reporting_scheduler_demo /tmp/reporting-scheduler-preview
python3 -m scripts.reporting_scheduler_demo /tmp/reporting-scheduler-confirmed --confirm
```

Ukázka nejprve vytvoří syntetický node s výchozím ručním reportem. Poté
rezervuje dvě poslední uzavřené týdenní periody podle Europe/Prague.
Bez --confirm zastaví první kandidát na review, projekt se po přípravě seedů
nezmění a druhá perioda čeká. S --confirm simuluje explicitní schválení obou
syntetických reportů a ověří přesně dva nové commity i stejné výsledky při
opakovaném publish. Nevolá LLM/síť, nemění běžný profil a neakceptuje task
ve Workspace. Data příkladu se nepovažují za reálné důkazy událostí.

## Tok místního vlastníka

1. `catch_up(project_id, task_ref, kind, start_local, limit=16,
   delivery_required=False)` provede konečný tick. Počátek má explicitní
   ISO offset a správnou místní kalendářní hranici; časovou zónu a revizi bere
   z připnutého tasku. Vrací runs, next_start a more. Opakování od stejného
   začátku vrací původní rezervace, nikoli nové výpočty. More vyžaduje další
   tick od next_start. Bez uzavřené periody nevznikne run.
2. Pro explicitní/manual/custom intent použijte `enqueue(request, run_id)`.
   Request má přesně project_id, task_ref, period, rules_ref, input_head,
   knowledge_cutoff, baseline_snapshot a delivery_required. Task/policy refs
   musí existovat v připnuté historii a zůstat aktuálně dostupné. Baseline je
   explicitní Ref nebo null; catch-up v tomto řezu používá null. Automatická
   diferenční baseline/syntéza není implementací MON-04.
3. `claim(run_id, worker_id, lease_seconds=60)` vrátí run a lease_token.
   Worker použije existující sběr/backendové služby s jejich vlastními
   journals. Jiný worker nemůže převzít aktivní práci. Expirace collecting
   označí unknown, nikdy sama nespustí další účinek.
4. `stage(run_id, lease_token, request)` přijímá jediný úplný ReportSnapshot
   request původního writeru, s přesně stejnými vstupními parametry runu.
   Validuje jej bez projektového zápisu a uloží immutable review kandidáta.
   `preview(run_id)` jej po restartu vrátí včetně Markdownu a approval digestu.
5. Člověk posoudí celý kandidát a použije `approve(run_id, digest,
   confirm=True)`. JSON modelu, tick ani claim nejsou schválením. Current
   policy a digest se kontrolují znovu. `publish(run_id)` používá stejný
   operation ID a stejný writer při prvním pokusu i recovery. Stale HEAD se
   automaticky neaktualizuje a schválené bajty se nesmí vyměnit.
6. Při delivery_required běh po vydání zůstane issued. Last issued snapshot
   už je dostupný, ale last successful cutoff se neposune. `begin_delivery`
   s explicitním potvrzením připne intent hash a key před účinkem; provider
   request/credentials patří mimo projekt Git. Volající ověří skutečný
   provider receipt a předá `confirm_delivery` přesné delivery_id,
   idempotency_key, intent_sha256, status=delivered a node-local receipt_ref.
   Bez takového ověření nelze ručně vyrobit úspěch jen z timeoutu.

`cutoff(project_id, task_entity, kind)` vrací poslední ověřený issued snapshot
odděleně od last_successful_cutoff (před dokončením může být null).
Při completed se cutoff a receipt potvrzují atomicky; starší dokončení jej
nevrátí zpět. Retry po ztrátě odpovědi vrací stejnou publikaci a receipt.

Failed/cancelled před vydáním lze znovu spustit jen explicitním `retry(...,
confirm=True)` se stejným intentem a novým attempt.
Připravený nebo posouzený kandidát lze odmítnout přes `cancel(..., confirm=True)`;
aktivní collecting/issuing účinek takto nelze slepě zrušit a opakovat.
Unknown vyžaduje dohledání původního účinku;
`reconcile_no_effect(..., confirm=True)` je lidské potvrzení,
že žádný účinek nenastal, nikoli automatická výjimka. Po vydání musí nový obsah
použít existující correction cestu, nikoli druhý základní report.

## Autority a omezení

Run journal je v novém soukromém adresáři mimo Git, standardně sourozenci
node konfigurace `.<node filename>.reporting-runs/`. Předem existující adresář
bez journalu se automaticky nepovažuje za nový: může znamenat ztrátu autority.
Zachovejte DB, attempts, původní unknown i receipts; nepřepisujte je z indexu.
Neznámé schéma, jiný node/owner nebo nebezpečná oprávnění se odmítnou.

Tento PoC je aplikační tick/worker API a spustitelná izolovaná ukázka. Neinstaluje
časovač do běžného backendu/OS, neprovádí autonomní syntézu ani sám neověřuje
vzdálené doručení. Produkční wiring, UI a provozní akceptace zůstávají samostatné.
Deterministické testy jsou v `tests.test_reporting_scheduler` a původní
reportingové sadě; zahrnují DST, konkurenci, restart stavů i Git CAS a
unknown delivery. Procesní pád neprokazuje odolnost vůči ztrátě disku/napájení.

## Ověření, 5. 11. 2026

Finální `python3 -m unittest discover -s tests -v` po poslední relevantní
změně kódu/testů: **1583 testů, 44 skipped, OK**, 584,191 s. Součástí je
všech 17 nových scénářů scheduleru, včetně DST a kanonického zápisu hranic,
dvojí rezervace, tokenů/expirace, změny task revize a její potvrzené náhrady,
revokace policy, obnovy review, změněného kandidáta, ochrany journalu,
procesních pádů před i po Git CAS a unknown delivery bez posunu cutoffu.

Samostatný cílený běh 17 scénářů prošel; poslední doplňující regresní selektory
také prošly. Finální ukázka bez --confirm skončila na review a nevytvořila
scheduled publikaci; ukázka s --confirm dokončila dvě periody dlouhé 169 a
168 UTC hodin, vytvořila právě dva nové commity a opakovaný publish vrátil
původní výsledek. Obě běžely nad novými izolovanými syntetickými projekty.

Prošly Python syntax, místní dokumentační odkazy a kontroly diffu/nových
souborů. Záznamy ukázek a testů jsou archivované v ignorované lokální
evidenci `.worktrees/mon-04-evidence/2026-11-05-scheduler-poc.tar.gz`;
`manifest.json` vedle archivu váže jeho SHA-256, source base a hashe skutečně
testovaných souborů v necommitnuté větvi. Archiv je důkazní kopie, nikoli
aktivní autorita runů nebo automaticky obnovovaný journal.

Zdrojový commit/push/PR ani změna autoritativního tasku se neprovedly.
Ověření neznamená instalaci časovače do běžného profilu, ověření reálného
externího doručení nebo lidskou akceptaci MON-04 ve Workspace.
