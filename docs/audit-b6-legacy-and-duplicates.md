<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Mrtvé legacy větve a duplicity desktop/web (AUDIT-B6-T1)

Stav: **implemented**, čeká na review. Úkol AUDIT-B6-T1 řeší nálezy B-ODD-07
a B-ODD-09 z [auditu B1](audit-b1-locks-versions-oddities.md#nálezy-b-odd).
Zdrojová větev je `feature/audit-b4-error-states`, protože uživatel
20. 11. 2026 výslovně povolil řešit dávky B4 až B7 v jedné větvi a jednom PR.
Rozhodnutí o metrikách, katalogu modelů a hláškách učinil uživatel téhož dne.

## B-ODD-07: skryté bloky UI

Audit uvedl dva skryté bloky s funkčními prvky a dosažitelnost nechal otevřenou.
Rozbor podle stromu DOM ukázal, že většina obsahu mrtvá není.

### `legacy-home-diagnostics`

| Obsah | Zjištění | Výsledek |
|---|---|---|
| Ověření spojení (`#increment`, `#count`, `/v1/counter`) | Živý háček: `desktop --smoke` na tlačítko programově klikne a čte čítač. Route používá také řada testů souběhu. | ponecháno, blok přejmenován na `smoke-diagnostics` a okomentován |
| Gamepad demo (`#gamepad-scan`, `/v1/gamepad/status`) | Bez viditelného ani programového spouštěče. Route neměla jiného klienta. | odstraněno UI, JS, CSS, route i `scan_gamepads()` |
| Mini přehrávač prezentace (`#presentation-mode` a další) | Bez spouštěče. Plnohodnotný presenter má vlastní ovládání. | odstraněno UI, JS a CSS; `/v1/presentation/status` dál používá presenter |

Nastavení gamepadu v presenteru (`/v1/gamepad/settings`) zůstává beze změny.

### `backend-settings-legacy`

Blok není legacy. Je to skryté výchozí místo formulářů, které dialog
„Nastavit“ v katalogu backendů dočasně přesouvá k sobě a po zavření vrací.
Dialog ale přesouval jen vyjmenovaná ID, takže se nikdy nezobrazilo:

- vysvětlující texty a nadpisy u jednotlivých backendů;
- návod k prvnímu přihlášení Google OAuth, včetně callback URL;
- formulář administrátorského klíče OpenAI pro metriky spotřeby
  (`#backend-metrics`). Indikátor spotřeby se zobrazoval, ale klíč nešel
  zadat. Jde o regresi z PR #96.

Oprava:

- Obsah každého backendu je v jednom kontejneru
  `.backend-settings-group[data-backend-settings="<backend_id>"]`. Dialog
  přesune všechny kontejnery daného backendu, ne seznam ID. OpenAI má dva:
  textový backend a Images s metrikami.
- Blok je přejmenován na `backend-settings-forms` a okomentován.
- Nápověda k AtlasCloud byla omylem až za formulářem Grok; je přesunutá
  k AtlasCloud.
- Tlačítko „Nastavit Google Drive“ v importu zdrojů otevíralo Nastavení
  a zaměřovalo pole ve skrytém bloku, takže formulář nebyl vidět. Nově otevře
  dialog Google Drive.

Katalog modelů (`model-catalog-*`) leží uvnitř `external-backend-form` a byl
dosažitelný i předtím, v dialogu OpenAI. Zůstává beze změny.

## B-ODD-09: zdvojený desktop/web dispatch

Audit napočítal 24 rout obsluhovaných v obou handlerech. Ve skutečnosti jde
o dvě skupiny; zbylé webové větve jen ověřují oprávnění a pak volají společný
desktopový dispatch, což je správné oddělení.

### Správa uzlu (`spikes/node_management_routes.py`)

`DesktopManagementHandler` a `WebHandler` měly každý vlastní kopii těchto rout:

- `/v1/federation/catalog/reconcile`;
- `/v1/federation/content/{reconcile,cancel,start-all,settings}`;
- `/v1/replications/{status,sync}`;
- `/v1/backend-metrics/{status,configure,refresh}`;
- obohacení odpovědi `/v1/administration` o stav replikací, katalogu
  a synchronizace obsahu.

Kopie se lišily jen názvem nasazení, aktérem a webovou kontrolou
administrátora. Teď je jedna implementace v mixinu `NodeManagementRoutes`
a funkci `administration_view`. Nasazení a cestu k uzlu bere ze
`server.administration`. Web před voláním ověří, že účet je administrátor
uzlu. Desktop jedná jako lokální administrátor uzlu.

`/v1/federation/enroll` záměrně sdílený není. Desktop se k serveru přihlašuje
jako klient, web přihlášení klienta přijímá; mají jen stejnou cestu.
`/v1/administration` si dál drží vlastní předběžné kontroly a hlášky.

### Média a workflow

Web znovu implementoval `/v1/media/{status,preview,confirm,publish}`
a šest rout `/v1/workflows/*`, jen aby předal vlastníka běhu a
`allow_local_only=False`. Teď to dělá jeden desktopový dispatch podle dvou
háčků handleru:

| Háček | Desktop | Web |
|---|---|---|
| `request_owner_id()` | `None` (lokální uzel) | ID přihlášeného účtu |
| `allow_local_only` | `True` | `False` |

Web si ponechal pouze kontroly oprávnění (zápis do projektu, administrátor
pro konfiguraci médií).

Změny chování, které sjednocení přineslo:

- Workflow cizího projektu vrací na desktopu 403 místo 400, stejně jako web.
- Desktop dřív hlásil u chyb médií a workflow obecné „Chat požadavek nelze
  provést“. Chybnou odpověď workflow backendu navíc hlásil jako „Obrazový
  backend nevrátil PNG“. Nově vrací konkrétní hlášky, které dřív měl jen web.
- Web vrací u nejasného výsledku (`BackendUnknown`) podrobnější desktopové
  hlášky.

## Uložená data a migrace

Žádný formát uložených dat se nemění. Uložený administrátorský klíč OpenAI,
nastavení gamepadu, znalostní vrstva katalogu modelů i journal workflow
a médií se čtou stejně jako dřív. Odstraněná route `/v1/gamepad/status`
nic neukládala. Migrace proto není potřeba.

## Ověření

- `tests/test_shared_dispatch.py`:
  - desktop i web volají jednu implementaci workflow a médií se svým
    vlastníkem a `allow_local_only`;
  - cizí projekt vrací 403 na obou stranách;
  - webová kontrola zápisu se provede před dispatchem;
  - hlášky chyb workflow a médií na desktopu;
  - routy správy uzlu sdílí oba handlery, v jejich souborech nezůstala kopie
    a web vyžaduje administrátora.
- `tests/test_desktop.py`:
  - odstraněná dema a zachovaný háček smoke testu;
  - nový test ve skutečném WebEngine (`M0_DESKTOP_TEST=1`): dialog přesune
    celé skupiny OpenAI včetně metrik a nápovědy, návod Google OAuth je
    viditelný, skupiny se vrací zpět a tlačítko „Nastavit Google Drive“
    otevře dialog se zaměřeným polem.
- Cílené běhy všech 80 modulů, které dotčené handlery používají, prošly.
- Testy WebEngine: všechny kromě `test_real_webengine_audience_renders_approved_slide`.
  Ten v tomto offscreen prostředí končí timeoutem i na nezměněném `HEAD`.
  Offscreen WebEngine bez zobrazeného okna také nevyvolá událost `close`
  dialogu, proto ji nový test doručí explicitně.
- Celá sada se spustí před PR.
