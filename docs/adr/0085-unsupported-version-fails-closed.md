<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0085 — nepodporovaná verze projektových dat uzavírá projekt s typovanou chybou

Datum: 2026-11-18. Úkol AUDIT-B3-T1, nález B-VER-01
([audit B1](../audit-b1-locks-versions-oddities.md#nálezy-b-ver)). Zdrojová
větev `feature/audit-b3-version-compat`, výchozí HEAD `0ac911a`. Kanonický
Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, projektový HEAD
`ec78422`. Rozhodnutí uživatele z 18. 11. 2026. Stav: **implemented**
(AUDIT-B3-T2, T3), čeká na review.

## Kontext

Sonda R3 ukázala, že jediný artefakt s metadaty `schema_version` 5 v commitu
zablokuje `artifacts.open` i `projects.open` celého projektu. Hláška
„Unknown schema version“ neuvádí artefakt, nalezenou ani podporovanou verzi,
ani to, že je potřeba novější program. Takový artefakt může vzniknout na
novějším uzlu a přijít synchronizací.

Audit nechal otevřené, zda připustit viditelný degradovaný stav jednoho
artefaktu (projekt otevřený, artefakt jen označený). To by změnilo dosavadní
zásadu sémantické validace celého snapshotu
([ADR 0003](0003-coordinated-operation.md),
[ADR 0023](0023-metadata-and-import-provenance.md)).

## Rozhodnutí

Zásada validace celého snapshotu se nemění. Projektový snapshot, který obsahuje
artefakt nebo registr s nepodporovanou verzí metadat, se neotevře pro čtení,
zápis, merge ani sync.

Odmítnutí je typované: `UnsupportedVersion` podle
[kontraktu kompatibility](../version-compatibility.md#k1--uzavřená-množina-verzí-a-pořadí-kontrol)
s polem `kind: artifact-metadata` nebo `registry`, ID artefaktu či registru,
nalezenou verzí, podporovaným rozsahem a `update: this-node`. HTTP odpověď
nese `code: "unsupported_version"` a tato pole. Uživatel tak vidí, který
artefakt otevření blokuje a že má aktualizovat program.

Viditelný degradovaný stav jednoho artefaktu se nezavádí. Pokud vznikne
doložená potřeba, bude samostatnou feature s vlastním ADR. Musela by vyřešit
neprůhledné zachování bajtů, vztahy k nevalidovanému artefaktu, index
a merge.

## Alternativy

- **Viditelný degradovaný artefakt.** Projekt by se otevřel a artefakt by byl
  jen ke čtení. Zamítnuto pro tuto dávku. Vztahy ani sémantický merge nelze
  ověřit proti artefaktu, jehož schéma program nezná. Index by musel nést
  částečnou projekci, kterou ADR 0023 výslovně vylučuje. Zápis by musel
  zaručit neprůhledné zachování cizích bajtů.
- **Jen lepší text hlášky bez typu.** Zamítnuto. Rozšíření, UI a peer by dál
  rozhodovaly podle textu, což je třída problému B-ODD-02.

## Důsledky a crash boundaries

Formát Gitu, indexu ani journalu se nemění. Odmítnutí vzniká při validaci, ještě
před journalem a Gitem. Index se z nepodporovaného commitu nestaví a dosavadní
index se nevydává za aktuální (stávající `StaleIndex`). Pending operace
v journalu zůstává beze změny a dokončí ji až program, který verzi podporuje.
Federační příjem nepodporovaného obsahu nic neaplikuje a cílová větev zůstává
na původním HEAD. Po aktualizaci programu se projekt otevře bez ruční opravy.
Návrat commitu na podporovanou verzi stačí také.

## Ověření

AUDIT-B3-T3, fixture R3: typovaná chyba s ID artefaktu a verzemi, nezměněný
HEAD, index a journal, a otevření po náhradě podporovanou verzí. Žádný test
nesmí očekávat tiché přeskočení artefaktu.
