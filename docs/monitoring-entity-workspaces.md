<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Samostatná GUI nástrojů a tabulková sestava

Upřesnění uživatele 12. 11. 2026, MON-08-09: filtry, pooly a úlohy mají
vlastní GUI; komplexní úloha je agregát tabulek bez vlastního editoru bloku.

Každá kategorie se otevírá z levé lišty na vlastní obrazovce s vlastním
nadpisem, účelovou tabulkou a samostatným formulářem. Původní společný
přepínač kategorií a jediný přepínaný formulář jsou odstraněny.

| Obrazovka | Obsah a vlastní editor |
| --- | --- |
| Zdroje | Kanál/hledání, interval a místní stav sběru; adresa a podmínky přístupu/uchování. |
| Filtry | Vstupní kanály, pravidla, cílový pool a využití; vlastní výběrová pravidla. |
| Pooly | Počet zpráv, retence, poslední potvrzený příjem; obsah, verze, filtry a pozorující uzly. |
| Úlohy zpracování | Vstupy, rozvrh, vykonavatel a stav; zadání, modelový režim a místo běhu. |

Komplexní úloha nemá formulář typu `task`. Agreguje výše uvedené tabulky.
Nad každou tabulkou jsou akce **Vytvořit nové** a **Přidat existující**.
Výběr existující položky připojí sdílenou definici bez kopírování; změna složení
se uloží ihned. Není zde režim úpravy sestavy, záhlavní formulář ani checkboxy.
Nová prázdná sestava vyžaduje pouze název; uložit ji lze před připojením
zpracování. Spuštění prázdné sestavy odmítne také backend. „Upravit“ u řádku otevře vlastní
obrazovku položky. Založení z agregátu použije její vlastní formulář a po
uložení ji připojí do sestavy. V samostatném katalogu výběr existující položky
otevře její detail; katalog již obsahuje všechny položky daného typu.
Samotné uložení nic nespouští ani neaktivuje.

Odpojení odstraní vazbu sestavy, ne sdílený blok. Pokud položku vyžaduje
jiné zvolené propojení, nelze ji odebrat a zobrazí se vysvětlení; nejprve je nutné
odpojit závislého spotřebitele. Neznámé ID se odmítne. Provozní stav zůstává
dostupný přes historii, vydané zprávy ve Výstupech.

Přehled zdrojů rozlišuje prázdný kanál, chybějící filtr, nulovou shodu,
opakované revize, nově uložené revize, HTTP 304, chybu a unknown. Počítají
se normalizované položky, vybrané obsahové revize a nově přijaté revize,
nikoli počet interních membership/observation řádků. Počty se uloží ve stejné
transakci jako pool a dokončení příjmu. Nevzniká uložená kopie odmítnutého textu.
Starší záznam bez počtů ani absence výsledku v omezeném přehledu nejsou
vydávány za úspěšnou kontrolu s nulovým nálezem.

## Vlastnictví a obnova

Reuse/adapt: původní katalog a výpočet využití, `MonitoringBlocks.save`,
Reporting/Workspace CAS, journal a receipts podle
[ADR 0082](adr/0082-composable-monitoring-and-message-pools.md).
GUI drží pouze rozpracovaný návrh. Pokus o uložení zachovává payload,
base HEAD a operation ID; nevytváří automatický nový pokus po unknown.
Rozepsaný editor chrání původní guard. Nejasné uložení sestavy lze zopakovat
explicitní akcí se stejným požadavkem.
Read-only a native RBAC se nemění. Pád před commitem obnovuje původní
journal, po commitu se dohledá původní receipt. Nová persistentní vrstva
ani writer nevznikají. Vytvoření položky a její připojení jsou dva zápisy:
pád mezi nimi zachová položku v katalogu; uživatel ji připojí přes Přidat
existující. Chyba připojení nesmí smazat již uloženou položku.

`tests.test_monitoring_blocks_browser` v reálném Qt/WebEngine kontroluje
oddělené formuláře, nepřítomnost task editoru, čtyři tabulky agregátu,
akce nad každou tabulkou, pool vytvořený samostatným formulářem,
odmítnutí odpojení nutného vstupu, odpojení poolu bez smazání a opětovné
připojení existujícího poolu bez duplicity.
Pokračuje skutečným sběrem syntetického RSS, návrhem, vydáním zprávy,
read-only stavem a uložením týdenního rozvrhu. Jde o izolovaný profil,
nikoli ruční akceptaci používaného desktopu nebo vzdálené nasazení.
