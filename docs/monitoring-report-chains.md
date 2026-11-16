<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Řetězení vydaných zpráv přes ID zpracování

Klíčem zdroje je stabilní ID **úlohy zpracování**, nikoliv název, agregovaná
komplexní úloha nebo ID jedné zprávy. Vydané zprávy zachovávají toto ID v
neměnné provenienci `block.id`; čtecí API jej vystavuje jako `processing_id`.
Přejmenování nebo změna přiřazeného uzlu proto stará vydání neodpojí.

V editoru zpracování vyberte **Vydané zprávy zdrojových úloh** podle názvu.
Definice ukládá volitelné `report_task_ids`. Pooly, webové hledání i vydané
zprávy lze kombinovat; alespoň jeden vstup je nutný. Zdroj může být sám
syntézou jiných vydaných zpráv. UI nevypisuje sebe ani potomky jako kandidáty;
backend nezávisle odmítne cykly, chybějící zdroj, duplicity a snížení privacy.
Původní definice bez nového pole zůstávají platné beze změny revize.

Při běhu se podle ID zdroje a pevného `period_end` vyberou **vydané** zprávy
za zadané okno. Návrh nebo chybový výsledek nenahrazuje vydání. Každý vstup
se uloží jako `report_inputs`: source task ID, run ID a přesný Git PinnedRef
(project, artifact, commit, path, SHA-256). Nezmrazuje se další kopie zdrojového
textu. Výsledek schválení zahrnuje tyto reference; idempotentní opakování
vrací původní uložený výsledek. Nevyvolává nový sběr ani hledání, pokud je
navazující zpracování samo výslovně nemá nakonfigurované.

Pro kalendářní zdroj se kontrolují splatné sloty v požadovaném okně podle
stejného kalendáře jako worker. Chybějící vydání způsobí popsanou chybu,
ikoliv zdánlivě kompletní syntézu. Pro ruční zdroj nelze odvodit očekávaný
počet vydání; požaduje se alespoň jedno vydání v okně. Výběr má limit 128
vstupních vydání. U kalendářního zdroje rozhoduje jeho slot podle připnuté původní definice,
u ručního zdroje původní `period_end`. Pozdní sestavení v témže slotu ani
datum opravy nebo přenosu neposunou zprávu do jiného vstupního období.

Nové vydání vytvořené ručním opětovným zpracováním drží `reprocess_of`.
Výběr používá koncové opravy, původní vydání zůstávají v historii. Dvě
souběžné opravy téhož vydání se neslučují podle hodin nebo UUID: vyžadují
lidské posouzení. Kontrola reference před modelem a při příjmu ze synchronizace
ověřuje skutečné historické bajty, tvůrčí úlohu, run ID, privacy a existenci
vydaného artefaktu. Kontextový manifest modelu obsahuje také původní
projektové artefakty; nejde pouze o odkazy ve volném textu promptu.

Hodinová ochrana porovnává také vstupní vydání. Změna commitu kvůli jiné
části projektu při stejném artefaktu a hashi nezpůsobí regenerování. Skutečná
oprava vede nejvýše k regenerování na konci ochrany podle původního kontraktu.
Po ochraně se výstup označí jako potenciálně zastaralý; automaticky se
nepřegeneruje ani nevydá. Označení se propaguje přes uložené reference, např.
oprava týdenního vydání označí měsíční syntézu i roční syntézu založenou na
původní měsíční zprávě. Vidí se v seznamu zpráv, detailu a přehledu zpracování.
Historická reference zůstává reprodukovatelná i po vydání opravy.

## Synchronizace a obnova

Reuse/adapt: Reporting/PinnedRef, audit vydání, ContextBuilder, stejný signed
pool sidecar a původní worker, journal a receipts podle ADR 0082. Návrh
navazuje na zmrazené vstupy staršího WatchSynthesis; jeho editor ani paralelní
workflow se nezavádějí. Reference vydaných zpráv se přenášejí jako součást
logického výsledku, nikoliv kopírováním worker databáze nebo modelového manifestu.

Crash boundaries zůstávají původní: výběr je read-only, před modelem se
uloží dispatch intent včetně přesných referencí; po nejasném externím efektu
zůstane unknown a nový placený pokus nevznikne automaticky. Výsledek a jeho
sdílená projekce se potvrzují jednou pool transakcí. Vydání používá původní
Git journal/receipt recovery; chyba před commitem obnovuje původní operaci,
po commitu se použije původní receipt. Pád mezi přenosem Git a sidecaru
obnovuje stávající signed exchange replay, příjemce odmítne nedostupné piny.

Nové definice a logické výsledky mají doplňková pole; před sdíleným používáním
je nutné aktualizovat všechny zúčastněné backendy. Starší validátor je má
odmítnout, nikoliv ignorovat jejich význam. Izolované podepsané dvouuzlové
scénáře a Qt/WebEngine testy nejsou fyzická akceptace Omnia–desktop.
