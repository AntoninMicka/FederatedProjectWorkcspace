<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0030 — Deklarativní katalog výstupních capability

Datum: 2026-10-11, rozšířeno 2026-10-12. Stav: přijato a lokálně PoC validated
pro descriptor, statický katalog, read-only plan/step DAG, aplikační review
planner návrhu a první durable execution `renderer.web-static` v dávkách
F-M4-OUTPUT-ROUTER-01/02. Julia, LLM a externí publikační capability zůstávají
samostatnými navazujícími adaptéry.

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
krok a nevytváří materializaci.

## Planner boundary a vysvětlení

Planner smí vrátit pouze uzavřený návrh `propose-output-plan` s lidským účelem a
plánem v1. Jeho text ani JSON nejsou autoritou. Aplikace při každém review znovu
validuje celý plán proti aktuálnímu reviewovanému katalogu a samostatné policy,
porovná project ID/HEAD a každý použitý artifact nebo materializovaný snapshot s
autorizovaným aplikačním stavem. Plannerem přidané schválení, execution akce,
vysvětlení, endpoint nebo jiné pole se odmítne.

Vysvětlení jednotlivých kroků generuje deterministicky aplikace. Uvádí přesnou
capability a verzi, typovou/policy/privacy bázi volby, execution boundary,
cost/side-effect, potřebná potvrzení a pouze ty alternativy, které mají shodný
vstupní i výstupní kontrakt a procházejí důvěryhodnou policy. Dostupnost runtime
se z názvu capability neodhaduje.

Výsledkem review je kanonický hash návrhu a plánu a handoff se stavem
`not-authorized`. Handoff pouze vyjmenovává kontroly, které musí budoucí
execution zopakovat: katalogové revize, policy hash, HEAD, autorizaci a bajty
artefaktů, hashe materializací a privacy/port kontrakty. Neobsahuje credential,
binding, model ani approval token a sám nesmí být přijat jako pokyn ke spuštění.
Ruční ověření popisuje
[checklist output routeru](../output-router-acceptance.md).

## Execution, persistence a recovery

Read-only validace F-M4-OUTPUT-ROUTER-01 nadále nic nezapisuje a platný plán ani
planner handoff nepředstavují approval. Execution F-M4-OUTPUT-ROUTER-02 je
samostatná aplikační operace s UUID. Před spuštěním znovu ověří přesnou policy,
hashe descriptorů a plánu, aktuální project HEAD, Git blob ID i skutečné bajty
artefaktů a úplné receipty dřívějších materializací. Privátní preview ukáže
přesné zdroje, kroky, privacy a zamýšlený lokální účinek. Approval digest váže
kanonický request a tento preview; změna kteréhokoli vstupu vyžaduje novou
operaci a potvrzení.

Autority jsou oddělené:

- projektový Git je pouze autoritou vstupních artefaktů; execution jej nemění;
- mode-0600 SQLite journal v privátním node-local adresáři je autoritou requestu,
  approval, stavů plánu/kroků, manifestů a receiptů;
- materializační cache je obnovitelná node-local projekce. Každá generace má
  úplné immutable bajty a kanonický receipt, indexovaný přes přesný producer
  plan, step a output SHA-256. Cache se necommituje ani nefederuje.

Krok přejde z `pending` do durable `dispatching` ještě před voláním přesné
reviewované runtime implementace. Jeho deterministický run contract váže plan,
project commit, policy/descriptor hashe, approval, privacy a hashe všech
skutečných vstupních bajtů. Výstup vznikne v mode-0700 staging generaci;
jednotlivé soubory jsou mode 0600, fsyncnuté a zveřejněné atomickým rename.
Teprve validní bounded výstup a receipt dovolí stav `completed`. Potomek smí
použít jen takto doložený výstup s kompatibilním portem a znovu ověřeným hashem.

Crash boundaries a recovery:

1. pád před `dispatching` ponechá připravenou operaci, kterou lze po opakované
   revalidaci spustit se stejným approval digestem;
2. pád po `dispatching` bez přesně doložené generace vede při explicitní
   reconciliation do `unknown`; krok ani potomci se automaticky neopakují;
3. pád po atomickém zveřejnění, ale před zápisem receiptu do SQLite dovolí
   explicitně převzít pouze generaci se shodným manifest hashem, výstupním
   hashem a kontraktem; renderer se podruhé nevolá;
4. `failed`, `unknown`, chybějící/stale vstup nebo nevalidní výstup označí dosud
   nespouštěné potomky `blocked`. Není dovolena jiná verze capability, backend,
   model ani fallback.

První runtime registry obsahuje pouze přesný `renderer.web-static@1.0` ve
`same-process` hranici. Vstupní Markdown dekóduje jako bounded UTF-8 a v HTML
náhledu jej pouze escapuje do `pre`; zdrojový HTML/script nikdy nespouští.
Výsledkem je bounded JSON static-site bundle a lokální materializace, nikoli
publikace. Julia runner, externí provider, project write a nasazení vyžadují
vlastní reviewovaný adaptér, run journal a podle účinku další samostatné
potvrzení/recovery kontrakt. Návrhový kontrakt Julia adaptéru uzavírá
[ADR 0057](0057-julia-computation-contract.md); implementace zůstává v
`COMP-02`.

## Reuse

Adaptují se bounded JSON parser a validační primitiva `module_manifest`, přesné
revize `BackendCapabilities`/`RoleDefinition` z ADR 0008, durable stavový vzor
F-M4-WORKFLOW-01 a atomická generace z ADR 0018. Existující module manifest
zůstává runtime/API kontrakt modulu; output descriptor jej nenahrazuje ani
nerozšiřuje o credentials. `Workspace` se záměrně nereuse jako zapisovač,
protože materializace není projektový artefakt. Publication CMS ani Cloudflare
adapter se nereuse jako renderer: jejich oprávnění a externí účinky jsou jiné.
Soukromá inventura neposkytuje komponentu se shodným plan/step manifestem,
approval digestem a durable `unknown`; kód se z ní nekopíruje. Nový plugin
framework, fronta, vektorová DB ani externí knihovna nejsou potřeba.
