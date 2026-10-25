<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-RESEARCH-WORKFLOW-01 — dynamický výzkumný workflow

Milník M4, cílová úroveň **PoC validated**. Větev
`feature/f-m4-research-workflow-01` vznikla z `develop` `5d74144`; cílem je
jediný PR do `develop`. Původní fyzická akceptace z 25. 10. 2026 byla po
navazujícím reálném pádu sestavení zprávy znovu otevřena. PR zatím nebyl
vytvořen ani sloučen.

## Úkoly

- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-A — kontrakt, profily, reuse a
  crash boundaries (designed).** [ADR 0048](docs/adr/0048-dynamic-research-workflow.md)
  drží uzavřený katalog činností, profilovou policy, persistentní autority a
  recovery. Reuse/reject je v [REUSE_CATALOG](REUSE_CATALOG.md).
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-B — výzkumný katalog a profily
  (implemented).** Přesné deskriptory a tři profily validují vstupy, výstupy,
  privacy, návaznosti a maximální budget.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-C — doménové adaptéry a
  dynamické materializování (implemented).** Search, reader a LLM používají
  své autoritativní journaly; planner volí jen aplikací sestavený kandidát nebo
  `finish` a materializace revize je idempotentní.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-D — chatové UI a řízení průchodu
  (implemented).** Ruční i automatický průchod ukazuje profily, fáze, zdroje,
  revize, rozhodnutí, budget a návrh zprávy. Durable výsledky tvoří jednu
  chronologickou osu; projekt se mění až samostatnou publikační operací.
- [ ] [in progress] **F-M4-RESEARCH-WORKFLOW-01-E — regrese a realistická
  akceptace (cílová úroveň: PoC validated).** Automatické testy pokrývají
  append/repeat/finish, známé chyby readeru, `unknown` bez retry, zvýšení
  limitu, restart/resume, jazyk, součet skutečných časů běhu a stabilní
  historii. Fyzické průchody ověřily cestu až k návrhu zprávy, ale následné
  opakování 25. 10. 2026 skončilo v `research.compose-report` jako `failed`.
  Read-only kontrola journalů doložila úspěšný 30,7s Ollama běh, tři přesně
  dostupné citace a jinak validní JSON; jedinou odmítnutou vlastností byl běžný
  závěrečný newline v Markdownu. Validátor nyní přijímá neprázdný bounded
  Markdown beze změny jeho bajtů, samostatně diagnostikuje pole, Markdown,
  strukturu citací a nedostupné source ID. Workflow karta zobrazuje konkrétní
  backendovou chybu. Přesná uložená odpověď z reálného selhaného runu po opravě
  prošla read-only parserem se všemi třemi citacemi a stabilním draft hashem;
  selhaný historický workflow zůstává auditně `failed` a automaticky se
  neopakuje. Ověření: tři cílené testy OK, `python3 -m py_compile`, generovaný
  JavaScript přes `node --check` a `python3 -m unittest discover -s tests -v`
  (805 testů OK, 28 skipped). Zbývá nový fyzický průchod přes sestavení a
  otevření návrhu zprávy.

## Akceptace

- Každý následník projde typovou, policy, privacy a budget validací; externí
  účinek má jedinou doménovou autoritu a `unknown` se neopakuje.
- Historie, zdroje, rozhodnutí a skutečný runtime zůstanou po restartu
  auditovatelné a projekt se bez samostatného potvrzení nezmění.
- Sestavení zprávy přijme běžný validní Markdown včetně koncového newline,
  odmítne skutečně neplatné nebo cizí citace a zobrazí konkrétní příčinu.
- Cílené testy, úplná sada a opakovaný fyzický průchod sestavením a otevřením
  návrhu zprávy projdou.

Odložený `OPS-NODE-MONITOR-01` je již veden v [BACKLOG](BACKLOG.md), nikoli
duplicitně v této aktivní dávce.
