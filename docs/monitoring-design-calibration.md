<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Návrhy sledování podle skutečných ukázek zdroje

Upřesnění uživatele 12. 11. 2026: funkční ladění sledování musí vycházet
z obsahu konkrétního zdroje, nikoli pouze ze slovního zadání tématu.
Shodná redakce je vodítko, ne záruka stejného formátu jiného kanálu.

V přehledu Filtry nebo Komplexní úlohy použijte návrh pomocí LLM, popište
cíl a vyberte jeden až tři již definované RSS/Atom kanály. Odeslání formuláře
výslovně spouští načtení ukázek a předání katalogu a ukázek nastavenému modelu.
Neaktivuje průběžný sběr, nepřepisuje filtr a nevydává zprávu.

Pro každý kanál se bez původního filtru načte plná odpověď RSS, nejvýše
prvních osm položek a dvě odkazované stránky stejného originu. Výběr se
neomezuje dosavadními klíčovými slovy: tím by se mohly skrýt právě chybně
vyřazené případy. Jde o aktuálně dostupné okno kanálu, které může obsahovat
starší články, nikoli úplný historický archiv. Starší článek mimo toto okno
ani jiný kanál stejné redakce tím nejsou ověřené.

Kontext obsahuje titulek, popis, publikovaný čas, RSS/Atom kategorie,
adresy, hash RSS, přesnou revizi zdroje a dostupný text odkazované stránky.
Stránka se převádí původním statickým HTML readerem, může obsahovat navigaci
a může být zkrácená; není vydávána za garantovanou extrakci pouze těla článku.
Nedostupnost, robots zákaz, redirect, odlišný origin nebo chybějící text
nevedou k alternativnímu zdroji či credential fallbacku. Selhání samotného
RSS zastaví návrh před modelovým účinkem.

Model dostává skutečné kontrakty bloků a filtrů. Doslovná klíčová slova
nemají české skloňování ani odstraňování diakritiky. Pro různé tvary má model
navrhnout explicitní omezený regex a doložit jej ukázkami. Například slovo
`ukrajina` samo nevybere text s `Ukrajiny`; regex `ukrajin` oba tvary pokryje.
Volba výrazů závisí na cíli uživatele a ukázkách, nejde o univerzální pravidlo.

Celý text odkazované stránky a její RSS kategorie jsou zde kontextem pro
návrh. Nejsou implicitně připojené k runtime položce ani novými poli filtru.
Runtime prohledává skutečné `title`, `content`, `author`, `url`, `channel`.
RSS `content:encoded`, je-li dostupné, má přednost před krátkým `description`;
Atom používá svůj původní content/summary. Návrh nesmí předstírat, že při
každém sběru automaticky stáhne také plný text odkazu nebo najde štítky,
které konektor do runtime položky nepředává.

Po návrhu proběhne skutečný `monitoring_filters.evaluate` nad normalizovanými
RSS položkami. Review ukáže vybrané, vyřazené, čekající nebo chybové výsledky
nových/upravených filtrů i filtrů převzatých navrženou komplexní úlohou.
Neověřený kanál je přiznaný. Ukázky nejsou ručně označený referenční dataset;
shoda s tématem i úplnost výběru zůstávají k posouzení uživatelem. Návrh lze
upravit a uložit původním CAS API. Samostatný návrh filtru nevyžaduje vytvořit
komplexní úlohu. Preview má limit šestnácti filtrů.

## Vlastnictví, soukromí a obnova

Reuse/adapt: původní `block-compose`, worker flock, job ID a journal,
`ContextBuilder` s Context Manifestem a privacy kontrolou před modelovým
dispatch, uzavřená validace bloků/filtrů a `MonitoringBlocks.save`.
Čtení stránek používá původní veřejný DNS/TLS transport, robots, omezení
dekódování a HTML projekci. Nepřibývá úložiště ani druhý writer.

Před prvním načtením existuje durable composition intent s výběrem kanálů,
typem návrhu a HEAD. Přerušení během čtení/modelu ponechá unknown; stejné ID
neprovede druhý GET ani model dispatch. Změněný požadavek stejné ID nepřevezme.
Před modelem se ověří původní HEAD. Původní modelový journal a manifest
nadále nesou kontext podle svých retenčních pravidel. Do projektového Gitu
ani message poolu ukázky nevstupují; vlastní review výsledek nese pokrytí,
hash, adresy a rozhodnutí, nikoli kopii těl článků. Původní expirace jobů a
recovery z [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md) zůstávají.

Nejvýše tři kanály, osm položek a dvě stránky na kanál, 8 000 znaků na stránku,
4 000 znaků RSS ukázky a celkem 192 KiB příkladového kontextu. Síťová čtení
neprovádějí modelové instrukce z článků; manifest přenáší data jako nedůvěryhodná.
Local-only zdroj se pro síťové vzorkování odmítne. Přijaté synchronizované
definice samy žádné vzorkování nespouštějí.
