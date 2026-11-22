<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0086 — Explicitní sdílení podkladu mezi projekty

Datum: 2026-11-21. Úkol XREF-02-A. Stav: **implemented** (kontrakt, služba
a CLI), čeká na review. Doplňuje [ADR 0070](0070-local-artifact-references.md),
které zůstává platné.

Návrh 22. 11. 2026: [ADR 0089](0089-project-relations-and-derived-read-access.md)
rozšiřuje návrh o schvalované projektové vztahy a odvozené čtení včetně
budoucích dat/výstupů. Je **designed, k review**, nikoli implementovaná změna
tohoto explicitního per-artifact sdílení. Obě autorizační větve mají koexistovat.

## Kontext

XREF-01 dovoluje vytvořit připnutou referenci každému, kdo smí číst zdroj
a zapisovat do cíle. Zdrojový projekt přitom nemá záznam o tom, co komu
nabídl, a nemůže sdílení ukončit. Samotná vazba dvou projektů by navíc
mohla vypadat jako přístup ke všem podkladům. XREF-02 potřebuje evidovat
původce, důvod, povolené cíle a odvolání.

## Rozhodnutí

**Záznam sdílení ve zdroji.** Sdílení je artefakt zdrojového projektu
s kanonickým `share.json` (`fpw-artifact-share-v1`) a tagem stejného jména.
Obsahuje `artifact_id`, účel `purpose`, seřazený seznam 1–64 cílových project UUID,
`originator_id`, důvod (nejvýše 1 000 znaků), `created_at` a `revoked`
(`null` nebo `{at, by}`). Jeden záznam se týká jednoho vlastního artefaktu,
nikoli celého projektu. Sdílet nelze referenci ani jiný záznam sdílení.
Účel `share` je běžné nabídnutí podkladu (např. zadání z nadřazeného projektu
do podprojektu). Účel `output` prohlašuje artefakt za výstup projektu pro jeho
odběratele (např. výsledek podprojektu pro nadřazený projekt). Oba účely mají
stejná pravidla oprávnění; liší se zobrazením a tím, že výstupy lze v cíli
nabídnout bez ručního hledání. Titulek záznamu neobsahuje titulek artefaktu, aby pozdější zpřísnění privacy
podkladu nevyzradil starý záznam.

Invarianty přechodu: záznam nelze smazat, pouze odvolat; artefakt, účel, původce
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

**Aktualizace, ukončení a použití (XREF-02-C).** Novější revize zdroje se
v cíli pouze nabídne. Repin ukáže porovnání připnuté a aktuální revize
(unified diff textu, jinak velikost a SHA-256) a uloží se až po potvrzení
přesného náhledu. Mění jen tuto referenci. Manifesty a evidence dřívějších
úkolů a zpráv odkazují na commit cílového projektu, v němž deskriptor nese
původní pin, takže je repin nepřepíše. Připravený, ale neodeslaný manifest se
po repinu odmítne a neodešle se s novými bajty. Vlastní kopie (fork) a
odebrání reference jsou potvrzené operace cílového projektu. Odebrání smaže
jen ukazatel; zdroj, sdílení i historie reference zůstávají v Gitu.

Ukončení sdílení (`revoked: {at, by}`) smí provést editor nebo správce zdroje.
Platí pro všechny cíle záznamu, je konečné a záznam zůstává v historii.
Brání budoucímu připojení, zobrazení, forku i přípravě kontextu
(`share-revoked`). Neruší kopie, které cíl legitimně vytvořil před ukončením,
ani bajty už předané v dřívějších bězích. Ty nelze zpětně odvolat.
Reference v cíli zůstává jako viditelný stav, dokud ji cíl neodebere.
Zúžení cílů jednoho záznamu UI zatím nenabízí; místo toho se sdílení ukončí
a vytvoří nové.

Sdílený podklad se do úkolu nebo konverzace vybírá jako jiné podklady
projektu (`selected_artifact_ids`). Context Builder jej podle ADR 0070 vyřeší
pro aktuálního uživatele a rozsah requestu, zapíše do manifestu důkaz
s pinem a `share` a před dispatch jej ověří znovu. Evidence úkolu obsahuje ID
reference a commit projektu, nikoli tichou kopii textu bez původu.
Připojení podkladu k plánovacímu úkolu Workspace patří k PLAN-TASK-WORK-01.

**Známá ztráta přístupu a offline stav (XREF-02-D).** Před XREF-02-D
platilo pravidlo ADR 0070 „známé smazání ani revokace neposkytují fallback do
cache“ jen tehdy, když byl zdroj dostupný. Kdyby pak zdroj vypadl, uložená
kopie se znovu zobrazila jako `offline-stale`. Nyní, když resolver zjistí
`deleted`, `share-revoked` nebo `not-shared`, zapíše do privátní cache uzlu
náhrobek a smaže uloženou kopii daného pinu. Náhrobek není vázaný na
uživatele, takže platí pro všechny účty uzlu včetně vlastníka uzlu.
Rozsah náhrobku:

- `deleted`: všechny piny a sdílení podkladu.
- `share-revoked`: všechny cíle sdílení.
- `not-shared`: jen daný cíl.
- `invalid-pin`: jen smaže cache daného pinu.

Offline čtení náhrobek respektuje. Úspěšné živé ověření smaže jen náhrobky,
které ověření vyvrátilo; ukončené sdílení je konečné, takže jeho náhrobek
nezmizí. Ztrátu přístupu, ke které došlo, zatímco byl zdroj na tomto uzlu
nedostupný, uzel zjistit nemůže. Proto offline obsah zůstává jen
k zobrazení, s označenou neověřenou privacy a časem posledního ověření.

UI odlišuje tyto stavy:

- `current`: aktuální ověřená revize.
- `newer-available`: zdroj má novější revizi.
- `offline-stale`: neověřená uložená kopie.
- `source-offline`: zdroj je nedostupný a ověřená kopie neexistuje.
- `source-inaccessible`: zdroj je neregistrovaný nebo bez oprávnění. Jde
  např. o deskriptor synchronizovaný na uzel bez zdroje. Stav neprozrazuje,
  která z obou příčin nastala.
- `deleted`, `share-revoked`, `not-shared` a `invalid-pin`.

Kontext pro LLM, fork ani repin cache nikdy nepoužijí. Export projektu
(bundle) nese jen deskriptor reference, nikdy bajty zdroje. Odmítnutý úkol
či zpráva se sdíleným vstupem vrací `409` se stavem sdílení a sdělením, že nic
nebylo odesláno.

**Hierarchie projektů mimo rozsah.** Viditelnost nadřazeného projektu do
podprojektů odvozená ze samotné vazby projektů ani výběr výstupů pravidlem
(včetně později vzniklých souborů) toto ADR nezavádí. Vyžadují samostatný
záznam hierarchie a vlastní rozhodnutí; tento kontrakt s nimi počítá jako
s dalším zdrojem oprávnění, nikoli jako s náhradou záznamu sdílení.

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
| Ukončení sdílení | Jedna transakce zdroje: preview nese přesný dosavadní záznam, zápis jej ověří proti `base_head` a změní jen `revoked`. Pád před commitem nic nezmění; stejné operation ID vrátí receipt. Změněný záznam vyžaduje nový náhled. |
| Odebrání reference | Jedna transakce cíle; preview nese digest deskriptoru. Po repinu mezi náhledem a potvrzením se zápis odmítne. Zdroj se nečte ani nemění. |
| Repin a fork | Beze změny podle ADR 0070: zdroj se čte znovu ve `prepare`, cíl drží schválené bajty v journalu. |
| Pád po čtení zdroje při připojení | Intent připravený v journalu cíle se po recovery dokončí se schváleným deskriptorem i tehdy, když zdroj mezitím sdílení ukončil. Každé další čtení pak vrátí `share-revoked`. Atomicita přes oba projekty se nepředstírá. |
| Náhrobek cache | Leží mimo Git a journal, zapisuje se atomicky s fsync. Pád před zápisem jen odloží jeho vznik do dalšího živého ověření; cache sama nikdy nerozšíří přístup. Ztráta celé cache vede k `source-offline`, ne k obsahu. |

Reálný výpadek napájení se nesimuluje. Procesové pády na hranách transakce
pokrývají stávající testy ADR 0070; jejich fixture nyní používá sdílení v2.

## Ověření

`tests.test_cross_references` (30 testů): povinné aktivní sdílení, účel výstupu
a povolený cíl, kanonický a nesmazatelný záznam, konečné odvolání, podvržený
původce či artefakt, práva zápisu ke zdroji a viditelnost cílů, zákaz řetězení,
neměnná provenance při repinu, platnost po smazání podkladu, legacy v1, CLI
a původní scénáře XREF-01.

XREF-02-B (UI): `tests.test_artifact_sharing` (fasáda: nabídky, použití,
skrytí nepřístupných projektů, přesný digest, smazaný zdroj),
`WebTests.test_sharing_routes_share_attach_and_open_with_member_scope`
(HTTP a rozsah člena) a `tests.test_ui_sharing_browser` (skutečný prohlížeč:
sdílet, připojit, otevřít jen ke čtení). HTTP cesty patří do konzervativní
aplikační fronty, protože čtou dva projekty
([vlastnictví HTTP](../http-concurrency-ownership.md#xref-02-sharing-routes-2026-11-21)).
XREF-02-C: `tests.test_cross_references` (nyní 34 testů) přidává ukončení
sdílení s auditem, replay, oprávněním a zachovaným forkem, zastaralý náhled
ukončení, odebrání reference se zachovaným zdrojem a historií a neměnnost již
připraveného manifestu při repinu. `tests.test_artifact_sharing` (6) pokrývá
porovnání revizí, fork, odebrání a ukončení bez prozrazení skrytých cílů.
HTTP test cest ověřuje repin, odmítnuté ukončení členem bez práva ke zdroji,
fork po ukončení (`409 share-revoked`) a odebrání. Prohlížečový test projde
porovnání a aktualizaci, vlastní kopii, ukončení a odebrání.
`ChatServiceTests.test_routed_task_uses_shared_reference_with_exact_pin_and_fails_after_revocation`
ověřuje úkol se sdíleným vstupem a jeho odmítnutí po ukončení sdílení.
XREF-02-D: `tests.test_cross_references` (40) přidává:

- náhrobky po ukončení sdílení a po smazání, platné i pro vlastníka uzlu
  a pro účet, který ztrátu nezjistil;
- rozsah náhrobku `not-shared` na jeden cíl a jeho zrušení živým ověřením;
- skutečné pády procesu u sdílení, ukončení a odebrání v pěti fázích
  transakce, každý s jediným commitem po recovery a opakovaném potvrzení;
- pád připojení po čtení zdroje s ukončením sdílení před recovery;
- export bundle bez bajtů zdroje.

`tests.test_artifact_sharing` (8) pokrývá nesynchronizovaný zdroj
a offline stav s cache i bez ní. `tests.test_desktop` ověřuje hlášku `409`
u odmítnutého sdíleného vstupu a prohlížečový test stav `source-inaccessible`.
Živá akceptace patří k XREF-02-E.
