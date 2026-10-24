<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Akceptace Public Source Readeru

Tento checklist ověřuje reader `F-M3-PUBLIC-SOURCE-READER-01` a jeho čitelnou
strukturovanou projekci `F-M3-PUBLIC-SOURCE-READER-02`. Reader načte nejvýše
jednu uživatelem vybranou HTTPS URL z durable výsledku SearXNG. Není to
crawler, browser ani automatický import do projektu.

## Předpoklady

- Spusťte desktop z aktuální feature větve a otevřete testovací projekt.
- V Nastavení nakonfigurujte funkční SearXNG a Ollamu.
- Proveďte řízené hledání, které vrátí nejméně dvě nezávislé veřejné statické
  HTTPS stránky. Pro negativní scénář zvolte také dynamickou aplikaci bez
  podporovaného viditelného serverového textu.
- Nepoužívejte stránky vyžadující účet, session cookie nebo souhlas s odesláním
  neveřejných dat.

## Fyzický průchod

1. U prvního výsledku stiskněte **Načíst stránku**. Před potvrzením nesmí
   vzniknout staging ani síťový GET readeru. Journal může obsahovat pouze
   durable stav `prepared`, aby přesný náhled a jeho digest přežily restart.
2. Zkontrolujte přesnou URL, origin, privacy, nulové redirecty, limity a dva
   deklarované účinky: `GET /robots.txt` a podmíněný GET dokumentu.
3. Náhled zrušte. Neproběhne síť ani projektový zápis; u výsledku lze připravit
   nový run, starý `prepared` záznam se nesmí automaticky odeslat.
4. Připravte náhled znovu, potvrďte jej a ověřte výchozí **Strukturovaný
   výtah**. Nadpisy, odstavce, vnořené seznamy a tabulky musí být ve
   srozumitelném pořadí; navigace a footer se nesmí promíchat s článkem.
   Skripty, styly, skryté elementy a odkazy se nespustí ani nestáhnou.
5. Přepněte na **Původní bounded text** a zpět. Obě zobrazení jsou inertní a
   přepnutí nevyvolá síť. Ověřte run ID, počet bloků, textový i projekční
   SHA-256 a výslovnou informaci, že projekt nebyl změněn. `git status` a HEAD
   testovacího projektu zůstanou stejné.
6. Restartujte desktop. U stejného výsledku použijte **Zobrazit načtený text**;
   musí se načíst z durable stagingu bez nového síťového požadavku.
7. Stejný průchod zopakujte na druhém nezávislém statickém originu.
8. Dynamická/JavaScript-only stránka musí skončit viditelně `unsupported`,
   nikoli prázdným úspěchem nebo spuštěním browserového fallbacku.
9. Je-li k dispozici run vytvořený před druhým řezem, otevřete jej po restartu.
   Musí se zobrazit původní textový fallback bez migrace, nového fetch nebo
   změny historických hashů.

## Automatické a negativní scénáře

Spusťte cíleně:

```sh
python3 -m unittest tests.test_public_source tests.test_context_builder -v
```

Testy musí pokrýt přesný binding/request/preview digest, privátní, loopback,
IPv4-mapped a smíšené DNS odpovědi, connect pinning, robots allow/deny a
nedostupnost, redirect, autentizaci, TLS/timeout hranici, `429/503`, lživý nebo
příliš velký `Content-Length`, wire/decoded/gzip limity, MIME, charset,
malformed/deep HTML, prázdný dynamický shell, prompt injection jako inertní
text, nadpisovou cestu, vnořené seznamy, tabulkové řádky, duplicitní stabilní
anchory, starý textový run, stale HEAD/preview, restart
`dispatching → unknown` a poškozený textový i strukturovaný staging.

## Hranice výsledku

Úspěšný run zachová request digest, requested/final URL, allowlisted hlavičky,
raw/text délku a SHA-256, adapter/binding revizi, čas a dostupné HTTP
validators. Nový run navíc zachová schema, SHA-256 a počet bloků strukturované
projekce. `PublicSourceInput` váže Context Manifest na run ID, adapter revision,
source URL, raw/text hash a hash projekce včetně anchorů. Neznámá licence,
autor nebo externí revize se neodhadují. Samotný fetch nikdy nevytváří Git
artefakt; taková publikace by vyžadovala nový preview, expected HEAD a
explicitní potvrzení.
