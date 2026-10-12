<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-UNIFIED-02C-FIX1

Feature dávka **UX-UNIFIED-02C-FIX1 — Samostatná stránka NotebookLM importu a
spolehlivý nativní picker** pokračuje na větvi
`fix/ux-unified-02c-notebooklm-navigation` proti `develop`. Uživatelská
akceptace po předchozím předání odhalila další chybu před potvrzením importu,
proto byla dávka znovu otevřena. Cílem PR zůstává `develop`; PR dosud nebyl
vytvořen ani sloučen.

- [x] [completed] **UX-UNIFIED-02C-FIX1-A — Samostatná stránka a navigace
  (implemented).** Import má vlastní stránku vyvolanou tlačítkem v levém panelu.
- [x] [completed] **UX-UNIFIED-02C-FIX1-B — Nativní pickery
  (implemented).** Archiv i cíl používají přesně validované jednorázové nativní
  akce; folder dialog se otevírá přímo bez druhého asynchronního callbacku.
- [x] [completed] **UX-UNIFIED-02C-FIX1-D — Viditelný cíl
  (implemented).** Ručně vybraná i výchozí výsledná cesta se zobrazuje v řádku
  **Cíl projektu** a je součástí potvrzovaného plánu.
- [ ] [in progress] **UX-UNIFIED-02C-FIX1-E — Bezpečná práva cílové složky
  (implemented, čeká na fyzickou akceptaci).** Ručně vybraný cíl byl prázdný a
  vlastněný aktuálním uživatelem, ale režim `0775` správně zastavil
  `ProjectCreation` ještě před zápisem do journalu. Výběr nyní validuje
  existenci, vlastnictví, symlinky, prázdnost a práva před plánem. Pouze u
  vlastní prázdné běžné složky nabídne výslovně potvrzenou opravu na `0700`;
  odmítnutí nic nemění. Potvrzení plánu navíc vrací konkrétní bezpečnou chybu,
  pokud se cíl mezitím změnil.
- [ ] [in progress] **UX-UNIFIED-02C-FIX1-C — Regrese, dokumentace a předání
  (PoC validated, čeká na fyzickou akceptaci).** `py_compile`, `node --check` a
  úplná sada prošly: **494 testů OK, 24 volitelných přeskočeno**. Izolovaný test
  skutečného privátního Takeoutu prošel a diagnostika se stejným uzlem, archivem
  a cílem došla až těsně před vytvoření projektu. Zbývá v běžícím desktopu
  potvrdit nabídku `0700`, znovu připravit plán a ověřit vytvoření i otevření
  projektu podle [checklistu](docs/notebooklm-import-acceptance.md).

Oprava nemění parser ani data importu. Před `ProjectCreation` pouze validuje
vybraný existující cíl a případně po explicitním souhlasu mění jeho režim;
nevzniká nová persistentní vrstva ani crash boundary.
