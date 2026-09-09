# ADR 0001 — Referenční storage experiment

Datum: 2026-09-09. Stav: přijato pro M0 experiment; produkční stack otevřený.

Začínáme Python standardní knihovnou a Git CLI bez shellu, protože jsou dostupné a dovolují ověřit konzistenci bez nové runtime závislosti. Produkční návrh má výchozí jeden backendový proces. Hybrid C++/Python musí doložit přínos měřením a náklady distribuce. libgit2 není zamítnuto: pkg-config jej v tomto prostředí nenalezl.

Prostředí prvního běhu: Linux aarch64, Python 3.14.4, Git 2.53.0. Toto není ověření cílového Turris Omnia/LXC.

## Výsledek prvního PoC

Příkaz `python3 -m unittest discover -s tests -v`: 4 testy prošly dne 2026-09-09.
Ověřena divergence dvou repozitářů, tři konfliktní verze, abort a merge se dvěma rodiči;
odmítnutí duplicitního ID bez nahrazení předchozího indexu; obnova indexu po změně HEAD
a po smazání databáze; indexování commitu bez zahrnutí rozpracovaných změn.
Obnova po změně HEAD simuluje pád mezi commitem a indexací, nejde o test násilného ukončení procesu.

## Výstupy a zbývající podmínky M0

- [x] Pracovní architektura, layout dat, hranice indexu a autoritativního stavu.
- [x] Popsaný uživatelský scénář konfliktu.
- [ ] Úplné strojové schéma a validátor frontmatter/sidecar.
- [ ] Obnova přerušeného zápisu artefaktu a sidecaru.
- [ ] libgit2 PoC a porovnání se stejnými scénáři Git CLI.
- [ ] Měření paměti, startu a balení na desktopu a Turris/LXC.
- [ ] Ověření bezpečného lokálního transportu a výběr desktopového obalu.
- [ ] Rozhodnutí o produkčním stacku a uzavření Gate M0.

## Podklady

- [Git merge: konflikty, rodiče a abort](https://git-scm.com/docs/git-merge)
- [Python subprocess: seznam argumentů a shell=False](https://docs.python.org/3/library/subprocess.html)
- [Dokumentace libgit2 pro následný PoC](https://libgit2.org/docs/)
