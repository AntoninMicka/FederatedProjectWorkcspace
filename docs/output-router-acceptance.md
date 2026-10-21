<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Checklist akceptace output routeru

Checklist ověřuje dávku `F-M4-OUTPUT-ROUTER-01`: statický capability katalog,
read-only plan/step DAG a aplikační review nedůvěryhodného planner návrhu.
Nespouští renderer, Ollamu ani jiný nástroj, nevytváří materializované výstupy a
nezapisuje do projektu. Execution patří až `F-M4-OUTPUT-ROUTER-02`.

## Rychlý read-only smoke

Z kořene repozitáře spusťte:

```sh
python3 scripts/output_router_smoke.py
```

Očekávaný checklist výsledku:

- [ ] `status` je `validated-read-only`;
- [ ] capability je přesně `renderer.web-static@1.0`;
- [ ] `execution_status` je `not-authorized`;
- [ ] `tampered_source_rejected` je `true`;
- [ ] `working_tree_unchanged` je `true`;
- [ ] výstup neobsahuje endpoint, credential, model ani potvrzení execution.

Smoke načte `README.md` z aktuálního Git commitu, připne blob ID, SHA-256 a
velikost, sestaví jednokrokový návrh a znovu jej ověří proti statickému katalogu,
samostatné policy a aplikačnímu snapshotu. Potom úmyslně změní hash zdroje a
ověří fail-closed odmítnutí. Nemění pracovní strom, a proto jej lze spustit i s
rozpracovanými změnami; kontroluje, že stav před a po zůstal totožný.

## Automatizované testy

```sh
python3 -m unittest tests.test_output_capabilities tests.test_output_plans -v
python3 -m unittest discover -s tests -v
python3 -m py_compile spikes/output_capabilities.py spikes/output_plans.py \
  spikes/output_planner.py scripts/output_router_smoke.py
git diff --check
```

- [ ] Cílená sada pokryje uzavřená schémata, přesné revize, změnu policy,
  nekompatibilní port, cyklus, cardinality, privacy, stale project HEAD,
  změněný trusted source a přepočet kompatibilních alternativ.
- [ ] Úplná sada skončí `OK`; přeskočené testy mají pouze doložený důvod
  reálného Qt/WebEngine, privátního vzorku nebo volitelného prostředí.
- [ ] `py_compile` a `git diff --check` skončí bez výstupu a s návratovým kódem 0.

## Ruční kontrola hranice

- [ ] V `modules/output-capabilities/` jsou pouze reviewované JSON descriptory;
  symlink nebo soubor s jiným suffixem způsobí odmítnutí katalogu.
- [ ] Planner proposal smí mít pouze akci `propose-output-plan`, účel a plán.
  Přidané `approval`, `execute`, endpoint nebo vlastní vysvětlení se odmítne.
- [ ] Změna HEAD, blob ID/SHA-256, privacy, policy hash nebo capability verze
  vyžaduje nový review; neexistuje fallback na jinou verzi či backend.
- [ ] Vysvětlení a kompatibilní alternativy vznikají z důvěryhodného katalogu a
  policy, nikoli z textu planneru.
- [ ] Handoff má vždy stav `not-authorized` a uvádí kontroly, které musí budoucí
  execution zopakovat. Platný plán sám není souhlas ke spuštění.

Do akceptační evidence zapište datum, commit, spuštěné příkazy a jejich skutečný
výsledek. Tato read-only část sama nedokládá funkční webový renderer, UI, LLM
plánování ani recovery execution; execution ověřuje až následující část.

## Execution a materializace — F-M4-OUTPUT-ROUTER-02

Následující část ověřuje první skutečný, lokální a explicitně potvrzený
`renderer.web-static@1.0`. Smoke čte připnuté bajty `README.md` z aktuálního
commitu, připraví privátní preview, použije jeho approval digest, vytvoří
materializaci pouze v dočasném mode-0700 adresáři a celý adresář poté odstraní.
Projektový Git ani publikované služby nemění.

### Rychlý execution smoke

```sh
python3 scripts/output_execution_smoke.py
```

Očekávaný výsledek:

- [ ] `preview_status` je `prepared` a `confirmation_digest` je 64znakový
  SHA-256 konkrétního requestu a preview;
- [ ] `execution_status` i `step_status` jsou `completed`;
- [ ] `output_sha256` má 64 hex znaků a `output_size` je kladné číslo;
- [ ] `project_head_unchanged` a `working_tree_unchanged` jsou `true`;
- [ ] `publication_performed` je `false`.

### Automatizované testy

```sh
python3 -m unittest tests.test_output_capabilities tests.test_output_plans \
  tests.test_output_execution -v
python3 -m unittest discover -s tests -v
python3 -m py_compile spikes/output_capabilities.py spikes/output_plans.py \
  spikes/output_planner.py spikes/output_renderers.py \
  spikes/output_execution.py scripts/output_router_smoke.py \
  scripts/output_execution_smoke.py
git diff --check
```

- [ ] Cílené testy ověří přesné potvrzení, změněný HEAD/zdroj, bezpečné HTML,
  předchozí materializaci, topologické zastavení potomků a idempotentní prepare.
- [ ] Simulovaný pád těsně po `dispatching` bez výstupu skončí po explicitní
  reconciliation jako `unknown` a renderer se automaticky nespustí.
- [ ] Simulovaný pád po atomickém zveřejnění generace ji převezme jen při shodě
  manifest hashe a renderer podruhé nevolá.
- [ ] Úplná sada, `py_compile` a `git diff --check` projdou po poslední změně.

### Ruční kontrola preview a hranic

- [ ] V JSON smoku zkontrolujte, že potvrzení vzniká až z připraveného preview;
  samotný planner handoff `not-authorized` nelze předat do `execute`.
- [ ] V dočasném testu ponechte ve vstupu řetězec `<script>alert(1)</script>` a
  ověřte, že výsledné `index.html` obsahuje pouze escapované
  `&lt;script&gt;...`, žádný spustitelný element.
- [ ] Změňte zdroj nebo checkout mezi `prepare` a `execute`: operace musí zůstat
  `prepared`, nevznikne generace ani Git commit a je potřeba nový preview.
- [ ] Přerušte běh po `step-dispatching`: restart nesmí krok opakovat. Explicitní
  `reconcile` bez přesné úplné generace jej označí `unknown` a potomky `blocked`.
- [ ] Přerušte běh po `materialization-published`: explicitní `reconcile` smí
  převzít pouze přesně shodný receipt/manifest/output; následné pokračování
  nevykoná renderer znovu.
- [ ] Ověřte, že cache leží mimo projektový root, databáze má mode 0600,
  generace mode 0700/soubory 0600 a cache není součástí Git/federace.
- [ ] Stav neprohlašujte za publikovaný web: tato dávka nedělá deploy, DNS,
  upload, Julia výpočet ani LLM dispatch. Ty potřebují vlastní capability,
  potvrzení a recovery.
