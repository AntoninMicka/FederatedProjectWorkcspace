# TODO — aktuální dávka M1

Aktuální milník: **M1 — Single-node project workspace**. Gate M0 je splněný v rozsahu architecture spike ([review a důkazy](WORK_LOG.md#gate-m0)); Gate M1 zůstává otevřený. Žádná aplikační část zatím není production-ready.

[Roadmapa a gates](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Další backlog](BACKLOG.md) · [Dokončená práce a ověření](WORK_LOG.md) · [Pravidla](AGENTS.md)

Dávka obsahuje zbývající práci milníku M1 a přijaté ad-hoc úkoly. Během práce se aktualizuje jen tato evidence; hotové položky i ověření zůstávají zde až do uzavření dávky. Pak se dávka přesune do WORK_LOG a další načte z BACKLOG. Již uzavřené výstupy M1-01 až M1-04 a doplňky sidebaru zůstávají v historickém logu; neopakují se.

## Rozsah a dokončení dávky

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.

Tento převzatý souhrn M1 je zastřešující úkol; M1-05 níže je jeho konkrétní první krok. Zahrnuje zbývající požadavky sekce M1 roadmapy, včetně typů artefaktů, metadat, obnovy indexu po přejmenování/smazání, recovery zápisů a zachování původních bajtů importu. Hotové části souhrnu doložené ve WORK_LOG se znovu neimplementují. Další kroky rozepisuj zde podle ověřeného stavu; relevantní existující V-* položky v BACKLOG používej jako návaznosti, jejich doplnění dočasně zachyť níže.

Podmínka uzavření: dokončené a ověřené zbývající požadavky M1 i přijaté ad-hoc úkoly a doložené review Gate M1 (použitelný workspace bez LLM v LXC i desktopu). Případné zúžení dávky musí výslovně zachovat otevřený gate a odloženou práci; samotné dokončení M1-05 nestačí.

## Na řadě

- [ ] [planned] **M1-05 — Metadata dokumentu v editoru (cílová úroveň: PoC validated).** Zobrazit současná metadata a doplnit editaci popisu/štítků přes existující operation ID/retry/receipt a validaci. Zachovat identitu, původ/provenance a vytvoření; změny privacy/provenance nepřidávat bez vymezeného kontraktu. Ověřit společný commit obsahu/metadat, historii a restart. Navazuje na stávající schopnost Metadata v M1; úkol zatím nebyl zahájen.

## Ad-hoc úkoly aktuální dávky

- [x] [completed] **WF-02 — Práce po dávkách (implemented, 2026-09-10).** Požadavek uživatele: celé milníky v TODO, navazující dávky v BACKLOG, průběžně měnit jen TODO a archivovat až po uzavření dávky; podporovat ad-hoc práci. Upraveny pokyny a pracovní dokumenty, souhrnný úkol M1 přesunut z BACKLOG do této dávky. Ověření: konzistence pravidel a odkazů, zachování původních otevřených položek a historických záznamů, `git diff --check`. Pouze dokumentační změna; aplikační testy znovu nespouštěny. Záznam zůstává zde do uzavření dávky M1.

## K předání do backlogu

Zatím bez nových položek. Sem patří ad-hoc práce mimo dávku a doplnění existujících backlogových úkolů s odkazem na jejich ID; nejde o podmínku dokončení této dávky.
