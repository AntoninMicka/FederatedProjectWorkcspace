<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — COMP-01

Aktivní feature dávka: **Julia výpočetní kontrakt a prostředí**

- Původ: uživatelem schválená priorita po doručení PR #102; strategický rozsah
  sekce 2G roadmapy a ADR 0018.
- Milník: M6 / modelování a výpočty.
- Cílová úroveň: **designed**.
- Větev: `feature/comp-01-julia-contract` z `develop` `64a7dac`.
- Cíl PR: `develop`.
- Rozsah: uzavřený kontrakt modelu, zmrazených vstupů, parametrů, Julia
  prostředí, odděleného run recordu, lokální materializace a explicitní
  publikace; podporovaný runtime/platformy, instalace, offline depot,
  aktualizace, limity a execution boundary.
- Mimo rozsah: spouštění Julia kódu, stažení nebo balení runtime, implementace
  runneru, notebookové UI, projektový writer a fyzická runtime akceptace; tyto
  kroky patří nejdříve do `COMP-02`.
- Reuse: adaptovat validovaný Git snapshot, Context Manifest a execution
  boundary z ADR 0008, materializované kompiláty z ADR 0018 a oddělení
  descriptoru/plánu/execution z ADR 0030. Nový job server, plugin framework,
  LLM run record ani druhé projektové úložiště se nezavádějí.

## Persistentní hranice a budoucí recovery

- Tato návrhová dávka nic nespouští ani nezapisuje do runtime stores. Musí ale
  vymezit autoritu budoucí operace: Git drží model, deklarované vstupy a
  prostředí; node-local journal drží rozpracovaný run; materializační cache je
  obnovitelná projekce; projektový artefakt vzniká jen samostatnou explicitní
  publikací přes Workspace.
- Návrh musí rozlišit pád před dispatch, neurčitý účinek po dispatch, neúplnou
  staging generaci, atomicky zveřejněnou generaci bez receipt a pád během
  samostatné publikace. Retry nesmí tiše znovu spustit `unknown` výpočet ani
  vydat poslední úspěšný výsledek za aktuální.

## Úkoly dávky

- [ ] [in progress] **COMP-01-A — reuse, licence a runtime/platform review
  (designed).** Ověřit existující interní komponenty a aktuální primární
  podklady Julia pro podporované verze/platformy, systémovou versus přibalenou
  instalaci, offline depot, aktualizace, redistribuci a omezení sandboxu.
- [ ] [planned] **COMP-01-B — verzovaný výpočetní kontrakt (designed).** Uzavřít
  schéma modelu, entry pointu, přesných vstupů a hashů, typovaných parametrů,
  `Project.toml`/`Manifest.toml`, runtime/platform identity, seed a execution
  policy bez credentials, depot/cache a uživatelského startupu v Gitu.
- [ ] [planned] **COMP-01-C — run, materializace a publikace (designed).** Oddělit
  Julia run record od LLM běhu, definovat stavy, limity, stdout/stderr,
  výstupní manifest/hashe, privacy odvozeniny, atomickou lokální generaci a
  samostatnou vědomou publikaci přes Workspace.
- [ ] [planned] **COMP-01-D — scénáře selhání a konzistence dokumentace
  (designed).** Prověřit stale HEAD/prostředí, chybějící balíček, síťový pokus,
  timeout/cancel/pád, neúplný či nadlimitní výstup, revokaci oprávnění,
  platformní numerickou odchylku a recovery na každé persistentní hranici;
  sladit ADR, roadmapu, reuse katalog a navazující akceptaci `COMP-02`.

## Akceptace dávky

- Kontrakt je jednoznačný, provider-neutral a neoznačuje návrh za implementaci.
- Každý požadovaný chybový a crash scénář má stav, autoritu a bezpečný recovery
  postup bez implicitního síťového přístupu nebo opakování neurčitého účinku.
- Runtime/licenční tvrzení odkazují na aktuální primární zdroje; neověřená
  distribuční rozhodnutí zůstávají otevřená a neblokují lokální návrh.
- Dokumentace a roadmapový graf jsou konzistentní a `git diff --check` projde.
