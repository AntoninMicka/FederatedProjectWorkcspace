# TODO — aktuální dávka M1

Aktuální milník: **M1 — Single-node project workspace**. Gate M0 je splněný v rozsahu architecture spike ([review a důkazy](WORK_LOG.md#gate-m0)); Gate M1 zůstává otevřený. Žádná aplikační část zatím není production-ready.

[Roadmapa a gates](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Další backlog](BACKLOG.md) · [Dokončená práce a ověření](WORK_LOG.md) · [Pravidla](AGENTS.md)

Dávka obsahuje zbývající práci milníku M1 a přijaté ad-hoc úkoly. Během práce se aktualizuje jen tato evidence; hotové položky i ověření zůstávají zde až do uzavření dávky. Pak se dávka přesune do WORK_LOG a další načte z BACKLOG. Již uzavřené výstupy M1-01 až M1-04 a doplňky sidebaru zůstávají v historickém logu; neopakují se.

## Rozsah a dokončení dávky

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.

Tento převzatý souhrn M1 je zastřešující úkol; M1-05 níže je jeho konkrétní první krok. Zahrnuje zbývající požadavky sekce M1 roadmapy, včetně typů artefaktů, metadat, obnovy indexu po přejmenování/smazání, recovery zápisů a zachování původních bajtů importu. Hotové části souhrnu doložené ve WORK_LOG se znovu neimplementují. Další kroky rozepisuj zde podle ověřeného stavu; relevantní existující V-* položky v BACKLOG používej jako návaznosti, jejich doplnění dočasně zachyť níže.

Podmínka uzavření: dokončené a ověřené zbývající požadavky M1 i přijaté ad-hoc úkoly a doložené review Gate M1 (použitelný workspace bez LLM v LXC i desktopu). Případné zúžení dávky musí výslovně zachovat otevřený gate a odloženou práci; samotné dokončení M1-05 nestačí.

## Na řadě

- [x] [completed] **M1-05 — Metadata dokumentu v editoru (PoC validated, 2026-09-10).** Záložka Metadata zobrazuje uložená metadata pouze pro čtení a dovoluje upravit popis/štítky. Obsah i explicitní změny metadat se ukládají jednou operací s původním operation ID/retry/receipt; identita, autor, vytvoření, privacy a provenance se zachovávají. Podporovány sidecary i frontmatter, vyčištění hodnot a samostatná editace metadat. Po uložení se čte potvrzený stav z Gitu. Reuse/adapt Artifacts, Qt widgetů a validátoru; crash boundaries ADR 0003/0016 beze změny. Kontrakt a limity: [ADR 0016](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

Ověření M1-05: cílených 15 testů artefaktů OK se skutečnými Qt widgety; společný obsah/metadata a historie, restart, readonly metadata, ztracená odpověď a retry, vazba digestu na změny metadat, odmítnutí nepovolených/nevalidních/nadměrných metadat bez pending a recovery na všech 12 procesních checkpointech. Celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **119 testů OK, bez vynechání**, 62,895 s. Místní odkazy a `git diff --check` v pořádku. Lokální Linux PoC; produkční připravenost ani nové ověření na cílovém zařízení se tím neprohlašují. Zůstává v TODO do uzavření dávky M1.


## Ad-hoc úkoly aktuální dávky

- [x] [completed] **WF-02 — Práce po dávkách (implemented, 2026-09-10).** Požadavek uživatele: celé milníky v TODO, navazující dávky v BACKLOG, průběžně měnit jen TODO a archivovat až po uzavření dávky; podporovat ad-hoc práci. Upraveny pokyny a pracovní dokumenty, souhrnný úkol M1 přesunut z BACKLOG do této dávky. Ověření: konzistence pravidel a odkazů, zachování původních otevřených položek a historických záznamů, `git diff --check`. Pouze dokumentační změna; aplikační testy znovu nespouštěny. Záznam zůstává zde do uzavření dávky M1.

- [x] [completed] **M1-AH-01 — Materializované kompiláty v roadmapě (designed, 2026-09-10).** Ad-hoc požadavek uživatele: soubory s výsledky zpracování zdrojů podle zadání (např. orientační rozpočtové obálky), ručně obnovitelné z aktuálních i nových zdrojů, bez verzování a přenosu výsledků. Doplněna sekce 2E roadmapy, [ADR 0018](docs/adr/0018-materialized-compilations.md) a vazba v architektuře: zachované zadání, lokální cache mimo Git, manifest vstupů, aktuálnost, privacy, recovery a explicitní uložení trvalého artefaktu. Ověřena konzistence s Git autoritou, oddělením indexu/journalu a ADR 0008; návrhové scénáře zahrnují změny zdrojů, revokaci a pády. Místní odkazy a `git diff --check` ověřeny. Pouze návrh, bez implementace či nových runtime testů; Gate M1 se nerozšiřuje. Záznam zůstává v aktuální dávce.

- [x] [completed] **M1-AH-02 — Hlavní panel chatu a náhledů (PoC validated, 2026-09-10).** Hlavní panel přepíná orchestrační chat a náhled vybraného artefaktu s uloženým popisem/metadaty. Podporuje základní Markdown, PNG/JPEG a stránkový raster PDF; chat bez backendu umožňuje pouze lokální rozepsání zadání a odesílání je nedostupné. Přepnutí záložek zachová obsah, změna projektu jej vymaže a opožděné odpovědi se odmítají. Autentizovaný endpoint čte jeden validovaný commit a odmítá pending/stale; projektové soubory se nemění. Reuse Projects/Workspace, token/origin kontrol a DOM; PDF používá systémový Poppler deklarovaný v .deb. Kontrakt, limity a recovery: [ADR 0019](docs/adr/0019-main-panel-preview.md), [návod](docs/project-opening.md).

Ověření M1-AH-02: cílené API a skutečný WebEngine pro Markdown/PNG/PDF, klávesnicové přepínání, zachování draftu mezi záložkami, vymazání při změně projektu, neaktivní HTML, validace registrace/ID, stale/pending, čtení commitnutých bajtů, limity a chybné/nedostupné PDF. Vizuálně zkontrolováno skutečné okno 1100 × 800. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **123 testů OK, bez vynechání**, 74,043 s, včetně instalace/upgrade/odstranění a offline desktopu. Místní odkazy, syntaxe JS a `git diff --check` ověřeny. Omezení: vstup 4 MiB, Markdown 2000 odřádkování a omezené formátování, PDF stránky 1–100/raster 1200 px/timeout 15 s; není to sandbox PDF parseru, plné RBAC ani zapojený LLM chat. Zůstává v TODO do uzavření dávky M1.


- [ ] [planned] připravit základní UI pro možnost ukázky PoC na schůzce s možnými partnery

## K předání do backlogu

Doplnění k **V-11** při předání dávky: příští distribuční inventář musí zahrnout novou systémovou závislost `poppler-utils` pro PDF náhledy (M1-AH-02). Historické inventáře se nepřepisují; veřejný release zůstává samostatným úkolem.
