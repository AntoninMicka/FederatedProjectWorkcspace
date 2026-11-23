<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Strukturované doplnění úkolů do roadmapy

Při ladění požadavku „doplnit do seznamu úkolů úkoly pro analýzu
a implementaci sw agenta“ byl dohledán úspěšný modelový běh s neplatným
návrhem Markdownu. Model nahradil řádek existujícího tasku, přidal nové
položky a `type: task` odsadil na stejnou úroveň jako jejich checkboxy.
Původní typové metadata se tak přiřadily jiné položce. Validátor správně
odmítl výsledek; původní roadmapa zůstala platná a nezměněná.

## Průchod

Při výstupu **Upravit vstup / Změny bloků** nad autoritativní roadmapou
s profilem `software-development/v1` rozpoznává aplikace také formulace
„doplň seznam úkolů o úkoly“, „doplnit do seznamu úkolů úkoly“ a anglické
„add tasks“. Uživatel může vybrat celý dokument, milník nebo dávku.
Samotný task nemůže být rodičem dalších úkolů; takový výběr se zastaví
před modelem s pokynem vybrat příslušného rodiče.

Role `task-output-roadmap-additions-v1` používá původní autorizovaný
Markdown Context Manifest v2 a stejný modelový rozpočet. Model dostane
uzavřené schéma `roadmap-additions`: rodiče z množiny skutečně viditelných
milníků a dávek, nové stabilní ID, názvy, jednořádkové popisy a závislosti.
Pod milníkem vznikne nová dávka s tasky; pod existující dávkou vzniknou
tasky přímo. Více milníků v témže souboru je podporováno. Typy, odsazení
a nezaškrtnuté checkboxy vytvoří aplikace. Při kolizi ID či neplatném obsahu
se návrh odmítne, ID se automaticky nepřejmenují.

Čistá transformace převede data na původní kanonický `markdown-patch`
s aplikací vypočtenými hash otisky. Vkládá se za vlastní metadata rodiče,
aby se jeho popis nepřesunul na novou položku. Původní položky se
negenerují znovu; jejich ID, text, typy, checkboxy, ručně zadané stavy,
checklisty a vlastní závislosti se kontrolují proti připnutému originálu.
Odvozené souhrnné stavy a zpětné vztahy se mohou přepočítat přidáním
nového tasku nebo jeho závislosti; to není změna ručně zadaného stavu.

Následuje úplná validace grafu a stávající společný editor s náhledem diffu
a výslovným potvrzením zápisu. [Výjimka ochrany](adr/0089-explicit-document-privacy-review.md)
zůstává samostatně potvrzená a připnutá. Model sám nic neukládá.
Starý odmítnutý běh se automaticky neopakuje ani neopravuje odhadováním
chybějících typů; původní surový výsledek zůstává v lokálním run journalu.

## Reuse a obnova

Používá se původní detekce přidávání úkolů z `roadmap_append_context`,
blokový Context Manifest a `markdown_patch.complete/apply`, registr rolí,
validátor grafu a native file-edit preview/confirm. Nová čistá serializace
nenahrazuje `PlanItems` ani nezavádí druhý plán nebo persistentní vrstvu.

Platí [ADR 0003](adr/0003-coordinated-operation.md) a
[ADR 0088](adr/0088-task-work-context.md). Před validací vzniká pouze
modelový výsledek v původním run journalu. Neplatná data nevytvoří
akceptovaný task outcome ani projektový commit. Platný návrh se uloží
do původního `TaskOutcomes`; jeho request nese použitou verzi doplnění.
Přerušení při zpracování nevede k automatickému modelovému retry.
Po finálním souhlasu používá zápis původní operation ID, CAS a native
journal; obnova před commitem je z journalu, index po commitu z HEAD.

Testy reprodukují chybné odsazení, ověřují více rodičů, menší rozsah,
zachování původních bajtů v LF/CRLF, závislosti, odmítnutí kolizí a vložení
řídicích polí. Browser průchod zpracuje české zadání přes kontrolu ochrany
až do potvrzeného zápisu. Používá lokální testovací model; živou akceptaci
skutečného uživatelského běhu tím nenahrazuje.
