<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-BACKEND-MODEL-02: pinning backendu a modelové nabídky

Navazující feature dávka vznikla 26. 10. 2026 na větvi
`feature/ux-backend-model-02-run-pinning` z `develop` `45144a0`. Původní
`UX-BACKEND-MODEL-01` byla před dokončením celé původně plánované akceptace
doručena ve dvou PR (#96 a #97); skutečně doručený rozsah je proto archivován
ve WORK_LOG a zbývající serverový pinning je explicitně oddělen sem. Cílová
úroveň je **implemented → PoC validated**, cíl jediného PR je `develop`.

## Rozsah a hranice

- **Výstup:** klient potvrdí revizi serverové projekce a přesný `offer_id`.
  Server těsně před přípravou běhu znovu ověří binding, nabídku, model, protokol,
  capabilities, credential revizi, privacy a oprávnění a vytvoří neměnný
  `RunSelection`.
- **Durabilita:** kanonický `RunSelection` a jeho digest se uloží do stávajícího
  provider run journalu ve stavu `prepared`. Nevzniká druhý journal ani nová
  autorita. Staré dokončené běhy zůstávají čitelné jako legacy.
- **Recovery:** pád před `prepared` nezanechá oprávnění k dispatch; po
  `prepared` se používá pouze uložený výběr. `dispatching` zůstává při nejasném
  přerušení `unknown` bez retry či fallbacku.
- **Mimo rozsah:** automatický výběr/fallback, hodnocení ceny či kvality,
  nové providery, redesign katalogu a fyzická akceptace celého faceliftu.

## Úkoly dávky

- [x] [completed] **UX-BACKEND-MODEL-02-A — kontrakt a revalidace
  (cíl: implemented).** Rozšířit volbu běhu o přesnou revizi projekce a nabídku,
  deterministicky sestavit `RunSelection` a fail-closed odmítnout stale,
  chybějící, nejednoznačnou nebo capability-nekompatibilní volbu před účinkem.
- [x] [completed] **UX-BACKEND-MODEL-02-B — jediný durable run journal
  (cíl: implemented).** Rozšířit verzovaně stávající `BackendExecution` a
  providerové journaly o kanonický výběr a digest; zachovat čtení legacy běhů,
  idempotenci a současnou hranici `prepared → dispatching`.
- [x] [completed] **UX-BACKEND-MODEL-02-C — sdílený klientský kontrakt
  (cíl: implemented).** Composer odešle z vybrané serverové projekce její
  revizi a přesný offer bez providerových hard-code výjimek a při stale chybě
  zachová zadání, obnoví nabídku a vyžádá novou vědomou volbu.
- [ ] [in progress] **UX-BACKEND-MODEL-02-D — regrese a akceptace
  (cíl: PoC validated).** Pokrýt všechny tři textové adaptéry, změnu bindingu,
  credentialu, discovery/knowledge/capability revize, nejednoznačný model,
  restart na persistentních hranicích, legacy běh, RBAC/privacy a zákaz
  fallbacku. Fyzicky potvrdit nejméně Ollamu a jeden externí backend v desktopu
  nebo sdíleném webu včetně uložené identity výběru.

## Akceptace

Nový běh nelze připravit z volného názvu modelu ani ze stale projekce. Přesně
zobrazený backend/model/offer a všechny rozhodné revize jsou po `prepared`
neměnné a doložitelné v jediném stávajícím run journalu. Změna katalogu,
bindingu, credentialu nebo capability před přípravou selže bez dispatch;
po přípravě nesmí běh přepočítat ani přesměrovat. Automatické testy a fyzický
průchod prokážou stejný kontrakt na lokálním i externím backendu.

## Průběžné ověření

Základ větve je čistý `develop` `45144a0`. Kontrakt, crash boundaries a reuse
jsou převzaty z [ADR 0053](docs/adr/0053-chat-backend-model-selection.md):
`ModelKnowledgeStore`/`ModelDiscoveryStore`, stávající bindingy,
`ChatRunChoice`, `BackendExecution` a jediné provider run journaly se adaptují;
nový store, router ani automatický fallback se nezavádí.

Implementace 26. 10. 2026 vyžaduje pro každý nový dispatch současně
`selection_revision` a přesný `offer_id`; server znovu ověřuje jedinou čerstvou
nabídku a potřebné capabilities. `RunSelection` obsahuje binding/model/protokol,
credential, knowledge a capability revize, jeho digest je součástí
`BackendExecution` a kanonická podoba se ukládá do stávajících journalů Ollamy,
OpenAI i AtlasCloudu. Legacy řádky zůstávají čitelné s prázdným pinningem.
Při obnovení již připraveného běhu se použije uložený výběr; pozdější změna
katalogu nebo preferencí jej nepřepočítá. Změna bindingu nebo identity výběru
selže bez nového dispatch.

Sdílený composer odesílá obě identity přímo z jediné projekce. Stale odpověď
zachová rozepsané zadání, vymaže pouze neplatnou volbu backend/model, obnoví
katalog a vyžádá novou vědomou volbu. Veřejná odpověď ukazuje kontrolovatelnou
identitu a digest výběru, ale necredential metadata.

Automatické ověření po poslední změně:

- cíleně `190` testů ve všech třech textových adaptérech, chat službě a UI —
  `OK`, `4` přeskočené volitelné Qt/WebEngine testy;
- plná sada `python3 -m unittest discover -s tests -v` — `871` testů za
  `207.630 s`, `OK`, `29` přeskočených volitelných testů;
- Python syntaxe, JavaScript `node --check` a `git diff --check` byly průběžně
  čisté; po tomto čistě dokumentačním zápisu stačí finální kontrola diffu.

Zbývá fyzická akceptace: v reálném desktopu nebo sdíleném webu spustit jednu
Ollamu a jeden externí backend z viditelně vybrané nabídky, ověřit stale obnovu
po změně katalogu a doložit uloženou identitu výběru v příslušném run journalu.
