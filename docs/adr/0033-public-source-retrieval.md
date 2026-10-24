<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0033 — Bounded získání veřejného zdroje

Datum: 2026-10-17. Stav: přijato jako návrhová hranice
`F-M3-PUBLIC-SOURCES-01`; první řez implementuje
`F-M3-PUBLIC-SOURCE-READER-01` na vlastní feature větvi.

Čitelnou strukturovanou projekci druhého řezu doplňuje
[ADR 0046](0046-structured-public-source-projection.md); síťové, privacy a
recovery hranice tohoto rozhodnutí nemění.

## Kontext

`F-M3-SEARCH-02` pracuje jen s bounded titulkem, URL a úryvkem ze SearXNG.
Samotné promptování proto nezíská fakta dostupná až v cílovém dokumentu.
Průzkum [podporovaných tříd](../public-sources-research.md) zároveň ukázal, že
neexistuje jeden přenosný „web source“ kontrakt: API, katalog, feed a HTML mají
odlišnou identitu, revizi, licenci, kvóty i způsob extrakce.

## Rozhodnutí

Vznikne společná read-only obálka `public-source-fetch-v1` a registr malých
adaptérů. Registr fail-closed deklaruje schema/revizi, podporované origins a
MIME, autentizační režim, druh identity/revize, limity a parser. Neznámý origin,
adaptér, MIME nebo pole se odmítne. Strukturovaný adaptér má přednost; obecný
`static-html-v1` je pouze explicitně zvolený fallback jedné stránky.

Vyhledání, získání a projektová publikace jsou tři oddělené operace:

1. SearXNG run poskytne candidate URL a snippet.
2. Uživatel schválí přesný fetch plán; durable fetch run získá a projektuje
   jediný zdroj.
3. Případné vytvoření projektového `source` artefaktu má vlastní preview,
   expected HEAD, potvrzení a Workspace operaci. Fetch sám do Gitu nezapisuje.

### Binding, request a výsledek

`PublicSourceBinding` nese stabilní binding ID/revizi, adapter ID/revizi,
HTTPS origin allowlist, identifikující User-Agent, autentizační režim a
absolutní maxima. Credential je pouze node-local reference; první statický
adaptér podporuje výhradně `auth: none`.

Kanonický `PublicSourceRequest` nese run/task/user/project ID, privacy,
expected project HEAD, binding a adapter revizi, původ candidate URL/result ID,
normalizovanou přesnou URL, účel, Accept allowlist a limity bajtů, času,
záznamů i textu. Preview hash váže všechna pole; změna cíle nebo limitu znamená
nový plán a nové potvrzení.

`PublicSourceResult` rozlišuje `succeeded`, `unsupported`, `rejected`, `failed`
a `unknown`. U úspěchu zachová request digest, requested/final URL, čas získání,
HTTP status, allowlisted response headers (`Content-Type`, `Content-Language`,
`Content-Length`, `Content-Encoding`, `Date`, `ETag`, `Last-Modified`, `Vary`,
`Cache-Control`, `Retry-After`), raw délku/SHA-256, textovou délku/SHA-256,
adaptérovu identitu/revizi, doloženou externí identitu/revizi/čas/licenci a
explicitní warnings/truncation. Neznámé údaje se neodhadují.

### Síťová a obsahová hranice

- Povolen je pouze `GET` na explicitní `https` URL bez userinfo a fragmentu.
  Výchozí port je 443; jiné porty i IP literal vyžadují jiný výslovný adaptér.
- Každé DNS rozlišení se validuje před spojením. Všechny A/AAAA adresy musí být
  veřejné; loopback, private, link-local, multicast, reserved, unspecified,
  IPv4-mapped a další nelokální výjimky se odmítnou. Spojení se připne k
  validované adrese a TLS stále ověří původní hostname/SNI, aby DNS rebinding
  mezi validací a connectem neotevřel interní síť.
- HTTP redirect se automaticky nenásleduje. Validovaný redirect je nový
  candidate target a potřebuje nový plán; tím se znovu provede origin, DNS,
  privacy a credential kontrola. Credential ani cookie se mezi cíli nepřenáší.
- Wire i decoded bajty, čas, hlavičky, kompresní poměr, počet záznamů, XML/HTML
  hloubka a výsledný text mají samostatné tvrdé limity. `Content-Length` je jen
  časný guard; stream se ukončí i při chybějící nebo lživé hodnotě. Částečný
  obsah se nevydává za úspěch.
- Parser přijímá jen adaptérovy MIME a charset. První vertikála přijímá pouze
  `text/html` a `text/plain`, deklarovaný UTF-8 nebo chybějící charset s plně
  validními UTF-8 bajty a content encoding `identity` či `gzip`; jiné charsety
  a encodingy odmítne. MIME sniffing, PDF, binární soubory, JavaScript, CSS,
  obrázky, formuláře, iframe/object, meta refresh, DTD/entity, remote content a
  další odkazy nespouští.
- `static-html-v1` respektuje RFC 9309 a identifikuje klienta. robots.txt není
  autentizace ani licence; zákaz fetch ukončí. Preview výslovně deklaruje
  nejvýše dva GET účinky stejného originu: RFC 9309 preflight a teprve při
  povolení cílový dokument. Nedostupný robots endpoint se vyhodnotí přesně
  podle RFC 9309, nikoli vždy jako allow. API adaptéry respektují jejich
  oficiální access policy a `Retry-After`.

OWASP doporučuje v SSRF hranici redirecty vypnout a validovat cíle. Stejně tak
upozorňuje, že vzdálený obsah může nést nepřímou prompt injection. Extrahovaný
text je proto vždy označen jako nedůvěryhodná data: nemění system/task policy,
nevolá nástroje, nevybírá další URL a neautorizuje publikaci. Sanitizace není
důkaz bezpečného významu; rozhodující je oddělení dat od oprávnění a
deterministická validace každého následného účinku.

### Recovery, cache a publikace

Samostatný node-local `PublicSourceRuns` journal adaptuje stavy
`prepared → dispatching → succeeded|unsupported|rejected|failed|unknown`.
Nesmí být další tabulkou v `SearchRuns`: search a fetch mají jiný request,
provider, response a neurčitou hranici. Pád před dispatch nezpůsobí síť;
přerušené `dispatching` se označí `unknown` a automaticky se neopakuje.

Úspěšné bounded raw bajty a projekce se nejprve fsyncnou do run-scoped
node-local stagingu, pak se SQLite stav atomicky uzavře. ETag/Last-Modified lze
použít pouze v novém explicitním revalidation runu. Odpověď `304` smí znovu
použít jen stále přítomné přesné bajty se shodným hashem; cache není projektová
autorita a respektuje `Cache-Control`, binding revizi i actor/project privacy.
Chybějící staging zneplatní použitelnost výsledku a vyžaduje nový potvrzený
run; obsah se potichu znovu nestáhne.

Context Manifest odkazuje na run, adapter revizi, raw/text hash a přesnou
projekci. Projektová publikace revaliduje run, privacy, licenci, expected HEAD
a hash a adaptuje metadata v2 podle ADR 0023/0024. Nové externí bajty nebo
revize vytvoří nový source UUID s volitelným `supersedes`; `source_url` není
důkaz licence, autora ani identity. Neznámá licence se nesmí změnit na tvrzení
o volném užití; případná publikace vyžaduje viditelné přiznání neznámých práv a
samostatné rozhodnutí uživatele.

## První implementační řez

`F-M3-PUBLIC-SOURCE-READER-01` implementuje obálku, journal, bezpečný HTTPS
transport a `static-html-v1` pro jednu explicitně vybranou SearXNG URL.
Výchozí maxima jsou nejvýše 2 MiB wire, 2 MiB decoded, 200 000 znaků projekce,
15 sekund a nulové redirecty; menší provider/user limit vyhrává. Parser
deterministicky zachová title, nadpisy, odstavce, položky seznamů a tabulkový
text, ale zahodí aktivní či skryté elementy a nic dalšího nestahuje.

Akceptace zahrne veřejný hostname, private/loopback i smíšené DNS odpovědi,
DNS rebinding, redirect na interní a jiný origin, TLS chybu, timeout, 429/503 s
`Retry-After`, lživý Content-Length, chunked/compressed limit, nečekané MIME a
charset, malformed/deep HTML, robots allow/deny/unavailable, prompt injection
v textu, restart ve všech stavech, stale binding/HEAD a Context Manifest bez
projektového zápisu. Skutečný fyzický průchod použije nejméně dvě nezávislé
veřejné statické stránky; dynamická stránka skončí viditelně `unsupported`.

## Reuse a odmítnuté varianty

- **Adaptovat:** `SearchRuns` state-machine vzor, ale ne jeho databázi;
  stdlib HTTP/TLS validaci z backendů; Context Manifest; bezpečnou textovou
  projekci; immutable `Sources` a jedinou Workspace/journal/Git/index hranici.
- **Nové:** malý adapter registry, `PublicSourceRuns`, SSRF-safe resolver/connect
  hranice a bounded statická HTML projekce. Jde o odlišnou odpověď a recovery
  než search snippet nebo LLM run.
- **Odmítnout:** obecný crawler, automatické následování search výsledků,
  Playwright/WebEngine fallback, session cookies, login, provider SDK pool,
  neoficiální endpointy, tiché MIME sniffing, RAG/vector DB a automatickou
  publikaci. Soukromá reuse inventura neposkytla shodnou komponentu s tímto
  preview/privacy/SSRF/recovery/provenance kontraktem; žádný kód se nepřebírá.

## Podklady

- [Průzkum veřejných zdrojů](../public-sources-research.md)
- [RFC 9110 — HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [RFC 9111 — HTTP caching](https://www.rfc-editor.org/rfc/rfc9111.html)
- [RFC 9309 — Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)
- [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
