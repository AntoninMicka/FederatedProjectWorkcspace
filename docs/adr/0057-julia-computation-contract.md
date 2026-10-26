<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0057 — Připnutý lokální Julia výpočetní kontrakt

- Stav: přijatý návrh
- Datum: 2026-10-26
- Dávka: `COMP-01`

## Kontext a hranice rozhodnutí

Julia je preferovaný výpočetní backend pro numerické modely, simulace,
optimalizace, statistiku, tabulky a grafické výstupy. Není LLM backend,
renderer s implicitním přístupem k projektu ani nový projektový writer. Import,
otevření projektu a zobrazení posledního výsledku nikdy nespouštějí kód.

Toto rozhodnutí uzavírá přenositelný kontrakt modelu a prostředí, lokální run
record, materializaci a předání k explicitní publikaci. Neimplementuje runner,
instalátor, sandbox ani UI. Jejich první ověření patří do `COMP-02` a nesmí
označit procesovou izolaci za bezpečný sandbox bez platformního důkazu.

Autority zůstávají oddělené:

- projektový Git drží definici výpočtu, model, `Project.toml`, přesně vybraný
  manifest a odkazy na vstupní artefakty;
- node-local runtime inventory drží přesný Julia executable, verzi, platformu,
  hash distribuce/executable/sysimage a stav jeho ověření;
- node-local run journal je autoritou requestu, approval, stavů a receiptů;
- privátní materializační cache je obnovitelná projekce podle ADR 0018;
- pouze samostatná operace Workspace může z vybraného výstupu vytvořit
  verzovaný projektový artefakt.

## Přenositelná definice výpočtu v1

Definice je striktní verzovaný JSON dokument `fpw-julia-computation-v1`.
Neznámé pole, nekanonické UUID, absolutní cesta, `..`, symlink, duplicita nebo
hodnota mimo deklarovaný limit se odmítne. Dokument nese právě tato pole:

```json
{
  "schema": "fpw-julia-computation-v1",
  "computation_id": "uuid",
  "title": "bounded UTF-8",
  "entrypoint": {
    "artifact_id": "uuid",
    "path": "relative/model.jl",
    "git_blob": "40-or-64-hex",
    "sha256": "64-hex"
  },
  "environment": {
    "project_path": "relative/Project.toml",
    "project_sha256": "64-hex",
    "manifest_path": "relative/Manifest-v1.10.toml",
    "manifest_sha256": "64-hex",
    "julia_compat": "1.10.12"
  },
  "inputs": [{
    "name": "identifier",
    "artifact_id": "uuid",
    "path": "relative/source.ext",
    "git_blob": "40-or-64-hex",
    "sha256": "64-hex",
    "media_type": "registered/type",
    "required": true
  }],
  "parameters": [{
    "name": "identifier",
    "type": "boolean|string|integer|number|array|object",
    "required": true,
    "default": null,
    "constraints": {}
  }],
  "outputs": [{
    "name": "identifier",
    "kind": "table|chart|report|dataset|file",
    "media_type": "registered/type",
    "required": true,
    "max_bytes": 1
  }],
  "execution_policy": {
    "network": "deny",
    "timeout_ms": 1,
    "cpu_threads": 1,
    "max_processes": 1,
    "memory_bytes": 1,
    "output_bytes": 1,
    "output_files": 1,
    "stdout_bytes": 1,
    "stderr_bytes": 1
  }
}
```

`constraints` je typově uzavřený podkontrakt: čísla mohou mít konečné
`minimum`/`maximum`, string `min_length`/`max_length` a uzavřený `enum`, pole
typ položky a maximální délku a objekt pevnou mapu properties bez dalších
klíčů. `NaN`, nekonečno, binární data a spustitelné fragmenty nejsou parametry.
Konkrétní request ukládá kanonický JSON parametrů a jeho SHA-256; argumenty se
nikdy neskládají do shellového příkazu.

Každý vstup patří stejnému validovanému project commitu jako definice.
`artifact_id`, cesta, Git blob, SHA-256 a skutečné bajty se před autorizací i
před dispatch znovu porovnají. V1 nepovoluje dynamický glob, síťový zdroj,
nepřipnutý `HEAD` ani materializaci bez úplného receiptu. Pozdější vazba na
výstup jiného kroku musí použít typed port a receipt z ADR 0030, nikoli cestu.

## Prostředí a runtime binding

Přenositelné prostředí tvoří `Project.toml` a právě jeden manifest vybraný při
přípravě requestu. Julia dokumentace označuje manifest za přesný záznam
přímých i nepřímých závislostí; Pkg jej spravuje a nemá se ručně přepisovat.
Pokud existuje `Manifest-v{major}.{minor}.toml`, může být vybrán, ale runner po
vytvoření requestu nesmí přepnout na obecný `Manifest.toml` ani na jinou verzi.
Kontroluje `julia_version`, `manifest_format`, `project_hash`, všechny path/git
dependency a odmítá chybějící nebo stale pár.

Runtime není součástí projektového Gitu ani automaticky `.deb` balíku. V prvním
PoC jej správce uzlu nainstaluje jako node-managed oficiální binární distribuci
a runtime inventory jej připne přesnou verzí a SHA-256. Automaticky se
aktualizující Juliaup channel, systémový balík bez doložené shody a pohyblivý
`julia` z `PATH` nejsou run binding. Aktualizace vytvoří nový binding/revizi;
staré run recordy se nepřepisují.

Výchozí reviewovaný profil pro `COMP-02` je Julia **1.10.12 LTS** na Linux
glibc x86-64 (upstream Tier 1) a ARMv8/aarch64 (Tier 2), vždy jen tam, kde je
dostupný ověřený oficiální archiv. Současná stable 1.13.x může později získat
samostatný profil, není implicitním fallbackem. Windows, macOS, musl, GPU a
distribuované worker procesy jsou mimo první PoC. Tento seznam je časově
citlivý a před každou distribuční změnou se znovu ověří proti upstream support
matrix a release feedu.

Julia je pod MIT licencí, ale sama odkazuje na samostatné third-party licence.
Každé budoucí přibalení runtime, depotů, registrů, balíčků nebo artefaktů proto
vyžaduje úplný SBOM/licenční inventář a přenesení příslušných notices. Toto ADR
redistribuci neschvaluje. První PoC používá node-managed instalaci; ani ta
neobchází kontrolu licencí balíčků použitých projektem.

## Offline depot a příprava prostředí

Příprava prostředí je samostatná explicitní administrativní operace. Smí mít
síť pouze podle vlastní policy a musí zaznamenat zdroj registru, package tree a
artifact hashe, licence, Julia verzi/platformu a hash výsledného připraveného
depotu. Selhání přípravy nevytvoří spustitelné prostředí.

Samotný výpočet nikdy nespouští `Pkg.add`, `Pkg.update`, resolution ani síťové
`instantiate`. Dostane nový privátní zapisovatelný overlay depot a připnutý
read-only připravený depot; `JULIA_DEPOT_PATH` se sestaví bez prázdných prvků,
protože ty by rozšířily cestu o výchozí depot. `JULIA_LOAD_PATH` obsahuje pouze
aktivní projekt a stdlib. Dále se nastaví `JULIA_PKG_OFFLINE=true`, ale jde jen
o defense in depth: oficiální Pkg dokumentace říká, že offline režim se snaží
pracovat bez připojení, nikoli že síť bezpečnostně zakazuje. Autoritativní zákaz
sítě musí vynutit OS izolace a při její nedostupnosti se run odmítne.

Runner nepřebírá uživatelský `HOME`, depot, startup ani history. Julia se
spouští bez shellu s přesným executable a minimálně s `--project=<snapshot>`,
`--startup-file=no`, `--history-file=no`, pevným `--threads=N`, oddělovačem
`--` a připnutým entrypointem. V1 zakazuje `-p`, `--machine-file`, libovolný
`--sysimage` a uživatelské CLI přepínače. Pracovní adresář, temp, HOME-like
runtime adresář, overlay depot i staging jsou privátní a operation-scoped.

## Run request, stavy a evidence

Node-local request `fpw-julia-run-v1` váže:

- `operation_id`, `run_id`, project ID a přesný project commit;
- computation ID a SHA-256 kanonické definice;
- přesné artifact/blob/content hashe entrypointu a všech vstupů;
- kanonické parametry a hash;
- Project/Manifest cesty, hashe a zjištěné hlavičky manifestu;
- runtime binding ID/revizi, Julia patch verzi, executable/distribution/sysimage
  hashe a platform fingerprint;
- execution policy, efektivní privacy, autorizujícího aktéra, časy a approval
  digest nad previewem přesných vstupů a lokálního účinku;
- volitelný seed; jeho přítomnost neslibuje bitovou reprodukovatelnost.

Platform fingerprint zahrnuje OS, architekturu, libc, Julia build commit,
CPU target/features, počet vláken, BLAS/LAPACK vendor a verzi a všechny další
akcelerátory použité během runu. Cache key zahrne celý request kromě operation
identity, včetně platformy a limitů. Shodný seed, zdroje a manifest samy
neznamenají shodné floating-point bajty napříč platformami. Doménové tolerance
nebo invarianty musí deklarovat a ověřit konkrétní model; obecný runner je
nevymýšlí.

Stavy jsou `prepared`, `authorized`, `dispatching`, `succeeded`, `failed`,
`cancel_requested`, `cancelled` a `unknown`. `dispatching` se durable zapíše
před vytvořením procesu. Známé odmítnutí před vznikem procesu může skončit
`failed`; po úspěšném signálu ukončení je `cancelled`. Timeout odešle omezenou
sekvenci ukončení, ale bez potvrzeného zániku celé procesní skupiny zůstává
`unknown`. Pád hosta nebo runneru po dispatch bez úplného validního receiptu je
také `unknown` a stejný run se automaticky neopakuje.

Julia run journal není LLM run store. Nemá model/provider/token/cost pole a
LLM telemetrie se z něj neodvozuje. Společné jsou jen obecné operation ID,
privacy, provenance a `unknown` princip.

## Izolace a limity

Julia kód je nedůvěryhodný nativní proces. CLI přepínač, pracovní adresář,
`Pkg.offline`, kontejner ani LXC samy nejsou bezpečnostní důkaz. `COMP-02` musí
na každé podporované platformě prokázat fail-closed enforcement:

- žádná síť a žádné zděděné sockety;
- read-only snapshot modelu, vstupů, prostředí a připraveného depotu;
- zápis pouze do operation-scoped temp, overlay depot a stagingu;
- vyčištěné prostředí bez credentials, agent socketů a host secrets;
- omezení wall time, CPU/thread/process count, paměti, file size/count,
  stdout/stderr a celého procesního stromu;
- zákaz symlinků, device/socket/FIFO výstupů, úniku cest a setuid/capability;
- potvrzené ukončení celé procesní skupiny při cancel/timeout.

Limit, který cílový OS neumí spolehlivě vynutit, není advisory: profil se
označí unsupported a run se nespustí. V1 nepovoluje síť ani externí side
effect. Pozdější síťový computation profil by potřeboval samostatné ADR,
Context Manifest, endpoint allowlist a recovery neurčitého externího účinku.

## Výstupní protokol a atomická materializace

Entrypoint dostane cestu k read-only kanonickému request JSON a k prázdnému
staging adresáři. Po skončení musí existovat právě jeden bounded
`fpw-julia-result-v1.json`, který pro každý deklarovaný výstup uvádí jméno,
kind, media type, relativní cestu, velikost a SHA-256. Stdout/stderr jsou
bounded diagnostika v run recordu, nikdy implicitní výsledek.

Runner odmítne chybějící/extra required výstup, překročení limitu, absolutní či
unikající cestu, symlink/hardlink mimo generaci, special file, změnu během
hashování, neplatný media-type kontrakt nebo neúplný manifest. Úspěšný exit code
bez validního výsledku je `failed`, ne `succeeded`.

Validní staging se fsyncne a atomicky zveřejní jako immutable soukromá generace
podle ADR 0018/0030. Run journal poté uloží receipt s request, manifest a output
hashi. Pád před rename zachová poslední úplnou generaci a staging lze uklidit.
Pád po rename před receiptem smí reconciliation převzít pouze generaci, jejíž
operation/run ID a všechny hashe přesně odpovídají durable requestu; jinak run
zůstává `unknown`. `failed`, `cancelled` a `unknown` generace se nevydávají za
poslední úspěšný výsledek.

UI může ukázat poslední úspěšnou generaci jen s jejím commitem, runtime a
stavem `stale`, pokud se změnil HEAD, definice, vstup, parametr, prostředí,
runtime/platforma, policy nebo oprávnění. Chybějící cache se přepočítá novým
vědomým runem; neopravuje se v Gitu.

## Privacy a explicitní publikace

Efektivní privacy runu a všech výstupů je nejpřísnější privacy definice,
entrypointu a vstupů. Oprávnění i skutečné bajty se revalidují před approval a
dispatch. Revokace po dokončení zablokuje zobrazení cache; samotný receipt se
zachová podle auditní policy bez zpřístupnění výstupu.

Publikace je nový `operation_id`, nikoli stav Julia runu. Uživatel vybere
konkrétní validní výstup a preview ukáže jeho hash, media type, privacy,
zdrojový run, model, parametry, runtime/platformu a přesný project HEAD.
Workspace znovu ověří oprávnění, receipt, bajty a expected HEAD a teprve potom
vytvoří nový artifact ID s provenance. Pád a retry se řídí Workspace journalem;
run journal ani cache nesmějí zapisovat Git. Publikace nikdy automaticky
nesnižuje privacy a nesmaže lokální generaci.

## Scénáře a rozhodnuté výsledky

| Scénář | Výsledek |
| --- | --- |
| HEAD, definice, vstup nebo prostředí se změnily před dispatch | odmítnout jako `stale`; nový request a approval |
| Manifest chybí, neodpovídá Projectu/runtime nebo balíček/artifact není v připraveném depotu | `failed` před dispatch procesu; bez sítě a fallbacku |
| Kód nebo Pkg zkusí síť | OS deny; run `failed`, při neprokazatelném stavu `unknown` |
| Timeout nebo cancel | ukončit celý procesní strom; `cancelled` jen po potvrzení, jinak `unknown` |
| Pád po dispatch | převzít jen úplnou hashově shodnou generaci, jinak `unknown`; bez auto-retry |
| Výstup je neúplný, extra, nadlimitní nebo nebezpečný typ souboru | `failed`; generaci nezveřejnit |
| Vstupní oprávnění je revokováno | dispatch/pohled/publikaci odmítnout; cache není autorita přístupu |
| Stejný model na jiné platformě/runtime | jiný cache key a nový run; žádný příslib bitové shody |
| Publikace narazí na nový HEAD nebo pád | Workspace konflikt/recovery; Julia run zůstává beze změny |

## Reuse a odmítnuté varianty

Reuse/adaptují se validovaný Git snapshot a artifact ID/hash kontroly,
Context Manifest/approval/`unknown` princip z ADR 0008, atomické generace z
ADR 0018, typed output a receipt hranice z ADR 0030 a jediný Workspace writer.
Julia run dostane vlastní malý node-local journal, protože LLM run, output
router execution ani Workspace journal nemají stejný procesní a recovery
kontrakt.

Odmítá se shell command v projektové konfiguraci, host `PATH`, uživatelský
depot/startup, automatický `Pkg.instantiate` při runu, síťový fallback,
Docker/LXC jako nedoložené synonymum sandboxu, ukládání cache do projektového
Gitu, automatická publikace, použití LLM run tabulky a přibalení Julia runtime
bez distribuční/licenční inventury.

Soukromá reuse inventura neposkytla komponentu se shodným připnutým Julia
prostředím, offline depotem, durable `unknown`, atomickou materializací a
Workspace publikací; nepřebírá se z ní kód ani neveřejné názvy.

## Ověřené veřejné podklady a otevřená implementační evidence

Ke dni 2026-10-26 byly použity pouze primární podklady:

- [Julia supported versions and platforms](https://julialang.org/downloads/support/)
  pro aktuální LTS/stable řady a support tiers;
- [official manual downloads](https://julialang.org/downloads/manual-downloads/)
  pro oficiální archivy, checksums a doporučení nepoužívat zastaralé
  distribuční balíky;
- [Pkg Project/Manifest contract](https://pkgdocs.julialang.org/dev/toml-files/)
  pro exact environment, versioned manifests a manifest metadata;
- [Julia CLI](https://docs.julialang.org/en/v1/manual/command-line-interface/)
  a [environment variables](https://docs.julialang.org/en/v1/manual/environment-variables/)
  pro project/startup/history/thread/depot hranice;
- [Pkg offline API](https://pkgdocs.julialang.org/v1/api/#Pkg.offline)
  pro omezenou semantiku offline režimu;
- [Julia 1.10.12 LICENSE](https://github.com/JuliaLang/julia/blob/v1.10.12/LICENSE.md)
  pro MIT licenci a povinné samostatné posouzení third-party komponent.

`COMP-02` musí teprve doložit skutečný runtime download/signature/checksum,
licence všech distribuovaných komponent, OS-level izolaci na každé podporované
platformě, limity, atomické fsync/rename, recovery a fyzický výpočet. Toto ADR
není důkazem runtime bezpečnosti ani produkční podpory Julia.
