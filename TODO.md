<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — COMP-02

Aktivní feature dávka: **Lokální Julia runner a publikace výsledků**

- Původ: uživatelem schválená priorita po doručení PR #103; implementační
  pokračování kontraktu `COMP-01` / ADR 0057.
- Milník: M6 / modelování a výpočty.
- Cílová úroveň: **PoC validated**.
- Větev: `feature/comp-02-julia-runner` z `develop` `b104843`.
- Cíl PR: `develop`.
- Rozsah: striktní parser `fpw-julia-computation-v1`, připnutý node-local
  runtime binding a preflight prostředí, explicitní lokální CLI běh,
  node-local run journal, OS-level izolace, bounded atomická materializace,
  stav posledního výsledku a vědomá publikace přes Workspace.
- Mimo rozsah: notebookové UI, obecný job server, automatická instalace či
  aktualizace Julia, síťové výpočty, GPU/distribuované workery, externí
  publikace a automatické commitování výsledků.
- Reuse: adaptovat `OutputExecutionStore` a atomické materializační generace,
  validovaný Git snapshot/artifact autorizaci, Workspace journal a CLI vzory;
  zachovat samostatný Julia run journal a nesmíchat jej s LLM runy.

## Crash hranice a recovery

- Git je autoritou definice/modelu/vstupů/prostředí. SQLite Julia run journal
  je autoritou requestu, approval, stavů a receiptů; privátní output cache je
  obnovitelná projekce. Publikace je samostatná Workspace operace.
- Pád před durable `dispatching` je bezpečně nespouštěný. Po `dispatching` bez
  potvrzeného zániku procesu nebo úplného hashově shodného receiptu je run
  `unknown` bez automatického retry.
- Staging se nesmí objevit jako výsledek. Po atomickém rename lze při restartu
  převzít pouze generaci přesně odpovídající durable requestu; jinak zůstává
  poslední úspěšná generace viditelně stale.
- Pád publikace se obnovuje pouze přes existující Workspace journal a nemění
  stav dokončeného Julia runu.

## Úkoly dávky

- [ ] [in progress] **COMP-02-A — kontrakt, runtime inventory a preflight
  (implemented).** Implementovat bounded fail-closed parser definice/requestu,
  exact HEAD/blob/hash/privacy revalidaci, připnutý runtime binding a kontrolu
  Project/Manifest/depotu bez sítě nebo implicitního fallbacku.
- [ ] [planned] **COMP-02-B — durable izolovaný runner a materializace
  (implemented).** Přidat CLI, vlastní SQLite journal/stavový automat,
  subprocess bez shellu, OS-level zákaz sítě a limity, cancel/timeout celého
  stromu, bounded stdout/stderr/output manifest a atomickou generaci s
  reconciliation po každém persistentním přechodu.
- [ ] [planned] **COMP-02-C — aktuálnost a explicitní publikace
  (implemented).** Rozlišit missing/current/stale/running/failed/cancelled/
  unknown, zobrazit přesnou provenance poslední generace a publikovat pouze
  uživatelem vybraný validní výstup jako nový artefakt přes standardní
  Workspace preview/approval/recovery.
- [ ] [planned] **COMP-02-D — bezpečnostní a crash regrese
  (PoC validated).** Ověřit úspěšný běh/retry, změnu modelu/vstupu/parametru/
  prostředí/runtime/platformy, concurrency, restart před/po každé hranici,
  timeout/cancel, limity, odmítnutou síť, symlink/special file, neautorizovaný
  vstup, stale výsledek a idempotentní publikaci.
- [ ] [planned] **COMP-02-E — runtime, balení, dokumentace a fyzická akceptace
  (PoC validated).** Doložit přesný archiv/signature/checksum a licence,
  podporované platformní profily a jejich OS izolaci; aktualizovat návod,
  ADR/reuse evidence a provést skutečný výpočet i publikaci na každé platformě,
  kterou tato dávka prohlásí za podporovanou.

## Akceptace dávky

- Žádný import, otevření projektu, status ani restart nespustí Julia kód.
- Run bez prokazatelné OS izolace, přesného runtime/prostředí, aktuálních
  oprávnění nebo úplného depotu selže před dispatch; síť ani jiný runtime není
  fallback.
- Cache se neobjeví v Git/exportu/federaci a publikace vždy projde jedinou
  Workspace zápisovou cestou s provenance a nejpřísnější privacy.
- Cílené testy, fyzické platformní ověření, plná testovací sada a
  `git diff --check` projdou před předáním PR.
