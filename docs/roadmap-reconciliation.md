<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# DEV-01 — jednorázová úplná sémantická reconciliation roadmapy

Stav: **proposal scan implemented**, 28. 10. 2026. Jde o jednorázový nástroj pro dokončení
migrace, nikoli o cílovou obecnou Workspace feature `PLAN-SEMANTIC-AUDIT-01`.
Nástroj nejprve deterministicky vytvoří úplnou resumovatelnou frontu a až poté
jednotlivé položky předává same-node Ollamě. Běh nic nezapisuje do projektu.

## Původní pracovní zvyklosti

Původní soubory nelze interpretovat jako jednu normalizovanou databázi úkolů:

- `TODO.md` držel jednu právě zpracovávanou feature dávku. Celá dávka včetně
  dokončených podúkolů a testů zůstávala pohromadě do jejího uzavření.
- Při uzavření se dávka jako celek přesouvala do `WORK_LOG.md`; stejné ID proto
  může být v historii, shrnutí milestone i odkazech dalších dávek.
- `BACKLOG.md` míchal budoucí feature, odklady a starší `implemented, ale
  neověřeno` položky. Checkbox `planned` sám nedokazuje, že schopnost nevznikla
  později a není doložena ve WORK_LOG.
- Master Checklist je strategický katalog schopností, milestone a gates. Často
  shrnuje tutéž práci jinou granularitou než TODO/WORK_LOG a může používat jedno
  ID pro širší požadavek i několik formulací.
- Historické výsledky, akceptace, původní požadavek a zbývající omezení bývaly
  ukládány sekvenčně. Pozdější text má vyšší důkazní hodnotu jen tehdy, když
  skutečně dokládá výsledek; poslední výskyt není automaticky autoritou.
- Volné myšlenky, roadmapové kapitoly a checklist podmínky nejsou automaticky
  implementační úkoly. Stejně tak dokončená historie nemá být znovu otevřena.

Tyto zvyklosti jsou vstupní interpretační politika, nikoli nedostatky, které má
model mechanicky přepsat.

## Požadovaný nový stav

- Jeden kanonický executable graf drží právě jednu současnou definici každého
  milestone, batch a task ID.
- Historický výsledek zůstává dohledatelnou evidencí, ale není otevřeným taskem.
- Neuzavřená část dříve implementované schopnosti dostane konkrétní residual
  task; neotevírá se znovu celá původní dávka.
- Budoucí doložený požadavek je executable uzel s rodičem, rozsahem, akceptací,
  stavem a provenance. Strategická myšlenka může zůstat popisem.
- Dvě různé definice téhož ID se explicitně sloučí, rozdělí na nová stabilní ID,
  nebo označí jako konflikt. Model nesmí výsledek vybrat potichu.
- Dependency hrana vyjadřuje skutečnou podmínku provedení, nikoli pouze pořadí
  textu, chronologickou návaznost nebo společné téma.
- Původní přesné bajty, zdrojové revize a vazba každého rozhodnutí zůstávají
  dohledatelné v importovaných source artefaktech.

## Zmrazený úplný pracovní seznam

První `scan --deep-check` načte všechny importované source artefakty a současný
kanonický plán na exact HEAD. V privátní node-local SQLite nejprve založí celý
konečný seznam a teprve potom odešle nejvýše `--limit` položek modelu. Další
běhy pokračují nad stejnými fingerprinty; `list`, rozhodnutí a TUI používají
tutéž frontu jako původní detached scan.

Jednotkou není každý řádek, ale `source cluster`: stabilní ID se všemi výskyty,
nebo stabilně identifikovaný bez-ID blok se všemi lokátory. Fronta zároveň drží
samostatné cílové uzly a podklady, které jsou kandidátem shody. Každá položka má:

- source repository, commit, path, byte range a SHA-256;
- všechny původní formulace, checkboxy a časové/evidenční okolí;
- cílový project ID, expected HEAD a nalezené node/artifact kandidáty;
- policy revision, analyzer revision a fingerprint;
- stav `queued/running/pending/dismissed/failed/unknown` a bounded odpověď.

Po vytvoření se seznam během běhu nerozšiřuje. Změna zdroje, cílového HEAD nebo
politiky vyžaduje novou frontu/reconciliation run; původní běh zůstane auditním
snapshotem. Díky tomu je známý jmenovatel coverage a běh může bezpečně pokračovat
přes noc.

## LLM posouzení jedné položky

Context Manifest obsahuje pouze daný source cluster, relevantní pozdější
důkazy, malé množství cílových kandidátů a výše uvedenou interpretační politiku.
Model vrací právě jeden striktně validovaný proposal:

- `keep-history` — správně zachovaná historická evidence;
- `keep-description` — strategický nebo volný text bez executable uzlu;
- `keep-canonical` — současný cílový uzel odpovídá zdrojům;
- `promote` — zachovaný požadavek má být executable uzlem;
- `create-residual` — schopnost vznikla, ale zbývá konkrétní práce/ověření;
- `merge-alias` — více zdrojových formulací patří jednomu uzlu;
- `split` — jedno staré ID pokrývá více rozdílných budoucích uzlů;
- `update-node` — oprava názvu, popisu, akceptace, maturity nebo rodiče;
- `add/remove-dependency` — návrh hrany se zdrojovým a logickým důvodem;
- `conflict` — podklady nestačí k bezpečnému automatickému návrhu.

Proposal nese source → current target → proposed state diff, citované úseky,
confidence, alternativy a důvod. ID, stav dokončení ani dependency nesmí být
přijaty, pokud nejsou ve schématu a neprojdou deterministickou validací.

## Noční běh a recovery

Výchozí souběh je jeden modelový request. Před dispatch je položka durable
`running`; po jednoznačné odpovědi přejde do `pending` nebo `dismissed`.
Timeout či ztracená odpověď je `unknown` a automaticky se neopakuje. Strukturně
chybná odpověď je `failed` s bounded raw payloadem. Restart pokračuje pouze
dalšími `queued` položkami. Průběh ukazuje celkový počet, hotové/pending/error
stavy, poslední aktivitu a odhad zbývající fronty.

Ukončení je bezpečné mezi položkami. Probíhající dispatch se při běžném stopu
nepřeruší; tvrdý pád zanechá `running`, který recovery vyhodnotí jako `unknown`,
nikoli jako bezpečný kandidát automatického retry.

## Review a jediný zápis

Po doběhnutí se návrhy třídí podle action, confidence, source souboru a dopadu.
TUI ukáže celý source cluster, současný cíl a navržený before/after stav.
Accept/reject nemění projekt. Přijaté návrhy se nejprve složí do jednoho
kandidátního snapshotu, společně se zkontrolují na kolize, duplicity, cykly,
hierarchii, chybějící rodiče a rozporné úpravy stejného uzlu.

Projekt lze změnit až jednou potvrzenou `Workspace.transact` operací proti
původnímu expected HEAD. Pád před commitem obnovuje Workspace journal; po
commitu je autoritou Git a index se obnoví z HEAD. Pokud se HEAD během nočního
běhu nebo review změnil, apply se odmítne a návrhy je nutné explicitně rebase
nebo vytvořit nový run. Proposal queue není druhou autoritou roadmapy.

Aktuální implementační řez končí u společné fronty, striktní validace a human
accept/reject. `apply` přijatých strukturovaných deep-check návrhů záměrně
selže před zápisem; skládání více editací, kontrola kolizí/cyklů a jediný
transakční writer zůstávají otevřenou částí této položky.

Po akceptaci lze do projektu uložit bounded reconciliation report s coverage,
přijatými/odmítnutými/conflict položkami a run fingerprintem. Privátní queue se
automaticky nemaže; její explicitní úklid patří až za ověřený receipt a export.

## Akceptace jednorázového nástroje

- vstupní počet položek je konečný a coverage po zdrojích dává 100 %;
- restart, timeout, `unknown`, vadná odpověď a stop mezi položkami nezpůsobí
  duplicitní dispatch ani projektový zápis;
- žádný proposal nevznikne bez exact source a target provenance;
- review odliší historii, description, canonical node, residual práci a konflikt;
- kandidát odmítne kolizi ID, cyklus, orphan, dvojí editaci a stale HEAD;
- jediný potvrzený apply má Workspace receipt a opakování nevytvoří druhý commit;
- namátková i strojová kontrola po apply dohledá všechny původní source clustery.
