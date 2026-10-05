<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0028 — Jeden Cloudflare Worker pro jeden publikační portál

Stav: přijato pro první adapter v `MOD-01-UI-G` jako **PoC validated**. Živý
provider release, veřejné HTTPS a cache hit byly akceptovány 2026-10-05;
adapter DNS ani Custom Domains nespravuje a jejich změnový lifecycle nebyl
testován.

## Kontext a rozhodnutí

Současné domény tvoří jeden obsahový celek a jeden release. První Cloudflare
adapter proto mapuje stabilní `portal_id=main` na jeden předem existující Worker
a nasazuje všechny vygenerované domény jako jednu verzi Workers Static Assets.
Worker vybírá adresář assetů podle přesného `Host`; neznámý host odmítne. Schéma
node-local bindingu nese `portal_id`, takže pozdější samostatné portály mohou mít
vlastní Worker, credential a release bez změny významu domény.

Workspace Worker automaticky nevytváří. Tím první operace potřebuje pouze
oprávnění aktualizovat existující Worker a nevyšší oprávnění pro vytvoření
providerového prostředku. Připojení Custom Domains a změny DNS nejsou součástí
uploadu: UI je uvádí jako `unchanged`/`unmanaged` a budou mít samostatný plán a
potvrzení.

Cloudflare Account ID, název Workeru a revize credentials jsou node-local.
Token je v privátní SQLite databázi s režimem 0600, nikdy se nevrací rendereru,
neukládá do projektového Gitu ani do receiptů. Read-only kontrola načítá skutečný
aktivní deployment a jeho verzi. Release SHA-256 se ukládá do anotace
`workers/tag`; shoda tagu a lokálního potvrzeného release znamená `current`.
Adapter dále rozlišuje `missing`, `outdated`, `drifted`, `partial`, `unknown` a
`unavailable`. Stav obsahu se uvádí pro každou doménu, i když mají společný
deployment.

## Potvrzení a recovery

Preview obsahuje účet, Worker, release hash, všechny hostnames, akci vytvoření
nové Worker verze, převod 100 % provozu a výslovné nezměnění DNS/Custom Domains.
Potvrzení lokálního generování neopravňuje k deploymentu; externí změna má
vlastní checkbox, `operation_id` a potvrzovací endpoint.

1. Přesný plán a release hash se uloží do node-local journalu ve stavu
   `prepared`.
2. Ještě před prvním mutačním Cloudflare voláním se stav změní na `dispatching`.
3. Adapter založí asset upload session, nahraje vyžádané buckety, vytvoří Worker
   verzi s host routerem a asset bindingem a vytvoří deployment se 100 % provozu.
4. Jakákoli chyba po přechodu do `dispatching` znamená `unknown`; požadavek se
   automaticky neopakuje, protože některý vzdálený krok už mohl proběhnout.
5. Read-only refresh načte aktivní verzi. Pouze shodný `workers/tag` smí neznámou
   operaci uzavřít jako `completed`; jinak zůstává otevřená k ručnímu posouzení.

Projektový Git se kvůli částečnému externímu účinku nevrací. Lokální `dist/sites`
je stále jen obnovitelný vstup uploadu, nikoli důkaz deploymentu.

## Omezení

Adapter je implementovaný proti přímému Cloudflare Workers API a testovaný s
deterministickým provider transportem včetně ztracené odpovědi a reconciliation.
Živá akceptace 2026-10-05 doložila, že asset upload může vedle dokumentovaného
HTTP 200 vrátit také úspěšný HTTP 202 s completion JWT; adapter proto přijímá
200, 201 a 202, ale nadále vyžaduje úspěšnou Cloudflare envelope a platný JWT.
Shoda DNS/TLS/cache se ověřuje odděleně od providerového deployment receipt.
Správa Custom Domains, vytváření Workeru, rollback na předchozí verzi a více
portálů jsou oddělené navazující schopnosti.

Použitý tok odpovídá dokumentaci Cloudflare pro
[přímý upload Static Assets](https://developers.cloudflare.com/workers/static-assets/direct-upload/)
a [Workers deployments API](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/subresources/deployments/).
