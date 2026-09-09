# Srovnávací C++/libgit2 experiment M0-03

Pouze pro izolované testovací repozitáře. Nejde o produkční Git adapter ani náhradu Workspace. Python testy orchestrují stejné scénáře pro Git CLI a tento malý C++ executable; nejde o návrh produkčního C++/Python IPC.

## Hranice zápisů a obnovy před implementací

Běžný commit a merge mění Git index/worktree; při neúspěchu stav zůstává k explicitnímu rozhodnutí. Testovací abort obnovuje čistý výchozí HEAD hard resetem a vyčistí merge state; je určen výhradně pro disposable repozitáře, nikoli pro obecný editor s cizími změnami.

Pro srovnání s ADR 0003 oddělit vytvoření commit objektu (`prepare`) od publikace (`cas`). Před CAS je kandidát nepublikovaný; nadřazený journal musí trvale uložit jeho ID. CAS musí odmítnout změněný výchozí HEAD. Po publikaci lze tentýž kandidát rozpoznat a obnovit SQLite index z HEAD bez druhého commitu. Testovat přerušení procesu mezi těmito hranicemi. Samotné libgit2 neimplementuje journal ani atomickou operaci přes filesystem/Git/SQLite; plná koordinace zůstává v existujícím Workspace.

Přenos a autentizaci ověřit na lokálním repozitáři a loopback HTTP s testovacími credentials. Nejde o produkční TLS/SSH ani síťovou federaci.

## Sestavení a spuštění

Vyžaduje C++17 compiler, libgit2 1.9.x development headers a odpovídající runtime. Výchozí Python aplikace tuto závislost nezískává. Balíčky instalujte podle svého prostředí; žádný test je automaticky nestahuje.

```sh
c++ -std=c++17 -O2 -Wall -Wextra -Werror \
  spikes/libgit2/probe.cpp $(pkg-config --cflags --libs libgit2) \
  -o /tmp/libgit2-probe
/tmp/libgit2-probe version
M0_LIBGIT2_PROBE=/tmp/libgit2-probe python3 -m unittest tests.test_git_comparison -v
M0_LIBGIT2_PROBE=/tmp/libgit2-probe M0_GIT_HTTP=1 \
  python3 -m unittest discover -s tests -v
```

HTTP test vyžaduje oprávnění vytvořit socket na `127.0.0.1` a `git-http-backend` ze systémového Gitu. Používá pouze smyšlené testovací credentials a ephemeral port. Bez `M0_GIT_HTTP=1` se tento test výslovně přeskočí; chyba socketu při zapnutém testu je selhání, nikoli úspěch. Bez `M0_LIBGIT2_PROBE` se přeskočí celá volitelná srovnávací třída. Neplatná cesta k explicitně zadanému probe je chyba.

Na ověřovaném hostu chyběly hlavičky, ale runtime již existoval. Development balíček byl stažen a rozbalen do `/tmp/m0-libgit2/sdk` bez systémové instalace; skutečný příkaz sestavení:

```sh
c++ -std=c++17 -O2 -Wall -Wextra -Werror \
  -I/tmp/m0-libgit2/sdk/usr/include spikes/libgit2/probe.cpp \
  /usr/lib/aarch64-linux-gnu/libgit2.so.1.9 -o /tmp/m0-libgit2/probe
```

Tyto cesty nejsou požadavkem projektu, ale záznamem lokálního experimentu. `/tmp` není trvalá instalace. Do repozitáře se neukládá balíček, hlavičky třetí strany ani binární build.

## Co porovnání dokládá

- Commit, branch, clone/fetch, konflikt stejné entity a všechny tři konfliktní verze, abort z čistého výchozího stavu a lidské řešení s oběma rodiči.
- Oddělení kandidátního commitu od CAS publikace; skutečné `os._exit` před i po publikaci, následná obnova společného SQLite Indexu a odmítnutí nečekaného HEAD.
- Odmítnutí neplatné projekce existujícím Python validátorem pro commity obou variant.
- HTTP fetch se správnou autentizací a odmítnutí chybějících/chybných credentials.

Příprava kandidáta v probe používá pracovní Git index a `git_index_add_bypath`, tedy není ekvivalentem raw journal-byte sestavení soukromého indexu ve Workspace. Nepřebírá jeho ochranu cizího stagingu, neomezuje všechny cesty ani nevynucuje celou transakci. Testovací receipt je podklad pro simulaci restartu, nikoli druhá implementace autoritativního journalu. Abort může smazat editace provedené během merge: používat pouze v testovací disposable kopii. Refaktoring Python validátoru do C++ ani síťová federace nejsou předmětem.

Výsledky a volba adapteru: [ADR 0005](../../docs/adr/0005-git-adapter-comparison.md). Náklady na start executable nelze vydávat za výkon libgit2 vložené do trvale běžícího procesu.
