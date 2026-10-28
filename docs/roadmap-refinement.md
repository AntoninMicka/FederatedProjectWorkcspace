<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# DEV-01 — iterativní refinement importované roadmapy

První bezpečný řez třídí pouze samostatné Markdown podklady z oddílu
`Samostatné podklady bez jednoznačného přiřazení`. Same-node Ollama smí
navrhnout připojení pod existující milestone/batch/task nebo ponechání
samostatně. Nesmí vytvořit ID, přepsat obsah, změnit stav, sloučit ani smazat
artefakt. Interní text modulového projektu se neposílá do hostitelského běhu.

## Lokální queue a opakování

Proposal queue je privátní node-local SQLite mimo projektový Git. Každý běh
používá explicitní Context Manifest, přesný project HEAD, samostatný Ollama run
a fingerprint projektu, obsahu, katalogu cílů a revize analyzátoru. Sdílená
node-local databáze filtruje `list`, rozhodnutí i apply vždy podle project ID.
Stavy:

- `pending` čeká na lidské rozhodnutí;
- `accepted` lze zahrnout do apply;
- `rejected`, `dismissed` a `applied` jsou pro stejný fingerprint terminální;
- `unknown` se automaticky neopakuje, protože odpověď mohla vzniknout;
- `failed` zachovává chybu i bounded raw odpověď a také se tiše neopakuje.

Změna analyzátorové revize vytváří nový fingerprint. Konvergence nastane
jen tehdy, když každý aktuální samostatný podklad skončí v terminálním
stavu; starý `unknown/failed` jiné revize ji neblokuje.

## CLI workflow

```bash
PROJECT=c898b941-8eb0-4406-8dad-6e2b96c06d59

python3 -m scripts.roadmap_refinement --project "$PROJECT" scan --limit 5
python3 -m scripts.roadmap_refinement --project "$PROJECT" list

python3 -m scripts.roadmap_refinement --project "$PROJECT" decide \
  --proposal PROPOSAL_UUID --accept
# nebo --reject

python3 -m scripts.roadmap_refinement --project "$PROJECT" apply \
  --operation-id NOVÉ_OPERATION_UUID
```

Úplná sémantická kontrola importovaných roadmapových zdrojů používá nový režim
téže služby a stejný výstupní seznam návrhů:

```bash
python3 -m scripts.roadmap_refinement --project "$PROJECT" scan \
  --deep-check --limit 25
python3 -m scripts.roadmap_refinement --project "$PROJECT" list
python3 -m scripts.roadmap_refinement --project "$PROJECT" tui \
  --deep-check --limit 5
```

První deep-check běh před jediným LLM voláním zmrazí všechny source clustery,
exact HEAD, nalezené výskyty v nových podpůrných souborech a současný task graph
do privátní queue. `--limit` omezuje počet requestů jednoho běhu, nikoli počet
inventarizovaných položek. Opakované spuštění pokračuje pouze položkami
`queued`; přerušené `running` přejdou fail-closed do `unknown`. Accepted
strukturované deep-check návrhy zatím nelze aplikovat: bezpečný společný writer
pro kolize, cykly a jednu Workspace transakci je další otevřený řez.

Pro jednorázové interaktivní review lze nad stejnou queue spustit stdlib
`curses` TUI:

```bash
# Interaktivní výběr dostupného projektu podle názvu a UUID:
python3 -m scripts.roadmap_refinement tui --limit 5

# Nebo přímé otevření známého projektu:
python3 -m scripts.roadmap_refinement --project "$PROJECT" tui --limit 5
```

Projektový selektor používá `j`/`k` nebo šipky, `Home`/`End`, potvrzení
`Enter` a ukončení `q`. Nedostupný registrovaný projekt nelze otevřít. Parametr
`--project` zůstává povinný pro neinteraktivní příkazy `scan`, `list`, `decide`
a `apply`.

Klávesy: `j`/`k` nebo šipky mění vybraný řádek, `Tab` přepíná fokus tabulky a
detailu a `PgUp`/`PgDn` stránkuje aktivní panel. `Home`/`End` skočí na začátek
nebo konec tabulky. `h` přepíná skrytí již rozhodnutých stavů (`accepted`,
`rejected`, `dismissed`, `applied`); `pending`, `failed` a `unknown` zůstávají
viditelné. `s` explicitně spustí bounded scan, `a` přijme pending návrh, `r` jej
zamítne, `p` připraví apply a teprve následné `y` jej provede; jiná klávesa
apply zruší. `q` rozhraní ukončí. TUI nemá vlastní storage ani writer: pouze
volá stejné `list`, `scan`, `decide` a `apply` hranice. Ollama scan probíhá
v background threadu a během něj se zobrazuje stav běhu; tabulka i detail dál
reagují. TUI nedovolí ukončení, dokud běh neskončí, aby lokální proces
nezanechal nejasný dispatch outcome pouze kvůli zavření rozhraní.

Levý panel má pojmenované sloupce stav, návrh a `zdroj → cíl`; místo samotných
UUID načítá názvy z přesné revize návrhu. Pravý panel vysvětluje navrženou akci,
odkud podklad pochází, jeho skutečnou cestu, cílové ID/název/typ, očekávaný
dopad, odůvodnění modelu a náhled zdrojového textu. UUID a HEAD jsou až v auditní
části. Delší detail se posouvá přes `PgUp`/`PgDn`.
Každý tabulkový řádek je dvouřádkový blok s ohraničenými buňkami. Vybraný blok
se při pohybu drží uprostřed viditelné stránky, pokud tomu nebrání začátek nebo
konec seznamu.
Importované názvy a náhledy se před vykreslením dělí na fyzické řádky a řídicí
znaky se převádějí na mezery. Newline, tab ani carriage return proto nemohou
pohnout curses kurzorem a přepsat sousední buňky.

`scan` ani `decide` nemění projekt. `apply` vezme všechny accepted návrhy
se stejným expected HEAD a zapíše pouze hlavní plán jednou
`Workspace.transact` operací. Před zápisem znovu ověří existenci dokumentu,
cíle, metadata a celý task graph. Přerušený apply je idempotentní podle
operation ID; lokální označení `applied` navazuje až na Workspace receipt.

Worker vyžaduje hlavní plán a validní executable task graph. Importovaný modul,
který uchovává pouze původní zdrojové artefakty, lze přes `list` zkontrolovat,
ale `scan` na něm záměrně skončí `Main plan is unavailable`.

## První živá evidence

Na importovaném HEAD `ede2a869c09f9fc2bf66f75eebfb07799b1fd7c1` bylo nalezeno
82 samostatných podkladů. První příliš velký kontext skončil po 180 sekundách
jako `unknown` a nebyl opakován. Revize v2 odstranila z kontextu celý hlavní
plán; jeden široký backlog správně skončil `keep-detached`.

Revize v3 předává target ID jako explicitní pole a pokračuje po chybné
odpovědi. Malá dávka vytvořila jeden `dismissed`, jeden `pending` a jeden
`failed` návrh. Pending přiřazení pod `COMP-01-A` je obsahově chybné a má
být lidsky zamítnuto; nebylo aplikováno. Failed odpověď naopak rozpoznala
`IMP-03`, které je zachováno v podpůrném textu, ale není cílovým task-graph
uzlem. To dokládá potřebu pozdějšího samostatného typu proposal pro
promotion zachovaného požadavku; první řez jej nesmí automaticky vytvořit.
