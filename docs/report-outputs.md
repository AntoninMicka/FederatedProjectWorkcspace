<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Výstupy jako konkrétní vydání zpráv

Levá lišta Výstupů používá společný strom Zprávy / Prezentace. Každá zpráva
je samostatná položka s menu **⋮** (zobrazit a export Markdown), stavem a krátkým
ID. Kliknutí otevře přímo její text vpravo. Neotevírá úlohu ani seznam jejích
běhů. Návrhy obsahují skutečný připravený text; rozpracované úlohy bez textu
nejsou vydávány za zprávy. Schválení návrhu zůstává samostatná výslovná akce.

Nový název obsahuje název zprávy, datum, čas na sekundy a pásmo, například
`Ranní zpráva · 2026-11-11 09:20:30 CET`. Použije se pásmo původní periody
nebo rozvrhu zpracování. Čas se zmrazí při dokončení sestavení, nikoli při
kliknutí na položku, pozdějším schválení nebo opakování publikace. Nové názvy
se uloží také do Git metadat konkrétního výstupu.

Staré Git revize se automaticky nepřejmenovávají. Pokud není dostupný přesný
čas sestavení, přehled výslovně označí čas vydání nebo chybějící čas návrhu.
Nezaměňuje začátek sledovaného období ani začátek běhu za dokončení sestavení.

## Autorita a načítání

Vydané ReportSnapshot a dokumenty z blokového zpracování se projektují z již
validovaného Git snapshotu. Nové blokové výstupy mají standardní metadata tag
`monitoring-output`; starší rozpozná zachovaná auditní patička s ověřenou
referencí na původní blok. Text zůstane dostupný také po smazání zadání.
K přenosu ani zobrazení vydané zprávy není potřeba kopie místního runtime běhu.
Jeho absence nesmí skrýt existující dokument v Gitu.

Seznam přenáší jen souhrny. Jednotlivý obsah se čte přes autentizované
`/v1/monitoring/output` pro konkrétní ID a očekávaný HEAD. Endpoint opakovaně
nečte celý projekt: použije autorizovaný snapshot původního dispatch. Změna
HEAD vyžaduje obnovu seznamu. UI zahodí opožděnou odpověď jiného projektu nebo
výběru. Zobrazuje text bezpečně, bez spuštění HTML či modelu.

Lokální schvalovací akce starších zpráv a blokových návrhů se znovu používají.
Vydaný dokument nevzniká pouhým kliknutím na položku. Pokud je dokument již
commitnutý, nezobrazí se podruhé jako návrh kvůli nedopsanému místnímu stavu.

## Publikace a recovery

Není zaveden nový writer, index ani journal. Scheduler uloží název/čas vedle
původního kandidáta ve své stávající transakci a předá je původnímu Reporting
writeru jako aplikační metadata. Markdown a jeho schválený hash se nemění.
Reporting zahrne metadata do zmraženého Workspace intentu. Blokové zpracování
používá původní result a `_doc` operaci s deterministickým ID.

Před Git commitem se používá původní journal recovery, po commitu se dokončí
index/receipt a místní stav. Opakování používá původní čas a název. Staré
kandidáty bez nových metadat zachovají původní publikační intent; restart jim
nesmí domyslet nový čas. Platí původní [ADR 0081](adr/0081-complete-project-data-sync.md)
a publikační schvalování; datový ani federační protokol se nemění. Nová metadata
používají existující title/description/tags, nikoli nový povinný typ záznamu.

Ověření zahrnuje zmrazení času před odloženým schválením, idempotentní publikaci,
původní scheduler/recovery a syntézu, čtenářská oprávnění, stale HEAD, čtení
jediného snapshotu, zachování výstupu po smazání zadání a podepsaný přenos na
uzel bez příslušného runtime běhu. Qt scénáře ověřují přímé otevření vydání,
datovaný název, původní schválení a návaznou prezentaci. Plná sada ani vzdálené
nasazení nejsou těmito cílenými testy doložené.

Cílené ověření: 49 backendových/regresních testů, doplňující UI/native testy
(včetně označení zrušeného návrhu jako nevydaného) a 3 skutečné Qt scénáře;
celkem 59 různých testů, 1 volitelný skip. Všechny provedené testy prošly.
`node --check` i `git diff --check` prošly. Kód zůstává lokální bez nasazení.
