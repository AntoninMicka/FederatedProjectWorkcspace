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

Nad adapter registry vznikne read-only **katalog podporovaných backendů**.
Descriptor backendu je kódem/verzovaným manifestem doložená identita a nese
zobrazovaný název, stav podpory, typ hranice a množinu služeb. Služby jsou
oddělené od modelových capabilities; první kontrakt rozlišuje alespoň
`text-generation`, `image-generation`, `web-search`, `storage-import` a
`resource-metrics`. Backend tedy nemusí poskytovat modely a jeden backend může
poskytovat více nesouvisejících služeb. Neznámá služba ani capability se
nepředstírá jako podporovaná.

Nastavení spojení je providerově specifický `BackendProfile` (endpoint,
credential reference, hranice, timeouty a další pravidla adapteru), nikoli
volba modelu. Dosavadní bindingy s modelem se migrují beze ztráty jako legacy
profil plus doložená nabídka; dokud migrace neumí oddělení prokázat, zůstane
profil čitelný, ale nový obecný dispatch se z něj nepovolí optimisticky.

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

### Nastavení backendů a modelový katalog

Sekce Nastavení zobrazí backendy stejným seznamovým vzorem jako federaci:
jedna tabulka všech podporovaných backendů, jejich stav připojení,
dostupnost a deklarované služby. Tabulka má pouze akce **Nastavit** a
**Resetovat**. Nastavit otevře vlastní dialog adapteru; dialog mění jen profil
připojení/credentials a smí explicitně provést read-only discovery nebo test.
Model pro běh se v dialogu backendu nevybírá. Reset vyžaduje samostatné
potvrzení, odstraní profil a jeho credential bezpečným providerovým lifecycle,
ale nemaže historii runů, modelovou knowledge vrstvu, poslední bezpečně
čitelné discovery snapshoty ani modelové preference. Ty se pouze promítnou jako
nedostupné/stale a nelze jimi autorizovat dispatch.

Do dokončení migrace legacy Ollama bindingu je jeho povinné pole `model`
výslovnou bootstrap výjimkou: dialog nabídne read-only načtení `/api/tags`, ale
při nedostupném discovery dovolí přesné ID zadat ručně. Ruční hodnota nevytváří
libovolnou per-run nabídku; až uložený revizovaný binding ji promítne jako jedinou
binding-scoped fallback nabídku. Úspěšné discovery se uloží pro přesnou revizi
bindingu a umožní výběr dalších doložených Ollama modelů v chatu.

Obecný modelový katalog dostane samostatnou stránku Nastavení. Tabulka ukáže
všechny kanonické modely i nesloučené scoped nabídky napříč backendy, jejich
dostupnost, čerstvost a souhrn schopností. Detail modelu je v této dávce
striktně read-only: oddělí obecné reviewované capabilities od efektivních
capabilities každé providerové nabídky a u každé hodnoty ukáže stav/provenance,
protokol a revizi. Konflikt, unknown a chybějící kanonická vazba zůstanou
viditelné. Dosavadní JSON import znalostí není součástí tohoto uživatelského
pohledu a nesmí z read-only dialogu vzniknout skrytá editace.

Konfigurace backendů je pouze pro oprávněného správce uzlu. Read-only katalog
smí vidět běžný uživatel v rozsahu backendů dostupných jeho uzlu, ale nikdy
endpoint secret, credential reference ani providerová account data, k nimž nemá
oprávnění.

### Zdroje a spotřeba backendů

Backend descriptor deklaruje také podporované resource metriky. Jednotná
read-only projekce rozliší:

- spotřebu uložených runů (`tokens`, requesty, trvání), jejímž zdrojem jsou
  validované providerové odpovědi v run journalu;
- providerový account usage/cost za vymezené období;
- aktuální balance/credits, volné tokeny, předplacené tokeny a quota/limit,
  pouze pokud je backend skutečně reportuje doloženým API; volná a předplacená
  zásoba zůstávají samostatné resource kinds a neslévají se spotřebou;
- kapacitní zdroje jako storage, pouze pokud je jejich scope a jednotka
  adapterem jednoznačně definovaná.

Každá hodnota nese adapter/backend, resource kind, scope, jednotku, období nebo
okamžik měření, `fetched_at`, stav čerstvosti a provenance. Spotřeba se nesmí
vydávat za zůstatek a chybějící metrika se z nuly neodhaduje. AtlasCloud dnes
dokládá tokeny z dokončených runů; to není důkaz živého kreditního zůstatku.
Monitor zobrazí obecné provider cards a u AtlasCloud ihned tuto doloženou
tokenovou spotřebu. Kredity zobrazí až po implementaci a ověření příslušného
provider resource adapteru.

Read-only otevření monitoru samo neprovádí placený ani mutující dotaz.
Explicitní refresh má bounded odpověď, deadline, bez automatického retry;
selhání zachová poslední validní cache jako stale a nikdy nemění routing,
binding ani run.

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
6. Reset backendu je vícevrstvá operace jen nad profilem a credentialem. Nejprve
   se durable odstaví profil pro nové dispatch, poté se odstraní credential;
   ztracená odpověď se obnoví read-only stavem. Historické runy a katalogové
   snapshoty se nemažou. Pokud adapter neumí atomický reset doložit, stav je
   `reset-pending` a nový dispatch zůstane zakázaný.
7. Resource refresh publikuje pouze kompletní validovanou cache. Pád nebo chyba
   provideru ponechá poslední validní report stale; nikdy nedoplní nulu,
   neodečte kredit lokálním odhadem ani nespustí inference.

## Reuse a odmítnuté varianty

Adaptujeme `ModelKnowledgeStore`/`ModelDiscoveryStore`, `BackendRegistry`,
`BackendCapabilities`, `ChatRunChoice`, existující binding stores, atomický JSON
vzor, `backend_metrics`, jediné provider run journals, settings tabulky/dialogy
a provider cards monitoru. Sdílený composer i Nastavení pouze vykreslí
serverové projekce. Odmítáme porovnání modelů podle názvu, ruční model mimo
nabídku pro nový tok, implicitní první kompatibilní offer, provider fallback,
automatický refresh při submitu, preference providerových offerů a nový
framework či druhý UI/store/journal, ruční per-run model mimo doložené discovery
nebo přesný legacy binding fallback, jednu univerzální konfigurační formu pro
všechny providery a smíšení backendových služeb, modelových capabilities,
spotřeby a zůstatku do jednoho boolean příznaku.

## Důsledky

Nastavení nadále slouží k připojení backendu a získání jeho nabídek; konkrétní
model se volí v chatu. Tabulka backendů je rozšiřitelná i na providery bez
modelů a modelový katalog je samostatný read-only pohled. Bez čerstvé a
doložené nabídky se nový run neodešle.
První implementace smí migrovat dosavadní bindingy do read modelu, ale nesmí
jejich providerové rozdíly skrýt optimistickou normalizací. Automatické
hodnocení kvality/ceny, auto-selection a fallback zůstávají mimo rozhodnutí.
