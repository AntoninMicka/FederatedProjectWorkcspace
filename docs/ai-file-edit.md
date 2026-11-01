<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Úprava vybraného dokumentu pomocí AI

AI-FILE-EDIT-01 přidává explicitní výstup **Upravit vstup** v režimu Úkol.
Uživatel vybere cílový Markdown dokument a Ollama backend. Cíl se přidá mezi
vstupy Context Manifestu; samotný výběr vstupu neopravňuje k zápisu.
Dosavadní omezení externích backendů na kontext bez projektových artefaktů
zůstává platné. Prezentace a jiné formáty tento postup odmítne.

Výsledek je dočasný návrh. Akce **Zkontrolovat úpravy ve společném editoru**
otvírá existující raw editor a umožní obsah dál upravit. Název a metadata
jsou při této úpravě zamknuté. **Uložit** ukáže diff skutečného obsahu editoru,
ID dokumentu a výchozí Git revizi. Až zaškrtnutí souhlasu a následné
**Potvrdit a uložit** dovolí zápis do původního dokumentu. Zavření dialogu
ponechá návrh rozpracovaný; odchod z editoru používá společnou ochranu
neuložených změn. Výsledek lze také zahodit přímo v konverzaci.

Zápis zachovává ID, název a ostatní metadata dokumentu, mění obsah a provenance
na `llm-transformed`. Native operation intent a výsledek úlohy obsahují vazbu
na task, run a manifest. Nevytváří se nový artefakt ani druhé plánovací úložiště.
Stejný postup lze použít pro Markdown roadmapy; celý výsledný task graph se
ověří jak v náhledu, tak pod zámkem těsně před zápisem. Neplatný graf se neuloží.

## Kontrakt a kontrola přístupu

Uzavřený `ExplicitTaskPlan` s výstupem `file-edit` vyžaduje
`target_artifact_id`, zdroj `artifacts`, zahrnutí cíle mezi vybrané artefakty
a `local-ollama`. Stávající výstupy a jejich serializace zůstávají kompatibilní.
Před voláním modelu se ověří typ cíle, current HEAD, oprávnění, replika a privacy.
Soukromí cílového dokumentu nesmí být nižší než soukromí kontextu.

`POST /v1/tasks/file-edit/preview` přijímá `project_id`, `task_id` a volitelné
`body`. Bez těla sestaví původní návrh (včetně patche); s tělem ověří aktuální
obsah společného editoru. Vrací původní dokument, výsledné tělo, diff a přesné potvrzení s digestem.
`POST /v1/tasks/file-edit/confirm` přijímá pouze `project_id`, `task_id`,
`artifact_id`, `base_head`, `body`, `approval_digest`, `approved:true` a stabilní
`operation_id`. Kontroluje vlastnictví úlohy, členství a oprávnění zapisovat,
projekt, cíl i shodu s náhledem. Read-only replika a síťový přístup k local-only
obsahu jsou odmítnuty. Obecná akce pro vytvoření artefaktu tuto úlohu odmítá.

## Crash boundaries a obnova

Používá se existující `TaskOutcomes` a `Artifacts.save` / `Workspace.transact`.
Platí nativní Git/journal/index obnova z [ADR 0003](adr/0003-coordinated-operation.md);
nová je hranice mezi potvrzením výsledku úlohy a spuštěním nativní operace:

1. Generování a náhled nic nezapisují do projektového Gitu.
2. Přesné potvrzení včetně operation ID se trvale připne do existujícího
   result slotu TaskOutcomes. Pád před touto hranicí vyžaduje nové potvrzení.
3. Native writer pod projektovým zámkem kontroluje HEAD, sémantiku a stále
   platný souhlas, poté převezme journal, soubory, Git commit a obnovu indexu.
4. Po nativním receiptu se TaskOutcomes dokončí odkazem na upravený dokument.
   Pád mezi commitem a dokončením výsledku obnoví původní operaci; nový commit
   se nevytváří. Při neznámém výsledku editor uchová přesné potvrzení a zamkne
   tělo. Opakované uložení pošle stejné operation ID, tělo i digest.

Po obnovení konverzace nabízí připnutý návrh **Dokončit potvrzené uložení**.
Jiný obsah pod stejným potvrzením se odmítá. Pokud native journal ještě nemá
operaci, lze souhlas zahodit; kontrola journalu a zrušení probíhají pod stejným
projektovým zámkem. Jakmile native operace začala, zahodit ji tímto způsobem
nelze a je třeba dokončit původní obnovu. Změna HEAD před zahájením native
operace se odmítne; nevzniká automatické přepsání novějšího dokumentu.

## Ověření a ruční akceptace

`tests.test_task_file_edit` ověřuje návrh bez zápisu, přesný cíl a uživatelské
úpravy, provenance, chybné potvrzení, zrušení, stale HEAD, soukromí, oprávnění,
nepodporované formáty, neplatnou roadmapu a obnovu bez duplicitního commitu.
Samostatné procesy končí přes `os._exit` před native operací, po přípravě
journalu, po aplikaci souborů, po posunutí Git reference a před dokončením
TaskOutcomes. Qt scénář `tests/ui/page_layout_smoke.py` ověřuje společný editor,
checkbox a zrušení diffu i opakování po ztracené odpovědi.

Ruční akceptace v běžícím uživatelském profilu je samostatná: vybrat skutečný
Markdown, zadat změnu přes Ollama, zkontrolovat a případně upravit diff,
potvrdit uložení a ověřit původní ID, obsah a historii. Ověřit i zahození
návrhu a odchod s neuloženými změnami. Izolované testy tuto akceptaci ani
ověření skutečného modelu nenahrazují.

## Patch namísto celého dokumentu

Nové UI ve výstupu **Upravit vstup** nabízí volbu **Patch** (výchozí) nebo
**Celý obsah (jen malé soubory)**. Od **32 KiB UTF-8 těla nebo 500 řádků**
backend vždy vyžaduje patch, i pokud klient požádal o celé tělo či použil
starší kontrakt bez volby. Limit se vyhodnocuje ze skutečného dokumentu
připnutého ke vstupní Git revizi před dispatch. Starší uložené návrhy lze dál
otevřít a dokončit; jejich obsah se zpětně nepřepisuje na nový formát.

Patch má uzavřený výstup `artifact-patch` s `schema_version:1`, `title` a
`edits:[{"before":"původní úsek","after":"nový úsek"}]`. Název přebírá backend
z cílového dokumentu. `ExplicitTaskPlan` přijímá volitelné `edit_format:patch|full`;
bez této volby zachovává serializaci a digest dosavadního plánu. Skutečný patch
připíná role `task-output-file-edit-patch-v2` v Context Manifestu; předchozí
patch role v1 i role pro celé tělo zůstávají zachované pro původní běhy.
Revize v2 výslovně zakazuje stejné bloky před/po a omezuje délku kotvy také
v modelovém JSON schématu. Autoritativní limit 4096 UTF-8 bajtů dál ověřuje backend.

Každý blok `before` musí v původním těle odpovídat přesně jednou, včetně
Unicode, mezer a konců řádků. Všechny bloky míří do původního těla; neaplikují
se postupně do výstupu předchozí změny. Pořadí návrhu nerozhoduje, překryv,
chybějící nebo opakovaný úsek se odmítne. Vložení používá existující jednoznačnou
kotvu, která se ponechá v `after`; smazání má prázdné `after`. Prázdné `before`
je dovoleno jen pro jedinou změnu prázdného dokumentu. Limit je 64 změn,
4096 UTF-8 bajtů na kotvu a 64 KiB celého seznamu změn. Patch nepřijímá cesty,
příkazy ani dodatečná pole. Není zde fuzzy aplikace, shell ani obecné `git apply`.

Po dokončení modelu se patch sestaví proti neměnnému původnímu tělu v paměti.
Ověří se výsledný Markdown i celý task graph; neplatný patch či celý dokument
místo vynuceného patche se odmítne bez dalšího modelového požadavku. Návrh se
uchová jako krátký patch v existujícím TaskOutcomes. Průběžný přenos a karta
návrhu ukazují čitelné bloky před/po. Společný editor otevře až sestavené tělo,
které lze dále ručně upravit. Následný diff, souhlas, kontrola HEAD, provenance
a nativní zápis zůstávají společné s úpravou celého těla.

Nevzniká nová crash boundary persistentního zápisu. Schválení stále trvale
připíná přesné výsledné tělo a operation ID před nativní operací. Obnova
použije toto tělo; patch se po částečném zápisu ani po commitu podruhé
neaplikuje. Neuložený patch nepřepisuje novější HEAD ani rozpracovaný editor.
Návrh bez změny se odmítá jako `patch-no-change`, příliš velká kotva jako
`patch-anchor-too-large`, nenalezená či nejednoznačná kotva jako
`patch-anchor-mismatch` a překryv jako `patch-overlap`. Stream vrací konkrétní
českou diagnostiku a `outcome:invalid-proposal` se stavem 422. Úspěšně přijatá
providerová odpověď s neplatným návrhem není neznámý přenos: OllamaRuns zůstává
`succeeded`, ale návrh v TaskOutcomes ani zápis dokumentu nevznikne. Další
modelový požadavek se automaticky nevysílá.

Regrese `tests.test_document_patch` zahrnuje hranice velikosti, vynucení i pro
starší klienty, přesnost a nejednoznačnost kotev, překryv, limity, cyklus roadmapy,
ruční úpravu výsledku, zrušení, stale HEAD, ztracenou odpověď a skutečný pád
procesu během nativního zápisu. Qt smoke ověřuje stream patche a otevření či
zahození sestaveného návrhu. Ruční akceptace se skutečným modelem zůstává
samostatná; velikost kontextu modelu se touto změnou nezvětšuje.

## Průběžný přenos a časové limity

Lokální explicitní úlohy v UI, včetně **Upravit vstup**, používají
`/v1/tasks/route-stream` a existující Ollama NDJSON parser. JSON obálka návrhu
se v UI nezobrazuje; průběžně se promítá text pole `content`. Tento text je
pouze dočasná projekce. Až validní finální providerový rámec a validace
výsledku úlohy vytvoří návrh pro společný editor.

Čas se měří na backendu monotónně od zahájení dispatch. **Soft limit je
180 sekund**, automatický **hard limit 360 sekund**. Soft limit nic neruší;
UI nabídne **Ukončit běh** nebo **Prodloužit na 30 minut**. Výslovné prodloužení
před hard hranicí nastaví celkový hard limit na **1800 sekund od začátku
běhu**, nikoli dalších 30 minut. Další prodloužení tuto hranici neposune.
Ukončení je dostupné i před soft limitem. Backend rozhodnutí přijímá přes
`/v1/tasks/run-control` pouze pro vlastníka daného projektu a run ID s aktuálním
oprávněním zapisovat; endpoint má samostatnou HTTP obsluhu vedle generování.

Řídicí stav a heartbeat jsou v paměti aktivního požadavku, nevzniká nová DB
ani obnovení providerového běhu. Hard limit, ukončení nebo ztráta klienta
přeruší místní upstream socket. To nedokazuje ukončení vzdáleného výpočtu.
Po dispatch je neúplný výsledek `unknown`, s diagnostikou důvodu v existujícím
OllamaRuns journalu; původní run se nesmí znovu odeslat. Pád procesu ztrácí
jen řízení aktivního spojení; durable `dispatching` zůstane při obnově
neopakovatelným `unknown`. Částečný dokument ani jeho změna se nevytvoří.
Po validním finálním rámci deadline končí; následné získávání runtime metrik
už nemění dokončený výsledek na timeout. Nativní potvrzení diffu a recovery
zápisu z předchozí sekce zůstávají beze změny.

Regrese `tests.test_task_stream` ověřuje přesné hranice 1×/2×/10×, opakované
prodloužení, dokončení, ukončení socketu, skutečný upstream bez prvního rámce,
vlastnictví a role přes HTTPS, obsluhu ukončení vedle obsazené aplikační fronty
a durable zákaz redispatch. Qt smoke ověřuje ovládání limitu, NDJSON deadline
události a čitelný průběžný text. Skutečný model a uživatelský profil vyžadují
samostatnou ruční akceptaci podle streaming checklistu.
