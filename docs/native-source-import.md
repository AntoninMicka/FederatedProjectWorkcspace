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
externím autorovi/datu. Nové importy zapisují schema v2 s blokem `import`:
`imported_at`, `imported_by`, SHA-256 původních bajtů a jméno/verzi importéru.
Volitelný původní autor, datum a revize se zapíší pouze pokud je importér dostane
jako doložený vstup; běžný picker je nevymýšlí. Přesný kontrakt popisuje
[ADR 0023](adr/0023-metadata-and-import-provenance.md). Obsah zdroje není editovatelný
nativním Markdown editorem; novou verzi importujte jako nový zdroj. Cílová
pravidla neměnných bajtů, nového UUID a vztahu `supersedes` popisuje
[ADR 0024](adr/0024-source-immutability-and-versioning.md). Transition validátor
proti přímým Git úpravám zatím není implementován.

Importní dialog nabízí samostatné volitelné pole **Doložený čas vzniku zdroje
(UTC)** ve formátu RFC3339, například `2024-05-10T14:30:00Z`. Tento údaj se uloží
jako `source_created_at`; čas importu vznikne automaticky a může být pozdější.
Nevyplněný čas vzniku se neodhaduje z času souboru, importu ani Git commitu.

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

V1 zdroj se nemigruje automaticky. Programová operace `Sources.migrate_source`
vyžaduje jeho UUID, aktuální HEAD a commit, který artefakt původně přidal jako
native Workspace import. Ověří ancestry, nepřítomnost artefaktu v rodiči,
Workspace trailer, shodné neměnné údaje i bajty. Teprve potom převezme
`created_at`/`author_id`, spočítá hash z importního blobu a jednou Workspace
operací zapíše v2; původního autora, datum, URL ani revizi nedoplňuje.

Import je lokálně PoC validated; aktuální důkazy a omezení drží
[F-M1-IMPORT-01 ve WORK_LOG](../WORK_LOG.md#f-m1-import-01--nativní-import-zdrojových-dokumentů--2026-09-14).
Designed pravidla ADR 0024 sama nedokládají jejich budoucí vynucení.
