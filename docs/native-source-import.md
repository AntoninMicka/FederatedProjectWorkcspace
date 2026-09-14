<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->
# Nativní import původních zdrojů

Otevřete projekt a v desktopové liště zvolte **Importovat zdroj…**. Vyberte
Markdown (.md), PNG, JPEG nebo PDF do 16 MiB, vyplňte název/popisek/štítky a
privacy. Před potvrzením nevzniká artefakt. Potvrzení ukáže původní basename,
privacy a SHA-256 vybraných bajtů. Úplná lokální cesta se do metadat nepřenáší.

Původní soubor se nepozmění a jeho bajty se importují bez překódování, stripování
frontmatter či normalizace konců řádků. Vždy vznikne nový UUID adresář obsahující
původní basename a metadata.json. Externí Markdown frontmatter zůstane součástí
obsahu, nikoli autoritou interních metadat. Původní soubor se nemaže.

Nový artefakt má kind=source a provenance=external. created_at je čas vytvoření
importovaného artefaktu a author_id místní importer, ne tvrzení o původním
externím autorovi/datu. Nepřidává se imported_at ani nový provenance manifest;
širší V-04/V-05 tím nejsou uzavřené. SHA-256 je součástí místního operation
intent, nikoli nové sidecar schema field. Obsah zdroje není editovatelný
nativním Markdown editorem; novou verzi importujte jako nový zdroj. Toto není
globální zákaz přímých Git úprav nebo všech obecných Workspace změn.

Privacy má výchozí project. Local-only respektuje stávající síťovou hranici a
může znepřístupnit celý projekt přes web; historický public-only Git přenos
nepřenese ani project/confidential. Import privacy neodvozuje automaticky z
externího souboru. PNG/JPEG/PDF se kontrolují hlavičkou, ne plným bezpečnostním
parserem. Importované HTML/PDF skripty se nespouštějí; preview zůstává omezené
stávajícím textovým/raster workflow. Náhled má nezávislý limit 4 MiB.

## Recovery a reuse

Adaptace Sources→Artifacts→Workspace zachovává writer lock, expected HEAD,
operation ID/digest/receipt a journal z ADR 0003/0016. Nezavádí nový projektový
index, importní DB ani mutující renderer/web endpoint. Obsah a sidecar se
validují jako výsledný snapshot ještě před přípravou journalu.

Před commitem je rozpracovaný soubor/metadatová dvojice řízena journalem;
native načtení projektu ji může dokončit. Po commitu je Git autorita a index
se obnovuje z přijatého HEAD. Cizí změny se nesmějí přepsat. Retry používá stejné
UUID, stejné zachycené bajty a operation ID; nečte při retry znovu externí soubor.
Zavření či načtení nejsou rollback připravené operace. Po restartu/načtení
nejprve ověřte Podklady, než importujete tentýž soubor znovu jako novou operaci.
Automatická deduplikace ani durable outbox pro dosud nepřipravený import nejsou
součástí první verze. Symlinky a změna stat údajů zdroje během čtení se odmítají;
nejde o sandbox proti závodícímu nekooperačnímu procesu.

Implementace je neověřená: nové testy ani skutečný GUI/import běh nebyly spuštěny.
