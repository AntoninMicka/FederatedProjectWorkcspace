<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Frontend shell a hranice desktopových capability

Tento dokument eviduje stav dávky `UX-UNIFIED-01`. Autoritativní projektová
data ani crash recovery se touto změnou nemění. Webový server a desktopový
WebEngine používají stejné `HTML` a `CSS` ze `spikes/desktop_ui.py`; varianty
smějí přidat pouze bootstrap autentizace a capability konkrétního uzlu.

## Společný frontend

- Katalog projektů, otevření projektu, sidebar, náhledy, chat, workflow,
  souhrny, extrakce, metadata, obrazové běhy, nastavení backendů, CMS a správa
  uzlu mají jediný DOM/CSS zdroj.
- Serverový bootstrap v `spikes/web_server.py` přidává přihlášení přístupovým
  klíčem, session/RBAC a serverové create/import capability.
- Desktopový bootstrap v `spikes/desktop_management.py` spoléhá na procesní
  token přidávaný WebEngine interceptorem a zpřístupní capability důvěryhodného
  single-user uzlu.
- Chybějící capability je skrytá deklarativním selektorem nebo atributem
  `hidden`; společný JavaScript nesmí selhat kvůli odstraněnému DOM prvku.

## Qt/PySide hranice

Qt zůstává oprávněný tam, kde je nutná integrace s lokálním OS nebo lifecyclem:

- výběr a oprava cesty lokálního projektu přes systémový file dialog,
- správa lokálního síťového procesu a test jeho endpointu,
- nasazení LXC uzlu a sledování lokálního workeru,
- přenos projektu využívající lokální credentials/proces,
- systémový askpass a otevření schváleného odkazu v systémovém prohlížeči,
- lifecycle okna, WebEngine procesu, signálů a bezpečného ukončení workerů.

Následující existující Qt dialogy nejsou desktop-only z principu a nesmějí být
dále rozšiřovány jako paralelní UI: vytvoření projektu, import NotebookLM,
import zdroje, editor dokumentu/TODO a historie artefaktu. Jejich backendové
služby zůstávají znovupoužitelné. V této dávce byl sjednocen shell a serverové
varianty create/import; úplné převedení těchto starších desktopových vstupů na
společné autorizované HTTP workflow vyžaduje samostatné mutující API a recovery
kontrakt a není vydáváno za dokončené.

## Ověřovací kontrakt

- `WEB_HTML == HTML` a `WEB_CSS == CSS`.
- Desktop management servíruje stejný `HTML` a `CSS` bez `.replace(...)`.
- Webový JavaScript obsahuje explicitní serverový bootstrap a poté celý
  společný aplikační JavaScript.
- Desktopový bootstrap pouze odemyká deklarované lokální capability.
- Reálný Qt/WebEngine smoke a živé nasazení na Turris zůstávají samostatnou
  platformní akceptací.
