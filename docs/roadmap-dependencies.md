<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Zaměřený scan závislostí

Kontrakt a recovery: [ADR 0061](adr/0061-focused-roadmap-dependency-review.md).
Aktuální zadání drží kanonický Workspace; tento dokument je návod a evidence.

## Scan a review

Použijte ID projektu z aktuálního exportu. Následující příklady používají
shell proměnnou `PROJECT`, nejde o pevně určený projekt pro všechny instalace.

```sh
python3 -m scripts.roadmap_refinement --project "$PROJECT" scan \
  --dependencies-only --focus-task DEV-02 --limit 1
python3 -m scripts.roadmap_refinement --project "$PROJECT" list
```

`--focus-task` lze opakovat; bez něj se pokračuje v celé dependency queue.
Položky jsou připnuté k jednomu HEAD. `--limit` omezuje dispatch, nikoli
počet uložených kandidátů. Report ukazuje total, remaining, states, stale,
complete a review_complete. Complete znamená úplný nezastaralý průchod
analýzou bez queued/running/failed/unknown/needs-context; neznamená přijetí
pending návrhů. Review_complete navíc vyžaduje, aby nezůstaly pending.
Nový režim nelze kombinovat s deep-check nebo forget-previous.

V desktopovém Workspace otevřete **Kontrola roadmapy**. Detail ukazuje
focus, připnuté zdroje a návrhy včetně citací. Schválit/Zamítnout je review;
**Provést vybraný** nejdříve ukáže diff a vyžádá potvrzení. Obecný webový
review přehled používá stejnou queue. Scan samotný se spouští CLI nebo TUI,
nikoli dlouhým blokujícím HTTP požadavkem.
Backend i UI musí používat revizi obsahující tento režim; po aktualizaci
restartujte backend a obnovte okno aplikace. Instalovaný starší backend se
samotným spuštěním CLI neaktualizuje.

```sh
python3 -m scripts.roadmap_refinement --project "$PROJECT" tui \
  --dependencies-only --limit 1
```

V TUI `s` spustí omezený scan, `a`/`r` schválí/zamítne pending návrh,
`p` připraví diff a `y` jej výslovně potvrdí. Obnova rozpracované operace
používá uložené operation ID, ne novou transakci.

CLI review a apply:

```sh
python3 -m scripts.roadmap_refinement --project "$PROJECT" decide \
  --proposal "$PROPOSAL" --accept
python3 -m scripts.roadmap_refinement --project "$PROJECT" preview
python3 -m scripts.roadmap_refinement --project "$PROJECT" apply \
  --operation-id "$OPERATION" --expected-preview-sha256 "$PREVIEW_SHA256"
```

CLI preview/apply skládá schválené návrhy projektu. Pokud jsou mezi nimi
staré/stale návrhy, musí být nejprve vyřešené; pro výběr jednotlivých návrhů
lze použít webové review. `no-change` zůstává k review a po přijetí nevytvoří
projektový commit. `needs-context` nelze přijmout jako hranu; nejprve je nutné
doplnit skutečný podklad a získat nový připnutý vstup.

## Přerušený zápis

Zopakujte apply se stejným OPERATION a PREVIEW_SHA256. Připravený intent
také zpřístupní **Obnovit připravený zápis** ve Workspace. Nesnažte se jej
obejít novým operation ID. Když ještě nevznikla nativní operace, lze zrušit
záměr a vrátit se k review:

```sh
python3 -m scripts.roadmap_refinement --project "$PROJECT" cancel-apply \
  --operation-id "$OPERATION"
```

Po začátku nativní operace se příkaz odmítne; nejprve je nutné dokončit
recovery. Lokální proposal/intent databázi nemažte kvůli znovuspuštění scanu.
Unknown není potvrzení selhání externího volání a nesmí se automaticky opakovat.

## Evidence tohoto řezu

Připnutý podklad: projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
HEAD `436485666354dcc73032dcfd9a0a6977ba9bf015`, exportní revize
`fc4ad5bc61b93cc30babb4e3dfa900d9f3c9a0823ac3b924a3b7e75468011714`.
Při zahájení byl IDE transport stale; aktuální snapshot byl získán přímo
nativním exportérem a porovnán s živým HEAD. Nejde o tvrzení, že IDE sync byl
opraven. Zdrojový základ je merge PR #117 (`8bca9a5`).

Cílené testy pokrývají focus/ID, přesné citace, duplicate/self-edge,
needs-context/no-change, kombinovaný cyklus, stale HEAD, záměnu evidence,
izolaci projektů, zachování staré queue, unknown bez retry a nativní recovery.
Změna HEAD během přípravy Context Manifestu se ověřuje před dispatch;
samotná předběžná kontrola před přípravou nestačí. Doplňkové testy ověřují
také frontmatter, zachování CRLF a zápis do původního linked podseznamu.
Navíc skutečné HTTP review s autentizací, TUI náhled/potvrzení a provedení
produkční JS obsluhy obnovy. Explicitní cílené selektory prošly včetně
kolize operation ID a změny HEAD během přípravy kontextu.

Celá závěrečná brána po poslední relevantní změně:
`python3 -m unittest discover -s tests -v` — **1 139 testů OK, 40 podmíněných
skipů**, 275,150 s. Běh měl povolené lokální sockety. Emitovaný JS prošel
`node --check`; syntaxe Pythonu, místní odkazy a finální `git diff --check`
jsou v pořádku. Neproběhla ruční akceptace v běžném profilu ani nasazení.

Živé same-node ověření použilo nakonfigurovaný `qwen3-coder:latest` na dvou
focus IDs, bez přijímání návrhů. První odpověď navrhla již existující hranu:
stav failed, nikoli zapsaná změna. Druhá prošla mechanickými kontrolami a
zůstala pending; její citace však sama neprokazuje nezbytnost závislosti,
takže nejde o sémantickou akceptaci. Aktuální scope má 166 otevřených položek:
164 queued, 1 failed, 1 pending. `complete=false`, `review_complete=false`.
Roadmapový HEAD se při těchto bězích neměnil. Celý scan nebyl proveden;
nové hrany nebyly lidsky schválené ani aplikované.
