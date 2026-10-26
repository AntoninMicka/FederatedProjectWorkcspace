<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Vizualizace roadmapy

V aplikaci otevřete **Nastavení → Roadmapa**. Pohled načte read-only projekci
feature dávek a zobrazí je v pruzích podle milestone. Silný obrys označuje
deterministickou kritickou cestu; přerušovaný zelený obrys plánované dávky,
jejíž všechny deklarované závislosti jsou dokončené a lze ji zahájit souběžně.

Graf lze filtrovat podle milestone a stavu. Uzel lze vybrat myší nebo klávesou
Enter/mezerník; detail ukáže přesné ID, zdroj, závislosti a vypočtenou vrstvu.
Tlačítko **Stáhnout SVG** vytvoří statický výstup pouze tehdy, pokud se od
načtení nezměnila revize žádného vstupního dokumentu.

Graf není editor. Názvy a stavy pocházejí z `TODO.md`, `BACKLOG.md`,
`WORK_LOG.md` a master roadmapy. Soubor `docs/roadmap-graph.json` obsahuje jen
stabilní ID, milestone a explicitní hrany. Nový uzel bez autoritativního
záznamu, neznámá závislost nebo cyklus zablokují celou projekci s konkrétní
diagnostikou; UI je samo neopravuje.
