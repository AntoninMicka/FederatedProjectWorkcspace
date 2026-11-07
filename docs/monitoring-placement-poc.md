<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08-07 — plán fyzického PoC Omnia ↔ desktop

Stav: **interní journal implementován, vzdálený runtime a fyzický PoC neprovedeny**. Autority a recovery popisuje
[ADR 0080](adr/0080-monitoring-execution-placement.md). Dokument ani JSON
příklady neaktivují worker, grant, přiřazení nebo nový endpoint.

## Výchozí evidence a chybějící implementace

Source checkout obsahuje lokální RSS/filter runtime a explicitní modelovou
syntézu. `placement.mode!=local` zůstává odmítnuté. Existují peer mapping,
obousměrný Git sync, doménové journaly a lokální scheduler fencing, ale tyto
komponenty zatím netvoří jeden vzdálený monitoring execution protocol.

První implementační řez je `spikes/monitoring_execution_journal.py`:
interní koordinační evidence nad stejným ReportingScheduler FULL journalem,
s explicitní migrací v3 → v4. Logical effect key neobsahuje vykonavatele,
epoch ani definici; obsah intentu a přiřazení se ukládají odděleně a při
opakované rezervaci se kontroluje shoda obou. Změněná revize nesmí znovu rezervovat stejný
účinek. Jediný begin přechod se trvale uloží před případným dispatch;
opakovaný begin není nové povolení. Výsledek znamená pouze
`result-awaiting-import`, nikoli import nebo dokončení Workspace úkolu.
Unknown, begun a dosud neimportovaný výsledek blokují další slot streamu.
Explicitní převzetí je zatím možné pouze před begin, se zvýšením fence a
zachováním historie. Pro unknown není přidána administrátorská zkratka.

Tento modul není grant ani síťové API. Není zatím zapojen do RSS/model
dispatchu; neověřuje peer, schopnosti, projektové oprávnění nebo podpisy.
Tyto kontroly musí doplnit navazující autentizovaná execution vrstva před
voláním interního journalu. Neexistuje zde import receipt transition, takže
výsledek zůstává blokovaný do její implementace. Unit testy ověřují souběh,
rollback před commitem, restart po begin, původní výsledek po unknown,
fencing, migrace a odmítnutí ztracené autority. Nejsou fyzickým PoC.

Crash boundaries: rezervace a každý přechod jsou samostatné SQLite transakce
`synchronous=FULL`; pád před commitem se vrátí na předchozí stav. Pád po begin
commitu a před potvrzením zanechá `begun`, které neopravňuje druhý dispatch.
Pád po uložení výsledku dovolí znovu dohledat stejný descriptor. Migrace
nevytváří vedlejší DB; chybějící v4 tabulka nebo celý existující journal
vyžaduje recovery místo nové prázdné autority. Workspace/Git import zatím
není součástí těchto přechodů a jeho crash hranice se nemění.

Při návrhu byla read-only nalezena výchozí lokální node konfigurace a jeden
zapamatovaný deployment target. To není ověření živé identity/pinu, služby,
aktuálního peer mapování nebo možnosti vykonat MON-08-07. Místní adresy,
cesty k deployment konfiguraci a skutečné node UUID nejsou veřejný runbook.
SSH pokus během implementace skončil odmítnutím přihlášení veřejným klíčem.
Deployment, změna trustu ani spuštění uživatelského odběru neproběhly.

Před fyzickým PoC zbývá implementovat a lokálně ověřit:

1. Samostatný signed execution agreement a jeho CAS/migraci v Administration;
   změny nesmějí přidat execute k existujícím read/replicate grantům.
2. Bounded capability read model, autorizace explicitního assignmentu a
   pevného koordinátora nad implementovanou unikátní rezervací.
3. Claim/begin-effect/result/reconciliation kontrakt nad peer auth; worker
   staging oddělený od projektového writeru a stable backend effect ID.
4. Guardy lokálního i vzdáleného RSS/model dispatchu, aby dva synchronizované
   workspaces nevytvořily dvě základní rezervace téhož účinku.
   Před přechodem existujícího grantu doložit quiescence všech starých workerů
   a stav jejich efektů; samotná aktualizace kódu není fencing staré instance.
5. Read model s důvodem blokace a executor/assignment provenance; import
   výsledku stále přes původní Reporting/Workspace API a lidské review reportu.

Přenos/synchronizace výsledných artefaktů nesmí předstírat hotový MON-08-08.
Pro první PoC lze používat explicitně předem připravené validované fixture
vstupy; produkční disponibilitu ani automatický sync tím nelze potvrdit.

## Příprava izolovaného scénáře

- Read-only ověřit skutečný SSH target/container, známý host key, veřejnou
  identitu/pin a verzi obou backendů. Deployment preference není aktuální fakt.
- Použít dočasné testovací node identity, scoped test project UUID a fixture
  datový adresář mimo uživatelské projekty. Neklonovat živou node identity.
- Doložit přesné source revize/hash nasazeného PoC kódu na obou strojích.
  Probe nad starým backendem není ověření nové implementace.
- Testovací credentials zůstanou node-local; jejich hodnoty nejsou v reportu.
  Zachovat SSH/TLS ověřování, neřešit problém vypnutím trust kontrol.
- Nejprve použít syntetický feed a model transport pro opakovatelné fault
  injekce. Takové výsledky označit jako syntetické i na skutečném hardwaru.
- Pro skutečný veřejný RSS fetch a skutečný model použít zvlášť posouzený
  přesný zdroj/target a existující approval. Neodvozovat capture/licenci ani
  nový modelový souhlas z testovací fixture.
- Neaktivovat živé uživatelské watch_grants, neměnit provozní systémové služby
  a nevracet funkční release kvůli problému izolovaného PoC.

## Akceptační a fault matrix

| Scénář | Nutný pozorovaný výsledek |
| --- | --- |
| Stejná definice na dvou uzlech bez execution souhlasu | Žádný GET/model dispatch; oba ukazují konkrétní chybějící souhlas. |
| RSS + isolated regex přiřazeny Omnii | Efekt proběhne na Omnii jednou, s ověřeným grantem/revizí; desktop nepoluje paralelně. |
| Týdenní JSON model role přiřazena desktopu | Původní Context Manifest/binding a backend journal na desktopu; Omnia roli nepřebírá. |
| Desktop offline nebo capability offer stale | node-unavailable/capability-stale; žádný alternativní model ani executor. |
| Chybějící payload, přítomný pouze manifest/hash | waiting-inputs; žádné falešně complete období. |
| Připojení po návratu a duplicitní request/result | Stejný effect/run ID, jeden import/candidate; žádné dvojí vydání. |
| Ztracený claim/begin acknowledgement | Dohledání stejného ID/receipt; bez nové rezervace. |
| Pád po provider success, před result acknowledgement | Reuse původního výsledku; počet provider dispatchů zůstane jedna. |
| Pád po Workspace ref, před ack/indexem | Stejný native receipt, index odpovídá HEAD; žádný druhý commit. |
| Lease expiry / peer revokace po dispatch | unknown-effect blokuje původní stream; jiný node jej neobejde. |
| Explicitní takeover po prokázaném no-effect | Nový fence/assignment, stejné logical effect ID, historie starého pokusu zůstane. |
| Starý/pozměněný ticket, jiný peer/project/target | Odmítnutí před účinkem a před importem, bez credential fallbacku. |
| Local-only, nepovolený confidential scope nebo licence/retence | Odmítnutí přenosu/dispatchu, žádná implicitní reklasifikace. |
| Chybějící koordinační journal po restartu | Reconciliation required; žádná nová prázdná autorita. |
| Divergence projektového Gitu | Původní incoming refs/semantic review; žádný automatický merge nebo dvojí publish. |

## Co musí mít výsledný protokol o PoC

Dva skutečné stroje, ověřené identity/role, source hashe a přesné grant/assignment
revize; source/input/model piny a cutoff; měřené capability/resource výsledky;
časované fáze a počty skutečných síťových účinků; journal stavy před/po fault;
Workspace receipts/HEAD/index; samostatné kandidát/review/vydání a známé limity.
Doklad nesmí zaměnit unit test, ping, build nebo nabídku capability za provedení.

Gate designed je review ADR/kontraktů a konkrétního recovery plánu. Gate
PoC validated vyžaduje provedení a uchované důkazy výše; až potom lze navrhnout
akceptaci příslušné úrovně Workspace. Aktuální úkol zůstává otevřený.
