<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Prezentace z konkrétní vydané zprávy

V detailu vydané zprávy je po potvrzení dostupné **Vytvořit prezentaci ze
zprávy**. Použije přesné zobrazené vydání, jeho HEAD a SHA-256. Neprovádí
další výzkum, webové hledání ani modelový požadavek. Nevydané návrhy nejsou
vstupem této akce. Native RBAC a právo zápisu zůstávají původní.

Výsledek je běžný dokument prezentace v původním formátu. Poznámky slidů
obsahují původní report ID, commit a hash. Metadata s tagem
`monitoring-derived-presentation` a prefixem `fpw-report-presentation-v1:`
uchovávají uzavřený PinnedRef; nepředstavují grant ani autoritu k dispatch.
Prezentace dědí privacy zprávy. Lze ji dál upravovat stávajícím editorem.

Detail zprávy odkazuje na své prezentace, editor prezentace zpět na zdroj.
Změna zdrojových bajtů nebo nahrazení ReportSnapshot novější revizí označí
prezentaci jako potenciálně zastaralou. Její obsah se nepřepisuje.
U změněného Markdown dokumentu zpětná akce výslovně otevírá aktuální zdroj;
původní pin zůstává v poznámkách a metadatech. Pokud zdroj v aktuálním
přehledu chybí, GUI tuto nedostupnost přizná.

Nové potvrzení nad změněným zdrojem může vytvořit další prezentaci. Nad
totožnými zdrojovými bajty se použije existující odvozená prezentace včetně
jejích případných ručních úprav. Historické prezentace bez strukturovaného
source pinu se automaticky nepřeznačují ani neodhadují z volných poznámek.

## Limity a obnova

Jde o počáteční deterministickou osnovu: nejvýše deset oddílů, dvanáct
řádků na slide a 800 znaků na řádek. Úplný text se tím nemění; je stále
v dostupné zdrojové zprávě. Výsledek není automatické publikování ani
spuštění presenteru.

Reuse/adapt: `new_deck`, `new_slide`, `encode_deck`, `Artifacts.save` a
Reporting/Workspace journal/CAS/receipt podle
[ADR 0003](adr/0003-coordinated-operation.md). Obsah prezentace a metadata
původu vzniknou jedinou původní Git transakcí. Před commitem rozhoduje
journal; po commitu lze obnovit index a dohledat receipt.

Operation ID a artifact ID jsou deterministické pro zdrojové vydání a
zobrazený HEAD. Po ztracené odpovědi se původní receipt ověřuje ještě před
odmítnutím starého HEAD. V opačném případě musí HEAD zůstat aktuální až do
Git CAS. Nová revize zdroje nikdy nepřepíše starou prezentaci. Nevzniká
druhý writer ani nový provozní journal. Přenos probíhá původním podepsaným
Git syncem, nikoli přenosem SQLite nebo stavů lokálních běhů.

## Ověření

`tests.test_report_outputs` ověřuje potvrzení, stale HEAD, opakování původního
požadavku, použití existující prezentace, děděnou privacy, opravu zdroje,
starý nezměněný deck a skutečné ukončení procesu před/po Git ref.
`tests.test_monitoring_http` ověřuje read-only odmítnutí a native API.
`tests.test_report_outputs_ui` kontroluje zachování zobrazeného HEAD i po
pozdějším pollu a odmítnutí akce po změně projektu. Podepsaný dvouuzlový
test přenáší report i prezentaci s totožnou provenance bez modelového journalu.
Prohlížečový průchod je součástí `tests.test_monitoring_blocks_browser`.
Izolované testy nejsou ruční akceptací ani nasazením na Omnii.
