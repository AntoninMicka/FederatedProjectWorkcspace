<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0036 — Explicitní jazyk odpovědi LLM

Datum: 2026-10-22. Stav: přijato v dávce `F-M2-CHAT-LANGUAGE-01` na úrovni
designed; fyzická akceptace na reálném modelu zůstává otevřená.

## Kontext

Jazyk zadání neurčuje spolehlivě jazyk odpovědi. Gemma může na české zadání
odpovědět slovensky a současný běh neobsahuje dohledatelnou informaci, který
jazyk uživatel požadoval. Skrytý překlad výstupu by změnil providerovu odpověď,
zakryl nedodržení požadavku a přidal další nezaznamenaný modelový účinek.

## Rozhodnutí

Jazyk odpovědi je provider-neutral policy s normalizovaným BCP 47 tagem.
Precedence je od nejslabší po nejsilnější: **uzel → projekt → vlákno → běh**.
Výchozí hodnota nového uzlu je `cs-CZ`. Projekt a vlákno dědí, dokud uživatel
neuloží vlastní hodnotu; volba v promptu je jednorázový override běhu.

Při přípravě každého běhu se dědění uzavře na konkrétní `{tag, source}`. Tato
hodnota je součástí payloadu i Context Manifestu a adapter ji převede na
explicitní instrukci provider requestu. Chat turn trvale ukládá tag, zdroj a
stav `unverified`; pozdější změna výchozí hodnoty tedy nemění historii.
Stejný payload používají Ollama i OpenAI adapter, takže policy není odvozena z
providera ani modelu.

UI zobrazuje BCP 47 volbu v promptu a u odpovědi požadovaný jazyk i stav shody.
První verze jazyk automaticky nedetekuje: `unverified` je pravdivější než
heuristický odhad. Providerovu odpověď nepřekládá, nepřepisuje a neslibuje
deterministické dodržení. Pozdější detektor smí stav změnit jen jako samostatný
dohledatelný výsledek, nikoli jako podklad skryté opravy.

## Persistentní hranice a recovery

Uzlová a projektová preference je atomický node-local JSON mimo projektový
Git. Preference vlákna a materializovaný jazyk turnu jsou v autoritativním
chatovém SQLite store. Změna thread preference používá očekávanou revizi.
Příprava zprávy a její jazykové provenance probíhá v jedné SQLite transakci;
pád před commitem nezanechá ani jedno. Po commitu se retry stejným turn ID musí
shodovat i v jazyku. Context Manifest a provider request jsou svázané digestem
existujícího run journalu; neznámý síťový účinek se kvůli jazyku neopakuje.

## Reuse a odmítnuté varianty

Řešení reuse/adaptuje atomický node-local settings vzor, `ChatThreads`,
`ContextBuilder` a existující adapter/run journaly. Nepřidává překladač,
language-detection knihovnu, nový provider adapter ani projektový artefakt.
Odmítá se odvození jazyka pouze ze zadání, provider-specific nastavení bez
manifestu, tiché přeložení odpovědi a tvrzení, že prompt jazyk garantuje.

## Akceptace

Automatické testy musí pokrýt normalizaci a odmítnutí neplatného tagu,
precedence, atomický zápis, migraci chatového store, přesný payload/manifest,
provider request, idempotenci turnu a restart. Fyzická akceptace na Gemmě ověří
`cs-CZ`, pokračování stejného vlákna, jednorázovou změnu dalšího běhu a restart;
případná jazyková odchylka musí zůstat viditelnou nezměněnou odpovědí.
