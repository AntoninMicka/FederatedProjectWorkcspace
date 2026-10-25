<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0053: Revizovaný výběr backendu a modelové nabídky v chatu

- Stav: přijaté pro implementaci
- Datum: 2026-10-25
- Dávka: `UX-BACKEND-MODEL-01`

## Kontext

Sdílený composer již obsahuje volbu backendu a modelu, ale klient skládá
providerově specifické stavy a `ChatRunChoice` nese pouze adapter a text modelu.
AtlasCloud binding je navíc pevně svázán s jednou nabídkou, zatímco OpenAI a
Ollama dovolují textový model odvodit z bindingu. Takový stav neumí bezpečně
model-first filtr, více nabídek jednoho kanonického modelu ani preferenční
pořadí. Provider-neutral katalog z ADR 0051 už odděluje model, nabídku a binding;
tato feature z něj nesmí udělat router ani druhou konfigurační autoritu.

## Rozhodnutí

### Autority a revizovaná projekce

Backendové bindingy a credentials zůstávají autoritou připojení. Reviewovaná
knowledge vrstva a providerové discovery snapshoty zůstávají autoritou identity,
protokolu, dostupnosti a doložených capabilities nabídek. Nová serverová
**projekce voleb** je pouze bounded read model nad těmito stavy; nic neukládá do
projektového Gitu a sama nevytváří binding.

Každá projekce nese vlastní digest/revizi a u každé spustitelné nabídky:

- `adapter_id`, `binding_id` a `binding_revision`;
- `offer_id`, `provider_model_id`, `protocol` a dostupnost/čerstvost;
- volitelný `canonical_model_id` pouze z explicitní knowledge vazby;
- efektivní capabilities se stavem, zdrojem a revizí podle fail-closed
  precedence ADR 0051;
- `knowledge_revision`, `discovery_revision` a capability revision použité
  projekcí.

Stejný providerový název nikdy automaticky neslučuje modely. Nabídka bez
explicitní kanonické vazby je samostatná scoped volba; může být vybrána po
backendu, ale nepoužije se pro křížový model-first filtr ani pro kanonické
preference. Nakonfigurovaný přesný binding se smí promítnout jako spustitelná
nabídka, jen pokud server dokáže doložit jeho identitu, revizi a capabilities;
stale, removed, conflicting nebo unknown požadavek dispatch neopravňuje.

### Obousměrný filtr a explicitní volba

Klient pošle serveru požadovanou operaci a výstup odvozené z existující
role/akce/výstupního formátu. Server vrátí pouze kompatibilní nabídky:

1. bez volby backendu řadí modely podle explicitní preference, nikoli podle
   odhadované kvality;
2. backend-first omezí modely na spustitelné nabídky tohoto bindingu;
3. canonical-model-first omezí backendy na nabídky explicitně mapované na
   tento model;
4. po zvolení backendu i modelu musí zbýt právě jedna nabídka. Pokud stejný
   backend nabízí více protokolů nebo modifikátorů, UI vyžádá explicitní
   variantu; první v pořadí se automaticky nevybere.

Změna jednoho filtru zachová druhý pouze tehdy, je-li stále kompatibilní;
jinak jej viditelně vymaže. Prázdný, offline nebo stale stav je konkrétní
diagnostika, ne prázdná aktivní nabídka. Sdílený `spikes/desktop_ui.py` je
jediný desktop/web widget; providerové větve smí být pouze v serverových
adaptérech a projekci, ne v pravidlech formuláře.

### Preference

`model-preferences.json` je nová node-local autorita se schématem, monotónní
revizí, časem změny a uspořádaným unikátním seznamem
`preferred_model_ids`. Zápis vyžaduje očekávanou revizi, celý dokument se předem
validuje a publikuje se stejným mode-0600 `fsync`/`replace`/directory-`fsync`
vzorem jako katalog. Neznámá nebo později odstraněná ID lze zachovat v
uloženém pořadí, ale UI je nenabízí a nikdy z nich neodvodí oprávnění.

Kompatibilní preferované modely jsou v první úrovni, ostatní pod „Další“.
Preference nevybírají backend, nabídku ani model, nejsou autorizací, fallbackem
ani součástí providerového credentialu.

### Pinning a revalidace před účinkem

Klient potvrzuje `selection_revision` a přesnou identitu nabídky, ne volný text
modelu. Server těsně před preview/prepare znovu sestaví projekci a fail-closed
ověří shodu bindingu, credential reference/revize, offeru, protokolu,
knowledge/discovery/capability revizí, požadované capability, RBAC a privacy.
Neshoda vrátí stale-selection bez dispatch a vyžádá novou viditelnou volbu.

Po úspěšné revalidaci vznikne neměnný `RunSelection`. Jeho kanonický digest
a pole adapter/binding/offer/model/protokol/capability a všechny revize se uloží
do autoritativního provider run journalu ještě ve stavu `prepared`. Stávající
`BackendExecution` se rozšíří nebo verzovaně migruje; nesmí vzniknout druhý
journal. Přechod `prepared` → `dispatching` je nadále jediná hranice externího
účinku. Změna katalogu, bindingu nebo preference po `prepared` nemění uložený
run; adaptér odešle pouze jeho připnutý kontrakt, nebo bezpečně odmítne bez
odeslání, pokud nutný credential už přesné revizi neodpovídá.

## Crash boundaries a recovery

1. Pád před atomickým `replace` preferencí ponechá starou revizi; dočasný
   soubor není autorita. Pád po `replace` může znamenat novou durable revizi,
   kterou klient po novém čtení uvidí.
2. Projekce voleb je obnovitelná z aktuálních bindingů, knowledge, discovery a
   preferencí. Její ztráta nebo restart serveru nevyvolá providerový dotaz ani
   inference a nemění žádný run.
3. Pád před durable `prepared` nezanechá oprávnění k dispatch. Pád po něm a
   před `dispatching` obnoví tentýž připnutý výběr; nesestavuje jej z nového
   katalogu ani preferencí.
4. `dispatching` se po nejasném přerušení nadále obnovuje jako `unknown` bez
   automatického retry nebo volby jiné nabídky. `succeeded` se vrací
   idempotentně; `failed` vyžaduje nový run a novou explicitní volbu.
5. Migrace journalu je startup prerequisite: staré záznamy zůstanou čitelné
   jako legacy bez domýšleného offeru, ale nový dispatch se bez plného
   `RunSelection` nepřipraví. Projektový Git se mění až samostatnou publikací
   výsledku.

## Reuse a odmítnuté varianty

Adaptujeme `ModelKnowledgeStore`/`ModelDiscoveryStore`, `BackendRegistry`,
`BackendCapabilities`, `ChatRunChoice`, existující binding stores, atomický JSON
vzor a jediné provider run journals. Sdílený composer pouze vykreslí
serverovou projekci. Odmítáme porovnání modelů podle názvu, ruční model mimo
nabídku pro nový tok, implicitní první kompatibilní offer, provider fallback,
automatický refresh při submitu, preference providerových offerů a nový
framework či druhý UI/store/journal.

## Důsledky

Nastavení nadále slouží k připojení backendu a získání jeho nabídek; konkrétní
model se volí v chatu. Bez čerstvé a doložené nabídky se nový run neodešle.
První implementace smí migrovat dosavadní bindingy do read modelu, ale nesmí
jejich providerové rozdíly skrýt optimistickou normalizací. Automatické
hodnocení kvality/ceny, auto-selection a fallback zůstávají mimo rozhodnutí.
