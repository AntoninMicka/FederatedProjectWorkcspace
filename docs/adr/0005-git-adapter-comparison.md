# ADR 0005 — Srovnání Git CLI a C++/libgit2

Datum: 2026-09-09. Stav: přijato pro navazující implementaci, PoC validated na vývojovém Linux hostu; produkční balení/transporty otevřené.

## Rozhodnutí

**Zachovat Git CLI jako výchozí Git adapter pro navazující implementaci.** Existující Workspace už nad ním ověřuje journal, serializaci, raw bytes, kandidátní commit, CAS publikaci a SQLite index. C++/libgit2 zůstává ověřenou alternativou pro případ doložené potřeby nativního backendu; jeho dřívější nedostupnost přes pkg-config nebyla technickým zamítnutím.

Změna nyní by vyžadovala přenést ochrany Workspace a bezpečnost transportů do další implementace; nové porovnání neprokázalo přínos, který by tento přenos vyžadoval. Testovací C++ executable není návrh trvalého C++/Python hybridu. Jazyk produkčního backendu, desktopový obal a konkrétní distribuční balení dále závisí na M0-05/M0-06. Tato volba nezavírá Gate M0.

## Podmínky experimentu

Ubuntu 26.04.1 LTS, Linux arm64, Python 3.14, Git 2.53.0, GCC C++ 15.2.0, C++17. Runtime `libgit2-1.9:arm64` 1.9.1+ds-1ubuntu1.1 již byl nainstalován. Development balíček stejné verze byl stažen z Ubuntu ports a rozbalen do `/tmp`; systém nebyl modifikován. Sestavení s `-O2 -Wall -Wextra -Werror` prošlo bez varování.

Zdroj, příkazy a hranice použití: [spikes/libgit2](../../spikes/libgit2/README.md). Nový C++ driver volá libgit2 přímo. Git CLI slouží v obou variantách také jako nezávislý čtenář výsledné historie; validace metadat a SQLite index se adaptují z existujícího PoC. Žádné produkční zdrojové komponenty ani licence se nekopírovaly do projektu.

## Výsledky

| Scénář | Git CLI | C++/libgit2 |
| --- | --- | --- |
| Commit, větev, lokální clone/fetch | prošlo | prošlo |
| Divergence stejné entity, base/ours/theirs v indexu | prošlo | prošlo |
| Abort a lidský merge se dvěma rodiči | prošlo | prošlo v disposable kopii; abort není obecné undo cizích editací |
| Kandidát před CAS, odmítnutí cizího HEAD | prošlo | prošlo |
| Pád procesu před/po CAS, restart bez dalšího commitu, obnova indexu | prošlo | prošlo; nadřazený journal zůstává mimo libgit2 |
| Neplatná projekce není publikována do SQLite indexu | prošlo | prošlo přes stejný Python validátor |
| Loopback HTTP fetch, správné/chybějící/chybné credentials | prošlo | prošlo přes credential callback |
| Kompletní souborový journal a ochrana cizího stagingu | existující Workspace PoC | nepřeneseno; C++ probe toto nedokládá |
| Produkční TLS/SSH, vault, revokace a síťová federace | neověřeno | neověřeno |

Lokální HTTP test vyžadoval povolení socketu mimo výchozí sandbox. Použil `git-http-backend`, loopback port a smyšlené credentials; žádný cizí účet nebo projekt. Testovací Git CLI posílá dummy Basic header přímo, libgit2 použije callback; ani jedno není implementace produkčního credential úložiště. Standardní verifikace certifikátů není v probe vypínána, ale TLS se tímto HTTP testem neověřilo.

Počty a poslední příkaz plného ověření drží TODO u M0-03. Srovnávací scénáře jsou v [tests/test_git_comparison.py](../../tests/test_git_comparison.py); bez explicitně zadaného sestaveného probe jsou označeny skipped, nikoli validated.

## Orientační náklady a balení

Na tomto hostu měl probe 75 800 B, sdílená libgit2 1 381 640 B a Git executable 4 329 080 B. Nejde o velikosti instalačních balíčků: Git potřebuje helpers, libgit2 další sdílené knihovny. `ldd` runtime ukázalo mimo jiné OpenSSL/libcrypto, libssh2, PCRE2, zlib, GSSAPI/Kerberos a jejich transitivní závislosti.

Orientační 50 běhů po 5 zahřívacích spuštěních v prázdném dočasném repo s jedním commitem: `git rev-parse HEAD` medián 0,695 ms (0,637–1,579 ms); nový proces `probe head` 5,628 ms (5,141–11,322 ms). Měřeno Python `perf_counter_ns` okolo `subprocess.run`, výstup do DEVNULL. Pořadí bylo CLI, pak probe; prostředí ani cache nebyly izolované. Výsledek popisuje start dvou executable na tomto hostu, nikoli výkon dlouho běžícího C++ backendu, paměť aplikace nebo Turris.

Pro Git CLI je třeba ve výsledném balení zajistit kompatibilní Git a požadované transport helpers, verzování a bezpečnou konfiguraci. Pro libgit2 navíc řešit build headers/linker, runtime ABI a distribuční závislosti konkrétního OS/architektury. Záznam copyright v Ubuntu balíčku uvádí pro libgit2 „GPL-2 with linking exception, origin admission“ a samostatné licence dílčích komponent. Audit výsledné distribuce a notices je stále součástí release readiness; nejde o právní závěr o kompatibilitě celé aplikace.

## Zbývající ověření

M0-05 ověří cílový Turris/LXC a desktopové náklady; M0-06 uzavře stack a balení. TODO V-06/V-09 drží produkční Git konfigurace a autentizované transporty. Migrace Workspace na libgit2 by vyžadovala samostatné rozhodnutí a stejné crash/conflict/privacy testy, včetně zachování bajtů, cizích změn a řízení přístupu.

## Podklady

- [libgit2: podmíněná aktualizace reference](https://libgit2.org/docs/reference/v1.9.0/refs/git_reference_create_matching.html)
- [libgit2: remote callbacks, credentials a certifikáty](https://libgit2.org/docs/reference/v1.9.0/remote/git_remote_callbacks.html)
- API kontrakty ověřeny také proti hlavičkám Ubuntu libgit2 1.9.1 (`refs.h`, `merge.h`, `reset.h`, `credential.h`); balíčková metadata licence v jeho `copyright` souboru.
