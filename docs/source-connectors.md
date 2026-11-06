<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# MON-08-02 — Zdrojové konektory

`spikes.source_connectors` sjednocuje deklaraci konektorů a vstupní položky
pro navazující monitoring. Rozhodnutí a recovery:
[ADR 0075](adr/0075-source-connector-contract.md).

## Dostupnost

| Konektor | Funkční operace | Hranice |
| --- | --- | --- |
| `rss-atom` | Ruční čtení a normalizace RSS 2.0 / Atom 1.0 | Původní bounded HTTPS reader, bez automatického pokračování. |
| `static-text` | Normalizace zachyceného UTF-8 HTML / textu | Nemění přísnější policy/MIME původního SourceCollectoru; PDF nepodporuje. |
| `web-search` | Normalizace existujícího SearXNGResult | Nový dispatch není připojený; stav not-configured. |
| `platform-channel` | Deklarace konfigurace/oprávnění/credential slotu | Unavailable, bez platformního dispatch a bez fallbacku na RSS. |
| `workspace-output` | Read/normalize připnuté vydané zprávy | Vyžaduje registrovaný node, projekt a oprávnění; bez nich not-configured. |

V aplikaci **Zdroje → Typy zdrojů a dostupnost** ukazuje stejné stavy.
Nedostupný nakonfigurovaný kanál se označí také v jeho vlastním přehledu.
Pouhá přítomnost typu v definici sledování neznamená dostupný konektor.
Nová konfigurace odběrů nebo providerů tímto UI nevzniká.

## Společný kontrakt

`SourceConnector.describe()` vrací `fpw-source-connector-v1`: operace,
config fields a uzavřené config schema, požadovaná oprávnění, credential
slots s node-local uložením, limity, dostupnost a způsob pokračování.
Skutečné credentials nejsou argumentem normalizace ani součástí metadat.

`read(config, SourceContext, continuation=None)` a
`normalize(payload, SourceContext)` vracejí `fpw-source-batch-v1`:
`{schema, connector, items, continuation}`. Konkrétní payload normalizace
je uzavřený podle adaptéru: RSS `{raw,url}`, dokument `{raw,content_type,url}`,
search seznam `{title,url,snippet}`; Workspace reader jej sestaví z ověřeného
ReportingTask, ReportSnapshot a přesných Markdown bajtů. Normalizace přebírá
již oprávněná data; sama není aplikačním udělením oprávnění.

Každý `fpw-source-item-v1` obsahuje:

- `id`, `connector`, `source_id`, `source_locator`, `original_id`, `url`;
- `channel`, `author`, `title`, pokud je zdroj poskytl;
- `published_at`, `discovered_at`, `imported_at` jako odlišné UTC údaje;
- `content`, `content_ref`, `content_sha256` pro skutečné bajty či pin;
- `provenance={origin,raw_sha256,input_ref,untrusted}`;
- `privacy` a explicitní aplikační `retention`.

Neznámé údaje jsou null. Datum publikace se nenahrazuje zjištěním/importem.
Zdroj bez GUID může mít identitu odvozenou z původní adresy. Identita je
namespacovaná konektorem a zdrojem, nikoli časem nebo titulkem. Při změně
obsahu se mění obsahový hash; aliases a trvalé sledování oprav navazují
v MON-08-03. Hash celého feedu je jiný údaj než hash obsahu jedné položky.
RSS cache vrací nový kontrakt v `items`; `entries` zůstává UI projekcí pro
kompatibilitu. Raw hash se zachovává u konkrétní revize, ne u pozdějšího
feedu, ve kterém položka už nemusí být.

HTML a další obsah zůstávají inertní data. Uzavřený item odmítne cizí pole
jako `confirmed`, `event` nebo `credentials`. Konektor nezapisuje Event,
nevolá LLM, nehodnotí pokrok a nepublikuje zprávu. Vydaná zpráva Workspace
se ověřuje proti aktuálnímu oprávněnému projektu a přesným pinům; nevydaný
ReportingTask se odmítne. Čtení cizího projektu, snížení privacy, změna hashe
nebo HEAD během čtení selže. Network režim neexportuje local-only projekt.
Network reader navíc vyžaduje aplikačního `actor` a ověří jeho aktuální
project-read oprávnění před čtením. Lokální reader používá autorizovanou
registraci projektu daného uzlu. API pro čtení interních výstupů zde není
nově vystavené do globální sekce Zdroje.

## Limity a pokračování

Limit jednoho vstupu je 512 KiB wire/decoded dat, jednoho batche 500 položek
a 4 MiB JSON, jednoho textu 131072 znaků. Překročení je chyba bez tichého
zkrácení. Dokumentový adaptér používá původní bounded HTML projekci.
RSS zachovává původní bezpečný XML parser, robots a ověření DNS/IP/TLS.

Všechny aktuální adaptéry deklarují `continuation.kind=none`, `persisted=false`.
Cursor, conditional GET a periodické kontroly zatím nejsou implementované;
neprázdné pokračování u read operace selže. Metadata availability neprokazují
dostupnost konkrétní externí služby. Search/platform credentials a budoucí
stav pokračování zůstávají v node-local službě, nikoli v synchronizovaných
definicích. Retention v položce je pravidlo předané aplikací, nikoli nový
automatický retention worker.

## Ověření

`python3 -m unittest tests.test_source_connectors tests.test_rss_pilot tests.test_rss_sources.RSSSourcesTests -v`:
25 testů OK. Ověřeny jsou společné item/batch schéma pro RSS, HTML/text,
výsledky hledání a skutečnou připnutou vydanou zprávu; oddělené časy,
neznámá publikace/autor, nativní identita bez GUID, obsahové hashe,
zachování původního raw hashe a nemožnost vložit potvrzení nebo credentials.
Read-only Workspace scénář nemění HEAD ani pracovní strom. Zamítne
nižší privacy, cizí projekt, chybný hash, nevydaný vstup a network reader
bez project-read oprávnění. RSS odmítne cizí URL/continuation/local-only
před síťovým účinkem; nedostupný platformní kanál nepoužije RSS fallback.

Izolovaný běh `tests.test_rss_sources.RSSSourcesHTTPTests` a
`tests.test_rss_sources_browser` s `M0_DESKTOP_TEST=1`: 3 testy OK.
Ověřena skutečná HTTPS autentizace/RBAC, normalizované položky v API,
zobrazení unavailable/not-configured v katalogu, přepínání kanálů,
inertní titulek a mobilní rozměr. Jde o automatizovaný browser smoke,
nikoli ruční akceptaci běžného profilu. Plná závěrečná sada dávky MON-08
zůstává až před jejím finálním předáním.
