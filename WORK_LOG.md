# Záznam dokončené práce

Dokončené výstupy, výsledky ověření a historická gate review. Aktuální okno práce drží [TODO](TODO.md), vzdálenější otevřené položky [BACKLOG](BACKLOG.md), strategii a gates [roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>).

Starší záznamy od review M0-09R níže byly beze změny důkazů přesunuty z TODO. Časy, počty testů, popisy tehdejšího stavu a starší negativní review jsou historické; neoznačují automaticky dnešní stav. Nové dokončené výstupy přidávejte nahoru s ID, datem, úrovní výsledku, ověřením a omezeními. Původní ID a důkazy zachovávejte; věcné opravy doplňujte jako datované dodatky.

## WF-01 — Přehledné aktuální okno práce — 2026-09-10

- [x] [completed] **WF-01 — Oddělení aktuální práce, backlogu a historie (implemented).** AGENTS vymezuje roadmapu pro milníky/gates, TODO pro nejvýše 5 bezprostředních úkolů, BACKLOG pro ostatní otevřenou práci a WORK_LOG pro dokončené výstupy a ověření. Úkol se přesouvá se stejným ID a kontextem; historie se nepřepisuje. Z původních 23 otevřených položek zůstává M1-05 v TODO a 22 v BACKLOG; všechny historické sekce byly zachovány beze změny důkazů. Opraveny odkazy a zastaralý aktuální milník v úvodu roadmapy na M1. Existující allowlist zdrojového balíčku byl rozšířen o oba nové dokumenty, včetně kontroly v manifest testu.

Ověření: automatické porovnání původních a přesunutých sekcí i všech otevřených položek, kontrola místních odkazů a finálního diffu. Cílené testy balíčku prošly (Qt v prvním běhu vynecháno); následně `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů OK, bez vynechání**, 62,380 s. `git diff --check` bez chyb. Tato změna nezahajuje M1-05 ani nemění aplikační chování či produkční připravenost.

<a id="gate-m0"></a>
## Závěrečné Gate review M0-09R

Posouzený HEAD `1efc6d3`, pracovní strom čistý. **Gate M0 splněn pro rozsah architecture spike; přechod do M1 je schválen.** Toto rozhodnutí nahrazuje předchozí negativní review, která zůstávají níže jako historie. Neprohlašuje produkční připravenost ani splnění Gate M1.

| Podmínka Gate M0 | Důkaz | Závěr |
| --- | --- | --- |
| Zaznamenaný stack podložený PoC | ADR 0013; srovnání Git ADR 0005, PySide/měření ADR 0010 | Splněno: Python, Git CLI/SQLite, PySide/WebEngine, Linux .deb. |
| Autoritativní schéma a obnova indexu | ADR 0002/0004, validátory a testy; M0-05 rebuild indexu na cíli | Splněno pro minimální schéma. |
| Koordinace a recovery | ADR 0003, Workspace testy a M0-05: všech 12 checkpointů na Omnia SSD | Splněno pro procesní pády ve vymezeném PoC. |
| Návrh bezpečného lokálního API | ADR 0006/0007/0010, token/origin policy, skutečné Qt okno | Splněno pro návrh a transportní PoC. |
| Konflikt entity a obsah/sidecar | M0-07, FEDERATION a test_merge_scenarios | Splněno včetně čistého sémanticky neplatného merge. |
| Orchestrace bez LLM a execution boundaries | ADR 0008, návrhové scénáře | Splněno jako designed; LLM/RBAC engine se nepředstírá. |
| Cílové prostředí a balení | ADR 0012 čistá instalace/offline/upgrade/purge; M0-05 ARMv7/Btrfs měření | Splněno jako PoC validated. |

Poslední plná sada má 73 úspěšných testů (důkaz u cílového probe); nový uživatelský výstup potvrzuje cílové ověření. V tomto dokumentačním review se testy neopakovaly. Ověřeny návaznost důkazů, odkazy a finální diff.

Otevřené V-01 až V-11 se nepřevádějí na hotové: V-08 a V-10 jsou integrační podmínky práce s projekty, V-04/V-05 podmínky rozšíření metadat/importu, V-06/V-07 produkční ochrany a V-11 veřejný release. Výpadek napájení, plné RBAC, síťová federace, LLM, kapacita velkých projektů ani další OS nejsou vstupními podmínkami M1 podle definice Gate M0. Jejich backlog zůstává zachovaný. Produkční HTTP server není schválen pouhým úspěchem loopback PoC.

- [x] [completed] **M1-01 — PoC validated: otevření existujícího projektu v desktopu.** Služba Projects ověřuje registraci v1, shodu commitnutého project.json, existující vlastněný root a soukromý state. Workspace vrací název, commit ID a artefakty pod společným zámkem; pending blokuje čtení, chybějící/stale index se obnovuje, neplatná projekce se nevydává za aktuální. Lokální API přijímá pouze registrovaná ID a zachovává token/Host/Origin ochrany. UI vykresluje názvy jako text a při změně výběru/chybě odstraňuje starý výsledek. Spuštění `./run.sh desktop --node SOUBOR` zachovává cesty vůči volajícímu. [Postup a izolovaná ukázka](docs/project-opening.md), [hranice recovery](docs/adr/0014-project-read.md).

  Ověření: plná sada s `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **83 testů úspěšně, bez skipů**. Nových deset testů pokrývá dva projekty/restart, ztrátu a stale index, nevalidní registraci/verzi/config, symlink/hardlink, pending, poškozenou projekci, změnu HEAD, přerušenou inicializaci a rollback indexace, autentizované HTTP, prázdný projekt, wrapper a skutečné Qt vykreslení HTML názvů jako textu. `bash -n run.sh` a `git diff --check` prošly. Nejde o produkční RBAC/Git sandbox ani nový cílový běh na Omnii. Balení a offline testy ověřují regresi původního smoke; nové projektové čtení má vlastní Qt test z checkoutu. Přesný příklad z návodu prošel skutečným desktopovým smoke; vizuálně ověřen název, commit a artefakt. Návod je zahrnut i v allowlistu zdrojového balíčku.

- [x] [completed] **M1-02 — PoC validated: vytvoření a registrace projektu z desktopu.** Nativní dialog přijímá název a neexistující cílovou složku; jeden worker připraví Git/project.json, lokální stav a index, atomicky publikuje registraci a otevře projekt. Bez `--node` používá výchozí XDG uzel, jehož konfigurace vzniká až při potvrzeném vytvoření. Uzlový SQLite journal drží stabilní ID/parametry/receipts, používá společný neblokující flock a při běžném restartu automaticky obnovuje pending vytvoření. Existující cíl, nesoulad konfigurace nebo cizí změna se nezahladí. HTTP zůstává pouze pro čtení; nativní mutující kontrakt a crash boundaries jsou v [ADR 0015](docs/adr/0015-project-creation.md). [Postup](docs/project-opening.md) a nápověda aktualizovány.

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **95 testů úspěšně, bez skipů**. Dvanáct nových testů pokrývá skutečné procesní pády na osmi hranicích, deterministickou obnovu prvního commitu, opakování ID/parametrů, dva projekty, busy/pending/timeout, zachování existujícího cíle a cizích změn, selhání atomického zápisu node.json, lazy default konfiguraci, odmítnutí mutace přes HTTP, skutečný Qt dialog a restart i automatickou obnovu/otevření při běžném startu GUI. Test nainstalovaného .deb nyní vytváří skutečný dočasný projekt a ověřuje jeho i node.json zachování po purge. Regresní offline start a předchozí storage crash testy prošly. `bash -n run.sh`, lokální odkazy a `git diff --check` ověřeny. Nejde o nové ověření na Omnii ani výpadek napájení.

- [x] [completed] **M1-03 — PoC validated: Markdown editor, checklisty a hlavní TODO projektu.** Nativní Qt dialog vytváří/upravuje Markdown document artefakty přes registrovaný Workspace; obsah/sidecar se commitují společně, existující frontmatter i metadata se zachovávají. Checklist panel mění značky přímo v Markdownu, hlavní TODO má rezervované stabilní UUIDv5 a vznikne až při prvním uložení. GUI drží operation ID při retry, Workspace váže požadavek na digest/receipt, kontroluje výchozí HEAD a používá neblokující zámek/deadline. Nativní otevření editoru dokončí pending journal; HTTP zůstává pro čtení. [Kontrakt a crash boundaries](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **105 testů úspěšně, bez skipů**. Deset nových testů ověřuje přesné Git bajty a metadata, hlavní TODO/rename, checklisty včetně Unicode a code fences, skutečný Qt dialog a opětovné otevření, ztracenou odpověď/retry, dvě souběžná vytvoření TODO, stale/busy/deadline, neplatné vstupy, cizí editaci, ztrátu indexu a skutečné procesní pády na 12 hranicích. Regresní testy desktopu, .deb a offline startu prošly; nové editování má vlastní Qt test z checkoutu, nejde o nový cílový běh na Omnii. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: 1 MiB těla dokumentu; rozepsaný neuložený text není trvalý draft, není implementovaný bohatý preview, automatické sloučení editací ani výpadek napájení. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03a — PoC validated: stromový přehled hlavního TODO v levém panelu.** Přehled zobrazuje uložené checklisty podle odsazení, stav dokončení a sbalitelné větve. Sdílí validovaný commit a zámek s přehledem projektu, bez mutací/recovery; nativní uložení využívá existující refresh. Starý výsledek se odstraní při změně projektu/načítání/chybě a opožděná odpověď se zahodí. Parser/čtení dokumentu sdílí editor a přehled přes `markdown_documents.py`. [Kontrakt](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **108 testů úspěšně, bez skipů**. Tři nové testy a rozšířený WebEngine smoke ověřují hierarchii/počet hotových položek, committed proti neuloženému obsahu, pending bez recovery, prázdný/nepodporovaný/velký TODO, readonly checkboxy, bezpečné texty, sbalení větví, vyčištění a opětovné načtení i restart. Vizuálně ověřen screenshot vlastního dočasného projektu. Regrese editoru, .deb a offline startu prošly. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. Limit přehledu je prvních 1000 položek s upozorněním; nadpisy nejsou stromové uzly a externí změny vyžadují nové otevření. Historie M1-04 nebyla zahájena.

- [x] [completed] **M1-04 — PoC validated: historie změn dokumentu.** Tlačítko Historie v editoru otevírá nativní readonly dialog s verzemi, datem/autorem/zprávou, původním Markdownem, metadaty a diffem uložených souborů. ArtifactHistory čte jen registrovaný projekt pod společným zámkem, kontroluje HEAD před/po čtení a odmítá pending bez recovery. Historické snapshoty validuje samostatně; neplatné verze zůstávají označené v seznamu. Full-history zachovává obě větve merge, diff nepouští externí drivery/textconv, draft se nemění. [ADR 0017](docs/adr/0017-artifact-history.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **116 testů úspěšně, bez skipů**. Osm nových testů pokrývá verze a diff checklistu/metadat, zachování HEAD/stagingu/journalu/indexu/draftů, unregistered/revspec/nedosažitelné revize, stale/busy/deadline/pending, historickou konfiguraci, invalidní snapshot, rename, obě větve merge, limit seznamu, smazání/recreate, zákaz externího diff driveru a skutečný Qt dialog se zachováním rozepsaného textu a vyčištěním výsledku po chybě. Vizuálně ověřen finální dialog nad vlastním dočasným projektem. Regrese .deb/offline/desktopu prošly; nový viewer má vlastní Qt test z checkoutu. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: nejvýše 100 záznamů a 1 MiB těla; bez revertu, prohlížeče nyní smazaných artefaktů nebo nového cílového ověření na Omnii. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03b — PoC validated: přepínání TODO a zdrojů/artefaktů v levém panelu.** Dvě readonly záložky používají společný snapshot otevřeného projektu. Seznam zahrnuje dokumenty i zdroje s názvem/ID. Přepínání kliknutím a šipkami/Home/End, zachovaná volba při refreshi a odstranění starých dat při přepnutí/chybě. Reuse existujícího seznamu artefaktů bez nového backendového endpointu nebo změn ukládání. [Návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů úspěšně, bez skipů**. Nový test skutečného WebEngine ověřuje PDF zdroj vedle dokumentu, prázdný projekt a neměnný HEAD; rozšířený smoke kontroluje obě záložky, klávesnici/fokus/ARIA, přesné názvy/ID jako text, zachování volby při refreshi a vyčištění obsahu. Vizuální kontrola vlastního dočasného projektu, odkazy, `bash -n run.sh` a `git diff --check` prošly. Volba záložky je pouze pro aktuální okno; po restartu začíná TODO. Seznam zatím neotevírá obsah zdrojů. Metadata M1-05 nebyla zahájena.

## Gate review M0-09 — 2026-09-09

Historické posouzení před následným ručním deployem; novější důkaz je uveden u M0-05 a v dokončených výstupech. Aktuální rozhodnutí drží závěrečné M0-09R výše.

Posouzený HEAD: `1c7b228`, vstupní pracovní strom čistý. Výsledek: **Gate M0 nesplněn; M1 nezahajovat automaticky.** Review je dokončené, schválení gate nikoli. Nezavádí se nové architektonické rozhodnutí ani změna priorit nasazení.

| Kritérium | Důkaz a úroveň | Závěr |
| --- | --- | --- |
| Autoritativní data a obnova indexu | ADR 0002–0004, metadata/configuration/storage a jejich testy; designed + PoC validated | Splněno pro rozsah M0; integrace konfigurace a úplnější projekce zbývají V-03/V-08. |
| Koordinovaná obnova zápisu | ADR 0003 a tests/test_workspace.py: crash boundaries, CAS, pending stav, dva zapisovatelé | Splněno pro řízený Linux PoC; ne důkaz produkčního hardeningu nebo výpadku napájení. |
| Bezpečné lokální API a desktopové propojení | ADR 0006/0007, tests/test_local_api.py a tests/test_desktop.py | Návrh a PoC splněny; persistentní operace a nedůvěryhodný obsah zbývají V-10. |
| Konflikty entity a obsah/sidecar | M0-07, tests/test_merge_scenarios.py a FEDERATION | PoC splněno včetně sémanticky neplatného čistého merge; conflict UI a síťová federace nejsou implementované. |
| Orchestrace bez LLM, role, manifest, execution boundaries | ADR 0008 a návrhová tabulka scénářů | Designed splněno; LLM/RBAC implementace se neprohlašuje za hotovou. |
| Finální stack a distribuční cesta | ADR 0005 volí Git CLI; ADR 0007 pouze PoC binding; M0-06b zdrojový archiv | **Nesplněno:** finální backendový stack/binding a distribuční posouzení M0-06 zůstávají otevřené. |
| Cílové prostředí a provozní měření | M0-05 doložený LXC bez běhu aplikace; desktopové testy na vývojovém hostu | **Nesplněno:** měření na Omnia/ARMv7 a úplné posouzení startu, paměti a instalace cílových variant. |

Uživatel následně potvrdil úspěch ruční akceptace desktopu: kliknutí, zavření a restart fungují. Současné UI obsahuje jen paměťový čítač; nelze v něm ještě otevřít projekt, uložit artefakt ani ověřit zachování projektových dat po restartu. Ruční akceptace: třikrát „Ověřit spojení“ → 1/2/3, zavření → návrat terminálu, nový `./run.sh desktop` → 0 a opět funkční tlačítko. Výsledek je uživatelské potvrzení, nikoli nový automatický test.

Evidence testů je převzatá z dokončených úkolů níže (poslední plná sada u M0-07), nikoli nový běh v tomto review. Zkontrolovány současné zdroje UI, pokrytí testů, návaznost ADR a gate. Dokumentační ověření: lokální odkazy a finální diff. Po doplnění M0-05/M0-06 zopakovat rozhodnutí o gate s novými důkazy; dnešní negativní výsledek zachovat jako historii. Samotné potvrzení čítače gate neuzavře.

## Aktualizované posouzení M0 po instalaci .deb

Historické posouzení před offline testem; novější důkaz je níže v dokončených výstupech.

Posouzený HEAD `2b0adf2`, vstupní pracovní strom čistý. Historický review výše se nepřepisuje. Nové důkazy: PySide6 skutečné okno, měření desktopu a renderer crash (ADR 0010), instalační balík s izolovaným dpkg lifecycle (ADR 0011), uživatelsky potvrzené instalované GUI na Ubuntu arm64 a v Debian kontejneru x86_64 pod běžným uživatelem, headless Omnia demo na SSD. Poslední plná sada je u balíku: 69 testů, v tomto dokumentačním review nebyla opakována.

[Inventář kandidáta](docs/adr/0011-runtime-inventory.md) obsahuje SHA-256 balíku, přibalených souborů a distribučních copyright souborů 229 systémových závislostí na vývojovém hostu. Je úplný pro popsaný průchod Depends/Pre-Depends, nikoli univerzální SBOM všech platforem nebo hotový licenční audit. Uživatelův Debian má vlastní doložené verze; inventář Ubuntu se na něj nepřenáší.

**Výsledek: Gate M0 zůstává otevřený.** Podklady pro Python/Git/SQLite + PySide a .deb výrazně pokročily; funkční instalace neznamená finální schválení produkčního stacku. M0-06e zbývá izolovaný offline start a doložení čistého OS bez checkoutu/testovací vrstvy, M0-05 cílová provozní měření. Před zveřejněním balíku navíc zbývá skutečný maintainer kontakt, licenční posouzení a způsob aktualizací.

Uživatel přesměrovává X11 přes síť; odpojení jeho kontejneru by přerušilo i displej a nebylo by vhodným testem aplikace. Offline ověření zůstává planned, nikoli tvrzené jako úspěch ani obecně blocked. **Nejbližší konkrétní krok:** připravit lokální grafický smoke v oddělené síťové konfiguraci se zachovaným loopbackem a lokálním displejem, bez zásahu do uživatelova X11 spojení. Akceptace: žádná externí konektivita, funkční čítač, zavření/restart; zaznamenat způsob izolace a závislosti. V této změně se tento experiment nespouští.

## Dokončené výstupy a důkazy

- [x] [completed] **M0-09R — Designed: závěrečné Gate review.** Podmínky Gate M0 splněny podle tabulky výše; přechod do M1 schválen. První implementační úkol M1-01 vymezen bez zahájení implementace. Produkční omezení a historické negativní review zachovány.

- [x] [completed] **M0-05 — PoC validated: cílový běh a recovery na Omnii SSD.** Uživatel doložil `spikes.target_probe` s výsledkem PASS: Btrfs, armv7l, Python 3.13.5, SQLite 3.46.1, Git 2.47.3. Navazuje na potvrzený Debian LXC a SSD /dev/sda; pracovní adresář /var/tmp/workspace-poc. Všech 15 případů má verified=true: tři normální běhy a 12 pádů vlastního workeru. Probe ověřil pending čtení, zachování kandidáta, přesné bajty, jediný commit operace, idempotenci recovery, rebuild smazaného indexu a úklid dočasných dat. Jde o uživatelský cílový výstup, nikoli nový běh celé unittest sady. Původní demo 0,66 s běželo na tmpfs a nemíchá se s novými SSD měřeními.

  | Normální běh | Celý worker (s) | Apply (s) | Python peak RSS (KiB) |
  | --- | --- | --- | --- |
  | 1 | 0,8741 | 0,489111 | 11392 |
  | 2 | 0,8749 | 0,487234 | 11648 |
  | 3 | 0,8655 | 0,481006 | 11648 |

  | Hranice přerušení | Recovery (s) |
  | --- | --- |
  | prepared | 0,4496 |
  | file:0 | 0,4446 |
  | file:1 | 0,4455 |
  | applied | 0,4472 |
  | files-applied | 0,4243 |
  | commit-created | 0,4261 |
  | commit-ready | 0,2838 |
  | ref-updated | 0,2765 |
  | committed | 0,2620 |
  | git-indexed | 0,2606 |
  | indexed | 0,2758 |
  | completed | 0,0011 |

  `process_s` zahrnuje start Pythonu a inicializaci Git projektu, nikoli start serverové služby; RSS patří Python workeru, ne celému kontejneru/Git potomkům. Normální recover bez pending operace trval 0,0010–0,0011 s. Pád procesu na checkpointu není výpadek napájení ani pád uvnitř libovolného syscallu. Malá fixture není kapacitní benchmark. Úroveň je PoC validated pro zvolený stack; další produkční hardening drží V-06/V-07. Ověřena konzistence dodaných hodnot, odkazy a diff; Gate M0 čeká na review M0-09R.

- [x] [completed] **Implemented — cílový probe pro M0-05.** `spikes.target_probe` přenáší stávající crash scénáře do ručního deploye, vyžaduje explicitní základ a očekávaný filesystem, měří tři normální běhy a ověřuje 12 pádů workeru, obnovu a přesné bajty bez duplicitního commitu. Při úspěchu uklidí jen vlastní data, při selhání je ponechá. Lokální regresní testy pokrývají skutečné pády, chybný filesystem bez zápisu a zachování diagnostiky. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 73 testů prošlo bez skipů. Ověřeny odkazy a finální diff. Skutečný běh na Omnia SSD zatím neproběhl v této změně, M0-05 zůstává otevřený.

- [x] [completed] **M0-06 — Designed: stack pro M1 uzavřen.** [ADR 0013](docs/adr/0013-m1-stack.md) přijímá Python, Git CLI, oddělené SQLite index/journal, PySide6/WebEngine, same-origin UI a linuxový .deb na základě již ověřených PoC. C++ port/hybrid není potřeba bez doloženého problému. Rozlišena volba technologií od produkčního HTTP serveru, release a cílových měření M0-05; gate zůstává otevřený. Ověřena návaznost ADR, odkazy a diff, bez nového běhu testů.

- [x] [completed] **M0-06e — PoC validated: instalační kandidát v čistém OS.** [ADR 0012](docs/adr/0012-clean-os-validation.md) dokládá nový oficiální Ubuntu 26.04 arm64 kontejner, skutečné stažení a vyřešení APT závislostí bez doporučených balíků, instalovaný launcher pod běžným uživatelem přes interní Xvfb, dva offline starty a upgrade/purge se zachováním kontrolních projektových/stavových souborů. Není použit checkout ani runtime hostitele. Dpkg audit čistý; runtime verze, velikosti, image digest a .deb hash zaznamenány. Kontejner odstraněn. Bez změny kódu a nového běhu celé unittest sady; provedeny skutečné instalační/grafické experimenty, kontrola odkazů a diffu. Inventář kandidáta drží ADR 0011; licenční posouzení veřejného releasu není tímto uzavřeno.

- [x] [completed] **PoC validated — offline grafický běh .deb.** `tests/test_desktop_offline.py` vytváří samostatný user/network namespace s pouze aktivním loopbackem; ověřuje namespace ID, nulové capabilities aplikace, nepřítomnost tras a odmítnutí externího TCP bez trasy. Lokální X11 socket zajišťuje skutečné okno, dva běhy ověřují kliknutí, zavření backendu a restart rozbaleného .deb. Hostitelská síť ani uživatelovo přesměrování X11 se nemění. Metoda a limity v ADR 0011; nejde o čistý OS ani obecný bezpečnostní sandbox. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 70 testů prošlo bez skipů. Odkazy a finální diff ověřeny.

- [x] [completed] **Designed — distribuční inventář a aktualizované M0 review.** Inventarizován konkrétní .deb a místní runtime, doplněny důkazy uživatelské instalace a omezení přesměrovaného X11. Rozhodnutí o gate zůstává otevřené; odkazy, shoda hashů a diff ověřeny, bez nového běhu aplikačních testů.

- [x] [completed] **Implemented — evidence uživatelského ověření .deb na druhém prostředí.** Uživatel hlásí funkční aplikaci v kontejneru; dodané os-release uvádí Debian GNU/Linux 13 Trixie 13.6, uname x86_64. Dpkg-query uvádí federated-workspace-poc 0.1.0~m0, python3 3.14.7-3, python3-pyside6.qtwebenginewidgets 6.8.2.1-4 a python3-yaml 6.0.3-1+b1. Jde o konkrétní uživatelské prostředí, nikoli automaticky standardní čistý Debian nebo obecnou podporu amd64. Původ balíků a offline start nejsou doloženy. Uživatel upřesnil spuštění instalovaného launcheru přes sudo -u user federated-workspace-poc: grafické okno tedy běželo pod běžným uživatelem, nikoli rootem. Funkčnost okna je uživatelsky potvrzená; diagnostický výpis pocházel z root shellu. Zaznamenání evidence neuzavírá M0-06e ani gate; bez nového běhu testů, ověřena konzistence a diff.

- [x] [completed] **Implemented / PoC validated — .deb kandidát a izolovaný dpkg lifecycle (část M0-06e).** `run.sh package-deb`, builder, launcher a desktop entry používají systémové závislosti bez instalace za běhu. Ověřeny obsah, nepřepsání výstupu, chybějící závislosti, upgrade/purge se zachováním kontrolních dat a skutečné instalované okno. Rozsah a předem popsané crash boundaries v ADR 0011; čistý OS test zůstává otevřený. Závěrečné `M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 69 testů prošlo bez skipů. Ověřen výsledný .deb, shellová syntaxe, odkazy a finální diff.

- [x] [completed] **M0-06d — PoC validated: PySide6/WebEngine a měření desktopu.** Desktop i launcher používají PySide6 bez fallbacku na PyQt, shiboken6 zajišťuje pořadí destrukce objektů. Skutečný click/close/restart, pád rendereru a rozbalený zdrojový balík ověřeny. `PYTHONPATH=/tmp/m0-pyside M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 67 testů prošlo bez skipů. Ověřen launcher z /tmp a SIGTERM, bash syntax a help. Tři měřené běhy a omezení RSS/loadFinished jsou v [ADR 0010](docs/adr/0010-pyside-desktop-validation.md). Runtime moduly byly rozbaleny do /tmp, běžný uživatel je musí připravit dle README; čistá instalace zůstává M0-06e. Dokumentace, lokální odkazy a finální diff zkontrolovány.

- [x] [completed] **M0-06c — Designed: posouzení bindingu a distribuce.** [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md) porovnává PyQt/PySide, zachování Python jádra a instalační varianty. Ověřeny oficiální licenční podklady, místní Qt/PyQt importy a apt kandidáti chybějících PySide WebEngine modulů. Doporučení PySide/.deb je podmíněné skutečným runtime a instalačním ověřením M0-06d/e. Žádná instalace ani změna kódu; dokumentační kontrola konzistence, odkazů a diffu, bez nového běhu testové sady.

- [x] [completed] **PoC validated — ruční deploy a storage demo na Omnii.** Uživatelem dodaný výstup potvrzuje instalaci PyYAML 6.0.3, vytvoření artefaktu a Git historie, index po znovuotevření, úklid dočasných dat a hlášku úspěšné instalace do current. Daemon se nespustil. Jde o úspěšný smoke běh, nikoli celou testovou sadu nebo recovery na cílovém zařízení. Následné orientační měření uživatele: celé demo 0,66 s, max RSS potomků 11 520 KiB, exit 0; podrobnosti a omezení u M0-05. Měřený běh používal /tmp na tmpfs. Další uživatelský výstup potvrzuje úspěšný neměřený běh s TMPDIR=/var/tmp/workspace-poc na /dev/sda/Btrfs, včetně indexu po znovuotevření a úklidu. Nejde o restart kontejneru ani test pádu. Zbývající ověření drží M0-05; desktopové připojení k serveru zatím neexistuje.

- [x] [completed] **M0-09 — Designed: Gate review před M1.** Kritéria, podklady a negativní rozhodnutí jsou v sekci Gate review výše. M0-05/M0-06 zůstávají otevřené; dokončení review neznamená splnění gate. Bez nového běhu testů a bez vzdáleného nasazení.

- [x] [completed] **M0-08 — Designed: kontrakty a pravidla publikace.** [ADR 0008](docs/adr/0008-context-and-publication-contracts.md) vymezuje Backend/Role/Context Manifest, přesné vstupy a cíl, autorizaci před odesláním, fallback, nejistý výsledek síťového volání a CAS publikaci při změně HEAD. Návrhové review scénářů zahrnuje uzel bez LLM, Ollamu, cloud, peer, local-only i zakázaný obsah v Git historii. Ověřena konzistence s ADR 0003/0004, roadmapou a odkazy; čistě dokumentační změna bez nového běhu testů. Implementace a akceptační scénáře navazují v M1–M5/V-10 a M3-UB-01; Gate M0 zůstává otevřený.

- [x] [completed] **M0-07 — PoC validated: zbývající merge scénáře.** `tests/test_merge_scenarios.py` ověřuje modify/delete s abortem a obnovou úplného páru obsah/sidecar, rename/edit s přesnými bajty a metadaty a textově čistý merge dvou validních větví s dangling relation. Validace kandidáta odmítne publikaci; úmyslně neplatný commit v negativním testu nenahradí index a čtení odmítne stale stav. Ověřena lidská oprava a rodiče merge; scénáře a limity jsou ve FEDERATION. Produkční synchronizace ani conflict UI nevznikají. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 66 testů prošlo bez skipů. Ověřeny lokální odkazy a finální diff.
- [x] [completed] **V-02 — PoC validated: přesný důvod odmítnutí duplicity indexem.** Existující test ve `tests/test_storage.py` nyní vytváří platnou Markdown entitu se stejným ID jako registr a vyžaduje chybu Duplicate ID; zachování indexu a odmítnutí stale čtení zůstává ověřeno. Původní nesoulad názvu JSON souboru již výsledek nezastíní.

- [x] [completed] **M0-06b — Implemented: reprodukovatelný zdrojový desktopový balíček.** `run.sh package-desktop` vytváří allowlistovaný tar.gz s manifestem SHA256, bez privátního katalogu, prostředí a binárních závislostí. Atomické zveřejnění kompletního souboru bez přepsání existujícího vydání; ověření rozbalené kopie je součástí grafických testů. Systémový runtime stále vyžaduje Python/Qt/PyYAML; finální binding, distribuční licence, instalační balík a M0-05 zůstávají otevřené. Závěrečná sada `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 63 testů prošlo bez skipů, včetně skutečného WebEngine z rozbaleného archivu mimo checkout. Bash syntax, lokální odkazy, finální diff a sestavení archivu ověřeny.

- [x] [completed] **Implemented — ruční deploy headless PoC na Omnii.** `run.sh deploy-omnia` poskytuje dry-run a explicitní SSH nasazení do běžícího Debian LXC na SSD, omezený archiv zdrojů, oddělená vydání a přepnutí current až po demu. Lokální testy ověřují obsah archivu, validaci vstupů, chyby SSH a zachování previous/current po chybě instalace. Závěrečná sada s `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1`: 60 testů prošlo bez skipů; bash syntax, dry-run, odkazy a diff ověřeny. Vzdálený deploy nebyl spuštěn; uživatel jej provede ručně, M0-05 zůstává otevřené.

- [x] [completed] **Designed — rozsah importu Drive, NotebookLM a konverzací.** Doplněna sekce 3C roadmapy a IMP-01 až IMP-03. Ověřeny oficiální podklady k dílčím API/exportům, lokální odkazy a diff. Konektory, autentizace ani parsery exportů nejsou implementované; žádná uživatelská cloudová data nebyla načtena.

- [x] [completed] **M0-06a — PoC validated: spustitelné desktopové okno.** `./run.sh desktop`, `spikes/desktop.py` a `desktop_ui.py` adaptují existující lokální API; Qt okno používá stejný Python proces s backendovým vláknem, token pouze v nativní části a off-the-record WebEngine. Skutečné UI/JS kliknutí ověřuje autentizované API a zavření backendu; nový start resetuje čítač. [ADR 0007](docs/adr/0007-desktop-poc.md) vymezuje změnu pořadí na žádost uživatele a otevřené produkční balení/licence i M0-05. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 56 testů prošlo bez skipů. Ověřeno vykreslené okno ze screenshotu, `bash -n run.sh`, help/chybné argumenty a skutečný launcher z /tmp včetně SIGTERM. Kontrola odkazů, soukromých údajů a diffu dokončena.

- [x] [completed] **M0-04 — PoC validated: lokální socket a loopback HTTP.** `spikes/local_api.py` a sedm testů v `tests/test_local_api.py` porovnávají stejný paměťový endpoint přes Unix socket a IPv4 loopback. Ověřeny token/rotace, Host/Origin, CSRF formáty/metody, UID/práva, limity/duplicity JSON a hlaviček, timeout a pipelining; odmítnuté požadavky nemění stav. [ADR 0006](docs/adr/0006-local-api-transport.md) preferuje same-origin loopback HTTP pro navazující UI, s Unix alternativou. Browser/obal, bootstrap tokenu a napojení Workspace zůstávají V-10. Závěrečné `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 53 testů prošlo bez skipů. Sandbox původně odmítl bind; běh s povolenými lokálními sockety uspěl. Dokumentace, odkazy a `git diff --check` ověřeny.

- [x] [completed] **R-00 — Implemented: oddělený veřejný a soukromý reuse katalog.** REUSE_CATALOG obsahuje technologie a komponenty workspace; seznam veřejných externích repozitářů je zatím prázdný. Lokální inventura je v `REUSE_CATALOG.private.md`, vyloučeném z Gitu. Ověřeny odkazy, absence soukromých detailů ve změněných veřejných dokumentech, ignore pravidlo a diff; bez nového běhu aplikačních testů. Detailní posouzení před převzetím zůstává R-01.

- [x] [completed] **M0-03 — PoC validated: Git CLI vs. C++/libgit2.** `spikes/libgit2/probe.cpp` sestaven s C++17 a `-Wall -Wextra -Werror` proti libgit2 1.9.1. `tests/test_git_comparison.py` spouští obě varianty nad stejnými scénáři commit/branch/clone/fetch, divergence/abort/merge, CAS a restart před/po publikaci, odmítnutí neplatné projekce a loopback HTTP autentizace. Finální `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 46 testů prošlo bez skipů. HTTP test vyžaduje povolený loopback socket; bez explicitních voleb jsou srovnávací testy skipped. [ADR 0005](docs/adr/0005-git-adapter-comparison.md) zachovává Git CLI jako výchozí adapter; libgit2 je ověřená alternativa, ne produkční náhrada Workspace. Zaznamenány build/runtime závislosti a orientační velikosti/start; cílové balení M0-05/M0-06 a produkční transporty V-09 zbývají. Hlavičky byly pouze rozbaleny do /tmp; systém ani produkční stack nebyly změněny.

- [x] [completed] **M0-02 — PoC validated: minimální project.json a konfigurace uzlu.** `spikes/configuration.py` a read-only `check_config`/`run.sh config` validují přenositelný projekt, lokální uzel, stabilní UUID, verzi v1, nepřekrývající se lokální cesty a opaque credential reference. Sdíleny parserové limity a UUID/timestamp pravidla; neznámé verze se odmítají bez migrace. Kontrakt a budoucí explicitní migrační pravidla: [ADR 0004](docs/adr/0004-project-node-config.md), příklady v DATA_MODEL. Deset nových testů konfigurace pokrývá i chybové cesty a read-only CLI. `python3 -m unittest discover -s tests -v`: 42 testů prošlo; `bash -n run.sh` a kontrola dokumentovaných příkladů/odkazů prošly. Zapojení konfigurace do aplikačního lifecycle, ověření identity/vaultu a migrační zápis zbývají V-08; distribuce uživatelů není implementována.

- [x] [completed] **Implemented — shellový launcher storage PoC.** `run.sh` poskytuje výchozí dočasné demo, explicitní setup do `.venv`, test, check a help; `spikes/demo.py` používá existující Workspace/Git a lifecycle podle ADR 0003. Ověřeno demo, `bash -n`, spuštění z cizího adresáře, relativní cesta s mezerami, chyby argumentů a neplatný/chybějící projekt bez zápisu. Přes `./run.sh test` prošlo 32 testů. Síťová instalace `setup` nebyla v tomto běhu provedena. Launcher není UI/server; běžná aplikace a balení zůstávají v M1.

- [x] [completed] **Implemented — optimalizace projektových instrukcí AGENTS.md.** Rozlišeno čtení pro návrh, dokumentaci a implementaci; doplněno opětovné použití nezměněných podkladů, pravidlo „další úkol“, aktualizace TODO po uceleném výsledku a evidence ověření bez duplikace počtů testů. Crash boundaries přesunuty před implementaci, zpřesněno cílené a závěrečné ověření. Architektonické mantinely, LLM workflow a pravidla commitů zachovány. Ověřena konzistence, lokální odkazy a diff; čistě dokumentační změna bez nového běhu testů.

- [x] **[completed] M0-01 — Jedna koordinovaná operace journal → validace → Git commit → index.**
  **PoC validated:** `spikes/workspace.py` adaptuje Journal/Git/Index a poskytuje apply/recover/read/receipt. Společný zámek, trvalé UUID a kandidátní commit před compare-and-swap posunem větve, blokované čtení pending operace a dokončený receipt. `tests/test_workspace.py`: 13 nových testů, včetně skutečných pádů procesu a dvou zapisovatelů; celkem 32 testů prošlo. Podrobnosti: [ADR 0003](docs/adr/0003-coordinated-operation.md). Původní akceptační požadavky:

  Operace musí mít stabilní `operation_id` a explicitní stavový životní cyklus. Minimálně musí být možné po restartu rozlišit:

  `prepared → files-applied → committed → indexed`

  Implementace nemusí použít přesně tyto názvy, ale stav musí být obnovitelný bez odhadu podle neúplných vedlejších efektů.

  Journal / operation record nesmí být definitivně odstraněn pouze proto, že byly úspěšně zapsány soubory. Musí zůstat dost informace k rozpoznání, zda příslušný Git commit již vznikl a zda byl index aktualizován.

  Operace eviduje minimálně:

  - operation ID,
  - výchozí HEAD,
  - zamýšlené změněné cesty,
  - stav operace,
  - po commitu výsledný commit ID.

  Recovery musí být idempotentní: opakovaný restart nesmí vytvořit další commit stejné operace.

  Git commit nesmí používat neomezené `git add --all`. Musí commitnout pouze cesty vlastněné aktuální operací, nebo operaci bezpečně odmítnout, pokud nelze oddělit cizí změny.

  Před commitem ověřit, že HEAD stále odpovídá výchozímu HEAD operace. Změna HEAD během operace nesmí být tiše přepsána.

  Akceptace: zámek pokrývá celý životní cyklus, pending stav brání publikaci neúplného projektu; commit obsahuje pouze zamýšlené změny a explicitního autora; restart po zápisu/před commitem i po commitu/před indexací neztratí změny ani nevytvoří duplicitní commit. Ověřit změnu HEAD, cizí rozpracované změny, opakovanou obnovu a dva kooperující zapisovatele. Původní podklad: ADR 0002; samostatný `Git.commit` zůstává testovacím helperem s `add --all`. Workspace jej nepoužívá a drží journal až do indexace. Limity: existující commit a běžná větev, čistý vstup, kooperující procesy se společným stavovým adresářem; ne produkční aplikace.

- [x] [completed] **IP-00 — Implemented: dokumentační integrace IP roadmapy.** Zachována podpůrná roadmapa v `docs/IP`, založeny PATENT_RISK_REGISTER a DEFENSIVE_DISCLOSURES s neověřeným watchlistem a rezervovanými DD náměty; propojeny master roadmapa, README a CONTRIBUTING. Zohledněna existující MPL-2.0. Ověřeny lokální odkazy, věcná konzistence a diff; patentová rešerše, publikace, DOI a crowdfunding zůstávají neprovedené.

- [x] **[completed] Designed — základní návrhy a kostra experimentů.** ARCHITECTURE, DATA_MODEL, FEDERATION, SECURITY, REUSE_CATALOG a ADR 0001/0002 existují; aplikační skeleton, síť ani UI tím nejsou hotové.
- [x] **[completed] PoC validated — Git divergence a historie.** `tests/test_storage.py`: dvě lokální repo kopie, tři konfliktní verze, abort, merge se dvěma rodiči. Žádná síťová federace/autentizace.
- [x] **[completed] PoC validated — validace artefaktů a registrů.** `spikes/metadata.py`, `tests/test_metadata.py`: schéma, UUID, JSON/YAML duplicity, limity, frontmatter, sidecar a vztahy.
- [x] **[completed] PoC validated — SQLite index.** `spikes/storage.py`, `tests/test_storage.py`: validovaný commit, stale detection, obnova z HEAD i po odstranění databáze, oddělení necommitnutých změn.
- [x] **[completed] PoC validated — souborový journal.** `spikes/journal.py`, `tests/test_journal.py`: vytvoření, přejmenování, smazání, přerušená obnova, cizí editace, zachování binárních bajtů a návazný ručně koordinovaný commit/index. Testy používají skutečné `os._exit` v pomocném procesu.
- [x] **[completed] Implemented, ručně ověřeno — CLI validátor projekce.** `spikes/check_project.py`; důkaz smoke testu v ADR 0002, automatizace zbývá V-01.
- [x] **[completed] Implemented — vývojový workflow.** AGENTS.md, tento TODO a reconciliace roadmapy vůči kódu; architektura, ADR a experimenty zachovány.

## Posouzení repozitáře k 2026-09-09

Výchozí HEAD posouzení: `71424f2`; pracovní strom byl čistý. Přečteny dokumenty, oba ADR, všechny spikes a testy. Opětovně spuštěno `python3 -m unittest discover -s tests -v`: **19 testů prošlo** na současném vývojovém hostu. Repozitář neobsahuje nakonfigurovaný build/lint/CI. Přehled neprohlašuje produkční připravenost.

Rozpory a opravy stavu: nezaškrtnuté frontmatter/sidecar, index a definice metadat v roadmapě jsou nyní výslovně PoC validated; původní operativní seznam sekce 19 je převeden sem. Návrhové body backendu, federace, desktopu a bezpečnosti jsou designed, ne implementované. Katalog SQLite nyní zahrnuje i lokální autoritativní journal, což nemění rozhodnutí o neautoritativním projektovém indexu. Věcné otevřené mezery metadat, indexu a testových důkazů jsou V-01 až V-06. Historické počty testů v ADR 0001/0002 zachovávají význam výsledků jednotlivých experimentů.
