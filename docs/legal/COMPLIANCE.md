<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Compliance evidence — výchozí záznam

Datum ověření podkladů: **2026-09-10**. Výchozí větev: **develop**.
Ověřený výchozí commit: `84c06ce9b29ba4bdf4cdaa7557c09186f7a6ede5`.
Tento údaj označuje podklady před přidáním této evidence, nikoli budoucí release.

Jde o zavedení evidence a notices pro současné Linux balení, nikoli o dokončený
licenční audit, právní stanovisko nebo označení `production-ready`. Neřeší patenty,
FTO, ochranné známky, GDPR ani AI Act. Ty zůstávají v oddělených existujících evidencích.
Tento dokument je podklad k existujícím release gates, ne další produktová roadmapa.

## Closure review 2026-09-13

Review target: commit `128928e9fe88f9e353a22ca8bdd0db3922126301`, current
Linux source archive and unbundled `.deb` distribution model. Reference runtime evidence
was collected on Ubuntu 26.04.1 LTS (arm64). This closure supersedes the gate states in
the older baseline table below for this reviewed scope; the baseline text is retained as
historical context.

**Pre-release compliance verdict: GO WITH CONDITIONS.** No known licensing blocker was
identified for continued development or for preparing a release candidate under the
reviewed unbundled model. The remaining condition is release-specific evidence (CE-01):
a real release branch/tag/version and final artifact hashes do not exist yet by design.

| ID | Closure state | Evidence / boundary |
| --- | --- | --- |
| CE-01 | OPEN — release-only | The audit build is bound to commit `128928e9...`, but a final release version/tag and final artifact hashes must be created from the release branch. |
| CE-02 | PASS for reviewed reference profile | Runtime/provider inventory recorded Python 3.14.4, PyYAML/LibYAML, PySide/Shiboken 6.10.2, Qt/WebEngine 6.10.2, Chromium 134.0.6998.208, SQLite, Git, Poppler and actual shell/coreutils providers. Package copyright evidence was hash-checked. The 356-package conservative OS graph is evidence, not application payload or a claim of a complete SBOM. |
| CE-03 | PASS for reviewed replacement scenario | A modified compatible Shiboken 6.10.2 library built from matching Ubuntu source was substituted while the audit application remained unchanged; the isolated runtime smoke test passed. No About/license UI is present in the reviewed desktop, so UI notice placement is N/A; notices are delivered as files. |
| CE-04 | PASS for audit baseline | Source and `.deb` artifacts were bound to the audited Git tree and hashes; manifests/notices were checked. The verification batch reported 148 PASS and 5 BLOCKED; the four libgit2 checks and the CE-03 replacement check were then rerun with their required inputs and reported PASS, with no reported FAIL. Re-run the release-relevant profile on the final release commit. |
| CE-05 | PASS for current distributed set | The current source builder selects 100 UTF-8 source/document/license files (plus generated manifest), with no binary assets or vendored dependency tree. Project files carry SPDX metadata; intentional third-party license texts retain upstream ownership. Historical planning material is classified as project-originated/AI-assisted. |
| CE-06 | N/A for current unbundled model | Reopen before shipping a bundled Python/Qt/Chromium runtime, AppImage/container/standalone image, copied virtualenv/wheels, external assets, model weights or other new third-party payload. |

CE-02 and CE-05 are closure decisions for the reviewed distribution scope, not an
assertion that every package installed on the operating system is part of the workspace
or that a plagiarism/similarity scan was performed. A material change in dependencies,
modules, bundling, reused code/assets or supported runtime profile reopens the affected
gate.

## Co je doloženo a co nikoli

Z repozitáře byly načteny aktuální branch metadata, dotčené build skripty a jejich
testy, záznamy o runtime a relevantní části implementace. Výchozí obsahy
`scripts/package_deb.py` a `scripts/package_desktop.py` použité pro patch byly
porovnány s Git blob SHA dodanými GitHubem. Text PyYAML licence byl načten přímo
z tagu 6.0.3 a jeho blob SHA byl rovněž ověřen. Přesné zdroje obsahuje
[LICENSE_SOURCES.md](LICENSE_SOURCES.md).

Předchozí souhrnné hodnocení typu „vlastní soubory PASS“ se samo o sobě nepovažuje
za audit autorství každého souboru. SPDX je deklarace, ne důkaz původu. V původní
baseline nebyl proveden provenance review distribuovaného setu, úplný tranzitivní
inventář ani kontrola skutečného release kandidáta. Pozdější closure review výše
doplňuje provenance a runtime evidence pro auditovaný rozsah; nejde o globální
podobnostní scan ani o důkaz obsahu budoucího releasu.

Schválení PyYAML MIT v `REUSE_CATALOG.md` se zachovává jako schválení licenčního
směru. Neznamená bezpečnostní audit, schválení libovolného wheelu ani automatické
schválení všech jeho přibalených komponent.

## Evidence komponent

[DEPENDENCIES.toml](DEPENDENCIES.toml) odděluje:

- vlastní zdroje v balíku;
- knihovny načítané v procesu a poskytované systémem;
- samostatně spouštěné systémové programy;
- build/test nástroje a volitelné experimenty.

Pole `license_evidence` a `release_status` se nesmějí zaměňovat. Identifikovaná
licence není sama o sobě splněním distribučních povinností. Stav `not_bundled`
popisuje pouze současné build skripty; není to univerzální právní výjimka.
Záměrně nejde o CycloneDX/SPDX SBOM ani o vyřešený tranzitivní dependency graph.

## Dodávané notices a licence

Uživatelský vstup je [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
Zachovává MPL vlastního kódu a cizí autorská označení, popisuje systémové závislosti,
LGPL cestu pro Qt/PySide, samostatný Chromium kontext a LibYAML jako podmíněnou závislost.

Přiloženy jsou úplné texty GPLv3 a LGPLv3 a původní MIT notice PyYAML 6.0.3.
Texty licencí nejsou přeznačené na MPL a nedostávají copyright autora workspace.
Jsou uložené jako `COPYING.*` / `LICENSE.*`, mimo `LICENSES/` určený pro licence
vlastních covered files podle REUSE. Pouhá přítomnost těchto textů nemění licenci aplikace.

Systémové dynamické knihovny neznamenají „žádné LGPL povinnosti“. Tento balíček
proto přidává upozornění, oba licenční texty a [postup výměny knihoven](RELINKING.md).
Před releasem je potřeba prokázat zamýšlenou cestu podle LGPL 4(d)(1), ne jen
konstatovat, že závislost není přibalená. Pokud UI zobrazuje autorská oznámení,
posoudit také LGPL 4(c) a doplnit příslušné knihovní oznámení a odkaz na licence.

## Napojení na balíčky

`scripts/license_files.py` obsahuje jediný explicitní seznam povinných distribuovaných
licenčních podkladů. Oba současné desktop build skripty jej používají. Chybějící,
prázdný nebo symlinkovaný podklad build odmítne; soukromé release evidence a libovolné
nové soubory z `docs/legal/` se automaticky nepřebírají.

Zdrojový archiv zahrnuje tyto soubory do existujícího SHA-256 manifestu. `.deb` je
instaluje pod `/usr/share/doc/federated-workspace-poc/` se zachováním relativních cest.
Opraven je též odkaz Homepage na skutečné jméno vlastníka repozitáře. Závislosti,
verze aplikace, runtime a funkční kód se tímto patchem nemění. Omnia deploy a jiné
než tyto dva distribuční kanály nejsou tímto patchem schválené ani změněné.

## Otevřené podmínky před veřejným releasem

| ID | Požadovaný důkaz | Stav této baseline |
| --- | --- | --- |
| CE-01 | Přesný release commit, tag, platforma, verze a hashe všech artefaktů; vazba source archive ↔ instalátor | OPEN |
| CE-02 | Inventář skutečných OS/pip balíků, poskytovatelů, tranzitivních knihoven a jejich copyright/source údajů | OPEN |
| CE-03 | Výměna kompatibilní modifikované PySide/Qt knihovny a smoke test; kontrola oznámení v případném About UI | OPEN |
| CE-04 | Úplná současná testovací sada, skutečné buildy, rozbalení obou formátů a kontrola notices na cílovém systému | OPEN |
| CE-05 | Kontrola provenance všech distribuovaných zdrojů/assetů včetně historického reuse a chybějících SPDX údajů | OPEN |
| CE-06 | Při bundlování nový inventář, plné third-party notices a splnění zdrojových/relinking/installation povinností | N/A jen pro současný nebundlovaný model; znovu otevřít při změně |

Tyto evidence nemají měnit priority M1. Při integraci zaznamenat ad-hoc práci do
aktuálního TODO podle AGENTS.md a navázat ji na existující release gate.
Za uzavření konkrétního releasu odpovídá vydavatel; neoznačovat celý Qt, Git nebo OS
stack jako produkčně schválený na základě této tabulky.

## Jak vytvořit důkaz konkrétního releasu

Použít čistý checkout vybraného commitu v samostatném build prostředí. Před buildem
zaznamenat `git rev-parse HEAD` a stav pracovního stromu. SHA přiřazená existujícímu
artefaktu dodatečně bez průkazného buildu nejsou důkazem jeho původu.

Spustit úplnou současnou sadu `python3 -m unittest discover -s tests -v` a relevantní
existující smoke testy. Pak z téhož čistého checkoutu vytvořit source archive i `.deb`.
Uložit SHA-256, výstup `dpkg-deb --info`, `dpkg-deb --contents`, seznam členů archivu
a zkontrolovat `MANIFEST.sha256.json`. Balíčky lze rozbalit bez instalace; samotná
kontrola souborů však nenahrazuje ověření aplikace na podporovaném systému.

Na čistém cílovém Debian/Ubuntu systému zaznamenat alespoň přímé balíky:

```sh
dpkg-query -W -f='${binary:Package}	${Version}	${Architecture}	${source:Package}	${source:Version}
' \
  python3 python3-yaml python3-pyside6.qtwebenginewidgets git coreutils poppler-utils
```

Toto je **pouze výchozí seznam**, ne tranzitivní uzávěr. Doplnit skutečné balíky pro
importované moduly PySide6, Shiboken, Qt, WebEngine, načtené plugins a LibYAML,
stejně jako poskytovatele `readlink`, `dirname`, `pdftoppm` a Git. Zjistit je z
cest skutečně načtených/spouštěných souborů, `dpkg-query -S` a dependency metadat;
řešit alternativní/virtuální balíky podle skutečně zvolené implementace. Nelze
převzít GNU licenci pro každý balík pojmenovaný `coreutils` bez této kontroly.

Pro každý použitý balík archivovat skutečný copyright text a soubory, na které
odkazuje, jeho hash, upstream a source-package verzi. Pro pip uložit přesné artefakty
(wheel/sdist), jejich hashe, METADATA a přibalené license soubory. Nestahovat libovolné
nejnovější verze místo verzí použitých v releasu. Přibalený LibYAML nebo Qt runtime
mění rozsah povinností, i když nebyl explicitní položkou requirements.

Evidenci připravovat mimo distribuční allowlist a před publikací odstranit uživatelská
jména, soukromé cesty, interní URL, tokeny či jiné neveřejné údaje. Nezveřejňovat
celý seznam nesouvisejícího software na osobním stroji.

## Minimální release záznam

```yaml
schema_version: 1
status: open
release_version: null
release_commit: null
release_tag: null
build_platform: null
source_archive_sha256: null
deb_sha256: null
runtime_inventory_file: null
runtime_inventory_scope: null
notices_hashes_file: null
source_availability_evidence: null
lgpl_replacement_test: null
full_test_result: null
provenance_review: null
reviewed_by: null
reviewed_at: null
unresolved_findings: []  # prázdný seznam není automaticky PASS
```

Neznámá pole ponechat explicitně neověřená. Pokud artefakt obsahuje něco mimo tento
model (například kontejnerový OS image, fonty, jiný editor, LLM váhy nebo nástroj
převzatý z cizího repozitáře), evidence se musí rozšířit před schválením releasu.

## Ověření počáteční změny

Při přípravě prošlo 10 nových izolovaných testů v
`tests/test_license_packaging.py`: registry a hashe licencí, zdrojový manifest a
reprodukovatelnost, obsah skutečně sestaveného testovacího `.deb`, zákaz přepsání
výstupu, nepřibalení soukromé evidence, odmítnutí chybějících/prázdných/symlinkovaných
podkladů a spuštění obou skriptů z jiného pracovního adresáře.

Byl použit syntetický strom s hashově ověřenými původními build skripty a skutečnými
novými licenčními podklady. Testovací `.deb` obsahoval zástupné aplikační soubory;
nešlo o produkční build workspace. Úplný checkout, celá současná testovací sada,
Qt smoke test, výměna knihovny ani cílová instalace v této přípravě ověřeny nebyly.
Po aplikaci patche spustit vše relevantní v plném repozitáři a výsledek zapsat do TODO.
