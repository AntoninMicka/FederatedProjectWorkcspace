<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Vstupy, čekající verze a návaznosti monitoringu

Detail návrhu i vydané zprávy zobrazuje použité pooly, zdroje dostupných
položek, přesné obsahové revize a identifikátory položek. Ukazuje připnutou
definici zpracování, vstupní Git revizi a uložené hashe webových hledání.
Nová vydání zachovávají také source ID a reference použitých filtrů;
starší nebo sdílený návrh bez těchto údajů je nesmí zpětně odhadnout.
Navazující zpracování používá
[vydané zprávy přes stabilní ID zdrojové úlohy](monitoring-report-chains.md).

Dostupnost znamená, že je daná verze dosud v místní retenční kolekci.
Po retenci zůstane přesná reference, ale přehled neobnovuje titulky ani texty
ze soukromých pracovních kopií. Metadata vydané zprávy se při čtení nemění.
Pokud je dostupná dodatečná obsahová verze stejné položky v témže
poolu, zobrazí se možné zastarání podle časů prvního výběru verzí. Kontrola
pokrývá i opravu načtenou jiným uzlem před sestavením a přenesenou později. Další pozorování téhož obsahu samo o sobě
varování nezpůsobí. Jde o porovnání s místně dostupnými daty; výpadek uzlu,
retence nebo dosud neuskutečněný přenos brání úplnému ověření. Varování
nepřepisuje zprávu a nespouští model. Aktualizaci zajišťuje ruční zpracování.

Pool rozlišuje použité a čekající **obsahové verze**. Čekání se počítá vůči
každému aktuálně připojenému zpracování zvlášť: položka může být zahrnutá
v jednom návrhu a stále čekat na jiného spotřebitele. Verze mimo aktuální
časové okno spotřebitele se nevydává za čekající; detail ukazuje tento důvod. Počty zahrnují všechny
dosud uložené úspěšné místní i sdílené běhy a provenance vydaných zpráv,
nikoli jen posledních 100 běhů hlavního přehledu. Failed/unknown není důkaz
použití. Bez připojeného zpracování se ukáže tento důvod místo falešného
nulového čekání. Při ztrátě veškeré evidence o nevydaném návrhu se jeho
položky opět jeví jako čekající; neexistuje druhý trvalý processing ledger.

U přijaté položky jsou důvody výběru a přesná revize filtru. Běžný RSS sběr
navíc uchovává souhrnné počty podle filtru, výsledku a důvodu pravidla,
včetně vyřazení. Souhrn neobsahuje odmítnuté titulky, URL ani texty. Je vidět
v detailu zdroje a historii sběrů. U starších běhů se chybějící důvody
nedopočítávají z dnešní konfigurace. Kontrola HTTP 304 nedává nové rozhodnutí
filtru, původní souhrn lze najít v historii.

Tabulky ukazují poslední/příští sběr, nejbližší zpracování a poslední vydání.
Termín zpracování respektuje kalendář, časovou zónu, DST a aktuální zmeškaný
slot bez vyrábění backlogu. U vzdáleného uzlu jde o plán podle sdílené
konfigurace a známých výsledků, nikoli potvrzení jeho dosažitelnosti.
Vydání nemá automatický termín: vyžaduje skončenou ochranu a ruční posouzení.
Agregát obsahuje rozbalovací tabulku toku zdroj → filtr → pool → zpracování,
včetně producentů sdíleného poolu mimo explicitní členství sestavy.
Náhled upozorní na cyklus; nezavádí editor obecného grafu.

## Vlastnictví a obnova

Reuse/adapt: původní Reporting snapshoty a audit vydání, místní pooly,
sdílené výsledky, kalendář `processing_slot` a existující čtecí API.
`monitoring_evidence.py` je čtecí projekce bez nové persistentní vrstvy.
Otevření přehledu nevykonává cleanup, model, HTTP sběr ani Git commit.
Reference doplněné do nového vydání ukládá původní journal/receipt writer;
crash boundaries vydání podle ADR 0082 se nemění. Souhrn pravidel je ve
stejné FULL transakci jako pool a dokončení sběru: před commitem se vrátí
obojí, po commitu lze použít uložený výsledek. Neexistuje nový cross-store
zápis ani synchronizace provozního journalu.
