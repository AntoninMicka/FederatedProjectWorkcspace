<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0071 — Reportingové návrhy a explicitní review

Datum: 2026-11-05. Stav: lokální implementace MON-03 k review.

## Kontext a rozhodnutí

Aktuální synchronizovaný export projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59`
řadí první zahajitelný MON-03. Při načtení: queue revision `212`,
projektový HEAD `a8a965decc8c3d06b31743dcf3edc2f65a0d9bcb`, exportní revize
`37edc9076391f217906055b7dc356bc981a95b6c11abd710b5216bdce6adaa95`, packet
`b85f2f522bde01517d28ab232fe88c60ce8aa74190bdd77ef24eb623dbf6d547`,
`current=true`, `blockers=[]`, `stale=false`. Mapping směřuje na tento
repozitář. Scope a akceptaci poskytuje exportovaný BACKLOG source artefakt
`3928de31-234c-5754-a6a6-b31f587d2a45`, SHA-256
`cce3acad67fe4ffaf5eca1eddc2ddea8e9adba8f84fff13afafb0933e75dc6d2`, řádek 348.
Jde o podklad připnutého zadání, nikoli aktivaci archivovaného plánu.
Vývojový základ `5eabc54` je ověřený `origin/develop` po PR #137;
samostatná větev `feature/mon-03-evidence-story-tracking`.

Nad [ručním writerem](0068-manual-reporting-transactions.md) přidáváme
lokální API ReportingProposals. Volitelné role extractor, researcher a
evidence-evaluator mají vlastní reportingové revize a dostávají pouze
explicitní Context Manifest. ReportingTask musí mít `execution.llm=optional`.
Zůstává plně funkční ruční větev bez LLM; není automatický fallback ani
implicitní předání konverzace jiné roli.

Rozhraní je určeno místnímu vlastníkovi. Volající aplikace dodává aktuální
Authority a nakonfigurovaný binding/adapter; množinu čitelných ID nesmí
odvozovat z modelového výstupu. ContextBuilder znovu kontroluje HEAD,
práva, target i local-only hranici před dispatch a před novým přijetím.
Tento řez nepřidává vzdálené API, UI, autonomní vyhledávání, scheduler ani
spouštěč JSON policy. Backendový protokol je stávající prepare/dispatch/runs;
PoC ověřuje konkrétní OllamaAdapter se syntetickým transportem, nikoli všechny
providery nebo reálnou kvalitu extrakce.

## Návrh, evidence a přijetí

- Model vrací uzavřený `fpw-reporting-proposal-v1`: records a limitations.
  Povoleny jsou Event, EvidenceAssessment a Story; žádná změna definic,
  zdrojů, cest, metadat, pravidel nebo vydání reportu.
- Reference musí patřit do explicitního kontextu. Vybrat lze jednu revizi
  artefaktu a musí existovat už v deklarovaném commitu; škála tasku se vybírá
  explicitně. Subject hodnocení musí odpovídat ID a hashi tvrzení explicitně
  vybrané Event revize stejného tasku. Původní připnuté bajty a
  append-only pravidla nadále kontroluje reportingový validátor.
- Event i EvidenceAssessment musí zohlednit všechny vybrané Source záznamy.
  Význam supports/contradicts/context posuzuje člověk; validátor význam textu
  neuhodne. Bez dostupného podporujícího primárního zdroje musí confidence
  zůstat null/insufficient. Při rozporu není dovoleno high a chybějící omezení.
  Číselná maturity zůstává návrhem podle připnuté škály, nikoli měřením modelu.
- Modelový Event nesmí tvrdit `verified-operation`. Ověřený provoz vyžaduje
  samostatnou lidskou práci s důkazy přes existující ruční cestu a pravidla
  vydání. Primární marketing ani community nejsou certifikací provozu.
- Generování a preview nemění projektový Git. Přijetí vyžaduje explicitní
  `confirm=True` a digest přesného auditovaného návrhu od úspěšného durable
  backendového běhu. Nelze předložit jiný model/prompt/odpověď pod původním
  potvrzením. Actor/time nových review dodává writer místního vlastníka.
- Přijetí uloží nové revize a neměnný audit v jediném Workspace commitu.
  Audit drží validovaný návrh, instrukci, omezenou projekci Context Manifestu,
  model/target a run/manifest/result digesty. Úplný manifest se session/node
  autoritou a raw odpověď zůstávají node-local. Audit není nový run journal.
- Provenance každé odvozeniny zahrnuje všechny vstupy, i vybraný zdroj, který
  model odmítl nebo který není ve výsledné story. Privacy výsledku nesmí být
  nižší než privacy celého kontextu. Audit respektuje navíc nejpřísnější
  explicitní privacy navržených výstupů. Bez reklasifikace se nic nesnižuje.

Přijetí je rozhodnutí o projektových datech. Akceptace implementační dávky
MON-03 ve Workspace, zdrojový commit a doručení PR jsou samostatné kroky.
Tento dokument autoritativní stav úkolu nemění.

Po založení větve z develop označil autosync původní packet jako stale:
baseline před squash mergem #137 není předkem nového vývojového základu.
Rozsah byl načten ze synchronizovaného exportu ještě před přechodem větve;
baseline se nepřepisuje. Pro další aktuální předání výsledku je potřeba
nová generace balíčku ve stejném mappingu. Uživatel toto předání obnovil:
packet `09a13c1817c2eb638913e014d6717f0c7dbce5c70a928731e53ee1b432822c82`,
queue revision `213`, baseline `5eabc5473bdb28c3ee1f979ce95c51a3d9568a89`,
sync `2026-11-05T18:39:43.577Z`, `stale=false`. Porovnání manifestů
ukázalo pouze změnu queue revision; projektová revize, rozsah i všech devět
podkladů zůstaly stejné a jejich hashe byly znovu ověřeny.

## Persistence a recovery

Používáme [ADR 0003](0003-coordinated-operation.md),
[ADR 0063](0063-reporting-contract-and-boundaries.md) a ADR 0068.
Rozdíl proti ručnímu zápisu je pouze předcházející backendový běh:

| Hranice | Autorita a obnova |
| --- | --- |
| Context prepare před backendovým intentem | Pouze read-only připravený kontext. Neexistuje schválená projektová revize. Volající uchovává PreparedContext soukromě; nelze jej rekonstruovat z projektového indexu. |
| Backend prepared / dispatching | Stávající BackendRuns váže run ID, model/role a manifest digest. Unknown/dispatching se nesmí automaticky znovu odeslat; projekt se nemění. |
| Succeeded, před review | Raw odpověď je v backendovém journalu. Preview ji parsuje a validuje; retry použije stejný výsledek. Nový model/prompt potřebuje nové připravené zadání a run ID. |
| Schválení, před Workspace intentem | Digest váže kanonický návrh, projekci kontextu a run/result digesty. Při změně HEAD/práv se nový zápis odmítne; není automatický rebase. |
| Workspace prepared / dílčí soubory / před CAS | Původní journal drží všechny bajty auditu a revizí. Recovery dokončí stejnou operaci; cizí změnu zachová dle ADR 0003. |
| Po CAS, před indexem/receiptem | Audit i revize již existují v jednom commitu. Recovery dokončí index/receipt. Retry se stejným operation ID nevytváří další commit. |
| Dokončeno / ztracená odpověď | Přijetí znovu ověří vlastníka, kontextová oprávnění a původní úspěšný výsledek a vrátí původní Workspace receipt. Jiný intent se stejným operation ID je konflikt. |
| Ztráta backendového journalu nebo soukromého PreparedContext | Git audit a přijaté revize zůstávají čitelné; nové dispatch/přijetí se zastaví do reconciliation. Nevydáváme hash za obnovitelný run ani nespouštíme náhradní model. |

Mezi backendovým journalem a projektovým writerem není distribuovaná
transakce. Nemění se scheduled ReportRun, cutoff ani externí doručení.
Process-crash testy nepředstírají odolnost vůči ztrátě disku nebo napájení.

## Reuse a ověření

Reuse/adapt ContextBuilder, Authority/Target, registry rolí, stávající
backendové runs/dispatch, reportingová schémata a původní Workspace writer.
Další writer, provider SDK, DB či automatický modelový soudce by stávající
hranice duplikovaly. Veřejný i dostupný soukromý katalog byly přečteny;
externí kód se nepřenášel.

Použití a akceptační scénáře: [reportingové návrhy](../reporting-proposals.md).
Technické důkazy tvoří deterministické scénáře přes skutečný backendový
journal a izolované Git projekty. Reálný model, běžný uživatelský profil a
lidská akceptace MON-03 se tím nepotvrzují.
