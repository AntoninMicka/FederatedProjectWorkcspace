<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Pracovní kontext úkolu — PLAN-TASK-WORK-01-A/B/C/D

V roadmapě otevřete detail konkrétního nedokončeného úkolu a použijte
**Zahájit úkol**. Start ověří projektová oprávnění a předpoklady a označí task
jako Probíhá přes běžný projektový writer. Úkol nemusí mít checklist.

Vpravo se zobrazí trvalý panel pracovního kontextu a ovladače:

- **Pozastavit** uvolní aktivní kontext tohoto okna; task nepřepne na Odloženo.
- **Pokračovat** znovu ověří oprávnění a zadání vybrané pozastavené relace.
- **Ukončit relaci** uzavře pracovní úsek, nikoli úkol v roadmapě.
- **Dokončit úkol** po výslovném lidském potvrzení zapíše dokončení do roadmapy
  a uzavře vybranou relaci. Vyžaduje dokončené závislosti a již potvrzený
  checklist; jeho body se automaticky nezaškrtnou. Při nesplněných podmínkách
  panel ukáže důvod a nabídne **Otevřít zadání úkolu**.
- **Navrhnout dokončení** uloží komentář jako lokální pending návrh relace.
  Task ani checklist se nezaškrtnou. Skutečné lidské dokončení zajišťuje
  samostatná akce **Dokončit úkol**; návrh ji sám nevyvolá.
- Jiný úkol zahájíte z jeho detailu. Potvrzené přepnutí pozastaví původní
  relaci. Nové zadání stejného tasku uzavře starý úsek a zachová oba piny.

Výběr projektu nebo dokumentu sám pracovní kontext nepřepne. Relace jiného
projektu si uchová původ a vlastní identitu; shodná task ID různých projektů
se nezamění. Samotný start ani pokračování nevolá model nebo hledání.

Po restartu desktopu se uložená práce nabídne přímo z backendu, i když nový
prohlížeč nemá žádné sessionStorage a server používá jinou lokální adresu.
Vyberte původní úkol a **Obnovit a pokračovat**. Po potvrzení se převezme jeho
původní okno, zneplatní stará capability a pokračuje se ve stejné relaci:
pin zadání, checklistový kontext, činnosti a uložené nabídky zůstávají stejné.
Pokud není otevřený jiný projekt, otevře se projekt obnoveného úkolu.
Výpis uložené práce sám nic neaktivuje. Převzetí vyžaduje autentizovaného
vlastníka, čerstvou capability nového okna a přesné CAS revize; znalost UUID
nestačí. Cizí účet nemůže relaci vypsat ani převzít. Rozpracovaná nativní
operace se místo automatického pokračování nabídne k původní obnově.

Po reloadu použijte **Obnovit pracovní okno**. Převzetí vyžaduje původní
ověření uložené v tomto tabu, pozastaví jeho aktivní relaci a zneplatní token
původního okna. Potom zvolte relaci a **Pokračovat**. Duplicitní tab se nesmí
připojit nebo zahájit práci samovolně. Ztracená odpověď obnovy se dohledá
stejným restore operation ID; nevytváří se nová operace.

Po chybě startu/přepnutí použijte **Obnovit kontext**. Pending start nabízí
**Dokončit obnovu** se stejným ID. **Zrušit zahájení** je přípustné jen před
zahájením nativního zápisu; publikovaný projektový commit se tím nevrací.
Dokud je kontext nejistý, nelze pod ním zahájit další činnost. Rozpracovaný
editor se neukládá ani nemaže; pozastavení relace jeho draft zachová.

Panel ukazuje aktuální zadání, projekt, stav a postup checklistu. Volba
**Celý úkol** nebo konkrétního bodu mění pouze kontext následné práce;
nezaškrtává splnění. Původní pin zadání relace zůstává neměnný.
**Vybrat jiný úkol** otevře plán; samotný výběr ještě nezmění pracovní relaci.

Panel lze sbalit a znovu otevřít při čtení podkladu, editaci, hledání i chatu.
V úzkém okně se otevírá jako dialog s návratem fokusu, klávesou Escape
a omezením Tab na jeho ovladače. Neuložený editor zůstává zachován; navigace
používá jeho běžné potvrzení. Prezentační režim panel skryje.
Po ztrátě oprávnění se vyčistí zadání i checklist. Činnosti ukazují druh, čas, výsledek a dostupný commit; lokální návrhy
dokončení se zobrazují zvlášť. Komentované přílohy nabízí část D níže.

## Rozsah tohoto řezu

Implementované jsou pracovní relace (A), pravý panel se zadáním/checklistem
(B), evidence nativních činností (C) a potvrzené komentované záznamy (D).
Propojení zadání s LLM běhy (E) a společné recovery celé dávky (F)
zůstávají navazujícími úkoly stejné dávky. Celou dávku tímto nelze akceptovat.

`capture` vrací neměnnou identitu původní relace a jejího zadání pro evidenci C
a navazující E včetně vybraného bodu `selected_checklist`. Evidence C ji zachytí před
operací; předání zadání jako vstupu modelu zůstává součástí E.
Nabídka obsahuje nejvýše 50 posledních relací okna plus jeho aktivní relaci;
starší uložené relace se tím nemažou. Historický index nedostává novou autoritu.

## Evidence činností

Při aktivní relaci se skutečné uložení, import, odstranění, konverzační turn,
vyhledávání či modelový běh evidují pod kontextem zachyceným před operací.
Sbalení panelu evidenci nevypíná. Neuložený draft, náhled nebo jednotlivé
klávesy nevytvářejí záznam. Evidence nepřidává vstupy do Context Manifestu,
nespouští poskytovatele a nepotvrzuje splnění úkolu.

Sdílené desktop/web UI přidává ověřený header `X-FPW-Task-Work` pouze
k podporovaným nativním akcím. Jeho JSON obsahuje `window_id`, `window_token`
a `context_revision`. API klient bez pracovního okna jej nepřidává; backend
neodhaduje kontext podle posledního projektu ani cizího okna. Přesný seznam
akcí drží `spikes/task_activities.py:ROUTES`: dokumenty, zdroje včetně Drive,
plán, Julia/prezentace, stage/commit artefaktu, uložené chatové výstupy,
vyhledávání, chat a modelové úlohy. Běžné přímé volání Python služby bez
pracovního okna se za uživatelskou činnost automaticky nevydává.

Záznam má stabilní event ID odvozené z autora, nativní akce a operation/run ID,
původní relaci, pin zadání a checklistový kontext, autora, časy, hash requestu,
reference vstupů a nativního výsledku a stav `succeeded`, `failed` či `unknown`.
Stejný request/ID seskupí replay do jedné činnosti; jiné tělo pod stejným ID
se odmítne. Streamové delty nejsou samostatné činnosti. Pozdní výsledek se
připíše původní relaci i po přepnutí či pozastavení.

Do evidence se nekopírují texty, prompty, tajné hodnoty ani modelové návrhy.
Čtení znovu ověřuje aktuální práva. Web nezobrazuje lokálně zachycené události
ani reference do projektu s local-only obsahem; nedostupný podklad se tím
nezpřístupní. Komentovaný a verzovaný projektový záznam zajišťuje D; společné recovery celé dávky patří do F.

Záznam před účinkem je trvale `unknown`. Nativní writer nebo run journal
zůstává autoritou účinku; před odesláním terminální odpovědi se doplní receipt.
Pád po nativním commitu před doplněním evidence ponechá `unknown`, nikoli
falešný úspěch. Chyba finalizace evidence nezmění úspěšnou nativní odpověď
na chybu vyzývající k opakování. Výslovný replay stejné nativní operace může doplnit původní
receipt bez druhého commitu; evidence nic sama neopakuje. Neznámý placený
běh se řeší původním run journalem, nikdy novým automatickým pokusem.

## Připojení už existujícího souboru

V pracovním panelu vybraného úkolu zvolte **Připojit existující soubor /
artefakt**, vyberte položku projektu a doplňte komentář. Teprve **Potvrdit a
připojit** uloží připnutou verzi výsledku a stručný záznam s odkazem přímo do
textu úkolu. Výstup není nutné znovu ukládat ani vytvářet novou činnost.
Obsah souboru se nekopíruje a úkol se nedokončí.

**Obnovit výběr** načte aktuální seznam a zachová komentář. Při přerušeném
zápisu použijte původní **Obnovit zápis**; opakování stejné operace nevytvoří
další přílohu. Soubor uložený jen mimo projekt nejprve přidejte mezi podklady.

### Odkaz do jiného projektu

Použijte **Připojit odkaz z jiného projektu**. Existující sdílecí dialog nabídne
podklady výslovně sdílené do projektu úkolu. Po potvrzení se odkaz objeví ve
výběru přílohy; záznam do úkolu opět uloží až **Potvrdit a připojit**. Stejným
výběrem lze připojit již existující projektovou referenci. Zdrojový soubor se
nekopíruje a jeho projekt, identita a připnutá revize zůstávají zachované.

**Původní verze** otevře skutečný obsah zdroje v původně připnuté revizi,
nikoli JSON soubor odkazu. Pozdější explicitní aktualizace reference jej
nepřepíše. **Aktuální artefakt** používá nynější revizi reference. Odvolané
sdílení nebo odebraná práva zabrání otevření obsahu i novému připojení.
Odkazy uvnitř náhledu se otevírají ve zdrojovém projektu, aniž se tím přepne
pracovní úkol. HTTP(S) odkazy lze otevřít v prohlížeči; desktop je po kliknutí
předá systémovému prohlížeči.

## Přidání komentovaného záznamu

V pravém panelu pod **Přidat záznam k úkolu** vyberte jednu nebo více
činností stejné původní relace. Upravte předvyplněný komentář, případný bod
původního checklistu a privacy. **Uložit rozepsané**, **Odložit** a **Odmítnout**
uchovají nabídku lokálně bez projektového commitu. **Otevřít nabídku** ji
znovu načte; pravidelné obnovení panelu neotevírá žádný modal a nepřepisuje
právě psaný komentář. Neuložený editor podkladu zůstává samostatný.

**Potvrdit a připojit** uloží stručný komentář a odkazy přímo do textu původního úkolu a současně vytvoří verzovaný projektový artefakt s komentářem,
původními event/operation/run referencemi a připnutými souborovými výsledky.
Výsledky určuje nativní receipt a změněné artefakty v jeho Git commitu;
vstupní podklady se samy nestávají výsledky.
Obsah inventáře či analýzy se do roadmapy nekopíruje. Bod checklistu zůstává
pouze kontextem; jeho splnění, akceptace úkolu i dávky vyžadují samostatné kroky.
Záznam failed/unknown události neobsahuje smyšlený uložený výsledek.

Záznamy jsou dostupné také přímo v **Úkoly / roadmapa → detail úkolu →
Plnění úkolu a výsledky**. Tento pohled nevyžaduje zahájenou relaci ani
převzetí pracovního okna. Čte potvrzené záznamy z projektového Gitu, včetně
záznamů jiných autorů při současném právu číst projekt. Pod nimi je oddělená
**Automatická evidence na tomto uzlu** s vlastními nepřipojenými činnostmi,
rozepsanými/odloženými komentáři a odkazy na vzniklé soubory. Lokální evidence
se tím nepublikuje ani nesynchronizuje. Čtenář projektu má přístup k potvrzeným
záznamům, nikoli k lokální činnosti jiného účtu. **Obnovit záznamy** provede
nové čtení. Není-li lokální store dostupný, Git záznamy zůstanou zobrazené
s výslovnou informací o nedostupné lokální evidenci.

Potvrzené záznamy jsou chronologické. **Původní verze** otevře přesné uložené
bajty a commit výsledku, **Aktuální artefakt** jeho nynější verzi. Při odstranění
artefaktu zůstává původní verze dostupná z historie. Náhled je uvnitř panelu,
bez uložení nebo zavření rozpracovaného editoru. Změna oprávnění náhled vyčistí.
**Upravit komentář** přidá revizi a zachová předchozí komentáře i původní piny.

Zápis čekající na obnovu nabízí **Obnovit zápis** pod původním operation ID.
**Zrušit před zápisem** je dostupné pouze před zahájením nativního writeru;
po commitu se dokončí původní receipt, nevytváří se nový záznam. Při změně HEAD
zachovejte text a použijte **Obnovit nabídku**; připravený intent se nepřebazuje.

Projektový formát je `artifacts/<record-id>/task-work.json` s běžnou metadata
sidecar a schématem `fpw-task-record-v1`. Validator kontroluje unikátní eventy,
privacy a historii oprav; sémantický přechod nepovoluje přepsání provenance
ani odstranění dřívějších revizí. Není to druhé úložiště stavu úkolů.

## API, úložiště a ověření

`POST /v1/task-work` používá aktuální autentizaci aplikace. `window` vygeneruje
window ID a capability; do requestu se nesmí vložit cizí user/node ID. Další
akce jsou scoped touto dvojicí. Credential se nezapisuje do projektového Gitu
ani do request payloadů lokálního journalu; v DB je pouze jeho hash.

| Akce | Další pole vedle `action`, `window_id`, `window_token` |
| --- | --- |
| `history` | Pouze `action`, bez window capability; readonly výpis nejvýše 50 vlastních relací s aktuální kontrolou oprávnění. |
| `reclaim` | Capability nového prázdného okna, `operation_id`, `context_revision`, `work_session_id`, `session_revision`, `target_context_revision`, `confirmed: true`; vrátí rotovanou capability původního okna. |
| `complete` | `operation_id`, `context_revision`, `work_session_id`, `session_revision`, `expected_head`, `confirmed: true`. |
| `status` | Žádná; čte ověřený stav a případný pending záměr. |
| `inspect` | `project_id`, `task_id`, `expected_head`; vrátí aktuální digest fragmentu pro start. |
| `start` | `operation_id`, `context_revision`, `project_id`, `task_id`, `expected_head`, `fragment_sha256`, `selected_checklist` (`null` nebo platný index). |
| `switch` | Pole startu a `work_session_id`, `session_revision` původní aktivní relace. |
| `pause`, `resume`, `close` | `operation_id`, `context_revision`, `work_session_id`, `session_revision`. |
| `select-checklist` | Pole lokální změny relace a `selected_checklist` (`null` nebo platný index); pouze aktivní či pozastavená relace s aktuálním zadáním. |
| `propose-completion` | Pole lokální změny relace a textový `comment` (max. 4 000 znaků). |
| `recover`, `cancel` | Původní `operation_id`; request se načte z lokálního intentu. |
| `restore` | `operation_id`, `context_revision`; vrátí novou window capability a pauzu. |
| `record-list` | Bez window capability: `project_id`, `task_id`, `expected_head`; projektové záznamy a oddělené vlastní lokální činnosti. |
| `record-preview` | Bez window capability: `project_id`, `task_id`, `expected_head`, `record_id`, `output_index`, `version`, `page`. |
| `record-activity-preview` | Stejná čtecí pole, místo `record_id` vlastní `event_id`. |
| `record-attachment-options` | `work_session_id`; dostupné existující soubory aktuálního projektu a jejich aktuální HEAD. |
| `record-attach` | `operation_id`, `work_session_id`, `artifact_id`, `comment`, `selected_checklist`, `expected_head`, `privacy`; výslovně potvrzené připojení. |
| `record-offer` | `operation_id`, `work_session_id`, `event_ids`, `offer_revisions`, `comment`, `selected_checklist`, `state` (`draft`/`deferred`/`dismissed`). |
| `record-publish` | Pole nabídky bez `state`, navíc `expected_head`, `privacy`. |
| `record-amend` | `operation_id`, `work_session_id`, `record_id`, `record_revision`, `comment`, `selected_checklist`, `expected_head`. |
| `record-recover`, `record-cancel` | Původní `operation_id`; obnoví nebo před nativním zápisem zruší uložený intent. |
| `record-output` | `project_id`, `record_id`, `output_index`, `version` (`original`/`current`), `page`; readonly náhled. |
| `capture` | `context_revision`; vyžaduje aktivní, aktuálně oprávněnou relaci bez pending záměru. |

Mutace vrací také `operation.state`; replay odmítnuté operace se nesmí
vykládat jako úspěšné zahájení jen proto, že lze znovu přečíst kontext.
Lokální operace a nativní projektový zápis mají rozdílné, deterministicky
provázané operation ID. Podrobný kontrakt a crash boundaries stanovuje
[ADR 0088](adr/0088-task-work-context.md).

Lokální operační databáze je `.<node-filename>.task-work/contexts.sqlite`
u node konfigurace, mimo projektový Git. Jde o autoritu lokálních relací
s verzí schématu 1 a právy 0600 v adresáři 0700, nikoli obnovitelný index.
Neznámá verze, cizí vlastník nebo symlink se odmítají bez vymazání dat.
Flock konkrétní operace serializuje její replay a cancel mezi procesy;
SQLite writer transakce se nedrží přes Git, síť nebo providerový účinek.
Výběr checklistu používá existující jedinou lokální transakci s CAS a replay:
před commitem se neuplatní, po commitu se stejným operation ID vrátí tentýž
výsledek. Nemění Git ani index a nepřidává migraci či další crash boundary.

Cílené ověření:

```sh
python3 -m unittest tests.test_task_records tests.test_task_activities tests.test_task_work tests.test_task_work_http tests.test_ide_bridge_panel -v
M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' python3 -m unittest tests.test_task_work_browser -v
```

Testy s dočasnými projekty a skutečným Qt/HTTPS nedokládají instalaci ani
lidskou akceptaci běžného profilu. Celá závěrečná sada se spouští před předáním
celé dávky podle AGENTS, nikoli po každé její dílčí změně.
