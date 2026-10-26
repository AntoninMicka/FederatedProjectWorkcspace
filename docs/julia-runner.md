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

## Runtime a binding

Archiv a `.asc` stáhněte přímo z odkazů oficiální stránky. Před rozbalením
porovnejte checksum z oficiálního manifestu a ověřte podpis proti fingerprintu
výše. Samotný import klíče bez porovnání fingerprintu není ověření identity.

### Doporučený onboarding

Pro podporovaný ARM64 profil vytvoří jediný příkaz privátní depot, run state a
připnutý binding. Nevyžaduje projekt, node ani user UUID:

```sh
federated-workspace-poc-julia setup \
  --runtime /opt/julia-1.10.12 \
  --archive /srv/runtime-sources/julia-1.10.12-linux-aarch64.tar.gz
```

Při běhu ze zdrojového checkoutu použijte místo instalovaného příkazu
`python3 -m spikes.julia_cli setup`. Výchozí cíl je
`$XDG_STATE_HOME/federated-workspace/julia/1.10.12-linux-aarch64`, případně
`~/.local/state/...`; lze jej změnit argumentem `--root`. Příkaz před zápisem
ověří podporovanou verzi a platformu, známý oficiální SHA-256 archivu a
praktickou dostupnost bubblewrap namespaces. Vytvoří pouze owned mode-0700
adresáře a nový mode-0600 `binding.json`; shodné opakování je idempotentní a
odlišný existující binding se nikdy nepřepíše.

JSON výsledek obsahuje pole `next.command` s přesným `prepare` příkazem a
vyplněnými cestami k novému state a bindingu. Zástupné hodnoty projektu a UUID
se doplní podle registrovaného projektu; definice `computation.json` a její
artefakty musí být verzované v tomto projektu.

Výsledek záměrně uvádí `archive_signature: not-verified-by-setup`: checksum je
připnutý v dodané verzi workspace, ale GPG identitu release klíče je stále
nutné ověřit samostatně podle předchozího odstavce. Úspěšný onboarding také
neinstaluje balíčky a nevytváří projektovou definici výpočtu.

Připravte privátní node-local depot. Pro projekt bez externích balíčků může být
prázdný; jinak jej musí samostatná administrativní operace naplnit včetně
registrů, package trees, artifacts a licenční evidence. Výpočet nikdy nespouští
`Pkg.instantiate`, resolution ani síťový fallback.

Po samostatném GPG ověření vytvoří exact binding tento fail-closed příkaz;
výstupní soubor nesmí předem existovat:

```sh
python3 -m scripts.julia_runtime_binding \
  --runtime-root /opt/julia-1.10.12 \
  --archive /srv/runtime-sources/julia-1.10.12-linux-aarch64.tar.gz \
  --archive-sha256 cc257b21967049642bfe17de1aff7dae17477eba4f423f98cb400c002080e5a2 \
  --depot /var/lib/federated-workspace/julia-depot-1.10.12 \
  --version 1.10.12 \
  --binding-id 00000000-0000-4000-8000-000000000000 \
  --revision official-1.10.12-linux-aarch64 \
  --output /var/lib/federated-workspace/julia-1.10.12-aarch64.json
```

Binding se při každé operaci znovu porovná s executable, sysimage, celým
rozbaleným distribučním stromem a depotem. Archivní SHA-256 je vstupní kontrola
při vytvoření bindingu; `distribution_sha256` v bindingu je hash skutečného
rozbaleného stromu, takže pozdější změna jiné runtime knihovny nezůstane skrytá.
Symlink unikající z distribuce, group/world-writable runtime nebo odlišný hash
operaci zastaví. Aktualizace vytváří nový binding; nepřepisuje staré runy.

## Explicitní běh

Globální argumenty CLI jsou cesta projektového Git worktree, privátní mode-0700
Julia state, binding a aktuální node/user UUID. `prepare` načte computation a
parametry jako bounded striktní JSON a vrátí preview s `approval_digest`:

```sh
python3 -m spikes.julia_cli \
  --project /srv/projects/example --state /srv/state/example-julia \
  --binding /var/lib/federated-workspace/julia-1.10.12-aarch64.json \
  --node-id NODE_UUID --user-id USER_UUID \
  prepare --operation-id RUN_UUID --project-id PROJECT_UUID \
  --computation computation.json --parameters parameters.json
```

Teprve následný příkaz s přesným digestem dispatchuje proces:

```sh
python3 -m spikes.julia_cli \
  --project /srv/projects/example --state /srv/state/example-julia \
  --binding /var/lib/federated-workspace/julia-1.10.12-aarch64.json \
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
M0_JULIA_RUNTIME_ROOT=/opt/julia-1.10.12 \
M0_JULIA_ARCHIVE=/srv/runtime-sources/julia-1.10.12-linux-aarch64.tar.gz \
  python3 -m unittest -v \
  tests.test_julia_computation.JuliaRuntimeAcceptanceTests
```

Samostatná kontrola namespace s testovacím runtime je pod
`M0_JULIA_SANDBOX_TEST=1`. Bez těchto proměnných plná unit sada oba fyzické
testy přeskočí; to není fyzická akceptace platformy.
