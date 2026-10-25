<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0051: Provider-neutral katalog modelů, nabídek a schopností

- Stav: přijaté a PoC ověřené
- Datum: 2026-10-25
- Dávka: `F-M3-MODEL-CATALOG-01`

## Kontext

`OpenAIModelCatalog` dnes atomicky ukládá bounded seznam modelových ID pro
jeden OpenAI binding a credential revizi. Je to užitečná discovery cache, ale
směšuje providerovou nabídku s identitou modelu, nenese doložené capabilities
a nelze ji bezpečně sdílet s dalšími adaptéry. `BackendBinding` přitom musí
zůstat přesným potvrzeným cílem konkrétního běhu; katalog není router.

## Rozhodnutí

Katalog má tři oddělené identity:

1. **Kanonický model** je node-local, uživatelsky zkontrolovaná znalostní
   identita. Vzniká explicitním importem nebo editací a nikdy pouhou shodou
   providerového názvu.
2. **Providerová nabídka** je přesná dvojice provideru a jeho modelového ID,
   doplněná explicitním protokolem. `offer_id` je stabilní pouze uvnitř tohoto
   katalogu. Nabídka může, ale nemusí odkazovat na kanonický model.
3. **Backend binding** je existující lokální potvrzená konfigurace endpointu,
   credentials, nabídky a revize. Katalog jej nevytváří, nemění ani nevolí.

Node-local stav mimo projektový Git je rozdělen na dvě autority:

- `model-catalog-knowledge.json` je explicitně reviewovaná znalostní vrstva;
- jeden discovery snapshot na provider/scope je poslední kompletní pozorování
  konkrétního bindingu a credential revize.

Obě vrstvy mají striktní schéma v1, bounded počet a velikost záznamů a jsou
publikovány přes dočasný soubor, `fsync`, atomický `replace` a `fsync`
adresáře. Export znalostní vrstvy neobsahuje endpoint, credential reference,
secret ani dostupnost účtu. Discovery cache není exportem znalostí.
Původní validní `openai-models.json` se při čtení promítne pouze v paměti jako
`stale`, protože starý formát nezná binding revizi. Read-only status proto nic
nezapisuje. Původní soubor se nemaže; až explicitní úspěšný provider refresh
vytvoří nový čerstvý snapshot.

## Capabilities a precedence

Capability je přesný klíč z podporovaného seznamu, boolean hodnota, zdroj,
revize/čas a stav:

- `reported`: údaj oznámený a pro konkrétní nabídku ověřený adapterem;
- `reviewed`: explicitně zkontrolovaný údaj znalostní vrstvy;
- `conflicting`: provider a znalostní vrstva si odporují;
- `unknown`: použitelný údaj chybí.

Vyhodnocení je fail-closed. `reported` má přednost, pokud existuje. Při rozporu
s `reviewed` je výsledkem `conflicting` a capability se nepovažuje za
podporovanou. Pokud provider capability neposkytuje, lze použít `reviewed`.
Neznámý klíč, stav, protokol nebo hodnota se odmítne. Seznam schopností se
nesjednocuje optimistickou unií. Dostupnost, cena, účetní údaje a limity jsou
samostatné vlastnosti a nejsou capability.

První schema podporuje `generate-text`, `text-output`, `json-output` a
`streaming`. Novou capability lze přidat jen novou podporovanou revizí schématu.

## Discovery, stale stav a odstranění

Provider adapter vrátí úplný bounded snapshot. Úspěch jej atomicky nahradí;
chybějící dříve pozorovaná nabídka je `removed`, nikoli automaticky smazaná
znalost. Neúspěšný refresh starý snapshot nepřepíše a read-only projekce jej
smí zobrazit jako `stale` s normalizovanou kategorií chyby. Cache odpovídající
jinému bindingu nebo credential revizi je také `stale` a nikdy neopravňuje
dispatch.

OpenAI Models API v první implementaci hlásí pouze nabídky; textové capability
proto nepředstíráme jako providerem reportované. Existující adapterem ověřené
capabilities bindingu lze zobrazit odděleně jako binding evidence, ale nesmějí
se zpětně připsat každé objevené nabídce.

Ruční model zůstává povolený. Uživatel musí potvrdit konfiguraci bindingu stejně
jako dosud. Refresh, import ani odstranění nabídky nemění aktivní binding,
request digest nebo durable run.

## Crash boundaries a recovery

1. Pád před `replace` ponechá starou autoritu; dočasný soubor není platný
   snapshot a při dalším zápisu se používá nové unikátní jméno.
2. Pád po `replace` a před návratem volajícímu může znamenat, že nový snapshot
   je durable, i když UI výsledek nevidělo. Opakovaný read jej bezpečně načte;
   refresh je read-only providerový dotaz, nikoli inference dispatch.
3. Chyba provideru, timeout, rate-limit nebo neplatná odpověď nemění poslední
   validní snapshot. Projekce jej označí `stale`; automatický retry se nekoná.
4. Knowledge import se nejprve celý validuje a až potom atomicky publikuje.
   Vyžaduje očekávanou předchozí revizi; neplatný, stale nebo přerušený import
   nezmění předchozí znalostní vrstvu.
5. Binding a backend run journal zůstávají samostatnými autoritami. Recovery
   katalogu nesmí znovu odeslat, přesměrovat ani měnit inference run.

## Reuse a odmítnuté varianty

Adaptujeme `OpenAIModelCatalog`, `BackendRegistry`, `BackendCapabilities` a
node-local atomické JSON zápisy. Soukromá inventura sloužila pouze jako
srovnání capability tvaru; její prioritní pool ani kód se nepřebírají.
Odmítáme automatické sloučení podle názvu, výběr prvního dostupného backendu,
provider fallback, capabilities odhadované z názvu a projektový Git jako
úložiště node-local availability nebo credentials.

## Důsledky

Katalog lze rozšířit o AtlasCloud nebo další provider bez změny identity
bindingu. UI může pravdivě ukázat zdroj, čas a konflikt. Cena a account usage
zůstávají mimo capability kontrakt. V1 není veřejný komunitní registr ani
automaticky synchronizovaná znalostní databáze.
