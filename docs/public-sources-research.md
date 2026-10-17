<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Průzkum podporovaných veřejných zdrojů

Stav k 2026-10-17 pro `F-M3-PUBLIC-SOURCES-01`. Jde o návrhový podklad, ne o
seznam právě dostupných služeb ani o implementovaný crawler. Limity, podmínky a
providerové verze jsou proměnlivé; implementace je musí číst z konfigurace,
odpovědí a aktuální dokumentace, nikoli převzít jako trvalé konstanty z této
tabulky.

## Ověřené třídy

| Třída | Ověřený podporovaný vstup | Identita a provenance | Přístup, limity a licence | Rozhodnutí |
| --- | --- | --- | --- | --- |
| Datové katalogy | CKAN Action API nabízí read-only GET `package_search`, `package_show` a podle instance DataStore. DCAT 3 rozlišuje dataset, distribuci, `accessURL`, přímý `downloadURL`, media type, formát, práva a licenci. | Stabilní ID datasetu/resource, URL katalogu, čas získání, případná revize/modified, distribuce a hash skutečně přijatých bajtů. `accessURL` není totéž co přímý download. | Veřejné GET mohou být anonymní, jiné akce chtějí token; konkrétní politika a kvóty patří provozovateli instance. Licenci je nutné převzít z datasetu/distribuce a její absenci přiznat. | **Samostatný deklarativní adaptér**, nikoli obecný CKAN klient. Nechat uživatele vybrat distribuci; katalogový záznam sám neautorizuje stažení ani další použití. |
| MediaWiki/Wikimedia | MediaWiki REST API vrací JSON page objekt, zdroj nebo HTML a umí cílit konkrétní revision ID. Page objekt nese nejnovější revision ID, timestamp, content model a licenční URL/název. | Wiki origin, page ID/key, revision ID, revision timestamp, obsahový model, licence, response hash a čas získání. Konkrétní revision endpoint je reprodukovatelnější než „latest“. | Identifikující User-Agent je povinný. Wikimedia v roce 2026 uvádí globální rate limits a `Retry-After`; čísla jsou experimentální a nesmějí se hardcodovat. Licence se liší podle wiki/projektu. | **Samostatný adaptér** s pinem na revision ID a licenčními poli. Pro Wikimedia respektovat aktuální access/rate policy; pro jiné MediaWiki nepředpokládat stejné limity. |
| Odborná metadata | Crossref REST API poskytuje JSON pro DOI, práce, časové filtry, licence, vztahy a aktualizace. Veřejný a „polite“ přístup nevyžaduje účet; placený Plus používá API klíč. | DOI, endpoint, index/deposit/update date, member/source, vztahy, licenční pole, čas získání a hash odpovědi. Metadata jsou tvrzení vkladatele či označeného důvěryhodného zdroje, ne důkaz pravdivosti článku. | Limity vrací response headers podle zvoleného poolu. Téměř všechna bibliografická metadata jsou otevřená, ale abstrakty mohou zůstat pod copyrightem autora či vydavatele a full-text odkazy mají vlastní podmínky. | **Samostatný metadata adaptér**. Automaticky nenásledovat full-text URL a nezaměňovat licenci metadata záznamu za licenci článku či abstraktu. |
| Syndikované feedy | Atom definuje feed/entry ID, title, author, `updated`, volitelně `published`, summary/content, source a links; HTML standard definuje feed autodiscovery přes `rel=alternate` a Atom/RSS MIME. | Origin feedu, feed ID, entry ID, `updated`/`published`, self/alternate URL, source metadata, response validators a hash. `atom:id` je identifikátor, nikoli povinně dereferencovatelná URL. | Atom `rights` je lidsky čitelná informace a specifikace výslovně říká, že není strojově čitelnou licencí. Vzdálený `content src` nebo enclosure je nový síťový cíl a nesmí se stáhnout implicitně. | **Malý feed adaptér**. RSS vyžaduje vlastní explicitně verzovaný parser; nesmí se tiše vydávat za Atom. Odkazy a přílohy zůstávají jen kandidáty nového potvrzeného fetch plánu. |
| Statická veřejná stránka | HTTPS GET poskytuje reprezentaci s `Content-Type`, případně ETag/Last-Modified a cache directives. HTML nemá obecné povinné schéma pro hlavní text, revizi, licenci ani datum publikace. | Původní a finální URL, HTTP validators, content language/type, čas získání, hash raw bajtů a hash deterministické textové projekce. Autor, datum a licence z HTML jsou pouze doložená pole, nikoli domyšlená fakta. | Pouze explicitně vybraný veřejný cíl, identifikující User-Agent, Robots Exclusion Protocol a podmínky provozovatele. Žádné přihlášení, cookies, browser automation nebo obcházení blokace. | **Omezený fallback**, ne crawler. Jeden potvrzený dokument, bez následování odkazů, assetů či formulářů. Dynamická stránka bez serverového obsahu se označí jako nepodporovaná. |

## Společné závěry

1. Strukturované providerové API nebo feed má přednost, pokud pro daný origin
   existuje zaregistrovaný a verzovaný adaptér. Dokáže zachovat identitu,
   revizi a licenci lépe než heuristická extrakce HTML.
2. Obecný statický reader je přesto potřebný jako omezený fallback pro
   uživatelem vybraný výsledek SearXNG. Není automatickým crawlerem: vezme jednu
   přesnou URL, nestahuje odkazy, skripty, obrázky ani přílohy a neprovádí
   JavaScript.
3. Katalog, search result, feed entry a cílový dokument jsou různé entity a
   síťové účinky. Locator nebo snippet není obsah; odkaz na distribuci či
   full-text se nestahuje bez nového plánu.
4. Licence a práva jsou data se svou provenance. Jejich absence znamená
   `unknown`, nikoli volné použití. `source_url` ani robots.txt licenci
   nedokládají.
5. Providerové kvóty jsou runtime policy. Klient respektuje `Retry-After` a
   deklarované headers, ale po neurčitém výsledku síťový účinek automaticky
   neopakuje.

## Doporučené pořadí implementace

První navazující dávka má být `F-M3-PUBLIC-SOURCE-READER-01`: společný durable
fetch kontrakt a jediný `static-html-v1` adaptér pro explicitně vybraný HTTPS
výsledek. Podporuje pouze serverově dodané UTF-8 `text/html` a `text/plain`,
jednu stránku do pevného limitu, bez redirectu, credentials, cookies,
JavaScriptu, assetů a link traversal. Před dispatch ukáže origin, URL, privacy,
limity a účel; po stažení zobrazí raw/text hash, MIME, čas a HTTP validators.
Text lze po další aplikační validaci připojit jako nedůvěryhodný Context
Manifest vstup, nikoli jako instrukci nebo automaticky publikovaný artefakt.

Tato vertikála přímo uzavírá doloženou mezeru za SearXNG a současně ověří
transport, SSRF, journal a textovou projekci. CKAN/DCAT, MediaWiki, Crossref a
Atom pak mohou přibýt jako samostatné adaptéry bez změny společné obálky.
Pokud statický reader narazí na dynamický obsah, login, blokaci nebo chybějící
serverový text, skončí jako `unsupported`; browserový fallback se nezavádí.

## Oficiální podklady

- [CKAN API guide](https://docs.ckan.org/en/latest/api/)
- [W3C DCAT 3](https://www.w3.org/TR/vocab-dcat-3/)
- [MediaWiki REST API reference](https://www.mediawiki.org/wiki/API:REST_API/Reference)
- [Wikimedia API access policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy)
- [Wikimedia API rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Crossref access and authentication](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
- [Crossref metadata licensing](https://www.crossref.org/documentation/retrieve-metadata/)
- [RFC 4287 — Atom](https://www.rfc-editor.org/rfc/rfc4287.html)
- [HTML feed autodiscovery](https://html.spec.whatwg.org/dev/links.html#rel-alternate)
- [RFC 9110 — HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [RFC 9111 — HTTP caching](https://www.rfc-editor.org/rfc/rfc9111.html)
- [RFC 9309 — Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)

