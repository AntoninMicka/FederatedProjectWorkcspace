<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Přímý RSS/Atom pilot

Uživatelem zvolený první kanál je
[ČT24 — Výběr redakce](https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313).
Skript `scripts.rss_pilot` ověřuje přímý odběr a porovnání položek. Jde
o izolovanou experimentální evidenci, nikoli integrovanou funkci Sledování.
Plán a akceptaci drží Workspace; tento pilot nedokončuje MON-08-01/02/03.
Inoreader není implementovaný. Neprobíhá LLM zpracování ani stahování článků.

## Použití

Z kořene zdrojového repozitáře, v prostředí s přístupem k veřejnému HTTPS:

```sh
mkdir -p /tmp/ct24-rss-probe
python3 -m scripts.rss_pilot \
  https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313 \
  > /tmp/ct24-rss-probe/first.json

python3 -m scripts.rss_pilot \
  https://ct24.ceskatelevize.cz/rss/tema/vyber-redakce-84313 \
  --previous /tmp/ct24-rss-probe/first.json \
  > /tmp/ct24-rss-probe/second.json
```

Každý běh vyžaduje úspěšný robots preflight a provede jeden GET kanálu;
redirect ani retry se automaticky neprovádí. Článek se neotevírá. JSON je
nedůvěryhodný obsah zdroje a experimentální historie pozorování. Uchovává
identifikátor, URL, titulek, autora a obsah poskytnutý kanálem, datum publikace
(pokud je známé), čas zjištění a hashe. Obsah včetně HTML zůstává inertní.
Datum zjištění nenahrazuje datum publikace. Datum Atom `updated` se nevydává
za datum publikace.

`counts` rozlišuje nové, opravené a nezměněné položky. Identifikátor a URL
fungují jako alternativní klíče v rámci přesné URL kanálu; jejich konflikt
se odmítne. Oprava přidá revizi a zachová předchozí obsah. Dočasné vypadnutí
položky z feedu ji nevymaže z předané historie. Bez `--previous` jde vždy
o nové samostatné pozorování; pilot nemá skrytou databázi.

Pro offline kontrolu lze přidat `--input /cesta/ke/kanalu.xml`; tehdy neprobíhá
síťový účinek. Předchozí JSON předávejte jako důvěryhodnou lokální evidenci,
nikoli libovolný externí dokument. Nepoužívejte stejný soubor pro vstup
`--previous` i přesměrovaný výstup: shell by jej před čtením zkrátil.

## Reuse, limity a recovery

Reuse: existující `StaticHTMLAdapter._get`, `PublicSourceBinding`, DNS/IP
kontrola a TLS; adaptace dekódování `TextAdapter` včetně kontroly úplného gzip
streamu. Běžný SourceCollector a jeho MIME/policy se nemění. RSS/Atom parser
je nový úzký adaptér nad stdlib ElementTree; odmítá DTD/entities, jiné formáty,
nebezpečná schémata odkazů, nadměrnou hloubku/počet XML uzlů a příliš velký
vstup. Limit odpovědi je 512 KiB, kanálu 500 položek, předávané historie 8 MiB.
Překročení je chyba, nikoli tiché zkrácení. XML je omezeno na UTF-8.

Skript nepíše do Git, SQLite ani projektových artefaktů. Výstup vzniká až po
úspěšném načtení, parsování a porovnání. Při pádu může shell zanechat prázdný
nebo částečný výstup; takový soubor se nepoužije jako další potvrzený stav.
Původní vstupní JSON zůstává zachovaný, pokud se používají odlišné cesty.
Po přerušení síťového běhu nelze tvrdit, že request nebyl odeslán; není zde
automatický retry ani runtime journal. Nevzniká transakce přes persistentní
vrstvy a experimentální JSON nenahrazuje autoritu Workspace.

Integrace do Sledování musí následně použít schválený datový model,
konektorový kontrakt, stávající Workspace writer a recovery podle
[ADR 0069](adr/0069-reporting-source-collector.md) a
[ADR 0073](adr/0073-monitoring-ui-and-period-synthesis.md). Pilot ještě nemá
podmíněné HTTP požadavky, plánování, filtry, UI ani projektový import a
nepředstavuje produkční RSS službu.

## Ověření 6. 11. 2026

`python3 -m unittest tests.test_rss_pilot -v`: 10 testů OK. Pokryty jsou RSS,
Atom, neznámá data publikace, deduplikace po předání JSON novému procesu,
historie oprav a dočasně chybějící položky, XML limity/DTD, robots zákaz,
redirect, nesprávné MIME, neúplná odpověď, HTTP 503 a vadný gzip.

Živý pilot vybraného kanálu: první běh v 16:52:36 UTC načetl 30 nových
položek, druhý v 16:52:46 UTC vykázal 0 nových, 0 opravených a 30
nezměněných. SHA-256 XML obou odpovědí:
`7136e793156445fe16f00a15e8e61bc7939828bdb9ded52c8389fd9e16a55762`.
Výsledky běhů jsou dočasná lokální evidence pod `/tmp/ct24-rss-probe/`;
články ani surový feed se do zdrojového Gitu nepřidávají. Tyto dva běhy
neprokazují dlouhodobou dostupnost kanálu nebo automatický provoz.
