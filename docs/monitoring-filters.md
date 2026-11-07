<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08-04 — filtry a vyhodnocovací postupy

Pravidla se ukládají přes dosavadní `MonitoringDefinitions.save` / admin
`/v1/monitoring/definition-save`. Nová definice je neměnná revize, nikoli
přepsání výsledků. Příklad `definition.selection`:

```json
{
  "revision": "selection-2",
  "instructions": "Vybrat zmínky o energetice bez reklamy.",
  "pipeline": {
    "schema": "fpw-monitoring-pipeline-v1",
    "revision": "energy-1",
    "steps": [
      {"id":"topic","kind":"keywords","fields":["title","content"],"all":[],"any":["energetika","elektřina"],"none":["inzerce"],"case_sensitive":false},
      {"id":"unique","kind":"dedup","field":"content_sha256"},
      {"id":"report","kind":"handoff"}
    ]
  }
}
```

Výslovně nakonfigurovaný RSS binding používá `mode="pipeline"`. Původní
`capture-only` a `queue-all` se nemění. Průchod levnými pravidly uloží pending,
vyřazení discarded, chyba regexu failed. LLM krok uloží captured s waiting
trace; sám nic neodesílá. Změna pravidel vyžaduje nový definition pin a nový
souhlas bindingu. Starší nálezy se hromadně nepřepočítají ani nezařadí znovu.

| Krok | Další přesná pole | Význam |
| --- | --- | --- |
| restrict | channels, languages, required_fields (seznamy) | Prázdný seznam neomezuje; chybějící požadovaná hodnota neprojde. |
| keywords | fields, all, any, none, case_sensitive | ALL i ANY i NONE platí současně; ANY prázdné neomezuje. Podřetězce, bez tokenizace/stemování. |
| regex | fields, pattern, flags, match, negate | search nebo fullmatch; IGNORECASE, MULTILINE, DOTALL, ASCII. |
| dedup | field | content_sha256, url nebo title; přesné porovnání, žádné mazání. |
| llm | role, instructions, target | classifier, extractor nebo evidence-evaluator; přesný Context Target. |
| assessment | žádná | Z explicitního LLM výsledku odliší relevance/significance/trustworthiness. |
| handoff | žádná | Závěrečný kandidát pro reporting, bez publikace. |

Každý krok má unikátní textové `id` a `kind`. Prohledávaná/požadovaná pole
jsou title, content, author, url, channel. ALL může být splněno napříč vybranými
poli; regex odpovídá alespoň jednomu poli. Jazyk není odhadovaný z textu;
normalizované RSS zatím jazyk nedodává, takže jazykové omezení v workeru
neprojde. Preview může přijmout explicitní mapu `languages={item_id:tag}`;
mapa je součástí náhledu a hashe vstupní evidence.

Regex má hard timeout pro celou dávku, nikoli pro každou položku. Neplatný
vzor se dá v náhledu diagnostikovat i uložit jako failed výsledek sběru.
Obsluha dalšího bindingu není na regulárním výrazu neomezeně blokovaná.
Limity a crash hranice popisuje [ADR 0077](adr/0077-monitoring-filter-pipelines.md).

## Náhled bez publikace

Autentizovaný reader může POST `/v1/monitoring/filter-preview`:
`{project_id,pipeline,items:[SourceItem,...]}` nebo
`{project_id,pipeline,finding_refs:[PinnedRef,...]}`; volitelně languages.
Maximálně 500 položek/4 MiB. Volba samples a refs je vzájemně výlučná.
Stávající uložené piny se ověřují stejnou source/HEAD/role hranicí.
API vrací pipeline, engine, hashe, rozhodnutí a jednotlivé kroky.
Žádný LLM, HTTP fetch, stavový přechod, Event ani zpráva se nespouští.
Preview samostatné ukázky nebere implicitně historii ostatních nálezů;
dedup workeru navíc používá tehdejší vybrané položky téhož sledování napříč
vstupy. Nezapočítává vyřazené ani dosud nevyhodnocené nálezy.

V sekci Sledování → Průběžný sběr RSS → Výběr položek je u položky důvod
a rozbalitelný průchod pravidly. „Náhled pravidel na ukázce“ dovoluje změnit
název/text a vyzkoušet přesnou uloženou pipeline. UI vykresluje text inertně.
Úplný editor nových WatchDefinition má vlastní navazující MON-08-09.

## Explicitní modelové pokračování

`MonitoringEvaluation(node, adapter)` používá již nakonfigurovaný backend;
nevytváří provider binding ani automatický modelový výběr. Python aplikační API:

1. `prepare(project_id, definition_ref, finding_ref, run_id, manifest_id, authority, binding)`
   jako pojmenované argumenty; vrací PreparedContext nad položkou, která
   skutečně došla levným trace k llm kroku. Připravit odmítnutou položku nelze.
2. `dispatch(prepared, authority=..., binding=...)` přes původní backend adapter.
   Stale HEAD, revokace, jiný Target nebo nesupersedované piny se znovu kontrolují.
   Pro externí hranici platí původní explicitní backend approval mechanismus.
3. `preview(prepared, authority=..., binding=...)` pouze čte úspěšný run a validuje
   JSON. Výstup obsahuje rozhodnutí, důvod, nullable relevance/significance 0..5,
   trustworthiness unverified/insufficient, claims a povinná limitations.
   Výrok o confirmed průlomu je chyba, nikoli automatická certifikace.
4. `accept(prepared, operation_id, approval_digest, authority=..., binding=..., confirm=True)`
   po review uloží SourceFinding nástupce a připnutý audit přes původní writer.
   Původní cheap-filter výsledek i historie zůstávají. Další zpracování přijímá
   pending kandidáta; handoff sám netvoří ani nevydává zprávu.

Backend výpadek, chybný JSON a unknown se nesmějí změnit na implicitní
deterministickou metodu nebo jiný model. Preview a accept již úspěšného runu
nepotřebují druhé volání. LLM běh ani lidské přijetí výběru nepředstavují
potvrzenou událost nebo ověřený provoz. UI po přijetí zobrazuje jednotlivé
rozměry a pravidla; audit má reference na roli, model, instrukce a výsledek.

Ověření: `python3 -m unittest tests.test_monitoring_filters -v` plus relevantní
RSS/model/Reporting a HTTPS/browser regrese. Testy používají syntetický model
a dočasné projekty; nedokládají živou uživatelskou subscription nebo ruční
akceptaci. Kompletní sada zůstává závěrečnou bránou celé MON-08.
