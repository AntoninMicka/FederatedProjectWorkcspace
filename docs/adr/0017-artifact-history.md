<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0017 — Historie dokumentu pouze pro čtení

Stav: přijato pro M1-04, lokální Linux PoC. Navazuje na [čtení projektu](0014-project-read.md) a [editor](0016-markdown-editor.md). Git zůstává autoritou; nevzniká kopie historie v SQLite.

## Rozsah a reuse

Společné tlačítko Historie v náhledu dokumentu otevře samostatnou stránku se seznamem commitů a výběrem dvou verzí. Zobrazí původní Markdown, metadata vybrané verze, autora/datum/zprávu commitu a textový diff uložených souborů. Přejmenování souboru uvnitř artefaktu patří do historie stejného UUID. Rozepsaný text se do historie neposílá ani se při jejím otevření/uzavření nemění; dosud neuložený nový dokument historii nemá.

Služba `ArtifactHistory` adaptuje autorizovaný přístup Artifacts/Projects ke Workspace, Git wrapper, validaci projektového commitu a sdílenou funkci document. Společný HTML/JavaScript frontend ji používá přes dva úzce typované endpointy pro seznam a porovnání; všechna data vkládá pouze přes `textContent`. Síťový adaptér navíc nad validovaným aktuálním snapshotem odmítá `local-only`. Nevznikla nová knihovna, storage ani obecný Git endpoint. Existující katalog neposkytuje důvod nahrazovat lokální Git cestu cizí komponentou.

## Čtecí kontrakt

Každé volání dostane registrované project UUID, artifact UUID a očekávaný úplný HEAD z editoru. Pod neblokujícím společným zámkem ověří pending stav, větev, absenci nevyřešeného merge, projektovou identitu a validitu současného snapshotu. Dokument musí existovat v aktuálním projektu. HEAD se kontroluje před i po čtení; změna vede k chybě a požadavku na nové načtení editoru. Historie nevolá recover. Projektový index není zdrojem historických dat.

Seznam používá full-history/topologický průchod commitů dosažitelných z vybraného HEAD pro adresář konkrétního artifact UUID. Neomezuje se na first-parent; obě větve merge zůstávají viditelné. Změny jiných artefaktů nejsou verzemi vybraného dokumentu. Zobrazení je omezené na nejnovějších 100 záznamů s explicitním upozorněním na zkrácení; nejde o kompletní prohlížeč všech větví/reflogu. Commit metadata mají limit 64 KiB a Git volání sdílejí deadline služby 60 sekund.

Každý historický snapshot se validuje včetně schématu project.json, jeho project UUID a celého artefaktového snapshotu. Historická konfigurace se porovnává s historickým commitem, nikoli s dnešním pracovním project.json; kontrola současné pracovní konfigurace zůstává povinná. Nevalidní/nepodporovaná verze zůstane označená v seznamu, ale porovnání ji odmítne. Smazání dokumentu ve starší verzi je reprezentováno absencí, nikoli prázdným dokumentem. Prohlížení nyní smazaných artefaktů nemá vlastní vstup v editoru.

Porovnání přijímá pouze úplné hash ID commitů a znovu ověří jejich dosažitelnost z očekávaného HEAD. Není možné předat cestu, revspec, cizí nedosažitelný objekt nebo větev místo commitu. Obsah a metadata se čtou z Git blobů, nikoli z pracovních souborů. Diff má explicitní rozsah artifact adresáře; používá textový režim bez externích diff nástrojů, textconv, barev a rename heuristik. Ukazuje skutečné souborové změny včetně frontmatteru/sidecaru, nikoli pouze změnu názvu/indexu. Při stejné dvojici verzí je diff prázdný.

## Hranice zápisů a UI

Hranice ADR 0014 se nemění. Konstrukce Workspace smí inicializovat lokální journal/index/lock; historie netvoří projektové operace, nezapisuje obsah, nemění HEAD, staging ani node identitu. Pending operace se pouze odmítne. Pád během čtení nevyžaduje novou recovery proceduru; další načtení zopakuje validaci. Nejde o rozšíření záruk při výpadku napájení ani o produkční Git sandbox (V-06).

Frontend dovolí jen jeden aktuální request token; změna výběru a nový požadavek vymažou předchozí obsah, takže pozdní odpověď ani chyba nevydává starou verzi za novou. Výstupy jsou pouze pro čtení. Historie nepřidává tlačítko pro checkout/reset/revert a nezasahuje do editorového draftu. PoC limit těla dokumentu zůstává 1 MiB. SQLite čekání, HTTP timeout a Git deadline nepředstavují preempci libovolného blokujícího filesystemového syscallu.

Ověření drží [testy historie](../../tests/test_artifact_history.py) a společných HTTP adaptérů; aktuální stav aktivní dávky a omezení jsou v [TODO](../../TODO.md).
