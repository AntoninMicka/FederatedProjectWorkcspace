<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Akceptace obrazové capability

Tento checklist ověřuje PoC `F-M3-MEDIA-01`. Není dokladem produkčního provozu
ani obecného multimodálního chatu. OpenAI Images a ComfyUI jsou samostatné
explicitní bindingy; test jednoho nenahrazuje test druhého.

## Automatizované ověření

```sh
python3 -m unittest tests.test_media_backend tests.test_media_service \
  tests.test_desktop tests.test_web_server -v
python3 -m unittest discover -s tests -v
git diff --check
```

Sada musí pokrýt přesný provider request, nepropustnost secretu, privacy a RBAC,
PNG signature/IHDR/CRC/rozměry, limit 16 MiB, limit inline preview 4 MiB,
malformed výsledek, timeout a durable `unknown`, zákaz opakování stejného runu,
vědomě nový approval/run, restart, neměnnou provenance a idempotentní recovery
publikace před i po aktualizaci Git reference.

## Skutečné UI

V grafické relaci spusťte:

```sh
python3 -m spikes.desktop --smoke
python3 -m spikes.desktop --node /cesta/node.json \
  --smoke --smoke-project UUID_REGISTROVANEHO_PROJEKTU
```

Druhý smoke musí vykreslit projekt a skutečným Qt/WebEngine ověřit také
oddělenou kartu Obrázek, prázdný request preview, prázdný result panel a
zakázaný dispatch před potvrzením. Nevolá provider a nemění projekt.

## Živý provider

Každý provider ověřujte samostatně na projektu určeném pro smoke test. Před
potvrzením zaznamenejte provider, binding/revision, model nebo workflow hash,
rozměr, privacy a očekávané náklady. Potom:

1. připravte preview a ověřte, že se provider ještě nevolal;
2. porovnejte zobrazený přesný request s nastavením a potvrďte jej;
3. ověřte PNG preview nebo u výsledku nad 4 MiB jeho hash a metadata;
4. před publikací ověřte, že HEAD projektu zůstal stejný;
5. publikujte, znovu otevřete artefakt a ověřte PNG, privacy, provider/run,
   binding revision, request/manifest/result hash a u ComfyUI workflow/prompt ID;
6. zopakujte publikaci se stejným operation ID a ověřte stejný commit bez
   dalšího providerového volání.

OpenAI smoke je nákladová externí akce a vyžaduje výslovné potvrzení. ComfyUI
smoke vyžaduje předem schválený endpoint a allowlisted workflow. Credential,
prompt ani výsledné bajty nekopírujte do TODO nebo logu. Timeout či ztracenou
odpověď ponechte `unknown`; neopakujte stejný run a případný nový pokus založte
vědomě s novým approval/run ID.

Do akceptační evidence zapište přesné příkazy, datum, provider/binding revision,
výsledek a hranice důkazu. Neprovedený provider nebo ruční Cloudflare deploy
musí zůstat výslovně otevřený; lokální testy jej nenahrazují.
