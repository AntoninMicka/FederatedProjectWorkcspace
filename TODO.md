<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-UNIFIED-01: Jednotný webový a desktopový frontend

Aktivní feature dávka **UX-UNIFIED-01** pokračuje na větvi
`feature/ux-unified-01-shared-frontend`, založené z `develop` `7bb4f5e`; cílem
jediného PR zůstává `develop`. Uživatel 2026-10-11 rozšířil akceptaci dávky:
společná historie artefaktu a společné vytvoření projektu jsou součástí stejné
unifikace UI, nikoli samostatné feature. Dříve prozatímně naplánované položky
`UX-UNIFIED-02A/02B` jsou proto sloučené níže jako `UX-UNIFIED-01-E/F`.

Výstupem je jeden společný webový frontend používaný také desktopovým WebEngine
obalem. Qt dialogy zůstávají jen pro vědomě desktop-only integrace s operačním
systémem nebo lifecyclem. Autorita Git dat, expected HEAD, journal, recovery,
RBAC a privacy hranice jednotlivých backendových operací se nemění.

- [x] [completed] **UX-UNIFIED-01-A — Jeden zdroj shellu a explicitní adaptéry
  (implemented / PoC validated).** Web a desktop servírují shodné HTML/CSS;
  liší se pouze autentizačním a capability bootstrapem.
- [x] [completed] **UX-UNIFIED-01-B — Per-chat akční menu a strom vláken
  (implemented / PoC validated).** Společné ovládání používá jeden strom
  zařazených a nezařazených chatů a akce konkrétního vlákna v jeho menu.
- [x] [completed] **UX-UNIFIED-01-C — Qt/PySide inventura (designed).** Hranice
  je popsána v `docs/ui-capability-inventory.md`.
- [x] [completed] **UX-UNIFIED-01-D — Společný import zdroje (implemented / PoC
  validated).** Samostatná stránka používá společnou `Sources` operaci; Qt
  importní dialog byl po dosažení parity odstraněn.
- [x] [completed] **UX-UNIFIED-01-E — Společná historie artefaktu (implemented
  / PoC validated).** Existující read-only `ArtifactHistory` obsluhuje jednu
  alternativní stránku otevřenou z per-document menu v seznamu Podkladů;
  zavření vrací náhled stejného dokumentu. HEAD-bound seznam a
  porovnání zobrazují nejvýše 100 topologicky seřazených verzí, obsah, metadata,
  diff a commit pouze jako text. Web zachovává RBAC a fail-closed odmítá celý
  snapshot s `local-only`; foreign/stale/pending, deleted/invalid/truncated a
  nulový diff pokrývají service/HTTP testy. Qt `HistoryDialog` a jeho vstup v
  editoru byly po paritě odstraněny. Následná UI regrese opravila projektovou
  projekci o explicitní `kind`, aby se vstup historie skutečně zobrazil u
  uložených dokumentů a zůstal skrytý u zdrojů. Historie je nyní v akčním menu
  konkrétního dokumentu a její zavření vrací jeho náhled; nevznikl zápis ani
  nový recovery stav. Stejné menu nyní nabízí také Kopírovat ID a pro existující
  dokument společnou stránku Upravit/přejmenovat a Připravit smazání. Zápisy
  znovu používají `Artifacts.save/delete`, expected HEAD, stabilní operation ID,
  journal a receipt; smazání navíc váže potvrzení na serverový preview digest.
  Web dovolí zápis jen rolím editor/project-admin a správcům, desktop zachovává
  lokální autoritu uzlu.
- [x] [completed] **UX-UNIFIED-01-F — Společné vytvoření projektu (implemented /
  PoC validated).** Web i desktop používají společný formulář s backendem
  vydaným přesným preview plánem a odděleným potvrzením. Stabilní operation ID,
  idempotentní receipt, journal a startup recovery dál řídí `ProjectCreation`.
  Webový adaptér odvozuje cíl výhradně z nakonfigurovaného projects root a RBAC
  jej omezuje na správce. Desktopový systémový picker vydává pouze opaque
  in-process capability svázanou s přesným cílem a operation ID; stejná
  capability zůstává použitelná pro shodný retry, nikoli pro jinou operaci.
  Potvrzení přijme jen plán vydaný stejnou backendovou instancí a znovu ověří
  jeho digest i cíl. Qt `CreationDialog` a tlačítko paralelního vytvoření v
  toolbaru byly odstraněny; nativní controller zůstává pro recovery a ostatní
  desktop-only operace.
- [ ] [planned] **UX-UNIFIED-01-G — Závěrečné předání.** Po dokončení E/F
  zopakovat relevantní cílené testy, úplnou sadu, `git diff --check`, přesunout
  evidenci do WORK_LOG a připravit jediný PR do `develop`. Skutečný WebEngine,
  HTTPS a Turris/LXC průchod evidovat odděleně od lokálních testů.

### Crash a recovery hranice

Historie a otevření editoru jsou HEAD-bound čtení pod zámkem: nevytvářejí
journal ani zápis a při pending operaci nebo změně HEAD fail-closed skončí.
Uložení a potvrzené smazání existujícího dokumentu používají beze změny
`Artifacts`/Workspace hranice: záměr a bajty jsou v journalu před Git CAS,
receipt dělá retry idempotentní a cizí HEAD/pracovní změna zastaví recovery.
Vytvoření projektu
znovu použije stávající `ProjectCreation` journal/receipt a jeho již definované
hranice před a po filesystem/Git/registraci; společná UI vrstva je nesmí
nahrazovat paralelním stavem.

### Dosavadní ověření

Po kroku F prošel `node --check` pro společný i výsledný webový JavaScript.
Cílená sada nového adaptéru, doménového vytvoření, desktopu a web serveru prošla:
**64 testů OK, 6 volitelných přeskočeno**. Úplná sada po poslední změně prošla:
**458 testů OK, 25 volitelných native/package/live testů přeskočeno**. Známé
neblokující `ResourceWarning` testovacích SQLite spojení zůstaly beze změny.
Skutečný Qt/WebEngine průchod společným formulářem a Turris/LXC deployment nebyly
provedeny.

### K předání do backlogu

- **UX-UNIFIED-02D — Společný editor dokumentu a TODO:** existující dokument už
  má společnou editaci/přejmenování, potvrzené smazání a Kopírovat ID. Pro
  pozdější dávku zbývá vytvoření nového dokumentu, hlavní TODO a odstranění
  zbylého Qt `EditorDialog`. Hromadné workflow Souhrn, Extrakce a Metadata
  zůstávají v hlavních záložkách, protože mají vlastní konfiguraci a mohou
  pracovat s více podklady.

[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)
