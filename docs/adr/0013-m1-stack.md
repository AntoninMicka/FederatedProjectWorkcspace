# ADR 0013 — Výchozí stack pro navazující M1

Datum: 2026-09-09. Stav: přijato, **designed**, podložené uvedenými PoC. Uzavírá volbu technologií M0-06, nikoli celý Gate M0 ani produkční připravenost.

## Rozhodnutí

| Vrstva | Zvolený základ | Důvod a důkaz |
| --- | --- | --- |
| Aplikační jádro desktopu a serveru | Python 3.11+, jeden aplikační backendový proces | Zachovat validátory a koordinovaný Workspace. Linux crash/CAS testy ADR 0003, uživatelské headless demo na Omnia ARMv7 a SSD ve WORK_LOG. |
| Projektové úložiště | Git CLI | ADR 0005 porovnalo Git CLI a libgit2; port nepřinesl doloženou potřebu přepsat koordinaci. Git zůstává autorita. |
| Lokální persistence | Python sqlite3, oddělený index a journal | ADR 0002/0003: index obnovitelný z validovaného commitu, journal autorita nedokončených operací mimo Git. |
| Metadata | Stávající omezené JSON/YAML validátory, PyYAML 6.0.3 | Zachovat ověřené schéma a parserové limity; rozšíření v M1 musí řešit V-04/V-05 explicitně. |
| Desktop | PySide6 + Qt 6 WebEngine | ADR 0010: skutečný callback, token interceptor, start/zavření/restart a pád rendereru; měření zahrnuje Chromium potomky. |
| Sdílené UI | HTML/CSS/JavaScript přes same-origin loopback HTTP | ADR 0006/0007/0010: token pouze v nativní vrstvě. Stávající statické UI je základ pro Project/Artifact služby, nikoli hotový editor. |
| První distribuční cíl | Linux; .deb se systémovými dynamickými závislostmi | Ubuntu 26.04 arm64 čistá instalace a offline upgrade/purge dle ADR 0012. Debian 13 x86_64 má oddělené uživatelské potvrzení, ne stejný automatický důkaz. |
| Omnia | Headless Python jádro v Debian LXC na SSD, ruční deploy | Bez Qt, bez automatického spuštění daemonu; dosavadní deploy a storage demo ověřeny uživatelem. |

Výběr platí pro začátek M1 po uzavření Gate M0. Neznamená novou implementaci služeb ani automatický přechod do M1. Existující stdlib HTTP handler zůstává transportním PoC pro loopback; není tím vybrán jako produkční internetový server. Doménové Project/Artifact služby musí být nezávislé na HTTP adaptéru. Volba produkčního serverového frameworku se provede až proti konkrétním požadavkům v rámci V-10/M1; nepřepisovat jádro podle frameworku.

## Nahrazená otevřená rozhodnutí a zachovaná historie

ADR 0007 vybralo PyQt pouze kvůli dostupnému experimentálnímu prostředí; navazující aplikace používá PySide, nikoli automatický fallback. Doporučení ADR 0009 pro binding a formát balíku je tímto přijato na základě ADR 0010–0012. Dřívější zmínky o otevřeném jazyku/obalu jsou historické, aktuální návrh shrnuje ARCHITECTURE.

C++/libgit2 zůstává ověřená alternativa, nikoli druhá produkční větev. Hybrid nevzniká: znamenal by další IPC, aktualizace a recovery protokol bez doloženého přínosu. Chromium renderer/helper procesy nemění pravidlo jediného aplikačního backendu. Windows/macOS, další balicí formáty ani zamražený runtime se nestávají podporovanými bez vlastního ověření.

## Otevřená akceptace

M0-05 dokončí měření a recovery zvoleného Python/Git/SQLite stacku na Omnia SSD. Není nutné dokončovat produkční C++ port jen kvůli opakovanému srovnání: dosavadní porovnání ADR 0005 postačuje k volbě výchozího adaptéru. Pokud cílová měření doloží problém, nejprve určit bottleneck; změnu tohoto rozhodnutí podložit měřením a novým ADR. Úspěšný krátký smoke ani součet RSS nevydávat za kapacitní plán.

Před persistentními UI operacemi zůstávají klientské operation ID/receipts, autorizace vstupů a řízení životního cyklu V-08/V-10; crash boundaries ADR 0003 se nemění. Před veřejnou distribucí zůstává V-11: licenční posouzení konkrétního releasu, skutečný maintainer kontakt a aktualizační kanál. MPL-2.0 projektu se nemění a komerční licence se nepořizují.

## Ověření rozhodnutí

Posouzený checkout 0d38135, čistý pracovní strom. Důkazy pocházejí z existujících ADR, testů a uživatelských výstupů ve WORK_LOG. Tato změna upravuje pouze návrh a evidenci; nespouští nové benchmarky, aplikaci ani celou testovou sadu. Ověřena konzistence hranic, lokální odkazy a diff. Gate review se zopakuje po M0-05; stav gate zůstává otevřený.
