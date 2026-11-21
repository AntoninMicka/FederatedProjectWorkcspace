<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Pracovní kontext úkolu — PLAN-TASK-WORK-01-A

V roadmapě otevřete detail konkrétního nedokončeného úkolu a použijte
**Zahájit úkol**. Start ověří projektová oprávnění a předpoklady a označí task
jako Probíhá přes běžný projektový writer. Úkol nemusí mít checklist.

Nad obsahem se zobrazí pracovní kontext a ovladače:

- **Pozastavit** uvolní aktivní kontext tohoto okna; task nepřepne na Odloženo.
- **Pokračovat** znovu ověří oprávnění a zadání vybrané pozastavené relace.
- **Ukončit relaci** uzavře pracovní úsek, nikoli úkol v roadmapě.
- **Navrhnout dokončení** uloží komentář jako lokální pending návrh relace.
  Task ani checklist se nezaškrtnou. Projektová publikace/přijetí návrhu bude
  navazující část D/F; tento ovladač je nyní nezajišťuje.
- Jiný úkol zahájíte z jeho detailu. Potvrzené přepnutí pozastaví původní
  relaci. Nové zadání stejného tasku uzavře starý úsek a zachová oba piny.

Výběr projektu nebo dokumentu sám pracovní kontext nepřepne. Relace jiného
projektu si uchová původ a vlastní identitu; shodná task ID různých projektů
se nezamění. Samotný start ani pokračování nevolá model nebo hledání.

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

## Rozsah tohoto řezu

Implementované jsou pracovní relace a základní ovládání. Pravý panel s celým
zadáním/checklistem (B), automatická evidence činností (C), komentované
projektové záznamy (D), propojení LLM běhů (E) a jejich společné recovery (F)
zůstávají navazujícími úkoly stejné dávky. Celou dávku tímto nelze akceptovat.

`capture` vrací neměnnou identitu původní relace a jejího zadání pro budoucí
C/E. Existující importy, editace a modelové běhy ji zatím samy nepoužívají.
Nabídka obsahuje nejvýše 50 posledních relací okna plus jeho aktivní relaci;
starší uložené relace se tím nemažou. Historický index nedostává novou autoritu.

## API, úložiště a ověření

`POST /v1/task-work` používá aktuální autentizaci aplikace. `window` vygeneruje
window ID a capability; do requestu se nesmí vložit cizí user/node ID. Další
akce jsou scoped touto dvojicí. Credential se nezapisuje do projektového Gitu
ani do request payloadů lokálního journalu; v DB je pouze jeho hash.

| Akce | Další pole vedle `action`, `window_id`, `window_token` |
| --- | --- |
| `status` | Žádná; čte ověřený stav a případný pending záměr. |
| `inspect` | `project_id`, `task_id`, `expected_head`; vrátí aktuální digest fragmentu pro start. |
| `start` | `operation_id`, `context_revision`, `project_id`, `task_id`, `expected_head`, `fragment_sha256`, `selected_checklist` (`null` nebo platný index). |
| `switch` | Pole startu a `work_session_id`, `session_revision` původní aktivní relace. |
| `pause`, `resume`, `close` | `operation_id`, `context_revision`, `work_session_id`, `session_revision`. |
| `propose-completion` | Pole lokální změny relace a textový `comment` (max. 4 000 znaků). |
| `recover`, `cancel` | Původní `operation_id`; request se načte z lokálního intentu. |
| `restore` | `operation_id`, `context_revision`; vrátí novou window capability a pauzu. |
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

Cílené ověření:

```sh
python3 -m unittest tests.test_task_work tests.test_task_work_http tests.test_ide_bridge_panel -v
M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu' python3 -m unittest tests.test_task_work_browser -v
```

Testy s dočasnými projekty a skutečným Qt/HTTPS nedokládají instalaci ani
lidskou akceptaci běžného profilu. Celá závěrečná sada se spouští před předáním
celé dávky podle AGENTS, nikoli po každé její dílčí změně.
