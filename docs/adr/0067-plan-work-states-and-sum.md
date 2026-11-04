<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0067 — Pracovní stavy plánu a odvozený stav skupiny SUM

- Datum: 2026-11-03
- Stav: přijatý návrh podle uživatelského zadání
- Rozsah: `NEW-B7B56C4A0B-TASK-1`, uživatelem rozšířeno na celý plán i frontu

## Rozhodnutí

Stav se ukládá přímo do vlastního Markdown bloku uzlu jako `- status: VALUE`.
Nevzniká další registr ani persistentní vrstva. Povolené hodnoty:

| Hodnota | Popisek |
| --- | --- |
| `planned` | Plánováno (New/Pending) |
| `in progress` | Probíhá |
| `resolved` | Vyřešeno, čeká na potvrzení splnění |
| `failed` | Selhalo |
| `completed` | Dokončeno (Done) |
| `deferred` | Odloženo |
| `sum` | SUM, odvodit stav ze všech obsažených položek |

Pro skupiny je podporován také přímý zápis značky SUM:

```markdown
- [SUM] [MILESTONE-DEV] DEV
  - type: milestone
```

Značka `[SUM]` je zkratka režimu agregace, nikoli potvrzený checkbox.
Stejný význam má `[ ]` s metadatem `status: sum`. Volitelná shodná deklarace
`status: sum` u značky SUM je přípustná; jiný ruční stav je konflikt.
Úprava názvu nebo ID ve strukturovaném editoru značku zachová. Při změně na
ruční stav výběrem v editoru se značka nahradí `[ ]` či `[x]` a zapíše se
příslušné `status`. Při lidském přijetí skupiny se `[SUM]` převede na `[x]`
a agregaci nadále uchovává `status: sum`. Stejné zkratky používají malé i
velké písmeno; na task nebo checklist se SUM použít nesmí.

Bez pole `status` zůstává původní význam checkboxu: `[x]` = Dokončeno,
`[ ]` = Plánováno. Historické popisy `Stav: …` zůstávají obyčejným textem.
Neznámé a opakované deklarace `status` jsou neplatný plán.

Checkbox zůstává autoritou potvrzeného dokončení a závislostí. `resolved`
ani `SUM · Dokončeno` samy nezaškrtnou skupinu ani nevytvoří lidskou akceptaci.
U ručně zadaného stavu znamená `[x]` vždy Dokončeno, také po pozdějším
přijetí zprávy z IDE. Ručně zapsané `status: completed` bez `[x]` je neplatné.
Volba Dokončeno v editoru připraví současně `[x]`; volba jiného ručního stavu
připraví `[ ]`. Výběr SUM checkbox nepřepisuje. Změna se projeví až po
explicitním uložení existujícím editorem.

`SUM` je povoleno pro milestone/batch (včetně prázdné skupiny) nebo obecný
uzel s potomky, nikoli pro task. Skupina agreguje všechny přímé potomky,
nejen viditelný filtr nebo položky ve frontě. Jejich skupiny se vyhodnotí
rekurzivně, včetně definic v odkazovaných souborech. Ručně nastavený stav
vnořené skupiny má přednost před jejími potomky; automatická agregace je
vždy explicitní volba SUM.

Pravidla v pořadí vyhodnocení:

1. Bez potomků → Plánováno.
2. Všichni Dokončeno → Dokončeno.
3. Alespoň jeden Selhalo → Selhalo.
4. Všichni Odloženo → Odloženo.
5. Pouze Plánováno a Odloženo → Plánováno.
6. Pouze Vyřešeno a Dokončeno → Vyřešeno.
7. Ostatní kombinace → Probíhá.

Projekce zpřístupní výsledný `status`, uložený `status_mode` a počty přímých
potomků podle výsledného stavu v `status_counts`. Kritická cesta, závislostní
blokace, připravenost, lokální Pozastaveno a zprávy agentů/lidské review
zůstávají samostatné příznaky. Mohou se zobrazit vedle pracovního stavu.
IDE dostává stejná pole přes snapshot a projekci připnuté fronty; starý
balíček bez těchto polí nadále používá původní příznaky. Stale stav zůstává
výslovně označený jako poslední známý. Hlášení agenta nemění pracovní stav.

## Zápis a recovery

Adaptujeme scoped editor z [ADR 0059](0059-file-plan-hierarchy-and-task-editor.md)
a transakci z [ADR 0003](0003-coordinated-operation.md). Výběr v UI mění jen
lokální draft vlastního bloku; zrušení nic nezapisuje. Uložení kontroluje
HEAD, digest fragmentu, oprávnění/privacy a validitu celého bundle. Ostatní
uložené `status_mode` musí zůstat beze změny; odvozené stavy předků se
přepočítají read-only projekcí.

Crash boundaries se nemění: `prepared` / `files-applied` před publikací
obnovuje journal; po `ref-updated` lze index obnovit z HEAD, následně
`indexed` / `completed`. Retry používá původní operation ID a shodné zadání.
Fronta a export mají vlastní lifecycle; mezi jejich refreshem a projektovým
commitem nepředstíráme atomicitu. Neaktuální export se nepoužívá jako
aktuální stav.

## Ověření

Deterministický test pokrývá všech 36 dvojic šesti ručních stavů, prázdnou
skupinu, ruční override, rekurzi a souborové definice. Scoped zápis ověřuje
nezměněné okolní bajty a replay po přerušení na všech pěti hranicích.
Qt smoke čte SUM, vybere jiný stav, uloží přes skutečné API a ověří stav
ve frontě. Izolovaný smoke nenahrazuje ruční akceptaci běžného profilu.

## Probíhá přes IDE bridge

Zpráva `kind: progress` může navrhovat pouze zahájení bez checklistu.
Přijetí používá stávající review/journal a vloží či upraví pouze vlastní
`status: in progress`. Případné explicitní změny checklistu zůstávají
samostatným obsahem stejné zprávy. Zahájení bez checklistu přijímá
Workspace automaticky (viz níže); ostatní doručení projekt nemění. SUM režim
skupiny se tím nenahrazuje; zahájení se hlásí u konkrétního podúkolu.

Fronta ověřuje zahajitelnost i přesnou připnutou revizi. Její řada nativních
receipts zahrnuje přijaté progress i completion commity, ale mezi potvrzené
úkoly počítá pouze completion. Více přijatých zpráv stejného tasku proto
nesmí způsobit falešné dokončení ani blokovat jeho pozdější completion.
Crash boundaries zůstávají stejné jako u existujícího review.

Ruční zahájení z fronty IDE (rozšíření 0.5.5) je stejná zpráva s
`reported_by: user`. Nepřidává writer, schéma ani crash boundary: zápis
do inboxu je atomický soubor bridge, doručení idempotentní receipt podle
UUID a změnu plánu provádí jen přijetí ve Workspace.

## Automatické přijetí zahájení (4. 11. 2026)

Na výslovný pokyn uživatele Workspace přijímá zahájení bez lidského
potvrzení. Pro hlášení zahájení tím mění dosavadní pravidlo z ADR 0062,
podle kterého změnu plánu provádí jen lidské review. Automaticky se přijímá
`kind: progress` bez checklistu, pokud je doručení aktuální (`received`).
Platí to pro agenta i uživatele, ve frontě i mimo ni. Receipt nese
`acceptance: automatic-start`. Jde o označení pravidla, ne výsledku;
výsledek dokládá záznam review. Dokončení, změny checklistu, dotazy
a zprávy dál vyžadují člověka.

Přijetí volá stejnou funkci review jako člověk. Používá oprávnění vlastníka
připojení a validace jsou stejné: zahajitelnost, SUM, nedokončený úkol,
přesná revize i HEAD. Volá se z `exchange` hned po trvalém uložení zprávy.
`operation_id` je UUIDv5 ze session a message ID, takže všechny pokusy
navazují na jediný záměr a jediný nativní commit. Ruční review stejné zprávy
pak skončí chybou `another decision`.

Hranice pádu a obnova:

1. Pád po uložení zprávy, ale před vznikem záměru: IDE nedostalo odpověď
   a pošle stejné UUID znovu. Větev `prior` pokus zopakuje.
2. Pád po vzniku záměru (`intent-prepared`), ale před nativní operací:
   další `exchange` dané session, včetně idle pollu, nejdřív dokončí
   rozpracované automatické záměry. Pokud se mezitím změnil HEAD, záměr
   skončí jako `stale` bez účinku.
3. Pád během nativní operace (`prepared` až `indexed`): projekt drží
   nedokončenou operaci, takže otevření projektu by selhalo. Proto se
   obnova spouští před otevřením projektu. Transakce se stejným
   `operation_id` dokončí právě jeden commit.
4. Pád po commitu, ale před zveřejněním výsledku (`before-outcome`), nebo
   po něm: obnova jen dopíše výsledek, druhý commit nevznikne.

Validační chyba (blokované zahájení nebo zastaralý snapshot) a dočasné
`PendingOperation` nezpůsobí chybu doručení. Zpráva zůstane doručená
a čeká na lidské review jako dosud. Bez nového doručení stejné zprávy se
nezaložený záměr znovu nezkouší, takže zahájení nemůže později proběhnout
samovolně. Obnova při pollu pokrývá jen aktuální session. Rozpracovaný
záměr staré session může dokončit vlastník připojení nebo administrátor
přes stávající pokračování review.

## Zahajitelnost závislých úkolů

Zahájit lze nedokončenou položku, jestliže všechny její přímé závislosti
mají pracovní stav Vyřešeno nebo Dokončeno a nejvýše jedna může mít stav
Probíhá. Bez závislostí je podmínka splněná. Dvě probíhající závislosti nebo
kterákoli Plánováno, Odloženo, Selhalo či neznámý stav zahájení blokují.
Používá se úplná projektová projekce včetně SUM, nikoli pouze viditelná fronta.

Jde o zahájení, nikoli potvrzení dokončení. Pole `ready`/`blocked` grafu a
`startable` IDE fronty vyjadřují tuto politiku. `completion_ready` grafu
vyjadřuje potvrzené checkboxy všech přímých závislostí. `eligible` fronty
pro dokončení navíc vyžaduje nedokončený, nepřidržený cíl a pro skupinu také
potvrzení všech jejích dětí. Přijetí `progress` podmínku opět ověří
nad aktuálním commitem, také mimo připnutou frontu. Příznak Pozastaveno,
neaktuálnost, read-only a ostatní oprávnění zůstávají samostatnými blokacemi.

Vyřešený předpoklad ani jediný probíhající předpoklad proto nemusí být
přítomen před položkou ve frontě. Přesuny a náhled odebrání používají stejnou
podmínku jako validace fronty. Ostatní dosud nevyřešené předpoklady lze
nadále plánovat dříve ve frontě jako Navazující; to neumožňuje okamžité zahájení.
Nevzniká nový writer ani crash boundary; stav je read-only výpočet a změny
fronty používají stávající revizi, náhled a atomický zápis.
