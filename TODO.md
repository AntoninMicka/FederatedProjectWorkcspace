<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — COMP-03

Aktivní feature dávka: **COMP-03 — Workspace řízení Julia výpočtu** na větvi
`feature/comp-03-julia-workspace`, základ/cíl PR `develop`, cílová úroveň **PoC
validated**. Dávka byla po implementaci evidence modelových nástrojů znovu
otevřena kvůli uživatelské kontrole jejího rozvržení; PR dosud není předpokládán
ani připravován.

Původní požadavky: roadmapa sekce 2F, `COMP-03`, návaznost na `COMP-02`,
`DOC-PATTERN-CATALOG-01` a `DOC-PATTERN-LIBRARY-01`. Výstupem je bezpečný shared
workflow pro authoring, exact preview, potvrzený Julia běh a explicitní
publikaci. Mimo rozsah zůstává obecné IDE, notebookové prostředí, instalátor
balíčků a MATLAB konverze (`COMP-MATLAB-CONVERSION-01` je v backlogu).

- [x] [completed] **COMP-03-A — projektová projekce definic a přesný preview
  (implemented).** Definice se načítají z přesného validovaného Git HEAD;
  preview nic nespouští.
- [x] [completed] **COMP-03-B — potvrzený běh a lifecycle (implemented).**
  Explicitní potvrzení, cancel, restart a reconcile zachovávají fail-closed
  stavy včetně `unknown` bez automatického retry.
- [x] [completed] **COMP-03-C — výstupy a explicitní publikace
  (implemented).** Bounded náhled a samostatně potvrzená idempotentní publikace
  znovu ověřují HEAD, oprávnění a privacy.
- [x] [completed] **COMP-03-D — shared desktop/web UI (implemented).** Otevření,
  import, změna parametrů ani čtení stavu nic nespouští; authoring je v
  Nástrojích a běh ve Výpočtech.
- [x] [completed] **COMP-03-F — editor Julia modelu a šablony (implemented).**
  Specializovaný editor atomicky spravuje `.jl`, `Project.toml`, manifest a
  hashovanou definici a reuse společný raw widget s nápovědou a příklady.
- [x] [completed] **COMP-03-G — evidence modelových nástrojů (implemented).**
  Bezpečný import `.jl` končí nejprve v lokálním konceptu; modely mají akce
  Zobrazit, Editovat, Spustit a potvrzené atomické Smazat.
- [ ] [in progress] **COMP-03-H — sidebarová evidence nástrojů (implemented,
  čeká na uživatelskou kontrolu).** Ovládání Nový nástroj a Import i seznam
  Julia modelů se přesouvají z hlavní plochy do levého panelu podle stejného
  vzoru jako Projekty. Každý model má třítečkovou nabídku akcí; hlavní plocha
  zůstává pro detail a editor bez duplicitní lišty a seznamu.
- [ ] [in progress] **COMP-03-E — závěrečná regrese, dokumentace a akceptace
  (PoC validated po dokončení).** Po poslední změně rozvržení je nutné zopakovat
  cílené i úplné ověření a následně vyčkat na uživatelskou vizuální kontrolu.

## Akceptační podmínky a recovery

- Levý panel Nástroje odpovídá vzoru panelu Projekty: ikonové primární akce,
  počet nástrojů, seznam položek a třítečkové kontextové nabídky.
- Hlavní panel neduplikuje primární akce ani katalog; Zobrazit/Editovat otevřou
  jeho detail nebo editor, Spustit pouze přejde k read-only exact preview.
- Import `.jl` zůstává lokálním konceptem do explicitního uložení. MATLAB je
  viditelný pouze jako nepodporovaná budoucí možnost.
- Uložení, publikace a smazání reuse Workspace/Journal/Git/index transakci:
  před commitem je autoritou journal, po commitu lze index obnovit z HEAD.
  Delete preview je read-only a confirm znovu ověří HEAD, digest, úplnost i
  vztahy; Git historie zůstává zachovaná.
- Změna bude předána k uživatelské kontrole bez doporučení PR. Teprve po
  přijetí rozvržení lze uzavřít akceptaci a přesunout dávku zpět do WORK_LOG.

## Ověření

Po poslední změně kódu a testů prošla úplná sada
`python3 -m unittest discover -s tests -v`: **957 testů, 920 úspěšných a 37
volitelných skipů, bez selhání**, 229,911 s. Samostatně prošlo všech 50
desktopových testů (45 úspěšných, 5 volitelných skipů), Python compile, kontrola
generovaného JavaScriptu přes `node --check` a `git diff --check`.

Skutečný Qt/WebEngine smoke byl spuštěn třikrát, ale lokální TLS handshake
opakovaně selhal (`net_error -202`): jednou při přihlášení a dvakrát při API
otevření Julia editoru. Test před importem nově čeká na dokončenou sidebarovou
projekci; aplikační smoke proto v tomto běhu není vydáván za úspěšný. Fyzická
Julia 1.10.12 Linux glibc aarch64 akceptace výpočetního lifecycle zůstává
platná. Uživatelská vizuální kontrola nového rozvržení je otevřená.
