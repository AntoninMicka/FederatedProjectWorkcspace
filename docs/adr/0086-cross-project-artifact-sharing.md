<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0086 — Explicitní sdílení podkladu mezi projekty

Datum: 2026-11-21. Úkol XREF-02-A. Stav: **implemented** (kontrakt, služba
a CLI), čeká na review. Doplňuje [ADR 0070](0070-local-artifact-references.md),
které zůstává platné.

## Kontext

XREF-01 dovoluje vytvořit připnutou referenci každému, kdo smí číst zdroj
a zapisovat do cíle. Zdrojový projekt přitom nemá záznam o tom, co komu
nabídl, a nemůže sdílení ukončit. Samotná vazba dvou projektů by navíc
mohla vypadat jako přístup ke všem podkladům. XREF-02 potřebuje evidovat
původce, důvod, povolené cíle a odvolání.

## Rozhodnutí

**Záznam sdílení ve zdroji.** Sdílení je artefakt zdrojového projektu
s kanonickým `share.json` (`fpw-artifact-share-v1`) a tagem stejného jména.
Obsahuje `artifact_id`, seřazený seznam 1–64 cílových project UUID,
`originator_id`, důvod (nejvýše 1 000 znaků), `created_at` a `revoked`
(`null` nebo `{at, by}`). Jeden záznam se týká jednoho vlastního artefaktu,
nikoli celého projektu. Sdílet nelze referenci ani jiný záznam sdílení.
Titulek záznamu neobsahuje titulek artefaktu, aby pozdější zpřísnění privacy
podkladu nevyzradil starý záznam.

Invarianty přechodu: záznam nelze smazat, pouze odvolat; artefakt, původce
a čas vzniku se nemění; odvolání je konečné a nové sdílení dostane nové ID.
Dokud záznam platí, lze měnit cíle a důvod. Smazání nebo zpřísnění privacy
sdíleného artefaktu zůstává povolené. Záznam tím nezaniká a reference v cíli
pak vrací `deleted`, resp. přísnější efektivní privacy.

**Reference v cíli.** Nová reference používá `fpw-artifact-reference-v2`
s polem `share` (`share_id`, `originator_id`, `attached_by`, `reason`).
Původce čte služba ze živého záznamu ve zdroji, ne od volajícího. Repin mění
pouze pin; schéma a `share` jsou neměnné. Reference v1 z XREF-01 zůstávají
čitelné a lze je repinovat. Jsou označené `schema` v1 a `share: null`.
Novou referenci v1 služba nevytvoří. Neznámá verze reference nebo sdílení
skončí typovanou chybou `UnsupportedVersion` podle
[ADR 0085](0085-unsupported-version-fails-closed.md).

**Oprávnění na obou stranách.** Vytvořit sdílení smí jen editor nebo správce
zdroje a jako cíle smí uvést jen projekty, které sám vidí. Projekt nemůže sdílet
sám do sebe. Připojení vyžaduje zápis do cíle, čtení zdroje a aktivní sdílení,
které cíl uvádí. Resolver při každém čtení, preview, zápisu, forku i přípravě
kontextu ověří záznam v aktuálním HEAD zdroje: chybějící nebo cizí záznam
vrátí `not-shared`, odvolaný `share-revoked`. Kontroly z ADR 0070 (živý grant
uživatele, rozsah requestu, privacy, pending zdroj, zákaz fallbacku do cache)
platí beze změny. Sdílení je tedy další zúžení, nikoli náhrada oprávnění
k projektu. Context Manifest nese v důkazu i `share`.

**Sdílení není synchronizace.** Záznam sdílení putuje se zdrojovým projektem
a reference s cílovým projektem podle [ADR 0081](0081-complete-project-data-sync.md).
Synchronizace cíle na jiný uzel přenese jen deskriptor. Bez registrovaného
zdroje a živého oprávnění na tom uzlu reference zůstane nedostupná a nikomu
nepřidá přístup ke zdroji.

## Crash boundaries a recovery

Vytvoření sdílení i připojení reference jsou dvě samostatné operace
`Workspace.transact` ve dvou repozitářích. Každá má vlastní preview digest,
expected HEAD, operation ID, journal a receipt
([ADR 0003](0003-coordinated-operation.md), ADR 0070). Atomicita přes oba
projekty se nepředstírá.

| Hranice | Stav a recovery |
| --- | --- |
| Před commitem sdílení | Žádný zápis do zdroje. Recovery zdroje dokončí nebo zahodí připravený intent. Stejné operation ID vrátí receipt. |
| Sdílení commitnuté, reference ne | Aktivní sdílení bez použití je přípustný stav. Je vidět ve zdroji a lze ho připojit později nebo odvolat. Nic nedělá automaticky. |
| Příprava reference | Zdroj se čte neblokujícím sdíleným zámkem; journal cíle drží přesné schválené bajty deskriptoru (ADR 0070). |
| Odvolání po připravené referenci | Připravený intent se dokončí bez nového čtení zdroje. Každé další čtení, fork či kontext pak skončí `share-revoked`. |

Reálný výpadek napájení se nesimuluje. Procesové pády na hranách transakce
pokrývají stávající testy ADR 0070; jejich fixture nyní používá sdílení v2.

## Ověření

`tests.test_cross_references` (29 testů): povinné aktivní sdílení
a povolený cíl, kanonický a nesmazatelný záznam, konečné odvolání, podvržený
původce či artefakt, práva zápisu ke zdroji a viditelnost cílů, zákaz řetězení,
neměnná provenance při repinu, platnost po smazání podkladu, legacy v1, CLI
a původní scénáře XREF-01. Uživatelské rozhraní, správa odvolání a použití
v úkolu či konverzaci patří k XREF-02-B až E.
