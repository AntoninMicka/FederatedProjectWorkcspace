<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-CONFLICT-RESOLUTION-01: historie a ruční řešení divergence

Původ: uživatelský požadavek 23. 10. 2026 po fyzickém potvrzení bezpečně
zachované divergence uzavřít synchronizační dávku a řešení konfliktů dodat
samostatně v uživatelsky přívětivém prohlížeči historie. Navazuje na ADR 0017,
ADR 0042 a `F-M5-SHARING-SYNC-01`, doručené PR #81 jako merge commit `c884cd2`.
Cílová úroveň: **designed → implemented → PoC validated**. Větev:
`feature/f-m5-conflict-resolution-01`, základ `develop` na `c884cd2`, cíl PR:
`develop`.

Dávka zobrazí lokální a `refs/federation/incoming/…` historii, nabídne
explicitní 3-way řešení `base / naše / protější / výsledek` a až po lidském
potvrzení publikuje sémanticky validní dvourodičový merge commit. Markdown lze
porovnávat jako raw text i jako bezpečně formátovaný náhled stejného návrhu.
Automatický merge při synchronizaci, obecný editor binárních souborů a externí
export jsou mimo rozsah.

## Úkoly dávky

- [ ] [in progress] **F-M5-CONFLICT-RESOLUTION-01-A — kontrakt, reuse spike a
  recovery návrh (cílová úroveň: designed).** Ověřit stávající
  `ArtifactHistory`, Markdown preview, Git wrapper a Workspace/Journal/Index.
  Udělat bounded UI spike nad MIT `@codemirror/merge`; potvrdit aktuální
  upstream, verzi, tranzitivní licence, bundling, klávesnici a mobilní
  použitelnost. Git CLI zůstane autoritou merge base, stromu a rodičů. Pokud
  dvoustranný CodeMirror nevyhoví čtyřpohledové orchestraci, adaptovat
  stávající editor bez nové UI knihovny. ADR popíše přesné autority, limity a
  crash boundaries před implementací zápisu.
- [ ] [planned] **F-M5-CONFLICT-RESOLUTION-01-B — historie a read-only 3-way
  model (cílová úroveň: implemented).** Nad autorizovaným projektem a přesně
  připnutými heady načíst bounded graf, společného předka, změněné cesty a
  `base/ours/theirs` bajty bez změny worktree, indexu či refs. Odlišit textový,
  add/add, změna–smazání, přejmenování–úprava a nepodporovaný/binární konflikt;
  stale head, změněná policy/trust a nevalidní historie selžou closed.
- [ ] [planned] **F-M5-CONFLICT-RESOLUTION-01-C — raw/rendered resolver UI
  (cílová úroveň: implemented).** Projektový prohlížeč historie nabídne seznam
  konfliktních cest, navigaci po blocích, volbu naší/protější/obou změn, přímou
  editaci výsledku a přepnutí raw Markdown ↔ bezpečně renderovaný náhled.
  Zobrazuje počet nevyřešených konfliktů, nedovolí zaměnit preview za uložený
  stav a před zrušením či opuštěním rozepsaného výsledku varuje.
- [ ] [planned] **F-M5-CONFLICT-RESOLUTION-01-D — validovaná publikace a
  recovery (cílová úroveň: implemented).** Pod jediným project writer lockem
  znovu ověřit oba heady, base, policy a trust, sémanticky validovat celý
  kandidátní snapshot a po explicitním potvrzení vytvořit merge commit s oběma
  rodiči přes journal/CAS. Po commitu obnovit worktree a index z potvrzeného
  HEAD; incoming ref uklidit jen podle doloženého výsledku. Restart před
  potvrzením nesmí nic publikovat, pád po durable přípravě se idempotentně
  dokončí nebo pravdivě nabídne obnovu.
- [ ] [planned] **F-M5-CONFLICT-RESOLUTION-01-E — automatické a fyzické
  ověření (cílová úroveň: PoC validated).** Ověřit čistý merge, stejný Markdown
  blok, raw/rendered shodu, ruční editaci, změnu–smazání,
  přejmenování–úpravu, sidecar/relationship validaci, stale head/policy/trust,
  zrušení a restart na každé persistentní hranici. Fyzický desktop ↔ LXC
  scénář potvrdí vytvoření a následný sync dvourodičového commitu.

## Akceptační podmínky

- prohlížení ani rozepsaný návrh nemění Git, index, worktree nebo incoming refs;
- uživatel vždy rozliší base, lokální, protější a výslednou podobu a může u
  Markdownu přepnout raw i bezpečně renderovaný pohled;
- publikace vyžaduje explicitní potvrzení přesného výsledku a nezměněné heady,
  policy, trust a oprávnění;
- celý výsledný snapshot projde projektovou a vztahovou validací před CAS;
- úspěch vytvoří jediný dvourodičový merge commit, obnoví index z jeho HEAD a
  následný federovaný sync jej přenese bez ztráty historie;
- cílené i úplné testy projdou a fyzický konflikt bude vyřešen mezi desktopem
  a LXC bez ručního zásahu do `.git`.
