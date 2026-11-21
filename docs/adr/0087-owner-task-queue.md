<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0087 — Jedna pracovní fronta napříč projekty

Datum: 21. 11. 2026. Rozhodnutí podle přímého zadání uživatele: fronta má
samostatnou sekci, změnu pořadí přetažením a úkoly z více projektů.
Navazuje na ADR 0060/0062. Přiřazování úkolů jiným uživatelům je mimo rozsah.

## Model a rozhraní

Fronta patří aktuálnímu vlastníkovi (stávající lokální autor / přihlášený účet),
nikoli otevřenému projektu. Identita položky je dvojice project ID / task ID.
Kanonické definice, závislosti a dokončení zůstávají v projektovém Gitu.
UI má vlastní sekci Fronta úloh dostupnou i bez otevřeného projektu. Každý řádek
uvádí projekt, nabízí detail úkolu a projektovou správu: příznaky, opravy,
zprávy a předání do IDE. Pořadí lze měnit přetažením nebo klávesnicí přes šipky.

Jeden privátní JSON schema 2 obsahuje celkové `order`, revizi a mapu
`projects` s původními projektovými stavy a revizemi. Název je SHA-256
kanonického JSON `['owner', owner_id]` ve stávajícím `.node.json.task-queues/`.
Projektový stav je výřez téže fronty, ne druhá autorita. Změna pořadí úkolů
jednoho projektu zvýší i jeho revizi; proložení cizím projektem bez změny jeho
relativního pořadí původní IDE balíček nezneplatňuje. Příznaky a audit zůstávají.

Původní projektové API zůstává pro přidání a správu položek a pro IDE.
Nové akce `owner-status` a `owner-move` na `/v1/task-queue` poskytují celou
oprávněnou frontu. `owner-status` přijímá pouze `action`. `owner-move` potřebuje
`project_id`, `task_id`, výsledný nulový `target_index`, `revision`,
`view_revision` a `expected_head` daného projektu. `view_revision` váže viditelný
rozsah, pořadí, projektové revize a režim čtení; změna práv nebo dostupnosti
projektu nesmí posunout cílový index na jinou položku bez nové kontroly.
Vlastník se odvozuje na serveru, nepřijímá se z requestu.

Web před čtením každého projektu kontroluje oprávnění a běžnou privacy
validaci. Neoprávněné projekty nezveřejňuje; u dočasně nedostupného oprávněného
projektu uvádí problém bez neověřeného obsahu. Odkazy se nemažou. Ostatní projekty
zůstávají použitelné. Reader může číst svou frontu; měnit může pouze položky
upravitelného projektu. Nezobrazené odkazy při přesunu zachovávají své pozice.
Server nedovolí přidat porušení pořadí předpokladů, ani ve vadné frontě.

## Migrace, souběh a crash boundaries

Reuse/adapt: `TaskQueue`, stejný neblokující flock, atomic replace/fsync,
`queue_faults`, projektový journal lock a stávající IDE projekce. Nevzniká nová
DB, journal, plán ani synchronizovaná kopie pracovního výběru.

Zámek je nově společný pro vlastníka napříč projekty. Pořadí zámků zůstává
fronta → journal dotčeného projektu; síťová volání ani čtení cizích projektů
se pod writer zámkem neprovádějí. Zápis fronty nemění Git, index ani journal.
Přes více projektových Gitů se neprovádí atomická transakce.

1. Dokud owner soubor neexistuje, reader sestaví pohled z původních schema 1
   front registrovaných projektů daného vlastníka. Zachová jejich pořadí,
   projektové revize, held flags a audit; projekty proloží v pořadí registrace.
   Čtení owner soubor nevytváří. První skutečná mutace uloží celý bundle jednou.
2. Před zápisem se ověří revize fronty, rozsah pohledu, HEAD a závislosti.
   Migrační vstupy i nový soubor podléhají původním kontrolám vlastníka,
   oprávnění 0600, JSON a zákazu symlinků. Poškození se nesmí tiše vynulovat.
3. Pád před replace ponechá původní owner soubor, nebo původní schema 1 fronty.
   Osamocený temporary není autorita. Pád po replace zveřejní celou novou
   frontu včetně projektových výřezů. Fsync potvrdí trvanlivost; chyba po replace
   je `QueueOutcomeUnknown` a vyžaduje nové načtení, nikoli automatický retry.
4. Staré projektové soubory zůstávají zachované, ale po vzniku owner souboru
   se už nepoužijí. Nelze z nich znovu oživit odstraněné položky. Smazání nebo
   downgrade owner souboru není recovery. Při přechodu nemají současně běžet
   staré a nové backendy nad stejnými lokálními frontami: starý writer používá
   projektový zámek a nový owner formát nezná.
5. Původní projektové mutace i globální přesun zapisují tentýž soubor pod týmž
   owner zámkem. Cizí projekt se nepřepíše. Projektové revize pro IDE i pořadí
   se zveřejní jedním replace; neměnné balíčky a lidské receipts se nemění.

Limit owner souboru je 8 MiB a 10 000 položek; přesah mutaci odmítne před
replace, bez ztráty původních front. Fyzická trvanlivost při výpadku napájení
nadále závisí na filesystemu a zařízení. Testy s přerušením nejsou lidská
akceptace běžného profilu ani důkaz produkčního víceuzlového provozu.
