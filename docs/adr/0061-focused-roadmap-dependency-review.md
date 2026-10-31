<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0061 — Zaměřený scan a review závislostí roadmapy

Datum: 31. 10. 2026. Stav: upřesnění schváleného záměru, implementace k review.
Návaznost: `PLAN-SEMANTIC-AUDIT-01`; tento řez neuzavírá celý sémantický audit.
Samostatná větev `feature/roadmap-dependency-scan` z `develop` `8bca9a5`
po uživatelem doručeném PR #117.

## Potřeba a rozsah

Uživatel požaduje doplnění skutečných předpokladů před plánováním fronty
práce. Pilotní inference nad aktuální roadmapou vrátily 26 neplatných návrhů
bez použitelné hrany; pilot byl zastaven a rozběhnutý výsledek označen unknown.
Tyto výsledky nedokládají úplnost roadmapy ani jedinou konkrétní příčinu
selhání modelu. Vynucení úzkého scope a ověřitelného zdroje je proto
aplikační podmínkou, nikoli slibem správnosti modelové odpovědi.

Nový režim doplňuje stávající refinement, nenahrazuje původní deep-check.
Může navrhovat jen chybějící `depends_on` existujícího otevřeného focus ID
na existující canonical ID. Nemění typy, názvy, hierarchii, completion,
nevytváří úkoly a neodstraňuje závislosti. Pracovní fronta, kompilát podkladů,
pluginové řízení práce a agent adaptéry zůstávají mimo tento řez.

## Návrhy a review

`fpw-roadmap-dependency-input-v1` připíná jedno focus ID, současné závislosti,
katalog cílů a evidence s artifact ID, cestou, digestem a intervalem řádků.
Současná definice se ohraničuje skutečnými uzly validovaného task graphu;
historické podklady jsou kontext, nikoli nové zadání. Odkazované texty mají
omezené výňatky, nikoli automatickou rekurzi do všech projektových dokumentů.
Jediný výňatek má nejvýše 32 KiB, celkový modelový vstup limit `MAX_FILE`.

Ollama dostane explicitní Context Manifest a focus input ID. Tento režim
vyžaduje existující same-node binding a konzervativně označuje odvozený
kontext local-only. Nezavádí nového providera, transport ani sdílení oprávnění.

`fpw-roadmap-dependency-proposal-v1` má decision propose / no-change /
needs-context, přesné focus ID, vysvětlení a seznam hran. Každá hrana nese
target ID, evidence ID, přesnou citaci a zdůvodnění nezbytnosti. Aplikace
kontroluje ID, focus, self-edge, duplicity, již existující hrany, citaci a
cyklus proti připnutému grafu. Samotný titulek bez dalšího obsahu nestačí;
mechanická kontrola substance není sémantickým důkazem správnosti.

Záznamy mají oddělený mode `dependency-check` ve stejné node-local queue.
Fingerprint váže projekt, HEAD, policy revision a celý připnutý vstup.
Staré režimy ani jejich review se nemažou. Failed, unknown a needs-context
nejsou úspěšně dokončenou analýzou a automaticky se znovu nespouštějí.
Nový source HEAD vytvoří nové fingerprinty; tento řez nepřidává automatický
retry nezměněného neúspěšného vstupu.

Lidské schválení samo roadmapu nemění. Samostatné preview složí vybrané
schválené návrhy a validuje celý společný kandidát včetně cyklů mezi návrhy.
Kontrola zdrojových bajtů proti původnímu snapshotu se před apply opakuje.
Apply vyžaduje explicitní preview SHA-256. Stale HEAD blokuje nový zápis;
výsledek již zahájené transakce se dohledává podle její identity.
Vložení hrany používá existující typed reconciliation a nativní writer,
ale mění bajty jen vložením jedné relation. Respektuje body-relative řádky
frontmatter dokumentů, zachovává nezměněné prefixy a CRLF a nepřebírá metadata
podúkolů do rodičovské dávky. Linked definice se upraví ve svém původním souboru.

## Recovery hranice

Základní nativní writer, journal a index zůstávají podle
[ADR 0003](0003-coordinated-operation.md). Nový lokální intent nepatří do
obnovitelného projektového indexu a nesmí být ztracen jako cache.

| Hranice | Obnova |
| --- | --- |
| Připravená queue před dispatch | Bez externího účinku; limit omezuje počet nových dispatchů. |
| Running po přerušení | Při příštím zamčeném scanu přejde na unknown; bez automatického retry. |
| Přijatý návrh před apply | Projekt beze změny; lze vrátit review mezi pending. |
| Dependency intent v SQLite | Připnutý projekt, HEAD, IDs a preview digest; review těchto IDs je zmrazené. |
| Intent před native operací | Znovu ověřit původní review; při novém HEAD stale. Nezahájený intent lze explicitně zrušit. |
| Během native journalu | Obnovit stejnou operaci podle ADR 0003; nezakládat další operation ID. |
| Native commit/receipt před queue outcome | Získat tentýž native receipt a dokončit outcome, bez druhého commitu. |
| Po outcome, ztracená odpověď | Vrátit uložený outcome stejného requestu. Jiné IDs/digest pod týmž ID se odmítnou. |

SQLite writer lock se nedrží přes nativní transakci. Příprava a zrušení
nezahájeného intentu respektují pořadí native writer lock → krátká queue
transakce. Zrušení po vzniku native operace je zakázané, vyžaduje recovery.
No-change review pouze atomicky aktualizuje lokální review stav, nevytváří
projektový commit. Souběžná zrušení a změny rozhodnutí se znovu kontrolují.

Přehled ve Workspace nabízí u rozpracovaného intentu obnovu původní operace.
TUI zobrazuje diff před potvrzením a umí obnovit tentýž intent. CLI dovoluje
opakovat apply s původním operation ID a digestem; je dostupné i explicitní
zrušení intentu, pokud ještě nezačal native zápis.

## Reuse a hranice ověření

Reuse/adapt: task graph, refinement queue a reconciliation, bezpečné webové
review, TUI, ContextBuilder, OllamaAdapter/OllamaRuns a Workspace.transact.
Nový modul `roadmap_dependencies` izoluje zaměření a validaci. Veřejný i
lokální soukromý reuse katalog byly nahlédnuté; soukromé názvy ani kód se
nepřebírají. Nový broker, databázový plán ani další writer nejsou potřeba.

Implementační a provozní evidence je v [návodu](../roadmap-dependencies.md).
Celoplošný scan ani lidské přijetí nových hran nejsou odvozené od toho, že
prošly syntetické testy či jedno živé inference. Cílený scan bez chybějících
citací není sám o sobě důkazem úplnosti celé roadmapy.
