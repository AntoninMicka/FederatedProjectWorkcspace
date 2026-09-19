<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-META-AI-01: Návrhy popisu a štítků

Milník M2; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-META-AI-01 — Návrhy popisu a štítků

- Stav: [ ] [in progress]; cílová úroveň PoC validated.
- Původ: roadmapa M2 „Auto-description“ a „Tagging“; navazuje na F-M2-SUMMARY-01 a F-M2-EXTRACT-01 začleněné PR #31 a #32.
- Skutečná větev: `feature/f-m2-meta-ai-01-metadata-suggestions`, založená z `develop` (`0f085e3`); jediný budoucí PR do `develop`.
- Výstup: lokální LLM navrhne pro jeden explicitně vybraný artefakt popis a štítky, zobrazí přesný rozdíl proti aktuálním metadatům a teprve po uživatelově volbě polí provede jediný obnovitelný metadata commit.
- Mimo rozsah: background/index-wide generování, automatické přepisování metadat, změna title/privacy/provenance, externí provider, RAG/embeddings a automatická publikace.
- Recovery: LLM task/preview a projektový metadata zápis jsou oddělené; `unknown` se neopakuje, potvrzení váže preview hash, původní HEAD i původní metadata a stejné task/operation ID nesmí vytvořit druhý návrh ani commit.
- Akceptace: přesný artifact/HEAD/privacy/cíl v manifestu; striktní bounded návrh; diff se zachováním ručních hodnot; volitelné potvrzení popisu a štítků; prázdné/duplicitní/nevhodné štítky a limity; stale HEAD, restart/retry a pády před/po publikaci; bezpečné desktopové vykreslení.

- [x] [completed] **F-M2-META-AI-01-A — Kontrakt návrhu, potvrzení a reuse review (designed, 2026-09-19).** ADR 0008 uzavírá request a `metadata-suggestions-v1`, limity a casefold unikátnost, vazbu obsahu i původních metadat, samostatné potvrzení popisu a aditivních tagů, zákaz automatického mazání či změny privacy/provenance a oddělené síťové/task/Workspace crash boundaries. Reuse katalog adaptuje Context Builder, Ollama, extractor task preview, metadata validaci a Workspace; přímé použití editoru ani nová závislost nejsou vhodné.
- [x] [completed] **F-M2-META-AI-01-B — Durable lokální návrh a validovaný diff (implemented, 2026-09-19).** Same-node role `metadata-advisor-v1` přidává serverem kanonizovaný metadata snapshot jako manifestovaný vstup se stejnou privacy, používá vlastní durable task store a striktně validuje `metadata-suggestions-v1`. Preview vrací původní hodnoty a přesný diff bez Git zápisu; restart neopakuje úspěšný dispatch a invalidní/`unknown` výsledek se nevydává jako návrh. Cílené backendové testy a kompletní sada 277 testů prošly, 22 podmíněných testů bylo přeskočeno; závěrečnou UI/publikační akceptaci dávky provede úkol C.
- [ ] [in progress] **F-M2-META-AI-01-C — Potvrzený metadata zápis, desktop UI a akceptace (cílová úroveň: PoC validated).** Přidat bezpečný diff, výběr polí, jediný Workspace commit, recovery a chybové testy.

### Následující dávka po samostatném merge

- `F-UX-SETTINGS-01` — centralizovaná stránka nastavení.
