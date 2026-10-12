<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Checklist akceptace read-only output routeru

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
výsledek. Tento checklist nedokládá funkční webový renderer, UI, LLM plánování
ani recovery execution; tyto schopnosti zůstávají navazující prací.
