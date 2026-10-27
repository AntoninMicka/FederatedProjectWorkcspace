<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Lokální Julia runner

Runner provádí pouze explicitně připravený a potvrzený
`fpw-julia-computation-v1`. Otevření projektu, status, import ani reconciliation
nespouštějí Julia kód. Definice, entrypoint, vstupy, `Project.toml` a manifest
jsou připnuté na jeden Git commit a konkrétní bajty; runtime binding připíná
executable, distribuci, sysimage, platformu a read-only offline depot.

## Ověřený profil a hranice

PoC je fyzicky ověřen pro oficiální Julia **1.10.12 LTS**, Linux glibc
**aarch64**, a `bubblewrap 0.11.1`. Archiv není součástí repozitáře ani `.deb`.
Jeho oficiální SHA-256 je
`cc257b21967049642bfe17de1aff7dae17477eba4f423f98cb400c002080e5a2` a
ověřený podpis používá fingerprint
`64B779A570972FFF7BFC2B54EAD471E1A1F2C10A`. Primární zdroje jsou
[ruční stažení Julia](https://julialang.org/downloads/manual-downloads/),
[checksum manifest](https://julialang-s3.julialang.org/bin/checksums/julia-1.10.12.sha256)
a [release key](https://julialang.org/assets/juliareleases.asc).

Linux x86-64 zůstává kandidátem z ADR 0057, ale tato dávka jej neprohlašuje za
ověřený profil. Windows, macOS, musl, GPU a distribuované workery nejsou
podporované. Bubblewrap musí na konkrétním hostu skutečně vytvořit user, PID,
mount a network namespace; pokud to host policy zakazuje, run fail-closed
selže. Jde o PoC izolaci nedůvěryhodného nativního procesu, nikoli obecný
produkčně certifikovaný sandbox.

## Zprovoznění podporované Julie od začátku

Tento postup je určený výhradně pro **Linux glibc aarch64**. Stávající Julia z
distribučního balíčku nebo příkaz `julia` v `PATH` se automaticky nepoužije:
runner potřebuje samostatný nezměněný strom z oficiálního archivu a původní
archiv pro kontrolu identity. Vedlejší instalace níže stávající Julii nemaže
ani nemění.

### 0. Nejdřív ověřte, že uzel obsahuje runner

Návod nepředpokládá, že starší instalace workspace už nový příkaz obsahuje.
Varianty nejsou zaměnitelné; vyberte ji podle adresáře, ve kterém pracujete.

Pokud jste v kořeni vývojového checkoutu `FederatedProjectWorkcspace` (je zde
soubor `spikes/julia_cli.py`), nepoužívejte balíčkový příkaz. Musí projít:

```sh
test -f spikes/julia_cli.py
test -f scripts/julia_runtime_binding.py
python3 -m spikes.julia_cli setup --help
```

Na uzlu instalovaném z aktuálního `.deb`, mimo zdrojový checkout, musí projít:

```sh
command -v federated-workspace-poc-julia
federated-workspace-poc-julia setup --help
```

Na Omnii v Debian LXC po **plném** deploymentu aktuální feature musí projít:

```sh
cd /opt/federated-workspace/current
test -f spikes/julia_cli.py
test -f scripts/julia_runtime_binding.py
.venv/bin/python -m spikes.julia_cli setup --help
```

Pokud příslušná kontrola neprojde, **dál nepokračujte**. Uzel má starší release
bez `COMP-02`; žádný Julia runtime tento chybějící workspace kód nenahradí.
Nejdřív nainstalujte aktuální `.deb` nebo proveďte plný `deploy-omnia` z této
feature větve. `--update-only` není pro první instalaci vhodné, protože
neinstaluje systémovou závislost `bubblewrap`.

### 1. Ověřte platformu a nástroje

```sh
uname -m
getconf GNU_LIBC_VERSION
command -v bwrap
command -v curl
command -v gpg
```

První dva příkazy musí vrátit `aarch64` a `glibc ...`. Na Debianu/Ubuntu lze
chybějící nástroje doplnit například:

```sh
sudo apt-get update
sudo apt-get install bubblewrap ca-certificates curl gnupg
```

Jiná architektura, musl nebo host zakazující user namespaces nejsou tímto PoC
podporované; neobcházejte kontrolu jiným runtime nebo vypnutím sandboxu.

### 2. Stáhněte všechny ověřovací podklady

Následující příkazy ukládají soubory do uživatelského adresáře a nevyžadují
zápis do `/opt` ani `/var`:

```sh
install -d -m 700 "$HOME/.local/share/fpw-julia/sources"
install -d -m 700 "$HOME/.local/share/fpw-julia/runtime"
cd "$HOME/.local/share/fpw-julia/sources"

curl --fail --location --proto '=https' --tlsv1.2 \
  --output julia-1.10.12-linux-aarch64.tar.gz \
  https://julialang-s3.julialang.org/bin/linux/aarch64/1.10/julia-1.10.12-linux-aarch64.tar.gz
curl --fail --location --proto '=https' --tlsv1.2 \
  --output julia-1.10.12-linux-aarch64.tar.gz.asc \
  https://julialang-s3.julialang.org/bin/linux/aarch64/1.10/julia-1.10.12-linux-aarch64.tar.gz.asc
curl --fail --location --proto '=https' --tlsv1.2 \
  --output julia-1.10.12.sha256 \
  https://julialang-s3.julialang.org/bin/checksums/julia-1.10.12.sha256
curl --fail --location --proto '=https' --tlsv1.2 \
  --output juliareleases.asc \
  https://julialang.org/assets/juliareleases.asc
```

Pokud stahujete jiným počítačem, přeneste všechny čtyři soubory beze změny.

### 3. Ověřte checksum, fingerprint a podpis

```sh
grep ' julia-1.10.12-linux-aarch64.tar.gz$' julia-1.10.12.sha256 \
  | sha256sum --check -

gpg --show-keys --with-colons juliareleases.asc \
  | awk -F: '$1 == "fpr" {print $10; exit}'
```

První příkaz musí skončit textem `OK`. Druhý musí vypsat přesně:

```text
64B779A570972FFF7BFC2B54EAD471E1A1F2C10A
```

Teprve potom použijte oddělený lokální keyring a ověřte podpis:

```sh
install -d -m 700 julia-release-gnupg
gpg --homedir ./julia-release-gnupg --import juliareleases.asc
gpg --homedir ./julia-release-gnupg --verify \
  julia-1.10.12-linux-aarch64.tar.gz.asc \
  julia-1.10.12-linux-aarch64.tar.gz
```

Příkaz musí skončit s návratovým kódem 0 a kladným potvrzením podpisu (text se
může lišit podle locale). Varování o tom, že klíč není certifikovaný osobním
důvěryhodným podpisem, nenahrazuje ani neruší předchozí ruční porovnání
fingerprintu.

### 4. Jedním příkazem rozbalte a připněte runtime

Ze zdrojového checkoutu repozitáře stačí cesta k již ověřenému původnímu
archivu:

```sh
cd /cesta/FederatedProjectWorkcspace
./run.sh julia-setup \
  "$HOME/.local/share/fpw-julia/sources/julia-1.10.12-linux-aarch64.tar.gz"
```

Stejný příkaz funguje uvnitř aktuálního Omnia release. Z nainstalovaného
`.deb`, který neposkytuje checkoutový `run.sh`, použijte:

```sh
federated-workspace-poc-julia setup-archive \
  --archive "$HOME/.local/share/fpw-julia/sources/julia-1.10.12-linux-aarch64.tar.gz"
```

Příkaz ještě před zápisem znovu porovná archiv s připnutým SHA-256, odmítne
absolutní a unikající cesty/linky, speciální soubory, nadlimitní obsah i jiný
kořen distribuce. Rozbaluje do privátního pending adresáře; až ověřený strom
atomicky přejmenuje na `.../runtime/julia-1.10.12`. Pád před přejmenováním
ponechá nejvýše vlastněný pending adresář, který shodné opakování bezpečně
obnoví novou extrakcí. Pád po přejmenování dokončí shodné opakování vytvořením
bindingu; existující odlišný binding se nepřepíše.

Úspěšný JSON obsahuje `"status":"ready"`, cesty `binding`, `state`, `depot`
a pole `next.command`. Výchozí cíl je pod
`$XDG_STATE_HOME/federated-workspace/julia/1.10.12-linux-aarch64`, je-li tato
proměnná absolutní; jinak pod
`$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64`.
Opakování stejného příkazu musí vrátit `"reused":true`.

`archive_signature: not-verified-by-setup` není chyba: setup ověřuje známý
oficiální checksum, ale nemůže doložit, že jste skutečně provedli samostatný
GPG krok výše. Příkaz také nestahuje balíčky, nespouští projektový kód a
nevytváří `computation.json`.

Tím je připravený **runtime**. Otevřený projekt poté nabídne v záložce
**Výpočty** každou validní definici `fpw-julia-computation-v1`. Tlačítko
**Nový Julia model** otevře specializovaný editor s minimální bez-závislostní
šablonou. Jedno potvrzené uložení zapíše Julia entrypoint, `Project.toml`,
`Manifest.toml` a definici jako čtyři projektově spravované `document`
artefakty v jediné Workspace transakci; importované immutable `source`
artefakty editor měnit nesmí. Uložením se kód nespouští.

Běžná část editoru obsahuje kód a JSON kontrakty parametrů a výstupů. Přesné
prostředí a execution policy jsou v pokročilé části. Výchozí manifest odpovídá
prázdnému projektu pro Julia 1.10.12; jakmile přidáte balíčky, vytvořte nový
manifest pomocí Julia Pkg v kontrolovaném přípravném prostředí a vložte jeho
úplné bajty. Editor balíčky nestahuje, `Pkg.resolve` ani `Pkg.instantiate`
nespouští a ručně sestavený manifest nevydává za reprodukovatelný.

Změna parametru ani příprava preview kód nespustí; běh vyžaduje samostatné
potvrzení exact preview a publikace jednoho výsledku další potvrzení.

Desktop použije lokálního autora projektu. Web používá přihlášený účet a
vyžaduje zápisové oprávnění pro preview, dispatch, cancel/reconcile i
publikaci; definici nebo vstup `local-only` přes síť nenabízí. Po restartu UI
čte Julia journal, ale samo běh neopakuje. Stav `dispatching` lze explicitně
reconcile, pouze pokud v aktuálním procesu neběží jeho worker; neúplný účinek
bez kompletní materializace skončí `unknown`.

`next.command` zůstává nízkoúrovňové CLI pro diagnostiku a automatizované
testy a vyžaduje UUID registrovaného projektu, uzlu a uživatele.

### Časté chyby

- `Unsupported Julia setup profile` znamená jinou verzi nebo architekturu.
- `Julia archive SHA-256 differs` znamená chybný, poškozený nebo jiný archiv.
- `Archive SHA-256 ... does not match supported profiles` vypíše skutečný hash
  i podporované verze. Jiný platný release (například 1.13.x) se nepovolí jen
  podle názvu; potřebuje vlastní připnutý checksum a runtime akceptaci.
- `Unsafe Julia distribution ...` znamená změněná práva nebo upravený již
  rozbalený runtime; stávající binding ani runtime se automaticky nepřepisují.
- Chyba `bwrap`/`Operation not permitted` znamená, že host nepovoluje potřebné
  namespaces. Runner záměrně nepokračuje bez síťové a procesové izolace.
- `Existing Julia binding differs` chrání existující běhy. Pro jiný runtime
  použijte nový `--root`; starý binding nepřepisujte.

Binding se při každé operaci znovu porovná s executable, sysimage, celým
rozbaleným distribučním stromem a depotem. Výpočet nikdy nespouští
`Pkg.instantiate`, resolution ani síťový fallback. Projekt s externími balíčky
proto vyžaduje samostatně připravený úplný offline depot.

### Nízkoúrovňový generátor bindingu

`python3 -m scripts.julia_runtime_binding --help` je diagnostické rozhraní pro
správce a testy. Pro běžné zprovoznění jej nepoužívejte; vyžaduje ruční UUID,
depot, checksum, revision i výstupní cestu a neposkytuje onboardingové kontroly
a adresářový lifecycle příkazu `setup`.

## Explicitní běh

Globální argumenty CLI jsou cesta projektového Git worktree, privátní mode-0700
Julia state, binding a aktuální node/user UUID. `prepare` načte computation a
parametry jako bounded striktní JSON a vrátí preview s `approval_digest`.
Použijte skutečné `state` a `binding` cesty vrácené v `next.command`; následující
příklad předpokládá, že `XDG_STATE_HOME` není nastavené:

```sh
python3 -m spikes.julia_cli \
  --project /cesta/k/registrovanemu-projektu \
  --state "$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64/state" \
  --binding "$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64/binding.json" \
  --node-id NODE_UUID --user-id USER_UUID \
  prepare --operation-id RUN_UUID --project-id PROJECT_UUID \
  --computation computation.json --parameters parameters.json
```

Teprve následný příkaz s přesným digestem dispatchuje proces:

```sh
python3 -m spikes.julia_cli \
  --project /cesta/k/registrovanemu-projektu \
  --state "$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64/state" \
  --binding "$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64/binding.json" \
  --node-id NODE_UUID --user-id USER_UUID \
  execute --operation-id RUN_UUID --approval-digest APPROVAL_SHA256
```

K dispozici jsou samostatné příkazy `status`, `cancel`, `reconcile` a `output`.
`output` vytvoří nový mode-0600 soubor a nikdy nepřepíše existující cestu.
Po durable `dispatching` se přerušený běh bez úplné hashově shodné generace
změní na `unknown` a automaticky se neopakuje. Cancel a timeout ukončují celou
procesní skupinu; cache zůstává mimo projektový Git, export a federaci.

`publish` je další explicitní Workspace operace s vlastním publication UUID,
expected HEAD, novým artifact UUID a autorem. Publikuje právě jeden ověřený
výstup, zachová nejpřísnější privacy a ukládá schema-v4 computation provenance.
Pád publikace obnovuje Workspace journal a nemění dokončený Julia run.

## Reprodukovatelná fyzická akceptace

Po ověření a rozbalení oficiálního archivu lze zopakovat skutečný výpočet,
aktivní síťový probe a publikaci v dočasném projektu:

```sh
M0_JULIA_RUNTIME_ROOT="$HOME/.local/state/federated-workspace/julia/1.10.12-linux-aarch64/runtime/julia-1.10.12" \
M0_JULIA_ARCHIVE="$HOME/.local/share/fpw-julia/sources/julia-1.10.12-linux-aarch64.tar.gz" \
  python3 -m unittest -v \
  tests.test_julia_computation.JuliaRuntimeAcceptanceTests
```

Samostatná kontrola namespace s testovacím runtime je pod
`M0_JULIA_SANDBOX_TEST=1`. Bez těchto proměnných plná unit sada oba fyzické
testy přeskočí; to není fyzická akceptace platformy.
