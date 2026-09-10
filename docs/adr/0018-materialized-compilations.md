<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0018 — Materializované kompiláty jako lokální cache

Datum: 2026-09-10. Stav: **designed**, přijatý návrh na požadavek uživatele (M1-AH-01). Implementace, datový kontrakt a UI zatím neexistují. Navazuje na [architekturu](../../ARCHITECTURE.md), [datový model](../../DATA_MODEL.md) a [Context Manifest / execution boundaries](0008-context-and-publication-contracts.md).

## Účel a autorita

Kompilát je soubor s výsledkem zpracování vybraných projektových zdrojů podle zadání, například orientační rozpočtová obálka. Je obnovitelnou lokální cache, nikoli autoritativním artefaktem, rozhodnutím nebo projektovým SQLite indexem. Jeho odstranění nesmí ztratit zdroje ani zadání. Výstup se necommituje, neverzuje a nepřenáší při federaci či exportu projektu; patří mimo projektový Git do oddělené cache uzlu/projektu. Nedoplňuje se nový kind do dnešního schématu v1.

Zachované zadání zahrnuje stabilní ID, instrukce, pravidlo výběru zdrojů a požadovaný výstup. Přenositelné zadání má být verzovanou projektovou definicí; konkrétní serializace a validace vzniknou před implementací, bez skryté změny stávajícího schématu. Lokální binding backendu a credentials zůstávají mimo projektový Git. Git tedy nadále drží autoritativní vstupy a definice, nikoli cache jejich výsledků.

Chce-li uživatel výsledek zachovat jako podklad rozhodnutí, explicitně jej uloží jako nový běžný verzovaný artefakt s provenance a vazbou na vstupy. Tato operace používá Workspace a ADR 0003; není automatickou součástí aktualizace cache. Ruční opravy samotného zahoditelného výsledku se nesmějí vydávat za trvale uloženou práci.

## Ruční aktualizace a aktuálnost

Uživatel spustí „Aktualizovat ze zdrojů“. Výběr může být explicitní seznam stabilních ID nebo uložené pravidlo, například zdroje určitého typu/štítku. Pravidlo se při každém spuštění znovu vyhodnotí nad jedním validovaným commitem: zahrne aktuální verze i nové odpovídající položky a rozpozná odstraněné zdroje. Nové položky se nepřidávají mimo pravidlo. Chybějící povinný zdroj či neplatná definice znamená chybu, nikoli tiché vynechání.

Lokální manifest výsledku nese project ID, revizi/hash zadání, commit vstupů, seznam ID a hashů skutečně použitých bajtů, konfiguraci/verzi zpracování, čas vzniku a hash výstupu. Změna zadání, vstupů nebo výsledku výběru znamená neaktuální cache. Nový HEAD vyžaduje opětovné ověření výběru a hashů; neověřený výsledek se nesmí označit jako aktuální. Změna zdrojů během výpočtu nezmění zmrazené vstupy; hotový výsledek zůstane označený svou verzí a případnou neaktuálností.

UI rozlišuje chybějící, aktuální, neaktuální, probíhající a neúspěšný výpočet. Poslední úspěšný výsledek lze zobrazit s jeho stářím, pokud k němu uživatel stále smí přistupovat. Otevření projektu, změna zdroje ani restart nespouštějí výpočet automaticky. Obnovitelnost znamená možnost nového výpočtu; u LLM negarantuje shodné bajty výsledku ani dostupnost původního backendu.

## Privacy a obnova

Přístup ke cache podléhá současným oprávněním ke zdrojům; cache nesmí obejít revokaci ani zachovat dostupnost zakázaného obsahu. Výsledek dědí omezení všech vstupů, bez implicitního snížení privacy. Externí zpracování používá explicitní Context Manifest a autorizaci podle ADR 0008; local-only nesmí opustit lokální hranici. Kompilát lze vytvořit i bez LLM; volba backendu ani vektorové DB tímto návrhem není předepsána.

Zápis výsledku proběhne do soukromé dočasné generace. Po ověření se soubor a manifest zveřejní jako jedna úplná generace atomickou změnou lokálního ukazatele; čtenář nikdy nespojí manifest s jiným výstupem. Souběžné aktualizace stejného kompilátu se serializují. Pád před zveřejněním ponechá poslední úplnou generaci; neúplný dočasný výsledek lze uklidit. Pád po zveřejnění umožní znovu načíst tuto generaci. Chybějící či poškozená cache vyžaduje nový ruční výpočet, nikoli opravu autoritativních zdrojů.

Run record potenciálně placeného LLM volání je oddělený autoritativní lokální stav, nikoli zahoditelná cache. Nejasný výsledek po pádu je unknown a nesmí vyvolat automatické opakování podle ADR 0008. Mazání cache nesmí mazat run record, pending journal ani credentials. Konkrétní implementace musí ověřit atomické zveřejnění, fsync hranice a bezpečný úklid na podporovaném filesystemu; tento návrh není důkaz crash odolnosti.

## Zařazení a ověření návrhu

Roadmapa eviduje schopnost samostatně v sekci 2E. Závisí na projektových zdrojích a metadatech M1; LLM varianta navazuje na Context Builder a backendy M2/M3. Není novou podmínkou Gate M1. Implementační krok se připraví podle priority v pracovní dávce; tato změna dokončuje pouze požadovaný návrh.

Reuse/adapt: zachovat validované Git snapshoty a ID artefaktů; pro případné uložení výsledku jako artefaktu použít Workspace, pro LLM ADR 0008. SQLite projektový index ani journal nepoužít jako úložiště cache. Existující katalog reuse neposkytuje důvod zavádět další storage framework.

Návrhová kontrola pokrývá změnu/verzi/přidání/odstranění zdroje, změnu zadání, změnu HEAD během výpočtu, nedostupný backend, revokaci přístupu, odstranění cache a pád před/po zveřejnění. Implementační akceptace musí tyto scénáře ověřit testy a navíc prokázat, že Git/export/federace neobsahují cache. Aktuální evidence dokončení návrhu je v [TODO](../../TODO.md); žádné runtime testy této schopnosti zatím neexistují.
