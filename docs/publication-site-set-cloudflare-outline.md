<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Pracovní nástřel: propojené webové výstupy a Cloudflare adapter

Stav: **diskusní návrh, nikoli přijaté architektonické rozhodnutí**.

Tento dokument zachycuje směr k dalšímu promyšlení. Neznamená autorizaci
produkčního deploymentu, změn DNS, vytvoření Cloudflare prostředků ani uložení
credentials. Před implementací se má zpřesnit do ADR a reviewovatelné feature
dávky.

## Cíl

Tři weby chápat jako jeden propojený publikační celek:

```text
Webový celek „Antonín / Proof of Idea"
├── proofofidea.cz   — hlavní prezentace a katalog
├── antoninmicka.cz  — profil, kontakty, odkazy a volitelné CV
├── tonymicka.cz     — timeline
└── společný katalog veřejných projektových výstupů
```

Celek má společnou identitu, šablonu, verzi vydání a potvrzovací operaci, ale
každá doména si zachovává vlastní kombinaci povolených částí a samostatně
zjistitelný stav
deploymentu.

## Rozdělení odpovědností

| Umístění | Odpovědnost |
| --- | --- |
| Nastavení → Moduly | Automatická detekce, verze, kompatibilita a Povolit/Zakázat. Žádný CMS editor ani deployment. |
| Projekt → Výstupy | Vytvoření, editace, náhled a historie propojeného webového celku. |
| Cloudflare adapter | Read-only status, plán změn a potvrzené vytvoření nebo aktualizace deploymentů. |
| Projektový Git | Autoritativní konfigurace webů, kurátorovaný obsah, vazby na projektové výstupy a schválené release záznamy. |
| Node-local stav | Cloudflare credential reference, operation journal, locks, provider receipts a stav `unknown`. |
| Lokální build | Obnovitelné HTML a assety; není autoritou ani důkazem nasazení. |

CMS je nyní nadprojektové. Cílově se editor přesune do projektu jako modul pro
výstupy; globální nastavení ponechá pouze správu dostupnosti modulů.

## Navržený projektový artefakt

Pracovní název: `publication-site-set`.

Artefakt by obsahoval zejména:

- stabilní ID celku a jeho název;
- seznam domén, povolených částí a jejich kurátorovaného obsahu;
- identitu společné šablony a verzi jejího kontraktu;
- pravidla katalogu veřejných projektových výstupů;
- explicitní vztahy na publikované výstupy jiných projektů;
- provider-neutral deployment targets bez credentials;
- poslední schválenou release identitu a provenance.

Katalog se nemá ručně duplikovat. Jednotlivé projekty vystaví veřejný
publikovatelný výstup a `publication-site-set` na něj vytvoří explicitní vztah.
Výběr nesmí vzniknout skrytým procházením všech soukromých projektů.

## UI projektu

Navržený tok v **Projekt → Výstupy → Webové stránky**:

1. vytvořit nebo otevřít propojený webový celek;
2. přidávat domény a editovat jejich části Profil, CV a Timeline;
3. spravovat společnou šablonu a katalog;
4. vytvořit náhled celého release, ne jen izolované domény;
5. zobrazit přesný seznam zahrnutých projektových výstupů;
6. uložit konfiguraci do projektu přes standardní expected-HEAD a journal;
7. načíst read-only stav Cloudflare;
8. zobrazit deployment plán;
9. samostatně potvrdit externí create/update operaci;
10. po operaci znovu načíst provider stav a ověřit publikovaný obsah.

## První Cloudflare adapter

Výchozí varianta k posouzení je jeden Cloudflare Pages projekt pro každou
kořenovou doménu, svázaný společným Workspace release ID. To zachová oddělený
obsah a stav domén, zatímco Workspace je obslouží jako jeden celek.

Alternativa je jeden Worker s host-based routingem a assety všech domén. Má méně
providerových projektů, ale přidává runtime routing a větší společný blast
radius. Volba Pages versus Worker zatím není uzavřena.

Adapter má pro každý cíl rozlišit alespoň:

- `missing` — providerový projekt neexistuje;
- `current` — publikovaný obsah odpovídá schválenému release;
- `outdated` — existuje novější schválený obsah;
- `drifted` — provider konfigurace se liší od očekávaného stavu;
- `partial` — deployment existuje, ale doména, DNS nebo TLS nejsou připravené;
- `unknown` — externí požadavek mohl proběhnout, ale odpověď se ztratila;
- `unavailable` — stav nyní nelze bezpečně načíst.

Souhrnný stav celku se odvozuje ze stavů jednotlivých domén. Tři externí
deploymenty nejsou atomická transakce; celek tedy může být dočasně `partial`.

## Preview a potvrzení deploymentu

Před externí změnou se zobrazí přesný plán pro každou doménu:

- vytvoření nového projektu, nebo aktualizace existujícího;
- identita a hash nasazovaného release;
- cílový Cloudflare účet a projekt bez zobrazení tajných údajů;
- změny custom domain, DNS a dalších bindings;
- operace, které se provedou, a operace ponechané beze změny.

Upload obsahu, připojení custom domain a změny DNS mají být samostatně viditelné
a potvrzené kroky. Povolení modulu samo o sobě nikdy neopravňuje k deploymentu.

## Crash boundaries a reconciliation

1. Workspace uloží operation ID, přesný potvrzený plán a hash release před
   prvním externím voláním.
2. Před voláním provideru se stav přepne na `dispatching`.
3. Ztracená nebo přerušená odpověď se zaznamená jako `unknown`; operace se
   automaticky neopakuje.
4. Recovery nejprve načte skutečný Cloudflare stav a porovná projekt, deployment
   a release hash.
5. Teprve doložený provider stav dovolí označit krok jako `completed`, nabídnout
   bezpečné pokračování nebo připravit nový potvrzovaný plán.
6. Receipt každé domény se uchová odděleně; souhrnný receipt odkazuje na všechny
   dílčí výsledky.

Projektový Git se nesmí automaticky vracet kvůli částečnému externímu účinku.
Provider credentials zůstávají mimo projekt, logy a verzované dokumenty.

## Navržené etapy

1. Uzavřít schéma `publication-site-set` a přesun CMS editoru do Projekt →
   Výstupy, stále pouze s lokálním buildem.
2. Přidat read-only Cloudflare binding a kontrolu stavů bez mutací.
3. Přidat preview přesného create/update plánu a explicitní potvrzení.
4. Implementovat journalovanou provider operaci včetně `unknown` a
   reconciliation.
5. Samostatně přijmout DNS, TLS, cache, opakovaný deploy a částečné selhání na
   skutečných doménách.

## Otevřené otázky

- Cloudflare Pages projekty po doménách, nebo jeden Worker s host routingem?
- Má být katalog součástí jednoho „portfolio“ projektu, nebo samostatného
  publikačního projektu?
- Jak projekt explicitně zpřístupní výstup do nadprojektového katalogu?
- Má změna DNS vyžadovat ještě druhé potvrzení oddělené od uploadu?
- Kde se bude spravovat node-local Cloudflare connection, pokud globální
  Nastavení → Moduly smí obsahovat jen Povolit/Zakázat?
- Jaký providerový identifikátor nebo obsahový hash spolehlivě doloží, že živý
  deployment odpovídá schválenému Workspace release?
- Má částečně úspěšný release umožnit dokončit zbývající domény, nebo vždy
  vyžádat nový společný plán?

## Poznámky k doplnění

Sem lze průběžně zapisovat nové nápady před převodem návrhu do ADR:

- 
