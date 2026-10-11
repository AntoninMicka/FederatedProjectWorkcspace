<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0030 — Deklarativní katalog výstupních capability

Datum: 2026-10-11. Stav: přijato pro development PoC; descriptor a statický
katalog implementuje F-M4-OUTPUT-ROUTER-01-A, read-only plan/step DAG a jeho
planner boundary zůstávají v dalších úkolech stejné dávky.

## Rozhodnutí

Výstupní renderer nebo nástroj popisuje přenositelný JSON descriptor se striktní
verzí schématu, stabilním ID a verzí capability i modulu. Descriptor je pouze
validovaný vstup deterministického aplikačního routeru. Není executable plugin,
runtime discovery, binding, oprávnění ani potvrzení ke spuštění.

Uzavřený kontrakt v1 nese:

- druh capability (`renderer`, `transformation`, `computation`) a výstupu;
- popis, podporované záměry, příklady pokynů a výslovně nepodporovaná použití;
- pojmenované vstupní a výstupní porty s module-local schema referencí, MIME,
  formátem a cardinality;
- volitelné šablony a instruktážní šablony pouze jako verzované reference s
  SHA-256; instruktážní reference navíc váže očekávané výstupní schéma;
- přesné revize požadovaných rolí a backendových capability, nikoli model,
  endpoint nebo credential;
- limity, privacy, execution boundary, permissions, cost/side-effect třídu,
  provenance, preview a samostatná potvrzení.

Neznámé pole, verze, enum, schema mimo deklarovaný modul, duplicita, nebezpečná
reference nebo nekompatibilní kombinace druhu/výstupu se odmítne. Externí účinek
musí výslovně vyžadovat potvrzení před externím účinkem. Povinný preview váže
také potvrzení před execution; descriptor sám tuto akci neprovádí.

## Katalog a hranice důvěry

Katalog načítá pouze omezený počet regular files s pevným suffixem z explicitně
určeného statického adresáře. Symlinky, neočekávané položky, příliš velké
soubory, duplicitní `(capability_id, capability_version)` a neznámá revize se
odmítají. Výpis je deterministicky seřazený a resolver vrací kopii; změna
volajícím nemění zvalidovanou registraci. Resolver nezkouší jinou verzi,
capability, renderer ani backend.

První descriptor `renderer.web-static` popisuje pouze lokální kompilaci
explicitně seřazených Markdown sekcí do statického webového bundle. Nepublikuje,
nehledá skrytě další projektové artefakty a nespouští skripty ze vstupů.

## Persistence, recovery a návaznost

Tato část pouze čte verzované descriptor soubory a validuje je v paměti.
Nezapisuje projektový Git, obnovitelný index ani node-local journal, takže pád
nezanechá nedokončenou operaci. Budoucí plan/step DAG může descriptor pouze
odkazovat přes přesné ID/verzi a musí jej znovu ověřit. Execution, Context
Manifesty, materializované výstupy, receipts, `unknown`, retry/recovery,
publikace a UI potvrzení patří F-M4-OUTPUT-ROUTER-02 a nemohou být odvozena ze
samotné přítomnosti descriptoru.

## Reuse

Adaptují se bounded JSON parser a validační primitiva `module_manifest`, přesné
revize `BackendCapabilities`/`RoleDefinition` z ADR 0008 a explicitní
artefaktový handoff F-M4-WORKFLOW-01. Existující module manifest zůstává
runtime/API kontrakt modulu; output descriptor jej nenahrazuje ani nerozšiřuje
o credentials. Nový plugin framework ani externí kód nejsou potřeba.
