<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Kalendář zpracování aktuálních bloků

Zpracování nabízí ruční, denní, týdenní, měsíční, čtvrtletní a roční rozvrh.
Interval sběru RSS je stále samostatný a neznamená volání modelu.
Týden začíná v pondělí, měsíc prvním dnem, čtvrtletí v lednu/dubnu/červenci/
říjnu a rok 1. ledna. Čas a kalendář používají uloženou IANA časovou zónu.

První tick po hranici aktuální periody a nastaveném čase smí připravit jeden
návrh. Při návratu offline uzlu se nezpracovává neomezený backlog; obslouží
se aktuální perioda. Vstupy určuje samostatné pole „Zprávy za posledních dní“
a při spuštění se zmrazí. Volba měsíční periody sama nepřepíná vstupy z poolu
na vydané týdenní zprávy a nenahrazuje analytickou syntézu WatchSynthesis.

Opakovaný tick a restart používají stejné ID `ident(block_id, kind+':'+slot)`.
Denní rozvrh zachovává původní ID. Podzimní opakování hodiny má jediný denní
slot; při jarním přeskočení času může tick proběhnout po dosažení nejbližšího
pozdějšího místního času. Nejde o násobky 24 hodin nebo 30 dnů.

Uložení nepovoluje místní běh. Změněná revize vyžaduje nové explicitní místní
zapnutí; jiný uzel ji nesmí automaticky převzít. Starší uzly nové enum hodnoty
odmítnou, proto je před přenosem těchto definic nutné aktualizovat oba uzly.

Reuse/adapt: původní bloková definice, ZoneInfo, effect flock, frozen intent,
block_jobs, backend run journal a explicitní review. Nevzniká nový writer
ani scheduler. Crash boundaries z [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md)
zůstávají: durable intent před modelem, unknown po nejistém dispatch, původní
receipt při vydání. Zánik procesu neopravňuje opakovat modelový účinek.

Ověření: `tests.test_processing_calendar` a příslušné testy
`tests.test_monitoring_blocks` kontrolují hranice, přestupný rok, DST,
restart, následující týden a změnu revize bez nového souhlasu. Skutečný
Qt/WebEngine scénář `tests.test_monitoring_blocks_browser` kontroluje nabídku
všech period a uložení týdenního rozvrhu formulářem.
