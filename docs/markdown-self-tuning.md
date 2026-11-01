<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Izolované self-ladění Markdown editací

Vývojový nástroj `scripts/markdown_self_tune.py` automatizuje opakované pokusy,
které jinak musel uživatel ručně zadávat do Workspace. Každý vybraný model
nejprve vytvoří patche, potom může navrhnout opravu odmítnutého patche a nakonec
úpravu vlastních instrukcí a omezených generačních parametrů. Jde o ladění
instrukcí a parametrů. Produkční kód, nastavení, dokumenty ani oprávnění se
automaticky nemění.

## Spuštění

Příprava syntetického projektu a reportu, bez volání modelu:

```sh
python3 scripts/markdown_self_tune.py
```

Omezená skutečná kampaň nad dvěma již nainstalovanými modely:

```sh
python3 scripts/markdown_self_tune.py --run-live \
  --models qwen3-coder:latest codestral:latest \
  --budget-seconds 480 --max-calls 32 --call-seconds 60 \
  --rounds 1 --repairs 1
```

Výchozí profil přebírá endpoint a tag z potvrzeného node-local bindingu;
`--node` umožní vybrat jeho konfiguraci. Nástroj aktuálně vyžaduje `same-node`.
Před živou kampaní ověří instalované tagy; nic nestahuje, nevybírá náhradní
model a nemění aktivní binding uživatele. Modely zpracovává postupně, aby
nepřepínal GPU mezi modely při každém jednotlivém pokusu.

`--rounds 0` vypne ladění instrukcí, `--repairs 0` vypne opravné návrhy.
Výchozí limity jsou 600 sekund kampaně, 40 volání, 90 sekund na volání,
jedno ladicí kolo a jeden opravný pokus. Strop je 4 modely, 3 kola a 2 opravy.
Čas se kontroluje před každým voláním a během generování přes existující
RunDeadline. Blokující lokální filesystem/Git či připojovací timeouty nejsou
preemptivním limitem celé aplikace. Překročení rozpočtu není úspěšný test.

## Smyčka a pevná kritéria

1. **První pokus:** model dostane stejné připnuté syntetické podklady,
   zadání a blokový kontrakt jako ostatní modely.
2. **Oprava patche:** při dokončené, ale odmítnuté odpovědi dostane původní
   podklady, svůj návrh a diagnostiku. Vrací nový návrh proti původním blokům.
   Každý pokus má nové run ID a odkaz na předchozí pokus. `unknown`, chyba
   providera či samotného harnessu opravnou větev nespouštějí.
3. **Návrh ladění:** tentýž model v oddělené roli `researcher-v2` dostane
   pouze chyby trénovací části a současnou experimentální konfiguraci.
   Vrací hypotézu, dodatek instrukcí do 2000 znaků, výstupní rozpočet
   1024/2048/4096 a teplotu 0/0,1/0,2. Neplatný nebo nezměněný návrh se odmítne.
4. **Nové ověření:** kandidát projde stejnou sadou. Model nemůže změnit
   fixture, rozsah, hashe, parser, validátor ani podmínky úspěchu.
5. **Review:** doporučení vznikne pouze při striktním zlepšení prvních pokusů
   trénovací části a splnění všech odložených případů. Neinstaluje se do
   produkce. Opravný pokus se nepočítá jako úspěch prvního pokusu.

Sada obsahuje opravu českého odstavce s CRLF a přidání úkolu do existující
dávky jako trénovací případy. Přesun sekce s kódem a vytvoření nové dávky
se čtyřmi požadovanými úkoly jsou odložené případy; jejich výsledky se
ladicí roli neposkytují. Roadmapa má 600 původních úkolů, ale model dostává
pouze vybrané místo vložení. Žádný skutečný projekt se nekopíruje.

Kontrola je deterministická: oprava odstavce a přesun sekce musí odpovídat
přesnému očekávanému obsahu včetně konců řádků; roadmapové operace musí
zachovat všechny původní uzly a přidat přesně požadované názvy, typy a
hierarchii. Jde o přísné, konkrétní fixture podmínky, nikoli univerzální
posouzení významu dokumentu. Počet případů je malý a není statistickým
důkazem spolehlivosti modelu.

## Evidence a obnova

Výchozí výstup je nový soukromý adresář `/tmp/fpw-self-tune-…`.
`--output` smí určit novou složku mimo zdrojový checkout. Existující evidence
se nepřepisuje. `report.md` shrnuje modely, profily, první pokusy, opravy
a trénovací/odložené výsledky. `report.json` uchovává nastavení, hypotézy,
run ID, návaznost oprav, chyby, metriky, hash fixtures a zdrojovou revizi
včetně hashů dotčených souborů. Uvádí také necommitnutý stav zdrojů.
Per-run soubory obsahují Context Manifest, providerovou odpověď, případný
náhled/diff či chybu. Úplnou durable evidenci přenosu drží izolovaný OllamaRuns.
`passed` u návrhu ladění znamená pouze platný návrh konfigurace, ne úspěšnou
editaci; výsledky editací jsou v jednotlivých profilech.

Vytvoření testovacího projektu a seedů používá ProjectCreation a Artifacts,
tedy existující journal/Git/index recovery podle [ADR 0003](adr/0003-coordinated-operation.md).
Během modelových pokusů se do tohoto projektu nezapisují výsledné patche;
HEAD, snapshot i čistota pracovního stromu se ověřují jako nezměněné. Report je oddělená diagnostická
projekce. JSON checkpoint se zapisuje atomicky, Markdown přehled je odvozený;
mezi oběma soubory se nepředstírá atomicita. Pád může zanechat poslední
checkpoint a providerový `dispatching` s neznámým výsledkem. Není zde
automatické resume ani přehrání původního run ID. Další kampaň má novou složku,
nové ID a nový explicitní rozpočet; stará evidence zůstává dostupná.

Návratový kód 0 u přípravy znamená pouze připravenou sadu. U `--run-live`
znamená, že poslední vyhodnocený profil každého modelu splnil všechny případy
alespoň po povolené opravě; neprokazuje kvalitu prvního pokusu ani lidskou
akceptaci. Kód 1 znamená neúspěšné/neprovedené případy, kód 2 přerušení nebo
chybu harnessu. Produkční nasazení profilu vyžaduje samostatné review.

## Reuse a omezení

Používají se ContextBuilder, registrované role, blokové schéma, AITaskOutcome,
`validate_patch_proposal`, sémantický task graph, OllamaAdapter/OllamaRuns
a RunDeadline. Experimentální adapter váže generační parametry do přesného
request digestu; v produkčních endpointech není dostupný. Nevolá produkční
chat router ani Qt UI, a proto není náhradou jejich testů či ruční akceptace.
Nemá vlastní writer, nový provider, další databázi ani modelového soudce,
který by mohl prohlásit chybný patch za správný.

`tests.test_markdown_self_tuning` ověřuje celou simulovanou smyčku včetně
opravy, nových run ID, ladicího návrhu, oddělení odložených dat, doporučení,
neměnnosti fixtures, limitů, odmítnutí neznámého výsledku a ochrany evidence.
Skutečné modelové výsledky se uchovávají v reportech jednotlivých kampaní.

## První skutečná kampaň — 1. 11. 2026

Proběhlo 28 nových volání přes skutečnou Ollamu: 16 prvních pokusů,
10 opravných návrhů a dva návrhy ladicí konfigurace. Oba modely samy navrhly
opravy a dodatek instrukcí; žádný modelový výstup se ručně neopravoval.

| Model | Výchozí první pokus | První pokus po ladění | Po opravě laděného návrhu |
| --- | --- | --- | --- |
| qwen3-coder:latest | 1/4 | 1/4 | 2/4 |
| codestral:latest | 2/4 | 2/4 | 3/4 |

Qwen navrhl přesnější zachování textu, instrukci k typům/odsazení úkolů,
2048 výstupních tokenů a teplotu 0,1. Codestral navrhl zdůraznit `type: task`,
1024 tokenů a teplotu 0,1. U Codestralu se opravil trénovací případ s jedním
úkolem, ale zhoršil první pokus o přesun. Opravný pokus přesun napravil.
Nová dávka se čtyřmi úkoly zůstala problémem u obou modelů. Žádný profil
neprošel doporučovací branou a žádný se nepřenesl do produkce.

Úplný soukromý archiv je lokálně v ignorovaném
`.worktrees/markdown-self-tuning-evidence/2026-11-01-72fcc1bc/`.
Obsahuje report, návrhy, diagnostiku a source snapshot s ověřenými SHA-256.
Jde o vývojový pokus, ne o statistický benchmark či akceptaci feature.
Poznámka `ARCHIVE.md` rozlišuje přesnou živě ověřenou verzi od následného
zpřísnění doporučovací brány, kontroly čistého pracovního stromu a doplnění
současné konfigurace do ladicího kontextu. Pozdější změny pokrývají cílené testy. Celá aplikační sada po
přidání tohoto vývojového nástroje nebyla znovu spuštěna.
