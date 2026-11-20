<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Chyby na pozadí a typovaný stav (AUDIT-B4-T1)

Stav: **implemented**, čeká na review. Úkol AUDIT-B4-T1, nálezy B-ODD-01,
B-ODD-03 a B-ODD-10 z [auditu B1](audit-b1-locks-versions-oddities.md#nálezy-b-odd).
Zdrojová větev `feature/audit-b4-error-states`, výchozí HEAD `1a46bd1`
(merge #149). Kanonický Workspace projekt
`c898b941-8eb0-4406-8dad-6e2b96c06d59`, projektový HEAD `a688515`.

## Pravidla

1. **Žádná chyba na pozadí nezmizí.** Smyčka, která výjimku zachytí, aby
   neukončila vlákno, ji předá `report_failure` v
   [`spikes/background_workers.py`](../spikes/background_workers.py). Očekávané
   třídy (`ValueError`, `OSError`, `sqlite3.Error`,
   `subprocess.SubprocessError`, `ProjectBusy` a třídy, které zadá volající)
   jdou do logu `spikes.background` na úrovni info, a to jen s názvem třídy.
   Ostatní třídy jsou programátorské nebo neznámé chyby. Zapisují se jako
   warning s tracebackem pro lokální diagnostiku. Formát řádku je
   `background_failed worker=<jméno> target=<peer|replikace|-> reason=<třída>`.
2. **Trvalý stav pro každou chybu.** Synchronizace katalogu, obsahu a replikace
   zapisuje u vyjmenovaných tříd stejný stav jako dřív. Pro jakoukoli jinou
   třídu nově zapíše obecný stav `error` s názvem třídy. RSS synchronizace
   předvoleb zapisuje stav `error` i při selhání přípravy požadavku.
3. **Stav se nerozlišuje podle textu.** Kód se rozhoduje podle typované
   výjimky a text slouží jen lidem. Původní texty zůstaly beze změny, takže
   chybové hlášky i dosavadní testy na text nadále platí.
4. **Chyba v UI je vidět.** Selhání pollu na veřejném promítání zobrazí stav
   „Spojení s promítáním je přerušené“ a nechá poslední známý slide. Do konzole
   se zapíše jen jednou za každou změnu stavu. Rozšíření zapíše selhání
   hlášení nedostupnosti do svého výstupu.

## Implementace

| Nález | Místo | Změna |
|---|---|---|
| B-ODD-01 | `federation_catalog.py`, `replication_control.py`, `rss_subscription_sync.py`, `federation_sync.py` | `report_failure` ve smyčkách přes peery, ve smyčkách plánovačů a v ručním workeru obsahové synchronizace. Záložní stav `error` v `CatalogControl.synchronize`, `ReplicationControl._synchronize` a `ContentSyncControl.synchronize`. RSS `prepare()` je uvnitř bloku, který zapisuje stav. |
| B-ODD-03 | `summary_service.py`, `role_workflow_service.py` | `OwnerUnavailable(ValidationError)` v `metadata.py`. Vyhazují ji kontroly vlastníka v souhrnech, workflow, autonomii, Julia bězích, spouštění výstupů a vláknech chatu. |
| B-ODD-03 | `project_repair.py` | `DuplicateProjectRegistration(ValidationError)` v `configuration.py`. |
| B-ODD-03 | `desktop_ui.py` | `InvalidSearchEvaluation` (`chat_service.py`) a `InvalidPresentationProposal` (`presentation_proposals.py`). Dřívější porovnání s textem „Ollama returned invalid presentation proposal“ nikdy neplatilo, protože tuto hlášku nic nevyhazovalo. Konkrétní česká diagnostika neplatného návrhu prezentace se proto dřív nezobrazila. Změněný projekt zůstává obecnou `ValidationError` a návrh nepovažuje za chybný. |
| B-ODD-03 | `composable_monitoring.py` | Porovnání s uloženou starší hodnotou je pojmenované jako `LEGACY_REVISION_ERROR`. Žádný současný kód tuto hodnotu nezapisuje, takže změna formulace živých hlášek větvení neovlivní. |
| B-ODD-10 | `desktop_ui.py` (veřejné promítání), `extensions/workspace-bridge/extension.js` | Viditelný stav spojení a logování jen při změně stavu; zápis do výstupu rozšíření. Ostatních deset `catch` označil audit (O04) za best-effort a zůstávají. |

## Crash boundaries

Formát Gitu, indexu, journalu, node-local SQLite ani uložených bindingů se
nemění. Nový zápis obecného stavu `error` používá stejné runtime tabulky a
stejnou transakci jako dosavadní vyjmenované stavy. Pokud selže i zápis
stavu, původní výjimka se dál propaguje a smyčka ji zaloguje. Obnova se řídí
journalem dané operace podle [ADR 0003](adr/0003-coordinated-operation.md);
logování nic znovu neodesílá ani neopakuje.

## Ověření

- [`tests/test_error_states.py`](../tests/test_error_states.py):
  - úrovně a obsah logu;
  - záložní stav u katalogu, replikace, obsahové synchronizace a RSS;
  - pokračování smyčky dalším peerem a kratší interval plánovače po chybě;
  - typované kontroly vlastníka;
  - netypovaná chyba s dřívějším textem se nepovažuje za chybějící záznam;
  - duplicitní registrace;
  - behaviorální test veřejného promítání v Node přes
    [`tests/presentation_screen_harness.cjs`](../tests/presentation_screen_harness.cjs).
- `tests/test_desktop.py`: diagnostika hledání se řídí typem (změněný text ji
  zachová, dřívější text bez typu ji nespustí); nově je pokrytá diagnostika
  neplatného návrhu prezentace.
- `tests/test_chat_service.py`: typy chyb u hodnocení hledání a návrhu
  prezentace; změněný projekt není chybný návrh.
- `tests/ide_bridge.test.js`: selhání hlášení nedostupnosti je ve výstupu
  rozšíření.

## Omezení

- `CHAT_VALIDATION_ERRORS` v `desktop_ui.py` dál převádí anglické hlášky na
  české podle textu. Jde o překladovou tabulku pro uživatelskou hlášku: když
  hláška chybí, zobrazí se obecná, ale stav ani další postup se tím nemění.
  Audit ji jako nález nevedl.
- Log `spikes.background` nemá vlastní rotaci ani UI. Používá výchozí
  konfiguraci procesu stejně jako dosavadní `local_api` a `sync_diagnostics`.
