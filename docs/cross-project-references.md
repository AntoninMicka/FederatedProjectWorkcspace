<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Připnuté meziprojektové reference — XREF-01

První řez poskytuje CLI a Python službu mezi lokálně registrovanými projekty.
Reference zobrazuje konkrétní revizi zdrojového artefaktu read-only. Novější
obsah nabídne, ale nepřevezme bez potvrzeného repinu. Nový GUI formulář tento
řez nepřidává; generický prohlížeč dokumentů může zobrazit JSON deskriptor.

## Vyzkoušení bez zásahu do existujících projektů

Z kořene checkoutu spusť ukázku s novým, dosud neexistujícím adresářem:

```sh
python3 -m scripts.reference_demo /tmp/fpw-reference-demo
```

Vzniknou dva syntetické projekty a samostatný node config. Ukázka vytvoří
referenci, změní zdroj a vypíše `state: newer-available` spolu s původním
`pinned_text: První připnutá revize.`. Nic neposílá modelu ani do Workspace.

Prohlédni soubory:

- `01-pinned-view.json`: původní připnuté zobrazení.
- `02-newer-offered.json`: stejný obsah, nabídka nové revize v `newer`.
- `context-manifest.json` a `context-payload.json`: manifest a skutečné bajty
  původní revize po ověřené přípravě i kontrole dispatch.
- `update-preview.json`: přesný návrh repinu k review.
- `demo.json`: vygenerované identifikátory a `explicit_update_command`.

Po posouzení návrhu spusť vypsaný `explicit_update_command`. Následný příkaz
`view` s node, target project ID a reference ID z `demo.json` zobrazí druhou
revizi. Nejde o test normálního profilu ani lidskou akceptaci úkolu.

## CLI nad registrovanými projekty

```sh
python3 -m spikes.cross_references --node NODE pin SOURCE_PROJECT ARTIFACT > pin.json
python3 -m spikes.cross_references --node NODE preview TARGET_PROJECT NEW_REFERENCE_ID pin.json 'Název odkazu' > preview.json
python3 -m spikes.cross_references --node NODE write preview.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
python3 -m spikes.cross_references --node NODE view TARGET_PROJECT REFERENCE_ID
python3 -m spikes.cross_references --node NODE index TARGET_PROJECT
```

Identifikátory jsou UUID. Preview odpověď má `value` a `sha256`; writer vyžaduje
právě tento digest a explicitní `--confirm`. HEAD zdroje/cíle zjistí služba.
Přerušenou odpověď opakuj se stejným operation ID a stejným preview.
CLI běží jako lokální vlastník uzlu a předpokládá jeho důvěryhodné OS oprávnění.
ChatService místo toho používá identitu přihlášeného uživatele a delegovaný
rozsah requestu; obecná oprávnění účtu tento rozsah nerozšíří.

Pro repin ulož `newer` z online view jako pin JSON, vytvoř preview se stejným
reference ID a `--update` a potvrď nový digest. Soubor pin může být přímo
objekt nebo ověřená CLI obálka `value`/`sha256`. Změna jiného artefaktu ve
zdrojovém projektu sama nabídku aktualizace nevytvoří.

Explicitní kopie má samostatný krok:

```sh
python3 -m spikes.cross_references --node NODE fork-preview TARGET_PROJECT REFERENCE_ID NEW_ARTIFACT_ID > fork.json
python3 -m spikes.cross_references --node NODE fork fork.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
```

Fork má nové ID a neměnnou provenance připnutého zdroje. Markdown dokument
lze lokálně upravovat; ostatní obsah je raw Source. Původní reference zůstává
připnutá a fork se sám neaktualizuje.

## Autorizace, offline stav a Context Manifest

Zobrazení vyžaduje živé oprávnění k oběma projektům. Efektivní privacy je
nejsilnější z místní reference, připnuté revize a aktuálního zdroje. Odvolaný
přístup, známé smazání, neplatný pin nebo pending source operace odmítnou
čtení i při existující cache. `--online-only` zakáže offline fallback.

Při nedostupném registrovaném source repozitáři může `view` použít soukromou
cache, pokud místní oprávnění stále platí. Výsledek je `offline-stale`,
`stale: true`, `privacy_unverified: true`; aktuální source privacy tehdy
nelze potvrdit. Tento obsah se nesmí použít pro Context Manifest, fork ani
externí boundary. Cache se ukládá mimo projektový Git a jeho autoritativní
state; ztráta cache nepoškodí referenci.

Index obsahuje pouze místní deskriptor. `index` živě doplní autorizovanou
dostupnost; nepovolený zdroj vrátí jen jako unavailable. ContextBuilder při
explicitním ProjectInput vyřeší referenci na přesné zdrojové bajty a manifest
obsahuje pin, zdrojový HEAD, revizi oprávnění, hash deskriptoru a privacy.
Před dispatch vše ověří znovu. Změna source HEAD i bez změny připnutých bajtů
vyžaduje novou přípravu. Editace/projekce přes referenci a reference na další
referenci jsou odmítnuty; pro editaci je určen explicitní fork.

Recovery, verzovaný formát a omezení revokace již získaných kopií popisuje
[ADR 0070](adr/0070-local-artifact-references.md). Rozpracovaný target intent
obnovuje původní Workspace journal bez opakovaného čtení zdroje.

## Důkazy a plánovací podklad

Rozsah odpovídá exportu projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
queue revision 202, project HEAD `03f4f27c6d399f2774b6c9c0b24ec827a1c44f1a`,
snapshot revision `e1d346bf43041e8fc9ac40edb72adb17f9d5a9d35df1bc8333df12c0b91847be`,
packet `e252ecbf19a8d590c1a9d69f603a7a1312beb230891e23e657a5eb26612c7861`.
Při zahájení byl export current/synchronized a source baseline
`1f4171bcdffeae43931aa1feb2dd3ebc3ccea09d` odpovídal develop po merge MON-02.
Toto je návrh výsledku k review; autoritativní akceptace ve Workspace zůstává
samostatným lidským krokem. Vzdálené reference patří M5.

Při závěrečné kontrole bridge hlásil `stale: true` a odmítnutí synchronizace
HTTP 422 (`failed_at: 2026-11-04T21:49:58.062Z`). Uvedený export tedy dokládá
zadání při zahájení; aktuální plánovací stav a doručení výsledku nejsou
potvrzené. Tato změna plánovací stav nepřepisuje.

Ověřeno: 21 testů `tests.test_cross_references` (včetně CLI, delegovaného
scope, revokace, privacy, cache, Context Manifestu, forku, rebuild indexu a
procesových pádů), 105 existujících chatových testů a skutečný běh syntetické
ukázky včetně následného potvrzeného CLI repinu a explicitního forku.
Závěrečná celá sada `python3 -m unittest discover -s tests -v`:
**1 546 testů za 512,606 s, OK, 44 skipped**. Běžela s povolenými lokálními
sockety pro existující integrační HTTP testy. `git diff --check`, whitespace
nových souborů a relativní odkazy nových návodů prošly.
