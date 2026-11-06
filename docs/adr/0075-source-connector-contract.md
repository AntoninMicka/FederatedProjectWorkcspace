<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0075 — Společný kontrakt zdrojových konektorů

Datum: 2026-11-06. Stav: implementovaný kontrakt MON-08-02 k review.

## Rozsah a autorita

MON-08-02 navazuje na [samostatná sledování](0074-independent-monitoring-definitions.md)
ve stejné dávce MON-08. Rozsah je kontrakt konektorů, jednotné inertní položky
a přiznaná dostupnost. Nejde o dokončení průběžného sběru nebo celého monitoringu.

IDE export při zahájení čekal na review. Aktuální zadání proto bylo znovu
načteno existujícím `IdeBridge.snapshot` přímo z kanonického Workspace:
projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, HEAD
`c390c4e2bd109eb46c225feaddcc72c3d789f36f`, export
`6a4d6ebdd1fce5058b3b660a138b6ee1556ad98785dac4218348ceb24e289c1e`.
MON-08-02 byl in progress, bez start blockers. Zdrojový základ `e70db00`.
Nový read-only snapshot nenahradil review ani neměnil autoritativní plán.

## Rozhodnutí a reuse

`SourceConnector` deklaruje identitu, operace, uzavřenou konfiguraci,
požadovaná oprávnění, logické credential slots, limity, pokračování a
dostupnost. `read(config, context, continuation=...)` a
`normalize(payload, context)` vracejí `fpw-source-batch-v1` s položkami
`fpw-source-item-v1`. Nepodporovaná operace nebo pokračování selže; nevzniká
tichý fallback. Deklarace požadovaného oprávnění sama není jeho udělením.
Síťové účinky musejí zůstat za aplikačním oprávněním a posouzením přístupu.

Reuse/adaptují se současný RSS/Atom parser a bezpečný transport,
`project_document` pro již zachycený HTML/text, přesný tvar SearXNGResult,
Projects/Reporting/PinnedRef a `SourceCollector.resolve` pro neměnné vydané
zprávy. RSS sekce Zdroje zobrazuje položky přes tento společný model;
starý `entries` view model zůstává kompatibilní projekcí a `items` je vlastní
normalizovaný kontrakt. U starších RSS revizí bez raw hashe se hash nevymýšlí;
nové revize si zachovají hash konkrétního původního feedu i při jeho změně.

Položka má původní identitu/adresu, kanál, autora/titulek, oddělené datum
publikace, zjištění a importu, dostupný obsah či jeho pin, obsahový hash,
provenance, privacy a retenci. Hash obsahu pokrývá přesné UTF-8 bajty obsahu;
raw hash je samostatný hash původního zachycení. Chybějící datum/autor zůstane
null. SourceContext dodává známé aplikační údaje; čas importu se automaticky
nedoplňuje při načtení. Privacy/retence se neodvozují z textu zdroje.

Položky jsou vždy untrusted vstupy. Uzavřená schémata nepřipouštějí pole
potvrzení události, pokroku, průlomu či credentials. Published ReportSnapshot
je při čtení podklad, nikoli automatické potvrzení dalších tvrzení.

Dostupnost je explicitní: RSS umí ruční read/normalize; HTML/text má pouze
normalizaci již zachycených dat; web search umí převést existující výsledky,
ale nový search dispatch není připojený. Platformní konektor je unavailable.
Workspace reader vyžaduje registrovaný node a oprávněný projekt; katalog
globální stránky bez projektové konfigurace jej označuje not-configured.
Vyšší privacy, cizí projekt, neplatný hash, nevydaný vstup a změna HEAD
při čtení vydané zprávy selžou před vrácením položky.

Credential slots jsou pouze názvy požadavků. Skutečné tokeny, hesla a
credential bindingy zůstávají u původních node-local služeb; nekopírují se
do definic, položek nebo výstupů. Tento řez nepřidává credential store.
Veřejná i dostupná soukromá reuse inventura byly zkontrolovány; externí kód
se nepřenášel. Druhý writer, crawler, scheduler, journal a provider SDK byly
odmítnuty jako duplicita nebo navazující scope.

## Persistence, chyby a recovery

Nevzniká žádný nový zápis do projektového Gitu, indexu nebo SQLite journalu.
Normalizace je čistá transformace; neplatná položka odmítne celý batch bez
tichého ořezu. RSS cache se mění až po validaci nového výsledku; předchozí
úspěšný obsah při chybě zůstává. Cache je node-local paměťový pilot.
Po restartu se začíná bez ní, nikoli s údajným potvrzeným stavem sběru.

Původní [ADR 0069](0069-reporting-source-collector.md) nadále řídí schválené
capture/import a jeho fetch journal; tento kontrakt jeho policy ani MIME
neobchází. Ruční RSS pilot má původní omezení bez automatického retry.
Systémové pokračování a podmíněné HTTP nejsou zatím implementované a
deskriptory deklarují `continuation.kind=none`, `persisted=false`.
Jejich připojení patří MON-08-03, nikoli druhému runtime v tomto řezu.

Použití, přesné limity a ověření: [Zdrojové konektory](../source-connectors.md).
