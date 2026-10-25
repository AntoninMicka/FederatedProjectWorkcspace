<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-RESEARCH-WORKFLOW-01 — dynamický výzkumný workflow

Původ: uživatelem schválený směr po fyzickém ověření řízeného hledání,
readeru a dynamických revizí plánu; převzato se stejným ID z
[BACKLOG](BACKLOG.md). Milník M4, cílová úroveň **PoC validated**. Větev
`feature/f-m4-research-workflow-01` vznikla z `develop` `5d74144`; cílem je
jediný PR do `develop`.

Předchozí dávka `F-M4-DYNAMIC-WORKFLOW-01` byla doručena PR #88 jako merge
commit `5d74144`; její evidence je ve
[WORK_LOG](WORK_LOG.md#f-m4-dynamic-workflow-01--katalog-činností-a-dynamický-plán--2026-10-24).

## Rozsah a hranice

Nad existujícím search workflow, Public Source Readerem a typovaným katalogem
sestavit podle cíle proměnný tok `vyhledat → načíst → ověřit původ a vazby →
vybrat relevantní zdroje → volitelně analyzovat → sestavit zprávu`. Po každé
dokončené činnosti lze v aktivované policy navrhnout kompatibilní další krok,
opakování nebo předčasné ukončení; dokončená historie zůstává neměnná.

UI nabídne několik výchozích profilů, ale profil je pouze allowlist činností,
hranice a počáteční budget, nikoli pevná pipeline. Zvýšení celkového limitu
vyžaduje přesnou uživatelem potvrzenou revizi. Vyhledávání, fetch a LLM běhy
zůstávají v existujících doménových journalech a stav `unknown` se
automaticky neopakuje. Sestavená zpráva je reviewovatelný návrh; projektový
artefakt vznikne jen samostatnou přesně potvrzenou publikační operací.

## Úkoly

- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-A — kontrakt, profily, reuse a
  crash boundaries (cílová úroveň: designed).** Vymezit činnosti, typované
  vazby, dynamický planner, profilovou policy, persistentní autority a obnovu
  přes search, reader, provider a autonomy journal bez druhého writeru.
  Výsledek: [ADR 0048](docs/adr/0048-dynamic-research-workflow.md) definuje
  uzavřený katalog, tři výchozí profily, planner jako auditovatelný bounded
  krok a přesné recovery hranice. Reuse/reject je zaznamenán v
  [REUSE_CATALOG](REUSE_CATALOG.md).
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-B — výzkumný katalog a profily
  (cílová úroveň: implemented).** Přidat uzavřené deskriptory pro fetch,
  ověření evidence, výběr relevance, volitelnou analýzu, sestavení zprávy a
  návrh dalšího kroku. Validovat profilové policy, přesné vnořené vstupy a
  výstupy, povolené návaznosti a celkové limity.
  Výsledek: reviewovaný katalog obsahuje šest nových verzovaných akcí a
  profily `quick-search-v1`, `read-and-verify-v1` a `deep-research-v1` jako
  přesné allowlisty, nikoli pevné pipeline. `ActionRegistry` validuje uzavřené
  vnořené objekty, digesty, URL/binding readeru, evidence, citace, plannerovy
  podmíněné výstupy i jeho kandidátní vstup proti cílovému deskriptoru;
  profil nesmí rozšířit akce, permissions, privacy, hranice ani maximum.
  Ověření: `python3 -m unittest tests.test_research_workflow
  tests.test_action_autonomy -v` (28 testů OK), `python3 -m unittest
  tests.test_spdx -v` (1 test OK), `python3 -m unittest discover -s tests -v`
  (794 testů OK, 28 skipped) a `git diff --check` bez chyb.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-C — doménové adaptéry a dynamické
  materializování (cílová úroveň: implemented).** Adaptovat čistý reader
  candidate builder, existující search/reader/provider journaly a bounded
  source ledger. Plannerův výstup pouze navrhne append/repeat/finish;
  deterministický validátor z něj idempotentně vytvoří nejvýše jednu revizi.
  Výsledek: reader candidate je bez durable zápisu a opakované preview je
  stabilní i přes neautoritativní čas vytvoření; fetch, evidence, selection,
  analysis, report a planner používají stávající reader/Ollama journaly a
  hashově svázané source reference. Modelové JSON výstupy procházejí přesnými
  fail-closed validátory a nemohou doplnit cizí source ID. Plannerovo
  `append`/`repeat`/`finish` se materializuje z run ID a proposal hashe na
  deterministická UUID; replay ani restart nevytvoří druhou revizi a zvýšení
  limitu zůstává pending do přesného potvrzení. Ověření:
  `python3 -m unittest tests.test_research_workflow
  tests.test_autonomy_service.AutonomyServiceTests.test_research_planner_materializes_one_confirmed_budget_revision
  tests.test_chat_service.ChatServiceTests.test_web_search_requires_preview_and_reuses_results_after_restart
  -v` (8 testů OK), `python3 -m unittest discover -s tests -v` (796 testů OK,
  28 skipped), `python3 -m py_compile spikes/action_autonomy.py
  spikes/autonomy_service.py spikes/chat_service.py spikes/research_workflow.py`
  a `git diff --check` bez chyb.
- [x] [completed] **F-M4-RESEARCH-WORKFLOW-01-D — chatové UI a řízení průchodu
  (cílová úroveň: implemented).** Nabídnout profily a režim ruční/automatický,
  zobrazit fáze, zdroje, důvod změny, provenance, zbývající limit a přesné
  revizní potvrzení. Report zůstane návrhem se samostatným uložením.
  Výsledek: chat nabízí jednorázové hledání i tři reviewované profily v ručním
  nebo automatickém režimu. Aktivní průchod ukazuje skutečně materializované
  fáze, zdrojová URL a run ID, počty vazeb, výběr a závěry, důvody aplikovaných
  i čekajících revizí a zbývající cost/kroky/čas. Zvýšení limitu potvrzuje
  přesný digest revize. Dokončený report se načítá z provider journalu jako
  návrh; otevření pouze předvyplní běžný editor a Git se změní až jeho
  samostatným uložením. Ověření: cílené testy autonomy API, profilového cyklu,
  materializace revize a obnovení reportu prošly; `python3 -m py_compile
  spikes/desktop_ui.py spikes/action_autonomy.py spikes/autonomy_service.py
  spikes/chat_service.py`, kontrola generovaného JavaScriptu přes `node
  --check`, `python3 -m unittest discover -s tests -v` (797 testů OK, 28
  skipped) a `git diff --check` bez chyb.
  Doplňující požadavek z fyzické kontroly: dlouhé operace musí mít zřetelnou
  dočasnou stavovou zprávu přímo na konci časové osy chatu (např.
  „Vyhledávám…“, „Načítám zdroj…“, „Model přemýšlí…“), kterou po dokončení
  nahradí durable výsledek nebo navazující stav workflow. Výsledek doplnění:
  jednotná živá položka se spinnerem a časem je za běhu přímo poslední položkou
  `role=log`, přežije překreslení časové osy a po dokončení se odstraní. Stav
  rozlišuje search, reader, ověření vazeb, selection, analýzu, report a planner
  v ručním i automatickém režimu; funguje také pro streamované i nestreamované
  modelové odpovědi. Ověření: tři cílené UI/API testy OK, `node --check`
  generovaného JavaScriptu, `python3 -m unittest discover -s tests -v` (797
  testů OK, 28 skipped) a `git diff --check` bez chyb.
  Oprava z fyzické kontroly: výzkumný požadavek již nepoužívá 120s klientský
  timeout proti 180s limitu Ollamy, ale čeká 210 s. Prohlížečové „signal timed
  out“ se převádí na akční diagnostiku s výsledkem `unknown`, zákazem
  automatického opakování a upozorněním přímo ve vlákně. Po opravě:
  `python3 -m unittest discover -s tests -v` (797 testů OK, 28 skipped),
  `node --check` generovaného JavaScriptu a `git diff --check` bez chyb.
- [ ] [in progress] **F-M4-RESEARCH-WORKFLOW-01-E — regrese a realistická
  akceptace (cílová úroveň: PoC validated).** Ověřit předčasné ukončení,
  doplňující hledání, opakované načtení, ověření vztahů, výběr zdrojů,
  vloženou analýzu, prodloužení schváleného limitu, restart, `unknown` bez
  retry a nezměněný projekt před potvrzenou publikací.
  První fyzický průchod profilem „Načíst a ověřit“ doložil dokončené hledání,
  ale planner skončil známou chybou. Příčina v implementaci: dostával pouze
  hashe ledgeru a přitom měl sám sestavit přesný vstup readeru, což bez
  source/URL/binding dat není možné; jednotkový test tuto mezeru zakryl
  okamžitým `finish`. Oprava připravuje typed kandidáty z existujících
  doménových autorit a model volí pouze jejich digest nebo ukončení. Neznámý
  digest se odmítne fail-closed a chat nově vypíše konkrétní journalovou chybu
  přímo u selhané fáze. Zbývá nový fyzický průchod přes fetch, ověření, výběr
  a sestavení zprávy a ostatní scénáře této položky. Ověření opravy:
  cílené kontraktové, katalogové, materializační a UI testy prošly;
  `python3 -m py_compile` dotčených modulů, `node --check` generovaného
  JavaScriptu, `python3 -m unittest discover -s tests -v` (797 testů OK,
  28 skipped) a `git diff --check` bez chyb. Následná fyzická kontrola odhalila
  zdánlivý reset po restartu: task outcome, nulové orchestration vlákno i
  autonomy journal zůstaly durable, ale UI po otevření projektu žádné uložené
  vlákno nevybralo. Během čekání šlo navíc opakovaně spustit přípravu stejného
  profilu a postupně vznikly čtyři souběžné navržené fronty. UI nyní obnoví nejnovější
  aktivní projektové vlákno a jeho task outcomes, bezpečně pozastavený workflow
  nabídne k pokračování a souběžnou přípravu pro stejné task ID odmítne se
  živou stavovou položkou. Existující duplicitní fronty se automaticky nemažou.
  První opakování fyzické kontroly ještě odhalilo, že obnovení načetlo task
  outcomes, ale autonomy journal až po samostatném kliknutí na hlavní záložku
  Chat; bez něj se proto nezobrazila akce `Aktivovat plán`. Obnova projektu nyní
  načte i projektovou frontu před prvním vykreslením obnoveného workflow.
  Následná fyzická kontrola odhalila vlastní příčinu úplného výpadku zobrazení:
  dva starší již terminální workflow zůstaly validní journalovou historií, ale
  jejich vstupy už neodpovídaly novější revizi katalogu činností. Validace
  prvního z nich shodila celý výpis a skryla i nově úspěšně připravené plány.
  Výpis nyní takovou terminální historii zachová a explicitně diagnostikuje,
  ale dovolí zobrazit aktuální validní fronty; nekompatibilní aktivní plán dál
  selže uzavřeně. Chybu načtení fronty už Chat neskrývá.
  Ověření doplnění: tři cílené desktopové testy OK, `python3 -m py_compile
  spikes/desktop_ui.py`, `node --check` generovaného JavaScriptu,
  `python3 -m unittest discover -s tests -v` (798 testů OK, 28 skipped) a
  `git diff --check` bez chyb. Realistický restart a pokračování zůstávají k
  fyzickému potvrzení. Další fyzický průchod ukázal, že známé odmítnutí
  jednoho zdroje (např. požadované přihlášení) terminálně ukončilo celý
  výzkumný workflow. Readerův neúspěšný pokus nyní zůstává auditovatelně
  `failed` a spotřebuje svůj cost, ale pouze reviewovaný planner na něj smí
  navázat; již zkoušený source ID znovu nenabízí a `unknown` zůstává
  terminální bez retry. Při pádu mezi zapsáním známé chyby a připojením
  planneru se po restartu doplní jediná idempotentní revize a workflow zůstane
  bezpečně pozastavené do pokračování uživatelem. Ověření: 57 cílených testů
  autonomy, research a readeru OK, restartový test doložil zachování chyby a
  nabídku pouze zbývajícího zdroje, `python3 -m unittest discover -s tests -v`
  (799 testů OK, 28 skipped) a `python3 -m py_compile` dotčených modulů.
  Reálné pokračování po odmítnutém zdroji proběhlo až k ověření evidence;
  fyzická kontrola přitom odhalila, že pětisekundový heartbeat při překreslení
  chatu zavíral rozbalené „Důvody změn plánu“. Stav rozbalení historie plánu i
  zrušených verzí dotazu se nyní drží podle workflow ID stejně jako technické
  detaily fronty a změna revize jej neruší. Ověření doplnění: dva cílené UI
  testy OK, `node --check` generovaného JavaScriptu,
  `python3 -m unittest discover -s tests -v` (799 testů OK, 28 skipped) a
  `git diff --check` bez chyb. Zbývající fáze realistické akceptace této
  položky zůstávají otevřené. Tentýž průchod po ověření evidence zůstal ve
  stavu `queued` bez materializovaného kroku a nevytvořil závěrečnou zprávu:
  klientský scheduler předčasně vracel dynamický plán bez pending kroku a
  historické známé chyby readeru nepovažoval za uzavřené pokusy. Automatika
  nyní v tomto přesném stavu vyžádá backendovou idempotentní revizi; `unknown`
  mezi uzavřené pokusy nezařazuje. Ověření opravy: dva cílené UI testy OK,
  `node --check` generovaného JavaScriptu,
  `python3 -m unittest discover -s tests -v` (799 testů OK, 28 skipped) a
  `git diff --check` bez chyb. Fyzicky zbývá potvrdit pokračování přes výběr
  relevantních zdrojů a zobrazení návrhu závěrečné zprávy. Při následné
  fyzické kontrole se ukázalo, že pokud backend po tomto dorovnání vrátil
  beze změny stejnou revizi bez materializovaného kroku, každý heartbeat
  spustil tentýž pokus znovu a krátká stavová zpráva v chatu blikala. Klient
  nyní pro přesný otisk revize, stavů kroků a revizních návrhů provede nejvýše
  jeden automatický dorovnávací pokus; znovu pokračuje až po skutečné změně
  durable stavu a při pokusu zobrazuje konkrétní text `Doplňuji další krok
  výzkumu…`. Ruční akce zůstává dostupná. Ověření doplnění: dva cílené UI
  testy OK, `node --check` generovaného JavaScriptu, `python3 -m py_compile
  spikes/desktop_ui.py`, `python3 -m unittest discover -s tests -v` (799 testů
  OK, 28 skipped) a `git diff --check` bez chyb. Fyzické opakování po restartu
  potvrdilo dostupné `Pokračovat`, ale resume pouze změnilo frontu z `paused`
  na `queued`; poslední dokončené `research.verify-evidence` zůstalo bez
  navazujícího planneru a bez čekající revize. Automatické dynamické workflow
  proto při explicitním resume nově provede první backendové `advance` přímo,
  bez závislosti na pozdějším překreslení nebo heartbeat klienta. Běžný
  countdown, approval i fail-closed hranice doménového účinku zůstávají v
  `advance`; ruční workflow se automaticky neposune. Ověření opravy: tři
  cílené testy resume/recovery OK, `python3 -m py_compile` dotčených modulů,
  `python3 -m unittest discover -s tests -v` (801 testů OK, 28 skipped) a
  `git diff --check` bez chyb. Fyzicky zbývá potvrdit, že obnovená fronta
  projde přes výběr relevantních zdrojů až k návrhu závěrečné zprávy. První
  opakování odhalilo závod mezi starým `paused` snapshotem UI a již obnoveným
  durable stavem `queued`: druhý resume byl odmítnut obecnou chatovou chybou,
  přestože žádný nový krok ani externí účinek nevznikl. Resume je nyní
  idempotentní i pro již `queued` frontu a backendové dorovnání provede pouze
  tehdy, když jsou všechny dosavadní kroky terminální, chybí následník a není
  čekající revize. Existující queued krok druhý požadavek automaticky
  neposune. Ověření: šest cílených resume, recovery a global-pause testů OK,
  `python3 -m py_compile` dotčených modulů,
  `python3 -m unittest discover -s tests -v` (802 testů OK, 28 skipped) a
  `git diff --check` bez chyb. Realistické pokračování zůstává k opakování.

## Akceptace

- Aktivovaný profil omezuje činnosti a hranice, ale nevynucuje pevné pořadí;
  každý dynamický následník projde typovou, policy, privacy a budget validací.
- Search, fetch a LLM účinky mají jedinou existující doménovou autoritu;
  planner ani autonomy queue účinek neopakují a neodhadují jeho úspěch.
- Původ, vazby, výběr a závěry jsou auditovatelně svázané s přesnými source/run
  ID a hashi; modelové hodnocení se nevydává za ověřený fakt.
- Limit lze zvýšit jen přes potvrzenou revizi, workflow může korektně skončit
  dříve a dokončená historie zůstává append-only.
- Zpráva se zobrazí jako návrh a do projektu se uloží až samostatným přesným
  potvrzením; cílené testy, úplná sada a realistický fyzický průchod projdou.

## K předání do backlogu

- [ ] [planned] **OPS-NODE-MONITOR-01 — systémová telemetrie a viditelný
  runtime Ollamy (cílová úroveň: implemented → PoC validated).** Původ:
  uživatelské zjištění, že Ollama může po změně prostředí začít tiše provádět
  inference pouze na CPU. Adaptovat již připravený panel Zdroje a jeho ukazatele
  CPU, GPU, RAM, VRAM, DISK a NET na omezenou read-only telemetrii skutečného
  uzlu. U každého Ollama běhu rozlišit očekávaný a doložený režim CPU/GPU,
  částečný offload a stav `unknown`; samotná konfigurace GPU, dostupné zařízení
  ani okamžité vytížení se nesmějí vydávat za důkaz GPU inference. Pro lokální
  i private-network backend definovat podporovaný diagnostický kontrakt a
  provenance měření; nedostupná vzdálená telemetrie zůstane explicitně
  neznámá. Při očekávaném GPU a doloženém CPU-only běhu zobrazit výrazné
  varování v panelu i u běhu, ale nic automaticky nerestartovat, nepřepínat ani
  neopakovat. Akceptace: fyzicky ověřit GPU běh, CPU-only regresi, částečný
  offload, nedostupnou/opožděnou telemetrii, restart aplikace a oddělení
  historického run evidence od živého systémového vzorku; žádná diagnostika
  nesmí zpřístupnit credentials ani obejít hranici důvěry uzlu.
