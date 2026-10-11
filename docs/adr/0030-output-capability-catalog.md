<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0030 — Deklarativní katalog výstupních capability

Datum: 2026-10-11. Stav: přijato pro development PoC; descriptor a statický
katalog implementuje F-M4-OUTPUT-ROUTER-01-A a read-only plan/step DAG
F-M4-OUTPUT-ROUTER-01-B. Planner boundary zůstává v posledním úkolu stejné
dávky.

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

## Read-only kompoziční plán

Plán v1 je uzavřený dokument s kanonickým UUID plánu, projektu a kroků, přesným
Git commitem a odkazem na samostatně dodanou důvěryhodnou policy. Reference
policy váže její ID, revizi a SHA-256 kanonických bajtů. Plán proto nemůže
rozšířit seznam capability, permissions, privacy tříd, execution boundaries,
cost tříd nebo side effects změnou vlastní deklarace.

Každý krok odkazuje přesné `(capability_id, capability_version)` a váže vstupní
porty na jednu z těchto explicitních referencí:

- projektový artefakt s artifact ID, commitem, bezpečnou cestou, blob ID,
  SHA-256, velikostí a typovým kontraktem;
- dříve materializovaný výstup s ID a hashem zdrojového plánu, step ID,
  output portem, SHA-256, velikostí a typovým kontraktem;
- pojmenovanou hranu z výstupního portu jiného kroku.

Schéma, MIME a formát musí přesně vyhovět oběma portům a počet vazeb cardinality
descriptoru. Hrana dědí privacy producenta, krok nejpřísnější privacy svých
vstupů a celý plán nejpřísnější privacy všech zdrojů a kroků. Každá hrana má
právě jednu cílovou vazbu, každý deklarovaný snapshot zdroje se skutečně použije
a graf musí být acyklický. Neznámá capability nebo verze, změněný hash policy,
oslabení privacy, nepovolené oprávnění či hranice a nekompatibilní port se
odmítnou bez fallbacku. Projektový artefakt s commitem
odlišným od plánu se rovněž odmítne; ověření plánu proti aktuálnímu HEAD a
skutečným bajtům zdrojů provede až aplikační revalidace před execution.

Validace plán pouze parsuje a porovnává s katalogem a policy. Nečte obsah
artefaktů, neověřuje runtime dostupnost, nevybírá binding/model, nedispatchuje
krok a nevytváří materializaci. Aplikační revalidace nedůvěryhodného návrhu
planneru a vysvětlení volby patří F-M4-OUTPUT-ROUTER-01-C.

## Persistence, recovery a návaznost

Tato část pouze čte verzované descriptor soubory a validuje plán v paměti.
Nezapisuje projektový Git, obnovitelný index ani node-local journal, takže pád
nezanechá nedokončenou operaci. Plan/step DAG descriptor pouze odkazuje přes
přesné ID/verzi a při každé validaci jej znovu ověří. Execution, Context
Manifesty, vznik nových materializovaných výstupů, receipts, `unknown`,
retry/recovery, publikace a UI potvrzení patří F-M4-OUTPUT-ROUTER-02 a nemohou
být odvozena ze samotné přítomnosti descriptoru nebo platného plánu.

## Reuse

Adaptují se bounded JSON parser a validační primitiva `module_manifest`, přesné
revize `BackendCapabilities`/`RoleDefinition` z ADR 0008 a explicitní
artefaktový handoff F-M4-WORKFLOW-01. Existující module manifest zůstává
runtime/API kontrakt modulu; output descriptor jej nenahrazuje ani nerozšiřuje
o credentials. Nový plugin framework ani externí kód nejsou potřeba.
